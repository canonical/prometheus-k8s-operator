# Copyright 2020 Canonical Ltd.
# See LICENSE file for licensing details.

import json
import logging
import unittest
import uuid
from string import Template

from charms.prometheus_k8s.v0.prometheus_scrape import (
    ALLOWED_KEYS,
    MetricsEndpointConsumer,
)
from ops.charm import CharmBase
from ops.framework import StoredState
from ops.testing import Harness

from tests.unit.helpers import PROJECT_DIR

logger = logging.getLogger(__name__)

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
    "model_uuid": "12de4fae-06cc-4ceb-9089-567be09fec78",
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
            {"targets": [FULL_TARGET, "*:7000"], "labels": {"some_key": "some-value"}}
        ],
    },
    {
        "job_name": "my-second-job",
        "static_configs": [
            {"targets": ["*:8000"], "labels": {"some_other_key": "some-other-value"}}
        ],
    },
]


ALERT_RULES = {
    "groups": [
        {
            "name": "None_a5edc336-b02e-4fad-b847-c530500c1c86_consumer-tester_alerts",
            "rules": [
                {
                    "alert": "CPUOverUse",
                    "expr": "process_cpu_seconds_total > 0.12",
                    "for": "0m",
                    "labels": {
                        "severity": "Low",
                        "juju_model": "None",
                        "juju_model_uuid": "a5edc336-b02e-4fad-b847-c530500c1c86",
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
                    "expr": "up == 0",
                    "for": "0m",
                    "labels": {
                        "severity": "critical",
                        "juju_model": "None",
                        "juju_model_uuid": "a5edc336-b02e-4fad-b847-c530500c1c86",
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
UNLABELED_ALERT_RULES = {
    "groups": [
        {
            "name": "unlabeled_external_cpu_alerts",
            "rules": [
                {
                    "alert": "CPUOverUse",
                    "expr": 'process_cpu_seconds_total{juju_model="None"}',
                    "for": "0m",
                    "labels": {
                        "severity": "Low",
                    },
                    "annotations": {
                        "summary": "Instance {{ $labels.instance }} CPU over use",
                        "description": "{{ $labels.instance }} of job "
                        "{{ $labels.job }} has used too much CPU.",
                    },
                },
            ],
        },
    ]
}
OTHER_SCRAPE_JOBS = [
    {
        "metrics_path": "/other-path",
        "static_configs": [{"targets": ["*:9000"], "labels": {"other_key": "other-value"}}],
    }
]
OTHER_SCRAPE_METADATA = {
    "model": "consumer-model",
    "model_uuid": "12de4fae-06cc-4ceb-9089-567be09fec78",
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
        metadata_file = open(PROJECT_DIR / "charmcraft.yaml")
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
            rel_id,
            "consumer/0",
            {
                "prometheus_scrape_unit_address": "1.1.1.1",
                "prometheus_scrape_unit_name": "consumer/0",
            },
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
                rel_id,
                "other-consumer/0",
                {
                    "prometheus_scrape_unit_address": "2.2.2.2",
                    "prometheus_scrape_unit_name": "other-consumer/0",
                },
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
                self.assertIn("juju_charm", labels)

            relabel_configs = job["relabel_configs"]
            self.assertEqual(len(relabel_configs), 1)

            relabel_config = relabel_configs[0]
            self.assertGreaterEqual(
                set(relabel_config.get("source_labels")),
                {"juju_model", "juju_model_uuid", "juju_application"},
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
        self.assertEqual(len(jobs), 3)  # two wildcards and one fully-qualified
        self.validate_jobs(jobs)

    def test_consumer_does_not_unit_label_fully_qualified_targets(self):
        self.setup_charm_relations()

        jobs = self.harness.charm.prometheus_consumer.jobs()
        self.assertEqual(len(jobs), 3)  # two wildcards and one fully-qualified
        for job in jobs:
            for static_config in job["static_configs"]:
                if FULL_TARGET in static_config.get("targets"):
                    self.assertNotIn("juju_unit", static_config.get("labels"))

    def test_consumer_does_attach_unit_labels_to_wildcard_hosts(self):
        self.setup_charm_relations()

        jobs = self.harness.charm.prometheus_consumer.jobs()
        self.assertEqual(len(jobs), 3)  # two wildcards and one fully-qualified
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
        self.assertEqual(len(jobs), 4)  # three wildcards and one fully-qualified

    def test_consumer_scrapes_each_port_for_wildcard_hosts(self):
        rel_ids = self.setup_charm_relations()
        self.assertEqual(len(rel_ids), 1)
        rel_id = rel_ids[0]

        jobs = self.harness.charm.prometheus_consumer.jobs()
        self.assertEqual(len(jobs), 3)  # two wildcards and one fully-qualified
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
            rel_id,
            "consumer/0",
            {
                "prometheus_scrape_unit_address": "1.1.1.1",
                "prometheus_scrape_unit_name": "provider/0",
            },
        )
        self.assertEqual(self.harness.charm._stored.num_events, 2)

        jobs = self.harness.charm.prometheus_consumer.jobs()
        self.validate_jobs(jobs)

    def test_consumer_accepts_targets_without_a_port_set(self):
        self.assertEqual(self.harness.charm._stored.num_events, 0)

        rel_id = self.harness.add_relation(RELATION_NAME, "consumer")
        jobs = DEFAULT_JOBS.copy()
        jobs[0]["static_configs"] = [
            {
                "targets": ["*"],
            }
        ]
        self.harness.update_relation_data(
            rel_id,
            "consumer",
            {
                "scrape_metadata": json.dumps(SCRAPE_METADATA),
                "scrape_jobs": json.dumps(jobs),
            },
        )
        self.assertEqual(self.harness.charm._stored.num_events, 1)
        self.harness.add_relation_unit(rel_id, "consumer/0")
        self.harness.update_relation_data(
            rel_id,
            "consumer/0",
            {
                "prometheus_scrape_unit_address": "1.1.1.1",
                "prometheus_scrape_unit_name": "provider/0",
            },
        )
        self.assertEqual(self.harness.charm._stored.num_events, 2)

        jobs = self.harness.charm.prometheus_consumer.jobs()
        self.validate_jobs(jobs)

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

        rules_file = self.harness.charm.prometheus_consumer.alerts
        alerts = list(rules_file.values())[0]

        alert_names = [x["alert"] for x in alerts["groups"][0]["rules"]]

        self.assertEqual(alert_names, ["CPUOverUse", "PrometheusTargetMissing"])

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
        with self.assertLogs(level="WARNING") as logger:
            _ = self.harness.charm.prometheus_consumer.alerts
            messages = logger.output
            self.assertEqual(len(messages), 1)
            self.assertIn(
                "Alert rules were found but no usable group or identifier was present", messages[0]
            )

    def test_consumer_accepts_rules_with_no_identifier(self):
        self.assertEqual(self.harness.charm._stored.num_events, 0)

        rel_id = self.harness.add_relation(RELATION_NAME, "consumer")
        self.harness.update_relation_data(
            rel_id,
            "consumer",
            {
                "alert_rules": json.dumps(UNLABELED_ALERT_RULES),
            },
        )
        self.harness.add_relation_unit(rel_id, "consumer/0")
        self.assertEqual(self.harness.charm._stored.num_events, 1)
        with self.assertLogs(level="DEBUG") as logger:
            _ = self.harness.charm.prometheus_consumer.alerts
            messages = logger.output

            searched_message = (
                "No labeled alert rules were found, and no 'scrape_metadata' "
                "was available. Using the alert group name as filename."
            )
            any_matches = any(searched_message in log_message for log_message in messages)
            self.assertTrue(any_matches)
        alerts = self.harness.charm.prometheus_consumer.alerts
        identifier = f"unlabeled_external_cpu_alerts_{RELATION_NAME}_{rel_id}"
        self.assertIn(identifier, alerts.keys())
        self.assertEqual(UNLABELED_ALERT_RULES, alerts[identifier])

    def test_bad_scrape_job(self):
        self.harness.set_leader(True)
        bad_scrape_jobs = json.dumps(
            [
                {
                    "metrics_path": "/metrics",
                    "static_configs": [{"targets": ["*:3100"]}],
                    "sample_limit": {"not_a_key": "not_a_value"},
                }
            ]
        )
        app_data = {"scrape_jobs": bad_scrape_jobs, "scrape_metadata": json.dumps(SCRAPE_METADATA)}

        rel_id = self.harness.add_relation(RELATION_NAME, "consumer")
        self.harness.add_relation_unit(rel_id, "consumer/0")
        self.harness.update_relation_data(rel_id, "consumer", app_data)
        self.harness.update_relation_data(
            rel_id,
            "consumer/0",
            {
                "prometheus_scrape_unit_address": "1.1.1.1",
                "prometheus_scrape_unit_name": "provider/0",
            },
        )
        jobs = self.harness.charm.prometheus_consumer.jobs()
        self.assertTrue(len(jobs) == 0)
        app_data = json.loads(
            self.harness.get_relation_data(rel_id, self.harness.charm.app.name).get("event", "{}")
        )
        self.assertIn("scrape_job_errors", app_data)


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
    name_prefix = "juju_{}_{}_{}_prometheus_scrape_".format(
        labels["juju_model"],
        labels["juju_model_uuid"][:7],
        labels["juju_application"],
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
        if job["job_name"] in job_name:
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


class TestWildcardTargetsWithMutliunitProvider(unittest.TestCase):
    """Test how scrape jobs of multiunit providers with wildcard-hosts get rendered to disk."""

    def set_relation_data(self, metrics_path: str = None, external_url_path: Template = None):
        job = {
            "job_name": "job",
            "static_configs": [{"targets": ["*:1234"]}],
        }
        if metrics_path:
            job.update({"metrics_path": metrics_path})

        self.harness.update_relation_data(
            self.rel_id,
            "remote-app",
            {
                "scrape_metadata": json.dumps(
                    {
                        "model": self.__class__.__name__,
                        "model_uuid": str(uuid.uuid4()),
                        "application": "remote-app",
                        "charm_name": "some-provider",
                    }
                ),
                "scrape_jobs": json.dumps([job]),
            },
        )

        external_url_path = external_url_path or Template("")
        self.harness.update_relation_data(
            self.rel_id,
            "remote-app/0",
            {
                "prometheus_scrape_unit_address": "10.10.10.10",
                "prometheus_scrape_unit_path": external_url_path.substitute(unit=0),
                "prometheus_scrape_unit_name": "remote-app/0",
            },
        )

        self.harness.update_relation_data(
            self.rel_id,
            "remote-app/1",
            {
                "prometheus_scrape_unit_address": "11.11.11.11",
                "prometheus_scrape_unit_path": external_url_path.substitute(unit=1),
                "prometheus_scrape_unit_name": "remote-app/1",
            },
        )

    def setUp(self):
        metadata_file = open("charmcraft.yaml")
        self.harness = Harness(EndpointConsumerCharm, meta=metadata_file)

        self.rel_id = self.harness.add_relation(RELATION_NAME, "remote-app")
        self.harness.add_relation_unit(self.rel_id, "remote-app/0")
        self.harness.add_relation_unit(self.rel_id, "remote-app/1")

        self.addCleanup(self.harness.cleanup)
        self.harness.begin()

    def test_bare_job(self):
        # WHEN the provider forwards a nice and simple scrape job
        self.set_relation_data(metrics_path=None, external_url_path=None)

        # THEN the consumer side sees two jobs
        # AND one static_config per job
        # AND one target per static_config
        jobs = self.harness.charm.prometheus_consumer.jobs()
        self.assertEqual(len(jobs), 2)  # two jobs, one job per unit
        self.assertEqual(len(jobs[0]["static_configs"]), 1)  # one static_config per unit
        self.assertEqual(len(jobs[1]["static_configs"]), 1)

        # one target per static_config
        self.assertEqual(len(targets_unit_0 := jobs[0]["static_configs"][0]["targets"]), 1)
        self.assertEqual(len(targets_unit_1 := jobs[1]["static_configs"][0]["targets"]), 1)

        # AND the consumer side expands it to unit addresses
        unit_netlocs = sorted([targets_unit_0[0], targets_unit_1[0]])
        self.assertEqual(unit_netlocs, ["10.10.10.10:1234", "11.11.11.11:1234"])

        # AND adds the default metrics_path key
        self.assertEqual(jobs[0]["metrics_path"], "/metrics")

    def test_job_with_metrics_path(self):
        # WHEN the provider specifies a metrics_path
        self.set_relation_data(metrics_path="/custom_path", external_url_path=None)

        # THEN the consumer uses it
        jobs = self.harness.charm.prometheus_consumer.jobs()
        self.assertEqual(jobs[0]["metrics_path"], "/custom_path")

    def test_job_with_same_path_prefix(self):
        # WHEN the provider sets unit addresses with the same path in both units
        self.set_relation_data(metrics_path=None, external_url_path=Template("/foo"))

        # THEN the consumer side sees two jobs
        # AND one static_configs per job
        # AN one target per static_config
        jobs = self.harness.charm.prometheus_consumer.jobs()
        self.assertEqual(len(jobs), 2)  # two jobs
        self.assertEqual(len(jobs[0]["static_configs"]), 1)  # one static_config per unit
        self.assertEqual(len(jobs[1]["static_configs"]), 1)

        # one target per static_config
        self.assertEqual(len(targets_unit_0 := jobs[0]["static_configs"][0]["targets"]), 1)
        self.assertEqual(len(targets_unit_1 := jobs[1]["static_configs"][0]["targets"]), 1)

        # AND the consumer side expands it to unit addresses
        unit_netlocs = sorted([targets_unit_0[0], targets_unit_1[0]])
        self.assertEqual(unit_netlocs, ["10.10.10.10:1234", "11.11.11.11:1234"])

        # AND prefixes the default metrics_path with the unit's path
        self.assertEqual(jobs[0]["metrics_path"], "/foo/metrics")
        self.assertEqual(jobs[1]["metrics_path"], "/foo/metrics")

    def test_job_with_different_path_prefix(self):
        # WHEN the provider sets unit addresses with a path
        self.set_relation_data(metrics_path=None, external_url_path=Template("/model-app-$unit"))

        # THEN the consumer side sees one job per unit
        jobs = self.harness.charm.prometheus_consumer.jobs()
        self.assertEqual(len(jobs), 2)  # one job per unit, so 2 in total
        self.assertEqual(len(jobs[0]["static_configs"]), 1)

        # one target per static_config
        self.assertEqual(len(targets_unit_0 := jobs[0]["static_configs"][0]["targets"]), 1)
        self.assertEqual(len(targets_unit_1 := jobs[1]["static_configs"][0]["targets"]), 1)

        # AND the consumer side expands it to unit addresses
        unit_netlocs = sorted([targets_unit_0[0], targets_unit_1[0]])
        self.assertEqual(unit_netlocs, ["10.10.10.10:1234", "11.11.11.11:1234"])

        # AND prefixes the default metrics_path with the unit's path
        paths = sorted([jobs[0]["metrics_path"], jobs[1]["metrics_path"]])
        self.assertEqual(paths, ["/model-app-0/metrics", "/model-app-1/metrics"])

    def test_job_with_port_and_path_prefix(self):
        # WHEN the provider sets unit addresses with a path and also specifies metrics_path
        self.set_relation_data(
            metrics_path="/custom-path", external_url_path=Template("/model-app-$unit")
        )

        # THEN the provider's metrics_path appended to the unit's path instead of the default
        jobs = self.harness.charm.prometheus_consumer.jobs()
        paths = sorted([jobs[0]["metrics_path"], jobs[1]["metrics_path"]])
        self.assertEqual(paths, ["/model-app-0/custom-path", "/model-app-1/custom-path"])
