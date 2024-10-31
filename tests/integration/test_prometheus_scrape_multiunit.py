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
import yaml
from deepdiff import DeepDiff
from helpers import (
    check_prometheus_is_ready,
    get_prometheus_active_targets,
    get_prometheus_config,
    get_prometheus_rules,
    oci_image,
    run_promql,
)
from .juju import Juju

logger = logging.getLogger(__name__)

prometheus_app_name = "prometheus"
prometheus_resources = {"prometheus-image": oci_image("./metadata.yaml", "prometheus-image")}
scrape_tester = "tester"
scrape_tester_resources = {
    "prometheus-tester-image": oci_image(
        "./tests/integration/prometheus-tester/metadata.yaml",
        "prometheus-tester-image",
    )
}
remote_write_tester = "grafana-agent"
num_units = 2  # Using the same number of units for both prometheus and the testers

# The period of time required to be idle before `wait_for_idle` returns is set to 90 sec because
# unit upgrades were observed to take place 40-70 seconds apart.
idle_period = 90


@pytest.mark.skip(reason="xfail")
def test_setup_env():
    Juju.cli(["model-config", 'logging-config="<root>=WARNING; unit=DEBUG"', "update-status-hook-interval=60m"])



@pytest.mark.skip(reason="xfail")
def test_prometheus_scrape_relation_with_prometheus_tester(
    prometheus_charm, prometheus_tester_charm
):
    """Relate several units of prometheus and several units of the tester charm.

    - Deploy several units of prometheus and several units of a "provider" charm, and relate them.
    - Confirm all units of prometheus have the correct and same targets and rules.
    """
    app_names = [prometheus_app_name, scrape_tester, remote_write_tester]

    # GIVEN prometheus and the tester charm are deployed with two units each

    Juju.deploy(prometheus_charm, resources=prometheus_resources, alias=prometheus_app_name, num_units=num_units, trust=True)
    Juju.deploy(prometheus_tester_charm, resources=scrape_tester_resources, alias=scrape_tester, num_units=num_units )
    Juju.deploy("ch:grafana-agent-k8s", alias=remote_write_tester, channel="edge", num_units=num_units, trust=True)
    Juju.wait_for_idle(app_names, timeout=600)

   
    for u in range(num_units):
        check_prometheus_is_ready(prometheus_app_name, u)
    

    # WHEN prometheus is not related to anything
    # THEN all prometheus units should have only one scrape target (self-scraping)
    for unit_num in range(num_units):
        targets = get_prometheus_active_targets( prometheus_app_name, unit_num)
        assert len(targets) == 1
        self_scrape = next(iter(targets))
        assert self_scrape["labels"]["job"] == "prometheus"
        assert self_scrape["labels"]["host"] == "localhost"

    # WHEN prometheus is related to the testers
    Juju.integrate(f"{prometheus_app_name}:metrics-endpoint", f"{scrape_tester}:metrics-endpoint")
    Juju.integrate(f"{prometheus_app_name}:receive-remote-write",
            f"{remote_write_tester}:send-remote-write",)
   
    Juju.wait_for_idle(app_names)

    # THEN all prometheus units should have all scrape units as targets (as well as self-scraping)
    # `targets_by_unit` is a List[List[dict]]: every unit has a List[dict] targets.
    targets_by_unit = [
            get_prometheus_active_targets( prometheus_app_name, u)
            for u in range(num_units)
        ]
    
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
    config_by_unit = 
        [get_prometheus_config(prometheus_app_name, u) for u in range(num_units)]
    
    # Convert the yaml strings into dicts
    config_by_unit = list(map(yaml.safe_load, config_by_unit))

    for u in range(1, num_units):
        # Exclude keys that are expected to differ (different IP address per unit)
        assert (
            DeepDiff(
                config_by_unit[0],
                config_by_unit[u],
                ignore_order=True,
                exclude_regex_paths=r"\['static_configs'\]\['targets'\]|\['labels'\]\['juju_unit'\]",
            )
            == {}
        )

    # AND all prometheus units have the exact same rules
    rules_by_unit =
        [get_prometheus_rules( prometheus_app_name, u) for u in range(num_units)]
    
    for u in range(1, len(rules_by_unit)):
        # Some fields will most likely differ, such as "evaluationTime" and "lastEvaluation".
        # Also excluding the following, which occasionally fails CI:
        # - "alerts" because the 'rules' endpoint returns a dict of firing alerts,
        #   which may vary across prometheus units given the share nothing and the units starting
        #   up at different times.
        # - "health", which takes time to switch from "unknown" to "ok".
        # - "state", which takes time to switch from "inactive" to "firing".
        assert (
            DeepDiff(
                rules_by_unit[0],
                rules_by_unit[u],
                ignore_order=True,
                exclude_regex_paths=r"evaluationTime|lastEvaluation|activeAt|alerts|health|state",
            )
            == {}
        )


