# Copyright 2020 Canonical Ltd.
# See LICENSE file for licensing details.

import functools
import json
import re
import unittest
from typing import List
from unittest.mock import patch

import yaml
from charms.observability_libs.v0.juju_topology import JujuTopology
from charms.prometheus_k8s.v0.prometheus_scrape import (
    ALLOWED_KEYS,
    AlertRules,
    CosTool,
    MetricsEndpointProvider,
    RelationInterfaceMismatchError,
    RelationNotFoundError,
    RelationRoleMismatchError,
)
from deepdiff import DeepDiff
from fs.tempfs import TempFS
from helpers import PROJECT_DIR, UNITTEST_DIR, patch_network_get
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


JOBS: List[dict] = [
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
            self, jobs=JOBS, alert_rules_path=str(UNITTEST_DIR / "prometheus_alert_rules")
        )


class EndpointProviderCharmExternalUrl(CharmBase):
    _stored = StoredState()

    def __init__(self, *args, **kwargs):
        super().__init__(*args)

        self.provider = MetricsEndpointProvider(
            self,
            jobs=JOBS,
            alert_rules_path=str(UNITTEST_DIR / "prometheus_alert_rules"),
            external_url="9.12.20.18",
        )


class EndpointProviderCharmWithMultipleEvents(CharmBase):
    _stored = StoredState()

    def __init__(self, *args, **kwargs):
        super().__init__(*args)

        self.provider = MetricsEndpointProvider(
            self,
            jobs=JOBS,
            alert_rules_path="./tests/unit/prometheus_alert_rules",
            refresh_event=[self.on.prometheus_tester_pebble_ready, self.on.config_changed],
        )


