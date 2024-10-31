#!/usr/bin/env python3
# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

import logging

import pytest
from helpers import (
    check_prometheus_is_ready,
    get_job_config_for,
    get_prometheus_config,
    get_prometheus_rules,
    get_rules_for,
    initial_workload_is_ready,
    oci_image,
)

from .juju import Juju

logger = logging.getLogger(__name__)

prometheus_app_name = "prometheus"
tester_app_name = "prometheus-tester"
app_names = [prometheus_app_name, tester_app_name]

initial_config = None
initial_rules = None


@pytest.mark.abort_on_fail
def test_prometheus_scrape_relation_with_prometheus_tester(
    prometheus_charm, prometheus_tester_charm
):
    """Test basic funcapp_namestionality of prometheus_scrape relation interface."""

    Juju.deploy(prometheus_charm, alias=prometheus_app_name, resources={"prometheus-image": prometheus_oci_image}, trust=True)
    Juju.deploy(prometheus_tester_charm, alias=tester_app_name, resources={"prometheus-tester-image": prometheus_tester_oci_image})
    Juju.wait_for_idle(app_names, timeout=1000)

    assert initial_workload_is_ready(app_names)
    assert check_prometheus_is_ready(prometheus_app_name, 0)

    global initial_config, initial_rules
    initial_config = get_prometheus_config(prometheus_app_name, 0)
    initial_rules = get_prometheus_rules(prometheus_app_name, 0)

    Juju.integrate(
        f"{prometheus_app_name}:metrics-endpoint", f"{tester_app_name}:metrics-endpoint"
    )
    Juju.wait_for_idle(app_names, timeout=1000)

    config_with_relation = get_prometheus_config(prometheus_app_name, 0)
    tester_job = get_job_config_for(tester_app_name, config_with_relation)
    assert tester_job != {}

    rules_with_relation = get_prometheus_rules(prometheus_app_name, 0)
    tester_rules = get_rules_for(tester_app_name, rules_with_relation)
    assert len(tester_rules) == 1


async def test_alert_rule_path_can_be_changed(prometheus_tester_charm):
    """Ensure scrape alert rules can be updated.

    This test upgrades the metrics provider charm and checks that
    updates to alert rules are propagated correctly.
    """
    # Change the alert rule path and ensure that there are 2
    # after refreshing so they are reloaded
    Juju.config(tester_app_name, ["alert-rules-path=src/with_extra_alert_rule"])
    Juju.wait_for_idle(app_names)

    resources = {
            "prometheus-tester-image": oci_image(
                "./tests/integration/prometheus-tester/metadata.yaml",
                "prometheus-tester-image",
            )
        }
    Juju.refresh(tester_app_name, prometheus_tester_charm, resources)
    Juju.wait_for_idle(app_names)

    rules_with_relation = get_prometheus_rules(prometheus_app_name, 0)
    tester_rules = get_rules_for(tester_app_name, rules_with_relation)
    assert len(tester_rules) == 2
