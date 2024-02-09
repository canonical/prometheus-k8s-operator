# # Copyright 2022 Canonical Ltd.
# # See LICENSE file for licensing details.
# from unittest.mock import patch

from unittest.mock import patch

import pytest
from charm import PrometheusCharm
from interface_tester import InterfaceTester
from scenario import Container, ExecOutput, State


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


def begin_with_initial_hooks_isolated() -> State:
    container = Container(
        "prometheus",
        can_connect=True,
        exec_mock={("update-ca-certificates", "--fresh"): ExecOutput(return_code=0, stdout="")},
    )
    state = State(containers=[container], leader=True)
    return state


@pytest.fixture
def interface_tester(interface_tester: InterfaceTester, prometheus_charm):
    interface_tester.configure(
        charm_type=prometheus_charm,
        state_template=begin_with_initial_hooks_isolated(),
    )
    yield interface_tester