class TestEndpointProvider(unittest.TestCase):
    def setUp(self):
        self.harness = Harness(EndpointProviderCharm, meta=PROVIDER_META)
        self.harness.set_model_name("MyUUID")
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

    @patch_network_get()
    def test_provider_sets_scrape_metadata(self):
        rel_id = self.harness.add_relation(RELATION_NAME, "provider")
        self.harness.add_relation_unit(rel_id, "provider/0")
        data = self.harness.get_relation_data(rel_id, self.harness.model.app.name)
        self.assertIn("scrape_metadata", data)
        scrape_metadata = data["scrape_metadata"]
        self.assertIn("model", scrape_metadata)
        self.assertIn("model_uuid", scrape_metadata)
        self.assertIn("application", scrape_metadata)

    @patch(
        "charms.prometheus_k8s.v0.prometheus_scrape.MetricsEndpointProvider._set_unit_ip",
        autospec=True,
    )
    def test_provider_selects_correct_refresh_event_for_sidecar(self, mock_set_unit_ip):
        self.harness.add_relation(RELATION_NAME, "provider")

        self.harness.container_pebble_ready("prometheus-tester")
        self.assertEqual(mock_set_unit_ip.call_count, 1)

    @patch(
        "charms.prometheus_k8s.v0.prometheus_scrape.MetricsEndpointProvider._set_unit_ip",
        autospec=True,
    )
    def test_provider_selects_correct_refresh_event_for_podspec(self, mock_set_unit_ip):
        """Tests that Provider raises exception if the default relation has the wrong role."""
        harness = Harness(
            EndpointProviderCharm,
            # No provider relation with `prometheus_scrape` as interface
            meta=f"""
                 name: provider-tester
                 containers:
                   prometheus-tester:
                 provides:
                   {RELATION_NAME}:
                     interface: prometheus_scrape
                 series:
                   - kubernetes
         """,
        )
        harness.begin()
        harness.charm.on.update_status.emit()
        self.assertEqual(mock_set_unit_ip.call_count, 1)

    @patch(
        "charms.prometheus_k8s.v0.prometheus_scrape.MetricsEndpointProvider._set_unit_ip",
        autospec=True,
    )
    def test_provider_can_refresh_on_multiple_events(self, mock_set_unit_ip):
        harness = Harness(
            EndpointProviderCharmWithMultipleEvents,
            # No provider relation with `prometheus_scrape` as interface
            meta=f"""
                 name: provider-tester
                 containers:
                   prometheus-tester:
                 provides:
                   {RELATION_NAME}:
                     interface: prometheus_scrape
                 series:
                   - kubernetes
         """,
        )
        harness.set_model_name("MyUUID")
        harness.begin()
        harness.add_relation(RELATION_NAME, "provider")

        harness.charm.on.config_changed.emit()
        self.assertEqual(mock_set_unit_ip.call_count, 1)

        harness.container_pebble_ready("prometheus-tester")
        self.assertEqual(mock_set_unit_ip.call_count, 2)

    @patch_network_get()
    def test_provider_unit_sets_address_on_pebble_ready(self):
        rel_id = self.harness.add_relation(RELATION_NAME, "provider")
        self.harness.container_pebble_ready("prometheus-tester")
        data = self.harness.get_relation_data(rel_id, self.harness.charm.unit.name)
        self.assertIn("prometheus_scrape_unit_address", data)
        self.assertEqual(data["prometheus_scrape_unit_address"], "10.1.157.116")

    @patch_network_get()
    def test_provider_unit_sets_address_on_relation_joined(self):
        rel_id = self.harness.add_relation(RELATION_NAME, "provider")
        self.harness.add_relation_unit(rel_id, "provider/0")
        data = self.harness.get_relation_data(rel_id, self.harness.charm.unit.name)
        self.assertIn("prometheus_scrape_unit_address", data)
        self.assertEqual(data["prometheus_scrape_unit_address"], "10.1.157.116")
        self.assertIn("prometheus_scrape_unit_name", data)

    @patch_network_get()
    def test_provider_sets_external_url(self):
        harness = Harness(EndpointProviderCharmExternalUrl, meta=PROVIDER_META)
        harness.set_model_name("MyUUID")
        harness.set_leader(True)
        harness.begin()
        rel_id = harness.add_relation(RELATION_NAME, "provider")
        harness.add_relation_unit(rel_id, "provider/0")
        data = harness.get_relation_data(rel_id, harness.charm.unit.name)
        self.assertIn("prometheus_scrape_unit_address", data)
        self.assertEqual(data["prometheus_scrape_unit_address"], "9.12.20.18")
        self.assertIn("prometheus_scrape_unit_name", data)

    @patch("socket.getfqdn", new=lambda *args: "some.host")
    @patch_network_get(private_address=None)
    def test_provider_unit_sets_fqdn_if_not_address_on_relation_joined(self):
        rel_id = self.harness.add_relation(RELATION_NAME, "provider")
        self.harness.add_relation_unit(rel_id, "provider/0")
        data = self.harness.get_relation_data(rel_id, self.harness.charm.unit.name)
        self.assertIn("prometheus_scrape_unit_address", data)
        self.assertEqual(data["prometheus_scrape_unit_address"], "some.host")
        self.assertIn("prometheus_scrape_unit_name", data)

    @patch_network_get()
    def test_provider_supports_multiple_jobs(self):
        rel_id = self.harness.add_relation(RELATION_NAME, "provider")
        self.harness.add_relation_unit(rel_id, "provider/0")
        data = self.harness.get_relation_data(rel_id, self.harness.model.app.name)
        self.assertIn("scrape_jobs", data)
        jobs = json.loads(data["scrape_jobs"])
        self.assertEqual(len(jobs), len(JOBS))
        names = [job["job_name"] for job in jobs]
        job_names = [job["job_name"] for job in JOBS]
        self.assertListEqual(names, job_names)

    @patch_network_get()
    def test_provider_sanitizes_jobs(self):
        rel_id = self.harness.add_relation(RELATION_NAME, "provider")
        self.harness.add_relation_unit(rel_id, "provider/0")
        data = self.harness.get_relation_data(rel_id, self.harness.model.app.name)
        self.assertIn("scrape_jobs", data)
        jobs = json.loads(data["scrape_jobs"])
        for job in jobs:
            keys = set(job.keys())
            self.assertTrue(keys.issubset(ALLOWED_KEYS))

    @patch_network_get()
    def test_each_alert_rule_is_topology_labeled(self):
        rel_id = self.harness.add_relation(RELATION_NAME, "provider")
        self.harness.add_relation_unit(rel_id, "provider/0")
        data = self.harness.get_relation_data(rel_id, self.harness.model.app.name)
        self.assertIn("alert_rules", data)
        alerts = json.loads(data["alert_rules"])
        self.assertIn("groups", alerts)
        self.assertEqual(len(alerts["groups"]), 6)
        for group in alerts["groups"]:
            for rule in group["rules"]:
                if "and_unit" not in group["name"]:
                    self.assertIn("labels", rule)
                    labels = rule["labels"]
                    self.assertIn("juju_model", labels)
                    self.assertIn("juju_application", labels)
                    self.assertIn("juju_model_uuid", labels)
                    self.assertIn("juju_charm", labels)
                    # alerts should not have unit information if not already present
                    self.assertNotIn("juju_unit", rule["labels"])
                    self.assertNotIn("juju_unit=", rule["expr"])
                else:
                    self.assertIn("labels", rule)
                    labels = rule["labels"]
                    self.assertIn("juju_model", labels)
                    self.assertIn("juju_application", labels)
                    self.assertIn("juju_model_uuid", labels)
                    self.assertIn("juju_charm", labels)
                    # unit information is already present
                    self.assertIn("juju_unit", rule["labels"])
                    self.assertIn("juju_unit=", rule["expr"])

    @patch_network_get()
    def test_each_alert_expression_is_topology_labeled(self):
        rel_id = self.harness.add_relation(RELATION_NAME, "provider")
        self.harness.add_relation_unit(rel_id, "provider/0")
        data = self.harness.get_relation_data(rel_id, self.harness.model.app.name)
        self.assertIn("alert_rules", data)
        alerts = json.loads(data["alert_rules"])
        self.assertIn("groups", alerts)
        self.assertEqual(len(alerts["groups"]), 6)
        group = alerts["groups"][0]
        for rule in group["rules"]:
            self.assertIn("expr", rule)
            for labels in expression_labels(rule["expr"]):
                self.assertIn("juju_model", labels)
                self.assertIn("juju_model_uuid", labels)
                self.assertIn("juju_application", labels)
                self.assertIn("juju_charm", labels)


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
        )  # type: ignore

    return CustomizedEndpointProvider


