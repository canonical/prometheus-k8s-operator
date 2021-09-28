# Copyright 2020 Canonical Ltd.
# See LICENSE file for licensing details.

import unittest
from unittest.mock import patch

from charms.prometheus_k8s.v0.prometheus_remote_write import (
    PrometheusRemoteWriteConsumer,
)
from ops.charm import CharmBase
from ops.testing import Harness

from charm import PrometheusCharm

RELATION = "remote-write"
PROVIDER_RELATION = "receive-remote-write"
METADATA = f"""
name: consumer-tester
requires:
  {RELATION}:
    interface: prometheus_remote_write
"""


class RemoteWriteConsumerCharm(CharmBase):
    def __init__(self, *args, **kwargs):
        super().__init__(*args)
        self.provider = PrometheusRemoteWriteConsumer(self, RELATION)


class TestRemoteWriteConsumer(unittest.TestCase):
    def setUp(self):
        self.harness = Harness(RemoteWriteConsumerCharm, meta=METADATA)
        self.addCleanup(self.harness.cleanup)
        self.harness.begin()

    def test_address_is_set(self):
        rel_id = self.harness.add_relation(RELATION, "provider")
        self.harness.add_relation_unit(rel_id, "provider/0")
        self.harness.update_relation_data(rel_id, "provider/0", {"address": "1.1.1.1"})
        self.harness.update_relation_data(rel_id, "provider/0", {"port": "9090"})
        assert list(self.harness.charm.provider.endpoints) == ["http://1.1.1.1:9090/api/v1/write"]

    def test_config_is_set(self):
        rel_id = self.harness.add_relation(RELATION, "provider")
        self.harness.add_relation_unit(rel_id, "provider/0")
        self.harness.update_relation_data(rel_id, "provider/0", {"address": "1.1.1.1"})
        self.harness.update_relation_data(rel_id, "provider/0", {"port": "9090"})
        assert list(self.harness.charm.provider.configs) == [
            {"url": "http://1.1.1.1:9090/api/v1/write"}
        ]

    def test_no_address_provided(self):
        rel_id = self.harness.add_relation(RELATION, "provider")
        self.harness.add_relation_unit(rel_id, "provider/0")
        self.harness.update_relation_data(rel_id, "provider/0", {"port": "9090"})
        assert list(self.harness.charm.provider.endpoints) == []

    def test_no_port_provided(self):
        rel_id = self.harness.add_relation(RELATION, "provider")
        self.harness.add_relation_unit(rel_id, "provider/0")
        self.harness.update_relation_data(rel_id, "provider/0", {"address": "1.1.1.1"})
        assert list(self.harness.charm.provider.endpoints) == []


class TestRemoteWriteProvider(unittest.TestCase):
    def setUp(self):
        self.harness = Harness(PrometheusCharm)
        self.addCleanup(self.harness.cleanup)
        self.harness.begin()

    @patch("ops.testing._TestingPebbleClient.remove_path")
    @patch("ops.testing._TestingPebbleClient.push")
    def test_port_is_set(self, *unused):
        rel_id = self.harness.add_relation(PROVIDER_RELATION, "consumer")
        self.harness.add_relation_unit(rel_id, "consumer/0")
        assert (
            self.harness.get_relation_data(rel_id, self.harness.charm.unit.name)["port"] == "9090"
        )
