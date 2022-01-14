#!/usr/bin/env python3
# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.


import logging
from pathlib import Path

import pytest
import yaml
from helpers import IPAddressWorkaround, unit_address  # type: ignore[import]
from juju import utils
from pytest_operator.plugin import OpsTest
from workload import Prometheus

log = logging.getLogger(__name__)

METADATA = yaml.safe_load(Path("./metadata.yaml").read_text())


@pytest.mark.abort_on_fail
async def test_build_and_deploy(ops_test: OpsTest, prometheus_charm):
    """Deploy the charm-under-test together with related charms."""
    await ops_test.model.set_config({"logging-config": "<root>=WARNING; unit=DEBUG"})
    resources = {"prometheus-image": METADATA["resources"]["prometheus-image"]["upstream-source"]}

    # deploy prometheus
    async with IPAddressWorkaround(ops_test):
        await ops_test.model.deploy(prometheus_charm, resources=resources, application_name="prom")
        await ops_test.model.wait_for_idle(apps=["prom"], status="active")

    # deploy avalanche
    await ops_test.model.deploy("ch:avalanche-k8s", application_name="av", channel="edge")
    await ops_test.model.wait_for_idle(apps=["av"], status="active")


@pytest.mark.abort_on_fail
async def test_charm_successfully_relates_to_avalanche(ops_test: OpsTest):
    await ops_test.model.add_relation("prom:receive-remote-write", "av:receive-remote-write")
    await ops_test.model.wait_for_idle(apps=["av", "prom"], status="active")


async def test_avalanche_metrics_are_ingested_by_prometheus(ops_test: OpsTest):
    address = await unit_address(ops_test, "prom", 0)

    async def prometheus_labels_contain_avalanche_labels() -> bool:
        return "label_key_kkkkk_0" in await Prometheus(address).labels()

    await utils.block_until_with_coroutine(prometheus_labels_contain_avalanche_labels, timeout=60)


@pytest.mark.abort_on_fail
async def test_avalanche_alerts_ingested_by_prometeus(ops_test: OpsTest):
    address = await unit_address(ops_test, "prom", 0)

    async def prometheus_alerts_contain_avalanche_alerts() -> bool:
        return len(await Prometheus(address).rules("alert")) > 0

    await utils.block_until_with_coroutine(prometheus_alerts_contain_avalanche_alerts, timeout=60)


async def test_avalanche_always_firing_alarm_is_firing(ops_test: OpsTest):
    address = await unit_address(ops_test, "prom", 0)

    async def avalanche_alert_is_firing() -> bool:
        if alerts := await Prometheus(address).alerts():
            alert = alerts[0]  # there is only one alert
            return alert["labels"]["alertname"] == "AlwaysFiring" and alert["state"] == "firing"
        return False

    await utils.block_until_with_coroutine(avalanche_alert_is_firing, timeout=60)
