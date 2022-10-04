# Copyright 2020 Canonical Ltd.
# See LICENSE file for licensing details.

import json
import logging
import unittest
from unittest.mock import patch

import ops
import yaml
from helpers import cli_arg, k8s_resource_multipatch, patch_network_get, prom_multipatch
from ops.testing import Harness

from charm import PROMETHEUS_CONFIG, PrometheusCharm

ops.testing.SIMULATE_CAN_CONNECT = True
logger = logging.getLogger(__name__)


class TestWebExternalUrlForCharm(unittest.TestCase):
    """Test that the web_external_url config option is rendered correctly for the charm.

    This entails:
    - default job config (the same prom scraping itself via localhost:9090)
    - self-scrape job (the requirer side of the prometheus_scrape relation data)
    - remote-write url (relation data for the provider side, i.e. receive-remote-write)
    """

    def setUp(self, *unused):
        self.harness = Harness(PrometheusCharm)
        self.addCleanup(self.harness.cleanup)

        pvc_patcher = patch.object(PrometheusCharm, "_get_pvc_capacity")
        self.pvc_mock = pvc_patcher.start()
        self.addCleanup(pvc_patcher.stop)
        self.harness.set_model_name("prometheus_model")
        self.pvc_mock.return_value = "1Gi"

        for p in [
            k8s_resource_multipatch,
            patch_network_get(),
            patch("socket.getfqdn", new=lambda *args: "fqdn"),
            patch("charm.KubernetesServicePatch", lambda x, y: None),
            patch("lightkube.core.client.GenericSyncClient"),
            prom_multipatch,
        ]:
            p.start()
            self.addCleanup(p.stop)

        self.harness.set_leader(True)

        self.rel_id_self_metrics = self.harness.add_relation(
            "self-metrics-endpoint", "remote-scraper-app"
        )
        self.harness.add_relation_unit(self.rel_id_self_metrics, "remote-scraper-app/0")

        self.rel_id_remote_write = self.harness.add_relation(
            "receive-remote-write", "remote-write-app"
        )
        self.harness.add_relation_unit(self.rel_id_remote_write, "remote-write-app/0")

    def app_data(self, rel_name: str):
        relation = self.harness.charm.model.get_relation(rel_name)
        return relation.data[self.harness.charm.app]

    def unit_data(self, rel_name: str):
        relation = self.harness.charm.model.get_relation(rel_name)
        return relation.data[self.harness.charm.unit]

    @property
    def container_name(self):
        return self.harness.charm._name

    @property
    def plan(self):
        return self.harness.get_container_pebble_plan(self.container_name)

    @property
    def config_file(self) -> dict:
        return yaml.safe_load(self.container.pull(PROMETHEUS_CONFIG).read())

    def test_web_external_url_not_set(self, *unused):
        # GIVEN an initialized charm
        # Note: harness does not re-init the charm on core events such as config-changed.
        # https://github.com/canonical/operator/issues/736
        # For this reason, repeating the begin_with_initial_hooks() in every test method.
        # When operator/736 is implemented, these lines can be moved to setUp().
        self.harness.update_config(unset=["web_external_url"])
        self.harness.begin_with_initial_hooks()
        self.harness.container_pebble_ready("prometheus")
        self.container = self.harness.charm.unit.get_container(self.container_name)

        # WHEN web_external_url is not set
        # (This had to be done above, before `begin`, due to operator/736)

        # THEN pebble plan does NOT have the --web.external_url arg set
        self.assertEqual(cli_arg(self.plan, "--web.external_url"), None)

        # AND default job is the default localhost:9090/metrics
        scrape_config = self.config_file["scrape_configs"][0]
        self.assertEqual(scrape_config["static_configs"][0]["targets"], ["localhost:9090"])
        self.assertEqual(scrape_config["metrics_path"], "/metrics")

        # AND the self-scrape job points to prom's fqdn
        self.assertEqual(
            self.app_data("self-metrics-endpoint").get("scrape_jobs"),
            json.dumps(
                [{"metrics_path": "/metrics", "static_configs": [{"targets": ["*:9090"]}]}]
            ),
        )
        self.assertEqual(
            self.unit_data("self-metrics-endpoint").get("prometheus_scrape_unit_address"),
            "fqdn",
        )

        # AND the remote-write provider points to prom's fqdn
        self.assertEqual(
            self.unit_data("receive-remote-write").get("remote_write"),
            '{"url": "http://fqdn:9090/api/v1/write"}',
        )

    def test_web_external_has_hostname_only(self, *unused):
        # GIVEN an initialized charm
        self.harness.update_config({"web_external_url": "http://foo.bar"})
        self.harness.begin_with_initial_hooks()
        self.harness.container_pebble_ready("prometheus")
        self.container = self.harness.charm.unit.get_container(self.container_name)

        # WHEN web_external_url is just a hostname
        # (This had to be done above, before `begin`, due to operator/736)

        # THEN pebble plan has the --web.external_url set to http://foo.bar
        self.assertEqual(cli_arg(self.plan, "--web.external-url"), "http://foo.bar")

        # AND default job is the default localhost:9090/metrics
        scrape_config = self.config_file["scrape_configs"][0]
        self.assertEqual(scrape_config["static_configs"][0]["targets"], ["localhost:9090"])
        self.assertEqual(scrape_config["metrics_path"], "/metrics")

        # AND the self-scrape job advertises a wildcard target on port 80
        self.assertEqual(
            self.app_data("self-metrics-endpoint").get("scrape_jobs"),
            json.dumps([{"metrics_path": "/metrics", "static_configs": [{"targets": ["*:80"]}]}]),
        )
        self.assertEqual(
            self.unit_data("self-metrics-endpoint").get("prometheus_scrape_unit_address"),
            "foo.bar",
        )

        # AND the remote-write provider points to prom's fqdn
        self.assertEqual(
            self.unit_data("receive-remote-write").get("remote_write"),
            '{"url": "http://foo.bar:80/api/v1/write"}',
        )

    def test_web_external_has_hostname_and_port(self, *unused):
        # GIVEN an initialized charm
        self.harness.update_config({"web_external_url": "http://foo.bar:1234"})
        self.harness.begin_with_initial_hooks()
        self.harness.container_pebble_ready("prometheus")
        self.container = self.harness.charm.unit.get_container(self.container_name)

        # WHEN web_external_url is a hostname with a port
        # (This had to be done above, before `begin`, due to operator/736)

        # THEN pebble plan has the --web.external_url set to http://foo.bar:1234
        self.assertEqual(cli_arg(self.plan, "--web.external-url"), "http://foo.bar:1234")

        # AND default job is the default localhost:9090/metrics
        scrape_config = self.config_file["scrape_configs"][0]
        self.assertEqual(scrape_config["static_configs"][0]["targets"], ["localhost:9090"])
        self.assertEqual(scrape_config["metrics_path"], "/metrics")

        # AND the self-scrape job advertises a wildcard target on port 1234
        self.assertEqual(
            self.app_data("self-metrics-endpoint").get("scrape_jobs"),
            json.dumps(
                [{"metrics_path": "/metrics", "static_configs": [{"targets": ["*:1234"]}]}]
            ),
        )
        self.assertEqual(
            self.unit_data("self-metrics-endpoint").get("prometheus_scrape_unit_address"),
            "foo.bar",
        )

        # AND the remote-write provider points to prom's fqdn
        self.assertEqual(
            self.unit_data("receive-remote-write").get("remote_write"),
            '{"url": "http://foo.bar:1234/api/v1/write"}',
        )

    def test_web_external_has_hostname_and_path(self, *unused):
        # GIVEN an initialized charm
        self.harness.update_config({"web_external_url": "http://foo.bar/baz"})
        self.harness.begin_with_initial_hooks()
        self.harness.container_pebble_ready("prometheus")
        self.container = self.harness.charm.unit.get_container(self.container_name)

        # WHEN web_external_url includes a path
        # (This had to be done above, before `begin`, due to operator/736)

        # THEN pebble plan has the --web.external_url set to http://foo.bar/baz
        self.assertEqual(cli_arg(self.plan, "--web.external-url"), "http://foo.bar/baz")

        # AND default job is the default localhost:9090/baz/metrics
        scrape_config = self.config_file["scrape_configs"][0]
        self.assertEqual(scrape_config["static_configs"][0]["targets"], ["localhost:9090"])
        self.assertEqual(scrape_config["metrics_path"], "/baz/metrics")

        # AND the self-scrape job advertises a wildcard target on port 80
        self.assertEqual(
            self.app_data("self-metrics-endpoint").get("scrape_jobs"),
            json.dumps([{"metrics_path": "/metrics", "static_configs": [{"targets": ["*:80"]}]}]),
        )
        self.assertEqual(
            self.unit_data("self-metrics-endpoint").get("prometheus_scrape_unit_address"),
            "foo.bar",
        )

        # AND the remote-write provider points to prom's fqdn
        self.assertEqual(
            self.unit_data("receive-remote-write").get("remote_write"),
            '{"url": "http://foo.bar:80/baz/api/v1/write"}',
        )

    def test_web_external_has_hostname_port_and_path(self, *unused):
        # GIVEN an initialized charm
        self.harness.update_config({"web_external_url": "http://foo.bar:1234/baz"})
        self.harness.begin_with_initial_hooks()
        self.harness.container_pebble_ready("prometheus")
        self.container = self.harness.charm.unit.get_container(self.container_name)

        # WHEN web_external_url includes a port and a path
        # (This had to be done above, before `begin`, due to operator/736)

        # THEN pebble plan has the --web.external_url set to http://foo.bar:1234/baz
        self.assertEqual(cli_arg(self.plan, "--web.external-url"), "http://foo.bar:1234/baz")

        # AND default job is the default localhost:9090/baz/metrics
        scrape_config = self.config_file["scrape_configs"][0]
        self.assertEqual(scrape_config["static_configs"][0]["targets"], ["localhost:9090"])
        self.assertEqual(scrape_config["metrics_path"], "/baz/metrics")

        # AND the self-scrape job advertises a wildcard target on port 1234
        self.assertEqual(
            self.app_data("self-metrics-endpoint").get("scrape_jobs"),
            json.dumps(
                [
                    {
                        "metrics_path": "/metrics",
                        "static_configs": [{"targets": ["*:1234"]}],
                    }
                ]
            ),
        )
        self.assertEqual(
            self.unit_data("self-metrics-endpoint").get("prometheus_scrape_unit_address"),
            "foo.bar",
        )

        # AND the remote-write provider points to prom's fqdn
        self.assertEqual(
            self.unit_data("receive-remote-write").get("remote_write"),
            '{"url": "http://foo.bar:1234/baz/api/v1/write"}',
        )
