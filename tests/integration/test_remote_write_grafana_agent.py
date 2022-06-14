#!/usr/bin/env python3
# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

import asyncio
import logging

import pytest
from helpers import check_prometheus_is_ready, oci_image, run_promql

logger = logging.getLogger(__name__)
prometheus_resources = {"prometheus-image": oci_image("./metadata.yaml", "prometheus-image")}


@pytest.mark.abort_on_fail
async def test_remote_write_with_grafana_agent(ops_test, prometheus_charm):
    """Test that Prometheus can be related with the Grafana Agent over remote_write."""
    prometheus_name = "prometheus"
    agent_name = "grafana-agent"
    apps = [prometheus_name, agent_name]

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
    )

    await ops_test.model.wait_for_idle(apps=apps, status="active", wait_for_units=1)
    assert await check_prometheus_is_ready(ops_test, prometheus_name, 0)

    await ops_test.model.add_relation(
        f"{prometheus_name}:receive-remote-write", f"{agent_name}:send-remote-write"
    )

    # A considerable idle_period is needed to guarantee metrics show up in prometheus
    # (60 sec was not enough).
    await ops_test.model.wait_for_idle(apps=apps, status="active", idle_period=90)

    assert await has_metric(
        ops_test,
        f'up{{juju_model="{ops_test.model_name}",juju_application="{agent_name}"}}',
        prometheus_name,
    )


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

    await ops_test.model.applications[prometheus_app_name].scale(scale_change=0)
    await ops_test.model.block_until(
        lambda: len(ops_test.model.applications[prometheus_app_name].units) == 0
    )
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
