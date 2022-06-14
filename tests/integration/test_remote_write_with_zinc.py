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
zinc_name = "zinc"
agent_remote_name = "grafana-agent-cmr"
zinc_remote_name = "zinc-cmr"
local_apps = [prometheus_name, agent_name, zinc_name]
remote_apps = [agent_remote_name, zinc_remote_name]


@pytest.mark.abort_on_fail
async def test_remote_write_with_zinc(ops_test, prometheus_charm):
    """Test that Prometheus can be related with the Grafana Agent over remote_write."""
    await asyncio.gather(
        ops_test.model.deploy(
            prometheus_charm,
            resources={"prometheus-image": oci_image("./metadata.yaml", "prometheus-image")},
            application_name=prometheus_name,
            trust=True,  # otherwise errors on ghwf (persistentvolumeclaims ... is forbidden)
        ),
        ops_test.model.deploy(
            "grafana-agent-k8s",
            application_name=agent_name,
            channel="edge",
        ),
        ops_test.model.deploy(
            "zinc-k8s",
            channel="edge",
            application_name=zinc_name,
        ),
    )

    await ops_test.model.wait_for_idle(apps=local_apps, status="active", wait_for_units=1)
    assert await check_prometheus_is_ready(ops_test, prometheus_name, 0)

    await asyncio.gather(
        ops_test.model.add_relation(prometheus_name, agent_name),
        ops_test.model.add_relation(
            f"{agent_name}:metrics-endpoint", f"{zinc_name}:metrics-endpoint"
        ),
    )

    await ops_test.model.wait_for_idle(apps=local_apps, status="active", idle_period=90)

    assert await has_metric(
        ops_test,
        f'up{{juju_model="{ops_test.model_name}",juju_application="{agent_name}"}}',
        prometheus_name,
    )
    assert await has_metric(
        ops_test,
        f'up{{juju_model="{ops_test.model_name}",juju_application="{zinc_name}"}}',
        prometheus_name,
    )


@pytest.mark.abort_on_fail
async def test_create_remote_write_models_for_zinc(ops_test):
    """Test that Prometheus can be related with the Grafana Agent over remote_write."""
    # pytest_operator keeps a dict[str, ModelState] for internal reference, and they'll
    # all get cleaned up just like the automatic one. The alias for the first one is
    # 'main' if we want to get it.
    #
    # 'consumer' is an alias, not the name of the model
    await ops_test.track_model("consumer")

    consumer = ops_test.models.get("consumer")
    await asyncio.gather(
        consumer.model.deploy(
            "grafana-agent-k8s",
            application_name=agent_remote_name,
            channel="edge",
        ),
        consumer.model.deploy(
            "zinc-k8s",
            channel="edge",
            application_name=zinc_remote_name,
        ),
    )

    await consumer.model.wait_for_idle(apps=remote_apps, status="active", idle_period=90)
    assert await check_prometheus_is_ready(ops_test, prometheus_name, 0)


@pytest.mark.abort_on_fail
async def test_offer_and_consume_remote_write_with_zinc(ops_test):
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
    await consumer.model.relate(agent_remote_name, "prom")

    # grafana-agent will block if it's related to anything with a remote_write relation
    # to prometheus, so establish this first
    await asyncio.gather(
        offer.model.wait_for_idle(apps=[prometheus_name], status="active", idle_period=90),
        consumer.model.wait_for_idle(apps=[agent_remote_name], status="active", idle_period=90),
    )

    await consumer.model.add_relation(
        f"{agent_remote_name}:metrics-endpoint", f"{zinc_remote_name}:metrics-endpoint"
    )
    await consumer.model.wait_for_idle(apps=remote_apps, status="active", idle_period=90)

    assert await has_metric(
        ops_test,
        f'up{{juju_model="{offer.model_name}",juju_application="{agent_name}"}}',
        prometheus_name,
    )

    assert await has_metric(
        ops_test,
        f'up{{juju_model="{consumer.model_name}",juju_application="{agent_remote_name}"}}',
        prometheus_name,
    )

    # Disconnect manually so pytest-operator can clean up without stack traces
    await consumer.model.remove_application(agent_remote_name, block_until_done=True)
    await consumer.model.remove_saas("prom")
    await controller.disconnect()


async def has_metric(ops_test, query: str, app_name: str) -> bool:
    # Throws if the query does not return any time series within 5 minutes,
    # and as a consequence, fails the test
    for timeseries in await run_promql(ops_test, query, app_name):
        if timeseries.get("metric"):
            return True

    return False
