# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

import unittest
from unittest.mock import patch

from helpers import (
    k8s_resource_multipatch,
    patch_network_get,
    prom_multipatch,
)
from ops.testing import Harness

from charm import Prometheus, PrometheusCharm


@prom_multipatch
class TestTls(unittest.TestCase):
    @prom_multipatch
    def setUp(self, *unused):
        self.harness = Harness(PrometheusCharm)
        self.harness.set_model_info("lma", "12de4fae-06cc-4ceb-9089-567be09fec78")
        self.harness.handle_exec("prometheus", ["update-ca-certificates", "--fresh"], result=0)
        self.addCleanup(self.harness.cleanup)

        patcher = patch.object(PrometheusCharm, "_get_pvc_capacity")
        self.mock_capacity = patcher.start()
        self.mock_capacity.return_value = "1Gi"
        self.addCleanup(patcher.stop)

    @k8s_resource_multipatch
    @patch("lightkube.core.client.GenericSyncClient")
    @patch.object(Prometheus, "reload_configuration", new=lambda _: True)
    @patch("socket.getfqdn", new=lambda *args: "fqdn")
    @patch_network_get()
    def test_tls_relation_without_certs(self, *unused):
        self.harness.begin_with_initial_hooks()

        # WHEN a certificates relation is added
        rel_id = self.harness.add_relation("certificates", "ca")
        self.harness.add_relation_unit(rel_id, "ca/0")

        # AND no certs are provided over relation data
        # THEN the scheme of the internal URL is http
        self.assertTrue(self.harness.charm.internal_url.startswith("http://"))

    @k8s_resource_multipatch
    @patch("lightkube.core.client.GenericSyncClient")
    @patch.object(Prometheus, "reload_configuration", new=lambda _: True)
    @patch("socket.getfqdn", new=lambda *args: "fqdn")
    @patch_network_get()
    @patch.multiple(
        "charm.PrometheusCharm",
        _is_tls_ready=lambda *_: True,
        _is_cert_available=lambda *_: True,
        _update_cert=lambda *_: None,
    )
    def test_tls_relation_with_tls_ready(self, *unused):
        self.harness.begin_with_initial_hooks()

        # WHEN a certificates relation is added
        rel_id = self.harness.add_relation("certificates", "ca")
        self.harness.add_relation_unit(rel_id, "ca/0")

        # AND certs become available (see decorators)
        # THEN the scheme of the internal URL is https
        self.assertTrue(self.harness.charm.internal_url.startswith("https://"))
