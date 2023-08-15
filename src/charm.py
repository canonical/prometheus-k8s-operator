#!/usr/bin/env python3

# Copyright 2020 Canonical Ltd.
# See LICENSE file for licensing details.

"""A Juju charm for Prometheus on Kubernetes."""
import hashlib
import logging
import re
import socket
from pathlib import Path
from typing import Dict, Optional, cast
from urllib.parse import urlparse

import yaml
from charms.alertmanager_k8s.v0.alertmanager_dispatch import AlertmanagerConsumer
from charms.catalogue_k8s.v0.catalogue import CatalogueConsumer, CatalogueItem
from charms.grafana_k8s.v0.grafana_dashboard import GrafanaDashboardProvider
from charms.grafana_k8s.v0.grafana_source import GrafanaSourceProvider
from charms.observability_libs.v0.cert_handler import CertHandler
from charms.observability_libs.v0.juju_topology import JujuTopology
from charms.observability_libs.v0.kubernetes_compute_resources_patch import (
    K8sResourcePatchFailedEvent,
    KubernetesComputeResourcesPatch,
    adjust_resource_requirements,
)
from charms.prometheus_k8s.v0.prometheus_scrape import (
    MetricsEndpointConsumer,
    MetricsEndpointProvider,
    PrometheusConfig,
)
from charms.prometheus_k8s.v1.prometheus_remote_write import (
    DEFAULT_RELATION_NAME as DEFAULT_REMOTE_WRITE_RELATION_NAME,
)
from charms.prometheus_k8s.v1.prometheus_remote_write import (
    PrometheusRemoteWriteProvider,
)
from charms.tempo_k8s.v0.charm_instrumentation import trace_charm
from charms.tempo_k8s.v0.tracing import TracingEndpointRequirer
from charms.traefik_k8s.v1.ingress_per_unit import (
    IngressPerUnitReadyForUnitEvent,
    IngressPerUnitRequirer,
    IngressPerUnitRevokedForUnitEvent,
)
from lightkube.core.client import Client
from lightkube.core.exceptions import ApiError as LightkubeApiError
from lightkube.resources.core_v1 import PersistentVolumeClaim, Pod
from ops.charm import ActionEvent, CharmBase
from ops.main import main
from ops.model import (
    ActiveStatus,
    BlockedStatus,
    MaintenanceStatus,
    ModelError,
    OpenedPort,
    WaitingStatus,
)
from ops.pebble import Error as PebbleError
from ops.pebble import ExecError, Layer
from prometheus_client import Prometheus
from utils import convert_k8s_quantity_to_legacy_binary_gigabytes

PROMETHEUS_DIR = "/etc/prometheus"
PROMETHEUS_CONFIG = f"{PROMETHEUS_DIR}/prometheus.yml"
RULES_DIR = f"{PROMETHEUS_DIR}/rules"
CONFIG_HASH_PATH = f"{PROMETHEUS_DIR}/config.sha256"
ALERTS_HASH_PATH = f"{PROMETHEUS_DIR}/alerts.sha256"

# Paths for the private key and the signed server certificate.
# These are used to present to clients and to authenticate other servers.
KEY_PATH = f"{PROMETHEUS_DIR}/server.key"
CERT_PATH = f"{PROMETHEUS_DIR}/server.cert"
CA_CERT_PATH = f"{PROMETHEUS_DIR}/ca.cert"
WEB_CONFIG_PATH = f"{PROMETHEUS_DIR}/prometheus-web-config.yml"

logger = logging.getLogger(__name__)


def sha256(hashable) -> str:
    """Use instead of the builtin hash() for repeatable values."""
    if isinstance(hashable, str):
        hashable = hashable.encode("utf-8")
    return hashlib.sha256(hashable).hexdigest()


class ConfigError(Exception):
    """Configuration specific errors."""

    pass


