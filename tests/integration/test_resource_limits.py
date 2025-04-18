#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

"""This test module tests prometheus resource limits on startup and after config-changed."""

import logging
from pathlib import Path

import pytest
import yaml
from helpers import check_prometheus_is_ready, get_podspec, oci_image
from lightkube.utils.quantity import equals_canonically
from pytest_operator.plugin import OpsTest

logger = logging.getLogger(__name__)

METADATA = yaml.safe_load(Path("./charmcraft.yaml").read_text())
app_name = METADATA["name"]
resources = {"prometheus-image": oci_image("./charmcraft.yaml", "prometheus-image")}

# GitHub runner is 2cpu7gb and occasionally times out when using 300 sec.
deploy_timeout = 600
resched_timeout = 600

default_limits = None
default_requests = {"cpu": "0.25", "memory": "200Mi"}


async def test_setup_env(ops_test: OpsTest):
    assert ops_test.model
    await ops_test.model.set_config({"logging-config": "<root>=WARNING; unit=DEBUG"})


@pytest.mark.abort_on_fail
async def test_build_and_deploy(ops_test: OpsTest, prometheus_charm):
    """Build the charm-under-test and deploy it."""
    assert ops_test.model
    await ops_test.model.deploy(
        prometheus_charm,
        resources=resources,
        application_name=app_name,
        trust=True,
    )

    await ops_test.model.wait_for_idle(
        status="active", timeout=deploy_timeout, raise_on_error=False
    )
    await ops_test.model.wait_for_idle(status="active")


@pytest.mark.abort_on_fail
async def test_default_resource_limits_applied(ops_test: OpsTest):
    podspec = get_podspec(ops_test, app_name, "prometheus")
    assert podspec.resources
    assert equals_canonically(podspec.resources.limits, default_limits)
    assert equals_canonically(podspec.resources.requests, default_requests)
    assert await check_prometheus_is_ready(ops_test, app_name, 0)


@pytest.mark.abort_on_fail
@pytest.mark.parametrize("cpu,memory", [("500m", "0.5Gi"), ("0.30000000000000004", "0.5G")])
async def test_resource_limits_match_config(ops_test: OpsTest, cpu, memory):
    assert ops_test.model
    custom_limits = {"cpu": cpu, "memory": memory}
    await ops_test.model.applications[app_name].set_config(custom_limits)
    await ops_test.model.wait_for_idle(status="active", timeout=resched_timeout)

    # Not comparing limits (for now) because the strings may differ (0.9G vs 900M)
    # Comparison is done inside the k8s resource patch.
    # client = Client()
    # pod = client.get(Pod, name=f"{app_name}-0", namespace=ops_test.model_name)
    # podspec = next(iter(filter(lambda ctr: ctr.name == "prometheus", pod.spec.containers)))
    # assert podspec.resources.limits == custom_limits
    # assert podspec.resources.requests == custom_limits

    assert await check_prometheus_is_ready(ops_test, app_name, 0)


@pytest.mark.abort_on_fail
@pytest.mark.parametrize(
    "cpu,memory", [("-1", "0.1Gi"), ("1", "-0.1Gi"), ("4x", "1Gi"), ("1", "1Gx")]
)
async def test_invalid_resource_limits_put_charm_in_blocked_status(ops_test: OpsTest, cpu, memory):
    assert ops_test.model
    custom_limits = {"cpu": cpu, "memory": memory}
    await ops_test.model.applications[app_name].set_config(custom_limits)
    await ops_test.model.wait_for_idle(status="blocked", timeout=resched_timeout)
    assert await check_prometheus_is_ready(ops_test, app_name, 0)


@pytest.mark.abort_on_fail
async def test_charm_recovers_from_invalid_resource_limits(ops_test: OpsTest):
    assert ops_test.model
    custom_limits = {"cpu": "500m", "memory": "0.5Gi"}
    await ops_test.model.applications[app_name].set_config(custom_limits)
    await ops_test.model.wait_for_idle(status="active", timeout=resched_timeout)
    assert await check_prometheus_is_ready(ops_test, app_name, 0)


@pytest.mark.abort_on_fail
async def test_upgrade(ops_test: OpsTest, prometheus_charm):
    """Make sure the app is able to upgrade when resource limits are set."""
    assert ops_test.model
    await ops_test.model.applications[app_name].refresh(path=prometheus_charm, resources=resources)
    await ops_test.model.wait_for_idle(status="active", timeout=300, idle_period=60)
    assert await check_prometheus_is_ready(ops_test, app_name, 0)


@pytest.mark.abort_on_fail
async def test_default_resource_limits_applied_after_resetting_config(ops_test: OpsTest):
    assert ops_test.model
    await ops_test.model.applications[app_name].reset_config(["cpu", "memory"])
    await ops_test.model.wait_for_idle(status="active", timeout=resched_timeout)

    podspec = get_podspec(ops_test, app_name, "prometheus")
    assert podspec.resources
    assert equals_canonically(podspec.resources.limits, default_limits)
    assert equals_canonically(podspec.resources.requests, default_requests)
    assert await check_prometheus_is_ready(ops_test, app_name, 0)
