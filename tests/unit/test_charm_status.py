#!/usr/bin/env python3
# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
import unittest
from unittest.mock import Mock, patch

import hypothesis.strategies as st
from helpers import patch_network_get
from hypothesis import assume, given
from ops.model import ActiveStatus, BlockedStatus
from ops.pebble import ChangeError
from ops.testing import Harness

from charm import PrometheusCharm

logger = logging.getLogger(__name__)


class TestActiveStatus(unittest.TestCase):
    """Feature: Charm's status should reflect the correctness of the config / relations.

    Background: When launched on its own, the charm should always end up with active status.
    In some cases (e.g. Ingress conflicts) the charm should go into blocked state.
    """

    def setUp(self) -> None:
        self.app_name = "prometheus-k8s"

    @patch_network_get(private_address="1.1.1.1")
    @patch("charm.KubernetesServicePatch", lambda x, y: None)
    @given(st.booleans(), st.integers(1, 5))
    def test_unit_is_active_if_deployed_without_relations_or_config(self, is_leader, num_units):
        """Scenario: Unit is deployed without any user-provided config or regular relations."""
        # without the try-finally, if any assertion fails, then hypothesis would reenter without
        # the cleanup, carrying forward the units that were previously added
        self.harness = Harness(PrometheusCharm)
        self.peer_rel_id = self.harness.add_relation("prometheus-peers", self.app_name)

        try:
            self.assertEqual(self.harness.model.app.planned_units(), 1)

            # GIVEN any number of units present
            for i in range(1, num_units):
                self.harness.add_relation_unit(self.peer_rel_id, f"{self.app_name}/{i}")

            # AND the current unit could be either a leader or not
            self.harness.set_leader(is_leader)

            # AND reload configuration succeeds
            with patch("prometheus_server.Prometheus.reload_configuration", lambda *a, **kw: True):
                self.harness.begin_with_initial_hooks()

                # WHEN no config is provided or relations created

                # THEN the unit goes into active state
                self.assertIsInstance(self.harness.charm.unit.status, ActiveStatus)

                # AND pebble plan is not empty
                plan = self.harness.get_container_pebble_plan(self.harness.charm._name)
                self.assertGreater(plan.to_dict().items(), {}.items())

        finally:
            # cleanup to prep for reentry by hypothesis' strategy
            self.harness.cleanup()

    @patch_network_get(private_address="1.1.1.1")
    @patch("charm.KubernetesServicePatch", lambda x, y: None)
    @given(st.booleans(), st.integers(1, 5))
    def test_unit_is_blocked_if_reload_configuration_fails(self, is_leader, num_units):
        """Scenario: Unit is deployed but reload configuration fails."""
        assume(is_leader or num_units > 1)

        # without the try-finally, if any assertion fails, then hypothesis would reenter without
        # the cleanup, carrying forward the units that were previously added
        self.harness = Harness(PrometheusCharm)
        self.peer_rel_id = self.harness.add_relation("prometheus-peers", self.app_name)

        try:
            self.assertEqual(self.harness.model.app.planned_units(), 1)

            # GIVEN any number of units present
            for i in range(1, num_units):
                self.harness.add_relation_unit(self.peer_rel_id, f"{self.app_name}/{i}")

            # AND the current unit could be either a leader or not
            self.harness.set_leader(is_leader)

            # AND reload configuration fails

            with patch("ops.model.Container.replan", Mock(side_effect=ChangeError)), patch(
                "prometheus_server.Prometheus.reload_configuration", lambda *a, **kw: False
            ):
                self.harness.begin_with_initial_hooks()

                # WHEN no config is provided or relations created

                # THEN the unit goes into blocked state
                self.assertIsInstance(self.harness.charm.unit.status, BlockedStatus)

                # AND pebble plan is not empty
                plan = self.harness.get_container_pebble_plan(self.harness.charm._name)
                self.assertGreater(plan.to_dict().items(), {}.items())

        finally:
            # cleanup to prep for reentry by hypothesis' strategy
            self.harness.cleanup()
