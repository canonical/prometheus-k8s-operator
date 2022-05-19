#!/usr/bin/env python3
# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

"""This test module tests the prometheus_scrape interface with multiple-to-multiple units related.

This test scaling up/down both sides of the relation, and upgrading.

1. Deploy several units of prometheus and several units of a "provider" charm, and relate them.
2. Confirm all units of prometheus have the correct and same targets and rules.
3. Upgrade prometheus.
4. Scale prometheus up and down.
5. Scale the "provider" charm up and down.
"""

import asyncio
import logging

import pytest
from deepdiff import DeepDiff
from helpers import (
    check_prometheus_is_ready,
    get_prometheus_active_targets,
    oci_image,
    run_promql,
)
from pytest_operator.plugin import OpsTest

logger = logging.getLogger(__name__)

prometheus_app_name = "prometheus"
# prometheus_resources = {"prometheus-image": oci_image("./metadata.yaml", "prometheus-image")}
prometheus_resources = {"prometheus-image": "prom/prometheus:v2.35.0"}
tester_app_name = "tester"
tester_resources = {
    "prometheus-tester-image": oci_image(
        "./tests/integration/prometheus-tester/metadata.yaml",
        "prometheus-tester-image",
    )
}
num_units = 2  # Using the same number of units for both prometheus and the tester

# The period of time required to be idle before `wait_for_idle` returns is set to 90 sec because
# unit upgrades were observed to take place 40-70 seconds apart.
idle_period = 90


async def test_setup_env(ops_test: OpsTest):
    await ops_test.model.set_config(
        {"logging-config": "<root>=WARNING; unit=DEBUG", "update-status-hook-interval": "60m"}
    )


@pytest.mark.abort_on_fail
async def test_prometheus_scrape_relation_with_prometheus_tester(
    ops_test: OpsTest, prometheus_charm, prometheus_tester_charm
):
    """Relate several units of prometheus and several units of the tester charm.

    - Deploy several units of prometheus and several units of a "provider" charm, and relate them.
    - Confirm all units of prometheus have the correct and same targets and rules.
    """
    app_names = [prometheus_app_name, tester_app_name]

    # GIVEN prometheus and the tester charm are deployed with two units each

    await asyncio.gather(
        ops_test.model.deploy(
            prometheus_charm,
            resources=prometheus_resources,
            application_name=prometheus_app_name,
            num_units=num_units,
        ),
        ops_test.model.deploy(
            prometheus_tester_charm,
            resources=tester_resources,
            application_name=tester_app_name,
            num_units=num_units,
        ),
    )

    await ops_test.model.wait_for_idle(apps=app_names, status="active", wait_for_units=num_units)
    await asyncio.gather(
        *[check_prometheus_is_ready(ops_test, prometheus_app_name, u) for u in range(num_units)]
    )

    # WHEN prometheus is not related to anything
    # THEN all prometheus units should have only one scrape target (self-scraping)
    for unit_num in range(num_units):
        targets = await get_prometheus_active_targets(ops_test, prometheus_app_name, unit_num)
        assert len(targets) == 1
        self_scrape = next(iter(targets))
        assert self_scrape["labels"]["job"] == "prometheus"
        assert self_scrape["labels"]["instance"] == "localhost:9090"

    # WHEN prometheus is related to the tester
    await ops_test.model.add_relation(prometheus_app_name, tester_app_name)
    await ops_test.model.wait_for_idle(apps=app_names, status="active")

    # THEN all prometheus units should have all tester units as targets (as well as self-scraping)
    # `targets_by_unit` is a List[List[dict]]: every unit has a List[dict] targets.
    targets_by_unit = await asyncio.gather(
        *[
            get_prometheus_active_targets(ops_test, prometheus_app_name, u)
            for u in range(num_units)
        ]
    )
    assert all(len(targets) == num_units + 1 for targets in targets_by_unit)

    # AND all prometheus units have the exact same targets
    # Only comparing the `labels` because comparing the entire `targets` dict would be cumbersome:
    # would need to pop 'lastScrape', 'lastScrapeDuration', whose values may differ across units.
    labels = [[{"labels": d["labels"]} for d in unit_targets] for unit_targets in targets_by_unit]
    for u in range(1, len(targets_by_unit)):
        assert DeepDiff(labels[0], labels[u], ignore_order=True) == {}
    # Could use `set`, but that would produce unhelpful error messages.
    # assert len(set(map(lambda x: json.dumps(x, sort_keys=True), targets_by_unit))) == 1

    # AND all prometheus units have the exact same config
    # TODO

    # AND all prometheus units have the exact same rules
    # TODO


