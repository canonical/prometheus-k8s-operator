#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import logging

import pytest
import yaml
from helpers import (
    check_prometheus_is_ready,
    get_prometheus_rules,
    get_rules_for,
    get_workload_file,
    oci_image,
    run_promql,
)

from .juju import Juju

logger = logging.getLogger(__name__)

PROMETHEUS_CONFIG = "/etc/prometheus/prometheus.yml"
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
async def test_deploy_charm(prometheus_tester_charm, prometheus_charm, prometheus_oci_image):
    """Build the charm-under-test and deploy it together with related charms.

    Assert on the unit status before any relations/configurations take place.
    """
    Juju.deploy(prometheus_charm, alias=prometheus_app_name, resources=prometheus_resources)
    Juju.deploy(prometheus_tester_charm, alias=tester_app_name, resources=tester_resources)
    Juju.integrate(
        f"{prometheus_app_name}:metrics-endpoint", f"{tester_app_name}:metrics-endpoint"
    )
    Juju.wait_for_idle(app_names, timeout=300)

    # Check only one alert rule exists
    rules_with_relation = get_prometheus_rules(prometheus_app_name, 0)
    tester_rules = get_rules_for(tester_app_name, rules_with_relation)

    assert len(tester_rules) == 1


@pytest.mark.abort_on_fail
async def test_files_are_retained_after_refresh(ops_test, prometheus_charm):
    # Get config from before the upgrade
    def get_config():
        return yaml.safe_load(
            get_workload_file(
                ops_test.model_name, prometheus_app_name, 0, "prometheus", PROMETHEUS_CONFIG
            )
        )

    config_before = get_config()

    logger.debug("Refreshing charm")
    await ops_test.model.applications[prometheus_app_name].refresh(
        path=prometheus_charm, resources=prometheus_resources
    )
    await ops_test.model.wait_for_idle(
        apps=app_names, status="active", timeout=300, idle_period=60
    )
    assert await check_prometheus_is_ready(ops_test, prometheus_app_name, 0)

    # Get config from after the upgrade
    config_after = get_config()
    assert config_before == config_after

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
    await ops_test.model.wait_for_idle(
        apps=app_names, status="active", timeout=300, idle_period=60
    )
    assert await check_prometheus_is_ready(ops_test, prometheus_app_name, 0)

    total1 = await run_promql(ops_test, query, prometheus_app_name)
    sum1 = int(total1[0]["value"][1])
    assert sum0 <= sum1