@trace_charm(tracing_endpoint="tempo")
class PrometheusCharm(CharmBase):
    """A Juju Charm for Prometheus."""

    def __init__(self, *args):
        super().__init__(*args)

        self._name = "prometheus"
        self._port = 9090
        self.container = self.unit.get_container(self._name)

        self.set_ports()

        self.resources_patch = KubernetesComputeResourcesPatch(
            self,
            self._name,
            resource_reqs_func=self._resource_reqs_from_config,
        )

        self.cert_handler = CertHandler(
            charm=self,
            key="prometheus-server-cert",
            peer_relation_name="prometheus-peers",
            extra_sans_dns=[socket.getfqdn()],
        )

        self.ingress = IngressPerUnitRequirer(
            self, relation_name="ingress", port=self._port, strip_prefix=True, redirect_https=True
        )

        self._topology = JujuTopology.from_charm(self)

        self.grafana_dashboard_provider = GrafanaDashboardProvider(charm=self)
        self.metrics_consumer = MetricsEndpointConsumer(self)
        self.alertmanager_consumer = AlertmanagerConsumer(
            charm=self,
            relation_name="alertmanager",
        )

        external_url = urlparse(self.external_url)

        self._scraping = MetricsEndpointProvider(
            self,
            relation_name="self-metrics-endpoint",
            jobs=self.self_scraping_job,
            external_url=self.external_url,
            refresh_event=[  # needed for ingress
                self.ingress.on.ready_for_unit,
                self.ingress.on.revoked_for_unit,
                self.on.update_status,
                self.cert_handler.on.cert_changed,
            ],
        )
        self._prometheus_client = Prometheus(
            f"{external_url.scheme}://localhost:9090/{external_url.path.strip('/')}"
        )

        self.remote_write_provider = PrometheusRemoteWriteProvider(
            charm=self,
            relation_name=DEFAULT_REMOTE_WRITE_RELATION_NAME,
            server_url_func=lambda: PrometheusCharm.external_url.fget(self),  # type: ignore
            endpoint_path="/api/v1/write",
        )

        self.grafana_source_provider = GrafanaSourceProvider(
            charm=self,
            source_type="prometheus",
            source_url=self.external_url,
            refresh_event=self.cert_handler.on.cert_changed,
        )

        self.catalogue = CatalogueConsumer(
            charm=self,
            refresh_event=[
                self.on.prometheus_pebble_ready,
                self.on.leader_elected,
                self.ingress.on.ready_for_unit,
                self.ingress.on.revoked_for_unit,
                self.on.config_changed,  # also covers upgrade-charm
                self.cert_handler.on.cert_changed,
            ],
            item=CatalogueItem(
                name="Prometheus",
                icon="chart-line-variant",
                url=self.external_url,
                description=(
                    "Prometheus collects, stores and serves metrics as time series data, "
                    "alongside optional key-value pairs called labels."
                ),
            ),
        )
        self.tracing = TracingEndpointRequirer(self)

        self.framework.observe(self.on.prometheus_pebble_ready, self._on_pebble_ready)
        self.framework.observe(self.on.config_changed, self._configure)
        self.framework.observe(self.on.upgrade_charm, self._configure)
        self.framework.observe(self.on.update_status, self._update_status)
        self.framework.observe(self.ingress.on.ready_for_unit, self._on_ingress_ready)
        self.framework.observe(self.ingress.on.revoked_for_unit, self._on_ingress_revoked)
        self.framework.observe(self.cert_handler.on.cert_changed, self._on_server_cert_changed)
        self.framework.observe(self.remote_write_provider.on.alert_rules_changed, self._configure)
        self.framework.observe(self.remote_write_provider.on.consumers_changed, self._configure)
        self.framework.observe(self.metrics_consumer.on.targets_changed, self._configure)
        self.framework.observe(self.alertmanager_consumer.on.cluster_changed, self._configure)
        self.framework.observe(self.resources_patch.on.patch_failed, self._on_k8s_patch_failed)
        self.framework.observe(self.on.validate_configuration_action, self._on_validate_config)

    def set_ports(self):
        """Open necessary (and close no longer needed) workload ports."""
        planned_ports = {
            OpenedPort("tcp", self._port),
        }
        actual_ports = self.unit.opened_ports()

        # Ports may change across an upgrade, so need to sync
        ports_to_close = actual_ports.difference(planned_ports)
        for p in ports_to_close:
            self.unit.close_port(p.protocol, p.port)

        new_ports_to_open = planned_ports.difference(actual_ports)
        for p in new_ports_to_open:
            self.unit.open_port(p.protocol, p.port)

    @property
    def metrics_path(self):
        """The metrics path, adjusted by ingress path (if any)."""
        return urlparse(self.external_url).path.rstrip("/") + "/metrics"

    @property
    def self_scraping_job(self):
        """Scrape config for "external" self monitoring.

        This scrape job is for a remote Prometheus to scrape this prometheus, for self-monitoring.
        Not to be confused with `self._default_config()`.
        """
        port = urlparse(self.external_url).port
        # `metrics_path` is automatically rendered by MetricsEndpointProvider, so no need
        # to specify it here.
        if self._is_tls_enabled():
            config = {
                "scheme": "https",
                "tls_config": {
                    "ca_file": self.cert_handler.ca,
                },
                "static_configs": [{"targets": [f"*:{port or 443}"]}],
            }
        else:
            config = {
                "scheme": "http",
                "static_configs": [{"targets": [f"*:{port or 80}"]}],
            }

        return [config]

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
        """Default configuration for the Prometheus workload.

        This scrape config is for prometheus to scrape itself, not to be confused with the
        self-monitoring scrape job in `self_scraping_job()`.
        """
        config = {
            "job_name": "prometheus",
            "scrape_interval": "5s",
            "scrape_timeout": "5s",
            "metrics_path": self.metrics_path,
            "honor_timestamps": True,
            "scheme": "http",  # replaced with "https" below if behind TLS
            "static_configs": [
                {
                    "targets": [f"{socket.getfqdn()}:{self._port}"],
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

        if self._is_tls_enabled():
            config.update(
                {
                    "scheme": "https",
                    "tls_config": {
                        "ca_file": CA_CERT_PATH,
                    },
                }
            )

        return config

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
        try:
            if ingress_url := self.ingress.url:
                return ingress_url
        except ModelError as e:
            logger.error("Failed obtaining external url: %s. Shutting down?", e)
        return f"{'https' if self._is_tls_enabled() else 'http'}://{socket.getfqdn()}:{self._port}"

    def _is_tls_enabled(self):
        return bool(self.cert_handler.cert)

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

        return Layer(layer_config)  # pyright: ignore

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
        self.unit.status = BlockedStatus(cast(str, event.message))

    def _on_server_cert_changed(self, _):
        for path in [KEY_PATH, CERT_PATH, CA_CERT_PATH]:
            self.container.remove_path(path, recursive=True)

        if self.cert_handler.ca:
            self.container.push(
                CA_CERT_PATH,
                self.cert_handler.ca,
                make_dirs=True,
            )
        if self.cert_handler.cert and self.cert_handler.key:
            self.container.push(
                CERT_PATH,
                self.cert_handler.cert,
                make_dirs=True,
            )
            self.container.push(
                KEY_PATH,
                self.cert_handler.key,
                make_dirs=True,
            )

        self.grafana_source_provider.update_source(self.external_url)
        self._configure(_)

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
                "Prometheus failed to reload the configuration; see debug logs"
            ),
            "cfg_load_timeout": MaintenanceStatus("Waiting for prometheus to start"),
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
                    self._generate_prometheus_config(),
                    self._set_alerts(),
                ]
            )
        except ConfigError as e:
            logger.error("Failed to generate configuration: %s", e)
            self.unit.status = BlockedStatus(str(e))
            return
        except PebbleError as e:
            logger.error("Failed to push updated config/alert files: %s", e)
            self.unit.status = early_return_statuses["push_fail"]
            return

        try:
            should_restart = self._update_layer()
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
            reloaded = self._prometheus_client.reload_configuration()
            if not reloaded:
                logger.error("Prometheus failed to reload the configuration")
                self.unit.status = early_return_statuses["cfg_load_fail"]
                return
            if reloaded == "read_timeout":
                self.unit.status = early_return_statuses["cfg_load_timeout"]
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
                "Cannot set workload version at this time: could not get Prometheus version."
            )

    def _update_layer(self) -> bool:
        current_planned_services = self.container.get_plan().services
        new_layer = self._prometheus_layer

        current_services = self.container.get_services()  # mapping from str to ServiceInfo
        all_svcs_running = all(svc.is_running() for svc in current_services.values())

        if current_planned_services == new_layer.services and all_svcs_running:
            return False

        self.container.add_layer(self._name, new_layer, combine=True)
        return True

    def _update_status(self, event):
        """Fired intermittently by the Juju agent."""
        # Unit could still be blocked if a reload failed (e.g. during WAL replay or ingress not
        # yet ready). Calling `_configure` to recover.
        if self.unit.status != ActiveStatus():
            self._configure(event)

    def _set_alerts(self) -> bool:
        """Create alert rule files for all Prometheus consumers.

        Returns: A boolean indicating if new or different alert rules were pushed.
        """
        metrics_consumer_alerts = self.metrics_consumer.alerts
        remote_write_alerts = self.remote_write_provider.alerts
        alerts_hash = sha256(str(metrics_consumer_alerts) + str(remote_write_alerts))
        alert_rules_changed = alerts_hash != self._pull(ALERTS_HASH_PATH)

        if alert_rules_changed:
            self.container.remove_path(RULES_DIR, recursive=True)
            self._push_alert_rules(metrics_consumer_alerts)
            self._push_alert_rules(remote_write_alerts)
            self._push(ALERTS_HASH_PATH, alerts_hash)

        return alert_rules_changed

    def _push_alert_rules(self, alerts):
        """Pushes alert rules from a rules file to the prometheus container.

        Args:
            alerts: a dictionary of alert rule files, fetched from
                either a metrics consumer or a remote write provider.
        """
        for topology_identifier, rules_file in alerts.items():
            filename = f"juju_{topology_identifier}.rules"
            path = f"{RULES_DIR}/{filename}"

            rules = yaml.safe_dump(rules_file)

            self._push(path, rules)
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

        if self._web_config():
            args.append(f"--web.config.file={WEB_CONFIG_PATH}")

        external_url = self.external_url
        args.append(f"--web.external-url={external_url}")

        if self.model.relations[DEFAULT_REMOTE_WRITE_RELATION_NAME]:
            args.append("--web.enable-remote-write-receiver")

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
        client = Client()  # pyright: ignore
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

        namespace_file = Path("/var/run/secrets/kubernetes.io/serviceaccount/namespace")
        if namespace_file.exists():
            namespace = namespace_file.read_text().strip()
        else:
            namespace = self.model.name

        capacity = cast(
            PersistentVolumeClaim,
            client.get(PersistentVolumeClaim, name=pvc_name, namespace=namespace),
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

    def _web_config(self) -> Optional[dict]:
        """Return the web.config.file contents as a dict, if TLS is enabled; otherwise None.

        Ref: https://prometheus.io/docs/prometheus/latest/configuration/https/
        """
        if self._is_tls_enabled():
            return {
                "tls_server_config": {
                    "cert_file": CERT_PATH,
                    "key_file": KEY_PATH,
                }
            }
        return None

    def _alerting_config(self) -> dict:
        """Construct Prometheus altering configuration.

        Returns:
            a dictionary consisting of the alerting configuration for Prometheus.
        """
        alertmanagers = self.alertmanager_consumer.get_cluster_info_with_scheme()
        if not alertmanagers:
            logger.debug("No alertmanagers available")
            return {}

        alerting_config: Dict[str, list] = PrometheusConfig.render_alertmanager_static_configs(
            alertmanagers
        )
        return alerting_config

    def _generate_prometheus_config(self) -> bool:
        """Construct Prometheus configuration and write to filesystem.

        Returns a boolean indicating if a new configuration was pushed.
        """
        prometheus_config = {
            "global": self._prometheus_global_config(),
            "rule_files": [f"{RULES_DIR}/juju_*.rules"],
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

            # If "tls_config" is absent but scheme is https, then set insecure_skip_verify.
            default_tls_config = (
                {"insecure_skip_verify": True} if job.get("scheme") == "https" else {}
            )
            if tls_config := job.get("tls_config", default_tls_config):
                # Certs are transferred over relation data and need to be written to files on disk.
                # CA certificate to validate the server certificate with.

                # If the scrape job has a TLS section but no "ca_file", then use ours, assuming
                # prometheus and all scrape jobs are signed by the same CA.
                if ca_file := tls_config.get("ca_file") or self.cert_handler.ca:
                    # TODO we shouldn't be passing CA certs over relation data, because that
                    #  reduces to self-signed certs. Both parties need to separately trust the CA
                    #  instead.
                    filename = f"{PROMETHEUS_DIR}/{job['job_name']}-ca.crt"
                    certs[filename] = ca_file
                    job["tls_config"] = {**tls_config, **{"ca_file": filename}}
                else:
                    # The tls_config section is present, but we don't have any CA certs
                    logger.warning(
                        "The scrape job '%s' has a tls_config section specified, but no CA certs "
                        "are available. Adding 'insecure_skip_verify' as a fallback.",
                        job["job_name"],
                    )
                    job["tls_config"] = {**tls_config, **{"insecure_skip_verify": True}}

                # Certificate and key files for client cert authentication to the server.
                if (cert_file := tls_config.get("cert_file")) and (
                    key_file := tls_config.get("key_file")
                ):
                    filename = f"{PROMETHEUS_DIR}/{job['job_name']}-client.crt"
                    certs[filename] = cert_file
                    job["tls_config"]["cert_file"] = filename
                    filename = f"{PROMETHEUS_DIR}/{job['job_name']}-client.key"
                    certs[filename] = key_file
                    job["tls_config"]["key_file"] = filename
                elif "cert_file" in tls_config or "key_file" in tls_config:
                    raise ConfigError(
                        'tls_config requires both "cert_file" and "key_file" if client '
                        "authentication is to be used"
                    )

            prometheus_config["scrape_configs"].append(job)  # type: ignore

        # Check if config changed, using its hash
        config_hash = sha256(
            yaml.safe_dump({"prometheus_config": prometheus_config, "certs": certs})
        )
        if config_hash == self._pull(CONFIG_HASH_PATH):
            return False

        logger.debug("Prometheus config changed")

        self._push(PROMETHEUS_CONFIG, yaml.safe_dump(prometheus_config))
        for filename, contents in certs.items():
            self._push(filename, contents)

        if web_config := self._web_config():
            self._push(WEB_CONFIG_PATH, yaml.safe_dump(web_config))
        else:
            self.container.remove_path(WEB_CONFIG_PATH, recursive=True)

        self._push(CONFIG_HASH_PATH, config_hash)
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

    def _pull(self, path) -> Optional[str]:
        """Pull file from container (without raising pebble errors).

        Returns:
            File contents if exists; None otherwise.
        """
        try:
            return cast(str, self.container.pull(path, encoding="utf-8").read())
        except (FileNotFoundError, PebbleError):
            # Drop FileNotFoundError https://github.com/canonical/operator/issues/896
            return None

    def _push(self, path, contents):
        """Push file to container, creating subdirs as necessary."""
        self.container.push(path, contents, make_dirs=True, encoding="utf-8")

    @property
    def tempo(self) -> Optional[str]:
        """Tempo endpoint for charm tracing."""
        return self.tracing.otlp_grpc_endpoint()


if __name__ == "__main__":
    main(PrometheusCharm)