class TestNonStandardProviders(unittest.TestCase):
    def setup(self, **kwargs):
        bad_provider_charm = customize_endpoint_provider(
            alert_rules_path=kwargs["alert_rules_path"]
        )
        self.harness = Harness(bad_provider_charm, meta=PROVIDER_META)
        self.harness.set_model_name("MyUUID")
        self.addCleanup(self.harness.cleanup)
        self.harness.set_leader(True)
        self.harness.begin()

    @patch_network_get()
    def test_a_bad_alert_expression_logs_an_error(self):
        self.setup(alert_rules_path=str(UNITTEST_DIR / "bad_alert_expressions"))

        with self.assertLogs(level="ERROR") as logger:
            rel_id = self.harness.add_relation(RELATION_NAME, "provider")
            self.harness.add_relation_unit(rel_id, "provider/0")
            messages = sorted(logger.output)
            self.assertEqual(len(messages), 1)
            self.assertIn("Invalid rules file: missing_expr.rule", messages[0])

    @patch_network_get()
    def test_a_bad_alert_rules_logs_an_error(self):
        self.setup(alert_rules_path=str(UNITTEST_DIR / "bad_alert_rules"))

        with self.assertLogs(level="ERROR") as logger:
            rel_id = self.harness.add_relation(RELATION_NAME, "provider")
            self.harness.add_relation_unit(rel_id, "provider/0")
            messages = sorted(logger.output)
            self.assertEqual(len(messages), 1)
            self.assertIn("Failed to read alert rules from bad_yaml.rule", messages[0])


def sorted_matchers(matchers) -> str:
    parts = [m.strip() for m in matchers.split(",")]
    return ",".join(sorted(parts))


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


