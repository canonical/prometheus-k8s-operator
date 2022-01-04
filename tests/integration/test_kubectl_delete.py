#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.


import logging
from pathlib import Path

import pytest
import yaml
from helpers import (  # type: ignore[attr-defined]
    IPAddressWorkaround,
    check_prometheus_is_ready,
)

log = logging.getLogger(__name__)

METADATA = yaml.safe_load(Path("./metadata.yaml").read_text())
app_name = METADATA["name"]


@pytest.mark.abort_on_fail
async def test_deploy_from_local_path(ops_test, prometheus_charm):
    """Deploy the charm-under-test."""
    resources = {"prometheus-image": METADATA["resources"]["prometheus-image"]["upstream-source"]}
    log.info("deploy local charm")

    async with IPAddressWorkaround(ops_test):
        await ops_test.model.deploy(
            prometheus_charm, application_name=app_name, resources=resources
        )
        await ops_test.model.block_until(
            lambda: len(ops_test.model.applications[app_name].units) > 0
        )
        await ops_test.model.wait_for_idle(apps=[app_name], status="active", timeout=1000)
        await check_prometheus_is_ready(ops_test, app_name, 0)


@pytest.mark.abort_on_fail
async def test_kubectl_delete_pod(ops_test, prometheus_charm):
    pod_name = f"{app_name}-0"
    log.info("Removing pod '%s' from model '%s'", pod_name, ops_test.model_name)
    cmd = [
        "microk8s.kubectl",
        "delete",
        "pod",
        "-n",
        ops_test.model_name,
        pod_name,
    ]

    retcode, stdout, stderr = await ops_test._run(*cmd)
    assert retcode == 0, f"kubectl failed: {(stderr or stdout).strip()}"
    log.info(stdout)
    await ops_test.model.block_until(lambda: len(ops_test.model.applications[app_name].units) > 0)
    await ops_test.model.wait_for_idle(apps=[app_name], status="active", timeout=1000)
    await check_prometheus_is_ready(ops_test, app_name, 0)
