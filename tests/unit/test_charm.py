# Copyright 2020 Canonical Ltd.
# See LICENSE file for licensing details.

import json
import socket
import unittest
import uuid
from unittest.mock import Mock, patch

import yaml
from ops.testing import Harness

from charm import PROMETHEUS_CONFIG, PrometheusCharm

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
    def setUp(self, *unused):
        self.harness = Harness(PrometheusCharm)
        self.addCleanup(self.harness.cleanup)

        patcher = patch.object(PrometheusCharm, "_get_pvc_capacity")
        self.mock_capacity = patcher.start()
        self.addCleanup(patcher.stop)
        self.harness.set_model_name("prometheus_model")
        self.mock_capacity.return_value = "1Gi"
        self.harness.begin_with_initial_hooks()

    def test_grafana_is_provided_port_and_source(self):
        rel_id = self.harness.add_relation("grafana-source", "grafana")
        self.harness.add_relation_unit(rel_id, "grafana/0")
        fqdn = socket.getfqdn()
        grafana_host = self.harness.get_relation_data(rel_id, self.harness.model.unit.name)[
            "grafana_source_host"
        ]
        self.assertEqual(grafana_host, "http://{}:{}".format(fqdn, "9090"))

    def test_web_external_url_is_passed_to_grafana(self):
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

    def test_invalid_log_level_defaults_to_debug(self):
        bad_log_config = {"log_level": "bad-level"}
        with self.assertLogs(level="ERROR") as logger:
            self.harness.update_config(bad_log_config)
            expected_logs = {
                "ERROR:root:Invalid loglevel: bad-level given, "
                "debug/info/warn/error/fatal allowed. "
                "defaulting to DEBUG loglevel."
            }
            self.assertGreaterEqual(set(logger.output), expected_logs)

        plan = self.harness.get_container_pebble_plan("prometheus")
        self.assertEqual(cli_arg(plan, "--log.level"), "debug")

    def test_valid_log_level_is_accepted(self):
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

    def test_web_external_url_has_precedence_over_ingress_relation(self):
        self.harness.set_leader(True)

        self.harness.update_config({"web_external_url": "http://test:80"})

        rel_id = self.harness.add_relation("ingress", "traefik-ingress")
        self.harness.add_relation_unit(rel_id, "traefik-ingress/0")

        plan = self.harness.get_container_pebble_plan("prometheus")
        self.assertEqual(cli_arg(plan, "--web.external-url"), "http://test:80")

    def test_web_external_url_set(self):
        self.harness.set_leader(True)

        self.harness.update_config({"web_external_url": "http://test:80"})

        plan = self.harness.get_container_pebble_plan("prometheus")
        self.assertEqual(cli_arg(plan, "--web.external-url"), "http://test:80")

    def test_metrics_wal_compression_is_not_enabled_by_default(self):
        plan = self.harness.get_container_pebble_plan("prometheus")
        self.assertEqual(cli_arg(plan, "--storage.tsdb.wal-compression"), None)

    def test_metrics_wal_compression_can_be_enabled(self):
        compress_config = {"metrics_wal_compression": True}
        self.harness.update_config(compress_config)

        plan = self.harness.get_container_pebble_plan("prometheus")
        self.assertEqual(
            cli_arg(plan, "--storage.tsdb.wal-compression"),
            "--storage.tsdb.wal-compression",
        )

    def test_valid_metrics_retention_times_can_be_set(self):
        retention_time_config = {}
        acceptable_units = ["y", "w", "d", "h", "m", "s"]
        for unit in acceptable_units:
            retention_time = "{}{}".format(1, unit)
            retention_time_config["metrics_retention_time"] = retention_time
            self.harness.update_config(retention_time_config)

            plan = self.harness.get_container_pebble_plan("prometheus")
            self.assertEqual(cli_arg(plan, "--storage.tsdb.retention.time"), retention_time)

    def test_invalid_metrics_retention_times_can_not_be_set(self):
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

    def test_global_evaluation_interval_can_be_set(self):
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

    def test_honor_labels_is_always_set_in_scrape_configs(self):
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

        prometheus_scrape_config = yaml.safe_load(self.harness.charm._prometheus_config())
        for job in prometheus_scrape_config["scrape_configs"]:
            if job["job_name"] != "prometheus":
                self.assertIn("honor_labels", job)
                self.assertTrue(job["honor_labels"])

    @patch("prometheus_server.Prometheus.reload_configuration")
    def test_configuration_reload(self, trigger_configuration_reload):
        self.harness.container_pebble_ready("prometheus")

        trigger_configuration_reload.assert_called()

        self.harness.update_config({"log_level": "INFO"})
        trigger_configuration_reload.assert_called()

    @patch("prometheus_server.Prometheus.reload_configuration", Mock())
    def test_given_prometheus_configurer_pebble_ready_when_get_plan_then_plan_contains_updated_pebble_layer(  # noqa: E501
        self,
    ):
        expected_plan = {
            "services": {
                "prometheus-configurer": {
                    "override": "replace",
                    "startup": "enabled",
                    "command": "prometheus_configurer "
                    "-port=9100 "
                    "-rules-dir=/etc/prometheus/rules/ "
                    "-prometheusURL=magma-orc8r-prometheus:9090 "
                    "-multitenant-label=networkID "
                    "-restrict-queries",
                }
            }
        }
        self.harness.container_pebble_ready("prometheus-configurer")

        updated_plan = self.harness.get_container_pebble_plan("prometheus-configurer").to_dict()
        self.assertEqual(expected_plan, updated_plan)


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
    def test_default_maximum_retention_size_is_80_percent(self):
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
    def test_multiplication_factor_applied_to_pvc_capacity(self):
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
