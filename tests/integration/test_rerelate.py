#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

"""This test module tests prometheus charm response to related apps being removed and re-related.

1. Deploy the charm under test and a related app, relate them and wait for them to become idle.
2. Remove the relation.
3. Re-add the relation.
4. Remove the related application.
5. Redeploy the related application and add the relation back again.
"""

import asyncio
import logging
from pathlib import Path

import pytest
import yaml
from helpers import oci_image
from pytest_operator.plugin import OpsTest

logger = logging.getLogger(__name__)

METADATA = yaml.safe_load(Path("./metadata.yaml").read_text())
app_name = METADATA["name"]
resources = {"prometheus-image": oci_image("./metadata.yaml", "prometheus-image")}
tester_app_name = "prometheus-tester"
tester_resources = {
    "prometheus-tester-image": oci_image(
        "./tests/integration/prometheus-tester/metadata.yaml",
        "prometheus-tester-image",
    )
}


async def test_setup_env(ops_test: OpsTest):
    await ops_test.model.set_config({"logging-config": "<root>=WARNING; unit=DEBUG"})


@pytest.mark.abort_on_fail
async def test_build_and_deploy(ops_test: OpsTest, prometheus_charm, prometheus_tester_charm):
    """Build the charm-under-test and deploy it together with related charms."""
    await asyncio.gather(
        ops_test.model.deploy(
            prometheus_charm,
            resources=resources,
            application_name=app_name,
            num_units=2,
            trust=True,
        ),
        ops_test.model.deploy(
            prometheus_tester_charm,
            resources=tester_resources,
            application_name=tester_app_name,
        ),
        ops_test.model.deploy(
            "ch:alertmanager-k8s",
            application_name="alertmanager",
            channel="edge",
        ),
        ops_test.model.deploy(
            "ch:grafana-k8s",
            application_name="grafana",
            channel="edge",
        ),
        ops_test.model.deploy(
            "ch:grafana-agent-k8s",
            application_name="grafana-agent",
            channel="edge",
        ),
        # TODO: add traefik after fetch-lib (there are breaking changes)
    )

    await asyncio.gather(
        ops_test.model.add_relation(app_name, tester_app_name),
        ops_test.model.add_relation(app_name, "alertmanager"),
        ops_test.model.add_relation(app_name, "grafana:grafana-source"),
        ops_test.model.add_relation(app_name, "grafana-agent:send-remote-write"),
    )
    await ops_test.model.wait_for_idle(status="active", timeout=600)


@pytest.mark.abort_on_fail
async def test_remove_relation(ops_test: OpsTest):
    await asyncio.gather(
        ops_test.model.applications[app_name].remove_relation("metrics-endpoint", tester_app_name),
        ops_test.model.applications[app_name].remove_relation("alertmanager", "alertmanager"),
        ops_test.model.applications[app_name].remove_relation("grafana-source", "grafana"),
        ops_test.model.applications[app_name].remove_relation(
            "receive-remote-write", "grafana-agent"
        ),
    )
    await ops_test.model.wait_for_idle(apps=[app_name], status="active", timeout=600)


@pytest.mark.abort_on_fail
async def test_rerelate(ops_test: OpsTest):
    await asyncio.gather(
        ops_test.model.add_relation(app_name, tester_app_name),
        ops_test.model.add_relation(app_name, "alertmanager"),
        ops_test.model.add_relation(app_name, "grafana:grafana-source"),
        ops_test.model.add_relation(app_name, "grafana-agent:send-remote-write"),
    )
    await ops_test.model.wait_for_idle(status="active", timeout=600)


@pytest.mark.abort_on_fail
async def test_remove_related_app(ops_test: OpsTest):
    await asyncio.gather(
        ops_test.model.applications[tester_app_name].remove(),
        ops_test.model.applications["alertmanager"].remove(),
        ops_test.model.applications["grafana"].remove(),
        ops_test.model.applications["grafana-agent"].remove(),
    )
    logger.debug("Applications removed. Blocking for 60 seconds then force removing...")
    # Block until it is really gone. Added after an itest failed when tried to redeploy:
    # juju.errors.JujuError: ['cannot add application "...": application already exists']
    try:
        await ops_test.model.block_until(
            lambda: tester_app_name not in ops_test.model.applications,
            lambda: "alertmanager" not in ops_test.model.applications,
            lambda: "grafana" not in ops_test.model.applications,
            lambda: "grafana-agent" not in ops_test.model.applications,
            timeout=60,
        )
    except asyncio.exceptions.TimeoutError:
        logger.warning("Timeout reached while blocking!")

    await ops_test.model.wait_for_idle(apps=[app_name], timeout=600)


@pytest.mark.abort_on_fail
async def test_rerelate_app(ops_test: OpsTest, prometheus_tester_charm):
    # TODO remove the "-new" suffix (otherwise it's not fully a "rerelate" test)
    await asyncio.gather(
        ops_test.model.deploy(
            prometheus_tester_charm,
            resources=tester_resources,
            application_name=tester_app_name,
            trust=True,
        ),
        ops_test.model.deploy(
            "ch:alertmanager-k8s",
            application_name="alertmanager",
            channel="edge",
        ),
        ops_test.model.deploy(
            "ch:grafana-k8s",
            application_name="grafana",
            channel="edge",
        ),
        ops_test.model.deploy(
            "ch:grafana-agent-k8s",
            application_name="grafana-agent",
            channel="edge",
        ),
    )

    await asyncio.gather(
        ops_test.model.add_relation(app_name, tester_app_name),
        ops_test.model.add_relation(app_name, "alertmanager"),
        ops_test.model.add_relation(app_name, "grafana:grafana-source"),
        ops_test.model.add_relation(app_name, "grafana-agent:send-remote-write"),
    )
    await ops_test.model.wait_for_idle(apps=[app_name], status="active", timeout=600)
