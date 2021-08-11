# Copyright 2020 Canonical Ltd.
# See LICENSE file for licensing details.

import responses
import unittest

from prometheus_server import Prometheus


class TestServer(unittest.TestCase):
    def setUp(self):
        self.prometheus = Prometheus("localhost", "9090")

    @responses.activate
    def test_prometheus_server_returns_valid_data(self):
        version = "1.0.0"

        responses.add(
            responses.GET,
            "http://localhost:9090/api/v1/status/buildinfo",
            json={
                "status": "success",
                "data": {"version": version},
            },
            status=200,
        )

        build_info = self.prometheus.build_info()
        got_version = build_info.get("version", None)
        self.assertEqual(got_version, version)

    @responses.activate
    def test_prometheus_server_reload_configuration_success(self):
        responses.add(
            responses.POST,
            "http://localhost:9090/-/reload",
            status=200,
        )

        self.assertTrue(self.prometheus.trigger_configuration_reload())

    @responses.activate
    def test_prometheus_server_reload_configuration_failure(self):
        responses.add(
            responses.POST,
            "http://localhost:9090/-/reload",
            status=500,
        )

        self.assertFalse(self.prometheus.trigger_configuration_reload())
