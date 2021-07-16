# Copyright 2020 Canonical Ltd.
# See LICENSE file for licensing details.

import json
import unittest

from ops.charm import CharmBase
from ops.framework import StoredState
from ops.testing import Harness
from charms.prometheus_k8s.v1.prometheus import PrometheusProvider

SCRAPE_METADATA = {
    "model": "consumer-model",
    "model_uuid": "abcdef",
    "application": "consumer",
}
SCRAPE_JOBS = [
    {"static_configs": [{"targets": ["*:8000"], "labels": {"status": "testing"}}]}
]


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

    def test_provider_returns_static_scrape_jobs(self):
        self.assertEqual(self.harness.charm._stored.num_events, 0)
        rel_id = self.harness.add_relation("monitoring", "consumer")
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
        jobs = self.harness.charm.prometheus_provider.jobs()
        self.assertEqual(len(jobs), 1)
        job = jobs[0]
        self.assertIn("job_name", job)
        self.assertIn("static_configs", job)
        static_configs = job["static_configs"]
        self.assertEqual(len(static_configs), 1)
        static_config = static_configs[0]
        self.assertIn("targets", static_config)
        self.assertIn("labels", static_config)
        targets = static_config["targets"]
        self.assertEqual(len(targets), 1)
        labels = static_config["labels"]
        self.assertIn("juju_model", labels)
        self.assertIn("juju_model_uuid", labels)
        self.assertIn("juju_application", labels)
        self.assertIn("juju_unit", labels)
