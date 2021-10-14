#!/usr/bin/env python3
# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

import logging

import pytest

logger = logging.getLogger(__name__)


@pytest.mark.abort_on_fail
async def test_build_and_deploy_with_ubuntu_image(ops_test):
    """Test that the Prometheus charm can be deployed successfully."""
    prometheus_charm = await ops_test.build_charm(".")
    resources = {"prometheus-image": "ubuntu/prometheus:latest"}

    await ops_test.model.deploy(
        prometheus_charm, resources=resources, application_name="prometheus"
    )
    await ops_test.model.wait_for_idle(apps=["prometheus"], status="active")

    assert ops_test.model.applications["prometheus"].units[0].workload_status == "active"
