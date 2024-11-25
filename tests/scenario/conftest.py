# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

from unittest.mock import patch

import pytest
from scenario import Context

from charm import PrometheusCharm


def tautology(*_, **__) -> bool:
    return True


@pytest.fixture
def prometheus_charm():
    with patch("lightkube.core.client.GenericSyncClient"), patch.multiple(
        "charm.KubernetesComputeResourcesPatch",
        _namespace="test-namespace",
        _patch=tautology,
        is_ready=tautology,
    ), patch("prometheus_client.Prometheus.reload_configuration"), patch.multiple(
        "charm.PrometheusCharm",
        _promtool_check_config=lambda *_: ("stdout", ""),
        _prometheus_version="0.1.0",
    ):
        yield PrometheusCharm


@pytest.fixture(autouse=True)
def disable_charm_tracing_buffer():
    with patch("charms.tempo_coordinator_k8s.v0.charm_tracing._Buffer.save", lambda *_: None):
        yield


@pytest.fixture(scope="function")
def context(prometheus_charm):
    return Context(charm_type=prometheus_charm, juju_version="3.0.3")
