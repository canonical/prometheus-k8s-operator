#!/usr/bin/env python3
# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

import asyncio
import logging

import pytest
from helpers import check_prometheus_is_ready, oci_image, run_promql
from juju.controller import Controller  # type: ignore

logger = logging.getLogger(__name__)

prometheus_name = "prometheus"
agent_name = "grafana-agent"


@pytest.mark.abort_on_fail
async def test_create_remote_write_models(ops_test, prometheus_charm):
    """Test that Prometheus can be related with the Grafana Agent over remote_write."""
    await ops_test.model.deploy(
        prometheus_charm,
        resources={"prometheus-image": oci_image("./metadata.yaml", "prometheus-image")},
        application_name=prometheus_name,
        trust=True,  # otherwise errors on ghwf (persistentvolumeclaims ... is forbidden)
    )

    # pytest_operator keeps a dict[str, ModelState] for internal reference, and they'll
    # all get cleaned up just like the automatic one. The alias for the first one is
    # 'main' if we want to get it.
    #
    # 'consumer' is an alias, not the name of the model
    await ops_test.track_model("consumer")

    offer, consumer = ops_test.models.get("main"), ops_test.models.get("consumer")
    await consumer.model.deploy(
        "grafana-agent-k8s",
        application_name=agent_name,
        channel="edge",
    )

    await asyncio.gather(
        offer.model.wait_for_idle(apps=[prometheus_name], status="active"),
        consumer.model.wait_for_idle(apps=[agent_name], status="active"),
    )

    assert await check_prometheus_is_ready(ops_test, prometheus_name, 0)


@pytest.mark.abort_on_fail
async def test_offer_and_consume_remote_write(ops_test):
    offer, consumer = ops_test.models.get("main"), ops_test.models.get("consumer")

    # This looks weird, but it's a bug in libjuju. If we don't do this, then
    # both create_offer and list_offers pass through a ContextManager which disconnects
    # the controller and confuses pytest-operator, causing subsequent failures.
    controller = Controller()
    await controller.connect()
    await controller.create_offer(
        offer.model.uuid,
        f"{prometheus_name}:receive-remote-write",
    )
    offers = await controller.list_offers(offer.model_name)
    await offer.model.block_until(
        lambda: all(offer.application_name == prometheus_name for offer in offers.results)
    )

    await consumer.model.consume(f"admin/{offer.model_name}.{prometheus_name}", "prom")
    await consumer.model.relate(agent_name, "prom")

    # Idle period of 60s is not enough - github CI fails for has_metric with idle_period=60.
    await asyncio.gather(
        offer.model.wait_for_idle(apps=[prometheus_name], status="active", idle_period=90),
        consumer.model.wait_for_idle(apps=[agent_name], status="active", idle_period=90),
    )

    assert await has_metric(
        ops_test,
        f'up{{juju_model="{consumer.model_name}",juju_application="{agent_name}"}}',
        prometheus_name,
    )

    # Disconnect manually so pytest-operator can clean up without stack traces
    await consumer.model.remove_application(agent_name, block_until_done=True)
    await consumer.model.remove_saas("prom")
    await controller.disconnect()


async def has_metric(ops_test, query: str, app_name: str) -> bool:
    # Throws if the query does not return any time series within 5 minutes,
    # and as a consequence, fails the test
    for timeseries in await run_promql(ops_test, query, app_name):
        if timeseries.get("metric"):
            return True

    return False