@pytest.mark.skip(reason="xfail")
def test_upgrade_prometheus(prometheus_charm):
    """Upgrade prometheus and confirm all is still green (see also test_upgrade_charm.py)."""
    # GIVEN an existing "up" timeseries
    query = 'count_over_time(up{host="localhost",job="prometheus"}[1y])'
    up_before = 
        [run_promql( query, prometheus_app_name, u) for u in range(num_units)]
    
    # Each response looks like this:
    # [
    #     {
    #         "metric":{"instance":"localhost:9090","job":"prometheus"},
    #         "value":[1652985131.383,"711"]
    #     }
    # ]
    # Extract the count value and convert it to int
    up_before = [int(next(iter(response))["value"][1]) for response in up_before]
    # Sanity check: make sure it's not empty
    assert len(up_before) > 0
    assert all(up_before)

    # WHEN prometheus is upgraded
    Juju.refresh(prometheus_app_name, path=prometheus_charm, resources=prometheus_resources)

    # THEN nothing breaks
    Juju.wait_for_idle([prometheus_app_name, scrape_tester, remote_write_tester], timeout=600)
    [check_prometheus_is_ready( prometheus_app_name, u) for u in range(num_units)]


    # AND series continuity is maintained
    up_after = [run_promql( query, prometheus_app_name, u) for u in range(num_units)]
    
    up_after = [int(next(iter(response))["value"][1]) for response in up_after]
    # The count after an upgrade must be greater than or equal to the count before the upgrade, for
    # every prometheus unit (units start at different times so the count across units may differ).
    assert all(up_before[i] <= up_after[i] for i in range(num_units))


@pytest.mark.skip(reason="xfail")
def test_rescale_prometheus():
    # GitHub runner doesn't have enough resources to deploy 3 unit with the default "requests", and
    # the unit fails to schedule. Setting a low limit, so it is able to schedule.
    Juju.config(prometheus_app_name, options=["cpu=0.2", "memory=0.1Gi"])
    
    Juju.wait_for_idle([prometheus_app_name], timeout=240)

    # WHEN prometheus is scaled up
    num_additional_units = 1
    Juju.add_units(prometheus_app_name, num_additional_units)

    new_num_units = num_units + num_additional_units

    # THEN nothing breaks
    # TODO: add wait_for_exact_units
    Juju.wait_for_idle([prometheus_app_name, scrape_tester, remote_tester],  timeout=240)

    for u in range(new_num_units):
        check_prometheus_is_ready( prometheus_app_name, u)

    # WHEN prometheus is scaled back down
    Juju.remove_units(prometheus_app_name, num_additional_units)

    # THEN nothing breaks
    # TODO: add wait_for_exact_units
    Juju.wait_for_idle([prometheus_app_name, scrape_tester, remote_tester], timeout=240)
    
    for u in range(num_units):
        check_prometheus_is_ready(prometheus_app_name, u)


