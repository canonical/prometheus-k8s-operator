#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import asyncio
import logging

import pytest
from helpers import (
    check_prometheus_is_ready,
    get_prometheus_rules,
    get_rules_for,
    oci_image,
    run_promql,
)

logger = logging.getLogger(__name__)

prometheus_resources = {"prometheus-image": oci_image("./metadata.yaml", "prometheus-image")}
tester_resources = {
    "prometheus-tester-image": oci_image(
        "./tests/integration/prometheus-tester/metadata.yaml", "prometheus-tester-image"
    )
}

prometheus_app_name = "prometheus-k8s"
tester_app_name = "prometheus-tester"
app_names = [prometheus_app_name, tester_app_name]


@pytest.mark.abort_on_fail
async def test_deploy_from_edge_and_upgrade_from_local_path(ops_test, prometheus_tester_charm):
    """Build the charm-under-test and deploy it together with related charms.

    Assert on the unit status before any relations/configurations take place.
    """
    logger.debug("deploy charm from charmhub")
    await asyncio.gather(
        ops_test.model.deploy(
            f"ch:{prometheus_app_name}",
            application_name=prometheus_app_name,
            channel="edge",
            trust=True,  # otherwise errors on ghwf (persistentvolumeclaims ... is forbidden)
        ),
        ops_test.model.deploy(
            prometheus_tester_charm, resources=tester_resources, application_name=tester_app_name
        ),
    )
    await ops_test.model.wait_for_idle(apps=app_names, status="active", timeout=300)

    await ops_test.model.add_relation(prometheus_app_name, tester_app_name)
    await ops_test.model.wait_for_idle(apps=app_names, status="active")
    # Check only one alert rule exists
    rules_with_relation = await get_prometheus_rules(ops_test, prometheus_app_name, 0)
    tester_rules = get_rules_for(tester_app_name, rules_with_relation)

    assert len(tester_rules) == 1


@pytest.mark.abort_on_fail
async def test_rules_are_retained_after_upgrade(ops_test, prometheus_charm):
    logger.debug("upgrade deployed charm with local charm %s", prometheus_charm)
    await ops_test.model.applications[prometheus_app_name].refresh(
        path=prometheus_charm, resources=prometheus_resources
    )
    await ops_test.model.wait_for_idle(
        apps=app_names, status="active", timeout=300, idle_period=60
    )
    assert await check_prometheus_is_ready(ops_test, prometheus_app_name, 0)

    # Check only one alert rule exists
    rules_with_relation = await get_prometheus_rules(ops_test, prometheus_app_name, 0)
    tester_rules = get_rules_for(tester_app_name, rules_with_relation)
    assert len(tester_rules) == 1


@pytest.mark.abort_on_fail
async def test_check_data_persist_on_charm_upgrade(ops_test, prometheus_charm):
    query = "prometheus_tsdb_head_chunks_created_total{}"
    total0 = await run_promql(ops_test, query, prometheus_app_name)
    sum0 = int(total0[0]["value"][1])

    logger.debug("upgrade deployed charm with local charm %s", prometheus_charm)
    await ops_test.model.applications[prometheus_app_name].refresh(
        path=prometheus_charm, resources=prometheus_resources
    )
    await ops_test.model.wait_for_idle(apps=app_names, status="active", timeout=300, idle_period=60)
    assert await check_prometheus_is_ready(ops_test, prometheus_app_name, 0)

    total1 = await run_promql(ops_test, query, prometheus_app_name)
    sum1 = int(total1[0]["value"][1])
    assert sum0 <= sum1
