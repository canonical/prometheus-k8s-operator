# Copyright 2020 Canonical Ltd.
# See LICENSE file for licensing details.

import json
import unittest

from ops.charm import CharmBase
from ops.framework import StoredState
from ops.testing import Harness
from charms.prometheus_k8s.v1.prometheus import PrometheusConsumer


class ConsumerCharm(CharmBase):
    _stored = StoredState()

    def __init__(self, *args, **kwargs):
        super().__init__(*args)
        self.provider = PrometheusConsumer(self,
                                           "monitoring",
                                           {"prometheus": ">=2.0"})

    def new_endpoint(self, ip, port):
        self.provider.add_endpoint(ip, port=port)

    def clear_endpoint(self, ip, port):
        self.provider.remove_endpoint(ip, port)


class TestLibrary(unittest.TestCase):
    def setUp(self):
        self.harness = Harness(ConsumerCharm)
        self.addCleanup(self.harness.cleanup)
        self.harness.set_leader(True)
        self.harness.begin()

    def test_consumer_can_set_an_endpoint(self):
        rel_id = self.harness.add_relation("monitoring", "provider")
        ip_set = "1.1.1.1"
        port_set = 8000
        data = self.harness.get_relation_data(rel_id, self.harness.model.app.name)
        self.assertFalse(data)
        self.harness.charm.new_endpoint(ip_set, port_set)
        data = self.harness.get_relation_data(rel_id, self.harness.model.app.name)
        self.assertIn("targets", data)
        target = json.loads(data["targets"])[0]
        ip, port = target.split(":")
        self.assertEqual(ip, ip_set)
        self.assertEqual(int(port), port_set)

    def test_consumer_can_remove_an_endpoint(self):
        rel_id = self.harness.add_relation("monitoring", "provider")
        ip_set = "1.1.1.1"
        port_set = 8000
        self.harness.charm.new_endpoint(ip_set, port_set)
        data = self.harness.get_relation_data(rel_id, self.harness.model.app.name)
        self.assertIn("targets", data)
        self.harness.charm.clear_endpoint(ip_set, port_set)
        data = self.harness.get_relation_data(rel_id, self.harness.model.app.name)
        target = json.loads(data["targets"])
        self.assertFalse(target)
