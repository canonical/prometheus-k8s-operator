# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Feature: Charm forwards logs to Loki via the logging relation."""

import dataclasses

import pytest
from helpers import add_relation_sequence, begin_with_initial_hooks_isolated
from scenario import Relation, State


class TestLoggingRelation:
    """Scenario: The charm is deployed and a logging relation is added."""

    def test_charm_starts_with_logging_relation(self, context):
        """The charm should initialize correctly when a logging relation is added."""
        state = begin_with_initial_hooks_isolated(context, leader=True)

        logging_rel = Relation("logging")
        state = add_relation_sequence(context, state, logging_rel)

        # Verify the charm is still functional after adding the logging relation
        state = context.run(context.on.update_status(), state)
        assert state.unit_status.name != "error"

    @pytest.mark.parametrize("event_type", ["relation_joined", "relation_changed"])
    def test_logging_relation_hooks_do_not_error(self, context, prometheus_container, event_type):
        """The charm should remain active through relation_joined and relation_changed."""
        logging_rel = Relation("logging")
        state = State(
            containers=[prometheus_container],
            relations=[logging_rel],
            leader=True,
        )

        state = context.run(getattr(context.on, event_type)(logging_rel), state)
        assert state.unit_status.name != "error"

    def test_logging_relation_departed(self, context, prometheus_container):
        """The charm should remain active after a logging relation is departed."""
        logging_rel = Relation("logging")
        state = State(
            containers=[prometheus_container],
            relations=[logging_rel],
            leader=True,
        )

        state = context.run(context.on.relation_departed(logging_rel), state)
        assert state.unit_status.name != "error"

    def test_logging_relation_broken(self, context, prometheus_container):
        """The charm should remain active after a logging relation is broken."""
        logging_rel = Relation("logging")
        state = State(
            containers=[prometheus_container],
            relations=[logging_rel],
            leader=True,
        )

        state = context.run(context.on.relation_broken(logging_rel), state)
        assert state.unit_status.name != "error"

    def test_logging_full_lifecycle(self, context):
        """The charm should remain active through the full logging relation lifecycle."""
        state = begin_with_initial_hooks_isolated(context, leader=True)

        # Add the relation (fires created, joined, changed)
        logging_rel = Relation("logging")
        state = add_relation_sequence(context, state, logging_rel)
        assert state.unit_status.name != "error"

        # Depart the relation
        logging_rel = state.get_relations("logging")[0]
        state = context.run(context.on.relation_departed(logging_rel), state)
        assert state.unit_status.name != "error"

        # Break the relation
        state = context.run(context.on.relation_broken(logging_rel), state)
        assert state.unit_status.name != "error"

        # Remove the relation from state and verify charm still works
        state = dataclasses.replace(
            state,
            relations=[r for r in state.relations if r.endpoint != "logging"],
        )
        state = context.run(context.on.update_status(), state)
        assert state.unit_status.name != "error"