@pytest.mark.skip(reason="xfail")
def test_rescale_tester():
    # WHEN testers are scaled up
    num_additional_units = 1
    Juju.add_units(scrape_tester, num_additional_units)
    Juju.add_units(remote_write_tester, num_additional_units)

    new_num_units = num_units + num_additional_units

    # THEN nothing breaks
    # TODO: add wait_for_exact_units
    Juju.wait_for_idle([scrape_tester, remote_write_tester, prometheus_app_name], timeout=240)

    for u in range(num_units):
        check_prometheus_is_ready( prometheus_app_name, u)


    # WHEN tester is scaled back down
    Juju.remove_units(scrape_tester, num_additional_units)
    Juju.remove_units(remote_write_tester, num_additional_units)

    # THEN nothing breaks
    # TODO: add wait_for_exact_units
    Juju.wait_for_idle([scrape_tester, remote_write_tester, prometheus_app_name], timeout=240)

    for u in range(num_units):
        check_prometheus_is_ready(prometheus_app_name, u)

@pytest.mark.skip(reason="xfail")
def test_upgrade_prometheus_while_rescaling_testers( prometheus_charm):
    """Upgrade prometheus and rescale testers at the same time (without waiting for idle)."""
    # WHEN prometheus is upgraded at the same time that the testers are scaled up
    num_additional_units = 1

    logger.info("Upgrading prometheus and scaling-up testers at the same time...")
    Juju.refresh(prometheus_app_name, path=prometheus_charm, resources=prometheus_resources)
    Juju.add_units(scrape_tester, num_additional_units)
    Juju.add_units(remote_write_tester, num_additional_units)


    new_num_units = num_units + num_additional_units

    # AND tester becomes active/idle after scale-up
    logger.info("Waiting for testers to become active/idle...")
    await ops_test.model.wait_for_idle(
        apps=[scrape_tester, remote_write_tester],
        status="active",
        timeout=300,
        wait_for_exact_units=new_num_units,
    )

    # AND all apps become idle after prometheus upgrade
    logger.info("Waiting for all apps to become active/idle...")
    await ops_test.model.wait_for_idle(status="active", idle_period=idle_period, timeout=600)

    # THEN nothing breaks
    await asyncio.gather(
        *[check_prometheus_is_ready(ops_test, prometheus_app_name, u) for u in range(num_units)]
    )

    # WHEN prometheus is upgraded at the same time that the testers are scaled back down
    logger.info("Upgrading prometheus and scaling-down testers at the same time...")
    await asyncio.gather(
        ops_test.model.applications[prometheus_app_name].refresh(
            path=prometheus_charm, resources=prometheus_resources
        ),
        ops_test.model.applications[scrape_tester].scale(scale_change=-num_additional_units),
        ops_test.model.applications[remote_write_tester].scale(scale_change=-num_additional_units),
    )

    # AND tester becomes active/idle after scale-down
    logger.info("Waiting for testers to become active/idle...")
    await ops_test.model.wait_for_idle(
        apps=[scrape_tester, remote_write_tester],
        status="active",
        timeout=300,
        wait_for_exact_units=num_units,
    )

    # AND all apps become idle after prometheus upgrade
    logger.info("Waiting for all apps to become active/idle...")
    await ops_test.model.wait_for_idle(status="active", idle_period=idle_period, timeout=300)

    # THEN nothing breaks
    await asyncio.gather(
        *[check_prometheus_is_ready(ops_test, prometheus_app_name, u) for u in range(num_units)]
    )


@pytest.mark.skip(reason="xfail")
async def test_rescale_prometheus_while_upgrading_testers(
    prometheus_tester_charm
):
    # WHEN prometheus is scaled up at the same time the testers are upgraded
    num_additional_units = 1
    Juju.refresh(scrape_tester, path=prometheus_tester_charm, resources=scrape_tester_resources)
    # Juju.refresh(remote_write_tester, channel="edge")
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
        ops_test.model.applications[scrape_tester].refresh(
            path=prometheus_tester_charm, resources=scrape_tester_resources
        ),
        # ops_test.model.applications[remote_write_tester].refresh(channel="edge"),
        ops_test.model.applications[prometheus_app_name].scale(scale_change=-num_additional_units),
    )

    # AND prometheus becomes active/idle after scale-down
    await ops_test.model.wait_for_idle(
        apps=[prometheus_app_name],
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
