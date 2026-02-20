# # Copyright 2022 Canonical Ltd.
# # See LICENSE file for licensing details.
# from unittest.mock import patch

import json
from unittest.mock import patch

import pytest
from charms.tempo_coordinator_k8s.v0.charm_tracing import charm_tracing_disabled
from interface_tester import InterfaceTester
from scenario import Container, Exec, Relation, State

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


prometheus_container = Container(
    name="prometheus",
    can_connect=True,
    execs={Exec(["update-ca-certificates", "--fresh"], return_code=0, stdout="")},
)

grafana_source_relation = Relation(
    "grafana-source",
    remote_app_data={
        "datasource_uids": json.dumps({"prometheus/0": "01234"}),
        "grafana_uid": "5678",
    },
)

grafana_datasource_exchange_relation = Relation(
    "send-datasource",
    remote_app_data={
        "datasources": json.dumps([{"type": "prometheus", "uid": "01234", "grafana_uid": "5678"}])
    },
)


def begin_with_initial_hooks_isolated() -> State:
    state = State(containers=[prometheus_container], leader=True)
    return state


@pytest.fixture
def interface_tester(interface_tester: InterfaceTester, prometheus_charm):
    interface_tester.configure(
        charm_type=prometheus_charm,
        state_template=begin_with_initial_hooks_isolated(),
    )
    yield interface_tester


@pytest.fixture
def grafana_datasource_exchange_tester(interface_tester: InterfaceTester, prometheus_charm):
    interface_tester.configure(
        charm_type=prometheus_charm,
        state_template=State(
            leader=True,
            containers=[prometheus_container],
            relations=[grafana_source_relation, grafana_datasource_exchange_relation],
        ),
    )
    yield interface_tester
