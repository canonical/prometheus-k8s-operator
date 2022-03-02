#!/usr/bin/env python3
# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

import asyncio
import logging

import pytest
from helpers import (
    check_prometheus_is_ready,
    get_job_config_for,
    get_prometheus_config,
    get_prometheus_rules,
    get_rules_for,
    initial_workload_is_ready,
    oci_image,
)
from pytest_operator.plugin import OpsTest

logger = logging.getLogger(__name__)


@pytest.mark.abort_on_fail
async def test_prometheus_scrape_relation_with_prometheus_tester(
    ops_test: OpsTest, prometheus_charm, prometheus_tester_charm
):
    """Test basic functionality of prometheus_scrape relation interface."""
    prometheus_app_name = "prometheus"
    tester_app_name = "prometheus-tester"
    app_names = [prometheus_app_name, tester_app_name]

    await asyncio.gather(
        ops_test.model.deploy(
            prometheus_charm,
            resources={"prometheus-image": oci_image("./metadata.yaml", "prometheus-image")},
            application_name=prometheus_app_name,
        ),
        ops_test.model.deploy(
            prometheus_tester_charm,
            resources={
                "prometheus-tester-image": oci_image(
                    "./tests/integration/prometheus-tester/metadata.yaml",
                    "prometheus-tester-image",
                )
            },
            application_name=tester_app_name,
        ),
    )

    await ops_test.model.wait_for_idle(apps=app_names, status="active")

    # TODO: Should not be needed.
    #       Drop once https://github.com/juju/python-libjuju/issues/574 is resolved
    #       - SA 2021-11-23
    await ops_test.model.block_until(
        lambda: (
            len(ops_test.model.applications[prometheus_app_name].units) > 0
            and len(ops_test.model.applications[tester_app_name].units) > 0
        )
    )

    assert initial_workload_is_ready(ops_test, app_names)
    await check_prometheus_is_ready(ops_test, prometheus_app_name, 0)

    initial_config, initial_rules = await asyncio.gather(
        get_prometheus_config(ops_test, prometheus_app_name, 0),
        get_prometheus_rules(ops_test, prometheus_app_name, 0),
    )

    await ops_test.model.add_relation(prometheus_app_name, tester_app_name)
    await ops_test.model.wait_for_idle(apps=[prometheus_app_name], status="active")

    config_with_relation = await get_prometheus_config(ops_test, prometheus_app_name, 0)
    tester_job = get_job_config_for(tester_app_name, config_with_relation)
    assert tester_job != {}

    rules_with_relation = await get_prometheus_rules(ops_test, prometheus_app_name, 0)
    tester_rules = get_rules_for(tester_app_name, rules_with_relation)
    assert len(tester_rules) == 1

    await ops_test.model.applications[tester_app_name].remove()
    await ops_test.model.wait_for_idle(apps=[prometheus_app_name], status="active")

    relation_removed_config, relation_removed_rules = await asyncio.gather(
        get_prometheus_config(ops_test, prometheus_app_name, 0),
        get_prometheus_rules(ops_test, prometheus_app_name, 0),
    )
    assert initial_config == relation_removed_config
    assert initial_rules == relation_removed_rules
