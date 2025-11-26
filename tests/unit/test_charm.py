# Copyright 2020 Canonical Ltd.
# See LICENSE file for licensing details.

import json
import logging
import socket
import unittest
import uuid
from unittest.mock import patch

import ops
import yaml
from helpers import cli_arg, k8s_resource_multipatch, prom_multipatch
from ops.model import ActiveStatus, BlockedStatus, MaintenanceStatus
from ops.testing import Harness

from charm import PROMETHEUS_CONFIG, PrometheusCharm

ops.testing.SIMULATE_CAN_CONNECT = True  # pyright: ignore
logger = logging.getLogger(__name__)

RELATION_NAME = "metrics-endpoint"
DEFAULT_JOBS = [{"metrics_path": "/metrics"}]
SCRAPE_METADATA = {
    "model": "provider-model",
    "model_uuid": str(uuid.uuid4()),
    "application": "provider",
    "charm_name": "provider-charm",
}

@prom_multipatch
class TestCharm(unittest.TestCase):
    @k8s_resource_multipatch
    @patch("lightkube.core.client.GenericSyncClient")
    @prom_multipatch
    def setUp(self, *unused):
        self.harness = Harness(PrometheusCharm)
        self.addCleanup(self.harness.cleanup)

        patcher = patch.object(PrometheusCharm, "_get_pvc_capacity")
        self.mock_capacity = patcher.start()
        self.addCleanup(patcher.stop)
        self.harness.set_model_name("prometheus_model")
        self.mock_capacity.return_value = "1Gi"
        self.harness.container_pebble_ready("prometheus")
        self.harness.handle_exec("prometheus", ["update-ca-certificates"], result=0)
        self.harness.begin_with_initial_hooks()

    def test_grafana_is_provided_port_and_source(self):
        rel_id = self.harness.add_relation("grafana-source", "grafana")
        self.harness.add_relation_unit(rel_id, "grafana/0")
        fqdn = socket.getfqdn()
        grafana_host = self.harness.get_relation_data(rel_id, self.harness.model.unit.name)[
            "grafana_source_host"
        ]
        self.assertEqual(grafana_host, "http://{}:{}".format(fqdn, "9090"))

    def test_default_cli_log_level_is_info(self):
        plan = self.harness.get_container_pebble_plan("prometheus")
        self.assertEqual(cli_arg(plan, "--log.level"), "info")

    @k8s_resource_multipatch
    @patch("lightkube.core.client.GenericSyncClient")
    def test_invalid_log_level_defaults_to_debug(self, *unused):
        bad_log_config = {"log_level": "bad-level"}
        with self.assertLogs(level="WARNING") as logger:
            self.harness.update_config(bad_log_config)
            expected_logs = {
                "WARNING:root:Invalid loglevel: bad-level given, "
                "debug/info/warn/error/fatal allowed. "
                "defaulting to DEBUG loglevel."
            }
            self.assertGreaterEqual(set(logger.output), expected_logs)  # type: ignore

        plan = self.harness.get_container_pebble_plan("prometheus")
        self.assertEqual(cli_arg(plan, "--log.level"), "debug")

    @k8s_resource_multipatch
    @patch("lightkube.core.client.GenericSyncClient")
    def test_valid_log_level_is_accepted(self, *unused):
        valid_log_config = {"log_level": "warn"}
        self.harness.update_config(valid_log_config)

        plan = self.harness.get_container_pebble_plan("prometheus")
        self.assertEqual(cli_arg(plan, "--log.level"), "warn")

    def test_ingress_relation_not_set(self):
        self.harness.set_leader(True)

        plan = self.harness.get_container_pebble_plan("prometheus")
        fqdn = socket.getfqdn()
        self.assertEqual(cli_arg(plan, "--web.external-url"), f"http://{fqdn}:9090")

    def test_ingress_relation_set(self):
        self.harness.set_leader(True)

        rel_id = self.harness.add_relation("ingress", "traefik-ingress")
        self.harness.add_relation_unit(rel_id, "traefik-ingress/0")

        with patch(
            "charms.observability_libs.v0.kubernetes_compute_resources_patch.KubernetesComputeResourcesPatch.is_ready",
            new=lambda _: True,
        ):
            self.harness.update_relation_data(
                rel_id,
                "traefik-ingress",
                key_values={
                    "ingress": yaml.safe_dump({"prometheus-k8s/0": {"url": "http://test:80"}})
                },
            )

        plan = self.harness.get_container_pebble_plan("prometheus")
        self.assertEqual(cli_arg(plan, "--web.external-url"), "http://test:80")

    @k8s_resource_multipatch
    @patch("lightkube.core.client.GenericSyncClient")
    def test_web_external_has_no_effect(self, *unused):
        self.harness.set_leader(True)

        self.harness.update_config({"web_external_url": "http://test:80/sub/path"})

        plan = self.harness.get_container_pebble_plan("prometheus")
        fqdn = socket.getfqdn()
        self.assertEqual(cli_arg(plan, "--web.external-url"), f"http://{fqdn}:9090")

    def test_metrics_wal_compression_is_not_enabled_by_default(self):
        plan = self.harness.get_container_pebble_plan("prometheus")
        self.assertEqual(cli_arg(plan, "--storage.tsdb.wal-compression"), None)

    @k8s_resource_multipatch
    @patch("lightkube.core.client.GenericSyncClient")
    def test_metrics_wal_compression_can_be_enabled(self, *unused):
        compress_config = {"metrics_wal_compression": True}
        self.harness.update_config(compress_config)

        plan = self.harness.get_container_pebble_plan("prometheus")
        self.assertEqual(
            cli_arg(plan, "--storage.tsdb.wal-compression"),
            "--storage.tsdb.wal-compression",
        )

    @k8s_resource_multipatch
    @patch("lightkube.core.client.GenericSyncClient")
    def test_valid_metrics_retention_times_can_be_set(self, *unused):
        retention_time_config = {}
        acceptable_units = ["y", "w", "d", "h", "m", "s"]
        for unit in acceptable_units:
            retention_time = "{}{}".format(1, unit)
            retention_time_config["metrics_retention_time"] = retention_time
            self.harness.update_config(retention_time_config)

            plan = self.harness.get_container_pebble_plan("prometheus")
            self.assertEqual(cli_arg(plan, "--storage.tsdb.retention.time"), retention_time)

    @k8s_resource_multipatch
    @patch("lightkube.core.client.GenericSyncClient")
    def test_invalid_metrics_retention_times_can_not_be_set(self, *unused):
        retention_time_config = {}

        # invalid unit
        retention_time = "1x"
        retention_time_config["metrics_retention_time"] = retention_time

        self.harness.update_config(retention_time_config)
        plan = self.harness.get_container_pebble_plan("prometheus")
        self.assertEqual(cli_arg(plan, "--storage.tsdb.retention.time"), None)

        # invalid time value
        retention_time = "5m1y2d"
        retention_time_config["metrics_retention_time"] = retention_time

        self.harness.update_config(retention_time_config)
        plan = self.harness.get_container_pebble_plan("prometheus")
        self.assertEqual(cli_arg(plan, "--storage.tsdb.retention.time"), None)

    @k8s_resource_multipatch
    @patch("lightkube.core.client.GenericSyncClient")
    @prom_multipatch
    def test_global_evaluation_interval_can_be_set(self, *unused):
        evalint_config = {}
        acceptable_units = ["y", "w", "d", "h", "m", "s"]
        for unit in acceptable_units:
            evalint_config["evaluation_interval"] = "{}{}".format(1, unit)
            self.harness.update_config(evalint_config)
            container = self.harness.charm.unit.get_container(self.harness.charm._name)
            config = container.pull(PROMETHEUS_CONFIG)
            gconfig = global_config(config)
            self.assertEqual(gconfig["evaluation_interval"], evalint_config["evaluation_interval"])

    def test_default_scrape_config_is_always_set(self):
        container = self.harness.charm.unit.get_container(self.harness.charm._name)
        config = container.pull(PROMETHEUS_CONFIG)
        prometheus_scrape_config = scrape_config(config, "prometheus")
        self.assertIsNotNone(prometheus_scrape_config, "No default config found")

    @k8s_resource_multipatch
    @patch("lightkube.core.client.GenericSyncClient")
    def test_honor_labels_is_always_set_in_scrape_configs(self, *unused):
        rel_id = self.harness.add_relation(RELATION_NAME, "provider")
        self.harness.add_relation_unit(rel_id, "provider/0")
        self.harness.update_relation_data(
            rel_id,
            "provider",
            {
                "scrape_metadata": json.dumps(SCRAPE_METADATA),
                "scrape_jobs": json.dumps(DEFAULT_JOBS),
            },
        )

        container = self.harness.charm.unit.get_container(self.harness.charm._name)
        config = container.pull(PROMETHEUS_CONFIG)
        prometheus_scrape_config = yaml.safe_load(config)
        for job in prometheus_scrape_config["scrape_configs"]:
            if job["job_name"] != "prometheus":
                self.assertIn("honor_labels", job)
                self.assertTrue(job["honor_labels"])

    @k8s_resource_multipatch
    @patch("lightkube.core.client.GenericSyncClient")
    @patch("prometheus_client.Prometheus.reload_configuration")
    def test_configuration_reload(self, trigger_configuration_reload, *unused):
        self.harness.update_config({"evaluation_interval": "1234m"})
        trigger_configuration_reload.assert_called()

    @k8s_resource_multipatch
    @patch("lightkube.core.client.GenericSyncClient")
    @patch("prometheus_client.Prometheus.reload_configuration")
    def test_configuration_reload_success(self, trigger_configuration_reload, *unused):
        trigger_configuration_reload.return_value = True
        self.harness.update_config({"evaluation_interval": "1234m"})
        self.harness.evaluate_status()
        self.assertIsInstance(self.harness.model.unit.status, ActiveStatus)

    @k8s_resource_multipatch
    @patch("lightkube.core.client.GenericSyncClient")
    @patch("prometheus_client.Prometheus.reload_configuration")
    def test_configuration_reload_error(self, trigger_configuration_reload, *unused):
        trigger_configuration_reload.return_value = False
        self.harness.update_config({"evaluation_interval": "1234m"})
        self.harness.evaluate_status()
        self.assertIsInstance(self.harness.model.unit.status, BlockedStatus)

    @k8s_resource_multipatch
    @patch("lightkube.core.client.GenericSyncClient")
    @patch("prometheus_client.Prometheus.reload_configuration")
    def test_configuration_reload_read_timeout(self, trigger_configuration_reload, *unused):
        trigger_configuration_reload.return_value = "read_timeout"
        self.harness.update_config({"evaluation_interval": "1234m"})
        self.harness.evaluate_status()
        self.assertIsInstance(self.harness.model.unit.status, MaintenanceStatus)


