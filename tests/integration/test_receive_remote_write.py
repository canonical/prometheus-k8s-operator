#!/usr/bin/env python3
# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

import asyncio
import logging

import pytest
from helpers import (
    check_prometheus_is_ready,
    get_prometheus_rules,
    has_metric,
    oci_image,
)
from pytest_operator.plugin import OpsTest

logger = logging.getLogger(__name__)

avalanche = "avalanche"
# prometheus that will consume from the app and write to the remote API
prom_send = "prometheus-sender"
prom_receive = "prometheus-receiver"  # prometheus that provides `/api/v1/write` API endpoint
local_apps = [avalanche, prom_receive, prom_send]


@pytest.mark.abort_on_fail
async def test_receive_remote_write(ops_test: OpsTest, prometheus_charm):
    """Test chaining via `receive-remote-write` relation.

    When two Prometheuses are related to one another via `receive-remote-write`,
    then all the alerts from the 1st prometheus should be forwarded to the second.

    Prometheus (prometheus-receiver) that provides `receive-remote-write` relation
    provides `/api/v1/write` API endpoint that will be consumed by Prometheus (prometheus-sender)
    that requires `send-remote-write` relation. Later, `prometheus-sender` will write all the data
    it receives from applications to the provided API point of `prometheus-receiver`.

    """
    await asyncio.gather(
        ops_test.model.deploy(
            prometheus_charm,
            resources={"prometheus-image": oci_image("./metadata.yaml", "prometheus-image")},
            application_name=prom_send,
            trust=True,  # otherwise errors on ghwf (persistentvolumeclaims ... is forbidden)
            series="focal",
        ),
        ops_test.model.deploy(
            prometheus_charm,
            resources={"prometheus-image": oci_image("./metadata.yaml", "prometheus-image")},
            application_name=prom_receive,
            trust=True,  # otherwise errors on ghwf (persistentvolumeclaims ... is forbidden)
            series="focal",
        ),
        ops_test.model.deploy(
            "avalanche-k8s", channel="edge", application_name=avalanche, series="focal"
        ),
    )

    await ops_test.model.wait_for_idle(apps=local_apps, status="active", wait_for_units=1)
    assert await check_prometheus_is_ready(ops_test, prom_send, 0)
    assert await check_prometheus_is_ready(ops_test, prom_receive, 0)

    await asyncio.gather(
        ops_test.model.add_relation(
            f"{prom_receive}:receive-remote-write", f"{prom_send}:send-remote-write"
        ),
        ops_test.model.add_relation(
            f"{avalanche}:metrics-endpoint", f"{prom_send}:metrics-endpoint"
        ),
    )

    await ops_test.model.wait_for_idle(apps=local_apps, status="active", idle_period=90)

    # check that both Prometheus have avalanche metrics and both fire avalanche alert
    for app in [prom_receive, prom_send]:
        assert await has_metric(
            ops_test,
            f'up{{juju_model="{ops_test.model_name}",juju_application="{avalanche}"}}',
            app,
        )

        # Note: the following depends on an avalanche alert coming from the avalanche charm
        # https://github.com/canonical/avalanche-k8s-operator/blob/main/src/prometheus_alert_rules
        prom_rules_list = await get_prometheus_rules(ops_test, app, 0)
        for rules_dict in prom_rules_list:
            if rules_list := rules_dict.get("rules", []):
                for rule in rules_list:
                    if rule["name"] == "AlwaysFiringDueToNumericValue":
                        assert rule["state"] == "firing"
                        break
                else:
                    # "AlwaysFiringDueToNumericValue" was not found, go to next rules_dict
                    continue
                break
        else:
            raise AssertionError(
                f"The 'AlwaysFiringDueToNumericValue' avalanche alert was not found in prometheus '{app}'"
            )
