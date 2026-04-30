# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

"""Feature: Charm forwards logs to Loki via the logging relation."""

from helpers import add_relation_sequence, begin_with_initial_hooks_isolated
from scenario import Relation


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
