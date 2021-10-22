# Copyright 2020 Canonical Ltd.
# See LICENSE file for licensing details.

import functools
import json
import re
import unittest
from unittest.mock import patch

from charms.prometheus_k8s.v0.prometheus_scrape import (
    ALLOWED_KEYS,
    JujuTopology,
    MetricsEndpointProvider,
    RelationInterfaceMismatchError,
    RelationNotFoundError,
    RelationRoleMismatchError,
    load_alert_rules_from_dir,
)
from ops.charm import CharmBase
from ops.framework import StoredState
from ops.testing import Harness

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
            self.assertIn(
                "Invalid alert rule missing_expr.rule: missing an 'expr' property", messages[0]
            )

    @patch("ops.testing._TestingModelBackend.network_get")
    def test_a_bad_alert_rules_logs_an_error(self, _):
        self.setup(alert_rules_path="./tests/unit/bad_alert_rules")

        with self.assertLogs(level="ERROR") as logger:
            rel_id = self.harness.add_relation(RELATION_NAME, "provider")
            self.harness.add_relation_unit(rel_id, "provider/0")
            messages = sorted(logger.output)
            self.assertEqual(len(messages), 1)
            self.assertIn("Failed to read alert rules from bad_yaml.rule", messages[0])

    def test_provider_default_scrape_relations_not_in_meta(self):
        self.setup(alert_rules_path="./tests/unit/non_standard_prometheus_alert_rules")

        alert_groups = self.harness.charm.provider._labeled_alert_groups
        self.assertTrue(len(alert_groups), 1)
        alert_group = alert_groups[0]
        rules = alert_group["rules"]
        self.assertTrue(len(rules), 1)
        rule = rules[0]
        self.assertEqual(rule["alert"], "OddRule")


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


class TestLoadAlertRulesFromDir(unittest.TestCase):

    # [{'name': 'MyModel_MyUUID_MyApp_alerts',
    #   'rules': [{'alert': 'CPUOverUse',
    #              'annotations': {'description': '{{ $labels.instance }} of job {{ '
    #                                             '$labels.job }} has used too much '
    #                                             'CPU.',
    #                              'summary': 'Instance {{ $labels.instance }} CPU '
    #                                         'over use'},
    #              'expr': 'process_cpu_seconds_total{juju_model="MyModel", '
    #                      'juju_model_uuid="MyUUID", juju_application="MyApp"} > '
    #                      '0.12',
    #              'for': '0m',
    #              'labels': {'juju_application': 'MyApp',
    #                         'juju_model': 'MyModel',
    #                         'juju_model_uuid': 'MyUUID',
    #                         'severity': 'Low'}},
    #             {'alert': 'PrometheusTargetMissing',
    #              'annotations': {'description': 'A Prometheus target has '
    #                                             'disappeared. An exporter might be '
    #                                             'crashed.\n'
    #                                             '  VALUE = {{ $value }}\n'
    #                                             '  LABELS = {{ $labels }}',
    #                              'summary': 'Prometheus target missing (instance '
    #                                         '{{ $labels.instance }})'},
    #              'expr': 'up{juju_model="MyModel", juju_model_uuid="MyUUID", '
    #                      'juju_application="MyApp"} == 0',
    #              'for': '0m',
    #              'labels': {'juju_application': 'MyApp',
    #                         'juju_model': 'MyModel',
    #                         'juju_model_uuid': 'MyUUID',
    #                         'severity': 'critical'}}]}]

    def setUp(self) -> None:
        self.topology = JujuTopology("MyModel", "MyUUID", "MyApp", "MyCharm")
        self.rule_groups = load_alert_rules_from_dir(
            "./tests/unit/prometheus_alert_rules", self.topology
        )

    def test_only_one_group_per_file(self):
        self.assertEqual(len(self.rule_groups), 1)

    def test_group_name_matches_topology(self):
        group = self.rule_groups[0]
        self.assertEqual(group["name"], self.topology.identifier + "_alerts")

    def test_at_least_one_alert_rule_in_group(self):
        group = self.rule_groups[0]
        rules = group["rules"]
        self.assertGreaterEqual(len(rules), 1)

    def test_every_alert_rule_has_expr_property(self):
        group = self.rule_groups[0]
        rules = group["rules"]
        self.assertTrue(all(bool(rule.get("expr")) for rule in rules))

    def test_every_alert_rule_has_topology_labels(self):
        group = self.rule_groups[0]
        rules = group["rules"]
        for rule in rules:
            with self.subTest(alert=rule["alert"]):
                self.assertGreaterEqual(
                    rule["labels"].items(), self.topology.as_dict_with_promql_labels().items()
                )

    def test_nested_rules_not_read_by_default(self):
        group = self.rule_groups[0]
        rules = group["rules"]
        # TODO consider using in-memory filesystem instead of actual disk files
        self.assertTrue(not (any(rule["alert"] == "CPUOverUseNested" for rule in rules)))


class TestLoadAlertRulesFromDirNested(unittest.TestCase):
    def setUp(self) -> None:
        self.topology = JujuTopology("MyModel", "MyUUID", "MyApp", "MyCharm")
        self.rule_groups = load_alert_rules_from_dir(
            "./tests/unit/prometheus_alert_rules", self.topology, recursive=True
        )

    def test_at_least_one_group_per_file(self):
        self.assertGreater(len(self.rule_groups), 1)

    def test_group_name_prefixed_by_subdir_name(self):
        expected_group_name = "nested_rules_dir_" + self.topology.identifier + "_alerts"
        nested = list(filter(lambda group: expected_group_name == group["name"], self.rule_groups))
        self.assertGreaterEqual(len(nested), 1)
