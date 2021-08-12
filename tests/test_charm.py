# Copyright 2020 Canonical Ltd.
# See LICENSE file for licensing details.

import unittest
import yaml
import json

from unittest.mock import patch
from ops.testing import Harness
from charm import PrometheusCharm

MINIMAL_CONFIG = {"prometheus-image-path": "prom/prometheus", "port": 9090}

SAMPLE_ALERTING_CONFIG = {
    "alertmanagers": [{"static_configs": [{"targets": ["192.168.0.1:9093"]}]}]
}


class TestCharm(unittest.TestCase):
    def setUp(self):
        self.harness = Harness(PrometheusCharm)
        self.addCleanup(self.harness.cleanup)
        self.harness.begin()

    @patch("ops.testing._TestingPebbleClient.push")
    @patch("ops.testing._TestingModelBackend.network_get")
    def test_grafana_is_provided_port_and_source(self, mock_net_get, _):
        self.harness.update_config(MINIMAL_CONFIG)
        IP = "1.1.1.1"
        net_info = {
            "bind-addresses": [{"interface-name": "ens1", "addresses": [{"value": IP}]}]
        }
        mock_net_get.return_value = net_info

        rel_id = self.harness.add_relation("grafana-source", "grafana")
        self.harness.add_relation_unit(rel_id, "grafana/0")
        grafana_host = self.harness.get_relation_data(
            rel_id, self.harness.model.unit.name
        )["grafana_source_host"]
        self.assertEqual(grafana_host, "{}:{}".format(IP, "9090"))

    @patch("ops.testing._TestingPebbleClient.push")
    def test_default_cli_log_level_is_info(self, _):
        self.harness.update_config(MINIMAL_CONFIG)
        plan = self.harness.get_container_pebble_plan("prometheus")
        self.assertEqual(cli_arg(plan, "--log.level"), "info")

    @patch("ops.testing._TestingPebbleClient.push")
    def test_invalid_log_level_defaults_to_debug(self, _):
        bad_log_config = MINIMAL_CONFIG.copy()
        bad_log_config["log-level"] = "bad-level"
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

    @patch("ops.testing._TestingPebbleClient.push")
    def test_valid_log_level_is_accepted(self, _):
        valid_log_config = MINIMAL_CONFIG.copy()
        valid_log_config["log-level"] = "warn"
        self.harness.update_config(valid_log_config)

        plan = self.harness.get_container_pebble_plan("prometheus")
        self.assertEqual(cli_arg(plan, "--log.level"), "warn")

    @patch("ops.testing._TestingPebbleClient.push")
    def test_tsdb_compression_is_not_enabled_by_default(self, _):
        compress_config = MINIMAL_CONFIG.copy()
        self.harness.update_config(compress_config)

        plan = self.harness.get_container_pebble_plan("prometheus")
        self.assertEqual(cli_arg(plan, "--storage.tsdb.wal-compression"), None)

    @patch("ops.testing._TestingPebbleClient.push")
    def test_tsdb_compression_can_be_enabled(self, _):
        compress_config = MINIMAL_CONFIG.copy()
        compress_config["tsdb-wal-compression"] = True
        self.harness.update_config(compress_config)

        plan = self.harness.get_container_pebble_plan("prometheus")
        self.assertEqual(
            cli_arg(plan, "--storage.tsdb.wal-compression"),
            "--storage.tsdb.wal-compression",
        )

    @patch("ops.testing._TestingPebbleClient.push")
    def test_valid_tsdb_retention_times_can_be_set(self, _):
        retention_time_config = MINIMAL_CONFIG.copy()
        acceptable_units = ["y", "w", "d", "h", "m", "s"]
        for unit in acceptable_units:
            retention_time = "{}{}".format(1, unit)
            retention_time_config["tsdb-retention-time"] = retention_time
            self.harness.update_config(retention_time_config)

            plan = self.harness.get_container_pebble_plan("prometheus")
            self.assertEqual(
                cli_arg(plan, "--storage.tsdb.retention.time"), retention_time
            )

    @patch("ops.testing._TestingPebbleClient.push")
    def test_invalid_tsdb_retention_times_can_not_be_set(self, _):
        retention_time_config = MINIMAL_CONFIG.copy()

        # invalid unit
        retention_time = "{}{}".format(1, "x")
        retention_time_config["tsdb-retention-time"] = retention_time
        with self.assertLogs(level="ERROR") as logger:
            self.harness.update_config(retention_time_config)
            expected_logs = ["ERROR:charm:Invalid unit x in time spec"]
            self.assertEqual(sorted(logger.output), expected_logs)

        plan = self.harness.get_container_pebble_plan("prometheus")
        self.assertEqual(cli_arg(plan, "--storage.tsdb.retention.time"), None)

        # invalid time value
        retention_time = "{}{}".format(0, "d")
        retention_time_config["tsdb-retention-time"] = retention_time
        with self.assertLogs(level="ERROR") as logger:
            self.harness.update_config(retention_time_config)
            expected_logs = ["ERROR:charm:Expected positive time spec but got 0"]
            self.assertEqual(sorted(logger.output), expected_logs)

        plan = self.harness.get_container_pebble_plan("prometheus")
        self.assertEqual(cli_arg(plan, "--storage.tsdb.retention.time"), None)

    @patch("ops.testing._TestingPebbleClient.push")
    def test_global_scrape_interval_can_be_set(self, push):
        scrapeint_config = MINIMAL_CONFIG.copy()
        acceptable_units = ["y", "w", "d", "h", "m", "s"]
        for unit in acceptable_units:
            scrapeint_config["scrape-interval"] = "{}{}".format(1, unit)
            self.harness.update_config(scrapeint_config)
            config = push.call_args[0]
            gconfig = global_config(config)
            self.assertEqual(
                gconfig["scrape_interval"], scrapeint_config["scrape-interval"]
            )
            push.reset()

    @patch("ops.testing._TestingPebbleClient.push")
    def test_global_scrape_timeout_can_be_set(self, push):
        scrapetime_config = MINIMAL_CONFIG.copy()
        acceptable_units = ["y", "w", "d", "h", "m", "s"]
        for unit in acceptable_units:
            scrapetime_config["scrape-timeout"] = "{}{}".format(1, unit)
            self.harness.update_config(scrapetime_config)
            config = push.call_args[0]
            gconfig = global_config(config)
            self.assertEqual(
                gconfig["scrape_timeout"], scrapetime_config["scrape-timeout"]
            )
            push.reset()

    @patch("ops.testing._TestingPebbleClient.push")
    def test_global_evaluation_interval_can_be_set(self, push):
        evalint_config = MINIMAL_CONFIG.copy()
        acceptable_units = ["y", "w", "d", "h", "m", "s"]
        for unit in acceptable_units:
            push.reset()
            evalint_config["evaluation-interval"] = "{}{}".format(1, unit)
            self.harness.update_config(evalint_config)
            config = push.call_args[0]
            gconfig = global_config(config)
            self.assertEqual(
                gconfig["evaluation_interval"], evalint_config["evaluation-interval"]
            )

    @patch("ops.testing._TestingPebbleClient.push")
    def test_valid_external_labels_can_be_set(self, push):
        label_config = MINIMAL_CONFIG.copy()
        labels = {"name1": "value1", "name2": "value2"}
        label_config["external-labels"] = json.dumps(labels)
        self.harness.update_config(label_config)
        config = push.call_args[0]
        gconfig = global_config(config)
        self.assertIsNotNone(gconfig["external_labels"])
        self.assertEqual(labels, gconfig["external_labels"])

    @patch("ops.testing._TestingPebbleClient.push")
    def test_invalid_external_labels_can_not_be_set(self, push):
        label_config = MINIMAL_CONFIG.copy()
        # label value must be string
        labels = {"name": 1}
        label_config["external-labels"] = json.dumps(labels)
        with self.assertLogs(level="ERROR") as logger:
            self.harness.update_config(label_config)
            expected_logs = ["ERROR:charm:External label keys/values must be strings"]
            self.assertEqual(sorted(logger.output), expected_logs)

        config = push.call_args[0]
        gconfig = global_config(config)
        self.assertIsNone(gconfig.get("external_labels"))

    @patch("ops.testing._TestingPebbleClient.push")
    def test_default_scrape_config_is_always_set(self, push):
        self.harness.update_config(MINIMAL_CONFIG)
        config = push.call_args[0]
        prometheus_scrape_config = scrape_config(config, "prometheus")
        self.assertIsNotNone(prometheus_scrape_config, "No default config found")

    @patch("prometheus_server.Prometheus.reload_configuration")
    @patch("ops.testing._TestingPebbleClient.push")
    def test_configuration_reload(self, push, trigger_configuration_reload):
        self.harness.update_config(MINIMAL_CONFIG)

        push.assert_called()
        trigger_configuration_reload.assert_not_called()

        label_config = MINIMAL_CONFIG.copy()
        labels = {"name1": "value1", "name2": "value2"}
        label_config["external-labels"] = json.dumps(labels)

        self.harness.update_config(label_config)

        trigger_configuration_reload.assert_called()


def alerting_config(config):
    config_yaml = config[1]
    config_dict = yaml.safe_load(config_yaml)
    return config_dict.get("alerting")


def global_config(config):
    config_yaml = config[1]
    config_dict = yaml.safe_load(config_yaml)
    return config_dict["global"]


def scrape_config(config, job_name):
    config_yaml = config[1]
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