@pytest.mark.abort_on_fail
async def test_upgrade_prometheus(ops_test: OpsTest, prometheus_charm):
    """Upgrade prometheus and confirm all is still green (see also test_upgrade_charm.py)."""
    # GIVEN an existing "up" timeseries
    up_before = await asyncio.gather(
        *[
            run_promql(ops_test, 'up{instance="localhost:9090"}[2h]', prometheus_app_name, u)
            for u in range(num_units)
        ]
    )
    # Each response looks like this:
    # [
    #     {
    #         "metric": {"__name__": "up", "instance": "localhost:9090", "job": "prometheus"},
    #         "values": [[1652931430.156, "1"], [1652931435.156, "1"]],
    #     }
    # ]
    up_before = [next(iter(response))["values"] for response in up_before]

    # WHEN prometheus is upgraded
    await ops_test.model.applications[prometheus_app_name].refresh(
        path=prometheus_charm, resources=prometheus_resources
    )

    # THEN nothing breaks
    await ops_test.model.wait_for_idle(status="active", idle_period=idle_period, timeout=300)
    await asyncio.gather(
        *[check_prometheus_is_ready(ops_test, prometheus_app_name, u) for u in range(num_units)]
    )

    # AND series continuity is maintained
    up_after = await asyncio.gather(
        *[
            run_promql(ops_test, 'up{instance="localhost:9090"}[2h]', prometheus_app_name, u)
            for u in range(num_units)
        ]
    )
    up_after = [next(iter(response))["values"] for response in up_after]
    # Need to convert the list of lists to list of tuples to be able to use set.issubset, which
    # doesn't work on lists because list is unhashable so cannot be a set element.
    assert all(
        set(map(tuple, up_before[i])).issubset(set(map(tuple, up_after[i])))
        for i in range(num_units)
    )


@pytest.mark.abort_on_fail
async def test_rescale_prometheus(ops_test: OpsTest):
    # WHEN prometheus is scaled up
    num_additional_units = 1
    await ops_test.model.applications[prometheus_app_name].scale(scale_change=num_additional_units)
    new_num_units = num_units + num_additional_units

    # THEN nothing breaks
    await ops_test.model.wait_for_idle(
        apps=[prometheus_app_name],
        status="active",
        timeout=120,
        wait_for_exact_units=new_num_units,
    )
    await ops_test.model.wait_for_idle(status="active")
    await asyncio.gather(
        *[
            check_prometheus_is_ready(ops_test, prometheus_app_name, u)
            for u in range(new_num_units)
        ]
    )

    # WHEN prometheus is scaled back down
    await ops_test.model.applications[prometheus_app_name].scale(
        scale_change=-num_additional_units
    )

    # THEN nothing breaks
    await ops_test.model.wait_for_idle(
        apps=[prometheus_app_name], status="active", timeout=120, wait_for_exact_units=num_units
    )
    await ops_test.model.wait_for_idle(status="active")
    await asyncio.gather(
        *[check_prometheus_is_ready(ops_test, prometheus_app_name, u) for u in range(num_units)]
    )


@pytest.mark.abort_on_fail
async def test_rescale_tester(ops_test: OpsTest):
    # WHEN tester is scaled up
    num_additional_units = 1
    await ops_test.model.applications[tester_app_name].scale(scale_change=num_additional_units)
    new_num_units = num_units + num_additional_units

    # THEN nothing breaks
    await ops_test.model.wait_for_idle(
        apps=[tester_app_name],
        status="active",
        timeout=120,
        wait_for_exact_units=new_num_units,
    )
    await ops_test.model.wait_for_idle(status="active")
    await asyncio.gather(
        *[check_prometheus_is_ready(ops_test, prometheus_app_name, u) for u in range(num_units)]
    )

    # WHEN tester is scaled back down
    await ops_test.model.applications[tester_app_name].scale(scale_change=-num_additional_units)

    # THEN nothing breaks
    await ops_test.model.wait_for_idle(
        apps=[tester_app_name], status="active", timeout=120, wait_for_exact_units=num_units
    )
    await ops_test.model.wait_for_idle(status="active")
    await asyncio.gather(
        *[check_prometheus_is_ready(ops_test, prometheus_app_name, u) for u in range(num_units)]
    )