def alerting_config(config):
    config_yaml = config[1]
    config_dict = yaml.safe_load(config_yaml)
    return config_dict.get("alerting")


def global_config(config_yaml):
    config_dict = yaml.safe_load(config_yaml)
    return config_dict["global"]


def scrape_config(config_yaml, job_name):
    config_dict = yaml.safe_load(config_yaml)
    scrape_configs = config_dict["scrape_configs"]
    for config in scrape_configs:
        if config["job_name"] == job_name:
            return config
    return None


@prom_multipatch
class TestConfigMaximumRetentionSize(unittest.TestCase):
    """Test the charmcraft.yaml option 'maximum_retention_size'."""

    def setUp(self):
        self.harness = Harness(PrometheusCharm)
        self.addCleanup(self.harness.cleanup)

        patcher = patch.object(PrometheusCharm, "_get_pvc_capacity")
        self.mock_capacity = patcher.start()
        self.addCleanup(patcher.stop)

    @k8s_resource_multipatch
    @patch("lightkube.core.client.GenericSyncClient")
    def test_default_maximum_retention_size_is_80_percent(self, *unused):
        """This test is here to guarantee backwards compatibility.

        Since charmcraft.yaml provides a default (which forms a contract), we need to prevent changing
        it unintentionally.
        """
        # GIVEN a capacity limit in binary notation (k8s notation)
        self.mock_capacity.return_value = "1Gi"

        # AND the maximum_retention_size config is left unspecified (let it keep its default)
        # WHEN the charm starts
        self.harness.container_pebble_ready("prometheus")
        self.harness.handle_exec("prometheus", ["update-ca-certificates"], result=0)
        self.harness.begin_with_initial_hooks()

        # THEN the pebble plan has the adjusted capacity of 80%
        plan = self.harness.get_container_pebble_plan("prometheus")
        self.assertEqual(cli_arg(plan, "--storage.tsdb.retention.size"), "0.8GB")

        # AND WHEN the config option is set and then unset
        self.harness.update_config({"maximum_retention_size": "50%"})
        self.harness.update_config(unset={"maximum_retention_size"})

        # THEN the pebble plan is back to 80%
        plan = self.harness.get_container_pebble_plan("prometheus")
        self.assertEqual(cli_arg(plan, "--storage.tsdb.retention.size"), "0.8GB")

    @k8s_resource_multipatch
    @patch("lightkube.core.client.GenericSyncClient")
    def test_multiplication_factor_applied_to_pvc_capacity(self, *unused):
        """The `--storage.tsdb.retention.size` arg must be multiplied by maximum_retention_size."""
        # GIVEN a capacity limit in binary notation (k8s notation)
        self.mock_capacity.return_value = "1Gi"

        # WHEN the charm starts
        self.harness.container_pebble_ready("prometheus")
        self.harness.handle_exec("prometheus", ["update-ca-certificates"], result=0)
        self.harness.begin_with_initial_hooks()

        for set_point, read_back in [("0%", "0GB"), ("50%", "0.5GB"), ("100%", "1GB")]:
            with self.subTest(limit=set_point):
                # WHEN a limit is set
                self.harness.update_config({"maximum_retention_size": set_point})

                # THEN the pebble plan the adjusted capacity
                plan = self.harness.get_container_pebble_plan("prometheus")
                self.assertEqual(cli_arg(plan, "--storage.tsdb.retention.size"), read_back)

    @k8s_resource_multipatch
    @patch("lightkube.core.client.GenericSyncClient")
    def test_invalid_retention_size_config_option_string(self, *unused):
        # GIVEN a running charm with default values
        self.mock_capacity.return_value = "1Gi"
        self.harness.container_pebble_ready("prometheus")
        self.harness.handle_exec("prometheus", ["update-ca-certificates"], result=0)
        self.harness.begin_with_initial_hooks()
        self.harness.evaluate_status()
        self.assertIsInstance(self.harness.model.unit.status, ActiveStatus)

        # WHEN the config option is set to an invalid string
        self.harness.update_config({"maximum_retention_size": "42"})

        # THEN cli arg is unspecified and the unit is blocked
        plan = self.harness.get_container_pebble_plan("prometheus")
        self.assertIsNone(cli_arg(plan, "--storage.tsdb.retention.size"))
        self.harness.evaluate_status()
        self.assertIsInstance(self.harness.model.unit.status, BlockedStatus)

        # AND WHEN the config option is set to another invalid string
        self.harness.update_config({"maximum_retention_size": "4GiB"})

        # THEN cli arg is unspecified and the unit is blocked
        plan = self.harness.get_container_pebble_plan("prometheus")
        self.assertIsNone(cli_arg(plan, "--storage.tsdb.retention.size"))
        self.harness.evaluate_status()
        self.assertIsInstance(self.harness.model.unit.status, BlockedStatus)

        # AND WHEN the config option is corrected
        self.harness.update_config({"maximum_retention_size": "42%"})

        # THEN cli arg is updated and the unit is goes back to active
        plan = self.harness.get_container_pebble_plan("prometheus")
        self.assertEqual(cli_arg(plan, "--storage.tsdb.retention.size"), "0.42GB")
        self.harness.evaluate_status()
        self.assertIsInstance(self.harness.model.unit.status, ActiveStatus)


