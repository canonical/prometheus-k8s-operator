#!/usr/bin/env python3

# Copyright 2020 Canonical Ltd.
# See LICENSE file for licensing details.

"""A Juju charm for Prometheus on Kubernetes."""
import hashlib
import logging
import re
import socket
import subprocess
from pathlib import Path
from typing import Dict, Optional, Tuple, TypedDict, cast
from urllib.parse import urlparse

import yaml
from charms.alertmanager_k8s.v1.alertmanager_dispatch import AlertmanagerConsumer
from charms.catalogue_k8s.v1.catalogue import CatalogueConsumer, CatalogueItem
from charms.grafana_k8s.v0.grafana_dashboard import GrafanaDashboardProvider
from charms.grafana_k8s.v0.grafana_source import GrafanaSourceProvider
from charms.observability_libs.v0.cert_handler import CertHandler
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
from charms.tempo_k8s.v1.charm_tracing import trace_charm
from charms.tempo_k8s.v1.tracing import TracingEndpointRequirer
from charms.traefik_k8s.v1.ingress_per_unit import (
    IngressPerUnitReadyForUnitEvent,
    IngressPerUnitRequirer,
    IngressPerUnitRevokedForUnitEvent,
)
from cosl import JujuTopology
from lightkube.core.client import Client
from lightkube.core.exceptions import ApiError as LightkubeApiError
from lightkube.resources.core_v1 import PersistentVolumeClaim, Pod
from ops import CollectStatusEvent, StoredState
from ops.charm import ActionEvent, CharmBase
from ops.main import main
from ops.model import (
    ActiveStatus,
    BlockedStatus,
    MaintenanceStatus,
    ModelError,
    OpenedPort,
    StatusBase,
    WaitingStatus,
)
from ops.pebble import Error as PebbleError
from ops.pebble import ExecError, Layer
from prometheus_client import Prometheus
from utils import convert_k8s_quantity_to_legacy_binary_gigabytes

PROMETHEUS_DIR = "/etc/prometheus"
PROMETHEUS_CONFIG = f"{PROMETHEUS_DIR}/prometheus.yml"
PROMETHEUS_GLOBAL_SCRAPE_INTERVAL = "1m"
RULES_DIR = f"{PROMETHEUS_DIR}/rules"
CONFIG_HASH_PATH = f"{PROMETHEUS_DIR}/config.sha256"
ALERTS_HASH_PATH = f"{PROMETHEUS_DIR}/alerts.sha256"

# Paths for the private key and the signed server certificate.
# These are used to present to clients and to authenticate other servers.
KEY_PATH = f"{PROMETHEUS_DIR}/server.key"
CERT_PATH = f"{PROMETHEUS_DIR}/server.cert"
CA_CERT_PATH = f"{PROMETHEUS_DIR}/ca.cert"
WEB_CONFIG_PATH = f"{PROMETHEUS_DIR}/prometheus-web-config.yml"

# To keep a tidy debug-log, we suppress some DEBUG/INFO logs from some imported libs,
# even when charm logging is set to a lower level.
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)


def sha256(hashable) -> str:
    """Use instead of the builtin hash() for repeatable values."""
    if isinstance(hashable, str):
        hashable = hashable.encode("utf-8")
    return hashlib.sha256(hashable).hexdigest()


class ConfigError(Exception):
    """Configuration specific errors."""

    pass


class CompositeStatus(TypedDict):
    """Per-component status holder."""

    # These are going to go into stored state, so we must use marshallable objects.
    # They are passed to StatusBase.from_name().
    retention_size: Tuple[str, str]
    k8s_patch: Tuple[str, str]
    config: Tuple[str, str]


def to_tuple(status: StatusBase) -> Tuple[str, str]:
    """Convert a StatusBase to tuple, so it is marshallable into StoredState."""
    return status.name, status.message


def to_status(tpl: Tuple[str, str]) -> StatusBase:
    """Convert a tuple to a StatusBase, so it could be used natively with ops."""
    name, message = tpl
    return StatusBase.from_name(name, message)


