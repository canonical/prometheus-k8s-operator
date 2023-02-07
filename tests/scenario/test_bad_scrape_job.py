#!/usr/bin/env python3
# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

import json

from unittest.mock import patch, MagicMock

from ops.framework import BoundEvent
from scenario import State, Relation, Container
from scenario.state import _CharmSpec

from charm import PrometheusCharm

EXTRA_FILES = ['cos-tool-amd64']

bad_scrape_job = json.dumps([{
    "metrics_path": "/metrics",
    "static_configs": [{"targets": ["*:3100"]}],
    "sample_limit": {"not_a_key": "not_a_value"}
}])

k8s_resource_multipatch = patch.multiple(
    "charm.KubernetesComputeResourcesPatch",
    _namespace="test-namespace",
    _patch=lambda *a, **kw: True,
    is_ready=lambda *a, **kw: True,
)

@patch("charm.KubernetesServicePatch")
@k8s_resource_multipatch
@patch("charms.observability_libs.v0.kubernetes_compute_resources_patch.ResourcePatcher")
def test_bad_config(*_):
    container = Container(
        name="prometheus",
        can_connect=True,
    )
    relation = Relation(
        endpoint="metrics-endpoint",
        interface="prometheus_scrape",
        remote_app_name="remote-app",
        remote_app_data={
            "alert_rules": [],
            "scrape_jobs": [bad_scrape_job],
        }
    )
    state = State(relations=[relation], containers=[container])
    result_state = state.trigger(charm_type=PrometheusCharm, event=relation.changed_event, extra_files=EXTRA_FILES)
    assert "scrape_job_errors" in result_state.relations[0].local_app_data.get("event", {})
