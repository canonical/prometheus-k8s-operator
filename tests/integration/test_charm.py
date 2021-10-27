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
)

logger = logging.getLogger(__name__)


@pytest.mark.abort_on_fail
@pytest.mark.parametrize("oci_image", ["ubuntu/prometheus:latest", "prom/prometheus:latest"])
async def test_build_and_deploy_with_alternative_images(ops_test, prometheus_charm, oci_image):
    """Test that the Prometheus charm can be deployed successfully."""
    resources = {"prometheus-image": oci_image}
    app_name = "prometheus-" + oci_image.split("/")[0]

    await ops_test.model.deploy(prometheus_charm, resources=resources, application_name=app_name)
    await ops_test.model.wait_for_idle(apps=[app_name], status="active")
    await ops_test.model.block_until(lambda: len(ops_test.model.applications[app_name].units) > 0)

    assert ops_test.model.applications[app_name].units[0].workload_status == "active"

    await check_prometheus_is_ready(ops_test, app_name, 0)

    await ops_test.model.applications[app_name].remove()
    await ops_test.model.reset()


@pytest.mark.abort_on_fail
async def test_build_and_deploy_prometheus_tester(ops_test, prometheus_tester_charm):
    """Test that Prometheus tester charm can be deployed successfully."""
    resources = {"prometheus-tester-image": "python:slim"}
    app_name = "prometheus-tester"

    await ops_test.model.deploy(
        prometheus_tester_charm, resources=resources, application_name=app_name
    )
    await ops_test.model.wait_for_idle(apps=[app_name], status="active")
    await ops_test.model.block_until(lambda: len(ops_test.model.applications[app_name].units) > 0)

    assert ops_test.model.applications[app_name].units[0].workload_status == "active"

    await ops_test.model.applications[app_name].remove()
    await ops_test.model.reset()


@pytest.mark.abort_on_fail
async def test_prometheus_scrape_relation_with_prometheus_tester(
    ops_test, prometheus_charm, prometheus_tester_charm
):
    """Test that Prometheus tester charm can be deployed successfully."""
    tester_resources = {"prometheus-tester-image": "python:slim"}
    prometheus_resources = {"prometheus-image": "ubuntu/prometheus:latest"}
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
    await ops_test.model.reset()
