#!/usr/bin/env python3
# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
from pathlib import Path

import pytest
import yaml
from helpers import IPAddressWorkaround, unit_address  # type: ignore[import]
from pytest_operator.plugin import OpsTest
from tenacity import retry, stop_after_attempt, wait_exponential
from workload import Prometheus

logger = logging.getLogger(__name__)

METADATA = yaml.safe_load(Path("./metadata.yaml").read_text())

# Some tests need to be retried, for example the alert does not fire as soon as a remote-write
# relation is formed. The same could be achieved by `utils.block_until_with_coroutine`, but the
# disadvantage is that the log would be very vague: it would show "asyncio.exceptions.TimeoutError"
# without pytest printing out the nicely formatted mismatch between left and right.
# By using tenacity the test body can be kept short, and the logs descriptive.
tenacious = retry(wait=wait_exponential(multiplier=1, min=10, max=60), stop=stop_after_attempt(7))


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
    av_config = {"metric_count": 50, "series_count": 1, "value_interval": 3600}
    await ops_test.model.deploy(
        "ch:avalanche-k8s", application_name="av", channel="edge", config=av_config
    )
    await ops_test.model.wait_for_idle(apps=["av"], status="active")


@pytest.mark.abort_on_fail
async def test_charm_successfully_relates_to_avalanche(ops_test: OpsTest):
    await ops_test.model.add_relation("prom:receive-remote-write", "av:receive-remote-write")
    await ops_test.model.wait_for_idle(apps=["av", "prom"], status="active")

    cmd = [
        "microk8s.kubectl",
        "logs",
        "-n",
        ops_test.model_name,
        "av-0",
        "-c",
        "avalanche",
    ]

    retcode, stdout, stderr = await ops_test.run(*cmd)
    logger.info("stdout: %s", stdout)
    logger.info("stderr: %s", stderr)


@tenacious
async def test_avalanche_metrics_are_ingested_by_prometheus(ops_test: OpsTest):
    address = await unit_address(ops_test, "prom", 0)
    labels = await Prometheus(address).labels()
    assert "label_key_kkkkk_0" in labels


@pytest.mark.abort_on_fail
@tenacious
async def test_avalanche_alerts_ingested_by_prometheus(ops_test: OpsTest):
    address = await unit_address(ops_test, "prom", 0)
    assert len(await Prometheus(address).rules("alert")) > 0


@tenacious
async def test_avalanche_always_firing_alarm_is_firing(ops_test: OpsTest):
    address = await unit_address(ops_test, "prom", 0)
    alert = (await Prometheus(address).alerts())[0]  # there is only one alert
    assert alert["labels"]["alertname"] == "AlwaysFiring"
    assert alert["state"] == "firing"
