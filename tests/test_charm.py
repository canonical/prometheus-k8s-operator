# Copyright 2020 Balbir Thomas
# See LICENSE file for licensing details.

import unittest
# from unittest.mock import Mock

from ops.testing import Harness
from charm import PrometheusCharm


class TestCharm(unittest.TestCase):
    def setUp(self):
        self.harness = Harness(PrometheusCharm)
        self.addCleanup(self.harness.cleanup)

    def test_image_path_is_required(self):
        self.harness.begin()
        missing_image_config = {
            'prometheus-image-path': '',
            'prometheus-image-username': '',
            'prometheus-image-password': ''
        }
        self.harness.update_config(missing_image_config)

        missing = self.harness.charm._check_config()
        expected = ['prometheus-image-path']
        self.assertEqual(missing, expected)

    def test_password_is_required_when_username_is_set(self):
        self.harness.begin()
        missing_password_config = {
            'prometheus-image-path': 'prom/prometheus:latest',
            'prometheus-image-username': 'some-user',
            'prometheus-image-password': '',
        }
        self.harness.update_config(missing_password_config)

        missing = self.harness.charm._check_config()
        expected = ['prometheus-image-password']
        self.assertEqual(missing, expected)
