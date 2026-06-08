#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

"""This test module tests prometheus resource limits on startup and after config-changed."""

import logging
from pathlib import Path

import jubilant
import pytest
import requests
import yaml
from helpers import oci_image
from lightkube import Client
from lightkube.resources.apps_v1 import StatefulSet
from lightkube.resources.core_v1 import Pod
from lightkube.utils.quantity import equals_canonically

logger = logging.getLogger(__name__)

METADATA = yaml.safe_load(Path("./charmcraft.yaml").read_text())
APP_NAME = METADATA["name"]
RESOURCES = {"prometheus-image": oci_image("./charmcraft.yaml", "prometheus-image")}

DEFAULT_LIMITS = None
DEFAULT_REQUESTS = {"cpu": "0.25", "memory": "200Mi"}


def get_podspec(model_name: str, app_name: str, container_name: str):
    client = Client()
    pod = client.get(Pod, name=f"{app_name}-0", namespace=model_name)
    assert pod.spec
    podspec = next(iter(filter(lambda ctr: ctr.name == container_name, pod.spec.containers)))
    return podspec


def get_statefulset_resources(model_name: str, app_name: str, container_name: str):
    """Get the resource requirements from the StatefulSet template."""
    client = Client()
    sts = client.get(StatefulSet, name=app_name, namespace=model_name)
    assert sts.spec and sts.spec.template and sts.spec.template.spec
    for ctr in sts.spec.template.spec.containers:
        if ctr.name == container_name:
            return ctr.resources
    return None


def check_prometheus_is_ready(host: str) -> bool:
    """Check if Prometheus server responds to HTTP API requests."""
    try:
        response = requests.get(f"http://{host}:9090/-/ready", timeout=5)
        return response.status_code == 200
    except requests.RequestException:
        return False


@pytest.mark.abort_on_fail
def test_build_and_deploy(juju: jubilant.Juju, prometheus_charm):
    """Build the charm-under-test and deploy it."""
    juju.model_config({"logging-config": "<root>=WARNING; unit=DEBUG"})
    juju.deploy(
        prometheus_charm,
        resources=RESOURCES,
        app=APP_NAME,
        trust=True,
    )
    juju.wait(lambda status: jubilant.all_active(status, APP_NAME) and jubilant.all_agents_idle(status, APP_NAME), timeout=600)


@pytest.mark.abort_on_fail
def test_default_resource_limits_applied(juju: jubilant.Juju):
    assert juju.model

    # Debug: check what's in the StatefulSet template vs the Pod
    sts_resources = get_statefulset_resources(juju.model, APP_NAME, "prometheus")
    logger.info(f"StatefulSet template resources: {sts_resources}")

    podspec = get_podspec(juju.model, APP_NAME, "prometheus")
    logger.info(f"Pod resources: {podspec.resources}")

    # If StatefulSet has resources but Pod doesn't, the rollout hasn't completed
    if sts_resources and sts_resources.requests and not podspec.resources.requests:
        logger.warning("StatefulSet has resources but Pod doesn't - waiting for rollout...")
        # Wait for pod to be recreated with the new resources
        import time
        for i in range(30):
            time.sleep(2)
            podspec = get_podspec(juju.model, APP_NAME, "prometheus")
            logger.info(f"Retry {i+1}: Pod resources: {podspec.resources}")
            if podspec.resources and podspec.resources.requests:
                break

    assert podspec.resources
    assert equals_canonically(podspec.resources.limits, DEFAULT_LIMITS)
    assert equals_canonically(podspec.resources.requests, DEFAULT_REQUESTS)
    host = juju.status().apps[APP_NAME].units[f"{APP_NAME}/0"].address
    assert check_prometheus_is_ready(host)


@pytest.mark.abort_on_fail
@pytest.mark.parametrize("cpu,memory", [("500m", "0.5Gi"), ("0.30000000000000004", "0.5G")])
def test_resource_limits_match_config(juju: jubilant.Juju, cpu, memory):
    custom_limits = {"cpu": cpu, "memory": memory}
    juju.config(APP_NAME, custom_limits)
    juju.wait(lambda status: jubilant.all_active(status, APP_NAME) and jubilant.all_agents_idle(status, APP_NAME), timeout=600)
    host = juju.status().apps[APP_NAME].units[f"{APP_NAME}/0"].address
    assert check_prometheus_is_ready(host)


@pytest.mark.abort_on_fail
@pytest.mark.parametrize(
    "cpu,memory", [("-1", "0.1Gi"), ("1", "-0.1Gi"), ("4x", "1Gi"), ("1", "1Gx")]
)
def test_invalid_resource_limits_put_charm_in_blocked_status(juju: jubilant.Juju, cpu, memory):
    custom_limits = {"cpu": cpu, "memory": memory}
    juju.config(APP_NAME, custom_limits)
    juju.wait(
        lambda status: status.apps[APP_NAME].is_blocked,
        timeout=600,
    )
    host = juju.status().apps[APP_NAME].units[f"{APP_NAME}/0"].address
    assert check_prometheus_is_ready(host)


@pytest.mark.abort_on_fail
def test_charm_recovers_from_invalid_resource_limits(juju: jubilant.Juju):
    custom_limits = {"cpu": "500m", "memory": "0.5Gi"}
    juju.config(APP_NAME, custom_limits)
    juju.wait(lambda status: jubilant.all_active(status, APP_NAME) and jubilant.all_agents_idle(status, APP_NAME), timeout=600)
    host = juju.status().apps[APP_NAME].units[f"{APP_NAME}/0"].address
    assert check_prometheus_is_ready(host)


@pytest.mark.abort_on_fail
def test_upgrade(juju: jubilant.Juju, prometheus_charm):
    """Make sure the app is able to upgrade when resource limits are set."""
    juju.refresh(APP_NAME, path=prometheus_charm, resources=RESOURCES)
    juju.wait(lambda status: jubilant.all_active(status, APP_NAME) and jubilant.all_agents_idle(status, APP_NAME), timeout=300, delay=60)
    host = juju.status().apps[APP_NAME].units[f"{APP_NAME}/0"].address
    assert check_prometheus_is_ready(host)


@pytest.mark.abort_on_fail
def test_default_resource_limits_applied_after_resetting_config(juju: jubilant.Juju):
    juju.config(APP_NAME, reset=["cpu", "memory"])
    juju.wait(lambda status: jubilant.all_active(status, APP_NAME) and jubilant.all_agents_idle(status, APP_NAME), timeout=600)

    assert juju.model
    podspec = get_podspec(juju.model, APP_NAME, "prometheus")
    assert podspec.resources
    assert equals_canonically(podspec.resources.limits, DEFAULT_LIMITS)
    assert equals_canonically(podspec.resources.requests, DEFAULT_REQUESTS)
    host = juju.status().apps[APP_NAME].units[f"{APP_NAME}/0"].address
    assert check_prometheus_is_ready(host)
