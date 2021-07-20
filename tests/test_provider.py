# Copyright 2020 Canonical Ltd.
# See LICENSE file for licensing details.

import json
import unittest

from ops.charm import CharmBase
from ops.framework import StoredState
from ops.testing import Harness
from charms.prometheus_k8s.v0.prometheus import PrometheusProvider

SCRAPE_METADATA = {
    "model": "consumer-model",
    "model_uuid": "abcdef",
    "application": "consumer",
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
OTHER_SCRAPE_JOBS = [
    {
        "metrics_path": "/other-path",
        "static_configs": [
            {"targets": ["*:9000"], "labels": {"other-key": "other-value"}}
        ],
    }
]
OTHER_SCRAPE_METADATA = {
    "model": "consumer-model",
    "model_uuid": "hijklm",
    "application": "other-consumer",
}
ALLOWED_KEYS = {"job_name", "metrics_path", "static_configs"}


class PrometheusCharm(CharmBase):
    _stored = StoredState()

    def __init__(self, *args, **kwargs):
        super().__init__(*args)
        self._stored.set_default(num_events=0)
        self.prometheus_provider = PrometheusProvider(
            self, "monitoring", "prometheus", self.version
        )
        self.framework.observe(
            self.prometheus_provider.on.targets_changed, self.record_events
        )

    def record_events(self, event):
        self._stored.num_events += 1

    @property
    def version(self):
        return "1.0.0"


class TestProvider(unittest.TestCase):
    def setUp(self):
        self.harness = Harness(PrometheusCharm)
        self.addCleanup(self.harness.cleanup)
        self.harness.set_leader(True)
        self.harness.begin()

    def setup_charm_relations(self, multi=False):
        rel_ids = []
        self.assertEqual(self.harness.charm._stored.num_events, 0)
        rel_id = self.harness.add_relation("monitoring", "consumer")
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
            rel_id = self.harness.add_relation("monitoring", "other-consumer")
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

    def test_provider_notifies_on_new_scrape_relation(self):
        self.assertEqual(self.harness.charm._stored.num_events, 0)

        rel_id = self.harness.add_relation("monitoring", "consumer")
        self.harness.update_relation_data(
            rel_id, "consumer", {"scrape_metadata": json.dumps(SCRAPE_METADATA)}
        )
        self.assertEqual(self.harness.charm._stored.num_events, 1)

    def test_provider_notifies_on_new_scrape_target(self):
        self.assertEqual(self.harness.charm._stored.num_events, 0)
        rel_id = self.harness.add_relation("monitoring", "consumer")
        self.harness.add_relation_unit(rel_id, "consumer/0")
        self.harness.update_relation_data(
            rel_id, "consumer/0", {"prometheus_scrape_host": "1.1.1.1"}
        )
        self.assertEqual(self.harness.charm._stored.num_events, 1)

    def test_provider_returns_all_static_scrape_labeled_jobs(self):
        self.setup_charm_relations()

        jobs = self.harness.charm.prometheus_provider.jobs()
        self.assertEqual(len(jobs), len(SCRAPE_JOBS))
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

    def test_provider_does_not_unit_label_fully_qualified_targets(self):
        self.setup_charm_relations()

        jobs = self.harness.charm.prometheus_provider.jobs()
        self.assertEqual(len(jobs), len(SCRAPE_JOBS))
        for job in jobs:
            for static_config in job["static_configs"]:
                if FULL_TARGET in static_config.get("targets"):
                    self.assertNotIn("juju_unit", static_config.get("labels"))

    def test_provider_does_attach_unit_labels_to_wildcard_hosts(self):
        self.setup_charm_relations()

        jobs = self.harness.charm.prometheus_provider.jobs()
        self.assertEqual(len(jobs), len(SCRAPE_JOBS))
        for job in jobs:
            for static_config in job["static_configs"]:
                if FULL_TARGET not in static_config.get("targets"):
                    self.assertIn("juju_unit", static_config.get("labels"))

    def test_provider_allows_custom_metrics_paths(self):
        self.setup_charm_relations()

        jobs = self.harness.charm.prometheus_provider.jobs()
        for job in jobs:
            if job.get("metrics_path"):
                name_suffix = job["job_name"].split("-")[-1]
                path = named_job_attribute(name_suffix, "metrics_path")
                self.assertEqual(job["metrics_path"], path)

    def test_provider_sanitizes_jobs(self):
        self.setup_charm_relations()

        jobs = self.harness.charm.prometheus_provider.jobs()
        for job in jobs:
            job_keys = set(job.keys())
            self.assertTrue(job_keys.issubset(ALLOWED_KEYS))

    def test_provider_returns_jobs_for_all_relations(self):
        self.setup_charm_relations(multi=True)

        jobs = self.harness.charm.prometheus_provider.jobs()
        self.assertEqual(len(jobs), len(SCRAPE_JOBS) + len(OTHER_SCRAPE_JOBS))

    def test_provider_scrapes_each_port_for_wildcard_hosts(self):
        rel_ids = self.setup_charm_relations()
        self.assertEqual(len(rel_ids), 1)
        rel_id = rel_ids[0]

        jobs = self.harness.charm.prometheus_provider.jobs()
        self.assertEqual(len(jobs), len(SCRAPE_JOBS))
        ports = wildcard_target_ports(SCRAPE_JOBS)
        targets = wildcard_targets(jobs, ports)
        consumers = self.harness.charm.model.get_relation("monitoring", rel_id)
        self.assertEqual(len(targets), len(ports) * len(consumers.units))


def named_job_attribute(job_name, attribute, jobs=SCRAPE_JOBS):
    """Fetch and attribute of a named job_name.

    Args:
        job_name: string name suffix of job_name.
        attribute: string name of attribute.
        jobs: optional list of jobs to search for job_name.

    Returns:
        value of requested attribute if found or None.
    """
    for job in jobs:
        if job["job_name"].endswith(job_name):
            return job[attribute]
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
