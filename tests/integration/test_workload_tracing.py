#!/usr/bin/env python3
# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.
import asyncio
import logging
from pathlib import Path

import pytest
import yaml
from helpers import deploy_tempo_cluster, get_application_ip, get_traces_patiently, oci_image

logger = logging.getLogger(__name__)

METADATA = yaml.safe_load(Path("./charmcraft.yaml").read_text())
APP_NAME = "prometheus"
TEMPO_APP_NAME = "tempo"
TEMPO_WORKER_APP_NAME = "tempo-worker"
PROMETHEUS_RESOURCES = {"prometheus-image": oci_image("./charmcraft.yaml", "prometheus-image")}
SSC = "self-signed-certificates"
SSC_APP_NAME = "ssc"


@pytest.mark.abort_on_fail
async def test_workload_traces(ops_test, prometheus_charm):

    # deploy Tempo and Prometheus
    await asyncio.gather(
        deploy_tempo_cluster(ops_test),
        ops_test.model.deploy(
            prometheus_charm, resources=PROMETHEUS_RESOURCES, application_name=APP_NAME, trust=True
        ),
    )

    # integrate workload-tracing only to not affect search results with charm traces
    await ops_test.model.integrate(f"{APP_NAME}:workload-tracing", f"{TEMPO_APP_NAME}:tracing")

    # stimulate prometheus to generate traces
    await ops_test.model.integrate(
        f"{APP_NAME}:receive-remote-write", f"{TEMPO_APP_NAME}:send-remote-write"
    )

    await ops_test.model.wait_for_idle(
        apps=[APP_NAME, TEMPO_APP_NAME, TEMPO_WORKER_APP_NAME], status="active", timeout=300
    )

    # verify workload traces are ingested into Tempo
    assert await get_traces_patiently(
        await get_application_ip(ops_test, TEMPO_APP_NAME),
        service_name=f"{APP_NAME}",
        tls=False,
    )


@pytest.mark.abort_on_fail
async def test_workload_traces_tls(ops_test):

    # integrate with a TLS Provider
    await ops_test.model.deploy(SSC, application_name=SSC_APP_NAME)
    await ops_test.model.integrate(SSC_APP_NAME + ":certificates", APP_NAME + ":certificates")
    await ops_test.model.integrate(
        SSC_APP_NAME + ":certificates", TEMPO_APP_NAME + ":certificates"
    )

    # wait for workloads to settle down
    await ops_test.model.wait_for_idle(
        apps=[APP_NAME, TEMPO_APP_NAME, TEMPO_WORKER_APP_NAME], status="active", timeout=300
    )

    # verify workload traces are ingested into Tempo
    assert await get_traces_patiently(
        await get_application_ip(ops_test, TEMPO_APP_NAME),
        service_name=f"{APP_NAME}",
    )
