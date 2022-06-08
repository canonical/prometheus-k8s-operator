#!/usr/bin/env python3
# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

import asyncio
import json
import logging

import pytest
from helpers import check_prometheus_is_ready, initial_workload_is_ready, oci_image

logger = logging.getLogger(__name__)


class AddressNotFoundError(Exception):
    def __init__(self, message):
        super().__init__(message)


@pytest.mark.abort_on_fail
async def test_ingress_traefik_k8s(ops_test, prometheus_charm):
    """Test that Prometheus can be related with the Grafana Agent over remote_write."""
    prometheus_name = "prometheus"
    traefik_name = "traefik-ingress"

    await asyncio.gather(
        ops_test.model.deploy(
            prometheus_charm,
            resources={"prometheus-image": oci_image("./metadata.yaml", "prometheus-image")},
            application_name=prometheus_name,
            trust=True,  # otherwise errors on ghwf (persistentvolumeclaims ... is forbidden)
        ),
        ops_test.model.deploy(
            "traefik-k8s",
            application_name=traefik_name,
            channel="edge",
            config={
                "routing_mode": "path",
                "external_hostname": "foo.bar",
            },
        ),
    )

    apps = [prometheus_name, traefik_name]
    await ops_test.model.wait_for_idle(apps=apps, status="active")
    assert initial_workload_is_ready(ops_test, apps)
    assert await check_prometheus_is_ready(ops_test, prometheus_name, 0)

    await ops_test.model.add_relation(traefik_name, f"{prometheus_name}:ingress")

    # Wait a little more than usual, there are various rounds of relation_changed
    # to be processed.

    await ops_test.model.wait_for_idle(apps=apps, status="active")

    result = await _retrieve_proxied_endpoints(ops_test, traefik_name)
    assert f"{prometheus_name}/0" in result
    assert result[f"{prometheus_name}/0"] == {
        "url": f"http://foo.bar:80/{ops_test.model_name}-{prometheus_name}-0"
    }


async def _retrieve_proxied_endpoints(ops_test, traefik_application_name):
    traefik_application = ops_test.model.applications[traefik_application_name]
    traefik_first_unit = next(iter(traefik_application.units))
    action = await traefik_first_unit.run_action("show-proxied-endpoints")
    await action.wait()
    result = await ops_test.model.get_action_output(action.id)

    return json.loads(result["proxied-endpoints"])