@pytest.mark.abort_on_fail
async def test_upgrade_prometheus_while_rescaling_tester(ops_test: OpsTest, prometheus_charm):
    """Upgrade prometheus and rescale tester at the same time (without waiting for idle)."""
    # WHEN prometheus is upgraded at the same time that the tester is scaled up
    num_additional_units = 1

    logger.info("Upgrading prometheus and scaling-up tester at the same time...")
    await asyncio.gather(
        ops_test.model.applications[prometheus_app_name].refresh(
            path=prometheus_charm, resources=prometheus_resources
        ),
        ops_test.model.applications[tester_app_name].scale(scale_change=num_additional_units),
    )
    new_num_units = num_units + num_additional_units

    # AND tester becomes active/idle after scale-up
    logger.info("Waiting for tester to become active/idle...")
    await ops_test.model.wait_for_idle(
        apps=[tester_app_name],
        status="active",
        timeout=300,
        wait_for_exact_units=new_num_units,
    )

    # AND all apps become idle after prometheus upgrade
    logger.info("Waiting for all apps to become active/idle...")
    await ops_test.model.wait_for_idle(status="active", idle_period=idle_period, timeout=300)

    # THEN nothing breaks
    await asyncio.gather(
        *[check_prometheus_is_ready(ops_test, prometheus_app_name, u) for u in range(num_units)]
    )

    # WHEN prometheus is upgraded at the same time that the tester is scaled back down
    logger.info("Upgrading prometheus and scaling-down tester at the same time...")
    await asyncio.gather(
        ops_test.model.applications[prometheus_app_name].refresh(
            path=prometheus_charm, resources=prometheus_resources
        ),
        ops_test.model.applications[tester_app_name].scale(scale_change=-num_additional_units),
    )

    # AND tester becomes active/idle after scale-down
    logger.info("Waiting for tester to become active/idle...")
    await ops_test.model.wait_for_idle(
        apps=[tester_app_name], status="active", timeout=300, wait_for_exact_units=num_units
    )

    # AND all apps become idle after prometheus upgrade
    logger.info("Waiting for all apps to become active/idle...")
    await ops_test.model.wait_for_idle(status="active", idle_period=idle_period, timeout=300)

    # THEN nothing breaks
    await asyncio.gather(
        *[check_prometheus_is_ready(ops_test, prometheus_app_name, u) for u in range(num_units)]
    )


@pytest.mark.abort_on_fail
async def test_rescale_prometheus_while_upgrading_tester(
    ops_test: OpsTest, prometheus_tester_charm
):
    # WHEN prometheus is scaled up at the same time the tester is upgraded
    num_additional_units = 1
    await asyncio.gather(
        ops_test.model.applications[tester_app_name].refresh(
            path=prometheus_tester_charm, resources=tester_resources
        ),
        ops_test.model.applications[prometheus_app_name].scale(scale_change=num_additional_units),
    )
    new_num_units = num_units + num_additional_units

    # AND prometheus becomes active/idle after scale-up
    await ops_test.model.wait_for_idle(
        apps=[prometheus_app_name],
        status="active",
        timeout=300,
        wait_for_exact_units=new_num_units,
    )

    # AND all apps become idle after tester upgrade
    await ops_test.model.wait_for_idle(status="active", idle_period=idle_period, timeout=300)

    # THEN nothing breaks
    await asyncio.gather(
        *[
            check_prometheus_is_ready(ops_test, prometheus_app_name, u)
            for u in range(new_num_units)
        ]
    )

    # WHEN prometheus is scaled back down at the same time the tester is upgraded
    await asyncio.gather(
        ops_test.model.applications[tester_app_name].refresh(
            path=prometheus_tester_charm, resources=tester_resources
        ),
        ops_test.model.applications[prometheus_app_name].scale(scale_change=-num_additional_units),
    )

    # AND prometheus becomes active/idle after scale-down
    await ops_test.model.wait_for_idle(
        apps=[tester_app_name],
        status="active",
        timeout=300,
        wait_for_exact_units=num_units,
    )

    # AND all apps become idle after tester upgrade
    await ops_test.model.wait_for_idle(status="active", idle_period=idle_period, timeout=300)

    # THEN nothing breaks
    await asyncio.gather(
        *[check_prometheus_is_ready(ops_test, prometheus_app_name, u) for u in range(num_units)]
    )
