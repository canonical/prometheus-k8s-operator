# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

import json
import unittest
from copy import deepcopy
from unittest.mock import patch

from charms.prometheus_k8s.v0.prometheus_scrape import MetricsEndpointAggregator, _dedupe_list
from cosl.rules import generic_alert_groups
from ops.charm import CharmBase
from ops.testing import Harness

PROMETHEUS_RELATION = "metrics-endpoint"
SCRAPE_TARGET_RELATION = "prometheus-target"
ALERT_RULES_RELATION = "prometheus-rules"
AGGREGATOR_META = f"""
name: aggregator-tester
containers:
  aggregator-tester:
provides:
  {PROMETHEUS_RELATION}:
    interface: prometheus_scrape
requires:
  {SCRAPE_TARGET_RELATION}:
    interface: http
  {ALERT_RULES_RELATION}:
    interface: prometheus-rules
"""

RELABEL_INSTANCE_CONFIG = {
    "source_labels": [
        "juju_model",
        "juju_model_uuid",
        "juju_application",
        "juju_unit",
    ],
    "separator": "_",
    "target_label": "instance",
    "regex": "(.*)",
}

ALERT_RULE_1 = """- alert: CPU_Usage
  expr: cpu_usage_idle{is_container!=\"True\", group=\"promoagents-juju\"} < 10
  for: 5m
  labels:
    override_group_by: host
    severity: page
    cloud: juju
  annotations:
    description: |
      Host {{ $labels.host }} has had <  10% idle cpu for the last 5m
    summary: Host {{ $labels.host }} CPU free is less than 10%
"""
ALERT_RULE_2 = """- alert: DiskFull
  expr: disk_free{is_container!=\"True\", fstype!~\".*tmpfs|squashfs|overlay\"}  <1024
  for: 5m
  labels:
    override_group_by: host
    severity: page
  annotations:
    description: |
      Host {{ $labels.host}} {{ $labels.path }} is full
      summary: Host {{ $labels.host }} {{ $labels.path}} is full
"""
LABELED_ALERT_RULE_1 = {
    "alert": "CPU_Usage",
    "expr": 'cpu_usage_idle{is_container!="True", group="promoagents-juju"} < 10',
    "for": "5m",
    "labels": {
        "override_group_by": "host",
        "severity": "page",
        "cloud": "juju",
        "juju_model": "testmodel",
        "juju_model_uuid": "12de4fae-06cc-4ceb-9089-567be09fec78",
        "juju_application": "rules-app-1",
        "juju_unit": "rules-app-1/0",
    },
    "annotations": {
        "description": "Host {{ $labels.host }} has had <  10% idle cpu for the last 5m\n",
        "summary": "Host {{ $labels.host }} CPU free is less than 10%",
    },
}
LABELED_ALERT_RULE_2 = {
    "alert": "DiskFull",
    "annotations": {
        "description": "Host {{ $labels.host}} {{ "
        "$labels.path }} is full\n"
        "summary: Host {{ $labels.host }} "
        "{{ $labels.path}} is full\n"
    },
    "expr": 'disk_free{is_container!="True", fstype!~".*tmpfs|squashfs|overlay"}  <1024',
    "for": "5m",
    "labels": {
        "juju_application": "rules-app-2",
        "juju_model": "testmodel",
        "juju_model_uuid": "12de4fae-06cc-4ceb-9089-567be09fec78",
        "juju_unit": "rules-app-2/0",
        "override_group_by": "host",
        "severity": "page",
    },
}


class EndpointAggregatorCharm(CharmBase):
    def __init__(self, *args, **kwargs):
        super().__init__(*args)

        relation_names = {
            "prometheus": PROMETHEUS_RELATION,
            "scrape_target": SCRAPE_TARGET_RELATION,
            "alert_rules": ALERT_RULES_RELATION,
        }
        self._aggregator = MetricsEndpointAggregator(
            self,
            relation_names,
        )


