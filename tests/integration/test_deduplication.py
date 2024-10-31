#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import json

from helpers import get_prometheus_active_targets, oci_image

from .juju import Juju

prometheus_app_name = "prometheus"
prometheus_resources = {"prometheus-image": oci_image("./metadata.yaml", "prometheus-image")}
tester_app_name = "tester"
tester_resources = {
    "prometheus-tester-image": oci_image(
        "./tests/integration/prometheus-tester/metadata.yaml",
        "prometheus-tester-image",
    )
}


def test_multiple_scrape_jobs_in_constructor(prometheus_charm, prometheus_tester_charm):
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

    Juju.deploy(
        prometheus_charm, alias=prometheus_app_name, resources=prometheus_resources, trust=True
    )
    Juju.deploy(
        prometheus_tester_charm,
        alias=tester_app_name,
        resources=tester_resources,
        config={"scrape_jobs": json.dumps(jobs)},
    )

    Juju.integrate(
        f"{prometheus_app_name}:metrics-endpoint", f"{tester_app_name}:metrics-endpoint"
    )
    Juju.wait_for_idle([prometheus_app_name, tester_app_name])

    targets = await get_prometheus_active_targets(prometheus_app_name)
    # Two unique jobs above plus an additional an additional job for self scraping.
    assert len(targets) == 3


def test_same_app_related_two_ways(prometheus_charm, prometheus_tester_charm):
    """Test that the deduplication works when the same app is related twice."""
    # TODO: is this correct?
    Juju.config(tester_app_name, ['scrape_jobs=""'])
    Juju.deploy("prometheus-scrape-config-k8s", channel="edge", alias="scrape-config")

    Juju.integrate(f"{prometheus_app_name}:metrics-endpoint", "scrape-config:metrics-endpoint")
    Juju.integrate("scrape-config:configurable-scrape-jobs", f"{tester_app_name}:metrics-endpoint")

    Juju.wait_for_idle([prometheus_app_name, "scrape-config", tester_app_name])
