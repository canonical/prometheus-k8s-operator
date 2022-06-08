#!/usr/bin/env python3
# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
from pathlib import Path

import pytest
import yaml
from helpers import unit_address
from pytest_operator.plugin import OpsTest
from workload import Prometheus

logger = logging.getLogger(__name__)

METADATA = yaml.safe_load(Path("./metadata.yaml").read_text())


@pytest.mark.abort_on_fail
async def test_charm_successfully_relates_to_avalanche(ops_test: OpsTest, prometheus_charm):
    """Deploy the charm-under-test together with related charms."""
    await ops_test.model.set_config({"logging-config": "<root>=WARNING; unit=DEBUG"})
    resources = {"prometheus-image": METADATA["resources"]["prometheus-image"]["upstream-source"]}

    # deploy prometheus
    await ops_test.model.deploy(
        prometheus_charm,
        resources=resources,
        application_name="prom",
        trust=True,  # otherwise errors on ghwf (persistentvolumeclaims ... is forbidden)
    )
    await ops_test.model.wait_for_idle(apps=["prom"], status="active")

    # deploy avalanche
    av_config = {"metric_count": 50, "series_count": 1, "value_interval": 3600}
    await ops_test.model.deploy(
        "ch:avalanche-k8s", application_name="av", channel="edge", config=av_config
    )
    await ops_test.model.wait_for_idle(apps=["av"], status="active")

    await ops_test.model.add_relation("prom:receive-remote-write", "av")
    await ops_test.model.wait_for_idle(apps=["av", "prom"], status="active", idle_period=60)

    cmd = [
        "microk8s.kubectl",
        "logs",
        "-n",
        ops_test.model_name,
        "av-0",
        "-c",
        "avalanche",
    ]

    _, stdout, stderr = await ops_test.run(*cmd)
    logger.info("stdout: %s", stdout)
    logger.info("stderr: %s", stderr)


@pytest.mark.xfail
async def test_avalanche_metrics_are_ingested_by_prometheus(ops_test: OpsTest):
    address = await unit_address(ops_test, "prom", 0)
    labels = await Prometheus(address).labels()
    assert "label_key_kkkkk_0" in labels


@pytest.mark.xfail
async def test_avalanche_alerts_ingested_by_prometheus(ops_test: OpsTest):
    address = await unit_address(ops_test, "prom", 0)
    assert len(await Prometheus(address).rules("alert")) > 0


@pytest.mark.xfail
async def test_avalanche_always_firing_alarms_are_firing(ops_test: OpsTest):
    address = await unit_address(ops_test, "prom", 0)
    alerts = await Prometheus(address).alerts()
    for alert in alerts:
        assert "AlwaysFiring" in alert["labels"]["alertname"]
        assert alert["state"] == "firing"
