#!/usr/bin/env python3
# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

"""Test various aspects of `external_url`.

1. When external_url is set (with path prefix) via traefik, default and self-scraping jobs are
   'up'.
2. When external_url is set (with path prefix) via config option to a different value,
   default and self-scraping jobs are 'up'.
"""

import asyncio
import json
import logging
import subprocess
import urllib.request

import pytest
from helpers import oci_image, unit_address
from pytest_operator.plugin import OpsTest
from workload import Prometheus

logger = logging.getLogger(__name__)

prometheus_app_name = "prometheus"
prometheus_resources = {"prometheus-image": oci_image("./metadata.yaml", "prometheus-image")}
external_prom_name = "external-prometheus"

# Two prometheus units are sufficient to test potential interactions between multi-unit
# deployments and external_url
num_units = 2

# The period of time required to be idle before `wait_for_idle` returns is set to 90 sec because
# the default scrape_interval in prometheus is 1m.
idle_period = 90


async def test_setup_env(ops_test: OpsTest):
    await ops_test.model.set_config(
        {"logging-config": "<root>=WARNING; unit=DEBUG", "update-status-hook-interval": "60m"}
    )


@pytest.mark.abort_on_fail
async def test_deploy(ops_test: OpsTest, prometheus_charm):
    await asyncio.gather(
        ops_test.model.deploy(
            prometheus_charm,
            resources=prometheus_resources,
            application_name=prometheus_app_name,
            num_units=num_units,
            trust=True,
        ),
        ops_test.model.deploy(
            prometheus_charm,
            resources=prometheus_resources,
            application_name=external_prom_name,  # to scrape the main prom
            trust=True,
        ),
        ops_test.model.deploy(
            "ch:traefik-k8s",
            application_name="traefik",
            channel="edge",
        ),
    )

    await asyncio.gather(
        ops_test.model.add_relation(
            f"{prometheus_app_name}:self-metrics-endpoint", external_prom_name
        ),
        ops_test.model.wait_for_idle(
            apps=[prometheus_app_name],
            status="active",
            wait_for_units=num_units,
            timeout=300,
        ),
        ops_test.model.wait_for_idle(
            apps=["traefik", external_prom_name],
            wait_for_units=1,
            timeout=300,
        ),
    )


async def wait_for_ingress(ops_test: OpsTest):
    """Returns when all ingressed prometheuses are ready.

    Wait until ingress is really ready.
    Workaround for https://github.com/canonical/traefik-k8s-operator/issues/78.
    """

    async def get_ingressed_endpoints():
        action = (
            await ops_test.model.applications["traefik"]
            .units[0]
            .run_action("show-proxied-endpoints")
        )
        res = (await action.wait()).results
        # res looks like this:
        # {'proxied-endpoints':
        #   '{"prometheus/0": {"url": "http://10.128.0.2:80/test-external-url-0lxt-prometheus-0"},
        #     "prometheus/1": {"url": "http://10.128.0.2:80/test-external-url-0lxt-prometheus-1"}
        #    }', 'return-code': 0}

        proxied_endpoints = json.loads(res["proxied-endpoints"])
        endpoints = [v["url"] for v in proxied_endpoints.values()]
        return endpoints

    ingressed_endpoints = await get_ingressed_endpoints()
    logger.debug("Waiting for endpoints to become reachable: %s", ingressed_endpoints)
    await ops_test.model.block_until(
        lambda: all(Prometheus(ep).is_ready() for ep in ingressed_endpoints)
    )


async def force_update_status(ops_test: OpsTest):
    """Force an update-status emission and wait for active/idle."""
    await ops_test.model.set_config({"update-status-hook-interval": "10s"})
    await asyncio.sleep(11)
    await ops_test.model.set_config({"update-status-hook-interval": "60m"})
    logger.debug("At this point, ingressed endpoints should become reachable and reldata updated")
    await ops_test.model.wait_for_idle(
        apps=[prometheus_app_name, "traefik", external_prom_name],
        status="active",
        timeout=600,
        idle_period=idle_period,
    )


