# Copyright 2020 Canonical Ltd.
# See LICENSE file for licensing details.

import json
import unittest

from unittest.mock import patch

from prometheus_server import Prometheus


class TestServer(unittest.TestCase):
    def setUp(self):
        self.prometheus = Prometheus("localhost", "9090")

    @patch('urllib3.PoolManager.request')
    def test_prometheus_server_returns_valid_data(self, request):
        version = "1.0.0"
        request.return_value.data = bytes(
            json.dumps({
                "status": "success",
                "data": {
                    "version": version
                }
            }),
            encoding="utf-8")
        build_info = self.prometheus.build_info()
        got_version = build_info.get("version", None)
        self.assertIsNotNone(got_version)
        self.assertEqual(got_version, version)
