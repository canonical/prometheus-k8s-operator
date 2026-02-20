#!/usr/bin/env python3
# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.
import logging
from pathlib import Path

import jubilant
import pytest
import yaml
from helpers import oci_image, push_to_otelcol, query_exemplars

# from minio import Minio

logger = logging.getLogger(__name__)

METADATA = yaml.safe_load(Path("./charmcraft.yaml").read_text())
APP_NAME = "prometheus"
OTELCOL_APP_NAME = "otelcol"
PROMETHEUS_RESOURCES = {"prometheus-image": oci_image("./charmcraft.yaml", "prometheus-image")}


@pytest.mark.abort_on_fail
@pytest.mark.setup
def test_prepare_environment(ops_test, prometheus_charm):
    juju = jubilant.Juju(model=ops_test.model.name)
    juju.deploy(charm="opentelemetry-collector-k8s", app=OTELCOL_APP_NAME, trust=True, channel="2/edge")
    juju.deploy(prometheus_charm, app=APP_NAME, resources=PROMETHEUS_RESOURCES, trust=True, config={"max_global_exemplars_per_user": 100000})
    juju.integrate(f"{APP_NAME}:receive-remote-write", f"{OTELCOL_APP_NAME}:send-remote-write")

    juju.wait(lambda status: jubilant.all_active(status, APP_NAME, OTELCOL_APP_NAME))


async def test_exemplars(ops_test):
    # WHEN exemplars are pushed to otel collector
    metric_name = "sample_metric"
    trace_id = await push_to_otelcol(ops_test, metric_name=metric_name)

    # THEN exemplars are found
    found_trace_id = await query_exemplars(ops_test, query_name=metric_name, app=APP_NAME)
    assert found_trace_id == trace_id