@prom_multipatch
class TestAlertsFilename(unittest.TestCase):
    REMOTE_SCRAPE_METADATA = {
        "model": "remote-model",
        "model_uuid": "be44e4b8-32eb-48e1-a843-b1c12e47b9b3",
        "application": "remote-app",
        "charm_name": "remote-charm",
    }

    LABELED_ALERT_RULES = {
        "groups": [
            {
                "name": "ZZZ_a5edc336-b02e-4fad-b847-c530500c1c86_consumer-tester_alerts",
                "rules": [
                    {
                        "alert": "CPUOverUse",
                        "expr": "process_cpu_seconds_total > 0.12",
                        "labels": {
                            "severity": "Low",
                            "juju_model": "ZZZ-model",
                            "juju_model_uuid": "a5edc336-b02e-4fad-b847-c530500c1c86",
                            "juju_application": "zzz-app",
                        },
                    },
                ],
            },
            {
                "name": "AAA_a5edc336-b02e-4fad-b847-c530500c1c86_consumer-tester_alerts",
                "rules": [
                    {
                        "alert": "PrometheusTargetMissing",
                        "expr": "up == 0",
                        "labels": {
                            "severity": "critical",
                            "juju_model": "AAA-model",
                            "juju_model_uuid": "a5edc336-b02e-4fad-b847-c530500c1c86",
                            "juju_application": "aaa-app",
                        },
                    },
                ],
            },
        ]
    }

    UNLABELED_ALERT_RULES = {
        "groups": [
            {
                "name": "ZZZ_group_alerts",
                "rules": [
                    {
                        "alert": "CPUOverUse",
                        "expr": "process_cpu_seconds_total > 0.12",
                        "labels": {"severity": "Low"},
                    },
                ],
            },
            {
                "name": "AAA_group_alerts",
                "rules": [
                    {
                        "alert": "PrometheusTargetMissing",
                        "expr": "up == 0",
                        "labels": {"severity": "critical"},
                    },
                ],
            },
        ]
    }

    @k8s_resource_multipatch
    @patch("lightkube.core.client.GenericSyncClient")
    @patch("prometheus_client.Prometheus.reload_configuration", lambda *_: True)
    @prom_multipatch
    def setUp(self, *unused):
        self.harness = Harness(PrometheusCharm)
        self.addCleanup(self.harness.cleanup)

        patcher = patch.object(PrometheusCharm, "_get_pvc_capacity")
        self.mock_capacity = patcher.start()
        self.addCleanup(patcher.stop)
        self.harness.set_model_name("prometheus_model")
        self.mock_capacity.return_value = "1Gi"
        self.harness.container_pebble_ready("prometheus")
        self.harness.handle_exec("prometheus", ["update-ca-certificates"], result=0)
        self.harness.begin_with_initial_hooks()

        self.rel_id = self.harness.add_relation(RELATION_NAME, "remote-app")
        self.harness.add_relation_unit(self.rel_id, "remote-app/0")

    @k8s_resource_multipatch
    @patch("lightkube.core.client.GenericSyncClient")
    @patch("prometheus_client.Prometheus.reload_configuration", lambda *_: True)
    def test_charm_writes_meaningful_alerts_filename_1(self, *_):
        # WHEN relation data includes both scrape_metadata and labeled alerts
        self.harness.update_relation_data(
            self.rel_id,
            "remote-app",
            {
                "scrape_metadata": json.dumps(self.REMOTE_SCRAPE_METADATA),
                "alert_rules": json.dumps(self.LABELED_ALERT_RULES),
            },
        )

        # THEN rules filename is derived from the contents of alert labels
        container = self.harness.charm.unit.get_container(self.harness.charm._name)
        files = container.list_files("/etc/prometheus/rules")
        self.assertEqual(
            {file.path for file in files},
            {
                f"/etc/prometheus/rules/juju_ZZZ-model_a5edc336_zzz-app_{RELATION_NAME}_{self.rel_id}.rules"
            },
        )

    @k8s_resource_multipatch
    @patch("lightkube.core.client.GenericSyncClient")
    @patch("prometheus_client.Prometheus.reload_configuration", lambda *_: True)
    def test_charm_writes_meaningful_alerts_filename_2(self, *_):
        # TODO: merge the contents of these tests into a single test (and fix the bug!)
        # WHEN relation data includes only labeled alerts (no scrape_metadata)
        self.harness.update_relation_data(
            self.rel_id,
            "remote-app",
            {
                "alert_rules": json.dumps(self.LABELED_ALERT_RULES),
            },
        )

        # THEN rules filename is derived from the first (!) rule's topology labels
        # TODO derive filename from _sorted_ rules so it's deterministic?
        container = self.harness.charm.unit.get_container(self.harness.charm._name)
        files = container.list_files("/etc/prometheus/rules")
        self.assertEqual(
            {file.path for file in files},
            {
                f"/etc/prometheus/rules/juju_ZZZ-model_a5edc336_zzz-app_{RELATION_NAME}_{self.rel_id}.rules"
            },
        )

    @k8s_resource_multipatch
    @patch("lightkube.core.client.GenericSyncClient")
    @patch("prometheus_client.Prometheus.reload_configuration", lambda *_: True)
    def test_charm_writes_meaningful_alerts_filename_3(self, *_):
        # WHEN relation data includes scrape_metadata but _unlabeled_ alerts
        self.harness.update_relation_data(
            self.rel_id,
            "remote-app",
            {
                "scrape_metadata": json.dumps(self.REMOTE_SCRAPE_METADATA),
                "alert_rules": json.dumps(self.UNLABELED_ALERT_RULES),
            },
        )

        # THEN rules filename is derived from the contents of scrape_metadata
        container = self.harness.charm.unit.get_container(self.harness.charm._name)
        files = container.list_files("/etc/prometheus/rules")
        self.assertEqual(
            {file.path for file in files},
            {
                f"/etc/prometheus/rules/juju_remote-model_be44e4b8_remote-app_{RELATION_NAME}_{self.rel_id}.rules"
            },
        )

    @k8s_resource_multipatch
    @patch("lightkube.core.client.GenericSyncClient")
    @patch("prometheus_client.Prometheus.reload_configuration", lambda *_: True)
    def test_charm_writes_meaningful_alerts_filename_4(self, *_):
        # TODO: merge the contents of these tests into a single test (and fix the bug!)
        # WHEN relation data includes only _unlabeled_ alerts (no scrape_metadata)
        self.harness.update_relation_data(
            self.rel_id,
            "remote-app",
            {
                "alert_rules": json.dumps(self.UNLABELED_ALERT_RULES),
            },
        )

        # THEN rules filename is derived from the first (!) rule's group name
        # TODO derive filename from _sorted_ rules so it's deterministic?
        container = self.harness.charm.unit.get_container(self.harness.charm._name)
        files = container.list_files("/etc/prometheus/rules")
        self.assertEqual(
            {file.path for file in files},
            {f"/etc/prometheus/rules/juju_ZZZ_group_alerts_{RELATION_NAME}_{self.rel_id}.rules"},
        )


