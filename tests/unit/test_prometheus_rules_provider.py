# Copyright 2020 Canonical Ltd.
# See LICENSE file for licensing details.

import json
import textwrap
import unittest
from unittest.mock import patch

import yaml
from charms.prometheus_k8s.v0.prometheus_scrape import PrometheusRulesProvider
from fs.tempfs import TempFS
from ops.charm import CharmBase
from ops.testing import Harness


@patch("charms.observability_libs.v0.juju_topology.JujuTopology.is_valid_uuid", lambda *args: True)
class TestReloadAlertRules(unittest.TestCase):
    """Feature: Provider charm can manually invoke reloading of alerts.

    Background: In use cases such as cos-configuration-k8s-operator, the last hook can fire before
    the alert files show up on disk. In that case relation data would remain empty of alerts. To
    circumvent that, a public method for reloading alert rules is offered.
    """

    NO_ALERTS = json.dumps({})  # relation data representation for the case of "no alerts"

    # use a short-form free-standing alert, for brevity
    ALERT = yaml.safe_dump({"alert": "free_standing", "expr": "avg(some_vector[5m]) > 5"})

    @patch(
        "charms.observability_libs.v0.juju_topology.JujuTopology.is_valid_uuid", lambda *args: True
    )
    def setUp(self):
        self.sandbox = TempFS("rule_files", auto_clean=True)
        self.addCleanup(self.sandbox.close)

        alert_rules_path = self.sandbox.getsyspath("/")

        class ConsumerCharm(CharmBase):
            metadata_yaml = textwrap.dedent(
                """
                provides:
                  metrics-endpoint:
                    interface: prometheus_scrape
                """
            )

            def __init__(self, *args, **kwargs):
                super().__init__(*args)
                self.rules_provider = PrometheusRulesProvider(self, dir_path=alert_rules_path)

        self.harness = Harness(ConsumerCharm, meta=ConsumerCharm.metadata_yaml)
        # self.harness = Harness(FakeConsumerCharm, meta=FakeConsumerCharm.metadata_yaml)
        self.addCleanup(self.harness.cleanup)
        self.harness.begin_with_initial_hooks()
        self.harness.set_leader(True)
        rel_id = self.harness.add_relation("metrics-endpoint", "prom")
        self.harness.add_relation_unit(rel_id, "prom/0")

    def test_reload_when_dir_is_still_empty_changes_nothing(self):
        """Scenario: The reload method is called when the alerts dir is still empty."""
        # GIVEN relation data contains no alerts
        relation = self.harness.charm.model.get_relation("metrics-endpoint")
        self.assertEqual(relation.data[self.harness.charm.app].get("alert_rules"), self.NO_ALERTS)

        # WHEN no rule files are present

        # AND the reload method is called
        self.harness.charm.rules_provider._reinitialize_alert_rules()

        # THEN relation data is unchanged
        relation = self.harness.charm.model.get_relation("metrics-endpoint")
        self.assertEqual(relation.data[self.harness.charm.app].get("alert_rules"), self.NO_ALERTS)

    def test_reload_after_dir_is_populated_updates_relation_data(self):
        """Scenario: The reload method is called after some alert files are added."""
        # GIVEN relation data contains no alerts
        relation = self.harness.charm.model.get_relation("metrics-endpoint")
        self.assertEqual(relation.data[self.harness.charm.app].get("alert_rules"), self.NO_ALERTS)

        # WHEN some rule files are added to the alerts dir
        self.sandbox.writetext("alert.rule", self.ALERT)

        # AND the reload method is called
        self.harness.charm.rules_provider._reinitialize_alert_rules()

        # THEN relation data is updated
        relation = self.harness.charm.model.get_relation("metrics-endpoint")
        self.assertNotEqual(
            relation.data[self.harness.charm.app].get("alert_rules"), self.NO_ALERTS
        )

    def test_reload_after_dir_is_emptied_updates_relation_data(self):
        """Scenario: The reload method is called after all the loaded alert files are removed."""
        # GIVEN alert files are present and relation data contains respective alerts
        self.sandbox.writetext("alert.rule", self.ALERT)

        self.harness.charm.rules_provider._reinitialize_alert_rules()
        relation = self.harness.charm.model.get_relation("metrics-endpoint")
        self.assertNotEqual(
            relation.data[self.harness.charm.app].get("alert_rules"), self.NO_ALERTS
        )

        # WHEN all rule files are deleted from the alerts dir
        self.sandbox.clean()

        # AND the reload method is called
        self.harness.charm.rules_provider._reinitialize_alert_rules()

        # THEN relation data is empty again
        relation = self.harness.charm.model.get_relation("metrics-endpoint")
        self.assertEqual(relation.data[self.harness.charm.app].get("alert_rules"), self.NO_ALERTS)

    def test_reload_after_dir_itself_removed_updates_relation_data(self):
        """Scenario: The reload method is called after the alerts dir doesn't exist anymore."""
        # GIVEN alert files are present and relation data contains respective alerts
        self.sandbox.writetext("alert.rule", self.ALERT)
        self.harness.charm.rules_provider._reinitialize_alert_rules()
        relation = self.harness.charm.model.get_relation("metrics-endpoint")
        self.assertNotEqual(
            relation.data[self.harness.charm.app].get("alert_rules"), self.NO_ALERTS
        )

        # WHEN the alerts dir itself is deleted
        self.sandbox.clean()

        # AND the reload method is called
        self.harness.charm.rules_provider._reinitialize_alert_rules()

        # THEN relation data is empty again
        relation = self.harness.charm.model.get_relation("metrics-endpoint")
        self.assertEqual(relation.data[self.harness.charm.app].get("alert_rules"), self.NO_ALERTS)

    def test_only_files_with_rule_or_rules_suffixes_are_loaded(self):
        """Scenario: User has both short-form rules (*.rule) and long-form rules (*.rules)."""
        # GIVEN various tricky combinations of files present
        filenames = ["alert.rule", "alert.rules", "alert.ruless", "alertrule", "alertrules"]
        for filename in filenames:
            rule_file = yaml.safe_dump({"alert": filename, "expr": "avg(some_vector[5m]) > 5"})
            self.sandbox.writetext(filename, rule_file)

        # AND the reload method is called
        self.harness.charm.rules_provider._reinitialize_alert_rules()

        # THEN only the *.rule and *.rules files are loaded
        relation = self.harness.charm.model.get_relation("metrics-endpoint")
        alert_rules = json.loads(relation.data[self.harness.charm.app].get("alert_rules"))
        alert_names = [groups["rules"][0]["alert"] for groups in alert_rules["groups"]]
        self.assertEqual(set(alert_names), {"alert.rule", "alert.rules"})

    def test_reload_with_empty_rules(self):
        """Scenario: The reload method is called with a zero-size alert file."""
        # GIVEN relation data contains no alerts
        relation = self.harness.charm.model.get_relation("metrics-endpoint")
        self.assertEqual(relation.data[self.harness.charm.app].get("alert_rules"), self.NO_ALERTS)

        # WHEN an empty rules file is written
        self.sandbox.writetext("alert.rule", "")

        # AND the reload method is called
        self.harness.charm.rules_provider._reinitialize_alert_rules()

        # THEN relation data is not updated
        relation = self.harness.charm.model.get_relation("metrics-endpoint")
        self.assertEqual(relation.data[self.harness.charm.app].get("alert_rules"), self.NO_ALERTS)
