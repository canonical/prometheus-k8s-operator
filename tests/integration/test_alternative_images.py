#!/usr/bin/env python3
# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

import pytest
from helpers import check_prometheus_is_ready, oci_image

tester_resources = {
    "prometheus-tester-image": oci_image(
        "./tests/integration/prometheus-tester/metadata.yaml", "prometheus-tester-image"
    )
}
prometheus_resources = {"prometheus-image": oci_image("./metadata.yaml", "prometheus-image")}


@pytest.mark.abort_on_fail
async def test_build_and_deploy_with_alternative_images(ops_test, prometheus_charm):
    """Test that the Prometheus charm can be deployed successfully."""
    app_name = "prometheus-ubuntu"

    await ops_test.model.deploy(
        prometheus_charm, resources=prometheus_resources, application_name=app_name
    )
    await ops_test.model.wait_for_idle(apps=[app_name], status="active")
    await ops_test.model.block_until(lambda: len(ops_test.model.applications[app_name].units) > 0)

    assert ops_test.model.applications[app_name].units[0].workload_status == "active"

    await check_prometheus_is_ready(ops_test, app_name, 0)

    await ops_test.model.applications[app_name].remove()
    await ops_test.model.block_until(lambda: app_name not in ops_test.model.applications)
    await ops_test.model.reset()
