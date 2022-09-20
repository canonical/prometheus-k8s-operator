#!/usr/bin/env python3
# Copyright 2020 Canonical Ltd.
# See LICENSE file for licensing details.

"""A Juju charm for Prometheus on Kubernetes."""
import hashlib
import logging
import os
import re
import socket
from typing import Dict, Optional, cast
from urllib.parse import urlparse

import yaml
from charms.alertmanager_k8s.v0.alertmanager_dispatch import AlertmanagerConsumer
from charms.grafana_k8s.v0.grafana_dashboard import GrafanaDashboardProvider
from charms.grafana_k8s.v0.grafana_source import GrafanaSourceProvider
from charms.landing_page_k8s.v0.landing_page import LandingPageApp, LandingPageConsumer
from charms.observability_libs.v0.juju_topology import JujuTopology
from charms.observability_libs.v0.kubernetes_compute_resources_patch import (
    K8sResourcePatchFailedEvent,
    KubernetesComputeResourcesPatch,
    adjust_resource_requirements,
)
from charms.observability_libs.v0.kubernetes_service_patch import KubernetesServicePatch
from charms.prometheus_k8s.v0.prometheus_remote_write import (
    DEFAULT_RELATION_NAME as DEFAULT_REMOTE_WRITE_RELATION_NAME,
)
from charms.prometheus_k8s.v0.prometheus_remote_write import (
    PrometheusRemoteWriteProvider,
)
from charms.prometheus_k8s.v0.prometheus_scrape import (
    MetricsEndpointConsumer,
    MetricsEndpointProvider,
)
from charms.traefik_k8s.v1.ingress_per_unit import (
    IngressPerUnitReadyForUnitEvent,
    IngressPerUnitRequirer,
    IngressPerUnitRevokedForUnitEvent,
)
from lightkube import Client
from lightkube.core.exceptions import ApiError as LightkubeApiError
from lightkube.resources.core_v1 import PersistentVolumeClaim, Pod
from ops.charm import ActionEvent, CharmBase
from ops.framework import StoredState
from ops.main import main
from ops.model import ActiveStatus, BlockedStatus, MaintenanceStatus, WaitingStatus
from ops.pebble import Error as PebbleError
from ops.pebble import ExecError, Layer

from prometheus_server import Prometheus
from utils import convert_k8s_quantity_to_legacy_binary_gigabytes

PROMETHEUS_CONFIG = "/etc/prometheus/prometheus.yml"
RULES_DIR = "/etc/prometheus/rules"

logger = logging.getLogger(__name__)


def sha256(hashable) -> str:
    """Use instead of the builtin hash() for repeatable values."""
    if isinstance(hashable, str):
        hashable = hashable.encode("utf-8")
    return hashlib.sha256(hashable).hexdigest()


