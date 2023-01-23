#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

import logging

import pytest
from helpers import oci_image

logger = logging.getLogger(__name__)

prometheus_resources = {"prometheus-image": oci_image("./metadata.yaml", "prometheus-image")}


@pytest.mark.abort_on_fail
@pytest.mark.parametrize("channel", ("edge", "beta", "candidate", "stable"))
async def test_deploy_from_channel_and_upgrade_with_current(ops_test, prometheus_charm, channel):
    logger.info("Deploy charm from %s channel", channel)
    app_name = f"prom-{channel}"
    await ops_test.model.deploy(
        "ch:prometheus-k8s",
        application_name=app_name,
        channel=channel,
        trust=True,
    )
    await ops_test.model.wait_for_idle(
        status="active", timeout=300, idle_period=60, raise_on_error=False
    )

    logger.info("Upgrade %s charm to current charm", channel)
    await ops_test.model.applications[app_name].refresh(
        path=prometheus_charm,
        resources=prometheus_resources,
    )
    await ops_test.model.wait_for_idle(
        status="active", timeout=300, idle_period=60, raise_on_error=False
    )

    # Now wait for idle without `raise_on_error=False`
    await ops_test.model.wait_for_idle(status="active")
