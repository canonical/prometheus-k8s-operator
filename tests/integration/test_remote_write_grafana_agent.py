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

    await ops_test.model.add_relation(prometheus_name, agent_name)

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
    sum0 = int(total0[0]["value"][1])

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
    assert check_prometheus_is_ready(ops_test, prometheus_app_name, 0)

    total1 = await run_promql(ops_test, query, prometheus_app_name)
    sum1 = int(total1[0]["value"][1])
    assert sum0 <= sum1


@pytest.mark.abort_on_fail
async def test_check_data_persist_on_charm_upgrade(ops_test, prometheus_charm):
    prometheus_app_name = "prometheus"
    agent_name = "grafana-agent"
    apps = [prometheus_app_name, agent_name]
    query = "prometheus_tsdb_head_chunks_created_total{}"
    total0 = await run_promql(ops_test, query, prometheus_app_name)
    sum0 = int(total0[0]["value"][1])

    logger.debug("upgrade deployed charm with local charm %s", prometheus_charm)
    await ops_test.model.applications[prometheus_app_name].refresh(
        path=prometheus_charm, resources=prometheus_resources
    )
    await ops_test.model.wait_for_idle(apps=apps, status="active", timeout=300, idle_period=60)
    assert check_prometheus_is_ready(ops_test, prometheus_app_name, 0)

    total1 = await run_promql(ops_test, query, prometheus_app_name)
    sum1 = int(total1[0]["value"][1])
    assert sum0 <= sum1


async def has_metric(ops_test, query: str, app_name: str) -> bool:
    # Throws if the query does not return any time series within 5 minutes,
    # and as a consequence, fails the test
    for timeseries in await run_promql(ops_test, query, app_name):
        if timeseries.get("metric"):
            return True

    return False
