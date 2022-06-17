#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import asyncio
import json

from helpers import get_prometheus_active_targets, oci_image
from pytest_operator.plugin import OpsTest

prometheus_app_name = "prometheus"
prometheus_resources = {"prometheus-image": oci_image("./metadata.yaml", "prometheus-image")}
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
    await ops_test.model.add_relation(prometheus_app_name, tester_app_name)
    await ops_test.model.wait_for_idle(status="active")

    targets = await get_prometheus_active_targets(ops_test, prometheus_app_name)
    # Two unique jobs above plus an additional an additional job for self scraping.
    assert len(targets) == 3
