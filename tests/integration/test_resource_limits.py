#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

"""This test module tests prometheus resource limits on startup and after config-changed."""

import logging
from pathlib import Path

import pytest
import yaml
from helpers import check_prometheus_is_ready, oci_image
from lightkube import Client
from lightkube.resources.core_v1 import Pod
from pytest_operator.plugin import OpsTest

logger = logging.getLogger(__name__)

METADATA = yaml.safe_load(Path("./metadata.yaml").read_text())
app_name = METADATA["name"]
resources = {"prometheus-image": oci_image("./metadata.yaml", "prometheus-image")}


async def test_setup_env(ops_test: OpsTest):
    await ops_test.model.set_config({"logging-config": "<root>=WARNING; unit=DEBUG"})


@pytest.mark.abort_on_fail
async def test_build_and_deploy(ops_test: OpsTest, prometheus_charm):
    """Build the charm-under-test and deploy it."""
    await ops_test.model.deploy(
        prometheus_charm,
        resources=resources,
        application_name=app_name,
        trust=True,
    )

    await ops_test.model.wait_for_idle(status="active", timeout=600)


@pytest.mark.abort_on_fail
async def test_default_resource_limits_applied(ops_test: OpsTest):
    client = Client()
    pod = client.get(Pod, name=f"{app_name}-0", namespace=ops_test.model_name)
    podspec = next(iter(filter(lambda ctr: ctr.name == "prometheus", pod.spec.containers)))
    default_limits = {"cpu": "1", "memory": "1Gi"}
    assert podspec.resources.limits == default_limits
    assert podspec.resources.requests == default_limits
    assert await check_prometheus_is_ready(ops_test, app_name, 0)


@pytest.mark.abort_on_fail
@pytest.mark.parametrize("cpu,memory", [("900m", "0.9Gi"), ("0.30000000000000004", "0.9G")])
async def test_resource_limits_match_config(ops_test: OpsTest, cpu, memory):
    custom_limits = {"cpu": cpu, "memory": memory}
    await ops_test.model.applications[app_name].set_config(custom_limits)
    await ops_test.model.wait_for_idle(status="active", timeout=300)

    # Not comparing limits (for now) because the strings may differ (0.9G vs 900Mi)
    # Comparison is done inside the k8s resource patch.
    # client = Client()
    # pod = client.get(Pod, name=f"{app_name}-0", namespace=ops_test.model_name)
    # podspec = next(iter(filter(lambda ctr: ctr.name == "prometheus", pod.spec.containers)))
    # assert podspec.resources.limits == custom_limits
    # assert podspec.resources.requests == custom_limits

    assert await check_prometheus_is_ready(ops_test, app_name, 0)


@pytest.mark.abort_on_fail
@pytest.mark.parametrize("cpu,memory", [("-1", "1Gi"), ("1", "-1Gi"), ("4x", "1Gi"), ("1", "1Gx")])
async def test_invalid_resource_limits_put_charm_in_blocked_status(ops_test: OpsTest, cpu, memory):
    custom_limits = {"cpu": cpu, "memory": memory}
    await ops_test.model.applications[app_name].set_config(custom_limits)
    await ops_test.model.wait_for_idle(status="blocked", timeout=300)
    assert await check_prometheus_is_ready(ops_test, app_name, 0)


@pytest.mark.abort_on_fail
async def test_charm_recovers_from_invalid_resource_limits(ops_test: OpsTest):
    custom_limits = {"cpu": "1", "memory": "1Gi"}
    await ops_test.model.applications[app_name].set_config(custom_limits)
    await ops_test.model.wait_for_idle(status="active", timeout=300)
    assert await check_prometheus_is_ready(ops_test, app_name, 0)
