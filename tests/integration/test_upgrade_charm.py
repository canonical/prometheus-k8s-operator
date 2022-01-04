#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.


import logging
from pathlib import Path

import pytest
import yaml
from helpers import (  # type: ignore[attr-defined]
    IPAddressWorkaround,
    cli_upgrade_from_path_and_wait,
)

log = logging.getLogger(__name__)

METADATA = yaml.safe_load(Path("./metadata.yaml").read_text())
app_name = METADATA["name"]


@pytest.mark.abort_on_fail
async def test_build_and_deploy(ops_test, prometheus_charm):
    """Build the charm-under-test and deploy it together with related charms.

    Assert on the unit status before any relations/configurations take place.
    """
    log.info("build charm from local source folder")
    resources = {
        "alertmanager-image": METADATA["resources"]["alertmanager-image"]["upstream-source"]
    }

    async with IPAddressWorkaround(ops_test):
        log.info("deploy charm from charmhub")
        await ops_test.model.deploy(f"ch:{app_name}", application_name=app_name, channel="edge")
        await ops_test.model.wait_for_idle(apps=[app_name], status="active", timeout=1000)

        log.info("upgrade deployed charm with local charm %s", prometheus_charm)
        # await ops_test.model.applications[app_name].refresh(
        #     path=local_charm, resources=resources
        # )

        await cli_upgrade_from_path_and_wait(
            ops_test,
            path=prometheus_charm,
            alias=app_name,
            resources=resources,
            wait_for_status="active",
        )
