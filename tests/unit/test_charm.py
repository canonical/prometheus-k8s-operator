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
from helpers import FakeProcessVersionCheck, k8s_resource_multipatch
from ops.model import Container
from ops.testing import Harness

from charm import PROMETHEUS_CONFIG, PrometheusCharm

ops.testing.SIMULATE_CAN_CONNECT = True
logger = logging.getLogger(__name__)

RELATION_NAME = "metrics-endpoint"
DEFAULT_JOBS = [{"metrics_path": "/metrics"}]
SCRAPE_METADATA = {
    "model": "provider-model",
    "model_uuid": str(uuid.uuid4()),
    "application": "provider",
    "charm_name": "provider-charm",
}


class TestCharm(unittest.TestCase):
    @patch("charm.KubernetesServicePatch", lambda x, y: None)
    @k8s_resource_multipatch
    @patch("lightkube.core.client.GenericSyncClient")
    @patch.object(Container, "exec", new=FakeProcessVersionCheck)
    def setUp(self, *unused):
        self.harness = Harness(PrometheusCharm)
        self.addCleanup(self.harness.cleanup)

        patcher = patch.object(PrometheusCharm, "_get_pvc_capacity")
        self.mock_capacity = patcher.start()
        self.addCleanup(patcher.stop)
        self.harness.set_model_name("prometheus_model")
        self.mock_capacity.return_value = "1Gi"
        self.harness.begin_with_initial_hooks()
        self.harness.container_pebble_ready("prometheus")

    def test_grafana_is_provided_port_and_source(self):
        rel_id = self.harness.add_relation("grafana-source", "grafana")
        self.harness.add_relation_unit(rel_id, "grafana/0")
        fqdn = socket.getfqdn()
        grafana_host = self.harness.get_relation_data(rel_id, self.harness.model.unit.name)[
            "grafana_source_host"
        ]
        self.assertEqual(grafana_host, "http://{}:{}".format(fqdn, "9090"))

    @k8s_resource_multipatch
    @patch("lightkube.core.client.GenericSyncClient")
    def test_web_external_url_is_passed_to_grafana(self, *unused):
        self.harness.set_leader(True)
        self.harness.update_config({"web_external_url": "http://test:80/foo/bar"})

        grafana_rel_id = self.harness.add_relation("grafana-source", "grafana")
        self.harness.add_relation_unit(grafana_rel_id, "grafana/0")

        grafana_host = self.harness.get_relation_data(
            grafana_rel_id, self.harness.model.unit.name
        )["grafana_source_host"]

        self.assertEqual(grafana_host, "http://test:80/foo/bar")

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
            self.assertGreaterEqual(set(logger.output), expected_logs)

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

        plan = self.harness.get_container_pebble_plan("prometheus")
        fqdn = socket.getfqdn()
        self.assertEqual(cli_arg(plan, "--web.external-url"), f"http://{fqdn}:9090")

    @k8s_resource_multipatch
    @patch("lightkube.core.client.GenericSyncClient")
    def test_web_external_url_has_precedence_over_ingress_relation(self, *unused):
        self.harness.set_leader(True)

        self.harness.update_config({"web_external_url": "http://test:80"})

        rel_id = self.harness.add_relation("ingress", "traefik-ingress")
        self.harness.add_relation_unit(rel_id, "traefik-ingress/0")

        plan = self.harness.get_container_pebble_plan("prometheus")
        self.assertEqual(cli_arg(plan, "--web.external-url"), "http://test:80")

    @k8s_resource_multipatch
    @patch("lightkube.core.client.GenericSyncClient")
    def test_web_external_url_set(self, *unused):
        self.harness.set_leader(True)

        self.harness.update_config({"web_external_url": "http://test:80"})

        plan = self.harness.get_container_pebble_plan("prometheus")
        self.assertEqual(cli_arg(plan, "--web.external-url"), "http://test:80")

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
    @patch("prometheus_server.Prometheus.reload_configuration")
    @patch.object(Container, "exec", new=FakeProcessVersionCheck)
    def test_configuration_reload(self, trigger_configuration_reload, *unused):
        self.harness.update_config({"evaluation_interval": "1234m"})
        trigger_configuration_reload.assert_called()


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


def cli_arg(plan, cli_opt):
    plan_dict = plan.to_dict()
    args = plan_dict["services"]["prometheus"]["command"].split()
    for arg in args:
        opt_list = arg.split("=")
        if len(opt_list) == 2 and opt_list[0] == cli_opt:
            return opt_list[1]
        if len(opt_list) == 1 and opt_list[0] == cli_opt:
            return opt_list[0]
    return None


