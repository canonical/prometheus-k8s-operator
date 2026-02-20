# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.


from helpers import begin_with_initial_hooks_isolated
from scenario import Context

"""Some brute-force tests, so that other tests can remain focused."""


def test_startup_shutdown_sequence(context: Context):
    state = begin_with_initial_hooks_isolated(context)
    state = context.run(context.on.update_status(), state)

    for peer_rel in state.get_relations("replicas"):
        state = context.run(context.on.relation_departed(peer_rel), state)

    state = context.run(context.on.stop(), state)
    context.run(context.on.remove(), state)
