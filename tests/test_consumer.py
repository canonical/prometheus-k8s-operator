# Copyright 2020 Canonical Ltd.
# See LICENSE file for licensing details.

import json
import re
import unittest
from unittest.mock import patch

from ops.charm import CharmBase
from ops.framework import StoredState

from ops.testing import Harness
from charms.prometheus_k8s.v0.prometheus import MetricsEndpointProvider


RELATION_NAME = "metrics-endpoint"
CONSUMER_SERVICE = "prometheus_tester"
CONSUMER_META = f"""
name: consumer-tester
containers:
  prometheus-tester:
requires:
  {RELATION_NAME}:
    interface: prometheus_scrape
"""
JOBS = [
    {
        "global": {"scrape_interval": "1h"},
        "rule_files": ["/some/file"],
        "file_sd_configs": [{"files": "*some-files*"}],
        "job_name": "my-first-job",
        "metrics_path": "one-path",
        "static_configs": [
            {
                "targets": ["10.1.238.1:6000", "*:7000"],
                "labels": {"some-key": "some-value"},
            }
        ],
    },
    {
        "job_name": "my-second-job",
        "metrics_path": "another-path",
        "static_configs": [
            {"targets": ["*:8000"], "labels": {"some-other-key": "some-other-value"}}
        ],
    },
]
ALLOWED_KEYS = {"job_name", "metrics_path", "static_configs"}


class ConsumerCharm(CharmBase):
    _stored = StoredState()

    def __init__(self, *args, **kwargs):
        super().__init__(*args)

        self.provider = MetricsEndpointProvider(
            self,
            RELATION_NAME,
            service_event=self.on.prometheus_tester_pebble_ready,
            jobs=JOBS,
        )
        self.provider._ALERT_RULES_PATH = "./tests/prometheus_alert_rules"


class TestConsumer(unittest.TestCase):
    def setUp(self):
        self.harness = Harness(ConsumerCharm, meta=CONSUMER_META)
        self.addCleanup(self.harness.cleanup)
        self.harness.set_leader(True)
        self.harness.begin()

    @patch("ops.testing._TestingModelBackend.network_get")
    def test_consumer_sets_scrape_metadata(self, _):
        rel_id = self.harness.add_relation(RELATION_NAME, "provider")
        self.harness.add_relation_unit(rel_id, "provider/0")
        data = self.harness.get_relation_data(rel_id, self.harness.model.app.name)
        self.assertIn("scrape_metadata", data)
        scrape_metadata = data["scrape_metadata"]
        self.assertIn("model", scrape_metadata)
        self.assertIn("model_uuid", scrape_metadata)
        self.assertIn("application", scrape_metadata)

    @patch("ops.testing._TestingModelBackend.network_get")
    def test_consumer_unit_sets_bind_address_on_pebble_ready(self, mock_net_get):
        bind_address = "192.0.8.2"
        fake_network = {
            "bind-addresses": [
                {
                    "interface-name": "eth0",
                    "addresses": [{"hostname": "prometheus-tester-0", "value": bind_address}],
                }
            ]
        }
        mock_net_get.return_value = fake_network
        rel_id = self.harness.add_relation(RELATION_NAME, "provider")
        self.harness.container_pebble_ready("prometheus-tester")
        data = self.harness.get_relation_data(rel_id, self.harness.charm.unit.name)
        self.assertIn("prometheus_scrape_host", data)
        self.assertEqual(data["prometheus_scrape_host"], bind_address)

    @patch("ops.testing._TestingModelBackend.network_get")
    def test_consumer_unit_sets_bind_address_on_relation_joined(self, mock_net_get):
        bind_address = "192.0.8.2"
        fake_network = {
            "bind-addresses": [
                {
                    "interface-name": "eth0",
                    "addresses": [{"hostname": "prometheus-tester-0", "value": bind_address}],
                }
            ]
        }
        mock_net_get.return_value = fake_network
        rel_id = self.harness.add_relation(RELATION_NAME, "provider")
        self.harness.add_relation_unit(rel_id, "provider/0")
        data = self.harness.get_relation_data(rel_id, self.harness.charm.unit.name)
        self.assertIn("prometheus_scrape_host", data)
        self.assertEqual(data["prometheus_scrape_host"], bind_address)

    @patch("ops.testing._TestingModelBackend.network_get")
    def test_consumer_supports_multiple_jobs(self, _):
        rel_id = self.harness.add_relation(RELATION_NAME, "provider")
        self.harness.add_relation_unit(rel_id, "provider/0")
        data = self.harness.get_relation_data(rel_id, self.harness.model.app.name)
        self.assertIn("scrape_jobs", data)
        jobs = json.loads(data["scrape_jobs"])
        self.assertEqual(len(jobs), len(JOBS))
        names = [job["job_name"] for job in jobs]
        job_names = [job["job_name"] for job in JOBS]
        self.assertListEqual(names, job_names)

    @patch("ops.testing._TestingModelBackend.network_get")
    def test_consumer_sanitizes_jobs(self, _):
        rel_id = self.harness.add_relation(RELATION_NAME, "provider")
        self.harness.add_relation_unit(rel_id, "provider/0")
        data = self.harness.get_relation_data(rel_id, self.harness.model.app.name)
        self.assertIn("scrape_jobs", data)
        jobs = json.loads(data["scrape_jobs"])
        for job in jobs:
            keys = set(job.keys())
            self.assertTrue(keys.issubset(ALLOWED_KEYS))

    @patch("ops.testing._TestingModelBackend.network_get")
    def test_each_alert_rule_is_topology_labeled(self, _):
        rel_id = self.harness.add_relation(RELATION_NAME, "provider")
        self.harness.add_relation_unit(rel_id, "provider/0")
        data = self.harness.get_relation_data(rel_id, self.harness.model.app.name)
        self.assertIn("alert_rules", data)
        alerts = json.loads(data["alert_rules"])
        self.assertIn("groups", alerts)
        self.assertEqual(len(alerts["groups"]), 1)
        group = alerts["groups"][0]
        for rule in group["rules"]:
            self.assertIn("labels", rule)
            labels = rule["labels"]
            self.assertIn("juju_model", labels)
            self.assertIn("juju_application", labels)
            self.assertIn("juju_model_uuid", labels)

    @patch("ops.testing._TestingModelBackend.network_get")
    def test_each_alert_expression_is_topology_labeled(self, _):
        rel_id = self.harness.add_relation(RELATION_NAME, "provider")
        self.harness.add_relation_unit(rel_id, "provider/0")
        data = self.harness.get_relation_data(rel_id, self.harness.model.app.name)
        self.assertIn("alert_rules", data)
        alerts = json.loads(data["alert_rules"])
        self.assertIn("groups", alerts)
        self.assertEqual(len(alerts["groups"]), 1)
        group = alerts["groups"][0]
        for rule in group["rules"]:
            self.assertIn("expr", rule)
            for labels in expression_labels(rule["expr"]):
                self.assertIn("juju_model", labels)
                self.assertIn("juju_model_uuid", labels)
                self.assertIn("juju_application", labels)


