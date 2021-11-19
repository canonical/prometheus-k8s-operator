# Copyright 2020 Canonical Ltd.
# See LICENSE file for licensing details.

import json
import unittest

from charms.prometheus_k8s.v0.prometheus_scrape import (
    ALLOWED_KEYS,
    MetricsEndpointConsumer,
)
from ops.charm import CharmBase
from ops.framework import StoredState
from ops.testing import Harness

RELATION_NAME = "metrics-endpoint"
DEFAULT_JOBS = [{"metrics_path": "/metrics"}]
BAD_JOBS = [
    {
        "metrics_path": "/metrics",
        "static_configs": [
            {
                "targets": ["*:80"],
                "labels": {
                    "juju_model": "bad_model",
                    "juju_application": "bad_application",
                    "juju_model_uuid": "bad_uuid",
                    "juju_unit": "bad_unit",
                    "juju_charm": "bad_charm",
                },
            }
        ],
    }
]

SCRAPE_METADATA = {
    "model": "consumer-model",
    "model_uuid": "abcdef",
    "application": "consumer",
    "charm_name": "test-charm",
}
FULL_TARGET = "10.1.238.1:6000"
SCRAPE_JOBS = [
    {
        "global": {"scrape_interval": "1h"},
        "rule_files": ["/some/file"],
        "file_sd_configs": [{"files": "*some-files*"}],
        "job_name": "my-first-job",
        "metrics_path": "/one-path",
        "static_configs": [
            {"targets": [FULL_TARGET, "*:7000"], "labels": {"some-key": "some-value"}}
        ],
    },
    {
        "job_name": "my-second-job",
        "static_configs": [
            {"targets": ["*:8000"], "labels": {"some-other-key": "some-other-value"}}
        ],
    },
]
ALERT_RULES = {
    "groups": [
        {
            "name": "None_f2c1b2a6-e006-11eb-ba80-0242ac130004_consumer-tester_alerts",
            "rules": [
                {
                    "alert": "CPUOverUse",
                    "expr": 'process_cpu_seconds_total{juju_model="None",'
                    'juju_model_uuid="f2c1b2a6-e006-11eb-ba80-0242ac130004",'
                    'juju_application="consumer-tester"} > 0.12',
                    "for": "0m",
                    "labels": {
                        "severity": "Low",
                        "juju_model": "None",
                        "juju_model_uuid": "f2c1b2a6-e006-11eb-ba80-0242ac130004",
                        "juju_application": "consumer-tester",
                    },
                    "annotations": {
                        "summary": "Instance {{ $labels.instance }} CPU over use",
                        "description": "{{ $labels.instance }} of job "
                        "{{ $labels.job }} has used too much CPU.",
                    },
                },
                {
                    "alert": "PrometheusTargetMissing",
                    "expr": 'up{juju_model="None",'
                    'juju_model_uuid="f2c1b2a6-e006-11eb-ba80-0242ac130004",'
                    'juju_application="consumer-tester"} == 0',
                    "for": "0m",
                    "labels": {
                        "severity": "critical",
                        "juju_model": "None",
                        "juju_model_uuid": "f2c1b2a6-e006-11eb-ba80-0242ac130004",
                        "juju_application": "consumer-tester",
                    },
                    "annotations": {
                        "summary": "Prometheus target missing (instance {{ $labels.instance }})",
                        "description": "A Prometheus target has disappeared."
                        "An exporter might be crashed.\n"
                        "VALUE = {{ $value }}\n  LABELS = {{ $labels }}",
                    },
                },
            ],
        }
    ]
}
OTHER_SCRAPE_JOBS = [
    {
        "metrics_path": "/other-path",
        "static_configs": [{"targets": ["*:9000"], "labels": {"other-key": "other-value"}}],
    }
]
OTHER_SCRAPE_METADATA = {
    "model": "consumer-model",
    "model_uuid": "hijklm",
    "application": "other-consumer",
    "charm_name": "other-charm",
}


class EndpointConsumerCharm(CharmBase):
    _stored = StoredState()

    def __init__(self, *args, **kwargs):
        super().__init__(*args)
        self._stored.set_default(num_events=0)
        self.prometheus_consumer = MetricsEndpointConsumer(self, RELATION_NAME)
        self.framework.observe(self.prometheus_consumer.on.targets_changed, self.record_events)

    def record_events(self, event):
        self._stored.num_events += 1

    @property
    def version(self):
        return "1.0.0"


