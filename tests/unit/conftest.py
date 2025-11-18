# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

from unittest.mock import patch

import pytest
from charms.tempo_coordinator_k8s.v0.charm_tracing import charm_tracing_disabled
from scenario import Container, Context, Exec

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
        with charm_tracing_disabled():
            yield PrometheusCharm


@pytest.fixture(scope="function")
def context(prometheus_charm):
    return Context(charm_type=prometheus_charm, juju_version="3.0.3")


@pytest.fixture(scope="function")
def prometheus_container():
    return Container(
        "prometheus",
        can_connect=True,
        execs={Exec(["update-ca-certificates", "--fresh"], return_code=0, stdout="")},
    )


@pytest.fixture(autouse=True)
def patch_buffer_file_for_charm_tracing(tmp_path):
    with patch(
        "charms.tempo_coordinator_k8s.v0.charm_tracing.BUFFER_DEFAULT_CACHE_FILE_NAME",
        str(tmp_path / "foo.json"),
    ):
        yield
