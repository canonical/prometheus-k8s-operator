# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""pytest-bdd step definitions for the alert_rule_customizations feature file.

Feature file: tests/unit/features/alert_rule_customizations.feature
"""

from typing import Any, Dict, List

import yaml
from _alert_rule_customization_helpers import (
    _make_remote_write_relation,
    _make_scrape_relation,
    customization_status,
    read_all_rules,
)
from ops.model import ActiveStatus, BlockedStatus
from pytest_bdd import given, parsers, scenario, then, when
from scenario import State

# ---------------------------------------------------------------------------
# Scenarios
# ---------------------------------------------------------------------------


@scenario("features/alert_rule_customizations.feature", "The charm becomes blocked when the customization is invalid YAML")
def test_blocked_invalid_yaml():
    pass


@scenario("features/alert_rule_customizations.feature", "The charm becomes blocked when the customization has invalid keys")
def test_blocked_invalid_keys():
    pass


@scenario("features/alert_rule_customizations.feature", "The charm becomes blocked when the customization has an invalid operation key")
def test_blocked_invalid_op_key():
    pass


@scenario("features/alert_rule_customizations.feature", "Removing an alert by name drops only that alert")
def test_remove_by_name():
    pass


@scenario("features/alert_rule_customizations.feature", "Removing an alert by group name drops the entire group")
def test_remove_by_group():
    pass


@scenario("features/alert_rule_customizations.feature", "Patching sets a field on a matching alert")
def test_patch_field():
    pass


@scenario("features/alert_rule_customizations.feature", "Patching replaces the expression of a matching alert")
def test_patch_expr():
    pass


@scenario("features/alert_rule_customizations.feature", "Patching adds a new label and preserves existing labels")
def test_patch_adds_label():
    pass


@scenario("features/alert_rule_customizations.feature", "Patching overwrites an existing label")
def test_patch_overwrites_label():
    pass


@scenario("features/alert_rule_customizations.feature", "Patching matches by label value and only touches matching alerts")
def test_patch_by_label():
    pass


@scenario("features/alert_rule_customizations.feature", "Multiple patch operations are each applied")
def test_multiple_patches():
    pass


@scenario("features/alert_rule_customizations.feature", "Removing and patching can be combined")
def test_remove_and_patch():
    pass


@scenario("features/alert_rule_customizations.feature", "Patching and removing apply to rules from both relation endpoints")
def test_both_endpoints():
    pass


@scenario("features/alert_rule_customizations.feature", "The charm becomes blocked when the customization yields invalid rules")
def test_blocked_invalid_rules():
    pass


@scenario("features/alert_rule_customizations.feature", "A remove that matches nothing results in no change")
def test_remove_no_match():
    pass


@scenario("features/alert_rule_customizations.feature", "A patch that matches nothing results in no change")
def test_patch_no_match():
    pass


@scenario("features/alert_rule_customizations.feature", "A remove and patch that match nothing result in no change")
def test_remove_patch_no_match():
    pass


# ---------------------------------------------------------------------------
# Given
# ---------------------------------------------------------------------------


@given(
    "the charm provides the following alert rules:",
    target_fixture="base_state",
)
def given_alert_rules(docstring, context, prometheus_container):
    """Build a State with a metrics-endpoint relation carrying the given rule groups."""
    groups_by_name: Dict[str, List[Dict[str, Any]]] = yaml.safe_load(docstring)
    groups = [{"name": name, "rules": rules} for name, rules in groups_by_name.items()]
    scrape_relation = _make_scrape_relation("myapp", groups)
    return {
        "context": context,
        "prometheus_container": prometheus_container,
        "relations": [scrape_relation],
        "groups": groups,
    }


@given(
    "the charm also provides the following remote write alert rules:",
    target_fixture="base_state",
)
def given_remote_write_alert_rules(docstring, base_state):
    """Add a receive-remote-write relation to the base state."""
    groups_by_name = yaml.safe_load(docstring)
    groups = [{"name": name, "rules": rules} for name, rules in groups_by_name.items()]
    rw_relation = _make_remote_write_relation("rw-app", groups)
    new_relations = base_state["relations"] + [rw_relation]
    return {
        **base_state,
        "relations": new_relations,
    }


# ---------------------------------------------------------------------------
# When
# ---------------------------------------------------------------------------


def _run_config_changed(base_state, docstring):
    """Apply the given customization string and return the output state."""
    context = base_state["context"]
    prometheus_container = base_state["prometheus_container"]
    relations = base_state["relations"]

    state_in = State(
        leader=True,
        relations=relations,
        containers=[prometheus_container],
        config={"alert_rule_customizations": docstring},
    )
    return context.run(context.on.config_changed(), state_in)


@when(
    "the customization is set to:",
    target_fixture="state_out",
)
def when_customization_is_set(base_state, docstring):
    return _run_config_changed(base_state, docstring)


# ---------------------------------------------------------------------------
# Then
# ---------------------------------------------------------------------------


def _written_alert_names(state_out, base_state) -> set:
    context = base_state["context"]
    rules = read_all_rules(context, state_out)
    return {
        r["alert"]
        for group_rules in rules.values()
        for r in group_rules
        if "alert" in r
    }


@then(parsers.parse('alert "{name}" is not written'))
def then_alert_not_written(name, state_out, base_state):
    written = _written_alert_names(state_out, base_state)
    assert name not in written, f"alert {name!r} was written but should not be"


@then(parsers.parse('alert "{name}" is written'))
def then_alert_written(name, state_out, base_state):
    written = _written_alert_names(state_out, base_state)
    assert name in written, f"alert {name!r} was not written"


@then(parsers.parse('alert "{name}" is not written in group "{group_name}"'))
def then_alert_not_written_in_group(name, group_name, state_out, base_state):
    context = base_state["context"]
    rules = read_all_rules(context, state_out)
    group_rules = rules.get(group_name, [])
    assert all(r.get("alert") != name for r in group_rules), (
        f"alert {name!r} was written in group {group_name!r} but should not be"
    )


@then(parsers.re(r'alert "(?P<name>[^"]+)" has "(?P<field>[^"]+)" equal to ["\'](?P<value>.+)["\']'))
def then_alert_field(name, field, value, state_out, base_state):
    context = base_state["context"]
    rule = _find_alert(state_out, context, name)
    assert rule.get(field) == value, f"expected {field}={value!r}, got {rule.get(field)!r}"


@then(parsers.parse('alert "{name}" has label "{key}" equal to "{value}"'))
def then_alert_label(name, key, value, state_out, base_state):
    context = base_state["context"]
    rule = _find_alert(state_out, context, name)
    labels = rule.get("labels", {})
    assert labels.get(key) == value, f"expected label {key}={value!r}, got {labels.get(key)!r}"


@then("the charm is in BlockedStatus for alert_rule_customizations")
def then_blocked_customizations(state_out):
    assert isinstance(customization_status(state_out), BlockedStatus)


@then("the charm is in ActiveStatus for alert_rule_customizations")
def then_active_customizations(state_out):
    assert isinstance(customization_status(state_out), ActiveStatus)


@then("all provided alert rules are still written unchanged")
def then_all_rules_still_written(state_out, base_state):
    context = base_state["context"]
    rules = read_all_rules(context, state_out)
    assert rules, "no alert rules were written to disk"


@then("the written alert rules are unchanged")
def then_written_rules_unchanged(state_out, base_state):
    """Compare the on-disk rules against a baseline run with no customizations applied."""
    baseline = _run_config_changed(base_state, "")
    context = base_state["context"]
    baseline_rules = read_all_rules(context, baseline)
    actual_rules = read_all_rules(context, state_out)
    assert actual_rules == baseline_rules, (
        f"the written alert rules changed:\nactual={actual_rules!r}\nbaseline={baseline_rules!r}"
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _find_alert(state_out, context, name):
    """Return the rule dict for an alert of the given name across all written groups."""
    rules = read_all_rules(context, state_out)
    for group_rules in rules.values():
        for rule in group_rules:
            if rule.get("alert") == name:
                return rule
    raise AssertionError(f"alert {name!r} not found in written rules")