async def test_jobs_are_up_via_traefik(ops_test: OpsTest):
    # Set up microk8s metallb addon, needed by traefik
    logger.info("(Re)-enabling metallb")
    cmd = [
        "sh",
        "-c",
        "ip -4 -j route | jq -r '.[] | select(.dst | contains(\"default\")) | .prefsrc'",
    ]
    result = subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    ip = result.stdout.decode("utf-8").strip()

    logger.info("First, disable metallb, just in case")
    try:
        cmd = ["sg", "microk8s", "-c", "microk8s disable metallb"]
        subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    except Exception as e:
        print(e)
        raise

    await asyncio.sleep(30)  # why? just because, for now

    logger.info("Now enable metallb")
    try:
        cmd = ["sg", "microk8s", "-c", f"microk8s enable metallb:{ip}-{ip}"]
        subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    except Exception as e:
        print(e)
        raise

    # GIVEN metallb is ready
    await asyncio.sleep(30)  # why? just because, for now

    # WHEN prometheus is related to traefik
    await ops_test.model.add_relation(f"{prometheus_app_name}:ingress", "traefik")

    # Workaround to make sure everything is up-to-date: update-status
    await ops_test.model.set_config({"update-status-hook-interval": "10s"})
    await asyncio.sleep(11)
    await ops_test.model.set_config({"update-status-hook-interval": "60m"})

    logger.info("At this point, after re-enabling metallb, traefik should become active")
    await ops_test.model.wait_for_idle(
        apps=[prometheus_app_name, "traefik", external_prom_name],
        status="active",
        timeout=600,
        idle_period=idle_period,
    )

    # THEN the prometheus API is served on metallb's IP and the model-app-unit path
    def prom_url(unit: int) -> str:
        return f"http://{ip}/{ops_test.model_name}-{prometheus_app_name}-{unit}"

    # AND the default job is healthy (its scrape url must have the path for this to work)
    prom_urls = [prom_url(i) + "/api/v1/targets" for i in range(num_units)]
    for url in prom_urls:
        logger.info("Attmpting to fetch targets from url: %s", url)
        targets = urllib.request.urlopen(url, None, timeout=2).read().decode("utf8")
        logger.info("Response: %s", targets)
        assert '"health":"up"' in targets
        assert '"health":"down"' not in targets

    # Workaround to make sure everything is up-to-date:
    # Ingress events are already passed as refresh_event to the MeetricsEndpointProvider.
    # TODO remove these two lines when https://github.com/canonical/traefik-k8s-operator/issues/78
    #  is fixed.
    await wait_for_ingress(ops_test)
    await force_update_status(ops_test)

    # AND the self-scrape jobs are healthy (their scrape url must have the entire web_external_url
    # for this to work).
    external_prom_url = f"http://{await unit_address(ops_test, external_prom_name, 0)}:9090"
    url = external_prom_url + "/api/v1/targets"
    logger.info("Attmpting to fetch targets from url: %s", external_prom_url)
    targets = urllib.request.urlopen(url, None, timeout=2).read().decode("utf8")
    logger.info("Response: %s", targets)
    assert '"health":"up"' in targets
    assert '"health":"down"' not in targets


async def test_jobs_are_up_with_config_option_overriding_traefik(ops_test: OpsTest):
    # GIVEN traefik ingress for prom
    # (from previous test)

    # WHEN the `web_external_url` config option is set
    await ops_test.model.applications[prometheus_app_name].set_config(
        {"web_external_url": "http://foo.bar/baz"},
    )

    await ops_test.model.wait_for_idle(
        apps=[prometheus_app_name],
        status="active",
        timeout=300,
    )

    # THEN the prometheus api is served on the unit's IP and web_external_url's path
    async def prom_url(unit: int) -> str:
        return f"http://{await unit_address(ops_test, prometheus_app_name, unit)}:9090/baz"

    # AND the default job is healthy (its scrape url must have the path for this to work)
    prom_urls = [await prom_url(i) + "/api/v1/targets" for i in range(num_units)]
    for url in prom_urls:
        logger.info("Attmpting to fetch targets from url: %s", url)
        targets = urllib.request.urlopen(url, None, timeout=2).read().decode("utf8")
        logger.info("Response: %s", targets)
        assert '"health":"up"' in targets
        assert '"health":"down"' not in targets
