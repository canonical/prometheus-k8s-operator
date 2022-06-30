#!/usr/bin/env python3
# Copyright 2021 Canonical Ltd.
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


@pytest.mark.abort_on_fail
async def test_remote_write_with_grafana_agent(
    ops_test, prometheus_charm, prometheus_tester_charm
):
    """Test that apps related with Grafana Agent over remote_write have correct expressions."""
    prometheus_name = "prometheus"
    agent_name = "grafana-agent"
    tester_name = "prometheus-tester"
    apps = [prometheus_name, agent_name, tester_name]

    await asyncio.gather(
        ops_test.model.deploy(
            prometheus_charm,
            resources={"prometheus-image": oci_image("./metadata.yaml", "prometheus-image")},
            application_name=prometheus_name,
            trust=True,  # otherwise errors on ghwf (persistentvolumeclaims ... is forbidden)
        ),
        ops_test.model.deploy(
            "grafana-agent-k8s",
            application_name=agent_name,
            channel="edge",
        ),
        ops_test.model.deploy(
            prometheus_tester_charm,
            resources={
                "prometheus-tester-image": oci_image(
                    "./tests/integration/prometheus-tester/metadata.yaml",
                    "prometheus-tester-image",
                )
            },
            application_name=tester_name,
        ),
    )

    await ops_test.model.wait_for_idle(apps=apps, status="active", wait_for_units=1)
    assert await check_prometheus_is_ready(ops_test, prometheus_name, 0)

    await asyncio.gather(
        ops_test.model.add_relation(
            f"{prometheus_name}:receive-remote-write", f"{agent_name}:send-remote-write"
        ),
        ops_test.model.add_relation(
            f"{tester_name}:metrics-endpoint", f"{agent_name}:metrics-endpoint"
        ),
    )

    # A considerable idle_period is needed to guarantee metrics show up in prometheus
    # (60 sec was not enough).
    await ops_test.model.wait_for_idle(apps=apps, status="active", idle_period=90)

    # Make sure topology labels are present
    rules_with_relation = await get_prometheus_rules(ops_test, prometheus_name, 0)
    tester_rules = get_rules_for(tester_name, rules_with_relation)[0]["rules"][0]

    expr = tester_rules["query"]
    topology_labels = [
        f'{k}="{v}"' for k, v in tester_rules["labels"].items() if k.startswith("juju_")
    ]
    assert all([field in expr for field in topology_labels])

    assert await has_metric(
        ops_test,
        f'up{{juju_model="{ops_test.model_name}",juju_application="{agent_name}"}}',
        prometheus_name,
    )


async def test_remote_write_alerts_deduplicate(ops_test):
    """Test that alerts for applications with multiple paths deduplicate."""
    prometheus_name = "prometheus"
    tester_name = "prometheus-tester"
    apps = [prometheus_name, tester_name]

    await ops_test.model.add_relation(
        f"{tester_name}:metrics-endpoint", f"{prometheus_name}:metrics-endpoint"
    )
    await ops_test.model.wait_for_idle(apps=apps, status="active", idle_period=90)

    # Make sure only one copy of the alerts is present
    rules_with_relation = await get_prometheus_rules(ops_test, prometheus_name, 0)
    tester_rules = get_rules_for(tester_name, rules_with_relation)[0]["rules"]
    assert len(tester_rules) == 1


@pytest.mark.abort_on_fail
async def test_check_data_persist_on_kubectl_delete_pod(ops_test, prometheus_charm):
    prometheus_app_name = "prometheus"
    pod_name = f"{prometheus_app_name}-0"
    query = "prometheus_tsdb_head_chunks_created_total{}"
    total0 = await run_promql(ops_test, query, prometheus_app_name)

    # total0 is a list of dicts in which "value" is a list that contains
    # the timestamp and the value itself.
    num_head_chunks_before = int(total0[0]["value"][1])
    assert num_head_chunks_before > 0

    cmd = [
        "sg",
        "microk8s",
        "-c",
        " ".join(["microk8s.kubectl", "delete", "pod", "-n", ops_test.model_name, pod_name]),
    ]

    logger.debug(
        "Removing pod '%s' from model '%s' with cmd: %s", pod_name, ops_test.model_name, cmd
    )

    retcode, stdout, stderr = await ops_test.run(*cmd)
    assert retcode == 0, f"kubectl failed: {(stderr or stdout).strip()}"
    logger.debug(stdout)

    await ops_test.model.block_until(
        lambda: len(ops_test.model.applications[prometheus_app_name].units) > 0
    )
    await ops_test.model.wait_for_idle(apps=[prometheus_app_name], status="active", timeout=60)
    assert await check_prometheus_is_ready(ops_test, prometheus_app_name, 0)

    total1 = await run_promql(ops_test, query, prometheus_app_name)
    num_head_chunks_after = int(total1[0]["value"][1])
    assert num_head_chunks_before <= num_head_chunks_after


@pytest.mark.abort_on_fail
async def test_check_data_not_persist_on_scale_0(ops_test, prometheus_charm):
    prometheus_app_name = "prometheus"

    query = "prometheus_tsdb_head_chunks_created_total{}"
    total0 = await run_promql(ops_test, query, prometheus_app_name)

    # total0 is a list of dicts in which "value" is a list that contains
    # the timestamp and the value itself.
    num_head_chunks_before = int(total0[0]["value"][1])

    logger.info("Scaling down %s to zero units", prometheus_app_name)
    await ops_test.model.applications[prometheus_app_name].scale(scale=0)

    logger.info("Blocking until scaled down...")
    await ops_test.model.wait_for_idle(apps=[prometheus_app_name], wait_for_exact_units=0, timeout=120)

    await ops_test.model.block_until(
        lambda: len(ops_test.model.applications[prometheus_app_name].units) == 0
    )
    logger.info("Scaling up %s units to 1", prometheus_app_name)
    await ops_test.model.applications[prometheus_app_name].scale(scale_change=1)
    await ops_test.model.wait_for_idle(apps=[prometheus_app_name], status="active", timeout=120)
    assert await check_prometheus_is_ready(ops_test, prometheus_app_name, 0)

    total1 = await run_promql(ops_test, query, prometheus_app_name)
    num_head_chunks_after = int(total1[0]["value"][1])
    assert num_head_chunks_before <= num_head_chunks_after


async def has_metric(ops_test, query: str, app_name: str) -> bool:
    # Throws if the query does not return any time series within 5 minutes,
    # and as a consequence, fails the test
    for timeseries in await run_promql(ops_test, query, app_name):
        if timeseries.get("metric"):
            return True

    return False
