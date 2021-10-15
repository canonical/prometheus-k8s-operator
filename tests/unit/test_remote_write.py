# Copyright 2020 Canonical Ltd.
# See LICENSE file for licensing details.

import unittest
from unittest.mock import patch

from charms.observability_libs.v0.kubernetes_service_patch import KubernetesServicePatch
from charms.prometheus_k8s.v0.prometheus_remote_write import (
    PrometheusRemoteWriteConsumer,
)
from ops.charm import CharmBase
from ops.model import ActiveStatus, BlockedStatus
from ops.testing import Harness

from charm import Prometheus, PrometheusCharm

RELATION_NAME = "receive-remote-write"
RELATION_INTERFACE = "prometheus_remote_write"
METADATA = f"""
name: consumer-tester
requires:
  {RELATION_NAME}:
    interface: {RELATION_INTERFACE}
"""

FILES = {}


def fake_push(self, path, content, **kwargs):
    global FILES
    FILES[path] = content


class RemoteWriteConsumerCharm(CharmBase):
    def __init__(self, *args, **kwargs):
        super().__init__(*args)
        self.remote_write_consumer = PrometheusRemoteWriteConsumer(self, RELATION_NAME)
        self.framework.observe(
            self.remote_write_consumer.on.endpoints_changed,
            self._handle_endpoints_changed,
        )

    def _handle_endpoints_changed(self, _):
        pass


class TestRemoteWriteConsumer(unittest.TestCase):
    def setUp(self):
        self.harness = Harness(RemoteWriteConsumerCharm, meta=METADATA)
        self.addCleanup(self.harness.cleanup)
        self.harness.begin()

    def test_address_is_set(self):
        rel_id = self.harness.add_relation(RELATION_NAME, "provider")
        self.harness.add_relation_unit(rel_id, "provider/0")
        self.harness.update_relation_data(
            rel_id,
            "provider/0",
            {"remote_write_endpoint": "http://1.1.1.1:9090/api/v1/write"},
        )
        assert list(self.harness.charm.remote_write_consumer.endpoints) == [
            "http://1.1.1.1:9090/api/v1/write"
        ]

    @patch.object(RemoteWriteConsumerCharm, "_handle_endpoints_changed")
    def test_config_is_set(self, mock_handle_endpoints_changed):
        rel_id = self.harness.add_relation(RELATION_NAME, "provider")
        self.harness.add_relation_unit(rel_id, "provider/0")
        self.harness.update_relation_data(
            rel_id,
            "provider/0",
            {"remote_write_endpoint": "http://1.1.1.1:9090/api/v1/write"},
        )

        mock_handle_endpoints_changed.assert_called()
        event = mock_handle_endpoints_changed.call_args.args[0]
        self.assertEqual(rel_id, event.relation_id)

        assert list(self.harness.charm.remote_write_consumer.configs) == [
            {"url": "http://1.1.1.1:9090/api/v1/write"}
        ]

    def test_no_remote_write_endpoint_provided(self):
        rel_id = self.harness.add_relation(RELATION_NAME, "provider")
        self.harness.add_relation_unit(rel_id, "provider/0")
        self.harness.update_relation_data(rel_id, "provider/0", {})
        assert list(self.harness.charm.remote_write_consumer.endpoints) == []


class TestRemoteWriteProvider(unittest.TestCase):
    @patch("ops.testing._TestingPebbleClient.remove_path")
    @patch("ops.testing._TestingPebbleClient.push", new=fake_push)
    @patch("ops.testing._TestingModelBackend.network_get")
    def setUp(self, mock_net_get, *_):
        ip = "1.1.1.1"
        net_info = {"bind-addresses": [{"interface-name": "ens1", "addresses": [{"value": ip}]}]}
        mock_net_get.return_value = net_info

        self.harness = Harness(PrometheusCharm)
        self.harness.set_model_info("lma", "123456")
        self.addCleanup(self.harness.cleanup)

    @patch.object(KubernetesServicePatch, "_service_object", new=lambda *args: None)
    @patch("ops.testing._TestingPebbleClient.remove_path")
    @patch("ops.testing._TestingPebbleClient.push", new=fake_push)
    @patch("ops.testing._TestingModelBackend.network_get")
    def test_port_is_set(self, mock_net_get, *_):
        ip = "1.1.1.1"
        net_info = {"bind-addresses": [{"interface-name": "ens1", "addresses": [{"value": ip}]}]}
        mock_net_get.return_value = net_info

        self.harness.begin_with_initial_hooks()

        rel_id = self.harness.add_relation(RELATION_NAME, "consumer")
        self.harness.add_relation_unit(rel_id, "consumer/0")
        self.assertEqual(
            self.harness.get_relation_data(rel_id, self.harness.charm.unit.name),
            {"remote_write_endpoint": "http://1.1.1.1:9090/api/v1/write"},
        )

        self.assertEqual(self.harness.charm.unit.status, ActiveStatus())

    @patch.object(KubernetesServicePatch, "_service_object", new=lambda *args: None)
    @patch.object(Prometheus, "reload_configuration", new=lambda _: True)
    @patch("ops.testing._TestingPebbleClient.remove_path")
    @patch("ops.testing._TestingPebbleClient.push", new=fake_push)
    @patch("ops.testing._TestingModelBackend.network_get")
    def test_multiple_units_with_ingress(self, mock_net_get, *_):
        ip = "1.1.1.1"
        net_info = {"bind-addresses": [{"interface-name": "ens1", "addresses": [{"value": ip}]}]}
        mock_net_get.return_value = net_info

        ingress_rel_id = self.harness.add_relation("ingress", "nginx-ingress")
        self.harness.add_relation_unit(ingress_rel_id, "ingress/0")

        self.harness.begin_with_initial_hooks()

        peers_rel_id = self.harness.charm.model.get_relation("prometheus-peers").id
        self.harness.add_relation_unit(peers_rel_id, "prometheus/1")

        cons_rel_id = self.harness.add_relation(RELATION_NAME, "consumer")
        self.harness.add_relation_unit(cons_rel_id, "consumer/0")
        self.assertEqual(
            self.harness.get_relation_data(cons_rel_id, self.harness.charm.unit.name),
            {
                "remote_write_endpoint": "http://prometheus-k8s-0.prometheus-k8s-endpoints.lma.svc.cluster.local:9090/api/v1/write"
            },
        )

        self.assertEqual(
            self.harness.charm.unit.status,
            BlockedStatus(
                "invalid combination of 'ingress', 'receive-remote-write' relations and multiple units"
            ),
        )

        self.harness.remove_relation_unit(peers_rel_id, "prometheus/1")

        # TODO Uncomment when https://github.com/canonical/operator/issues/638 is fixed
        # self.assertEqual(self.harness.charm.unit.status, ActiveStatus())
