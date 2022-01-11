#!/usr/bin/env python3
# Copyright 2020 Canonical Ltd.
# See LICENSE file for licensing details.

"""A Juju charm for Prometheus on Kubernetes."""

import logging
import os
import re

import yaml
from charms.alertmanager_k8s.v0.alertmanager_dispatch import AlertmanagerConsumer
from charms.grafana_k8s.v0.grafana_source import GrafanaSourceConsumer
from charms.istio_pilot.v0.ingress import IngressRequirer
from charms.observability_libs.v0.kubernetes_service_patch import KubernetesServicePatch
from charms.prometheus_k8s.v0.prometheus_remote_write import (
    PrometheusRemoteWriteProvider,
)
from charms.prometheus_k8s.v0.prometheus_scrape import MetricsEndpointConsumer
from ops.charm import CharmBase
from ops.main import main
from ops.model import ActiveStatus, BlockedStatus, WaitingStatus
from ops.pebble import Layer

from prometheus_server import Prometheus

PROMETHEUS_CONFIG = "/etc/prometheus/prometheus.yml"
RULES_DIR = "/etc/prometheus/rules"

INGRESS_MULTIPLE_UNITS_STATUS_MESSAGE = (
    "invalid combination of 'ingress', 'receive-remote-write' relations and multiple units"
)

logger = logging.getLogger(__name__)


