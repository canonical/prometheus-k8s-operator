# Copyright 2020 Canonical Ltd.
# See LICENSE file for licensing details.

import json
import unittest
from unittest.mock import patch

from charms.observability_libs.v0.kubernetes_service_patch import KubernetesServicePatch
from charms.prometheus_k8s.v0.prometheus_remote_write import (
    DEFAULT_RELATION_NAME as RELATION_NAME,
)
from charms.prometheus_k8s.v0.prometheus_remote_write import (
    RELATION_INTERFACE_NAME as RELATION_INTERFACE,
)
from charms.prometheus_k8s.v0.prometheus_remote_write import (
    PrometheusRemoteWriteConsumer,
)
from helpers import patch_network_get
from ops import framework
from ops.charm import CharmBase
from ops.model import ActiveStatus
from ops.testing import Harness

from charm import Prometheus, PrometheusCharm

METADATA = f"""
name: consumer-tester
requires:
  {RELATION_NAME}:
    interface: {RELATION_INTERFACE}
requires:
    ingress-unit:
        interface: ingress-unit
        limit: 1
    receive-remote-write:
        interface: prometheus_remote_write
"""


ALERT_RULES = {
    "groups": [
        {
            "name": "None_f2c1b2a6-e006-11eb-ba80-0242ac130004_consumer-tester_alerts",
            "rules": [
                {
                    "alert": "CPUOverUse",
                    "expr": 'process_cpu_seconds_total{juju_application="consumer-tester",'
                    'juju_model="None",'
                    'juju_model_uuid="f2c1b2a6-e006-11eb-ba80-0242ac130004"} > 0.12',
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
                    "expr": 'up{juju_application="consumer-tester",juju_model="None",'
                    'juju_model_uuid="f2c1b2a6-e006-11eb-ba80-0242ac130004"} == 0',
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


class RemoteWriteConsumerCharm(CharmBase):
    def __init__(self, *args, **kwargs):
        super().__init__(*args)
        self.remote_write_consumer = PrometheusRemoteWriteConsumer(
            self,
            RELATION_NAME,
            alert_rules_path="./tests/unit/prometheus_alert_rules",
        )
        self.framework.observe(
            self.remote_write_consumer.on.endpoints_changed,
            self._handle_endpoints_changed,
        )

    def _handle_endpoints_changed(self, _):
        pass


@patch("charms.observability_libs.v0.juju_topology.JujuTopology.is_valid_uuid", lambda *args: True)
class TestRemoteWriteConsumer(unittest.TestCase):
    @patch(
        "charms.observability_libs.v0.juju_topology.JujuTopology.is_valid_uuid", lambda *args: True
    )
    def setUp(self):
        self.harness = Harness(RemoteWriteConsumerCharm, meta=METADATA)
        self.addCleanup(self.harness.cleanup)
        self.harness.set_leader(True)

        patcher = patch.object(PrometheusCharm, "_get_pvc_capacity")
        self.mock_capacity = patcher.start()
        self.addCleanup(patcher.stop)

        self.mock_capacity.return_value = "1Gi"
        self.harness.set_model_name("test")
        self.harness.begin_with_initial_hooks()

    def test_address_is_set(self):
        rel_id = self.harness.add_relation(RELATION_NAME, "provider")
        self.harness.add_relation_unit(rel_id, "provider/0")
        self.harness.update_relation_data(
            rel_id,
            "provider/0",
            {"remote_write": json.dumps({"url": "http://1.1.1.1:9090/api/v1/write"})},
        )
        assert list(self.harness.charm.remote_write_consumer.endpoints) == [
            {"url": "http://1.1.1.1:9090/api/v1/write"}
        ]

    @patch.object(RemoteWriteConsumerCharm, "_handle_endpoints_changed")
    def test_config_is_set(self, mock_handle_endpoints_changed):
        rel_id = self.harness.add_relation(RELATION_NAME, "provider")

        self.harness.add_relation_unit(rel_id, "provider/0")
        self.harness.update_relation_data(
            rel_id,
            "provider/0",
            {"remote_write": json.dumps({"url": "http://1.1.1.1:9090/api/v1/write"})},
        )

        mock_handle_endpoints_changed.assert_called()
        event = mock_handle_endpoints_changed.call_args.args[0]
        self.assertEqual(rel_id, event.relation_id)

        assert list(self.harness.charm.remote_write_consumer.endpoints) == [
            {"url": "http://1.1.1.1:9090/api/v1/write"}
        ]

    def test_no_remote_write_endpoint_provided(self):
        rel_id = self.harness.add_relation(RELATION_NAME, "provider")
        self.harness.add_relation_unit(rel_id, "provider/0")
        self.harness.update_relation_data(rel_id, "provider/0", {})
        assert list(self.harness.charm.remote_write_consumer.endpoints) == []

    def test_alert_rule_has_correct_labels(self):
        rel_id = self.harness.add_relation(RELATION_NAME, "provider")
        self.harness.add_relation_unit(rel_id, "provider/0")
        rules = json.loads(
            self.harness.get_relation_data(rel_id, self.harness.charm.app)["alert_rules"]
        )
        for group in rules["groups"]:
            if group["name"].endswith("with_template_string_alerts"):
                expr = group["rules"][0]["expr"]
                self.assertIn("juju_model", expr)
                self.assertIn("juju_model_uuid", expr)
                self.assertIn("juju_application", expr)
                self.assertIn("juju_charm", expr)
                self.assertNotIn("juju_unit", expr)
                self.assertEqual(
                    set(group["rules"][0]["labels"]),
                    {
                        "juju_application",
                        "juju_charm",
                        "juju_model",
                        "juju_model_uuid",
                        "severity",
                    },
                )
                break
        else:
            assert False  # Could not find the correct alert rule to check

    def test_alert_rule_has_correct_labels_with_unit(self):
        rel_id = self.harness.add_relation(RELATION_NAME, "provider")
        self.harness.add_relation_unit(rel_id, "provider/0")
        rules = json.loads(
            self.harness.get_relation_data(rel_id, self.harness.charm.app)["alert_rules"]
        )
        for group in rules["groups"]:
            if group["name"].endswith("with_template_string_and_unit_alerts"):
                expr = group["rules"][0]["expr"]
                self.assertIn("juju_model", expr)
                self.assertIn("juju_model_uuid", expr)
                self.assertIn("juju_application", expr)
                self.assertIn("juju_charm", expr)
                self.assertIn("juju_unit", expr)
                self.assertEqual(
                    set(group["rules"][0]["labels"]),
                    {
                        "juju_application",
                        "juju_charm",
                        "juju_model",
                        "juju_model_uuid",
                        "severity",
                        "juju_unit",
                    },
                )
                break
        else:
            assert False  # Could not find the correct alert rule to check


@patch("charms.observability_libs.v0.juju_topology.JujuTopology.is_valid_uuid", lambda *args: True)
class TestRemoteWriteProvider(unittest.TestCase):
    @patch(
        "charms.observability_libs.v0.juju_topology.JujuTopology.is_valid_uuid", lambda *args: True
    )
    def setUp(self, *unused):
        self.harness = Harness(PrometheusCharm)
        self.harness.set_model_info("lma", "123456")
        self.addCleanup(self.harness.cleanup)

        patcher = patch.object(PrometheusCharm, "_get_pvc_capacity")
        self.mock_capacity = patcher.start()
        self.mock_capacity.return_value = "1Gi"
        self.addCleanup(patcher.stop)

    @patch.object(KubernetesServicePatch, "_service_object", new=lambda *args: None)
    @patch("charm.KubernetesComputeResourcesPatch")
    @patch.object(Prometheus, "reload_configuration", new=lambda _: True)
    @patch("socket.getfqdn", new=lambda *args: "fqdn")
    @patch_network_get()
    def test_port_is_set(self, *unused):
        self.harness.begin_with_initial_hooks()

        rel_id = self.harness.add_relation(RELATION_NAME, "consumer")
        self.harness.add_relation_unit(rel_id, "consumer/0")
        self.assertEqual(
            self.harness.get_relation_data(rel_id, self.harness.charm.unit.name),
            {"remote_write": json.dumps({"url": "http://fqdn:9090/api/v1/write"})},
        )
        self.assertIsInstance(self.harness.charm.unit.status, ActiveStatus)

    @patch.object(KubernetesServicePatch, "_service_object", new=lambda *args: None)
    @patch("charm.KubernetesComputeResourcesPatch")
    @patch.object(Prometheus, "reload_configuration", new=lambda _: True)
    @patch_network_get()
    def test_alert_rules(self, *unused):
        self.harness.begin_with_initial_hooks()

        rel_id = self.harness.add_relation(RELATION_NAME, "consumer")
        self.harness.update_relation_data(
            rel_id,
            "consumer",
            {"alert_rules": json.dumps(ALERT_RULES)},
        )

        self.harness.add_relation_unit(rel_id, "consumer/0")

        alerts = self.harness.charm.remote_write_provider.alerts()
        alerts = list(alerts.values())[0]  # drop the topology identifier
        self.assertEqual(len(alerts), 1)
        self.assertDictEqual(alerts, ALERT_RULES)

    @patch.object(KubernetesServicePatch, "_service_object", new=lambda *args: None)
    @patch("charm.KubernetesComputeResourcesPatch")
    @patch.object(Prometheus, "reload_configuration", new=lambda _: True)
    @patch_network_get()
    def test_address_is_updated_on_upgrade(self, *unused):
        rel_id = self.harness.add_relation(RELATION_NAME, "consumer")
        self.harness.add_relation_unit(rel_id, "consumer/0")

        with patch("socket.getfqdn", new=lambda *args: "fqdn.before"):
            self.harness.begin_with_initial_hooks()
            self.harness.container_pebble_ready("prometheus")

        self.assertEqual(
            self.harness.get_relation_data(rel_id, self.harness.charm.unit.name),
            {"remote_write": json.dumps({"url": "http://fqdn.before:9090/api/v1/write"})},
        )

        with patch("socket.getfqdn", new=lambda *args: "fqdn.after"):
            # An "upgrade" helper is controversial, so rolling my own
            # https://github.com/canonical/operator/pull/758
            # self.harness.upgrade()

            # Re-initialize charm
            self.harness._framework = framework.Framework(
                self.harness._storage,
                self.harness._charm_dir,
                self.harness._meta,
                self.harness._model,
            )
            self.harness._charm = None
            self.harness.begin()

            # Emit upgrade events
            self.harness.charm.on.upgrade_charm.emit()
            self.harness.charm.on.config_changed.emit()
            self.harness.charm.on.start.emit()

        self.assertEqual(
            self.harness.get_relation_data(rel_id, self.harness.charm.unit.name),
            {"remote_write": json.dumps({"url": "http://fqdn.after:9090/api/v1/write"})},
        )
