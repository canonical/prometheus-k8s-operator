# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

import dataclasses
import json

import yaml
from ops.model import ActiveStatus, BlockedStatus
from scenario import Relation, State

from charm import to_status


# To test that valid rules are written to disk and invalid rules are filtered out,
# we create two relations, a `receive-remote-write` relation and a `metrics-endpoint` relation, each with one valid and one invalid rule.
# The invalid rule has a syntax error in the expression to ensure it fails validation.
# To avoid having to write multiple similar alert rules, we use the helper function _alert_rules to generate the alert rules for each relation.
def _alert_rules(group_name: str, valid: bool) -> str:
    # This expr is invalid intentionally. It is missing a value after the '>' operator, which should cause validation to fail.
    invalid_expr = 'sum(rate({job="invalid"}[5m])) >'
    return json.dumps(
        {
            "groups": [
                {
                    "name": group_name,
                    "rules": [
                        {
                            "alert": f"{group_name}ValidA",
                            "expr": 'sum(rate({job="valid"}[5m])) > 0',
                            "for": "1m",
                            "labels": {"severity": "warning"},
                            "annotations": {"summary": "valid-a"},
                        },
                        {
                            "alert": f"{group_name}ValidB",
                            "expr": 'sum(rate({job="valid"}[10m])) > 0'
                            if valid
                            else invalid_expr,
                            "for": "1m",
                            "labels": {"severity": "warning"},
                            "annotations": {"summary": "valid-b"},
                        },
                    ],
                }
            ]
        }
    )


def _metadata(app_name: str) -> str:
    return json.dumps(
        {
            "model": "test",
            "model_uuid": "20ce8299-3634-4bef-8bd8-5ace6c8816b4",
            "application": app_name,
            "charm_name": f"{app_name}-charm",
        }
    )


VALID_SCRAPE_RELATION = Relation(
    "metrics-endpoint",
    remote_app_name="scrape-valid",
    remote_app_data={
        "alert_rules": _alert_rules("scrape-valid-group", valid=True),
        "scrape_metadata": _metadata("scrape-valid"),
    },
)

INVALID_SCRAPE_RELATION = Relation(
    "metrics-endpoint",
    remote_app_name="scrape-invalid",
    remote_app_data={
        "alert_rules": _alert_rules("scrape-invalid-group", valid=False),
        "scrape_metadata": _metadata("scrape-invalid"),
    },
)

VALID_REMOTE_WRITE_RELATION = Relation(
    "receive-remote-write",
    remote_app_name="remote-write-valid",
    remote_app_data={
        "alert_rules": _alert_rules("remote-write-valid-group", valid=True),
        "scrape_metadata": _metadata("remote-write-valid"),
    },
)

INVALID_REMOTE_WRITE_RELATION = Relation(
    "receive-remote-write",
    remote_app_name="remote-write-invalid",
    remote_app_data={
        "alert_rules": _alert_rules("remote-write-invalid-group", valid=False),
        "scrape_metadata": _metadata("remote-write-invalid"),
    },
)


def _written_group_names(context, state_out):
    """Helper function to read the alert rule group names that were written to disk."""
    fs = state_out.get_container("prometheus").get_filesystem(context)
    rules_dir = fs.joinpath("etc", "prometheus", "rules")
    if not rules_dir.exists():
        return set()

    written_group_names = set()
    for rule_file in sorted(path for path in rules_dir.iterdir() if path.is_file()):
        written_rules = yaml.safe_load(rule_file.read_text())
        for group in written_rules["groups"]:
            written_group_names.add(group["name"])
    return written_group_names


def _alert_rules_status(state_out):
    """Return only the alert-rule status, ignoring unrelated unit statuses like retention size."""
    charm_stored_state = next(
        stored_state
        for stored_state in state_out.stored_states
        if stored_state.owner_path == "PrometheusCharm"
    )
    return to_status(charm_stored_state.content["status"]["alert_rules"])


def test_valid_scrape_and_valid_remote_write_relations(context, prometheus_container):
    # GIVEN one valid scrape relation and one valid remote-write relation
    state_in = State(
        leader=True,
        relations=[VALID_SCRAPE_RELATION, VALID_REMOTE_WRITE_RELATION],
        containers=[prometheus_container],
    )

    # WHEN the relation changed event is processed
    state_out = context.run(context.on.relation_changed(VALID_SCRAPE_RELATION), state_in)

    # THEN all valid rules are written and the alert-rule status remains active
    assert _written_group_names(context, state_out) == {
        "scrape-valid-group",
        "remote-write-valid-group",
    }
    assert isinstance(_alert_rules_status(state_out), ActiveStatus)