class TestEndpointConsumer(unittest.TestCase):
    def setUp(self):
        metadata_file = open("metadata.yaml")
        self.harness = Harness(EndpointConsumerCharm, meta=metadata_file)
        self.addCleanup(self.harness.cleanup)
        self.harness.begin()

    def setup_charm_relations(self, multi=False):
        """Create relations used by test cases.

        Args:
            multi: a boolean indicating if multiple relations must be
            created.
        """
        rel_ids = []
        self.assertEqual(self.harness.charm._stored.num_events, 0)
        rel_id = self.harness.add_relation(RELATION_NAME, "consumer")
        rel_ids.append(rel_id)
        self.harness.update_relation_data(
            rel_id,
            "consumer",
            {
                "scrape_metadata": json.dumps(SCRAPE_METADATA),
                "scrape_jobs": json.dumps(SCRAPE_JOBS),
            },
        )
        self.harness.add_relation_unit(rel_id, "consumer/0")
        self.harness.update_relation_data(
            rel_id, "consumer/0", {"prometheus_scrape_host": "1.1.1.1"}
        )
        self.assertEqual(self.harness.charm._stored.num_events, 2)

        if multi:
            rel_id = self.harness.add_relation(RELATION_NAME, "other-consumer")
            rel_ids.append(rel_id)
            self.harness.update_relation_data(
                rel_id,
                "other-consumer",
                {
                    "scrape_metadata": json.dumps(OTHER_SCRAPE_METADATA),
                    "scrape_jobs": json.dumps(OTHER_SCRAPE_JOBS),
                },
            )
            self.harness.add_relation_unit(rel_id, "other-consumer/0")
            self.harness.update_relation_data(
                rel_id, "other-consumer/0", {"prometheus_scrape_host": "2.2.2.2"}
            )
            self.assertEqual(self.harness.charm._stored.num_events, 4)

        return rel_ids

    def validate_jobs(self, jobs):
        """Valdiate that a list of jobs has the expected fields.

        Existence for unit labels is not checked since these do not
        exist for all jobs.

        Args:
            jobs: list of jobs where each job is a dictionary.

        Raises:
            assertion failures if any job is not as expected.
        """
        for job in jobs:
            self.assertIn("job_name", job)
            self.assertIn("static_configs", job)
            static_configs = job["static_configs"]
            for static_config in static_configs:
                self.assertIn("targets", static_config)
                self.assertIn("labels", static_config)
                labels = static_config["labels"]
                self.assertIn("juju_model", labels)
                self.assertIn("juju_model_uuid", labels)
                self.assertIn("juju_application", labels)

            relabel_configs = job["relabel_configs"]
            self.assertEqual(len(relabel_configs), 1)

            relabel_config = relabel_configs[0]
            self.assertEqual(
                relabel_config.get("source_labels"),
                ["juju_model", "juju_model_uuid", "juju_application", "juju_unit"],
            )

    def test_consumer_notifies_on_new_scrape_relation(self):
        self.assertEqual(self.harness.charm._stored.num_events, 0)

        rel_id = self.harness.add_relation(RELATION_NAME, "consumer")
        self.harness.update_relation_data(
            rel_id, "consumer", {"scrape_metadata": json.dumps(SCRAPE_METADATA)}
        )
        self.assertEqual(self.harness.charm._stored.num_events, 1)

    def test_consumer_notifies_on_new_scrape_target(self):
        self.assertEqual(self.harness.charm._stored.num_events, 0)
        rel_id = self.harness.add_relation(RELATION_NAME, "consumer")
        self.harness.add_relation_unit(rel_id, "consumer/0")
        self.harness.update_relation_data(
            rel_id, "consumer/0", {"prometheus_scrape_host": "1.1.1.1"}
        )
        self.assertEqual(self.harness.charm._stored.num_events, 1)

    def test_consumer_returns_all_static_scrape_labeled_jobs(self):
        self.setup_charm_relations()

        jobs = self.harness.charm.prometheus_consumer.jobs()
        self.assertEqual(len(jobs), len(SCRAPE_JOBS))
        self.validate_jobs(jobs)

    def test_consumer_does_not_unit_label_fully_qualified_targets(self):
        self.setup_charm_relations()

        jobs = self.harness.charm.prometheus_consumer.jobs()
        self.assertEqual(len(jobs), len(SCRAPE_JOBS))
        for job in jobs:
            for static_config in job["static_configs"]:
                if FULL_TARGET in static_config.get("targets"):
                    self.assertNotIn("juju_unit", static_config.get("labels"))

    def test_consumer_does_attach_unit_labels_to_wildcard_hosts(self):
        self.setup_charm_relations()

        jobs = self.harness.charm.prometheus_consumer.jobs()
        self.assertEqual(len(jobs), len(SCRAPE_JOBS))
        for job in jobs:
            for static_config in job["static_configs"]:
                if FULL_TARGET not in static_config.get("targets"):
                    self.assertIn("juju_unit", static_config.get("labels"))

    def test_consumer_allows_custom_metrics_paths(self):
        rel_ids = self.setup_charm_relations()
        self.assertEqual(len(rel_ids), 1)
        rel_id = rel_ids[0]

        jobs = self.harness.charm.prometheus_consumer.jobs()
        for job in jobs:
            if job.get("metrics_path"):
                name_suffix = job_name_suffix(job["job_name"], juju_job_labels(job), rel_id)
                path = named_job_attribute(name_suffix, "metrics_path", "/metrics")
                self.assertEqual(job["metrics_path"], path)

    def test_consumer_sanitizes_jobs(self):
        self.setup_charm_relations()

        jobs = self.harness.charm.prometheus_consumer.jobs()
        for job in jobs:
            job_keys = set(job.keys())
            self.assertTrue(job_keys.issubset(ALLOWED_KEYS))

    def test_consumer_returns_jobs_for_all_relations(self):
        self.setup_charm_relations(multi=True)

        jobs = self.harness.charm.prometheus_consumer.jobs()
        self.assertEqual(len(jobs), len(SCRAPE_JOBS) + len(OTHER_SCRAPE_JOBS))

    def test_consumer_scrapes_each_port_for_wildcard_hosts(self):
        rel_ids = self.setup_charm_relations()
        self.assertEqual(len(rel_ids), 1)
        rel_id = rel_ids[0]

        jobs = self.harness.charm.prometheus_consumer.jobs()
        self.assertEqual(len(jobs), len(SCRAPE_JOBS))
        ports = wildcard_target_ports(SCRAPE_JOBS)
        targets = wildcard_targets(jobs, ports)
        consumers = self.harness.charm.model.get_relation(RELATION_NAME, rel_id)
        self.assertEqual(len(targets), len(ports) * len(consumers.units))

    def test_consumer_handles_default_scrape_job(self):
        self.assertEqual(self.harness.charm._stored.num_events, 0)

        rel_id = self.harness.add_relation(RELATION_NAME, "consumer")
        self.harness.update_relation_data(
            rel_id,
            "consumer",
            {
                "scrape_metadata": json.dumps(SCRAPE_METADATA),
                "scrape_jobs": json.dumps(DEFAULT_JOBS),
            },
        )
        self.assertEqual(self.harness.charm._stored.num_events, 1)
        self.harness.add_relation_unit(rel_id, "consumer/0")
        self.harness.update_relation_data(
            rel_id, "consumer/0", {"prometheus_scrape_host": "1.1.1.1"}
        )
        self.assertEqual(self.harness.charm._stored.num_events, 2)

        jobs = self.harness.charm.prometheus_consumer.jobs()
        self.validate_jobs(jobs)

    def test_consumer_overwrites_juju_topology_labels(self):
        self.assertEqual(self.harness.charm._stored.num_events, 0)
        rel_id = self.harness.add_relation(RELATION_NAME, "consumer")
        self.harness.update_relation_data(
            rel_id,
            "consumer",
            {
                "scrape_metadata": json.dumps(SCRAPE_METADATA),
                "scrape_jobs": json.dumps(BAD_JOBS),
            },
        )
        self.assertEqual(self.harness.charm._stored.num_events, 1)
        self.harness.add_relation_unit(rel_id, "consumer/0")
        self.harness.update_relation_data(
            rel_id, "consumer/0", {"prometheus_scrape_host": "1.1.1.1"}
        )
        self.assertEqual(self.harness.charm._stored.num_events, 2)

        jobs = self.harness.charm.prometheus_consumer.jobs()
        self.assertEqual(len(jobs), 1)
        self.validate_jobs(jobs)
        bad_labels = juju_job_labels(BAD_JOBS[0])
        labels = juju_job_labels(jobs[0])
        for label_name, label_value in labels.items():
            self.assertNotEqual(label_value, bad_labels[label_name])

    def test_consumer_returns_alerts_rules_file(self):
        self.assertEqual(self.harness.charm._stored.num_events, 0)

        rel_id = self.harness.add_relation(RELATION_NAME, "consumer")
        self.harness.update_relation_data(
            rel_id,
            "consumer",
            {
                "scrape_metadata": json.dumps(SCRAPE_METADATA),
                "alert_rules": json.dumps(ALERT_RULES),
            },
        )
        self.harness.add_relation_unit(rel_id, "consumer/0")
        self.assertEqual(self.harness.charm._stored.num_events, 1)

        rules_file = self.harness.charm.prometheus_consumer.alerts()
        self.maxDiff = None
        alerts = list(rules_file.values())[0]
        self.assertEqual(ALERT_RULES, alerts)

    def test_consumer_logs_an_error_on_missing_alerting_data(self):
        self.assertEqual(self.harness.charm._stored.num_events, 0)

        bad_metadata = {"bad": "metadata"}
        bad_rules = {"bad": "rule"}

        rel_id = self.harness.add_relation(RELATION_NAME, "consumer")
        self.harness.update_relation_data(
            rel_id,
            "consumer",
            {
                "scrape_metadata": json.dumps(bad_metadata),
                "alert_rules": json.dumps(bad_rules),
            },
        )
        self.harness.add_relation_unit(rel_id, "consumer/0")
        self.assertEqual(self.harness.charm._stored.num_events, 1)
        with self.assertLogs(level="ERROR") as logger:
            _ = self.harness.charm.prometheus_consumer.alerts()
            messages = sorted(logger.output)
            self.assertEqual(len(messages), 1)
            self.assertIn(f"Relation {rel_id} has invalid data", messages[0])


