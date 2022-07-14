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
        ops_test.model.add_relation(
            f"{app_name}:metrics-endpoint", f"{tester_app_name}:metrics-endpoint"
        ),
        ops_test.model.add_relation(f"{app_name}:alertmanager", "alertmanager"),
        ops_test.model.add_relation(f"{app_name}:grafana-source", "grafana"),
        ops_test.model.add_relation(f"{app_name}:receive-remote-write", "grafana-agent"),
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
        ops_test.model.add_relation(
            f"{app_name}:metrics-endpoint", f"{tester_app_name}:metrics-endpoint"
        ),
        ops_test.model.add_relation(f"{app_name}:alertmanager", "alertmanager"),
        ops_test.model.add_relation(f"{app_name}:grafana-source", "grafana"),
        ops_test.model.add_relation(f"{app_name}:receive-remote-write", "grafana-agent"),
    )
    await ops_test.model.wait_for_idle(status="active", timeout=600)