class TestBadConsumers(unittest.TestCase):
    def setUp(self):
        self.harness = Harness(ConsumerCharm, meta=CONSUMER_META)
        self.addCleanup(self.harness.cleanup)
        self.harness.set_leader(True)
        self.harness.begin()

    @patch("ops.testing._TestingModelBackend.network_get")
    def test_a_bad_alert_expression_logs_an_error(self, _):
        self.harness.charm.provider._ALERT_RULES_PATH = "./tests/bad_alert_expressions"

        with self.assertLogs(level="ERROR") as logger:
            rel_id = self.harness.add_relation(RELATION_NAME, "provider")
            self.harness.add_relation_unit(rel_id, "provider/0")
            messages = sorted(logger.output)
            self.assertEqual(len(messages), 1)
            self.assertIn("Invalid alert expression in PrometheusTargetMissing", messages[0])

    @patch("ops.testing._TestingModelBackend.network_get")
    def test_a_bad_alert_rules_logs_an_error(self, _):
        self.harness.charm.provider._ALERT_RULES_PATH = "./tests/bad_alert_rules"

        with self.assertLogs(level="ERROR") as logger:
            rel_id = self.harness.add_relation(RELATION_NAME, "provider")
            self.harness.add_relation_unit(rel_id, "provider/0")
            messages = sorted(logger.output)
            self.assertEqual(len(messages), 1)
            self.assertIn("Failed to read alert rules from bad_yaml.rule", messages[0])


def expression_labels(expr):
    """Extract labels from an alert rule expression.

    Args:
        expr: a string representing an alert expression.

    Returns:
        a generator which yields each set of labels in
        in the expression.
    """
    pattern = re.compile(r"\{.*\}")
    matches = pattern.findall(expr)
    for match in matches:
        match = match.replace("=", '":').replace("juju_", '"juju_')
        labels = json.loads(match)
        yield labels
