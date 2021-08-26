#!/usr/bin/env python3
# Copyright 2020 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
import os
import re
import yaml

from kubernetes_service import K8sServicePatch, PatchFailed

from ops.charm import CharmBase
from ops.framework import StoredState
from ops.main import main
from ops.model import ActiveStatus, BlockedStatus
from ops.pebble import ConnectionError, Layer
from prometheus_server import Prometheus
from charms.grafana_k8s.v1.grafana_source import GrafanaSourceConsumer
from charms.nginx_ingress_integrator.v0.ingress import IngressRequires
from charms.prometheus_k8s.v0.prometheus import MetricsEndpointConsumer
from charms.alertmanager_k8s.v0.alertmanager import AlertmanagerConsumer

PROMETHEUS_CONFIG = "/etc/prometheus/prometheus.yml"
RULES_DIR = "/etc/prometheus/rules"

logger = logging.getLogger(__name__)


class PrometheusCharm(CharmBase):
    """A Juju Charm for Prometheus."""

    _stored = StoredState()

    def __init__(self, *args):
        super().__init__(*args)

        self._name = "prometheus"
        self._prometheus_server = Prometheus("localhost", str(self.port))

        self._stored.set_default(
            k8s_service_patched=False,
        )

        # Relation handler objects

        # Allows Grafana to aggregate metrics
        self.grafana_source_consumer = GrafanaSourceConsumer(
            charm=self,
            name="grafana-source",
            consumes={"Grafana": ">=2.0.0"},
            refresh_event=self.on.prometheus_pebble_ready,
        )

        # Gathers scrape job information from metrics endpoints
        self.metrics_consumer = MetricsEndpointConsumer(self, "metrics-endpoint")

        # Maintains list of Alertmanagers to which alerts are forwarded
        self.alertmanager_consumer = AlertmanagerConsumer(
            self, relation_name="alertmanager", consumes={"alertmanager": ">=0.21.0"}
        )

        # Manages ingress for this charm
        self.ingress = IngressRequires(
            self,
            {
                "service-hostname": self._external_hostname,
                "service-name": self.app.name,
                "service-port": str(self.port),
            },
        )

        # Event handlers
        self.framework.observe(self.on.install, self._on_install)
        self.framework.observe(self.on.prometheus_pebble_ready, self._configure)
        self.framework.observe(self.on.config_changed, self._configure)
        self.framework.observe(self.on.upgrade_charm, self._configure)
        self.framework.observe(self.on.ingress_relation_joined, self._configure)
        self.framework.observe(self.on.ingress_relation_changed, self._configure)
        self.framework.observe(self.on.ingress_relation_broken, self._configure)
        self.framework.observe(self.metrics_consumer.on.targets_changed, self._configure)
        self.framework.observe(self.alertmanager_consumer.cluster_changed, self._configure)

    def _on_install(self, _):
        """Event handler for the install event during which we will update the K8s service"""
        self._patch_k8s_service()

    def _on_upgrade_charm(self, event):
        """Event handler for the upgrade_charm event during which we will update the K8s service"""
        self._patch_k8s_service()
        self._configure(event)

    def _configure(self, _):
        """Reconfigure and either reload or restart Prometheus.

        In response to any configuration change, such as a new consumer
        relation, or a new configuration set by the administrator, the
        Prometheus config file is regenerated, and pushed to the workload
        container. Prometheus configuration is reloaded if there has
        been no change to the Pebble layer (such as Prometheus command
        line arguments). If the Pebble layer has changed then Prometheus
        is restarted.
        """
        container = self.unit.get_container(self._name)

        if not container.is_ready():
            logger.debug(f"The {self._name} container is not ready")
            return

        # push Prometheus config file to workload
        prometheus_config = self._prometheus_config()
        try:
            container.push(PROMETHEUS_CONFIG, prometheus_config)
            logger.info("Pushed new configuration")
        except ConnectionError:
            logger.info("Ignoring config changes since pebble is not ready")
            return

        self._set_alerts(container)

        current_services = container.get_plan().services
        new_layer = self._prometheus_layer

        # Restart prometheus only if command line arguments have changed,
        # otherwise just reload its configuration.
        if current_services == new_layer.services:
            self._prometheus_server.reload_configuration()
            logger.info("Prometheus configuration reloaded")
        else:
            container.add_layer(self._name, new_layer, combine=True)
            container.restart(self._name)
            logger.info("Prometheus (re)started")

        self.unit.status = ActiveStatus()

    def _set_alerts(self, container):
        """Create alert rule files for all Prometheus consumers.

        Args:
            container: the Prometheus workload container into which
                alert rule files need to be created.
        """
        with container.is_ready():
            logger.debug("Processing alert rules")

            container.remove_path(RULES_DIR, recursive=True)

            for rel_id, alert_rules in self.metrics_consumer.alerts().items():
                filename = "juju_{}_{}_{}_rel_{}_alert.rules".format(
                    alert_rules["model"],
                    alert_rules["model_uuid"],
                    alert_rules["application"],
                    rel_id,
                )

                path = os.path.join(RULES_DIR, filename)
                rules = yaml.dump({"groups": alert_rules["groups"]})
                logger.debug("Rules for relation %s : %s", rel_id, rules)

                container.push(path, rules, make_dirs=True)
                logger.debug("Pushed new alert rules '%s': %s", filename, rules)

            self._prometheus_server.reload_configuration()
            logger.info("Updated alert rules")

    def _command(self) -> str:
        """Construct command to launch Prometheus.

        Returns:
            a sting consisting of Prometheus command and associated
            command line options.
        """
        config = self.model.config
        args = [
            f"--config.file={PROMETHEUS_CONFIG}",
            "--storage.tsdb.path=/var/lib/prometheus",
            "--web.enable-lifecycle",
            "--web.console.templates=/usr/share/prometheus/consoles",
            "--web.console.libraries=/usr/share/prometheus/console_libraries",
        ]

        if self.model.get_relation("ingress"):

            # TODO The ingress should communicate the externally-visible scheme
            external_url = f"http://{self._external_hostname}:{self.port}"

            args.append(f"--web.external-url={external_url}")

        # get log level
        allowed_log_levels = ["debug", "info", "warn", "error", "fatal"]
        log_level = config["log-level"].lower()

        # If log level is invalid set it to debug
        if log_level not in allowed_log_levels:
            logging.error(
                "Invalid loglevel: %s given, %s allowed. defaulting to DEBUG loglevel.",
                log_level,
                "/".join(allowed_log_levels),
            )
            log_level = "debug"

        # set log level
        args.append(f"--log.level={log_level}")

        # Enable time series database compression
        if config.get("metrics-wal-compression"):
            args.append("--storage.tsdb.wal-compression")

        # Set time series retention time
        if config.get("metrics-retention-time") and self._is_valid_timespec(
            config["metrics-retention-time"]
        ):
            args.append(f"--storage.tsdb.retention.time={config['metrics-retention-time']}")

        command = ["/bin/prometheus"]
        command.extend(args)

        return " ".join(command)

    def _is_valid_timespec(self, timeval) -> bool:
        """Is a time interval unit and value valid.

        If time interval is not valid unit status is set to blocked.

        Args:
            timeval: a string representing a time specification.

        Returns:
            True if time specification is valid and False otherwise.
        """
        matched = re.match(r"[1-9][0-9]*[ymwdhs]", timeval) is not None

        if not matched:
            self.unit.status = BlockedStatus(f"Invalid time spec : {timeval}")

        return matched

    def _prometheus_global_config(self) -> dict:
        """Construct Prometheus global configuration.

        Returns:
            a dictionary consisting of global configuration for Prometheus.
        """
        config = self.model.config
        global_config = {}

        if config.get("scrape-interval") and self._is_valid_timespec(config["scrape-interval"]):
            global_config["scrape_interval"] = config["scrape-interval"]

        if config.get("scrape-timeout") and self._is_valid_timespec(config["scrape-timeout"]):
            global_config["scrape_timeout"] = config["scrape-timeout"]

        if config.get("evaluation-interval") and self._is_valid_timespec(
            config["evaluation-interval"]
        ):
            global_config["evaluation_interval"] = config["evaluation-interval"]

        return global_config

    def _alerting_config(self) -> dict:
        """Construct Prometheus altering configuration.

        Returns:
            a dictionary consisting of the alerting configuration for Prometheus.
        """
        alerting_config = {}

        alertmanagers = self.alertmanager_consumer.get_cluster_info()

        if not alertmanagers:
            logger.debug("No alertmanagers available")
            return alerting_config

        alerting_config = {"alertmanagers": [{"static_configs": [{"targets": alertmanagers}]}]}
        return alerting_config

    def _prometheus_config(self) -> dict:
        """Construct Prometheus configuration.

        Returns:
            Prometheus config file in YAML (string) format.
        """
        prometheus_config = {
            "global": self._prometheus_global_config(),
            "rule_files": [os.path.join(RULES_DIR, "juju_*.rules")],
            "scrape_configs": [],
        }

        alerting_config = self._alerting_config()
        if alerting_config:
            prometheus_config["alerting"] = alerting_config

        # By default only monitor prometheus server itself
        default_config = {
            "job_name": "prometheus",
            "scrape_interval": "5s",
            "scrape_timeout": "5s",
            "metrics_path": "/metrics",
            "honor_timestamps": True,
            "scheme": "http",
            "static_configs": [{"targets": [f"localhost:{self.port}"]}],
        }
        prometheus_config["scrape_configs"].append(default_config)
        scrape_jobs = self.metrics_consumer.jobs()
        for job in scrape_jobs:
            prometheus_config["scrape_configs"].append(job)

        return yaml.dump(prometheus_config)

    @property
    def _prometheus_layer(self) -> Layer:
        """Construct the pebble layer

        Returns:
            a Pebble layer specification for the Prometheus workload container.
        """
        logger.debug("Building pebble layer")
        layer_config = {
            "summary": "Prometheus layer",
            "description": "Pebble layer configuration for Prometheus",
            "services": {
                self._name: {
                    "override": "replace",
                    "summary": "prometheus daemon",
                    "command": self._command(),
                    "startup": "enabled",
                }
            },
        }

        return Layer(layer_config)

    def _patch_k8s_service(self):
        """Fix the Kubernetes service that was setup by Juju with correct port numbers"""
        if self.unit.is_leader() and not self._stored.k8s_service_patched:
            service_ports = [
                (f"{self.app.name}", self.port, self.port),
            ]
            try:
                K8sServicePatch.set_ports(self.app.name, service_ports)
            except PatchFailed as e:
                logger.error("Unable to patch the Kubernetes service: %s", str(e))
            else:
                self._stored.k8s_service_patched = True
                logger.info("Successfully patched the Kubernetes service!")

    @property
    def _external_hostname(self) -> str:
        """Return the external hostname to be passed to ingress via the relation."""
        # It is recommended to default to `self.app.name` so that the external
        # hostname will correspond to the deployed application name in the
        # model, but allow it to be set to something specific via config.

        return self.config["web-external-url"] or f"{self.app.name}"

    @property
    def port(self) -> int:
        """Return the configured port for the Prometheus UI and API."""
        return self.model.config["port"]


if __name__ == "__main__":
    main(PrometheusCharm)
