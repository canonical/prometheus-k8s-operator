#!/usr/bin/env python3
# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""Integration tests for the logging (log forwarding) relation."""

import asyncio
import logging
from pathlib import Path

import pytest
import requests
import yaml
from helpers import oci_image, unit_address
from pytest_operator.plugin import OpsTest
from tenacity import retry, stop_after_attempt, wait_fixed

logger = logging.getLogger(__name__)

METADATA = yaml.safe_load(Path("./charmcraft.yaml").read_text())
APP_NAME = "prometheus"
LOKI_APP_NAME = "loki"
PROMETHEUS_RESOURCES = {"prometheus-image": oci_image("./charmcraft.yaml", "prometheus-image")}


@pytest.mark.abort_on_fail
async def test_build_and_deploy(ops_test: OpsTest, prometheus_charm):
    """Deploy prometheus and loki, then wait for active status."""
    assert ops_test.model
    await asyncio.gather(
        ops_test.model.deploy(
            prometheus_charm,
            resources=PROMETHEUS_RESOURCES,
            application_name=APP_NAME,
            trust=True,
        ),
        ops_test.model.deploy("loki-k8s", LOKI_APP_NAME, channel="dev/edge", trust=True),
    )
    await ops_test.model.wait_for_idle(apps=[APP_NAME, LOKI_APP_NAME], status="active")


@pytest.mark.abort_on_fail
async def test_logging_integration(ops_test: OpsTest):
    """Integrate prometheus with loki via the logging relation."""
    assert ops_test.model
    await ops_test.model.add_relation(f"{APP_NAME}:logging", f"{LOKI_APP_NAME}:logging")
    await ops_test.model.wait_for_idle(apps=[APP_NAME, LOKI_APP_NAME], status="active")


@retry(wait=wait_fixed(15), stop=stop_after_attempt(20))
async def test_logs_are_forwarded_to_loki(ops_test: OpsTest):
    """Verify that prometheus logs are present in Loki."""
    loki_address = await unit_address(ops_test, LOKI_APP_NAME, 0)
    url = f"http://{loki_address}:3100/loki/api/v1/query_range"
    response = requests.get(url, params={"query": f'{{juju_application="{APP_NAME}"}}'})
    response.raise_for_status()

    result = response.json().get("data", {}).get("result", [])
    assert len(result) > 0, f"No log entries found in Loki for {APP_NAME}"