class TestAlertRulesWithOneRulePerFile(unittest.TestCase):
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

        self.sandbox = TempFS("rule_files", auto_clean=True)
        self.addCleanup(self.sandbox.close)
        self.sandbox.makedirs("rules/prom/mixed_format")
        self.sandbox.makedirs("rules/prom/lma_format")
        self.sandbox.makedirs("rules/prom/prom_format")
        self.sandbox.writetext("rules/prom/mixed_format/lma_rule.rule", yaml.safe_dump(alert_rule))
        self.sandbox.writetext(
            "rules/prom/mixed_format/standard_rule.rule", yaml.safe_dump(rules_file_dict)
        )
        self.sandbox.writetext(
            "rules/prom/lma_format/free_standing_rule.rule", yaml.safe_dump(free_standing_rule)
        )
        self.sandbox.writetext(
            "rules/prom/prom_format/standard_rule.rule", yaml.safe_dump(rules_file_dict)
        )

        self.topology = JujuTopology(
            "MyModel", "12de4fae-06cc-4ceb-9089-567be09fec78", "MyApp", "MyUnit", "MyCharm"
        )

    def test_non_recursive_is_default(self):
        rules = AlertRules(topology=self.topology)
        rules.add_path(self.sandbox.getsyspath("/rules/prom/"))
        rules_file_dict = rules.as_dict()
        self.assertEqual({}, rules_file_dict)

    def test_non_recursive_lma_format_loading_from_root_dir(self):
        rules = AlertRules(topology=self.topology)
        rules.add_path(self.sandbox.getsyspath("/rules/prom/lma_format/"))
        rules_file_dict = rules.as_dict()

        expected_freestanding_rule = {
            "alert": "free_standing",
            "expr": "avg(some_vector[5m]) > 5",
            "labels": self.topology.label_matcher_dict,
        }

        expected_rules_file = {
            "groups": [
                {
                    "name": f"{sorted_matchers(self.topology.identifier)}_free_standing_rule_alerts",
                    "rules": [expected_freestanding_rule],
                },
            ]
        }

        self.assertEqual(expected_rules_file, rules_file_dict)

    def test_non_recursive_official_format_loading_from_root_dir(self):
        rules = AlertRules(topology=self.topology)
        rules.add_path(self.sandbox.getsyspath("/rules/prom/prom_format"))
        rules_file_dict = rules.as_dict()

        expected_alert_rule = {
            "alert": "CPUOverUse",
            "expr": f"process_cpu_seconds_total{{{sorted_matchers(self.topology.label_matchers)}}} > 0.12",
            "labels": self.topology.label_matcher_dict,
        }

        expected_rules_file = {
            "groups": [
                {
                    "name": f"{self.topology.identifier}_group1_alerts",
                    "rules": [expected_alert_rule],
                },
            ]
        }
        self.assertEqual(expected_rules_file, rules_file_dict)

    def test_alerts_in_both_formats_are_recursively_aggregated(self):
        """This test covers several aspects of the rules format.

        - Group name:
          - For rules in lma format, core group name is the filename
          - For rules in official format, core group name is the group name in the file
        """
        rules = AlertRules(topology=self.topology)
        rules.add_path(self.sandbox.getsyspath("/rules/prom"), recursive=True)
        rules_file_dict = rules.as_dict()

        expected_alert_rule = {
            "alert": "CPUOverUse",
            "expr": f"process_cpu_seconds_total{{{sorted_matchers(self.topology.label_matchers)}}} > 0.12",
            "labels": self.topology.label_matcher_dict,
        }

        expected_freestanding_rule = {
            "alert": "free_standing",
            "expr": "avg(some_vector[5m]) > 5",
            "labels": self.topology.label_matcher_dict,
        }

        expected_rules_file = {
            "groups": [
                {
                    "name": f"{self.topology.identifier}_mixed_format_group1_alerts",
                    "rules": [expected_alert_rule],
                },
                {
                    "name": f"{self.topology.identifier}_mixed_format_lma_rule_alerts",
                    "rules": [expected_alert_rule],
                },
                {
                    "name": f"{self.topology.identifier}_lma_format_free_standing_rule_alerts",
                    "rules": [expected_freestanding_rule],
                },
                {
                    "name": f"{self.topology.identifier}_prom_format_group1_alerts",
                    "rules": [expected_alert_rule],
                },
            ]
        }

        self.assertEqual({}, DeepDiff(expected_rules_file, rules_file_dict, ignore_order=True))

    def test_unit_not_in_alert_labels(self):
        rules = AlertRules(topology=self.topology)
        rules.add_path(self.sandbox.getsyspath("/rules/prom"), recursive=True)
        rules_file_dict = rules.as_dict()
        for group in rules_file_dict["groups"]:
            for rule in group["rules"]:
                self.assertTrue("juju_unit" not in rule["labels"])


