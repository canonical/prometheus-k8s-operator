#!/usr/bin/env python3
# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

import asyncio
import logging

import pytest
from helpers import (
    check_prometheus_is_ready,
    initial_workload_is_ready,
    oci_image,
    run_promql,
)

logger = logging.getLogger(__name__)


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
        ),
        ops_test.model.deploy(
            "grafana-agent-k8s",
            application_name=agent_name,
            channel="edge",
        ),
    )

    await ops_test.model.wait_for_idle(apps=apps, status="active")
    assert initial_workload_is_ready(ops_test, apps)
    assert check_prometheus_is_ready(ops_test, prometheus_name, 0)

    await ops_test.model.add_relation(prometheus_name, agent_name)
    await ops_test.model.wait_for_idle(apps=apps, status="active", idle_period=60)

    await has_metric(
        ops_test,
        f'up{{juju_model="{ops_test.model_name}",juju_application="{agent_name}"}}',
        prometheus_name,
    )


async def has_metric(ops_test, query: str, app_name: str) -> bool:
    # Throws if the query does not return any time series within 5 minutes,
    # and as a consequence, fails the test
    for timeseries in await run_promql(ops_test, query, app_name):
        if timeseries.get("metric"):
            return True

    raise Exception
