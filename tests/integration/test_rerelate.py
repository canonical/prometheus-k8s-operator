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
    apps_to_remove = {tester_app_name, "alertmanager", "grafana", "grafana-agent"}
    await asyncio.gather(*[ops_test.model.applications[app].remove() for app in apps_to_remove])
    logger.info("Trying to remove related applications")
    try:
        await ops_test.model.block_until(
            lambda: apps_to_remove.intersection(ops_test.model.applications.keys()) == set(),
            timeout=300,
        )
    except asyncio.exceptions.TimeoutError:
        logger.warning(
            "Failed to remove applications: %s",
            ", ".join([app for app in ops_test.model.applications if app in apps_to_remove]),
        )
        hung_apps = [
            name
            for name, app in ops_test.model.applications.items()
            if len(app.units) == 0 and app.status == "active"
        ]
        if hung_apps:
            for app in hung_apps:
                logger.warning("%s stuck removing. Forcing...", app)
                cmd = [
                    "juju",
                    "remove-application",
                    "--destroy-storage",
                    "--force",
                    "--no-wait",
                    app,
                ]
                logger.info("Forcibly removing {}".format(app))
                await ops_test.run(*cmd)
        else:
            raise

    try:
        await ops_test.model.wait_for_idle(status="active", timeout=300)
    except asyncio.exceptions.TimeoutError:
        logger.warning("Timeout waiting for idle, ignoring it.")


@pytest.mark.abort_on_fail
async def test_rerelate_app(ops_test: OpsTest, prometheus_tester_charm):
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
    await ops_test.model.wait_for_idle(status="active", timeout=600)