class PrometheusCharm(CharmBase):
    """A Juju Charm for Prometheus."""

    _stored = StoredState()

    def __init__(self, *args):
        super().__init__(*args)

        self._stored.set_default(config_hash=None, alerts_hash=None)

        self._name = "prometheus"
        self._port = 9090
        self.container = self.unit.get_container(self._name)

        self.service_patch = KubernetesServicePatch(
            self,
            [(f"{self.app.name}", self._port)],
        )

        self.resources_patch = KubernetesComputeResourcesPatch(
            self,
            self._name,
            resource_reqs_func=self._resource_reqs_from_config,
        )

        self._topology = JujuTopology.from_charm(self)

        self._scraping = MetricsEndpointProvider(
            self,
            relation_name="self-metrics-endpoint",
            jobs=self.self_scraping_job,
        )
        self.grafana_dashboard_provider = GrafanaDashboardProvider(charm=self)
        self.metrics_consumer = MetricsEndpointConsumer(self)
        self.ingress = IngressPerUnitRequirer(self, relation_name="ingress", port=self._port)

        external_url = urlparse(self.external_url)
        self._prometheus_server = Prometheus(web_route_prefix=external_url.path)

        self.remote_write_provider = PrometheusRemoteWriteProvider(
            charm=self,
            relation_name=DEFAULT_REMOTE_WRITE_RELATION_NAME,
            endpoint_address=external_url.hostname or "",
            endpoint_port=external_url.port or self._port,
            endpoint_schema=external_url.scheme,
            endpoint_path=f"{external_url.path}/api/v1/write",
        )

        self.grafana_source_provider = GrafanaSourceProvider(
            charm=self,
            source_type="prometheus",
            source_url=self.external_url,
        )
        self.alertmanager_consumer = AlertmanagerConsumer(
            charm=self,
            relation_name="alertmanager",
        )

        self.landing_page = LandingPageConsumer(
            charm=self,
            app=LandingPageApp(
                name="Prometheus",
                icon="chart-line-variant",
                url=self.external_url,
                description=(
                    "Prometheus collects and stores metrics as time series data,"
                    "i.e. metrics information is stored with the timestamp at which "
                    "it was recorded, alongside optional key-value pairs called "
                    "labels."
                ),
            ),
        )

        self.framework.observe(self.on.prometheus_pebble_ready, self._on_pebble_ready)
        self.framework.observe(self.on.config_changed, self._configure)
        self.framework.observe(self.on.upgrade_charm, self._configure)
        self.framework.observe(self.ingress.on.ready_for_unit, self._on_ingress_ready)
        self.framework.observe(self.ingress.on.revoked_for_unit, self._on_ingress_revoked)
        self.framework.observe(self.on.receive_remote_write_relation_created, self._configure)
        self.framework.observe(self.on.receive_remote_write_relation_changed, self._configure)
        self.framework.observe(self.on.receive_remote_write_relation_broken, self._configure)
        self.framework.observe(self.metrics_consumer.on.targets_changed, self._configure)
        self.framework.observe(self.alertmanager_consumer.on.cluster_changed, self._configure)
        self.framework.observe(self.resources_patch.on.patch_failed, self._on_k8s_patch_failed)
        self.framework.observe(self.on.validate_configuration_action, self._on_validate_config)

    @property
    def self_scraping_job(self):
        """The scrape job used by Prometheus to scrape itself during self-monitoring."""
        return [{"static_configs": [{"targets": [f"*:{self._port}"]}]}]

    @property
    def log_level(self):
        """The log level configured for the charm."""
        allowed_log_levels = ["debug", "info", "warn", "error", "fatal"]
        log_level = self.model.config["log_level"].lower()

        if log_level not in allowed_log_levels:
            logging.warning(
                "Invalid loglevel: %s given, %s allowed. defaulting to DEBUG loglevel.",
                log_level,
                "/".join(allowed_log_levels),
            )
            log_level = "debug"
        return log_level

    @property
    def _default_config(self):
        """Default configuration for the Prometheus workload."""
        return {
            "job_name": "prometheus",
            "scrape_interval": "5s",
            "scrape_timeout": "5s",
            "metrics_path": "/metrics",
            "honor_timestamps": True,
            "scheme": "http",
            "static_configs": [
                {
                    "targets": [f"localhost:{self._port}"],
                    "labels": {
                        "juju_model": self._topology.model,
                        "juju_model_uuid": self._topology.model_uuid,
                        "juju_application": self._topology.application,
                        "juju_unit": self._topology.charm_name,
                        "host": "localhost",
                    },
                }
            ],
            "relabel_configs": [
                {
                    "source_labels": [
                        "juju_model",
                        "juju_model_uuid",
                        "juju_application",
                        "juju_unit",
                    ],
                    "separator": "_",
                    "target_label": "instance",
                    "regex": "(.*)",
                }
            ],
        }

    @property
    def external_url(self) -> str:
        """Return the external hostname to be passed to ingress via the relation.

        If we do not have an ingress, then use the pod ip as hostname.
        The reason to prefer this over the pod name (which is the actual
        hostname visible from the pod) or a K8s service, is that those
        are routable virtually exclusively inside the cluster (as they rely)
        on the cluster's DNS service, while the ip address is _sometimes_
        routable from the outside, e.g., when deploying on MicroK8s on Linux.
        """
        if web_external_url := self.model.config.get("web_external_url"):
            return web_external_url
        if ingress_url := self.ingress.url:
            return ingress_url
        return f"http://{socket.getfqdn()}:{self._port}"

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
                    "command": self._generate_command(),
                    "startup": "enabled",
                }
            },
        }

        return Layer(layer_config)

    def _resource_reqs_from_config(self):
        limits = {
            "cpu": self.model.config.get("cpu"),
            "memory": self.model.config.get("memory"),
        }
        requests = {"cpu": "0.25", "memory": "200Mi"}
        return adjust_resource_requirements(limits, requests, adhere_to_requests=True)

    def _on_ingress_ready(self, event: IngressPerUnitReadyForUnitEvent):
        logger.info("Ingress for unit ready on '%s'", event.url)
        self._configure(event)

    def _on_ingress_revoked(self, event: IngressPerUnitRevokedForUnitEvent):
        logger.info("Ingress for unit revoked.")
        self._configure(event)

    def _on_k8s_patch_failed(self, event: K8sResourcePatchFailedEvent):
        self.unit.status = BlockedStatus(event.message)

    def _configure(self, _):
        """Reconfigure and either reload or restart Prometheus.

        In response to any configuration change, such as a new consumer
        relation, or a new configuration set by the administrator, the
        Prometheus config file is regenerated, and pushed to the workload
        container. Prometheus's configuration is reloaded if there has
        been no change to the Pebble layer (such as Prometheus command
        line arguments). If the Pebble layer has changed then Prometheus
        is restarted.
        """
        early_return_statuses = {
            "cfg_load_fail": BlockedStatus(
                "Prometheus failed to reload the configuration (WAL replay or ingress in progress?); see debug logs"
            ),
            "restart_fail": BlockedStatus(
                "Prometheus failed to restart (config valid?); see debug logs"
            ),
            "push_fail": BlockedStatus(
                "Failed to push updated config/alert files; see debug logs"
            ),
            "layer_fail": BlockedStatus("Failed to update prometheus service; see debug logs"),
            "config_invalid": BlockedStatus("Invalid prometheus configuration; see debug logs"),
            "validation_fail": BlockedStatus(
                "Failed to validate prometheus config; see debug logs"
            ),
        }

        if not self.resources_patch.is_ready():
            if isinstance(self.unit.status, ActiveStatus) or self.unit.status.message == "":
                self.unit.status = WaitingStatus("Waiting for resource limit patch to apply")
            return

        if not self.container.can_connect():
            self.unit.status = MaintenanceStatus("Configuring Prometheus")
            return

        try:
            # Need to reload if config or alerts changed.
            # (Both functions need to run so cannot use the short-circuiting `or`.)
            should_reload = any(
                [
                    self._generate_prometheus_config(self.container),
                    self._set_alerts(self.container),
                ]
            )
        except PebbleError as e:
            logger.error("Failed to push updated config/alert files: %s", e)
            self.unit.status = early_return_statuses["push_fail"]
            return

        try:
            should_restart = self._update_layer(self.container)
        except (TypeError, PebbleError) as e:
            logger.error("Failed to update prometheus service: %s", e)
            self.unit.status = early_return_statuses["layer_fail"]
            return

        try:
            output, err = self._promtool_check_config()
            if err:
                logger.error(
                    "Invalid prometheus configuration. Stdout: %s Stderr: %s", output, err
                )
                self.unit.status = early_return_statuses["config_invalid"]
                return
        except PebbleError as e:
            logger.error("Failed to validate prometheus config: %s", e)
            self.unit.status = early_return_statuses["validation_fail"]
            return

        if should_restart:
            try:
                # If a config is invalid then prometheus would exit immediately.
                # This would be caught by pebble (default timeout is 30 sec) and a ChangeError
                # would be raised.
                self.container.replan()
                logger.info("Prometheus (re)started")
            except PebbleError as e:
                logger.error(
                    "Failed to replan; pebble layer: %s; %s",
                    self._prometheus_layer.to_dict(),
                    e,
                )
                self.unit.status = early_return_statuses["restart_fail"]
                return

        elif should_reload:
            reloaded = self._prometheus_server.reload_configuration()
            if not reloaded:
                logger.error(
                    "Prometheus failed to reload the configuration (WAL replay or ingress in progress?)"
                )
                self.unit.status = early_return_statuses["cfg_load_fail"]
                return

            logger.info("Prometheus configuration reloaded")

        if (
            isinstance(self.unit.status, BlockedStatus)
            and self.unit.status not in early_return_statuses.values()
        ):
            return

        self.remote_write_provider.update_endpoint()
        self.grafana_source_provider.update_source(self.external_url)
        self.unit.status = ActiveStatus()

    def _on_pebble_ready(self, event) -> None:
        """Pebble ready hook.

        This runs after the workload container starts.
        """
        self._configure(event)
        if version := self._prometheus_version:
            self.unit.set_workload_version(version)
        else:
            logger.debug(
                "Cannot set workload version at this time: could not get Alertmanager version."
            )

    def _update_config(self, container) -> bool:
        """Pushes new config, if needed.

        Returns a boolean indicating if a new configuration was pushed.
        """
        config = self._generate_prometheus_config(container)
        config_hash = sha256(config)

        if config_hash == self._stored.config_hash:
            return False

        logger.debug("Prometheus config changed")
        container.push(PROMETHEUS_CONFIG, config, make_dirs=True)
        self._stored.config_hash = config_hash
        logger.info("Pushed new configuration")
        return True

    def _update_layer(self, container) -> bool:
        current_services = container.get_plan().services
        new_layer = self._prometheus_layer

        if current_services == new_layer.services:
            return False

        container.add_layer(self._name, new_layer, combine=True)
        return True

    def _update_status(self, event):
        """Fired intermittently by the Juju agent."""
        self.unit.set_workload_version(self._prometheus_server.version())

        # Unit could still be blocked if a reload failed (e.g. during WAL replay or ingress not
        # yet ready). Calling `_configure` to recover.
        if self.unit.status != ActiveStatus():
            self._configure(event)

    def _set_alerts(self, container) -> bool:
        """Create alert rule files for all Prometheus consumers.

        Args:
            container: the Prometheus workload container into which
                alert rule files need to be created. This container
                must be in a pebble ready state.

        Returns: A boolean indicating if new alert rules were pushed.
        """
        metrics_consumer_alerts = self.metrics_consumer.alerts()
        remote_write_alerts = self.remote_write_provider.alerts()

        alerts_hash = sha256(str(metrics_consumer_alerts) + str(remote_write_alerts))
        if alerts_hash == self._stored.alerts_hash:
            return False

        container.remove_path(RULES_DIR, recursive=True)
        self._push_alert_rules(container, self.metrics_consumer.alerts())
        self._push_alert_rules(container, self.remote_write_provider.alerts())
        self._stored.alerts_hash = alerts_hash
        return True

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
            filename = f"juju_{topology_identifier}.rules"
            path = os.path.join(RULES_DIR, filename)

            rules = yaml.safe_dump(rules_file)

            container.push(path, rules, make_dirs=True)
            logger.debug("Updated alert rules file %s", filename)

    def _generate_command(self) -> str:
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

        external_url = self.external_url
        args.append(f"--web.external-url={external_url}")

        if self.model.relations[DEFAULT_REMOTE_WRITE_RELATION_NAME]:
            args.append("--enable-feature=remote-write-receiver")

        args.append(f"--log.level={self.log_level}")

        if config.get("metrics_wal_compression"):
            args.append("--storage.tsdb.wal-compression")

        if self._is_valid_timespec(retention_time := config.get("metrics_retention_time", "")):
            args.append(f"--storage.tsdb.retention.time={retention_time}")

        try:
            ratio = self._percent_string_to_ratio(config.get("maximum_retention_size", ""))

        except ValueError as e:
            logger.warning(e)
            self.unit.status = BlockedStatus(f"Invalid retention size: {e}")

        else:
            # `storage.tsdb.retention.size` uses the legacy binary format, so "GB" and not "GiB"
            # https://github.com/prometheus/prometheus/issues/10768
            # For simplicity, always communicate to prometheus in GiB
            try:
                capacity = convert_k8s_quantity_to_legacy_binary_gigabytes(
                    self._get_pvc_capacity(), ratio
                )
            except ValueError as e:
                self.unit.status = BlockedStatus(f"Error calculating retention size: {e}")
            except LightkubeApiError as e:
                self.unit.status = BlockedStatus(
                    "Error calculating retention size "
                    f"(try running `juju trust` on this application): {e}"
                )
            else:
                logger.debug("Retention size limit set to %s (%s%%)", capacity, ratio * 100)
                args.append(f"--storage.tsdb.retention.size={capacity}")

        command = ["/bin/prometheus"] + args

        return " ".join(command)

    def _promtool_check_config(self) -> tuple:
        """Check config validity. Runs `promtool check config` inside the workload.

        Returns:
            A 2-tuple, (stdout, stderr).
        """
        proc = self.container.exec(["/usr/bin/promtool", "check", "config", PROMETHEUS_CONFIG])
        try:
            output, err = proc.wait_output()
        except ExecError as e:
            output, err = e.stdout, e.stderr

        return output, err

    def _on_validate_config(self, event: ActionEvent) -> None:
        if not self.container.can_connect():
            event.fail("Could not connect to the Prometheus workload!")
            return

        output, err = self._promtool_check_config()
        event.set_results(
            {"result": output, "error-message": err, "valid": False if err else True}
        )

    def _get_pvc_capacity(self) -> str:
        """Get PVC capacity from pod name.

        This may need to be handled differently once Juju supports multiple storage instances
        for k8s (https://bugs.launchpad.net/juju/+bug/1977775).
        """
        # Assuming the storage name is "databases" (must match metadata.yaml).
        # This assertion would be picked up by every integration test so no concern this would
        # reach production.
        assert (
            "database" in self.model.storages
        ), "The 'database' storage is no longer in metadata: must update literals in charm code."

        # Get PVC capacity from kubernetes
        client = Client()
        pod_name = self.unit.name.replace("/", "-", -1)

        # Take the first volume whose name starts with "<app-name>-database-".
        # The volumes array looks as follows for app "am" and storage "data":
        # 'volumes': [{'name': 'am-data-d7f6a623',
        #              'persistentVolumeClaim': {'claimName': 'am-data-d7f6a623-am-0'}}, ...]
        pvc_name = ""
        for volume in cast(
            Pod, client.get(Pod, name=pod_name, namespace=self.model.name)
        ).spec.volumes:
            if not volume.persistentVolumeClaim:
                # The volumes 'charm-data' and 'kube-api-access-xxxxx' do not have PVCs - filter
                # those out.
                continue
            # claimName looks like this: 'prom-database-325a0ee8-prom-0'
            matcher = re.compile(rf"^{self.app.name}-database-.*?-{pod_name}$")
            if matcher.match(volume.persistentVolumeClaim.claimName):
                pvc_name = volume.persistentVolumeClaim.claimName
                break

        if not pvc_name:
            raise ValueError("No PVC found for pod " + pod_name)

        capacity = cast(
            PersistentVolumeClaim,
            client.get(PersistentVolumeClaim, name=pvc_name, namespace=self.model.name),
        ).status.capacity["storage"]

        # The other kind of storage to query for is
        # client.get(...).spec.resources.requests["storage"]
        # but to ensure prometheus does not fill up storage we need to limit the actual value
        # (status.capacity) and not the requested value (spec.resources.requests).

        return capacity

    def _is_valid_timespec(self, timeval: str) -> bool:
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

    def _percent_string_to_ratio(self, percentage: str) -> float:
        """Convert a string representation of percentage of 0-100%, to a 0-1 ratio.

        Raises:
            ValueError, if the percentage string is invalid or not within range.
        """
        if not percentage.endswith("%"):
            raise ValueError("Percentage string must be a number followed by '%', e.g. '80%'")
        value = float(percentage[:-1]) / 100.0
        if value < 0 or value > 1:
            raise ValueError("Percentage value must be in the range 0-100.")
        return value

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

    def _generate_prometheus_config(self, container) -> bool:
        """Construct Prometheus configuration and write to filesystem.

        Returns a boolean indicating if a new configuration was pushed.
        """
        prometheus_config = {
            "global": self._prometheus_global_config(),
            "rule_files": [os.path.join(RULES_DIR, "juju_*.rules")],
            "scrape_configs": [],
        }

        alerting_config = self._alerting_config()
        if alerting_config:
            prometheus_config["alerting"] = alerting_config

        prometheus_config["scrape_configs"].append(self._default_config)  # type: ignore
        certs = {}
        scrape_jobs = self.metrics_consumer.jobs()
        for job in scrape_jobs:
            job["honor_labels"] = True
            if (tls_config := job.get("tls_config")) and (ca_file := tls_config.get("ca_file")):
                # Cert is transferred over relation data and needs to be written to a file on disk.
                cert_filename = f"/etc/prometheus/{job['job_name']}.crt"
                certs[cert_filename] = ca_file
                job["tls_config"]["ca_file"] = cert_filename
            prometheus_config["scrape_configs"].append(job)  # type: ignore

        # Check if config changed, using its hash
        config_hash = sha256(
            yaml.safe_dump({"prometheus_config": prometheus_config, "certs": certs})
        )
        if config_hash == self._stored.config_hash:
            return False

        logger.debug("Prometheus config changed")

        container.push(PROMETHEUS_CONFIG, yaml.safe_dump(prometheus_config), make_dirs=True)
        for filename, contents in certs.items():
            container.push(filename, contents, make_dirs=True)

        self._stored.config_hash = config_hash
        logger.info("Pushed new configuration")
        return True

    @property
    def _prometheus_version(self) -> Optional[str]:
        """Returns the version of Prometheus.

        Returns:
            A string equal to the Prometheus version.
        """
        if not self.container.can_connect():
            return None
        version_output, _ = self.container.exec(["/bin/prometheus", "--version"]).wait_output()
        # Output looks like this:
        # prometheus, version 2.33.5 (branch: ...
        result = re.search(r"version (\d*\.\d*\.\d*)", version_output)
        if result is None:
            return result
        return result.group(1)


if __name__ == "__main__":
    main(PrometheusCharm)
