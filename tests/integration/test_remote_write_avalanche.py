#!/usr/bin/env python3
# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.


import json
import logging
import urllib.request
from pathlib import Path
from typing import Optional

import pytest
import yaml
from helpers import IPAddressWorkaround, unit_address  # type: ignore[import]

log = logging.getLogger(__name__)

METADATA = yaml.safe_load(Path("./metadata.yaml").read_text())


@pytest.mark.abort_on_fail
async def test_build_and_deploy(ops_test, prometheus_charm):
    """Deploy the charm-under-test together with related charms."""
    await ops_test.model.set_config({"logging-config": "<root>=WARNING; unit=DEBUG"})
    resources = {"prometheus-image": METADATA["resources"]["prometheus-image"]["upstream-source"]}

    # deploy prometheus
    async with IPAddressWorkaround(ops_test):
        await ops_test.model.deploy(prometheus_charm, resources=resources, application_name="prom")
        await ops_test.model.wait_for_idle(apps=["prom"], status="active")

    # deploy avalanche
    await ops_test.model.deploy("ch:avalanche-k8s", application_name="av", channel="edge")
    await ops_test.model.wait_for_idle(apps=["av"], status="active")


@pytest.mark.abort_on_fail
async def test_charm_successfully_relates_to_avalanche(ops_test):
    await ops_test.model.add_relation("prom:receive-remote-write", "av:receive-remote-write")
    await ops_test.model.wait_for_idle(apps=["av", "prom"], status="active")


async def test_avalanche_metrics_are_ingested_by_prometheus(ops_test):
    prom_url = f"http://{await unit_address(ops_test, 'prom', 0)}:9090/api/v1/labels"

    response = urllib.request.urlopen(prom_url, data=None, timeout=5.0)
    assert response.code == 200

    # response looks like this:
    # {
    #   "status": "success",
    #   "data": [
    #     "__name__",
    #     "alertname",
    #     "alertstate",
    #     ...
    #     "juju_application",
    #     "juju_charm",
    #     "juju_model",
    #     "juju_model_uuid",
    #     "label_key_kkkkk_0",
    #     "label_key_kkkkk_1",
    #     "label_key_kkkkk_2",
    #     ...
    #     "version"
    #   ]
    # }

    labels_response = json.loads(response.read())
    assert "label_key_kkkkk_0" in labels_response["data"]


@pytest.mark.abort_on_fail
async def test_avalanche_alerts_ingested_by_prometeus(ops_test):
    prom_url = f"http://{await unit_address(ops_test, 'prom', 0)}:9090/api/v1/rules?type=alert"

    response = urllib.request.urlopen(prom_url, data=None, timeout=5.0)
    assert response.code == 200

    # response looks like this:
    # {"status":"success","data":{"groups":[]}

    alerts_response = json.loads(response.read())
    assert len(alerts_response["data"]["groups"]) > 0


async def test_avalanche_always_firing_alarm_is_firing(ops_test):
    async def get_alert() -> Optional[dict]:
        prom_url = f"http://{await unit_address(ops_test, 'prom', 0)}:9090/api/v1/alerts"

        response = urllib.request.urlopen(prom_url, data=None, timeout=5.0)
        assert response.code == 200

        # response looks like this:
        #
        # {
        #   "status": "success",
        #   "data": {
        #     "alerts": [
        #       {
        #         "labels": {
        #           "alertname": "AlwaysFiring",
        #           "job": "non_existing_job",
        #           "juju_application": "avalanche-k8s",
        #           "juju_charm": "avalanche-k8s",
        #           "juju_model": "remotewrite",
        #           "juju_model_uuid": "5d2582f6-f8c9-4496-835b-675431d1fafe",
        #           "severity": "High"
        #         },
        #         "annotations": {
        #           "description": " of job non_existing_job is firing the dummy alarm.",
        #           "summary": "Instance  dummy alarm (always firing)"
        #         },
        #         "state": "firing",
        #         "activeAt": "2022-01-13T18:53:12.808550042Z",
        #         "value": "1e+00"
        #       }
        #     ]
        #   }
        # }

        alerts_response = json.loads(response.read())
        alerts = alerts_response["data"]["alerts"]
        if len(alerts) == 0:
            return None
        return alerts[0]  # there is only one alert

    await ops_test.model.block_until_with_coroutine(get_alert, timeout=60)

    alert = await get_alert()
    assert alert["labels"]["alertname"] == "AlwaysFiring"
    assert alert["state"] == "firing"