class PrometheusCharm(CharmBase):
    """A Juju Charm for Prometheus."""

    def __init__(self, *args):
        super().__init__(*args)

        self._name = "prometheus"
        self._port = 9090
        self._prometheus_server = Prometheus()

        self.service_patch = KubernetesServicePatch(self, [(f"{self.app.name}", self._port)])

        # Relation handler objects

        # Allows Grafana to aggregate metrics
        self.grafana_source_consumer = GrafanaSourceConsumer(
            charm=self,
            name="grafana-source",
            refresh_event=self.on.prometheus_pebble_ready,
        )

        # Gathers scrape job information from metrics endpoints
        self.metrics_consumer = MetricsEndpointConsumer(self)

        # Exposes remote write endpoints
        self.remote_write_provider = PrometheusRemoteWriteProvider(
            self,
            relation_name="receive-remote-write",
            endpoint_address=self._remote_write_address,
            endpoint_port=self._port,
        )

        # Maintains list of Alertmanagers to which alerts are forwarded
        self.alertmanager_consumer = AlertmanagerConsumer(self, relation_name="alertmanager")

        # Manages ingress for this charm
        self.ingress = IngressRequirer(
            self,
            port = self._port,
            per_unit_routes = True,
        )

        # Event handlers
        self.framework.observe(self.on.prometheus_pebble_ready, self._configure)
        self.framework.observe(self.on.config_changed, self._configure)
        self.framework.observe(self.on.upgrade_charm, self._configure)
        self.framework.observe(self.ingress.on.ready, self._configure)
        self.framework.observe(self.ingress.on.removed, self._configure)
        self.framework.observe(self.on.receive_remote_write_relation_created, self._configure)
        self.framework.observe(self.on.receive_remote_write_relation_broken, self._configure)
        self.framework.observe(self.on.prometheus_peers_relation_joined, self._configure)
        self.framework.observe(self.on.prometheus_peers_relation_departed, self._configure)
        self.framework.observe(self.metrics_consumer.on.targets_changed, self._configure)
        self.framework.observe(self.alertmanager_consumer.on.cluster_changed, self._configure)

        if relations := self.model.relations["metrics-endpoint"]:
            app_data_bag = relations[0].data[self.app]
            if self.unit.is_leader():
                app_data_bag["test"] = "OK"
            else:
                print(f"Check if we can read the own app data bag: {app_data_bag['test']}")

    def _on_upgrade_charm(self, event):
        """Handler for the upgrade_charm event during which will update the K8s service."""
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

        if not container.can_connect():
            self.unit.status = WaitingStatus("Waiting for Pebble ready")
            return

        # push Prometheus config file to workload
        prometheus_config = self._prometheus_config()
        container.push(PROMETHEUS_CONFIG, prometheus_config)
        logger.info("Pushed new configuration")

        # push alert rules if any
        self._set_alerts(container)

        current_services = container.get_plan().services
        new_layer = self._prometheus_layer

        ### TODO
        # Fix this: updating the command args in manual tests did not result
        # in Prometheus restarting!

        # # Restart prometheus only if command line arguments have changed,
        # # otherwise just reload its configuration.
        # if current_services == new_layer.services:
        #     reloaded = self._prometheus_server.reload_configuration()
        #     if not reloaded:
        #         self.unit.status = BlockedStatus("Failed to load Prometheus config")
        #         return
        #     logger.info("Prometheus configuration reloaded")
        # else:
        #     container.add_layer(self._name, new_layer, combine=True)
        #     container.restart(self._name)
        #     logger.info("Prometheus (re)started")

        container.add_layer(self._name, new_layer, combine=True)
        container.restart(self._name)
        logger.info("Prometheus (re)started")

        ### END TODO

        # Ensure the right address is set on the remote_write relations
        self.remote_write_provider.update_endpoint()

        self.unit.status = ActiveStatus()

    def _set_alerts(self, container):
        """Create alert rule files for all Prometheus consumers.

        Args:
            container: the Prometheus workload container into which
                alert rule files need to be created. This container
                must be in a pebble ready state.
        """
        container.remove_path(RULES_DIR, recursive=True)

        self._push_alert_rules_group(container, self.metrics_consumer.alerts())
        self._push_alert_rules_group(container, self.remote_write_provider.alerts())

    def _push_alert_rules_group(self, container, alerts):
        for group_name, group in alerts.items():
            filename = "juju_" + group_name + ".rules"
            path = os.path.join(RULES_DIR, filename)
            rules = yaml.dump(group)

            container.push(path, rules, make_dirs=True)
            logger.debug("Updated alert rules file %s", filename)

    def _command(self) -> str:
        """Construct command to launch Prometheus.

        Returns:
            a string consisting of Prometheus command and associated
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
            if unit_external_url := self.ingress.unit_url:
                logger.debug(f"Setting external web URL to ingress-provided '{unit_external_url}'")
                args.append(f"--web.external-url={unit_external_url}")

        # enable remote write if an instance of the relation exists
        if self.model.relations["receive-remote-write"]:
            args.append("--enable-feature=remote-write-receiver")

        # get log level
        allowed_log_levels = ["debug", "info", "warn", "error", "fatal"]
        log_level = config["log_level"].lower()

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
        if config.get("metrics_wal_compression"):
            args.append("--storage.tsdb.wal-compression")

        # Set time series retention time
        if config.get("metrics_retention_time") and self._is_valid_timespec(
            config["metrics_retention_time"]
        ):
            args.append(f"--storage.tsdb.retention.time={config['metrics_retention_time']}")

        command = ["/bin/prometheus"] + args

        return " ".join(command)

    def _is_valid_timespec(self, timeval) -> bool:
        """Is a time interval unit and value valid.

        If time interval is not valid unit status is set to blocked.

        Args:
            timeval: a string representing a time specification.

        Returns:
            True if time specification is valid and False otherwise.
        """
        if not (matched := re.match(r"[1-9][0-9]*[ymwdhs]", timeval)):
            self.unit.status = BlockedStatus(f"Invalid time spec : {timeval}")

        return matched

    def _prometheus_global_config(self) -> dict:
        """Construct Prometheus global configuration.

        Returns:
            a dictionary consisting of global configuration for Prometheus.
        """
        config = self.model.config
        global_config = {"scrape_interval": "1m", "scrape_timeout": "10s"}

        if config.get("evaluation_interval") and self._is_valid_timespec(
            config["evaluation_interval"]
        ):
            global_config["evaluation_interval"] = config["evaluation_interval"]

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

    def _prometheus_config(self) -> str:
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
            "static_configs": [{"targets": [f"localhost:{self._port}"]}],
        }
        prometheus_config["scrape_configs"].append(default_config)
        scrape_jobs = self.metrics_consumer.jobs()
        for job in scrape_jobs:
            prometheus_config["scrape_configs"].append(job)

        return yaml.dump(prometheus_config)

    @property
    def _prometheus_layer(self) -> Layer:
        """Construct the pebble layer.

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

    @property
    def _external_hostname(self) -> str:
        """Return the external hostname to be passed to ingress via the relation."""
        # It is recommended to default to `self.app.name` so that the external
        # hostname will correspond to the deployed application name in the
        # model, but allow it to be set to something specific via config.

        return self.config["web_external_url"] or f"{self.app.name}"

    @property
    def _remote_write_address(self) -> str:
        return self._external_hostname if self.model.get_relation("ingress") else None


if __name__ == "__main__":
    main(PrometheusCharm)
