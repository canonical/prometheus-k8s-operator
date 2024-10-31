#!/usr/bin/env python3
# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

import logging

import pytest
from helpers import check_prometheus_is_ready, oci_image

from .juju import Juju

logger = logging.getLogger(__name__)

prometheus_app_name = "prometheus"
prometheus_resources = {"prometheus-image": oci_image("./metadata.yaml", "prometheus-image")}
scrape_tester = "tester"
bad_scrape_tester = "invalid-tester"
scrape_tester_resources = {
    "prometheus-tester-image": oci_image(
        "./tests/integration/prometheus-tester/metadata.yaml",
        "prometheus-tester-image",
    )
}
scrape_shim = "prometheus-scrape-config"


def test_setup_env():
    Juju.cli(["model-config", "logging-config=<root>=WARNING; unit=DEBUG"])


@pytest.mark.abort_on_fail
def test_good_config_validates_successfully(prometheus_charm, prometheus_tester_charm):
    """Deploy Prometheus and a single client with a good configuration."""
    Juju.deploy(
        prometheus_charm,
        alias=prometheus_app_name,
        resources=prometheus_resources,
        trust=True,
    )
    Juju.deploy(prometheus_tester_charm, resources=scrape_tester_resources, alias=scrape_tester)
    Juju.wait_for_idle([prometheus_app_name, scrape_tester])
    await check_prometheus_is_ready(prometheus_app_name, 0)

    Juju.integrate(f"{prometheus_app_name}:metrics-endpoint", f"{scrape_tester}:metrics-endpoint")

    # set some custom configs to later check they persisted across the test
    res = Juju.run(f"{prometheus_app_name}/0", "validate-configuration")

    assert res["valid"] == "True"
    assert res["error-message"] == ""
    assert "SUCCESS" in res["result"]  # NOTE: this is coming from promtool so may change


@pytest.mark.abort_on_fail
async def test_bad_config_sets_action_results(prometheus_charm, prometheus_tester_charm):
    """Deploy Prometheus and a single client with a good configuration."""
    Juju.wait_for_idle([prometheus_app_name])

    Juju.cli(
        [
            "ssh",
            "--container",
            "prometheus",
            f"{prometheus_app_name}/0",
            "echo bad-prometheus-config > /etc/prometheus/prometheus.yml",
        ]
    )

    # set some custom configs to later check they persisted across the test
    res = Juju.run(f"{prometheus_app_name}/0", "validate-configuration")

    assert res["valid"] == "False"
    assert "FAILED" in res["error-message"]  # NOTE: this is coming from promtool so may change
    assert "SUCCESS" not in res["result"]  # NOTE: this is coming from promtool and may change
