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
async def test_deploy_from_edge_and_upgrade_from_local_path(ops_test, prometheus_charm):
    """Build the charm-under-test and deploy it together with related charms.

    Assert on the unit status before any relations/configurations take place.
    """
    log.info("build charm from local source folder")
    resources = {"prometheus-image": METADATA["resources"]["prometheus-image"]["upstream-source"]}

    async with IPAddressWorkaround(ops_test):
        log.info("deploy charm from charmhub")
        await ops_test.model.deploy(f"ch:{app_name}", application_name=app_name, channel="edge")
        await ops_test.model.wait_for_idle(apps=[app_name], status="active", timeout=1000)

        log.info("upgrade deployed charm with local charm %s", prometheus_charm)
        await ops_test.model.applications[app_name].refresh(
            path=prometheus_charm, resources=resources
        )
        await ops_test.model.wait_for_idle(apps=[app_name], status="active", timeout=1000)
        await check_prometheus_is_ready(ops_test, app_name, 0)