def test_valid_scrape_and_invalid_remote_write_relations(context, prometheus_container):
    # GIVEN one valid scrape relation and one invalid remote-write relation
    state_in = State(
        leader=True,
        relations=[VALID_SCRAPE_RELATION, INVALID_REMOTE_WRITE_RELATION],
        containers=[prometheus_container],
    )

    # WHEN the relation changed event is processed
    state_out = context.run(context.on.relation_changed(VALID_SCRAPE_RELATION), state_in)

    # THEN only valid rules are written and the alert-rule status is blocked
    assert _written_group_names(context, state_out) == {"scrape-valid-group"}
    assert isinstance(_alert_rules_status(state_out), BlockedStatus)

    invalid_remote_write_relation_out = next(
        r for r in state_out.relations
        if r.endpoint == "receive-remote-write"
    )

    # AND WHEN the invalid remote-write relation is removed
    state_out = context.run(context.on.relation_broken(invalid_remote_write_relation_out), state_out)

    # THEN the charm status must be active since the remaining scrape relation is valid
    assert isinstance(_alert_rules_status(state_out), ActiveStatus)


def test_invalid_scrape_and_valid_remote_write_relations(context, prometheus_container):
    # GIVEN one invalid scrape relation and one valid remote-write relation
    state_in = State(
        leader=True,
        relations=[INVALID_SCRAPE_RELATION, VALID_REMOTE_WRITE_RELATION],
        containers=[prometheus_container],
    )

    # WHEN the relation changed event is processed
    state_out = context.run(context.on.relation_changed(INVALID_SCRAPE_RELATION), state_in)

    # THEN only valid rules are written and the alert-rule status is blocked
    assert _written_group_names(context, state_out) == {"remote-write-valid-group"}
    assert isinstance(_alert_rules_status(state_out), BlockedStatus)

    invalid_scrape_relation_out = next(
        r for r in state_out.relations
        if r.endpoint == "metrics-endpoint"
    )

    # AND WHEN the invalid scrape relation is removed
    state_out = context.run(context.on.relation_broken(invalid_scrape_relation_out), state_out)

    # THEN the charm status must be active since the remaining remote-write relation is valid
    assert isinstance(_alert_rules_status(state_out), ActiveStatus)


def test_invalid_scrape_and_invalid_remote_write_relations(context, prometheus_container):
    # GIVEN one invalid scrape relation and one invalid remote-write relation
    state_in = State(
        leader=True,
        relations=[INVALID_SCRAPE_RELATION, INVALID_REMOTE_WRITE_RELATION],
        containers=[prometheus_container],
    )

    # WHEN the relation changed event is processed
    state_out = context.run(context.on.relation_changed(INVALID_SCRAPE_RELATION), state_in)

    # THEN invalid relation rules are not written and the alert-rule status is blocked
    assert _written_group_names(context, state_out) == set()
    assert isinstance(_alert_rules_status(state_out), BlockedStatus)


def test_invalid_scrape_relation_becoming_valid_recovers_to_active(
    context, prometheus_container
):
    # GIVEN a scrape relation with invalid rules has already blocked the charm
    state_in = State(
        leader=True,
        relations=[INVALID_SCRAPE_RELATION],
        containers=[prometheus_container],
    )

    blocked_state = context.run(context.on.relation_changed(INVALID_SCRAPE_RELATION), state_in)

    assert isinstance(_alert_rules_status(blocked_state), BlockedStatus)

    # WHEN the same scrape relation updates its rules to become valid
    relation_after_invalid = blocked_state.get_relation(INVALID_SCRAPE_RELATION.id)
    now_valid_relation = dataclasses.replace(
        relation_after_invalid,
        remote_app_data={
            **relation_after_invalid.remote_app_data,
            "alert_rules": VALID_SCRAPE_RELATION.remote_app_data["alert_rules"],
        },
    )

    recovered_state = context.run(
        context.on.relation_changed(now_valid_relation),
        dataclasses.replace(blocked_state, relations=[now_valid_relation]),
    )

    # THEN the previous invalid status is cleared and valid rules are written
    assert _written_group_names(context, recovered_state) == {"scrape-valid-group"}
    assert isinstance(_alert_rules_status(recovered_state), ActiveStatus)


def test_invalid_remote_write_relation_becoming_valid_recovers_to_active(
    context, prometheus_container
):
    # GIVEN a remote-write relation with invalid rules has already blocked the charm
    state_in = State(
        leader=True,
        relations=[INVALID_REMOTE_WRITE_RELATION],
        containers=[prometheus_container],
    )

    blocked_state = context.run(
        context.on.relation_changed(INVALID_REMOTE_WRITE_RELATION), state_in
    )

    assert isinstance(_alert_rules_status(blocked_state), BlockedStatus)

    # WHEN the same remote-write relation updates its rules to become valid
    relation_after_invalid = blocked_state.get_relation(INVALID_REMOTE_WRITE_RELATION.id)
    now_valid_relation = dataclasses.replace(
        relation_after_invalid,
        remote_app_data={
            **relation_after_invalid.remote_app_data,
            "alert_rules": VALID_REMOTE_WRITE_RELATION.remote_app_data["alert_rules"],
        },
    )

    recovered_state = context.run(
        context.on.relation_changed(now_valid_relation),
        dataclasses.replace(blocked_state, relations=[now_valid_relation]),
    )

    # THEN the previous invalid status is cleared and valid rules are written
    assert _written_group_names(context, recovered_state) == {"remote-write-valid-group"}
    assert isinstance(_alert_rules_status(recovered_state), ActiveStatus)