@trace_charm(
    tracing_endpoint="tempo",
    server_cert="server_cert_path",
    extra_types=[
        KubernetesComputeResourcesPatch,
        CertHandler,
        MetricsEndpointConsumer,
        MetricsEndpointProvider,
        Prometheus,
    ],
)
class PrometheusCharm(CharmBase):
    """A Juju Charm for Prometheus."""

    _stored = StoredState()

    def __init__(self, *args):
        super().__init__(*args)

        # Prometheus has a mix of pull and push statuses. We need stored state for push statuses.
        # https://discourse.charmhub.io/t/its-probably-ok-for-a-unit-to-go-into-error-state/13022
        self._stored.set_default(
            status=CompositeStatus(
                retention_size=to_tuple(ActiveStatus()),
                k8s_patch=to_tuple(ActiveStatus()),
                config=to_tuple(ActiveStatus()),
            )
        )

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
        # Update certs here in init to avoid code ordering issues
        self._update_cert()

        self.ingress = IngressPerUnitRequirer(
            self,
            relation_name="ingress",
            port=self._port,
            strip_prefix=True,
            redirect_https=True,
            scheme=lambda: "https" if self._is_tls_ready() else "http",
        )

        self._topology = JujuTopology.from_charm(self)

        self.grafana_dashboard_provider = GrafanaDashboardProvider(charm=self)
        self.metrics_consumer = MetricsEndpointConsumer(self)
        self.alertmanager_consumer = AlertmanagerConsumer(
            charm=self,
            relation_name="alertmanager",
        )

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
        self._prometheus_client = Prometheus(self.internal_url)

        self.remote_write_provider = PrometheusRemoteWriteProvider(
            charm=self,
            relation_name=DEFAULT_REMOTE_WRITE_RELATION_NAME,
            server_url_func=lambda: PrometheusCharm.external_url.fget(self),  # type: ignore
            endpoint_path="/api/v1/write",
        )

        self.grafana_source_provider = GrafanaSourceProvider(
            charm=self,
            source_type="prometheus",
            source_url=self.internal_url,  # https://github.com/canonical/operator/issues/970
            refresh_event=self.cert_handler.on.cert_changed,
            extra_fields={"timeInterval": PROMETHEUS_GLOBAL_SCRAPE_INTERVAL},
        )

        self.catalogue = CatalogueConsumer(charm=self, item=self._catalogue_item)
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
        self.framework.observe(self.on.collect_unit_status, self._on_collect_unit_status)

    def _on_collect_unit_status(self, event: CollectStatusEvent):
        # "Pull" statuses
        retention_time = self.model.config.get("metrics_retention_time", "")
        if not self._is_valid_timespec(retention_time):
            event.add_status(BlockedStatus(f"Invalid time spec : {retention_time}"))

        # "Push" statuses
        for status in self._stored.status.values():
            event.add_status(to_status(status))

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
    def _catalogue_item(self) -> CatalogueItem:
        return CatalogueItem(
            name="Prometheus",
            icon="chart-line-variant",
            url=self.external_url,
            description=(
                "Prometheus collects, stores and serves metrics as time series data, "
                "alongside optional key-value pairs called labels."
            ),
        )

    @property
    def self_scraping_job(self):
        """Scrape config for "external" self monitoring.

        This scrape job is for a remote Prometheus to scrape this prometheus, for self-monitoring.
        Not to be confused with `self._default_config()`.
        """
        port = urlparse(self.external_url).port
        # `metrics_path` is automatically rendered by MetricsEndpointProvider, so no need
        # to specify it here.
        if self._is_tls_ready():
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
            "metrics_path": "/metrics",
            "honor_timestamps": True,
            "scheme": "http",  # replaced with "https" below if behind TLS
            "static_configs": [
                {
                    "targets": [f"{socket.getfqdn()}:{self._port}"],
                    "labels": {
                        "juju_model": self._topology.model,
                        "juju_model_uuid": self._topology.model_uuid,
                        "juju_application": self._topology.application,
                        "juju_unit": self._topology.unit,
                        "juju_charm": self._topology.charm_name,
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

        if self._is_tls_ready():
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
    def internal_url(self) -> str:
        """Returns workload's FQDN. Used for ingress."""
        scheme = "https" if self._is_tls_ready() else "http"
        return f"{scheme}://{socket.getfqdn()}:{self._port}"

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
        return self.internal_url

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
        self._stored.status["k8s_patch"] = to_tuple(BlockedStatus(cast(str, event.message)))

    def _on_server_cert_changed(self, _):
        self._update_cert()
        self._configure(_)

    def _is_cert_available(self) -> bool:
        return (
            self.cert_handler.enabled
            and (self.cert_handler.cert is not None)
            and (self.cert_handler.key is not None)
            and (self.cert_handler.ca is not None)
        )

    def _is_tls_ready(self) -> bool:
        return (
            self.container.can_connect()
            and self.container.exists(CERT_PATH)
            and self.container.exists(KEY_PATH)
            and self.container.exists(CA_CERT_PATH)
        )

    def _update_cert(self):
        if not self.container.can_connect():
            return

        ca_cert_path = Path("/usr/local/share/ca-certificates/ca.crt")

        if self._is_cert_available():
            # Save the workload certificates
            self.container.push(
                CERT_PATH,
                self.cert_handler.cert,  # pyright: ignore
                make_dirs=True,
            )
            self.container.push(
                KEY_PATH,
                self.cert_handler.key,  # pyright: ignore
                make_dirs=True,
            )
            # Save the CA among the trusted CAs and trust it
            self.container.push(
                ca_cert_path,
                self.cert_handler.ca,  # pyright: ignore
                make_dirs=True,
            )
            # FIXME with the update-ca-certificates machinery prometheus shouldn't need
            #  CA_CERT_PATH.
            self.container.push(
                CA_CERT_PATH,
                self.cert_handler.ca,  # pyright: ignore
                make_dirs=True,
            )

            # Repeat for the charm container. We need it there for prometheus client requests.
            ca_cert_path.parent.mkdir(exist_ok=True, parents=True)
            ca_cert_path.write_text(self.cert_handler.ca)  # pyright: ignore
        else:
            self.container.remove_path(CERT_PATH, recursive=True)
            self.container.remove_path(KEY_PATH, recursive=True)
            self.container.remove_path(ca_cert_path, recursive=True)
            self.container.remove_path(CA_CERT_PATH, recursive=True)  # TODO: remove (see FIXME ^)
            # Repeat for the charm container.
            ca_cert_path.unlink(missing_ok=True)

        self.container.exec(["update-ca-certificates", "--fresh"]).wait()
        subprocess.run(["update-ca-certificates", "--fresh"])

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

        # "is_ready" is a racy check, so we do it once here (instead of in collect-status)
        if self.resources_patch.is_ready():
            self._stored.status["k8s_patch"] = to_tuple(ActiveStatus())
        else:
            if isinstance(to_status(self._stored.status["k8s_patch"]), ActiveStatus):
                self._stored.status["k8s_patch"] = to_tuple(
                    WaitingStatus("Waiting for resource limit patch to apply")
                )
            return

        # "can_connect" is a racy check, so we do it once here (instead of in collect-status)
        if self.container.can_connect():
            self._stored.status["config"] = to_tuple(ActiveStatus())
        else:
            self._stored.status["config"] = to_tuple(MaintenanceStatus("Configuring Prometheus"))
            return

        if self._is_cert_available() and not self._is_tls_ready():
            self._update_cert()

        # We use the internal url for grafana source due to
        # https://github.com/canonical/operator/issues/970
        self.grafana_source_provider.update_source(self.internal_url)
        self.ingress.provide_ingress_requirements(
            scheme=urlparse(self.internal_url).scheme, port=self._port
        )
        self.remote_write_provider.update_endpoint()
        self.catalogue.update_item(item=self._catalogue_item)

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
            self._stored.status["config"] = to_tuple(BlockedStatus(str(e)))
            return
        except PebbleError as e:
            logger.error("Failed to push updated config/alert files: %s", e)
            self._stored.status["config"] = to_tuple(early_return_statuses["push_fail"])
            return
        else:
            self._stored.status["config"] = to_tuple(ActiveStatus())

        try:
            layer_changed = self._update_layer()
        except (TypeError, PebbleError) as e:
            logger.error("Failed to update prometheus service: %s", e)
            self._stored.status["config"] = to_tuple(early_return_statuses["layer_fail"])
            return
        else:
            self._stored.status["config"] = to_tuple(ActiveStatus())

        try:
            output, err = self._promtool_check_config()
            if err:
                logger.error(
                    "Invalid prometheus configuration. Stdout: %s Stderr: %s", output, err
                )
                self._stored.status["config"] = to_tuple(early_return_statuses["config_invalid"])
                return
        except PebbleError as e:
            logger.error("Failed to validate prometheus config: %s", e)
            self._stored.status["config"] = to_tuple(early_return_statuses["validation_fail"])
            return
        else:
            self._stored.status["config"] = to_tuple(ActiveStatus())

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
            self._stored.status["config"] = to_tuple(early_return_statuses["restart_fail"])
            return
        else:
            self._stored.status["config"] = to_tuple(ActiveStatus())

        # We only need to reload if pebble didn't replan (if pebble replanned, then new config
        # would be picked up on startup anyway).
        if not layer_changed and should_reload:
            reloaded = self._prometheus_client.reload_configuration()
            if not reloaded:
                logger.error("Prometheus failed to reload the configuration")
                self._stored.status["config"] = to_tuple(early_return_statuses["cfg_load_fail"])
                return
            if reloaded == "read_timeout":
                self._stored.status["config"] = to_tuple(early_return_statuses["cfg_load_timeout"])
                return

            logger.info("Prometheus configuration reloaded")
            self._stored.status["config"] = to_tuple(ActiveStatus())

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

        # For stripPrefix middleware to work correctly, we need to set web.external-url and
        # web.route-prefix in a particular way.
        # https://github.com/prometheus/prometheus/issues/1191
        route_prefix = urlparse(self.external_url).path.strip("/")
        external_url = f"{self.internal_url.rstrip('/')}/{route_prefix}".rstrip("/")
        args.append(f"--web.external-url={external_url}")
        args.append("--web.route-prefix=/")

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
            self._stored.status["retention_size"] = to_tuple(
                BlockedStatus(f"Invalid retention size: {e}")
            )

        else:
            # `storage.tsdb.retention.size` uses the legacy binary format, so "GB" and not "GiB"
            # https://github.com/prometheus/prometheus/issues/10768
            # For simplicity, always communicate to prometheus in GiB
            try:
                capacity = convert_k8s_quantity_to_legacy_binary_gigabytes(
                    self._get_pvc_capacity(), ratio
                )
            except ValueError as e:
                self._stored.status["retention_size"] = to_tuple(
                    BlockedStatus(f"Error calculating retention size: {e}")
                )
            except LightkubeApiError as e:
                self._stored.status["retention_size"] = to_tuple(
                    BlockedStatus(
                        "Error calculating retention size "
                        f"(try running `juju trust` on this application): {e}"
                    )
                )
            else:
                logger.debug("Retention size limit set to %s (%s%%)", capacity, ratio * 100)
                args.append(f"--storage.tsdb.retention.size={capacity}")
                self._stored.status["retention_size"] = to_tuple(ActiveStatus())

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
        ).spec.volumes:  # pyright: ignore
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
        ).status.capacity[  # pyright: ignore
            "storage"
        ]

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
        matched = timespec_re.search(timeval)
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
        global_config = {
            "scrape_interval": PROMETHEUS_GLOBAL_SCRAPE_INTERVAL,
            "scrape_timeout": "10s",
        }

        if config.get("evaluation_interval") and self._is_valid_timespec(
            config["evaluation_interval"]
        ):
            global_config["evaluation_interval"] = config["evaluation_interval"]

        return global_config

    def _web_config(self) -> Optional[dict]:
        """Return the web.config.file contents as a dict, if TLS is enabled; otherwise None.

        Ref: https://prometheus.io/docs/prometheus/latest/configuration/https/
        """
        if self._is_tls_ready():
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
        alertmanagers = self.alertmanager_consumer.get_cluster_info()
        if not alertmanagers:
            logger.debug("No alertmanagers available")
            return {}

        alerting_config: Dict[str, list] = PrometheusConfig.render_alertmanager_static_configs(
            list(alertmanagers)
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
        certs: Dict[str, str] = {}
        scrape_jobs = self.metrics_consumer.jobs()
        for job in scrape_jobs:
            job["honor_labels"] = True

            processed_job, processed_certs = self._process_tls_config(job)
            certs = {**certs, **processed_certs}
            prometheus_config["scrape_configs"].append(processed_job)  # type: ignore

        web_config = self._web_config()

        # Check if config changed, using its hash
        config_hash = sha256(
            yaml.safe_dump(
                {"prometheus_config": prometheus_config, "web_config": web_config, "certs": certs}
            )
        )

        self._push(PROMETHEUS_CONFIG, yaml.safe_dump(prometheus_config))
        for filename, contents in certs.items():
            self._push(filename, contents)

        if web_config:
            self._push(WEB_CONFIG_PATH, yaml.safe_dump(web_config))
        else:
            self.container.remove_path(WEB_CONFIG_PATH, recursive=True)

        if config_hash == self._pull(CONFIG_HASH_PATH):
            return False

        self._push(CONFIG_HASH_PATH, config_hash)
        logger.info("Pushed new configuration")
        return True

    def _process_tls_config(self, job):
        certs: Dict[str, str] = {}  # Mapping form cert filename to cert content.
        if (tls_config := job.get("tls_config", {})) or job.get("scheme") == "https":
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
                    "are available.",
                    job["job_name"],
                )

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

        return job, certs

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
        return self.tracing.otlp_http_endpoint()

    @property
    def server_cert_path(self) -> Optional[str]:
        """Server certificate path for TLS tracing."""
        return CERT_PATH


if __name__ == "__main__":
    main(PrometheusCharm)
