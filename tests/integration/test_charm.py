#!/usr/bin/env python3
# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

import logging

import pytest

logger = logging.getLogger(__name__)


@pytest.mark.abort_on_fail
@pytest.mark.parametrize("oci_image", ["ubuntu/prometheus:latest", "prom/prometheus:latest"])
async def test_build_and_deploy_with_alternative_images(ops_test, prometheus_charm, oci_image):
    """Test that the Prometheus charm can be deployed successfully."""
    resources = {"prometheus-image": oci_image}
    app_name = "prometheus-" + oci_image.split("/")[0]

    await ops_test.model.deploy(prometheus_charm, resources=resources, application_name=app_name)
    await ops_test.model.wait_for_idle(apps=[app_name], status="active")

    assert ops_test.model.applications[app_name].units[0].workload_status == "active"

    await ops_test.model.applications[app_name].remove()
