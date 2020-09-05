# Copyright 2020 Balbir Thomas
# See LICENSE file for licensing details.

import unittest
from unittest.mock import Mock

from ops.testing import Harness
from charm import PrometheusCharm


class TestCharm(unittest.TestCase):
    def test_config_changed(self):
        harness = Harness(PrometheusCharm)
        # from 0.8 you should also do:
        # self.addCleanup(harness.cleanup)
        harness.begin()
        self.assertEqual(list(harness.charm._stored.things), [])
        harness.update_config({"thing": "foo"})
        self.assertEqual(list(harness.charm._stored.things), ["foo"])

    def test_action(self):
        harness = Harness(PrometheusCharm)
        harness.begin()
        # the harness doesn't (yet!) help much with actions themselves
        action_event = Mock(params={"fail": ""})
        harness.charm._on_fortune_action(action_event)

        self.assertTrue(action_event.set_results.called)

    def test_action_fail(self):
        harness = Harness(PrometheusCharm)
        harness.begin()
        action_event = Mock(params={"fail": "fail this"})
        harness.charm._on_fortune_action(action_event)

        self.assertEqual(action_event.fail.call_args, [("fail this",)])
