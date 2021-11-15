#!/usr/bin/env python3
# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

import logging

import pytest
import tenacity
import yaml
from helpers import unit_address
from workload import Prometheus

logger = logging.getLogger(__name__)


def container_images(metadata_file="./metadata.yaml"):
    with open(metadata_file) as f:
        manifest = yaml.safe_load(f)

        if "resources" not in manifest:
            raise ValueError("The 'metadata.yaml' file declares no resources")

        resources = {}
        for resource_name, resource_spec in manifest.get("resources").items():
            if resource_spec["type"] == "oci-image":
                resources[resource_name] = resource_spec["upstream-source"]

        return resources


@pytest.mark.abort_on_fail
async def test_remote_write_with_grafana_agent(ops_test):
    """Test that Prometheus can be related with the Grafana Agent over remote_write."""
    charms = await ops_test.build_charms(".")

    prometheus_application_name = "prometheus"
    grafana_agent_application_name = "grafana-agent"

    await ops_test.model.deploy(
        charms["prometheus-k8s"],
        resources=container_images(),
        application_name=prometheus_application_name,
    )
    await ops_test.model.deploy(
        "grafana-agent-k8s",
        application_name=grafana_agent_application_name,
        channel="edge",
    )

    await ops_test.model.add_relation(prometheus_application_name, grafana_agent_application_name)

    await ops_test.model.wait_for_idle(apps=[prometheus_application_name], status="active")
    await ops_test.model.wait_for_idle(apps=[grafana_agent_application_name], status="active")

    assert (
        ops_test.model.applications[prometheus_application_name].units[0].workload_status
        == "active"
    )
    assert (
        ops_test.model.applications[grafana_agent_application_name].units[0].workload_status
        == "active"
    )

    host = await get_unit_address(ops_test, prometheus_application_name)

    prometheus = Prometheus(host=host)

    while not await check_if_prometheus_ready(prometheus):
        pass

    promql_query = f'up{{juju_model="{ops_test.model_name}",juju_application="{grafana_agent_application_name}"}}'

    while True:
        for timeseries in await run_promql(promql_query):
            if metric := timeseries.get("metric"):
                logger.info(f'Found Grafana Agent "up" metric: {metric}')
                return


@tenacity.retry(wait=tenacity.wait_fixed(2))
async def get_unit_address(ops_test, application_name, unit_index=0):
    return await unit_address(ops_test, application_name, unit_index)


@tenacity.retry(wait=tenacity.wait_fixed(2))
async def check_if_prometheus_ready(prometheus: Prometheus):
    return await prometheus.is_ready()


@tenacity.retry(wait=tenacity.wait_fixed(2))
async def run_promql(prometheus: Prometheus, promql_query):
    return await prometheus.run_promql(promql_query)
