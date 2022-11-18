#!/usr/bin/env python3
# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

import asyncio
import logging

import pytest
from helpers import (
    check_prometheus_is_ready,
    get_prometheus_rules,
    oci_image,
    run_promql,
)
from pytest_operator.plugin import OpsTest

logger = logging.getLogger(__name__)

avalanche = "avalanche"
# prometheus that will consume from the app and write to the remote API
prom_write = "prometheus-write"
prom_read = "prometheus-read"  # prometheus that provides `/api/v1/write` API endpoint
local_apps = [avalanche, prom_read, prom_write]


@pytest.mark.abort_on_fail
async def test_receive_remote_write(ops_test: OpsTest, prometheus_charm):
    """Test chaining via `receive-remote-write` relation.

    When two Prometheuses are related to one another via `receive-remote-write`,
    then all the alerts from the 1st prometheus should be forwarded to the second.

    """
    await asyncio.gather(
        ops_test.model.deploy(
            prometheus_charm,
            resources={"prometheus-image": oci_image("./metadata.yaml", "prometheus-image")},
            application_name=prom_write,
            trust=True,  # otherwise errors on ghwf (persistentvolumeclaims ... is forbidden)
            series="focal",
        ),
        ops_test.model.deploy(
            prometheus_charm,
            resources={"prometheus-image": oci_image("./metadata.yaml", "prometheus-image")},
            application_name=prom_read,
            trust=True,  # otherwise errors on ghwf (persistentvolumeclaims ... is forbidden)
            series="focal",
        ),
        ops_test.model.deploy(
            "avalanche-k8s", channel="edge", application_name=avalanche, series="focal"
        ),
    )

    await ops_test.model.wait_for_idle(apps=local_apps, status="active", wait_for_units=1)
    assert await check_prometheus_is_ready(ops_test, prom_write, 0)
    assert await check_prometheus_is_ready(ops_test, prom_read, 0)

    await asyncio.gather(
        ops_test.model.add_relation(
            f"{prom_read}:receive-remote-write", f"{prom_write}:send-remote-write"
        ),
        ops_test.model.add_relation(
            f"{avalanche}:metrics-endpoint", f"{prom_write}:metrics-endpoint"
        ),
    )

    await ops_test.model.wait_for_idle(apps=local_apps, status="active", idle_period=90)

    # check that both Prometheus have avalanche metrics and both fire avalanche alert
    for app in [prom_read, prom_write]:
        assert await has_metric(
            ops_test,
            f'up{{juju_model="{ops_test.model_name}",juju_application="{avalanche}"}}',
            app,
        )

        # Note: the following depends on an avalnche alert coming from the avalanche charm
        # https://github.com/canonical/avalanche-k8s-operator/blob/main/src/prometheus_alert_rules
        prom_rules = await get_prometheus_rules(ops_test, app, 0)
        for rule in prom_rules:
            if ava_rule := rule.get("rules", {}):
                if ava_rule[0]["name"] == "AlwaysFiringDueToNumericValue":
                    assert ava_rule[0]["state"] == "firing"
                    break
        else:
            raise AssertionError("Rule was not fired")


async def has_metric(ops_test, query: str, app_name: str) -> bool:
    # Throws if the query does not return any time series within 5 minutes,
    # and as a consequence, fails the test
    for timeseries in await run_promql(ops_test, query, app_name):
        if timeseries.get("metric"):
            return True

    return False
