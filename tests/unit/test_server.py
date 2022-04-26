# Copyright 2020 Canonical Ltd.
# See LICENSE file for licensing details.

import unittest

import responses

from prometheus_server import Prometheus


class TestServerPrefix(unittest.TestCase):
    @responses.activate
    def test_prometheus_server_without_route_prefix_returns_valid_data(self):
        self.prometheus = Prometheus("localhost", 9090)

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

        got_version = self.prometheus.version()
        self.assertEqual(got_version, version)

    @responses.activate
    def test_prometheus_server_without_route_prefix_reload_configuration_success(self):
        self.prometheus = Prometheus("localhost", 9090)

        responses.add(
            responses.POST,
            "http://localhost:9090/-/reload",
            status=200,
        )

        self.assertTrue(self.prometheus.reload_configuration())

    @responses.activate
    def test_prometheus_server_without_route_prefix_reload_configuration_failure(self):
        self.prometheus = Prometheus("localhost", 9090)

        responses.add(
            responses.POST,
            "http://localhost:9090/-/reload",
            status=500,
        )

        self.assertFalse(self.prometheus.reload_configuration())

    @responses.activate
    def test_prometheus_server_with_route_prefix_returns_valid_data(self):
        self.prometheus = Prometheus("localhost", 9090, "/foobar")

        version = "1.0.0"

        responses.add(
            responses.GET,
            "http://localhost:9090/foobar/api/v1/status/buildinfo",
            json={
                "status": "success",
                "data": {"version": version},
            },
            status=200,
        )

        got_version = self.prometheus.version()
        self.assertEqual(got_version, version)

    @responses.activate
    def test_prometheus_server_with_route_prefix_reload_configuration_success(self):
        self.prometheus = Prometheus("localhost", 9090, "/foobar")

        responses.add(
            responses.POST,
            "http://localhost:9090/foobar/-/reload",
            status=200,
        )

        self.assertTrue(self.prometheus.reload_configuration())

    @responses.activate
    def test_prometheus_server_with_route_prefix_reload_configuration_failure(self):
        self.prometheus = Prometheus("localhost", 9090, "/foobar")

        responses.add(
            responses.POST,
            "http://localhost:9090/foobar/-/reload",
            status=500,
        )

        self.assertFalse(self.prometheus.reload_configuration())

    @responses.activate
    def test_healthy(self):
        self.prometheus = Prometheus("localhost", 9090)

        responses.add(
            responses.GET,
            "http://localhost:9090/-/healthy",
            status=200,
        )

        self.assertTrue(self.prometheus.is_healthy())

    @responses.activate
    def test_not_healthy(self):
        self.prometheus = Prometheus("localhost", 9090)

        responses.add(
            responses.GET,
            "http://localhost:9090/-/healthy",
            status=500,
        )

        self.assertFalse(self.prometheus.is_healthy())

    @responses.activate
    def test_ready(self):
        self.prometheus = Prometheus("localhost", 9090)

        responses.add(
            responses.GET,
            "http://localhost:9090/-/ready",
            status=200,
        )

        self.assertTrue(self.prometheus.is_ready())

    @responses.activate
    def test_not_ready(self):
        self.prometheus = Prometheus("localhost", 9090)

        responses.add(
            responses.GET,
            "http://localhost:9090/-/ready",
            status=500,
        )

        self.assertFalse(self.prometheus.is_ready())
