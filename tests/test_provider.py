# Copyright 2020 Canonical Ltd.
# See LICENSE file for licensing details.

import json
import unittest

from ops.charm import CharmBase
from ops.framework import StoredState
from ops.testing import Harness
from prometheus_provider import MonitoringProvider


class PrometheusCharm(CharmBase):
    _stored = StoredState()

    def __init__(self, *args, **kwargs):
        super().__init__(*args)
        self._stored.set_default(num_events=0)
        self.prometheus_provider = MonitoringProvider(self,
                                                      "monitoring",
                                                      "prometheus",
                                                      self.version)
        self.framework.observe(self.prometheus_provider.on.targets_changed,
                               self.record_events)

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

    def test_provider_notifies_on_new_scrape_targets(self):
        self.assertEqual(len(self.harness.charm.prometheus_provider._stored.jobs), 0)
        self.assertEqual(self.harness.charm._stored.num_events, 0)
        rel_id = self.harness.add_relation("monitoring", "target")
        target_ip = "1.1.1.1"
        self.harness.update_relation_data(rel_id, "target", {
            "targets": json.dumps([target_ip])
        })
        jobs = self.harness.charm.prometheus_provider._stored.jobs['rel_id']
        jobs = json.loads(jobs)
        self.assertIsNotNone(jobs)
        static_configs = jobs.get('static_configs', None)
        self.assertIsNotNone(static_configs)
        self.assertEqual(len(static_configs), 1)
        targets = static_configs[0].get("targets", None)
        self.assertIsNotNone(targets)
        self.assertEqual(len(targets), 1)
        target = targets[0]
        self.assertEqual(target, target_ip)
        self.assertEqual(self.harness.charm._stored.num_events, 1)