class TestAlertRulesWithMultipleRulesPerFile(unittest.TestCase):
    def setUp(self) -> None:
        self.topology = JujuTopology(
            "MyModel", "12de4fae-06cc-4ceb-9089-567be09fec78", "MyApp", "MyCharm"
        )

    def gen_rule(self, name, **extra):
        return {
            "alert": f"CPUOverUse_{name}",
            "expr": f"process_cpu_seconds_total{{{sorted_matchers(self.topology.label_matchers)}}} > 0.12",
            **extra,
        }

    def gen_group(self, name):
        return {"name": f"group_{name}", "rules": [self.gen_rule(1), self.gen_rule(2)]}

    def test_load_multiple_rules_per_file(self):
        """Test official format with multiple alert rules per group in multiple groups."""
        rules_file_dict = {"groups": [self.gen_group(1), self.gen_group(2)]}
        sandbox = TempFS("rule_files", auto_clean=True)
        sandbox.makedirs("rules")
        sandbox.writetext("rules/file.rule", yaml.safe_dump(rules_file_dict))

        rules = AlertRules(topology=self.topology)
        rules.add_path(sandbox.getsyspath("/rules"), recursive=False)
        rules_file_dict_read = rules.as_dict()

        expected_rules_file = {
            "groups": [
                {
                    "name": f"{self.topology.identifier}_group_1_alerts",
                    "rules": [
                        self.gen_rule(1, labels=self.topology.label_matcher_dict),
                        self.gen_rule(2, labels=self.topology.label_matcher_dict),
                    ],
                },
                {
                    "name": f"{self.topology.identifier}_group_2_alerts",
                    "rules": [
                        self.gen_rule(1, labels=self.topology.label_matcher_dict),
                        self.gen_rule(2, labels=self.topology.label_matcher_dict),
                    ],
                },
            ]
        }
        self.assertDictEqual(expected_rules_file, rules_file_dict_read)

    def test_duplicated_alert_names_within_alert_rules_list_are_silently_accepted(self):
        """Test official format when the alert rules list has a duplicated alert name."""
        rules_file_dict = {
            "groups": [
                {
                    "name": "my_group",
                    "rules": [self.gen_rule("same"), self.gen_rule("same")],
                }
            ]
        }
        sandbox = TempFS("rule_files", auto_clean=True)
        sandbox.makedirs("rules")
        sandbox.writetext("rules/file.rule", yaml.safe_dump(rules_file_dict))

        rules = AlertRules(topology=self.topology)
        rules.add_path(sandbox.getsyspath("/rules"), recursive=False)
        rules_file_dict_read = rules.as_dict()

        expected_rules_file = {
            "groups": [
                {
                    "name": f"{self.topology.identifier}_my_group_alerts",
                    "rules": [
                        self.gen_rule("same", labels=self.topology.label_matcher_dict),
                        self.gen_rule("same", labels=self.topology.label_matcher_dict),
                    ],
                },
            ]
        }
        self.assertDictEqual(expected_rules_file, rules_file_dict_read)

    def test_duplicated_group_names_within_a_file_are_silently_accepted(self):
        rules_file_dict = {"groups": [self.gen_group("same"), self.gen_group("same")]}
        sandbox = TempFS("rule_files", auto_clean=True)
        sandbox.makedirs("rules")
        sandbox.writetext("rules/file.rule", yaml.safe_dump(rules_file_dict))

        rules = AlertRules(topology=self.topology)
        rules.add_path(sandbox.getsyspath("/rules"), recursive=False)
        rules_file_dict_read = rules.as_dict()

        expected_rules_file = {
            "groups": [
                {
                    "name": f"{self.topology.identifier}_group_same_alerts",
                    "rules": [
                        self.gen_rule(1, labels=self.topology.label_matcher_dict),
                        self.gen_rule(2, labels=self.topology.label_matcher_dict),
                    ],
                },
                {
                    "name": f"{self.topology.identifier}_group_same_alerts",
                    "rules": [
                        self.gen_rule(1, labels=self.topology.label_matcher_dict),
                        self.gen_rule(2, labels=self.topology.label_matcher_dict),
                    ],
                },
            ]
        }
        self.assertDictEqual(expected_rules_file, rules_file_dict_read)

    def test_deeply_nested(self):
        sandbox = TempFS("rule_files", auto_clean=True)
        sandbox.makedirs("rules/a/b/")
        sandbox.writetext("rules/file.rule", yaml.safe_dump(self.gen_rule(0)))
        sandbox.writetext("rules/a/file.rule", yaml.safe_dump(self.gen_rule(1)))
        sandbox.writetext("rules/a/b/file.rule", yaml.safe_dump(self.gen_rule(2)))

        rules = AlertRules(topology=self.topology)
        rules.add_path(sandbox.getsyspath("/rules"), recursive=True)
        rules_file_dict_read = rules.as_dict()

        expected_rules_file = {
            "groups": [
                {
                    "name": f"{self.topology.identifier}_file_alerts",
                    "rules": [self.gen_rule(0, labels=self.topology.label_matcher_dict)],
                },
                {
                    "name": f"{self.topology.identifier}_a_file_alerts",
                    "rules": [self.gen_rule(1, labels=self.topology.label_matcher_dict)],
                },
                {
                    "name": f"{self.topology.identifier}_a_b_file_alerts",
                    "rules": [self.gen_rule(2, labels=self.topology.label_matcher_dict)],
                },
            ]
        }
        self.assertDictEqual(expected_rules_file, rules_file_dict_read)


