#!/usr/bin/env python3
# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

import asyncio
import logging

import pytest
from helpers import check_prometheus_is_ready, oci_image

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


async def test_setup_env(ops_test):
    await ops_test.model.set_config({"logging-config": "<root>=WARNING; unit=DEBUG"})


@pytest.mark.abort_on_fail
async def test_good_config_validates_successfully(
    ops_test, prometheus_charm, prometheus_tester_charm
):
    """Deploy Prometheus and a single client with a good configuration."""
    await asyncio.gather(
        ops_test.model.deploy(
            prometheus_charm,
            resources=prometheus_resources,
            application_name=prometheus_app_name,
            trust=True,  # otherwise errors on ghwf (persistentvolumeclaims ... is forbidden)
        ),
        ops_test.model.deploy(
            prometheus_tester_charm,
            resources=scrape_tester_resources,
            application_name=scrape_tester,
        ),
    )
    await ops_test.model.wait_for_idle(apps=[prometheus_app_name, scrape_tester], status="active")
    await check_prometheus_is_ready(ops_test, prometheus_app_name, 0)

    await ops_test.model.add_relation(
        f"{prometheus_app_name}:metrics-endpoint", f"{scrape_tester}:metrics-endpoint"
    )

    # set some custom configs to later check they persisted across the test
    action = (
        await ops_test.model.applications[prometheus_app_name]
        .units[0]
        .run_action("validate-configuration")
    )
    res = (await action.wait()).results

    assert res["valid"] == "True"
    assert res["error-message"] == ""
    assert "SUCCESS" in res["result"]  # NOTE: this is coming from promtool so may change


@pytest.mark.abort_on_fail
async def test_bad_config_sets_action_results(ops_test, prometheus_charm, prometheus_tester_charm):
    """Deploy Prometheus and a single client with a good configuration."""
    await asyncio.gather(
        ops_test.model.deploy(
            "prometheus-scrape-config-k8s",
            channel="edge",
            application_name=scrape_shim,
            config={"scrape_interval": "NotANumber!!!"},
        ),
        ops_test.model.deploy(
            prometheus_tester_charm,
            resources=scrape_tester_resources,
            application_name=bad_scrape_tester,
        ),
    )
    await ops_test.model.wait_for_idle(apps=[scrape_shim, bad_scrape_tester])

    await asyncio.gather(
        ops_test.model.add_relation(
            f"{bad_scrape_tester}:metrics-endpoint", f"{scrape_shim}:configurable-scrape-jobs"
        ),
        ops_test.model.add_relation(
            f"{prometheus_app_name}:metrics-endpoint", f"{scrape_shim}:metrics-endpoint"
        ),
    )
    await ops_test.model.wait_for_idle(apps=[prometheus_app_name, scrape_shim, bad_scrape_tester])

    # set some custom configs to later check they persisted across the test
    action = (
        await ops_test.model.applications[prometheus_app_name]
        .units[0]
        .run_action("validate-configuration")
    )
    res = (await action.wait()).results

    assert res["valid"] == "False"
    assert "FAILED" in res["error-message"]  # NOTE: this is coming from promtool so may change
    assert "SUCCESS" not in res["result"]  # NOTE: this is coming from promtool and may change
