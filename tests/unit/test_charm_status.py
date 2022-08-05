#!/usr/bin/env python3
# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

import datetime
import logging
import unittest
from unittest.mock import Mock, patch

import ops
from helpers import k8s_resource_multipatch, patch_network_get
from ops.model import ActiveStatus, BlockedStatus
from ops.pebble import Change, ChangeError, ChangeID
from ops.testing import Harness

from charm import PrometheusCharm

ops.testing.SIMULATE_CAN_CONNECT = True
logger = logging.getLogger(__name__)


@patch("charm.KubernetesServicePatch", lambda x, y: None)
class TestActiveStatus(unittest.TestCase):
    """Feature: Charm's status should reflect the correctness of the config / relations.

    Background: When launched on its own, the charm should always end up with active status.
    In some cases (e.g. Ingress conflicts) the charm should go into blocked state.
    """

    def setUp(self) -> None:
        self.app_name = "prometheus-k8s"
        self.harness = Harness(PrometheusCharm)
        self.addCleanup(self.harness.cleanup)
        self.peer_rel_id = self.harness.add_relation("prometheus-peers", self.app_name)

        # GIVEN a total of three units present
        for i in range(1, 3):
            self.harness.add_relation_unit(self.peer_rel_id, f"{self.app_name}/{i}")

        # AND the current unit is a leader
        self.harness.set_leader(True)

        patcher = patch.object(PrometheusCharm, "_get_pvc_capacity")
        self.mock_capacity = patcher.start()
        self.mock_capacity.return_value = "1Gi"
        self.addCleanup(patcher.stop)

    @patch_network_get()
    @patch("charm.Prometheus.version", lambda x: "1.0.0")
    @k8s_resource_multipatch
    @patch("lightkube.core.client.GenericSyncClient")
    def test_unit_is_active_if_deployed_without_relations_or_config(self, *unused):
        """Scenario: Unit is deployed without any user-provided config or regular relations."""
        # GIVEN reload configuration succeeds
        with patch("prometheus_server.Prometheus.reload_configuration", lambda *a, **kw: True):
            self.harness.begin_with_initial_hooks()
            self.harness.container_pebble_ready("prometheus")

            # WHEN no config is provided or relations created

            # THEN the unit goes into active state
            self.assertIsInstance(self.harness.charm.unit.status, ActiveStatus)

            # AND pebble plan is not empty
            plan = self.harness.get_container_pebble_plan(self.harness.charm._name)
            self.assertTrue(plan.to_dict())
            # Ensure the workload version is set accordingly
            self.assertEqual(self.harness.get_workload_version(), "1.0.0")

    @patch("charm.Prometheus.version", lambda x: "1.0.0")
    @k8s_resource_multipatch
    @patch("lightkube.core.client.GenericSyncClient")
    def test_unit_update_status_updates_version(self, *_):
        self.harness.begin()
        # Force set a workload version before triggering the event
        self.harness.charm.unit.set_workload_version("0.1.0")
        self.assertEqual(self.harness.get_workload_version(), "0.1.0")
        # Trigger the update status event
        self.harness.charm.on.update_status.emit()
        # Ensure the workload version is updated accordingly
        self.assertEqual(self.harness.get_workload_version(), "1.0.0")

    @patch_network_get()
    @k8s_resource_multipatch
    @patch("lightkube.core.client.GenericSyncClient")
    def test_unit_is_blocked_if_reload_configuration_fails(self, *unused):
        """Scenario: Unit is deployed but reload configuration fails."""
        # GIVEN reload configuration fails
        # Construct mock objects
        cid = ChangeID("0")
        spawn_time = datetime.datetime.now()
        change = Change(cid, "kind", "summary", "status", [], False, None, spawn_time, None)
        replan_patch = patch(
            "ops.model.Container.replan", Mock(side_effect=ChangeError("err", change))
        )
        reload_patch = patch(
            "prometheus_server.Prometheus.reload_configuration", lambda *a, **kw: False
        )
        with replan_patch, reload_patch:
            self.harness.begin_with_initial_hooks()
            self.harness.container_pebble_ready("prometheus")

            # WHEN no config is provided or relations created

            # THEN the unit goes into blocked state
            self.assertIsInstance(self.harness.charm.unit.status, BlockedStatus)

            # AND pebble plan is not empty
            plan = self.harness.get_container_pebble_plan(self.harness.charm._name)
            self.assertTrue(plan.to_dict())