class TestConfigMaximumRetentionSize(unittest.TestCase):
    """Test the config.yaml option 'maximum_retention_size'."""

    def setUp(self):
        self.harness = Harness(PrometheusCharm)
        self.addCleanup(self.harness.cleanup)

        patcher = patch.object(PrometheusCharm, "_get_pvc_capacity")
        self.mock_capacity = patcher.start()
        self.addCleanup(patcher.stop)

    @patch("charm.KubernetesServicePatch", lambda x, y: None)
    @k8s_resource_multipatch
    @patch("lightkube.core.client.GenericSyncClient")
    @patch.object(Container, "exec", new=FakeProcessVersionCheck)
    def test_default_maximum_retention_size_is_80_percent(self, *unused):
        """This test is here to guarantee backwards compatibility.

        Since config.yaml provides a default (which forms a contract), we need to prevent changing
        it unintentionally.
        """
        # GIVEN a capacity limit in binary notation (k8s notation)
        self.mock_capacity.return_value = "1Gi"

        # AND the maximum_retention_size config is left unspecified (let it keep its default)
        # WHEN the charm starts
        self.harness.begin_with_initial_hooks()
        self.harness.container_pebble_ready("prometheus")

        # THEN the pebble plan has the adjusted capacity of 80%
        plan = self.harness.get_container_pebble_plan("prometheus")
        self.assertEqual(cli_arg(plan, "--storage.tsdb.retention.size"), "0.8GB")

    @patch("charm.KubernetesServicePatch", lambda x, y: None)
    @k8s_resource_multipatch
    @patch("lightkube.core.client.GenericSyncClient")
    @patch.object(Container, "exec", new=FakeProcessVersionCheck)
    def test_multiplication_factor_applied_to_pvc_capacity(self, *unused):
        """The `--storage.tsdb.retention.size` arg must be multiplied by maximum_retention_size."""
        # GIVEN a capacity limit in binary notation (k8s notation)
        self.mock_capacity.return_value = "1Gi"

        # AND a multiplication factor as a config option
        self.harness.update_config({"maximum_retention_size": "50%"})

        # WHEN the charm starts
        self.harness.begin_with_initial_hooks()
        self.harness.container_pebble_ready("prometheus")

        # THEN the pebble plan the adjusted capacity
        plan = self.harness.get_container_pebble_plan("prometheus")
        self.assertEqual(cli_arg(plan, "--storage.tsdb.retention.size"), "0.5GB")


