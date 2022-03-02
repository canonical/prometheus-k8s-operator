#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.


import logging

import pytest
from helpers import (
    IPAddressWorkaround,
    check_prometheus_is_ready,
    get_prometheus_rules,
    get_rules_for,
    oci_image,
    rebuild_prometheus_tester,
    remove_tester_alert_rule_file,
    write_tester_alert_rule_file,
)
from tenacity import RetryError, Retrying, retry_if_exception_type, stop_after_attempt

logger = logging.getLogger(__name__)

prometheus_resources = {"prometheus-image": oci_image("./metadata.yaml", "prometheus-image")}
tester_resources = {
    "prometheus-tester-image": oci_image(
        "./tests/integration/prometheus-tester/metadata.yaml", "prometheus-tester-image"
    )
}

PROMETHEUS_APP_NAME = "prometheus-k8s"
TESTER_APP_NAME = "prometheus-tester"

# Please see https://github.com/canonical/prometheus-k8s-operator/issues/197
TIMEOUT = 1000

MISSING_TARGET_RULE = """alert: PrometheusTargetMissing
expr: up == 0
for: 0m
labels:
  severity: critical
annotations:
  summary: "Prometheus target missing (instance {{ $labels.instance }})"
  description: "A Prometheus target has disappeared. An exporter might be crashed."
"""


@pytest.mark.abort_on_fail
async def test_deploy_from_edge_and_upgrade_from_local_path(ops_test, prometheus_charm):
    """Build the charm-under-test and deploy it together with related charms.

    Assert on the unit status before any relations/configurations take place.
    """
    async with IPAddressWorkaround(ops_test):
        logger.debug("deploy charm from charmhub")
        await ops_test.model.deploy(
            f"ch:{PROMETHEUS_APP_NAME}", application_name=PROMETHEUS_APP_NAME, channel="edge"
        )
        await ops_test.model.wait_for_idle(
            apps=[PROMETHEUS_APP_NAME], status="active", timeout=TIMEOUT
        )

        logger.debug("upgrade deployed charm with local charm %s", prometheus_charm)
        await ops_test.model.applications[PROMETHEUS_APP_NAME].refresh(
            path=prometheus_charm, resources=prometheus_resources
        )
        await ops_test.model.wait_for_idle(
            apps=[PROMETHEUS_APP_NAME], status="active", timeout=TIMEOUT
        )
        await check_prometheus_is_ready(ops_test, PROMETHEUS_APP_NAME, 0)


async def test_upgrading_rules_provider_also_updates_rule_files(ops_test, prometheus_tester_charm):
    """Ensure scrape alert rules can be updated.

    This test upgrades the metrics provider charm and checks that
    updates to alert rules are propagated correctly.
    """
    await ops_test.model.deploy(
        prometheus_tester_charm, resources=tester_resources, application_name=TESTER_APP_NAME
    )
    await ops_test.model.wait_for_idle(apps=[TESTER_APP_NAME], status="active")
    await ops_test.model.block_until(
        lambda: len(ops_test.model.applications[TESTER_APP_NAME].units) > 0
    )
    assert ops_test.model.applications[TESTER_APP_NAME].units[0].workload_status == "active"

    await ops_test.model.add_relation(PROMETHEUS_APP_NAME, TESTER_APP_NAME)
    await ops_test.model.wait_for_idle(
        apps=[PROMETHEUS_APP_NAME, TESTER_APP_NAME], status="active"
    )

    # Check only one alert rule exists
    tester_rules = []
    for attempt in Retrying(
        retry=retry_if_exception_type(AssertionError), stop=stop_after_attempt(3)
    ):
        try:
            with attempt:
                rules_with_relation = await get_prometheus_rules(ops_test, PROMETHEUS_APP_NAME, 0)
                tester_rules = get_rules_for(TESTER_APP_NAME, rules_with_relation)
                assert len(tester_rules) == 1
        except RetryError:
            pass

    # Add new alert rule, rebuild and refresh prometheus tester charm
    write_tester_alert_rule_file(MISSING_TARGET_RULE, "target_missing.rule")
    tester_charm = await rebuild_prometheus_tester(ops_test)
    await ops_test.model.applications[TESTER_APP_NAME].refresh(
        path=tester_charm, resources=tester_resources
    )
    remove_tester_alert_rule_file("target_missing.rule")

    await ops_test.model.wait_for_idle(
        apps=[PROMETHEUS_APP_NAME, TESTER_APP_NAME], status="active"
    )

    # Check there are now two alert rules
    tester_rules = []
    for attempt in Retrying(
        retry=retry_if_exception_type(AssertionError), stop=stop_after_attempt(3)
    ):
        try:
            with attempt:
                rules_with_relation = await get_prometheus_rules(ops_test, PROMETHEUS_APP_NAME, 0)
                tester_rules = get_rules_for(TESTER_APP_NAME, rules_with_relation)
                assert len(tester_rules) == 2
        except RetryError:
            pass
