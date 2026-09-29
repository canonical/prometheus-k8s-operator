# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""pytest-bdd step definitions for the alert_rule_customizations feature file.

Feature file: tests/unit/features/alert_rule_customizations.feature
"""

import pytest
import yaml
from _alert_rule_customization_helpers import (
    _make_remote_write_relation,
    _make_scrape_relation,
    customization_status,
    read_all_rules,
)
from ops.model import ActiveStatus, BlockedStatus
from pytest_bdd import given, parsers, scenarios, then, when
from scenario import State

scenarios("features/alert_rule_customizations.feature")


# ---------------------------------------------------------------------------
# Given
# ---------------------------------------------------------------------------


@given(
    parsers.parse("the charm provides the following alert rules:\n{docstring}"),
    target_fixture="scrape_relation",
)
def given_charm_provides_alert_rules(docstring):
    """Build a metrics-endpoint relation carrying the rule groups from the docstring."""
    groups = _docstring_to_groups(docstring)
    return _make_scrape_relation("myapp", groups)


@given(
    parsers.parse("the charm also provides the following remote write alert rules:\n{docstring}"),
    target_fixture="remote_write_relation",
)
def given_charm_provides_remote_write_alert_rules(docstring):
    """Add a receive-remote-write relation to the scenario."""
    groups = _docstring_to_groups(docstring)
    return _make_remote_write_relation("rw-app", groups)


@pytest.fixture
def remote_write_relation():
    """Present by default; overridden by the remote-write Given step when used."""
    return


@pytest.fixture
def relations(scrape_relation, remote_write_relation):
    """Assemble the full list of relations to attach to the charm state."""
    if remote_write_relation is not None:
        return [scrape_relation, remote_write_relation]
    return [scrape_relation]


# ---------------------------------------------------------------------------
# When
# ---------------------------------------------------------------------------


def _run_config_changed(context, prometheus_container, config, relations):
    """Run config_changed through the charm for the given relations and config."""
    state_in = State(
        leader=True,
        relations=relations,
        containers=[prometheus_container],
        config=config,
    )
    return context.run(context.on.config_changed(), state_in)


@when(
    parsers.parse("the customization is applied:\n{docstring}"),
    target_fixture="state_out",
)
def when_customization_is_applied(docstring, relations, context, prometheus_container):
    """Set the customization config and run config_changed through the charm."""
    return _run_config_changed(
        context,
        prometheus_container,
        {"alert_rule_customizations": docstring},
        relations,
    )


@when(
    parsers.parse('the customization is set to invalid YAML: "{config_string}"'),
    target_fixture="state_out",
)
def when_customization_is_invalid_yaml(config_string, relations, context, prometheus_container):
    return _run_config_changed(
        context,
        prometheus_container,
        {"alert_rule_customizations": config_string},
        relations,
    )


@when(
    "the customization contains an unknown top-level key",
    target_fixture="state_out",
)
def when_customization_unknown_top_level_key(relations, context, prometheus_container):
    config = {
        "alert_rule_customizations": (
            "replace:\n"
            "  - where:\n"
            "      alert: AlphaFiring\n"
        )
    }
    return _run_config_changed(context, prometheus_container, config, relations)


@when(
    "the customization contains an invalid key within an operation",
    target_fixture="state_out",
)
def when_customization_invalid_operation_key(relations, context, prometheus_container):
    config = {
        "alert_rule_customizations": (
            "patch:\n"
            "  - where:\n"
            "      alert: AlphaFiring\n"
            "    set:\n"
            "      duration: 5m\n"
        )
    }
    return _run_config_changed(context, prometheus_container, config, relations)


# ---------------------------------------------------------------------------
# Then
# ---------------------------------------------------------------------------


def _written_alert_names(state_out, context) -> set:
    rules = read_all_rules(context, state_out)
    return {
        r["alert"]
        for group_rules in rules.values()
        for r in group_rules
        if "alert" in r
    }


@then(parsers.parse('alert "{name}" is not written'))
def then_alert_not_written(name, state_out, context):
    written = _written_alert_names(state_out, context)
    assert name not in written, f"alert {name!r} was written but should not be"


@then(parsers.parse('alert "{name}" is written'))
def then_alert_written(name, state_out, context):
    written = _written_alert_names(state_out, context)
    assert name in written, f"alert {name!r} was not written"


@then(parsers.parse('alert "{name}" is not written in group "{group_name}"'))
def then_alert_not_written_in_group(name, group_name, state_out, context):
    rules = read_all_rules(context, state_out)
    group_rules = rules.get(group_name, [])
    assert all(r.get("alert") != name for r in group_rules), (
        f"alert {name!r} was written in group {group_name!r} but should not be"
    )


@then(parsers.re(r'alert "(?P<name>[^"]+)" has "(?P<field>[^"]+)" equal to ["\'](?P<value>.+)["\']'))
def then_alert_field(name, field, value, state_out, context):
    rule = _find_alert(state_out, context, name)
    assert rule.get(field) == value, f"expected {field}={value!r}, got {rule.get(field)!r}"


@then(parsers.parse('alert "{name}" has label "{key}" equal to "{value}"'))
def then_alert_label(name, key, value, state_out, context):
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
def then_all_rules_still_written(state_out, context):
    rules = read_all_rules(context, state_out)
    assert rules, "no alert rules were written to disk"


@then("the written alert rules are unchanged")
def then_written_rules_unchanged(state_out, relations, context, prometheus_container):
    """Compare the on-disk rules against a baseline run with no customizations applied."""
    baseline = _run_config_changed(
        context,
        prometheus_container,
        {"alert_rule_customizations": ""},
        relations,
    )
    baseline_rules = read_all_rules(context, baseline)
    actual_rules = read_all_rules(context, state_out)
    assert actual_rules == baseline_rules, (
        f"the written alert rules changed:\nactual={actual_rules!r}\nbaseline={baseline_rules!r}"
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _docstring_to_groups(docstring):
    """Parse a feature-file docstring into a list of rule groups.

    The docstring maps group name -> list of rules (see the feature file).
    """
    parsed = yaml.safe_load(docstring)
    return [
        {"name": group_name, "rules": rules}
        for group_name, rules in parsed.items()
    ]


def _find_alert(state_out, context, name):
    """Return the rule dict for an alert of the given name across all written groups."""
    rules = read_all_rules(context, state_out)
    for group_rules in rules.values():
        for rule in group_rules:
            if rule.get("alert") == name:
                return rule
    raise AssertionError(f"alert {name!r} not found in written rules")