class TestAlertRulesContainingUnitTopology(unittest.TestCase):
    """Tests that check MetricsEndpointProvider does not remove unit topology.

    Unit Topology information is not added to alert rules expressions and labels,
    by the MetricsEndpointProvider. However, if unit topology information is
    present in the labels then it must not be removed since the client that
    the alert be limited to a specific unit.
    """

    def setup(self, **kwargs):
        bad_provider_charm = customize_endpoint_provider(
            alert_rules_path=kwargs["alert_rules_path"]
        )
        self.harness = Harness(bad_provider_charm, meta=PROVIDER_META)
        self.harness.set_model_name("MyUUID")
        self.addCleanup(self.harness.cleanup)
        self.harness.set_leader(True)
        self.harness.begin()

    @patch_network_get()
    def test_unit_label_is_retained_if_hard_coded(self):
        self.setup(alert_rules_path=str(UNITTEST_DIR / "alert_rules_with_unit_topology"))
        rel_id = self.harness.add_relation("metrics-endpoint", "provider")
        self.harness.add_relation_unit(rel_id, "provider/0")

        # check unit topology is present in labels and in alert rule expression
        relation = self.harness.charm.model.get_relation("metrics-endpoint")
        alert_rules = json.loads(relation.data[self.harness.charm.app].get("alert_rules"))
        for group in alert_rules["groups"]:
            for rule in group["rules"]:
                self.assertIn("juju_unit", rule["labels"])
                self.assertIn("juju_unit=", rule["expr"])


class TestNoLeader(unittest.TestCase):
    """Tests the case where leader is not set immediately."""

    def setUp(self):
        self.harness = Harness(EndpointProviderCharm, meta=PROVIDER_META)
        self.harness.set_model_name("MyUUID")
        self.addCleanup(self.harness.cleanup)
        self.harness.set_leader(False)
        self.harness.begin_with_initial_hooks()

    @patch_network_get()
    def test_alert_rules(self):
        """Verify alert rules are added when leader is elected after the relation is created."""
        rel_id = self.harness.add_relation(RELATION_NAME, "provider")
        self.harness.add_relation_unit(rel_id, "provider/0")
        self.harness.set_leader(True)

        data = self.harness.get_relation_data(rel_id, self.harness.model.app.name).get(
            "alert_rules"
        )
        self.assertIsNotNone(data)
        self.assertGreater(len(data), 0)  # type: ignore[arg-type]


class CharmProvidingPromBakedInRules(CharmBase):
    _stored = StoredState()

    def __init__(self, *args, **kwargs):
        super().__init__(*args)

        self.provider = MetricsEndpointProvider(
            self, jobs=JOBS, alert_rules_path=str(PROJECT_DIR / "src" / "prometheus_alert_rules")
        )
        self.tool = CosTool(self)


class TestBakedInAlertRules(unittest.TestCase):
    """Test that the baked-in alert rules, as written to relation data, pass validation."""

    def setUp(self):
        self.harness = Harness(CharmProvidingPromBakedInRules, meta=PROVIDER_META)
        self.harness.set_model_name("MyUUID")
        self.addCleanup(self.harness.cleanup)
        self.harness.set_leader(True)
        self.harness.begin_with_initial_hooks()

    @patch_network_get()
    def test_alert_rules(self):
        """Verify alert rules are added when leader is elected after the relation is created."""
        rel_id = self.harness.add_relation(RELATION_NAME, "provider")
        self.harness.add_relation_unit(rel_id, "provider/0")

        data = self.harness.get_relation_data(rel_id, self.harness.model.app.name)
        baked_in_alert_rules_as_they_appear_in_reldata = json.loads(data["alert_rules"])

        tool = self.harness.charm.tool
        valid, errs = tool.validate_alert_rules(baked_in_alert_rules_as_they_appear_in_reldata)
        self.assertEqual(valid, True)
        self.assertEqual(errs, "")
