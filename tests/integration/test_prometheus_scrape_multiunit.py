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
from deepdiff import DeepDiff
import pytest
from helpers import (
    check_prometheus_is_ready,
    get_prometheus_active_targets,
    oci_image,
)
from pytest_operator.plugin import OpsTest

logger = logging.getLogger(__name__)

prometheus_app_name = "prometheus"
prometheus_resources = {"prometheus-image": oci_image("./metadata.yaml", "prometheus-image")}
tester_app_name = "tester"
num_units = 2  # Using the same number of units for both prometheus and the tester


async def test_setup_env(ops_test: OpsTest):
    await ops_test.model.set_config({"logging-config": "<root>=WARNING; unit=DEBUG"})


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
            resources={
                "prometheus-tester-image": oci_image(
                    "./tests/integration/prometheus-tester/metadata.yaml",
                    "prometheus-tester-image",
                )
            },
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


@pytest.mark.abort_on_fail
async def test_upgrade_prometheus(ops_test: OpsTest, prometheus_charm):
    """Upgrade prometheus and confirm all is still green (see also test_upgrade_charm.py)."""
    # WHEN prometheus is upgraded
    await ops_test.model.applications[prometheus_app_name].refresh(
        path=prometheus_charm, resources=prometheus_resources
    )

    # THEN nothing breaks
    await ops_test.model.wait_for_idle(status="active", idle_period=60)
    await asyncio.gather(
        *[check_prometheus_is_ready(ops_test, prometheus_app_name, u) for u in range(num_units)]
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
        timeout=600,
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
        apps=[prometheus_app_name], status="active", timeout=600, wait_for_exact_units=num_units
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
        timeout=600,
        wait_for_exact_units=new_num_units,
    )
    await ops_test.model.wait_for_idle(status="active")
    await asyncio.gather(
        *[
            check_prometheus_is_ready(ops_test, prometheus_app_name, u)
            for u in range(num_units)
        ]
    )

    # WHEN tester is scaled back down
    await ops_test.model.applications[tester_app_name].scale(
        scale_change=-num_additional_units
    )

    # THEN nothing breaks
    await ops_test.model.wait_for_idle(
        apps=[tester_app_name], status="active", timeout=600, wait_for_exact_units=num_units
    )
    await ops_test.model.wait_for_idle(status="active")
    await asyncio.gather(
        *[check_prometheus_is_ready(ops_test, prometheus_app_name, u) for u in range(num_units)]
    )
