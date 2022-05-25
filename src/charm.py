#!/usr/bin/env python3
# Copyright 2020 Canonical Ltd.
# See LICENSE file for licensing details.

"""A Juju charm for Prometheus on Kubernetes."""

import logging
import os
import re
import socket
from typing import Dict
from urllib.parse import urlparse

import yaml
from charms.alertmanager_k8s.v0.alertmanager_dispatch import AlertmanagerConsumer
from charms.grafana_k8s.v0.grafana_source import GrafanaSourceProvider
from charms.observability_libs.v0.kubernetes_service_patch import KubernetesServicePatch
from charms.prometheus_k8s.v0.prometheus_remote_write import (
    DEFAULT_RELATION_NAME as DEFAULT_REMOTE_WRITE_RELATION_NAME,
)
from charms.prometheus_k8s.v0.prometheus_remote_write import (
    PrometheusRemoteWriteProvider,
)
from charms.prometheus_k8s.v0.prometheus_scrape import MetricsEndpointConsumer
from charms.traefik_k8s.v0.ingress_per_unit import IngressPerUnitRequirer
from ops.charm import CharmBase
from ops.main import main
from ops.model import ActiveStatus, BlockedStatus, WaitingStatus
from ops.pebble import ChangeError, Layer

from prometheus_server import Prometheus

PROMETHEUS_CONFIG = "/etc/prometheus/prometheus.yml"
RULES_DIR = "/etc/prometheus/rules"

CORRUPT_PROMETHEUS_CONFIG_MESSAGE = "Failed to load Prometheus config"

logger = logging.getLogger(__name__)


