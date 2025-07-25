#!/usr/bin/env python3
# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.
import logging
from pathlib import Path

import jubilant
import pytest
import yaml
from helpers import get_application_ip, get_traces_patiently, oci_image
from minio import Minio

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
    minio_user = "accesskey"
    minio_pass = "secretkey"
    minio_bucket = "tempo"
    # Set up minio and s3-integrator
    juju = jubilant.Juju(model=ops_test.model.name)
    juju.deploy(charm="tempo-coordinator-k8s", app="tempo", channel="2/edge", trust=True)
    juju.deploy(charm="tempo-worker-k8s", app="tempo-worker", channel="2/edge", trust=True)
    juju.deploy(
        charm="minio",
        app="minio-tempo",
        trust=True,
        config={"access-key": minio_user, "secret-key": minio_pass},
    )
    juju.deploy(charm="s3-integrator", app="s3-tempo", channel="edge")
    juju.wait(lambda status: jubilant.all_active(status, "minio-tempo"), delay=5)
    minio_address = juju.status().apps["minio-tempo"].units["minio-tempo/0"].address
    minio_client: Minio = Minio(
        f"{minio_address}:9000",
        access_key=minio_user,
        secret_key=minio_pass,
        secure=False,
    )
    if not minio_client.bucket_exists(minio_bucket):
        minio_client.make_bucket(minio_bucket)
    juju.config("s3-tempo", {"endpoint": f"{minio_address}:9000", "bucket": minio_bucket})
    juju.run(
        unit="s3-tempo/0",
        action="sync-s3-credentials",
        params={"access-key": minio_user, "secret-key": minio_pass},
    )
    juju.integrate("tempo:s3", "s3-tempo")
    juju.integrate("tempo:tempo-cluster", "tempo-worker")
    # Deploy Prometheus
    juju.deploy(prometheus_charm, app=APP_NAME, resources=PROMETHEUS_RESOURCES, trust=True)

    # integrate workload-tracing only to not affect search results with charm traces
    await ops_test.model.integrate(f"{APP_NAME}:workload-tracing", f"{TEMPO_APP_NAME}:tracing")

    # stimulate prometheus to generate traces
    await ops_test.model.integrate(
        f"{APP_NAME}:receive-remote-write", f"{TEMPO_APP_NAME}:send-remote-write"
    )

    await ops_test.model.wait_for_idle(
        apps=[APP_NAME, TEMPO_APP_NAME, TEMPO_WORKER_APP_NAME],
        status="active",
        timeout=300,
        # wait for an idle period
        delay=10,
        successes=3,
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
    await ops_test.model.deploy(SSC, application_name=SSC_APP_NAME, channel="1/stable")
    await ops_test.model.integrate(SSC_APP_NAME + ":certificates", APP_NAME + ":certificates")
    await ops_test.model.integrate(
        SSC_APP_NAME + ":certificates", TEMPO_APP_NAME + ":certificates"
    )

    # wait for workloads to settle down
    await ops_test.model.wait_for_idle(
        apps=[APP_NAME, TEMPO_APP_NAME, TEMPO_WORKER_APP_NAME],
        status="active",
        timeout=300,
        # wait for an idle period
        delay=10,
        successes=3,
    )

    # verify workload traces are ingested into Tempo
    assert await get_traces_patiently(
        await get_application_ip(ops_test, TEMPO_APP_NAME),
        service_name=f"{APP_NAME}",
    )
