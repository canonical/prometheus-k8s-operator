# Copyright 2020 Canonical Ltd.
# See LICENSE file for licensing details.

import unittest

import responses
from prometheus_client import Prometheus


class TestServerPrefix(unittest.TestCase):
    def test_address_glueing(self):
        # WHEN no args are provided THEN use localhost:9090
        p = Prometheus()
        self.assertEqual(p.base_url, "http://localhost:9090")

        # WHEN path is provided THEN it is appended to localhost:9090
        for path in ["foo", "foo/"]:
            with self.subTest(path=path):
                p = Prometheus(f"http://localhost:9090/{path}")
                self.assertEqual(p.base_url, "http://localhost:9090/foo")

    @responses.activate
    def test_prometheus_client_without_route_prefix_returns_valid_data(self):
        self.prometheus = Prometheus("http://localhost:9090")

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
    def test_prometheus_client_without_route_prefix_reload_configuration_success(self):
        self.prometheus = Prometheus("http://localhost:9090")

        responses.add(
            responses.POST,
            "http://localhost:9090/-/reload",
            status=200,
        )

        self.assertTrue(self.prometheus.reload_configuration())

    @responses.activate
    def test_prometheus_client_without_route_prefix_reload_configuration_failure(self):
        self.prometheus = Prometheus("http://localhost:9090")

        responses.add(
            responses.POST,
            "http://localhost:9090/-/reload",
            status=500,
        )

        self.assertFalse(self.prometheus.reload_configuration())

    @responses.activate
    def test_prometheus_client_with_route_prefix_returns_valid_data(self):
        self.prometheus = Prometheus("http://localhost:9090/foobar")

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
    def test_prometheus_client_with_route_prefix_reload_configuration_success(self):
        self.prometheus = Prometheus("http://localhost:9090/foobar")

        responses.add(
            responses.POST,
            "http://localhost:9090/foobar/-/reload",
            status=200,
        )

        self.assertTrue(self.prometheus.reload_configuration())

    @responses.activate
    def test_prometheus_client_with_route_prefix_reload_configuration_failure(self):
        self.prometheus = Prometheus("http://localhost:9090/foobar")

        responses.add(
            responses.POST,
            "http://localhost:9090/foobar/-/reload",
            status=500,
        )

        self.assertFalse(self.prometheus.reload_configuration())
