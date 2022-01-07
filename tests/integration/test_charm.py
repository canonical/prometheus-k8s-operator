#!/usr/bin/env python3
# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

import logging

import pytest
from helpers import (
    check_prometheus_is_ready,
    get_job_config_for,
    get_prometheus_config,
    get_prometheus_rules,
    get_rules_for,
    oci_image,
)

logger = logging.getLogger(__name__)

tester_resources = {
    "prometheus-tester-image": oci_image(
        "./tests/integration/prometheus-tester/metadata.yaml", "prometheus-tester-image"
    )
}
prometheus_resources = {"prometheus-image": oci_image("./metadata.yaml", "prometheus-image")}


@pytest.mark.abort_on_fail
async def test_prometheus_scrape_relation_with_prometheus_tester(
    ops_test, prometheus_charm, prometheus_tester_charm
):
    """Test basic functionality of prometheus_scrape relation interface."""
    prometheus_app_name = "prometheus"
    tester_app_name = "prometheus-tester"

    await ops_test.model.deploy(
        prometheus_charm, resources=prometheus_resources, application_name=prometheus_app_name
    )
    await ops_test.model.deploy(
        prometheus_tester_charm, resources=tester_resources, application_name=tester_app_name
    )
    await ops_test.model.wait_for_idle(apps=[prometheus_app_name], status="active")
    await ops_test.model.wait_for_idle(apps=[tester_app_name], status="active")
    await ops_test.model.block_until(
        lambda: len(ops_test.model.applications[prometheus_app_name].units) > 0
    )
    await ops_test.model.block_until(
        lambda: len(ops_test.model.applications[tester_app_name].units) > 0
    )

    assert ops_test.model.applications[prometheus_app_name].units[0].workload_status == "active"
    assert ops_test.model.applications[tester_app_name].units[0].workload_status == "active"

    await check_prometheus_is_ready(ops_test, prometheus_app_name, 0)
    initial_config = await get_prometheus_config(ops_test, prometheus_app_name, 0)
    initial_rules = await get_prometheus_rules(ops_test, prometheus_app_name, 0)

    await ops_test.model.add_relation(prometheus_app_name, tester_app_name)
    await ops_test.model.wait_for_idle(apps=[prometheus_app_name], status="active")
    config_with_relation = await get_prometheus_config(ops_test, prometheus_app_name, 0)
    tester_job = get_job_config_for(tester_app_name, config_with_relation)
    assert tester_job != {}

    rules_with_relation = await get_prometheus_rules(ops_test, prometheus_app_name, 0)
    tester_rules = get_rules_for(tester_app_name, rules_with_relation)
    assert tester_rules != {}

    await ops_test.model.applications[tester_app_name].remove()
    await ops_test.model.wait_for_idle(apps=[prometheus_app_name], status="active")

    relation_removed_config = await get_prometheus_config(ops_test, prometheus_app_name, 0)
    assert initial_config == relation_removed_config

    relation_removed_rules = await get_prometheus_rules(ops_test, prometheus_app_name, 0)
    assert initial_rules == relation_removed_rules

    await ops_test.model.applications[prometheus_app_name].remove()

    await ops_test.model.block_until(
        lambda: prometheus_app_name not in ops_test.model.applications
    )
    await ops_test.model.block_until(lambda: tester_app_name not in ops_test.model.applications)
    await ops_test.model.reset()