class EndpointResolvingAggregatorCharm(CharmBase):
    def __init__(self, *args, **kwargs):
        super().__init__(*args)

        relation_names = {
            "prometheus": PROMETHEUS_RELATION,
            "scrape_target": SCRAPE_TARGET_RELATION,
            "alert_rules": ALERT_RULES_RELATION,
        }
        self._aggregator = MetricsEndpointAggregator(self, relation_names, resolve_addresses=True)


class TestEndpointAggregator(unittest.TestCase):
    def setUp(self):
        self.harness = Harness(EndpointAggregatorCharm, meta=AGGREGATOR_META)
        self.harness.set_model_info(name="testmodel", uuid="12de4fae-06cc-4ceb-9089-567be09fec78")
        self.addCleanup(self.harness.cleanup)
        self.harness.set_leader(True)
        self.harness.begin_with_initial_hooks()

    def test_adding_prometheus_then_target_forwards_a_labeled_scrape_job(self):
        prometheus_rel_id = self.harness.add_relation(PROMETHEUS_RELATION, "prometheus")
        self.harness.add_relation_unit(prometheus_rel_id, "prometheus/0")

        target_rel_id = self.harness.add_relation(SCRAPE_TARGET_RELATION, "target-app")
        self.harness.add_relation_unit(target_rel_id, "target-app/0")

        hostname = "scrape_target_0"
        port = "1234"
        self.harness.update_relation_data(
            target_rel_id,
            "target-app/0",
            {
                "hostname": f"{hostname}",
                "port": f"{port}",
            },
        )

        prometheus_rel_data = self.harness.get_relation_data(
            prometheus_rel_id, self.harness.model.app.name
        )
        scrape_jobs = json.loads(prometheus_rel_data.get("scrape_jobs", "[]"))
        expected_jobs = [
            {
                "job_name": "juju_testmodel_12de4fa_target-app_prometheus_scrape",
                "static_configs": [
                    {
                        "targets": ["scrape_target_0:1234"],
                        "labels": {
                            "juju_model": "testmodel",
                            "juju_model_uuid": "12de4fae-06cc-4ceb-9089-567be09fec78",
                            "juju_application": "target-app",
                            "juju_unit": "target-app/0",
                            "host": "scrape_target_0",
                        },
                    }
                ],
                "relabel_configs": [RELABEL_INSTANCE_CONFIG],
            }
        ]
        self.assertListEqual(scrape_jobs, expected_jobs)

    def test_adding_prometheus_then_target_forwards_a_labeled_alert_rule(self):
        prometheus_rel_id = self.harness.add_relation(PROMETHEUS_RELATION, "prometheus")
        self.harness.add_relation_unit(prometheus_rel_id, "prometheus/0")

        alert_rules_rel_id = self.harness.add_relation(ALERT_RULES_RELATION, "rules-app")
        self.harness.add_relation_unit(alert_rules_rel_id, "rules-app/0")
        self.harness.update_relation_data(
            alert_rules_rel_id, "rules-app/0", {"groups": ALERT_RULE_1}
        )

        prometheus_rel_data = self.harness.get_relation_data(
            prometheus_rel_id, self.harness.model.app.name
        )

        alert_rules = json.loads(prometheus_rel_data.get("alert_rules", "{}"))
        groups = alert_rules.get("groups", [])
        self.assertEqual(len(groups), 1 + len(generic_alert_groups.application_rules))

        labeled_rule = deepcopy(LABELED_ALERT_RULE_1)
        labeled_rule["labels"]["juju_application"] = "rules-app"
        labeled_rule["labels"]["juju_unit"] = "rules-app/0"
        expected_group = {
            "name": "juju_testmodel_12de4fa_rules-app_alert_rules",
            "rules": [labeled_rule],
        }
        self.maxDiff = None
        self.assertIn(expected_group, groups)

    def test_adding_target_then_prometheus_forwards_a_labeled_scrape_job(self):
        target_rel_id = self.harness.add_relation(SCRAPE_TARGET_RELATION, "target-app")
        self.harness.add_relation_unit(target_rel_id, "target-app/0")

        hostname = "scrape_target_0"
        port = "1234"
        self.harness.update_relation_data(
            target_rel_id,
            "target-app/0",
            {
                "hostname": f"{hostname}",
                "port": f"{port}",
            },
        )

        prometheus_rel_id = self.harness.add_relation(PROMETHEUS_RELATION, "prometheus")
        self.harness.add_relation_unit(prometheus_rel_id, "prometheus/0")

        prometheus_rel_data = self.harness.get_relation_data(
            prometheus_rel_id, self.harness.model.app.name
        )
        scrape_jobs = json.loads(prometheus_rel_data.get("scrape_jobs", "[]"))
        expected_jobs = [
            {
                "job_name": "juju_testmodel_12de4fa_target-app_prometheus_scrape",
                "static_configs": [
                    {
                        "targets": ["scrape_target_0:1234"],
                        "labels": {
                            "juju_model": "testmodel",
                            "juju_model_uuid": "12de4fae-06cc-4ceb-9089-567be09fec78",
                            "juju_application": "target-app",
                            "juju_unit": "target-app/0",
                            "host": "scrape_target_0",
                        },
                    }
                ],
                "relabel_configs": [RELABEL_INSTANCE_CONFIG],
            }
        ]
        self.assertListEqual(scrape_jobs, expected_jobs)

    def test_adding_target_then_prometheus_forwards_a_labeled_alert_rule(self):
        prometheus_rel_id = self.harness.add_relation(PROMETHEUS_RELATION, "prometheus")
        self.harness.add_relation_unit(prometheus_rel_id, "prometheus/0")

        alert_rules_rel_id = self.harness.add_relation(ALERT_RULES_RELATION, "rules-app")
        self.harness.add_relation_unit(alert_rules_rel_id, "rules-app/0")
        self.harness.update_relation_data(
            alert_rules_rel_id, "rules-app/0", {"groups": ALERT_RULE_1}
        )

        prometheus_rel_data = self.harness.get_relation_data(
            prometheus_rel_id, self.harness.model.app.name
        )

        alert_rules = json.loads(prometheus_rel_data.get("alert_rules", "{}"))
        groups = alert_rules.get("groups", [])
        self.assertEqual(len(groups), 1 + len(generic_alert_groups.application_rules))

        labeled_rule = deepcopy(LABELED_ALERT_RULE_1)
        labeled_rule["labels"]["juju_application"] = "rules-app"
        labeled_rule["labels"]["juju_unit"] = "rules-app/0"
        expected_group = {
            "name": "juju_testmodel_12de4fa_rules-app_alert_rules",
            "rules": [labeled_rule],
        }

        self.assertIn(expected_group, groups)

    def test_scrape_jobs_from_multiple_target_applications_are_forwarded(self):
        prometheus_rel_id = self.harness.add_relation(PROMETHEUS_RELATION, "prometheus")
        self.harness.add_relation_unit(prometheus_rel_id, "prometheus/0")

        target_rel_id_1 = self.harness.add_relation(SCRAPE_TARGET_RELATION, "target-app-1")
        self.harness.add_relation_unit(target_rel_id_1, "target-app-1/0")
        self.harness.update_relation_data(
            target_rel_id_1,
            "target-app-1/0",
            {
                "hostname": "scrape_target_0",
                "port": "1234",
            },
        )

        target_rel_id_2 = self.harness.add_relation(SCRAPE_TARGET_RELATION, "target-app-2")
        self.harness.add_relation_unit(target_rel_id_2, "target-app-2/0")
        self.harness.update_relation_data(
            target_rel_id_2,
            "target-app-2/0",
            {
                "hostname": "scrape_target_1",
                "port": "5678",
            },
        )

        prometheus_rel_data = self.harness.get_relation_data(
            prometheus_rel_id, self.harness.model.app.name
        )
        scrape_jobs = json.loads(prometheus_rel_data.get("scrape_jobs", "[]"))
        self.assertEqual(len(scrape_jobs), 2)

        expected_jobs = [
            {
                "job_name": "juju_testmodel_12de4fa_target-app-1_prometheus_scrape",
                "static_configs": [
                    {
                        "targets": ["scrape_target_0:1234"],
                        "labels": {
                            "juju_model": "testmodel",
                            "juju_model_uuid": "12de4fae-06cc-4ceb-9089-567be09fec78",
                            "juju_application": "target-app-1",
                            "juju_unit": "target-app-1/0",
                            "host": "scrape_target_0",
                        },
                    }
                ],
                "relabel_configs": [RELABEL_INSTANCE_CONFIG],
            },
            {
                "job_name": "juju_testmodel_12de4fa_target-app-2_prometheus_scrape",
                "static_configs": [
                    {
                        "targets": ["scrape_target_1:5678"],
                        "labels": {
                            "juju_model": "testmodel",
                            "juju_model_uuid": "12de4fae-06cc-4ceb-9089-567be09fec78",
                            "juju_application": "target-app-2",
                            "juju_unit": "target-app-2/0",
                            "host": "scrape_target_1",
                        },
                    }
                ],
                "relabel_configs": [RELABEL_INSTANCE_CONFIG],
            },
        ]

        self.assertListEqual(scrape_jobs, expected_jobs)

    def test_alert_rules_from_multiple_target_applications_are_forwarded(self):
        prometheus_rel_id = self.harness.add_relation(PROMETHEUS_RELATION, "prometheus")
        self.harness.add_relation_unit(prometheus_rel_id, "prometheus/0")

        alert_rules_rel_id_1 = self.harness.add_relation(ALERT_RULES_RELATION, "rules-app-1")
        self.harness.add_relation_unit(alert_rules_rel_id_1, "rules-app-1/0")
        self.harness.update_relation_data(
            alert_rules_rel_id_1,
            "rules-app-1/0",
            {"groups": ALERT_RULE_1},
        )

        alert_rules_rel_id_2 = self.harness.add_relation(ALERT_RULES_RELATION, "rules-app-2")
        self.harness.add_relation_unit(alert_rules_rel_id_2, "rules-app-2/0")
        self.harness.update_relation_data(
            alert_rules_rel_id_2,
            "rules-app-2/0",
            {"groups": ALERT_RULE_2},
        )

        prometheus_rel_data = self.harness.get_relation_data(
            prometheus_rel_id, self.harness.model.app.name
        )

        alert_rules = json.loads(prometheus_rel_data.get("alert_rules", "{}"))
        groups = alert_rules.get("groups", [])
        self.assertEqual(len(groups), 2 + len(generic_alert_groups.application_rules))

        expected_groups = [
            {
                "name": "juju_testmodel_12de4fa_rules-app-1_alert_rules",
                "rules": [LABELED_ALERT_RULE_1],
            },
            {
                "name": "juju_testmodel_12de4fa_rules-app-2_alert_rules",
                "rules": [LABELED_ALERT_RULE_2],
            },
        ]

        for expected in expected_groups:
            self.assertIn(expected, groups)

    def test_scrape_job_removal_differentiates_between_applications(self):
        prometheus_rel_id = self.harness.add_relation(PROMETHEUS_RELATION, "prometheus")
        self.harness.add_relation_unit(prometheus_rel_id, "prometheus/0")

        target_rel_id_1 = self.harness.add_relation("prometheus-target", "target-app-1")
        self.harness.add_relation_unit(target_rel_id_1, "target-app-1/0")
        self.harness.update_relation_data(
            target_rel_id_1,
            "target-app-1/0",
            {
                "hostname": "scrape_target_0",
                "port": "1234",
            },
        )

        target_rel_id_2 = self.harness.add_relation("prometheus-target", "target-app-2")
        self.harness.add_relation_unit(target_rel_id_2, "target-app-2/0")
        self.harness.update_relation_data(
            target_rel_id_2,
            "target-app-2/0",
            {
                "hostname": "scrape_target_1",
                "port": "5678",
            },
        )

        prometheus_rel_data = self.harness.get_relation_data(
            prometheus_rel_id, self.harness.model.app.name
        )
        scrape_jobs = json.loads(prometheus_rel_data.get("scrape_jobs", "[]"))
        self.assertEqual(len(scrape_jobs), 2)

        self.harness.remove_relation_unit(target_rel_id_2, "target-app-2/0")
        scrape_jobs = json.loads(prometheus_rel_data.get("scrape_jobs", "[]"))
        self.assertEqual(len(scrape_jobs), 1)

        expected_jobs = [
            {
                "job_name": "juju_testmodel_12de4fa_target-app-1_prometheus_scrape",
                "static_configs": [
                    {
                        "targets": ["scrape_target_0:1234"],
                        "labels": {
                            "juju_model": "testmodel",
                            "juju_model_uuid": "12de4fae-06cc-4ceb-9089-567be09fec78",
                            "juju_application": "target-app-1",
                            "juju_unit": "target-app-1/0",
                            "host": "scrape_target_0",
                        },
                    }
                ],
                "relabel_configs": [RELABEL_INSTANCE_CONFIG],
            }
        ]
        self.assertListEqual(scrape_jobs, expected_jobs)

    def test_alert_rules_removal_differentiates_between_applications(self):
        prometheus_rel_id = self.harness.add_relation(PROMETHEUS_RELATION, "prometheus")
        self.harness.add_relation_unit(prometheus_rel_id, "prometheus/0")

        alert_rules_rel_id_1 = self.harness.add_relation("prometheus-rules", "rules-app-1")
        self.harness.add_relation_unit(alert_rules_rel_id_1, "rules-app-1/0")
        self.harness.update_relation_data(
            alert_rules_rel_id_1,
            "rules-app-1/0",
            {"groups": ALERT_RULE_1},
        )

        alert_rules_rel_id_2 = self.harness.add_relation("prometheus-rules", "rules-app-2")
        self.harness.add_relation_unit(alert_rules_rel_id_2, "rules-app-2/0")
        self.harness.update_relation_data(
            alert_rules_rel_id_2,
            "rules-app-2/0",
            {"groups": ALERT_RULE_2},
        )

        prometheus_rel_data = self.harness.get_relation_data(
            prometheus_rel_id, self.harness.model.app.name
        )

        alert_rules = json.loads(prometheus_rel_data.get("alert_rules", "{}"))
        groups = alert_rules.get("groups", [])
        self.assertEqual(len(groups), 2 + len(generic_alert_groups.application_rules))

        self.harness.remove_relation_unit(alert_rules_rel_id_2, "rules-app-2/0")
        alert_rules = json.loads(prometheus_rel_data.get("alert_rules", "{}"))
        groups = alert_rules.get("groups", [])
        self.assertEqual(len(groups), 1 + len(generic_alert_groups.application_rules))

        expected_group = {
            "name": "juju_testmodel_12de4fa_rules-app-1_alert_rules",
            "rules": [LABELED_ALERT_RULE_1],
        }

        self.assertIn(expected_group, groups)

    def test_removing_scrape_jobs_differentiates_between_units(self):
        prometheus_rel_id = self.harness.add_relation(PROMETHEUS_RELATION, "prometheus")
        self.harness.add_relation_unit(prometheus_rel_id, "prometheus/0")

        target_rel_id = self.harness.add_relation("prometheus-target", "target-app")
        self.harness.add_relation_unit(target_rel_id, "target-app/0")
        self.harness.update_relation_data(
            target_rel_id,
            "target-app/0",
            {
                "hostname": "scrape_target_0",
                "port": "1234",
            },
        )

        self.harness.add_relation_unit(target_rel_id, "target-app/1")
        self.harness.update_relation_data(
            target_rel_id,
            "target-app/1",
            {
                "hostname": "scrape_target_1",
                "port": "5678",
            },
        )

        prometheus_rel_data = self.harness.get_relation_data(
            prometheus_rel_id, self.harness.model.app.name
        )
        scrape_jobs = json.loads(prometheus_rel_data.get("scrape_jobs", "[]"))

        self.assertEqual(len(scrape_jobs), 1)
        self.assertEqual(len(scrape_jobs[0].get("static_configs")), 2)

        self.harness.remove_relation_unit(target_rel_id, "target-app/1")
        scrape_jobs = json.loads(prometheus_rel_data.get("scrape_jobs", "[]"))

        self.assertEqual(len(scrape_jobs), 1)
        self.assertEqual(len(scrape_jobs[0].get("static_configs")), 1)

        expected_jobs = [
            {
                "job_name": "juju_testmodel_12de4fa_target-app_prometheus_scrape",
                "static_configs": [
                    {
                        "targets": ["scrape_target_0:1234"],
                        "labels": {
                            "juju_model": "testmodel",
                            "juju_model_uuid": "12de4fae-06cc-4ceb-9089-567be09fec78",
                            "juju_application": "target-app",
                            "juju_unit": "target-app/0",
                            "host": "scrape_target_0",
                        },
                    }
                ],
                "relabel_configs": [RELABEL_INSTANCE_CONFIG],
            }
        ]
        self.assertListEqual(scrape_jobs, expected_jobs)

    def test_removing_alert_rules_differentiates_between_units(self):
        prometheus_rel_id = self.harness.add_relation(PROMETHEUS_RELATION, "prometheus")
        self.harness.add_relation_unit(prometheus_rel_id, "prometheus/0")

        alert_rules_rel_id = self.harness.add_relation("prometheus-rules", "rules-app")
        self.harness.add_relation_unit(alert_rules_rel_id, "rules-app/0")
        self.harness.update_relation_data(
            alert_rules_rel_id,
            "rules-app/0",
            {"groups": ALERT_RULE_1},
        )

        self.harness.add_relation_unit(alert_rules_rel_id, "rules-app/1")
        self.harness.update_relation_data(
            alert_rules_rel_id,
            "rules-app/1",
            {"groups": ALERT_RULE_2},
        )

        prometheus_rel_data = self.harness.get_relation_data(
            prometheus_rel_id, self.harness.model.app.name
        )

        alert_rules = json.loads(prometheus_rel_data.get("alert_rules", "{}"))
        groups = alert_rules.get("groups", [])
        self.assertEqual(len(groups), 1 + len(generic_alert_groups.application_rules))

        self.harness.remove_relation_unit(alert_rules_rel_id, "rules-app/1")

        alert_rules = json.loads(prometheus_rel_data.get("alert_rules", "{}"))
        groups = alert_rules.get("groups", [])
        self.assertEqual(len(groups), 1 + len(generic_alert_groups.application_rules))

        labeled_rule = deepcopy(LABELED_ALERT_RULE_1)
        labeled_rule["labels"]["juju_application"] = "rules-app"
        labeled_rule["labels"]["juju_unit"] = "rules-app/0"
        expected_group = {
            "name": "juju_testmodel_12de4fa_rules-app_alert_rules",
            "rules": [labeled_rule],
        }

        self.assertIn(expected_group, groups)

    def test_alert_rules_only_generic(self):
        # GIVEN a prometheus relation
        prometheus_rel_id = self.harness.add_relation(PROMETHEUS_RELATION, "prometheus")
        self.harness.add_relation_unit(prometheus_rel_id, "prometheus/0")

        # WHEN there is no charm related, providing no alert rules
        prometheus_rel_data = self.harness.get_relation_data(
            prometheus_rel_id, self.harness.model.app.name
        )

        alert_rules = json.loads(prometheus_rel_data.get("alert_rules", "{}"))
        groups = alert_rules.get("groups", [])
        # THEN the relation data contains only the generic alerts
        self.assertEqual(len(groups), len(generic_alert_groups.application_rules))
        alert_names_from_reldata = [r["alert"] for g in groups for r in g["rules"]]
        alert_names_expected = [
            r["alert"]
            for g in generic_alert_groups.application_rules["groups"]
            for r in g["rules"]
        ]
        self.assertEqual(alert_names_from_reldata, alert_names_expected)

    def test_deduplication(self):
        # GIVEN unique scrape jobs and alert rule groups
        unique = [
            {
                "job_name": "juju_random_model__scrape_job_1",
                "static_configs": [...],
                "relabel_configs": [...],
            },
            {
                "job_name": "juju_random_model__scrape_job_2",
                "static_configs": [...],
                "relabel_configs": [...],
            },
            {"name": "juju_random_model__alert_rules_1", "rules": [...]},
            {"name": "juju_random_model__alert_rules_2", "rules": [...]},
        ]
        # WHEN there are duplicates
        duplicates = unique + unique
        # THEN they are deduplicated
        assert unique == _dedupe_list(duplicates)