def juju_job_labels(job, num=0):
    """Fetch job labels.

    Args:
        job: a list of static scrape jobs
        num: index of static config for which labels must be extracted.

    Returns:
        a dictionary of job labels for the first static job.
    """
    static_config = job["static_configs"][num]
    return static_config["labels"]


def job_name_suffix(job_name, labels, rel_id):
    """Construct provider set job name.

    Args:
        job_name: Consumer generated job name string.
        labels: dictionary of juju static job labels
        rel_id: id of relation for this job.

    Returns:
        string name of job as set by provider (if any)
    """
    name_prefix = "juju_{}_{}_{}_prometheus_{}_scrape_".format(
        labels["juju_model"],
        labels["juju_model_uuid"][:7],
        labels["juju_application"],
        rel_id,
    )
    return job_name[len(name_prefix) :]


def named_job_attribute(job_name, attribute, default=None, jobs=SCRAPE_JOBS):
    """Fetch and attribute of a named job_name.

    Args:
        job_name: string name suffix of job_name.
        attribute: string name of attribute.
        default: optional default value to be returned if attribute is not found.
        jobs: optional list of jobs to search for job_name.

    Returns:
        value of requested attribute if found or default.
    """
    for job in jobs:
        if job["job_name"].endswith(job_name):
            return job.get(attribute, default)
    return None


def wildcard_target_ports(jobs):
    """Fetch list of wildcard target ports from a job list.

    Args:
        jobs: list of jobs to search for wildcard target ports.

    Returns:
        possibly empty list of wildcard target ports.
    """
    ports = []
    for job in jobs:
        for static_config in job["static_configs"]:
            for target in static_config["targets"]:
                if target.startswith("*"):
                    ports.append(target.split(":")[-1])
    return ports


def wildcard_targets(jobs, wildcard_ports):
    """Fetch list of wildcard targets.

    Args:
        jobs: list of jobs to be searched.
        wildcard_ports: ports of wildcard targets.

    Returns:
       possibly empty list of wildcard targets.
    """
    targets = []
    for job in jobs:
        for static_config in job["static_configs"]:
            for target in static_config["targets"]:
                for port in wildcard_ports:
                    if target.endswith(port):
                        targets.append(target)
    return targets