class TestAlertsFilename(unittest.TestCase):
    REMOTE_SCRAPE_METADATA = {
        "model": "remote-model",
        "model_uuid": "f299585c-9ac6-4b0c-ae06-46d1be2a7262",
        "application": "remote-app",
        "charm_name": "remote-charm",
    }

    LABELED_ALERT_RULES = {
        "groups": [
            {
                "name": "ZZZ_f2c1b2a6-e006-11eb-ba80-0242ac130004_consumer-tester_alerts",
                "rules": [
                    {
                        "alert": "CPUOverUse",
                        "expr": "process_cpu_seconds_total > 0.12",
                        "labels": {
                            "severity": "Low",
                            "juju_model": "ZZZ-model",
                            "juju_model_uuid": "f2c1b2a6-e006-11eb-ba80-0242ac130004",
                            "juju_application": "zzz-app",
                        },
                    },
                ],
            },
            {
                "name": "AAA_f2c1b2a6-e006-11eb-ba80-0242ac130004_consumer-tester_alerts",
                "rules": [
                    {
                        "alert": "PrometheusTargetMissing",
                        "expr": "up == 0",
                        "labels": {
                            "severity": "critical",
                            "juju_model": "AAA-model",
                            "juju_model_uuid": "f2c1b2a6-e006-11eb-ba80-0242ac130004",
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

    @patch("charm.KubernetesServicePatch", lambda x, y: None)
    @k8s_resource_multipatch
    @patch("lightkube.core.client.GenericSyncClient")
    @patch("prometheus_server.Prometheus.reload_configuration", lambda *_: True)
    @patch.object(Container, "exec", new=FakeProcessVersionCheck)
    def setUp(self, *unused):
        self.harness = Harness(PrometheusCharm)
        self.addCleanup(self.harness.cleanup)

        patcher = patch.object(PrometheusCharm, "_get_pvc_capacity")
        self.mock_capacity = patcher.start()
        self.addCleanup(patcher.stop)
        self.harness.set_model_name("prometheus_model")
        self.mock_capacity.return_value = "1Gi"
        self.harness.begin_with_initial_hooks()
        self.harness.container_pebble_ready("prometheus")

        self.rel_id = self.harness.add_relation(RELATION_NAME, "remote-app")
        self.harness.add_relation_unit(self.rel_id, "remote-app/0")

    @patch("charm.KubernetesServicePatch", lambda x, y: None)
    @k8s_resource_multipatch
    @patch("lightkube.core.client.GenericSyncClient")
    @patch("prometheus_server.Prometheus.reload_configuration", lambda *_: True)
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

        # THEN rules filename is derived from the contents of scrape_metadata
        container = self.harness.charm.unit.get_container(self.harness.charm._name)
        files = container.list_files("/etc/prometheus/rules")
        self.assertEqual(
            {file.path for file in files},
            {"/etc/prometheus/rules/juju_remote-model_f299585c_remote-app.rules"},
        )

    @patch("charm.KubernetesServicePatch", lambda x, y: None)
    @k8s_resource_multipatch
    @patch("lightkube.core.client.GenericSyncClient")
    @patch("prometheus_server.Prometheus.reload_configuration", lambda *_: True)
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
                "/etc/prometheus/rules/juju_ZZZ-model_f2c1b2a6-e006-11eb-ba80-0242ac130004_zzz-app.rules"
            },
        )

    @patch("charm.KubernetesServicePatch", lambda x, y: None)
    @k8s_resource_multipatch
    @patch("lightkube.core.client.GenericSyncClient")
    @patch("prometheus_server.Prometheus.reload_configuration", lambda *_: True)
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
            {"/etc/prometheus/rules/juju_remote-model_f299585c_remote-app.rules"},
        )

    @patch("charm.KubernetesServicePatch", lambda x, y: None)
    @k8s_resource_multipatch
    @patch("lightkube.core.client.GenericSyncClient")
    @patch("prometheus_server.Prometheus.reload_configuration", lambda *_: True)
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
            {file.path for file in files}, {"/etc/prometheus/rules/juju_ZZZ_group_alerts.rules"}
        )


def raise_if_called(*_, **__):
    raise RuntimeError("This should not have been called")


class TestPebblePlan(unittest.TestCase):
    """Test the pebble plan is kept up-to-date (situational awareness)."""

    @patch("charm.KubernetesServicePatch", lambda x, y: None)
    @k8s_resource_multipatch
    @patch("lightkube.core.client.GenericSyncClient")
    @patch("prometheus_server.Prometheus.reload_configuration", lambda *_: True)
    @patch.object(Container, "exec", new=FakeProcessVersionCheck)
    def setUp(self, *_):
        self.harness = Harness(PrometheusCharm)
        self.addCleanup(self.harness.cleanup)

        patcher = patch.object(PrometheusCharm, "_get_pvc_capacity")
        self.mock_capacity = patcher.start()
        self.addCleanup(patcher.stop)
        self.harness.set_model_name(self.__class__.__name__)
        self.mock_capacity.return_value = "1Gi"
        self.harness.begin_with_initial_hooks()
        self.harness.container_pebble_ready("prometheus")

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
        "ops.testing._TestingPebbleClient",
        autostart_services=raise_if_called,
        replan_services=raise_if_called,
        start_services=raise_if_called,
        stop_services=raise_if_called,
        restart_services=raise_if_called,
    )
    @patch("prometheus_server.Prometheus.reload_configuration")
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
    @patch("socket.getfqdn", new=lambda *args: "fqdn")
    @patch("ops.testing._TestingPebbleClient.replan_services")
    @patch("ops.testing._TestingPebbleClient.start_services")
    @patch("ops.testing._TestingPebbleClient.restart_services")
    @patch("prometheus_server.Prometheus.reload_configuration")
    def test_workload_restarts_when_some_config_options_change(
        self, reload_config, restart, start, replan, *_
    ):
        """Some config options go in as cli args and require workload restart."""
        # GIVEN a pebble plan
        first_plan = self.plan
        self.assertTrue(self.service.is_running())

        # WHEN web_external_url is set
        self.harness.update_config({"web_external_url": "http://test:80/foo/bar"})

        # THEN pebble service is updated
        second_plan = self.plan
        self.assertEqual(cli_arg(second_plan, "--web.external-url"), "http://test:80/foo/bar")
        self.assertNotEqual(first_plan.to_dict(), second_plan.to_dict())

        # AND workload is restarted
        self.assertTrue(self.service.is_running())
        self.assertTrue(restart.called or start.called or replan.called)
        restart.reset_mock()
        start.reset_mock()
        replan.reset_mock()

        # BUT reload is not invoked
        reload_config.assert_not_called()

        # WHEN web_external_url is changed
        self.harness.update_config({"web_external_url": "http://test:80/foo/bar/baz"})

        # THEN pebble service is updated
        third_plan = self.plan
        self.assertEqual(cli_arg(third_plan, "--web.external-url"), "http://test:80/foo/bar/baz")
        self.assertNotEqual(second_plan.to_dict(), third_plan.to_dict())

        # AND workload is restarted
        self.assertTrue(self.service.is_running())
        self.assertTrue(restart.called or start.called or replan.called)
        restart.reset_mock()
        start.reset_mock()
        replan.reset_mock()

        # BUT reload is not invoked
        reload_config.assert_not_called()

        # WHEN web_external_url is unset
        self.harness.update_config(unset=["web_external_url"])

        # THEN pebble service is updated
        fourth_plan = self.plan
        self.assertEqual(cli_arg(fourth_plan, "--web.external-url"), "http://fqdn:9090")
        self.assertNotEqual(third_plan.to_dict(), fourth_plan.to_dict())

        # AND workload is restarted
        self.assertTrue(self.service.is_running())
        self.assertTrue(restart.called or start.called or replan.called)
        restart.reset_mock()
        start.reset_mock()
        replan.reset_mock()

        # BUT reload is not invoked
        reload_config.assert_not_called()

    @k8s_resource_multipatch
    @patch("lightkube.core.client.GenericSyncClient")
    @patch.multiple(
        "ops.testing._TestingPebbleClient",
        autostart_services=raise_if_called,
        replan_services=raise_if_called,
        start_services=raise_if_called,
        stop_services=raise_if_called,
        restart_services=raise_if_called,
    )
    @patch("prometheus_server.Prometheus.reload_configuration")
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


@patch("charms.observability_libs.v0.juju_topology.JujuTopology.is_valid_uuid", lambda *args: True)
class TestTlsConfig(unittest.TestCase):
    @patch("charm.KubernetesServicePatch", lambda x, y: None)
    @k8s_resource_multipatch
    @patch("lightkube.core.client.GenericSyncClient")
    @patch.object(Container, "exec", new=FakeProcessVersionCheck)
    def setUp(self, *_):
        self.harness = Harness(PrometheusCharm)
        self.addCleanup(self.harness.cleanup)

        self.rel_id = self.harness.add_relation(RELATION_NAME, "provider-app")
        self.harness.add_relation_unit(self.rel_id, "provider-app/0")

        self.harness.begin_with_initial_hooks()
        self.harness.container_pebble_ready("prometheus")

    @k8s_resource_multipatch
    @patch("lightkube.core.client.GenericSyncClient")
    @patch("prometheus_server.Prometheus.reload_configuration", lambda *_: True)
    @patch.object(Container, "exec", new=FakeProcessVersionCheck)
    def test_ca_file(self, *_):
        scrape_jobs = [
            {
                "job_name": "job1",
                "static_configs": [
                    {"targets": ["*:80"]},
                ],
                "tls_config": {"ca_file": "CERT DATA 1"},
            },
            {
                "job_name": "job2",
                "static_configs": [
                    {"targets": ["*:80"]},
                ],
                "tls_config": {"ca_file": "CERT DATA 2"},
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

        container = self.harness.charm.unit.get_container("prometheus")
        self.assertEqual(container.pull("/etc/prometheus/job1.crt").read(), "CERT DATA 1")
        self.assertEqual(container.pull("/etc/prometheus/job2.crt").read(), "CERT DATA 2")

    @k8s_resource_multipatch
    @patch("lightkube.core.client.GenericSyncClient")
    @patch("prometheus_server.Prometheus.reload_configuration", lambda *_: True)
    @patch.object(Container, "exec", new=FakeProcessVersionCheck)
    def test_insecure_skip_verify(self, *_):
        scrape_jobs = [
            {
                "job_name": "job1",
                "static_configs": [
                    {"targets": ["*:80"]},
                ],
                "tls_config": {"insecure_skip_verify": False},
            },
            {
                "job_name": "job2",
                "static_configs": [
                    {"targets": ["*:80"]},
                ],
                "tls_config": {"insecure_skip_verify": True},
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

        container = self.harness.charm.unit.get_container("prometheus")
        config_on_disk = container.pull("/etc/prometheus/prometheus.yml").read()
        as_dict = yaml.safe_load(config_on_disk)
        tls_subset = {
            d["job_name"]: d["tls_config"]["insecure_skip_verify"]
            for d in as_dict["scrape_configs"]
            if "tls_config" in d
        }
        self.assertEqual(tls_subset["job1"], False)
        self.assertEqual(tls_subset["job2"], True)

