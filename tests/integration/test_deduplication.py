#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import asyncio
import json

from helpers import get_prometheus_active_targets, oci_image
from pytest_operator.plugin import OpsTest

prometheus_app_name = "prometheus"
prometheus_resources = {"prometheus-image": oci_image("./charmcraft.yaml", "prometheus-image")}
tester_app_name = "tester"
tester_resources = {
    "prometheus-tester-image": oci_image(
        "./tests/integration/prometheus-tester/metadata.yaml",
        "prometheus-tester-image",
    )
}


async def test_multiple_scrape_jobs_in_constructor(
    ops_test: OpsTest, prometheus_charm, prometheus_tester_charm
):
    """Test that job names are properly deduped when in the same consumer unit."""
    assert ops_test.model
    jobs = [
        {
            "scrape_interval": "10s",
            "static_configs": [{"targets": ["*:8000"]}],
        },
        {
            "scrape_interval": "10s",
            "static_configs": [{"targets": ["*:8000"]}],
        },
        {
            "scrape_interval": "10s",
            "static_configs": [{"targets": ["*:8001"]}],
        },
    ]
    await asyncio.gather(
        ops_test.model.deploy(
            prometheus_charm,
            resources=prometheus_resources,
            application_name=prometheus_app_name,
            trust=True,
        ),
        ops_test.model.deploy(
            prometheus_tester_charm,
            resources=tester_resources,
            application_name=tester_app_name,
            config={"scrape_jobs": json.dumps(jobs)},
        ),
    )
    await ops_test.model.add_relation(
        f"{prometheus_app_name}:metrics-endpoint", f"{tester_app_name}:metrics-endpoint"
    )
    await ops_test.model.wait_for_idle(status="active")

    targets = await get_prometheus_active_targets(ops_test, prometheus_app_name)
    # Two unique jobs above plus an additional an additional job for self scraping.
    assert len(targets) == 3


async def test_same_app_related_two_ways(
    ops_test: OpsTest, prometheus_charm, prometheus_tester_charm
):
    """Test that the deduplication works when the same app is related twice."""
    assert ops_test.model
    await asyncio.gather(
        ops_test.model.applications[tester_app_name].reset_config(["scrape_jobs"]),
        ops_test.model.deploy(
            "prometheus-scrape-config-k8s", channel="2/edge", application_name="scrape-config"
        ),
    )
    await asyncio.gather(
        ops_test.model.add_relation(
            f"{prometheus_app_name}:metrics-endpoint", "scrape-config:metrics-endpoint"
        ),
        ops_test.model.add_relation(
            "scrape-config:configurable-scrape-jobs", f"{tester_app_name}:metrics-endpoint"
        ),
    )
    await ops_test.model.wait_for_idle(status="active")
