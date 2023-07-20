# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

from unittest.mock import patch

import pytest
from helpers import add_relation_sequence, begin_with_initial_hooks_isolated
from scenario import Context, Relation, State

"""Some brute-force tests, so that other tests can remain focused."""


def test_startup_shutdown_sequence(context: Context):
    state = begin_with_initial_hooks_isolated(context)
    state = context.run("update-status", state)

    for peer_rel in state.get_relations("replicas"):
        state = context.run(peer_rel.departed_event, state)

    state = context.run("stop", state)
    context.run("remove", state)