def raise_if_called(*_, **__):
    raise RuntimeError("This should not have been called")


@prom_multipatch
class TestPebblePlan(unittest.TestCase):
    """Test the pebble plan is kept up-to-date (situational awareness)."""

    @k8s_resource_multipatch
    @patch("lightkube.core.client.GenericSyncClient")
    @patch("prometheus_client.Prometheus.reload_configuration", lambda *_: True)
    @prom_multipatch
    def setUp(self, *_):
        self.harness = Harness(PrometheusCharm)
        self.addCleanup(self.harness.cleanup)

        patcher = patch.object(PrometheusCharm, "_get_pvc_capacity")
        self.mock_capacity = patcher.start()
        self.addCleanup(patcher.stop)
        self.harness.set_model_name(self.__class__.__name__)
        self.mock_capacity.return_value = "1Gi"
        self.harness.container_pebble_ready("prometheus")
        self.harness.handle_exec("prometheus", ["update-ca-certificates"], result=0)
        self.harness.begin_with_initial_hooks()

        self.container_name = self.harness.charm._name
        self.container = self.harness.charm.unit.get_container(self.container_name)

    @property
    def plan(self):
        return self.harness.get_container_pebble_plan("prometheus")

    @property
    def service(self):
        return self.container.get_service("prometheus")

    @k8s_resource_multipatch
    @patch("lightkube.core.client.GenericSyncClient")
    @patch.multiple(
        "ops._private.harness._TestingPebbleClient",
        start_services=raise_if_called,
        stop_services=raise_if_called,
        restart_services=raise_if_called,
    )
    @patch("prometheus_client.Prometheus.reload_configuration")
    def test_no_restart_nor_reload_when_nothing_changes(self, reload_config_patch, *_):
        """When nothing changes, calling `_configure()` shouldn't result in downtime."""
        # GIVEN a pebble plan
        initial_plan = self.plan
        self.assertTrue(self.service.is_running())

        for trigger in [
            lambda: self.harness.charm._configure(None),
            self.harness.charm.on.update_status.emit,
        ]:
            with self.subTest(trigger=trigger):
                # WHEN manually calling _configure or emitting update-status
                trigger()

                # THEN pebble service is unchanged
                current_plan = self.plan
                self.assertEqual(initial_plan.to_dict(), current_plan.to_dict())
                self.assertTrue(self.service.is_running())

                # AND workload (re)start is NOT attempted
                # (Patched pebble client would raise if (re)start was attempted.
                # Nothing else to do here.)

                # AND reload is not invoked
                reload_config_patch.assert_not_called()

    @k8s_resource_multipatch
    @patch("lightkube.core.client.GenericSyncClient")
    @patch.multiple(
        "ops._private.harness._TestingPebbleClient",
        start_services=raise_if_called,
        stop_services=raise_if_called,
        restart_services=raise_if_called,
    )
    @patch("prometheus_client.Prometheus.reload_configuration")
    def test_workload_hot_reloads_when_some_config_options_change(self, reload_config_patch, *_):
        """Some config options go into the config file and require a reload (not restart)."""
        # GIVEN a pebble plan
        initial_plan = self.plan
        self.assertTrue(self.service.is_running())

        # WHEN evaluation_interval is changed
        self.harness.update_config(unset=["evaluation_interval"])
        self.harness.update_config({"evaluation_interval": "1234s"})

        # THEN a reload is invoked
        reload_config_patch.assert_called()

        # BUT pebble service is unchanged
        current_plan = self.plan
        self.assertEqual(initial_plan.to_dict(), current_plan.to_dict())
        self.assertTrue(self.service.is_running())

        # AND workload (re)start is NOT attempted
        # (Patched pebble client would raise if (re)start was attempted. Nothing else to do here.)


