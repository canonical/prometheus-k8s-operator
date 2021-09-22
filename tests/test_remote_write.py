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
PROVIDER_RELATION = "remote-write-server"
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

    def test_addr(self):
        rel_id = self.harness.add_relation(RELATION, "provider")
        self.harness.add_relation_unit(rel_id, "provider/0")
        self.harness.update_relation_data(rel_id, "provider/0", {"ingress-address": "1.1.1.1"})
        self.harness.update_relation_data(rel_id, "provider/0", {"port": "9090"})
        assert list(self.harness.charm.provider.endpoints) == ["http://1.1.1.1:9090/api/v1/write"]

    def test_config(self):
        rel_id = self.harness.add_relation(RELATION, "provider")
        self.harness.add_relation_unit(rel_id, "provider/0")
        self.harness.update_relation_data(rel_id, "provider/0", {"ingress-address": "1.1.1.1"})
        self.harness.update_relation_data(rel_id, "provider/0", {"port": "9090"})
        assert list(self.harness.charm.provider.configs) == [
            {"url": "http://1.1.1.1:9090/api/v1/write"}
        ]

    def test_external_address(self):
        rel_id = self.harness.add_relation(RELATION, "provider")
        self.harness.add_relation_unit(rel_id, "provider/0")
        self.harness.update_relation_data(rel_id, "provider/0", {"ingress-address": "1.1.1.1"})
        self.harness.update_relation_data(rel_id, "provider/0", {"port": "9090"})
        self.harness.update_relation_data(rel_id, "provider/0", {"external-address": "2.2.2.2"})
        assert list(self.harness.charm.provider.endpoints) == ["http://2.2.2.2:9090/api/v1/write"]

    def test_no_address(self):
        rel_id = self.harness.add_relation(RELATION, "provider")
        self.harness.add_relation_unit(rel_id, "provider/0")
        self.harness.update_relation_data(rel_id, "provider/0", {"port": "9090"})
        assert list(self.harness.charm.provider.endpoints) == []

    def test_no_port(self):
        rel_id = self.harness.add_relation(RELATION, "provider")
        self.harness.add_relation_unit(rel_id, "provider/0")
        self.harness.update_relation_data(rel_id, "provider/0", {"ingress-address": "1.1.1.1"})
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
        self.harness.charm.on[PROVIDER_RELATION].relation_created.emit(
            self.harness.charm.model.get_relation(PROVIDER_RELATION, rel_id)
        )
        assert self.harness.get_relation_data(rel_id, "port") == "9090"
