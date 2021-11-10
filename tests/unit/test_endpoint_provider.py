# Copyright 2020 Canonical Ltd.
# See LICENSE file for licensing details.

import functools
import json
import os
import re
import unittest
from unittest.mock import patch

import yaml
from charms.prometheus_k8s.v0.prometheus_scrape import (
    ALLOWED_KEYS,
    AlertRules,
    JujuTopology,
    MetricsEndpointProvider,
    RelationInterfaceMismatchError,
    RelationNotFoundError,
    RelationRoleMismatchError,
)
from deepdiff import DeepDiff
from ops.charm import CharmBase
from ops.framework import StoredState
from ops.testing import Harness

from .helpers import Sandbox

RELATION_NAME = "metrics-endpoint"
PROVIDER_META = f"""
name: provider-tester
containers:
  prometheus-tester:
provides:
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
        "scrape_interval": "1s",
        "disallowed_key": "irrelavent_value",
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


class EndpointProviderCharm(CharmBase):
    _stored = StoredState()

    def __init__(self, *args, **kwargs):
        super().__init__(*args)

        self.provider = MetricsEndpointProvider(
            self, jobs=JOBS, alert_rules_path="./tests/unit/prometheus_alert_rules"
        )


class TestEndpointProvider(unittest.TestCase):
    def setUp(self):
        self.harness = Harness(EndpointProviderCharm, meta=PROVIDER_META)
        self.addCleanup(self.harness.cleanup)
        self.harness.set_leader(True)
        self.harness.begin()

    def test_provider_default_scrape_relations_not_in_meta(self):
        """Tests that the Provider raises exception when no promethes_scrape in meta."""
        harness = Harness(
            EndpointProviderCharm,
            # No provider relation with `prometheus_scrape` as interface
            meta="""
                name: provider-tester
                containers:
                    prometheus:
                        resource: prometheus-image
                prometheus-tester: {}
                provides:
                    non-standard-name:
                        interface: prometheus_scrape
                """,
        )
        self.assertRaises(RelationNotFoundError, harness.begin)

    def test_provider_default_scrape_relation_wrong_interface(self):
        """Tests that Provider raises exception if the default relation has the wrong interface."""
        harness = Harness(
            EndpointProviderCharm,
            # No provider relation with `prometheus_scrape` as interface
            meta="""
                name: provider-tester
                containers:
                    prometheus:
                        resource: prometheus-image
                prometheus-tester: {}
                provides:
                    metrics-endpoint:
                        interface: not_prometheus_scrape
                """,
        )
        self.assertRaises(RelationInterfaceMismatchError, harness.begin)

    def test_provider_default_scrape_relation_wrong_role(self):
        """Tests that Provider raises exception if the default relation has the wrong role."""
        harness = Harness(
            EndpointProviderCharm,
            # No provider relation with `prometheus_scrape` as interface
            meta="""
                name: provider-tester
                containers:
                    prometheus:
                        resource: prometheus-image
                prometheus-tester: {}
                requires:
                    metrics-endpoint:
                        interface: prometheus_scrape
                """,
        )
        self.assertRaises(RelationRoleMismatchError, harness.begin)

    @patch("ops.testing._TestingModelBackend.network_get")
    def test_provider_sets_scrape_metadata(self, _):
        rel_id = self.harness.add_relation(RELATION_NAME, "provider")
        self.harness.add_relation_unit(rel_id, "provider/0")
        data = self.harness.get_relation_data(rel_id, self.harness.model.app.name)
        self.assertIn("scrape_metadata", data)
        scrape_metadata = data["scrape_metadata"]
        self.assertIn("model", scrape_metadata)
        self.assertIn("model_uuid", scrape_metadata)
        self.assertIn("application", scrape_metadata)

    @patch("ops.testing._TestingModelBackend.network_get")
    def test_provider_unit_sets_bind_address_on_pebble_ready(self, mock_net_get):
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
    def test_provider_unit_sets_bind_address_on_relation_joined(self, mock_net_get):
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
    def test_provider_supports_multiple_jobs(self, _):
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
    def test_provider_sanitizes_jobs(self, _):
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
        alerts = json.loads(data["alert_rules"])[1]
        self.assertIn("groups", alerts)
        self.assertEqual(len(alerts["groups"]), 3)
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
        alerts = json.loads(data["alert_rules"])[1]
        self.assertIn("groups", alerts)
        self.assertEqual(len(alerts["groups"]), 3)
        group = alerts["groups"][0]
        for rule in group["rules"]:
            self.assertIn("expr", rule)
            for labels in expression_labels(rule["expr"]):
                self.assertIn("juju_model", labels)
                self.assertIn("juju_model_uuid", labels)
                self.assertIn("juju_application", labels)


class CustomizableEndpointProviderCharm(CharmBase):
    _stored = StoredState()

    def __init__(self, *args, **kwargs):
        super().__init__(*args)

        self.provider = MetricsEndpointProvider(
            self, jobs=JOBS, alert_rules_path=kwargs["alert_rules_path"]
        )


def customize_endpoint_provider(*args, **kwargs):
    class CustomizedEndpointProvider(CustomizableEndpointProviderCharm):
        __init__ = functools.partialmethod(
            CustomizableEndpointProviderCharm.__init__, *args, **kwargs
        )

    return CustomizedEndpointProvider


class TestNonStandardProviders(unittest.TestCase):
    def setup(self, **kwargs):
        bad_provider_charm = customize_endpoint_provider(
            alert_rules_path=kwargs["alert_rules_path"]
        )
        self.harness = Harness(bad_provider_charm, meta=PROVIDER_META)
        self.addCleanup(self.harness.cleanup)
        self.harness.set_leader(True)
        self.harness.begin()

    @patch("ops.testing._TestingModelBackend.network_get")
    def test_a_bad_alert_expression_logs_an_error(self, _):
        self.setup(alert_rules_path="./tests/unit/bad_alert_expressions")

        with self.assertLogs(level="ERROR") as logger:
            rel_id = self.harness.add_relation(RELATION_NAME, "provider")
            self.harness.add_relation_unit(rel_id, "provider/0")
            messages = sorted(logger.output)
            self.assertEqual(len(messages), 1)
            self.assertIn("Invalid rules file: missing_expr.rule", messages[0])

    @patch("ops.testing._TestingModelBackend.network_get")
    def test_a_bad_alert_rules_logs_an_error(self, _):
        self.setup(alert_rules_path="./tests/unit/bad_alert_rules")

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


class TestAlertRules(unittest.TestCase):
    def setUp(self) -> None:
        free_standing_rule = {
            "alert": "free_standing",
            "expr": "avg(some_vector[5m]) > 5",
        }

        alert_rule = {
            "alert": "CPUOverUse",
            "expr": "process_cpu_seconds_total{%%juju_topology%%} > 0.12",
        }
        rules_file_dict = {"groups": [{"name": "group1", "rules": [alert_rule]}]}

        self.sandbox = Sandbox()
        self.sandbox.put_files(
            ("rules/prom/sub1/lma_rule.rule", yaml.safe_dump(alert_rule)),
            ("rules/prom/sub1/standard_rule.rule", yaml.safe_dump(rules_file_dict)),
            ("rules/prom/sub2/free_standing_rule.rule", yaml.safe_dump(free_standing_rule)),
        )

        self.topology = JujuTopology("MyModel", "MyUUID", "MyApp", "MyCharm")

    def test_non_recursive_is_default(self):
        rules_file_dict = AlertRules.from_path(
            os.path.join(self.sandbox.root, "rules", "prom"), topology=self.topology
        ).as_rules_file_dict()
        self.assertEqual({}, rules_file_dict)

    def test_alerts_in_both_formats_are_recursively_aggregated(self):
        self.maxDiff = None
        rules_file_dict = AlertRules.from_path(
            os.path.join(self.sandbox.root, "rules", "prom"),
            topology=self.topology,
            recursive=True,
        ).as_rules_file_dict()

        expected_alert_rule = {
            "alert": "CPUOverUse",
            "expr": f"process_cpu_seconds_total{{{self.topology.promql_labels}}} > 0.12",
            "labels": self.topology.as_dict_with_promql_labels(),
        }

        expected_freestanding_rule = {
            "alert": "free_standing",
            "expr": "avg(some_vector[5m]) > 5",
            "labels": self.topology.as_dict_with_promql_labels(),
        }

        expected_rules_file = {
            "groups": [
                {
                    "name": f"{self.topology.identifier}_sub1_group1_alerts",
                    "rules": [expected_alert_rule],
                },
                {
                    "name": f"{self.topology.identifier}_sub1_lma_rule_alerts",
                    "rules": [expected_alert_rule],
                },
                {
                    "name": f"{self.topology.identifier}_sub2_free_standing_rule_alerts",
                    "rules": [expected_freestanding_rule],
                },
            ]
        }

        self.assertEqual({}, DeepDiff(expected_rules_file, rules_file_dict, ignore_order=True))
