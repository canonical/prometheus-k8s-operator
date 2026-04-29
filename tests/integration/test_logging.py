#!/usr/bin/env python3
# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
from pathlib import Path

import jubilant
import pytest
import yaml
from helpers import oci_image

logger = logging.getLogger(__name__)

METADATA = yaml.safe_load(Path("./charmcraft.yaml").read_text())
APP_NAME = "prometheus"
LOKI_APP_NAME = "loki"
PROMETHEUS_RESOURCES = {"prometheus-image": oci_image("./charmcraft.yaml", "prometheus-image")}


@pytest.mark.abort_on_fail
async def test_logging_integration(ops_test, prometheus_charm):
    """Deploy prometheus and loki, integrate via logging, and verify the relation is active."""
    juju = jubilant.Juju(model=ops_test.model.name)

    # Deploy Prometheus
    juju.deploy(prometheus_charm, app=APP_NAME, resources=PROMETHEUS_RESOURCES, trust=True)

    # Deploy Loki
    juju.deploy(charm="loki-k8s", app=LOKI_APP_NAME, channel="1/stable", trust=True)

    # Wait for apps to settle
    juju.wait(
        lambda status: jubilant.all_active(status, APP_NAME, LOKI_APP_NAME),
        delay=5,
        timeout=300,
    )

    # Integrate prometheus with loki via logging relation
    juju.integrate(f"{APP_NAME}:logging", f"{LOKI_APP_NAME}:logging")

    # Wait for the integration to settle
    juju.wait(
        lambda status: jubilant.all_active(status, APP_NAME, LOKI_APP_NAME),
        delay=5,
        timeout=300,
    )

    # Verify the relation is established
    status = juju.status()
    assert jubilant.all_active(status, APP_NAME, LOKI_APP_NAME)
