# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""Tests for SLO integration functionality."""

from ops.testing import Relation, State

RELATION_NAME = "slos"
INTERFACE_NAME = "slo"

SLO_CONFIG = """
version: prometheus/v1
service: test-service
labels:
  team: test-team
slos:
  - name: availability
    objective: 99.9
    description: "Service availability"
    sli:
      events:
        error_query: 'sum(rate(http_requests_total{status=~"5.."}[{{.window}}]))'
        total_query: 'sum(rate(http_requests_total[{{.window}}]))'
    alerting:
      name: TestServiceHighErrorRate
      labels:
        severity: critical
      annotations:
        summary: "Test service is experiencing high error rate"
"""


def test_slo_provider_publishes_config_on_pebble_ready(context, prometheus_container):
    """Test that SLO config is published when the workload is ready."""
    # Arrange
    slo_relation = Relation(RELATION_NAME, INTERFACE_NAME)
    relations = [slo_relation]

    state = State(
        relations=relations,
        leader=True,
        containers=[prometheus_container],
        config={"slos": SLO_CONFIG},
    )

    # Act - pebble_ready triggers _configure
    with context(context.on.pebble_ready(prometheus_container), state=state) as manager:
        state_out = manager.run()

    # Assert
    # The SLO provider should publish the config to app databag
    relation_data = state_out.get_relation(slo_relation.id).local_app_data
    assert "slo_spec" in relation_data
    # The library processes the YAML, so we just check it's not empty
    assert relation_data["slo_spec"]


def test_slo_provider_publishes_config_on_config_changed(context, prometheus_container):
    """Test that SLO config is published when config changes."""
    # Arrange
    slo_relation = Relation(RELATION_NAME, INTERFACE_NAME)
    relations = [slo_relation]

    state = State(
        relations=relations,
        leader=True,
        containers=[prometheus_container],
        config={"slos": SLO_CONFIG},
    )

    # Act
    with context(context.on.config_changed(), state=state) as manager:
        state_out = manager.run()

    # Assert
    relation_data = state_out.get_relation(slo_relation.id).local_app_data
    assert "slo_spec" in relation_data
    assert relation_data["slo_spec"]


def test_slo_provider_does_not_publish_without_config(context, prometheus_container):
    """Test that nothing is published when slos config is empty."""
    # Arrange
    slo_relation = Relation(RELATION_NAME, INTERFACE_NAME)
    relations = [slo_relation]

    state = State(
        relations=relations,
        leader=True,
        containers=[prometheus_container],
        config={"slos": ""},  # Empty config
    )

    # Act
    with context(context.on.config_changed(), state=state) as manager:
        state_out = manager.run()

    # Assert
    relation_data = state_out.get_relation(slo_relation.id).local_app_data
    # Should not publish anything
    assert "slo_spec" not in relation_data or relation_data.get("slo_spec") == ""


def test_slo_provider_does_not_publish_when_not_leader(context, prometheus_container):
    """Test that non-leader units do not publish SLO config."""
    # Arrange
    slo_relation = Relation(RELATION_NAME, INTERFACE_NAME)
    relations = [slo_relation]

    state = State(
        relations=relations,
        leader=False,  # Not leader
        containers=[prometheus_container],
        config={"slos": SLO_CONFIG},
    )

    # Act
    with context(context.on.config_changed(), state=state) as manager:
        state_out = manager.run()

    # Assert
    relation_data = state_out.get_relation(slo_relation.id).local_app_data
    # Non-leader should not publish
    assert "slo_spec" not in relation_data or relation_data.get("slo_spec") == ""


def test_slo_provider_does_nothing_without_relation(context, prometheus_container):
    """Test that SLO provider doesn't crash when relation doesn't exist."""
    # Arrange - no SLO relation
    state = State(
        relations=[],
        leader=True,
        containers=[prometheus_container],
        config={"slos": SLO_CONFIG},
    )

    # Act - should not crash
    with context(context.on.config_changed(), state=state) as manager:
        state_out = manager.run()

    # Assert - should complete successfully
    assert state_out is not None


def test_slo_config_updated_on_relation(context, prometheus_container):
    """Test that updating SLO config updates the relation data."""
    # Arrange
    slo_relation = Relation(RELATION_NAME, INTERFACE_NAME)
    relations = [slo_relation]

    initial_config = """version: prometheus/v1
service: test-initial
labels:
  team: test-team
slos:
  - name: test-slo
    objective: 99.5
    sli:
      events:
        error_query: 'sum(rate(errors[{{.window}}]))'
        total_query: 'sum(rate(requests[{{.window}}]))'
    alerting:
      name: TestAlert
      labels:
        severity: warning
"""
    updated_config = """version: prometheus/v1
service: test-updated
labels:
  team: test-team
slos:
  - name: test-slo-updated
    objective: 99.9
    sli:
      events:
        error_query: 'sum(rate(errors[{{.window}}]))'
        total_query: 'sum(rate(requests[{{.window}}]))'
    alerting:
      name: TestAlertUpdated
      labels:
        severity: critical
"""

    # Start with initial config
    state = State(
        relations=relations,
        leader=True,
        containers=[prometheus_container],
        config={"slos": initial_config},
    )

    # Act - First update
    with context(context.on.config_changed(), state=state) as manager:
        state_out = manager.run()

    relation_data = state_out.get_relation(slo_relation.id).local_app_data
    assert "slo_spec" in relation_data
    initial_result = relation_data.get("slo_spec")
    assert initial_result  # Should have content

    # Update config
    state_updated = State(
        relations=relations,
        leader=True,
        containers=[prometheus_container],
        config={"slos": updated_config},
    )

    # Act - Second update
    with context(context.on.config_changed(), state=state_updated) as manager:
        state_out = manager.run()

    # Assert - should have new config
    relation_data = state_out.get_relation(slo_relation.id).local_app_data
    assert "slo_spec" in relation_data
    updated_result = relation_data.get("slo_spec")
    assert updated_result
    # The content should be different after the update
    assert "test-updated" in updated_result