class PrometheusCharm(CharmBase):
    """A Juju Charm for Prometheus."""

    def __init__(self, *args):
        super().__init__(*args)

        self._name = "prometheus"
        self._port = 9090

        self.service_patch = KubernetesServicePatch(self, [(f"{self.app.name}", self._port)])

        # Relation handler objects

        # Gathers scrape job information from metrics endpoints
        self.metrics_consumer = MetricsEndpointConsumer(self)

        # Manages ingress for this charm
        self.ingress = IngressPerUnitRequirer(self, endpoint="ingress", port=self._port)

        external_url = urlparse(self._external_url)

        # Exposes remote write endpoints
        self.remote_write_provider = PrometheusRemoteWriteProvider(
            self,
            relation_name=DEFAULT_REMOTE_WRITE_RELATION_NAME,
            endpoint_address=external_url.hostname or "",
            endpoint_port=external_url.port or self._port,
            endpoint_schema=external_url.scheme,
            endpoint_path=f"{external_url.path}/api/v1/write",
        )

        # Allows Grafana to aggregate metrics
        self.grafana_source_consumer = GrafanaSourceProvider(
            charm=self,
            source_type="prometheus",
            source_url=self._external_url,
        )

        # Maintains list of Alertmanagers to which alerts are forwarded
        self.alertmanager_consumer = AlertmanagerConsumer(self, relation_name="alertmanager")

        # Event handlers
        self.framework.observe(self.on.prometheus_pebble_ready, self._configure)
        self.framework.observe(self.on.config_changed, self._configure)
        self.framework.observe(self.on.upgrade_charm, self._configure)
        self.framework.observe(self.ingress.on.ingress_changed, self._configure)
        self.framework.observe(self.on.receive_remote_write_relation_created, self._configure)
        self.framework.observe(self.on.receive_remote_write_relation_changed, self._configure)
        self.framework.observe(self.on.receive_remote_write_relation_broken, self._configure)
        self.framework.observe(self.metrics_consumer.on.targets_changed, self._configure)
        self.framework.observe(self.alertmanager_consumer.on.cluster_changed, self._configure)

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
        container.push(PROMETHEUS_CONFIG, prometheus_config, make_dirs=True)
        logger.info("Pushed new configuration")

        # push alert rules if any
        self._set_alerts(container)

        current_services = container.get_plan().services
        new_layer = self._prometheus_layer

        # Restart prometheus only if command line arguments have changed,
        # otherwise just reload its configuration.
        if current_services == new_layer.services:
            # No change in layer; reload config to make sure it is valid
            external_url = urlparse(self._external_url)
            prometheus_server = Prometheus(web_route_prefix=external_url.path)
            reloaded = prometheus_server.reload_configuration()
            if not reloaded:
                logger.error("Prometheus failed to reload the configuration")
                self.unit.status = BlockedStatus(CORRUPT_PROMETHEUS_CONFIG_MESSAGE)
                return

            logger.info("Prometheus configuration reloaded")

        else:
            # Layer changed - replan.
            container.add_layer(self._name, new_layer, combine=True)
            try:
                # If a config is invalid then prometheus would exit immediately.
                # This would be caught by pebble (default timeout is 30 sec) and a ChangeError
                # would be raised.
                container.replan()
                logger.info("Prometheus (re)started")
            except ChangeError as e:
                logger.error(
                    "Failed to replan; pebble plan: %s; %s", container.get_plan().to_dict(), str(e)
                )
                self.unit.status = BlockedStatus(CORRUPT_PROMETHEUS_CONFIG_MESSAGE)
                return

        if (
            isinstance(self.unit.status, BlockedStatus)
            and self.unit.status.message != CORRUPT_PROMETHEUS_CONFIG_MESSAGE
        ):
            return

        # Make sure that if the remote_write endpoint changes, it is reflected in relation data.
        self.remote_write_provider.update_endpoint()
        self.grafana_source_consumer.update_source(self._external_url)

        self.unit.status = ActiveStatus()

    def _set_alerts(self, container):
        """Create alert rule files for all Prometheus consumers.

        Args:
            container: the Prometheus workload container into which
                alert rule files need to be created. This container
                must be in a pebble ready state.
        """
        container.remove_path(RULES_DIR, recursive=True)

        self._push_alert_rules(container, self.metrics_consumer.alerts())
        self._push_alert_rules(container, self.remote_write_provider.alerts())

    def _push_alert_rules(self, container, alerts):
        """Pushes alert rules from a rules file to the prometheus container.

        Args:
            container: the Prometheus workload container into which
                alert rule files need to be created. This container
                must be in a pebble ready state.
            alerts: a dictionary of alert rule files, fetched from
                either a metrics consumer or a remote write provider.

        """
        for topology_identifier, rules_file in alerts.items():
            filename = "juju_" + topology_identifier + ".rules"
            path = os.path.join(RULES_DIR, filename)

            rules = yaml.dump(rules_file)

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

        external_url = self._external_url
        args.append(f"--web.external-url={external_url}")

        if self.model.get_relation(DEFAULT_REMOTE_WRITE_RELATION_NAME):
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
        # Prometheus checks here:
        # https://github.com/prometheus/common/blob/627089d3a7af73be778847aa577192b937b8d89a/model/time.go#L186
        # Which is where this regex is sourced from. The validation is done
        # when parsing flags as part of binary invocation here:
        # https://github.com/prometheus/prometheus/blob/c40e269c3e514953299e9ba1f6265e067ab43e64/cmd/prometheus/main.go#L302
        timespec_re = re.compile(
            r"^((([0-9]+)y)?(([0-9]+)w)?(([0-9]+)d)?(([0-9]+)h)?(([0-9]+)m)?(([0-9]+)s)?(([0-9]+)ms)?|0)$"
        )
        if not (matched := timespec_re.search(timeval)):
            self.unit.status = BlockedStatus(f"Invalid time spec : {timeval}")

        return bool(matched)

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
        alerting_config = {}  # type: Dict[str, list]

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
        prometheus_config["scrape_configs"].append(default_config)  # type: ignore
        scrape_jobs = self.metrics_consumer.jobs()
        for job in scrape_jobs:
            job["honor_labels"] = True
            prometheus_config["scrape_configs"].append(job)  # type: ignore

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
    def _external_url(self) -> str:
        """Return the external hostname to be passed to ingress via the relation."""
        if web_external_url := self.model.config.get("web_external_url"):
            return web_external_url

        if ingress_url := self.ingress.url:
            return ingress_url

        # If we do not have an ingress, then use the pod ip as hostname.
        # The reason to prefer this over the pod name (which is the actual
        # hostname visible from the pod) or a K8s service, is that those
        # are routable virtually exclusively inside the cluster (as they rely)
        # on the cluster's DNS service, while the ip address is _sometimes_
        # routable from the outside, e.g., when deploying on MicroK8s on Linux.
        return f"http://{socket.getfqdn()}:{self._port}"


if __name__ == "__main__":
    main(PrometheusCharm)
