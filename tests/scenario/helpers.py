# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

import dataclasses

from scenario import Container, Context, Exec, PeerRelation, Relation, State


def begin_with_initial_hooks_isolated(context: Context, *, leader: bool = True) -> State:
    container = Container(
        "prometheus",
        can_connect=False,
        execs={Exec(["update-ca-certificates", "--fresh"], return_code=0, stdout="")},
    )
    state = State(containers=[container])
    peer_rel = PeerRelation("prometheus-peers")

    state = context.run(context.on.install(), state)

    state = dataclasses.replace(state, relations=[peer_rel])
    state = context.run(context.on.relation_created(peer_rel), state)

    if leader:
        state = dataclasses.replace(state, leader=True)
        state = context.run(context.on.leader_elected(), state)
    else:
        state = dataclasses.replace(state, leader=False)
        state = context.run(context.on.leader_elected(), state)

    state = context.run(context.on.config_changed(), state)

    container = dataclasses.replace(container, can_connect=True)
    state = dataclasses.replace(state, containers=[container])
    state = context.run(context.on.pebble_ready(container), state)

    state = context.run(context.on.start(), state)

    return state


def add_relation_sequence(context: Context, state: State, relation: Relation):
    """Helper to simulate a relation-added sequence."""
    # TODO consider adding to scenario.sequences
    state_with_relation = dataclasses.replace(
        state,
        relations=state.relations.union([relation]),
    )
    state_after_relation_created = context.run(
        context.on.relation_created(relation), state_with_relation
    )

    # relation is not mutated!
    relation_1 = state_after_relation_created.get_relations(relation.endpoint)[0]
    state_after_relation_joined = context.run(
        context.on.relation_joined(relation_1), state_after_relation_created
    )

    relation_2 = state_after_relation_joined.get_relations(relation.endpoint)[0]
    state_after_relation_changed = context.run(
        context.on.relation_changed(relation_2), state_after_relation_joined
    )
    return state_after_relation_changed
