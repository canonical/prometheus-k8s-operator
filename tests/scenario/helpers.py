# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

from scenario import Container, Context, Network, PeerRelation, Relation, State


def begin_with_initial_hooks_isolated(context: Context, *, leader: bool = True) -> State:
    container = Container("prometheus", can_connect=False)
    state = State(containers=[container])
    peer_rel = PeerRelation("prometheus-peers")

    state = context.run("install", state)

    state = state.replace(relations=[peer_rel])
    state = context.run(peer_rel.created_event, state)

    if leader:
        state = state.replace(leader=True)
        state = context.run("leader-elected", state)
    else:
        state = state.replace(leader=False)
        state = context.run("leader-settings-changed", state)

    state = context.run("config-changed", state)

    container = container.replace(can_connect=True)
    state = state.replace(containers=[container])
    state = context.run(container.pebble_ready_event, state)

    state = context.run("start", state)

    return state


def add_relation_sequence(context: Context, state: State, relation: Relation):
    """Helper to simulate a relation-added sequence."""
    # TODO consider adding to scenario.sequences
    state_with_relation = state.replace(
        relations=state.relations + [relation],
        networks=state.networks + [Network.default(relation.endpoint)],
    )
    state_after_relation_created = context.run(relation.created_event, state_with_relation)
    state_after_relation_joined = context.run(relation.joined_event, state_after_relation_created)
    state_after_relation_changed = context.run(relation.changed_event, state_after_relation_joined)
    return state_after_relation_changed