class TestEndpointAggregatorWithRelabeling(unittest.TestCase):
    def setUp(self):
        self.harness = Harness(EndpointResolvingAggregatorCharm, meta=AGGREGATOR_META)
        self.harness.set_model_info(name="testmodel", uuid="12de4fae-06cc-4ceb-9089-567be09fec78")
        self.addCleanup(self.harness.cleanup)
        self.harness.set_leader(True)
        self.harness.begin_with_initial_hooks()

    @patch("socket.gethostbyaddr", new=lambda *args: ("target.harness.example.org",))
    def test_adding_prometheus_then_target_with_good_dns_adds_label(self):
        prometheus_rel_id = self.harness.add_relation(PROMETHEUS_RELATION, "prometheus")
        self.harness.add_relation_unit(prometheus_rel_id, "prometheus/0")

        target_rel_id = self.harness.add_relation(SCRAPE_TARGET_RELATION, "target-app")
        self.harness.add_relation_unit(target_rel_id, "target-app/0")

        hostname = "scrape_target_0"
        port = "1234"
        self.harness.update_relation_data(
            target_rel_id,
            "target-app/0",
            {
                "hostname": f"{hostname}",
                "port": f"{port}",
            },
        )

        prometheus_rel_data = self.harness.get_relation_data(
            prometheus_rel_id, self.harness.model.app.name
        )
        scrape_jobs = json.loads(prometheus_rel_data.get("scrape_jobs", "[]"))
        expected_jobs = [
            {
                "job_name": "juju_testmodel_12de4fa_target-app_prometheus_scrape",
                "static_configs": [
                    {
                        "targets": ["scrape_target_0:1234"],
                        "labels": {
                            "juju_model": "testmodel",
                            "juju_model_uuid": "12de4fae-06cc-4ceb-9089-567be09fec78",
                            "juju_application": "target-app",
                            "juju_unit": "target-app/0",
                            "host": "scrape_target_0",
                            "dns_name": "target.harness.example.org",
                        },
                    }
                ],
                "relabel_configs": [RELABEL_INSTANCE_CONFIG],
            }
        ]
        self.maxDiff = None
        self.assertListEqual(scrape_jobs, expected_jobs)

    @patch("socket.gethostbyaddr")
    def test_adding_prometheus_then_target_with_bad_dns_keeps_input(self, mock_lookup):
        mock_lookup.side_effect = OSError()
        prometheus_rel_id = self.harness.add_relation(PROMETHEUS_RELATION, "prometheus")
        self.harness.add_relation_unit(prometheus_rel_id, "prometheus/0")

        target_rel_id = self.harness.add_relation(SCRAPE_TARGET_RELATION, "target-app")
        self.harness.add_relation_unit(target_rel_id, "target-app/0")

        hostname = "scrape_target_0"
        port = "1234"
        self.harness.update_relation_data(
            target_rel_id,
            "target-app/0",
            {
                "hostname": f"{hostname}",
                "port": f"{port}",
            },
        )

        prometheus_rel_data = self.harness.get_relation_data(
            prometheus_rel_id, self.harness.model.app.name
        )
        scrape_jobs = json.loads(prometheus_rel_data.get("scrape_jobs", "[]"))
        expected_jobs = [
            {
                "job_name": "juju_testmodel_12de4fa_target-app_prometheus_scrape",
                "static_configs": [
                    {
                        "targets": ["scrape_target_0:1234"],
                        "labels": {
                            "juju_model": "testmodel",
                            "juju_model_uuid": "12de4fae-06cc-4ceb-9089-567be09fec78",
                            "juju_application": "target-app",
                            "juju_unit": "target-app/0",
                            "host": "scrape_target_0",
                            "dns_name": "scrape_target_0",
                        },
                    }
                ],
                "relabel_configs": [RELABEL_INSTANCE_CONFIG],
            }
        ]
        self.maxDiff = None
        self.assertListEqual(scrape_jobs, expected_jobs)