@prom_multipatch
class TestTlsConfig(unittest.TestCase):
    @k8s_resource_multipatch
    @patch("lightkube.core.client.GenericSyncClient")
    @prom_multipatch
    def setUp(self, *_):
        self.harness = Harness(PrometheusCharm)
        self.addCleanup(self.harness.cleanup)

        self.rel_id = self.harness.add_relation(RELATION_NAME, "provider-app")
        self.harness.add_relation_unit(self.rel_id, "provider-app/0")

        patcher = patch.object(PrometheusCharm, "_get_pvc_capacity")
        self.mock_capacity = patcher.start()
        self.addCleanup(patcher.stop)
        self.harness.set_model_name(self.__class__.__name__)
        self.mock_capacity.return_value = "1Gi"
        self.harness.container_pebble_ready("prometheus")
        self.harness.handle_exec("prometheus", ["update-ca-certificates"], result=0)
        self.harness.begin_with_initial_hooks()

    @k8s_resource_multipatch
    @patch("lightkube.core.client.GenericSyncClient")
    @patch("prometheus_client.Prometheus.reload_configuration", lambda *_: True)
    def test_ca_file(self, *_):
        scrape_jobs = [
            {
                "job_name": "job1",
                "static_configs": [
                    {"targets": ["*:80"]},
                ],
                "tls_config": {"ca_file": "CA 1"},
            },
            {
                "job_name": "job2",
                "static_configs": [
                    {"targets": ["*:80"]},
                ],
                "tls_config": {
                    "ca_file": "CA 2",
                    "cert_file": "CLIENT CERT 2",
                    "key_file": "CLIENT KEY 2",
                },
            },
        ]

        self.harness.update_relation_data(
            self.rel_id,
            "provider-app",
            {
                "scrape_jobs": json.dumps(scrape_jobs),
            },
        )
        self.harness.update_relation_data(
            self.rel_id,
            "provider-app/0",
            {
                "prometheus_scrape_unit_address": "1.1.1.1",
                "prometheus_scrape_unit_name": "provider-app/0",
            },
        )

        self.harness.evaluate_status()
        self.assertIsInstance(self.harness.model.unit.status, ActiveStatus)
        container = self.harness.charm.unit.get_container("prometheus")
        self.assertEqual(container.pull("/etc/prometheus/job1-ca.crt").read(), "CA 1")
        self.assertEqual(container.pull("/etc/prometheus/job2-ca.crt").read(), "CA 2")
        self.assertEqual(container.pull("/etc/prometheus/job2-client.crt").read(), "CLIENT CERT 2")
        self.assertEqual(container.pull("/etc/prometheus/job2-client.key").read(), "CLIENT KEY 2")

    @k8s_resource_multipatch
    @patch("lightkube.core.client.GenericSyncClient")
    @patch("prometheus_client.Prometheus.reload_configuration", lambda *_: True)
    def test_no_tls_config(self, *_):
        scrape_jobs = [
            {
                "job_name": "job1",
                "static_configs": [
                    {"targets": ["*:80"]},
                ],
            },
        ]

        self.harness.update_relation_data(
            self.rel_id,
            "provider-app",
            {
                "scrape_jobs": json.dumps(scrape_jobs),
            },
        )
        self.harness.update_relation_data(
            self.rel_id,
            "provider-app/0",
            {
                "prometheus_scrape_unit_address": "1.1.1.1",
                "prometheus_scrape_unit_name": "provider-app/0",
            },
        )

        self.harness.evaluate_status()
        self.assertIsInstance(self.harness.model.unit.status, ActiveStatus)

    @k8s_resource_multipatch
    @patch("lightkube.core.client.GenericSyncClient")
    @patch("prometheus_client.Prometheus.reload_configuration", lambda *_: True)
    def test_tls_config_missing_cert(self, *_):
        scrape_jobs = [
            {
                "job_name": "job1",
                "static_configs": [
                    {"targets": ["*:80"]},
                ],
                "tls_config": {
                    "ca_file": "CA 1",
                    "key_file": "CLIENT KEY 1",
                },
            },
        ]

        self.harness.update_relation_data(
            self.rel_id,
            "provider-app",
            {
                "scrape_jobs": json.dumps(scrape_jobs),
            },
        )
        self.harness.update_relation_data(
            self.rel_id,
            "provider-app/0",
            {
                "prometheus_scrape_unit_address": "1.1.1.1",
                "prometheus_scrape_unit_name": "provider-app/0",
            },
        )

        self.harness.evaluate_status()
        self.assertIsInstance(self.harness.model.unit.status, BlockedStatus)

    @k8s_resource_multipatch
    @patch("lightkube.core.client.GenericSyncClient")
    @patch("prometheus_client.Prometheus.reload_configuration", lambda *_: True)
    def test_tls_config_missing_key(self, *_):
        scrape_jobs = [
            {
                "job_name": "job1",
                "static_configs": [
                    {"targets": ["*:80"]},
                ],
                "tls_config": {
                    "ca_file": "CA 1",
                    "cert_file": "CLIENT CERT 1",
                },
            },
        ]

        self.harness.update_relation_data(
            self.rel_id,
            "provider-app",
            {
                "scrape_jobs": json.dumps(scrape_jobs),
            },
        )
        self.harness.update_relation_data(
            self.rel_id,
            "provider-app/0",
            {
                "prometheus_scrape_unit_address": "1.1.1.1",
                "prometheus_scrape_unit_name": "provider-app/0",
            },
        )

        self.harness.evaluate_status()
        self.assertIsInstance(self.harness.model.unit.status, BlockedStatus)
