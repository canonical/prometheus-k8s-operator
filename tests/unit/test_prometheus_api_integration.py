"""Tests that assert PrometheusCharm is wired up correctly to be a prometheus-api provider."""

from typing import Optional, Tuple
from unittest.mock import MagicMock, PropertyMock, patch

from ops.testing import Relation, State

RELATION_NAME = "prometheus-api"
INTERFACE_NAME = "prometheus_api"

PROMETHEUS_URL = "http://internal.com/"
PROMETHEUS_INGRESS_URL = "http://www.ingress-url.com/"


def local_app_data_relation_state(
    leader: bool, local_app_data: Optional[dict] = None
) -> Tuple[Relation, State]:
    """Return a testing State that has a single relation with the given local_app_data."""
    if local_app_data is None:
        local_app_data = {}
    else:
        # Scenario might edit this dict, and it could be used elsewhere
        local_app_data = dict(local_app_data)

    relation = Relation(RELATION_NAME, INTERFACE_NAME, local_app_data=local_app_data)
    relations = [relation]

    state = State(
        relations=relations,
        leader=leader,
    )

    return relation, state


@patch("charm.PrometheusCharm.internal_url", PropertyMock(return_value=PROMETHEUS_URL))
@patch("charm.PrometheusCharm._set_alerts", MagicMock())
def test_provider_sender_sends_data_on_relation_joined(context, prometheus_container):
    """Tests that a charm using PrometheusApiProvider sends the correct data on a relation joined event."""
    # Arrange
    prometheus_api = Relation(RELATION_NAME, INTERFACE_NAME)
    relations = [
        prometheus_api,
    ]

    state = State(
        relations=relations,
        leader=True,
        containers=[prometheus_container],
    )

    # Act
    with context(context.on.relation_joined(prometheus_api), state=state) as manager:
        state_out = manager.run()
        expected = {
            "direct_url": PROMETHEUS_URL,
        }

    # Assert
    assert state_out.get_relation(prometheus_api.id).local_app_data == expected


@patch(
    "charm.PrometheusCharm.external_url",
    PropertyMock(return_value=PROMETHEUS_INGRESS_URL),
)
@patch("charm.PrometheusCharm.internal_url", PropertyMock(return_value=PROMETHEUS_URL))
@patch("charm.PrometheusCharm._set_alerts", MagicMock())
def test_provider_sender_sends_data_with_ingress_url_on_relation_joined(
    context, prometheus_container
):
    """Tests that a charm using PrometheusApiProvider with an external url sends the correct data."""
    # Arrange
    prometheus_api = Relation(RELATION_NAME, INTERFACE_NAME)
    relations = [prometheus_api]

    state = State(
        relations=relations,
        leader=True,
        containers=[prometheus_container],
    )

    # Act
    with context(context.on.relation_joined(prometheus_api), state=state) as manager:
        state_out = manager.run()
        expected = {
            "direct_url": PROMETHEUS_URL,
            "ingress_url": PROMETHEUS_INGRESS_URL,
        }

    # Assert
    assert state_out.get_relation(prometheus_api.id).local_app_data == expected


@patch("charm.PrometheusCharm.internal_url", PropertyMock(return_value=PROMETHEUS_URL))
@patch("charm.PrometheusCharm._set_alerts", MagicMock())
def test_provider_sends_data_on_config_changed(context, prometheus_container):
    """Tests that a charm using PrometheusApiProvider sends data on a config-changed event."""
    # Arrange
    prometheus_api = Relation(RELATION_NAME, INTERFACE_NAME)
    relations = [prometheus_api]

    state = State(
        relations=relations,
        leader=True,
        containers=[prometheus_container],
    )

    # Act
    with context(context.on.config_changed(), state=state) as manager:
        state_out = manager.run()
        expected = {
            "direct_url": PROMETHEUS_URL,
        }

    # Assert
    assert state_out.get_relation(prometheus_api.id).local_app_data == expected
