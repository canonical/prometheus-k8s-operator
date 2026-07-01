#!/usr/bin/env python3
# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Integration tests for the logging (log forwarding) relation."""

import logging
from pathlib import Path

import jubilant
import pytest
import requests
import yaml
from helpers import oci_image
from tenacity import retry, stop_after_attempt, wait_fixed

logger = logging.getLogger(__name__)

METADATA = yaml.safe_load(Path("./charmcraft.yaml").read_text())
APP_NAME = "prometheus"
LOKI_APP_NAME = "loki"
PROMETHEUS_RESOURCES = {"prometheus-image": oci_image("./charmcraft.yaml", "prometheus-image")}


@pytest.mark.abort_on_fail
def test_build_and_deploy(juju: jubilant.Juju, prometheus_charm):
    """Deploy prometheus and loki, then wait for active status."""
    juju.deploy(
        prometheus_charm,
        resources=PROMETHEUS_RESOURCES,
        app=APP_NAME,
        trust=True,
    )
    juju.deploy("loki-k8s", LOKI_APP_NAME, channel="dev/edge", trust=True)
    juju.wait(
        lambda status: jubilant.all_active(status, APP_NAME, LOKI_APP_NAME)
        and jubilant.all_agents_idle(status, APP_NAME, LOKI_APP_NAME),
        timeout=600,
        delay=5.0,
    )


@pytest.mark.abort_on_fail
def test_logging_integration(juju: jubilant.Juju):
    """Integrate prometheus with loki via the logging relation."""
    juju.integrate(f"{APP_NAME}:logging", f"{LOKI_APP_NAME}:logging")
    juju.wait(
        lambda status: jubilant.all_active(status, APP_NAME, LOKI_APP_NAME)
        and jubilant.all_agents_idle(status, APP_NAME, LOKI_APP_NAME),
        timeout=600,
        delay=5.0,
    )


@retry(wait=wait_fixed(15), stop=stop_after_attempt(20))
def test_logs_are_forwarded_to_loki(juju: jubilant.Juju):
    """Verify that prometheus logs are present in Loki."""
    loki_address = juju.status().apps[LOKI_APP_NAME].units[f"{LOKI_APP_NAME}/0"].address
    url = f"http://{loki_address}:3100/loki/api/v1/query_range"
    response = requests.get(url, params={"query": f'{{juju_application="{APP_NAME}"}}'})
    response.raise_for_status()

    result = response.json().get("data", {}).get("result", [])
    assert len(result) > 0, f"No log entries found in Loki for {APP_NAME}"
