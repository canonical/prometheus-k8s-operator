# Copyright 2020 Canonical Ltd.
# See LICENSE file for licensing details.

import unittest
from unittest.mock import patch

import yaml
from ops.testing import Harness

from charm import PROMETHEUS_CONFIG, PrometheusCharm

MINIMAL_CONFIG = {}

SAMPLE_ALERTING_CONFIG = {
    "alertmanagers": [{"static_configs": [{"targets": ["192.168.0.1:9093"]}]}]
}


class TestCharm(unittest.TestCase):
    @patch("charm.KubernetesServicePatch", lambda x, y: None)
    def setUp(self):
        self.harness = Harness(PrometheusCharm)
        self.addCleanup(self.harness.cleanup)
        self.harness.begin()

    @patch("ops.testing._TestingModelBackend.network_get")
    def test_grafana_is_provided_port_and_source(self, mock_net_get):
        self.harness.update_config(MINIMAL_CONFIG)
        ip = "1.1.1.1"
        net_info = {"bind-addresses": [{"interface-name": "ens1", "addresses": [{"value": ip}]}]}
        mock_net_get.return_value = net_info

        rel_id = self.harness.add_relation("grafana-source", "grafana")
        self.harness.add_relation_unit(rel_id, "grafana/0")
        grafana_host = self.harness.get_relation_data(rel_id, self.harness.model.unit.name)[
            "grafana_source_host"
        ]
        self.assertEqual(grafana_host, "{}:{}".format(ip, "9090"))

    def test_default_cli_log_level_is_info(self):
        self.harness.update_config(MINIMAL_CONFIG)
        plan = self.harness.get_container_pebble_plan("prometheus")
        self.assertEqual(cli_arg(plan, "--log.level"), "info")

    def test_invalid_log_level_defaults_to_debug(self):
        bad_log_config = MINIMAL_CONFIG.copy()
        bad_log_config["log_level"] = "bad-level"
        with self.assertLogs(level="ERROR") as logger:
            self.harness.update_config(bad_log_config)
            expected_logs = [
                "ERROR:root:Invalid loglevel: bad-level given, "
                "debug/info/warn/error/fatal allowed. "
                "defaulting to DEBUG loglevel."
            ]
            self.assertEqual(sorted(logger.output), expected_logs)

        plan = self.harness.get_container_pebble_plan("prometheus")
        self.assertEqual(cli_arg(plan, "--log.level"), "debug")

    def test_valid_log_level_is_accepted(self):
        valid_log_config = MINIMAL_CONFIG.copy()
        valid_log_config["log_level"] = "warn"
        self.harness.update_config(valid_log_config)

        plan = self.harness.get_container_pebble_plan("prometheus")
        self.assertEqual(cli_arg(plan, "--log.level"), "warn")

    def test_ingress_relation_not_set(self):
        self.harness.set_leader(True)

        valid_log_config = MINIMAL_CONFIG.copy()
        self.harness.update_config(valid_log_config)

        plan = self.harness.get_container_pebble_plan("prometheus")
        self.assertIsNone(cli_arg(plan, "--web.external-url"))

    def test_ingress_relation_set(self):
        self.harness.set_leader(True)

        self.harness.update_config(MINIMAL_CONFIG.copy())

        rel_id = self.harness.add_relation("ingress", "ingress")
        self.harness.add_relation_unit(rel_id, "ingress/0")

        plan = self.harness.get_container_pebble_plan("prometheus")
        self.assertEqual(
            cli_arg(plan, "--web.external-url"),
            "http://prometheus-k8s:9090",
        )

    def test_metrics_wal_compression_is_not_enabled_by_default(self):
        compress_config = MINIMAL_CONFIG.copy()
        self.harness.update_config(compress_config)

        plan = self.harness.get_container_pebble_plan("prometheus")
        self.assertEqual(cli_arg(plan, "--storage.tsdb.wal-compression"), None)

    def test_metrics_wal_compression_can_be_enabled(self):
        compress_config = MINIMAL_CONFIG.copy()
        compress_config["metrics_wal_compression"] = True
        self.harness.update_config(compress_config)

        plan = self.harness.get_container_pebble_plan("prometheus")
        self.assertEqual(
            cli_arg(plan, "--storage.tsdb.wal-compression"),
            "--storage.tsdb.wal-compression",
        )

    def test_valid_metrics_retention_times_can_be_set(self):
        retention_time_config = MINIMAL_CONFIG.copy()
        acceptable_units = ["y", "w", "d", "h", "m", "s"]
        for unit in acceptable_units:
            retention_time = "{}{}".format(1, unit)
            retention_time_config["metrics_retention_time"] = retention_time
            self.harness.update_config(retention_time_config)

            plan = self.harness.get_container_pebble_plan("prometheus")
            self.assertEqual(cli_arg(plan, "--storage.tsdb.retention.time"), retention_time)

    def test_invalid_metrics_retention_times_can_not_be_set(self):
        retention_time_config = MINIMAL_CONFIG.copy()

        # invalid unit
        retention_time = "1x"
        retention_time_config["metrics_retention_time"] = retention_time

        self.harness.update_config(retention_time_config)
        plan = self.harness.get_container_pebble_plan("prometheus")
        self.assertEqual(cli_arg(plan, "--storage.tsdb.retention.time"), None)

        # invalid time value
        retention_time = "0d"
        retention_time_config["metrics_retention_time"] = retention_time

        self.harness.update_config(retention_time_config)
        plan = self.harness.get_container_pebble_plan("prometheus")
        self.assertEqual(cli_arg(plan, "--storage.tsdb.retention.time"), None)

    def test_global_evaluation_interval_can_be_set(self):
        evalint_config = MINIMAL_CONFIG.copy()
        acceptable_units = ["y", "w", "d", "h", "m", "s"]
        for unit in acceptable_units:
            evalint_config["evaluation_interval"] = "{}{}".format(1, unit)
            self.harness.update_config(evalint_config)
            container = self.harness.charm.unit.get_container(self.harness.charm._name)
            config = container.pull(PROMETHEUS_CONFIG)
            gconfig = global_config(config)
            self.assertEqual(gconfig["evaluation_interval"], evalint_config["evaluation_interval"])

    def test_default_scrape_config_is_always_set(self):
        self.harness.update_config(MINIMAL_CONFIG)
        container = self.harness.charm.unit.get_container(self.harness.charm._name)
        config = container.pull(PROMETHEUS_CONFIG)
        prometheus_scrape_config = scrape_config(config, "prometheus")
        self.assertIsNotNone(prometheus_scrape_config, "No default config found")

    @patch("prometheus_server.Prometheus.reload_configuration")
    def test_configuration_reload(self, trigger_configuration_reload):
        self.harness.container_pebble_ready("prometheus")

        self.harness.update_config(MINIMAL_CONFIG)
        trigger_configuration_reload.assert_called()

        self.harness.update_config({"log_level": "INFO"})
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
