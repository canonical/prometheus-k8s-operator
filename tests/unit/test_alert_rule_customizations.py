# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Unit tests for the alert_rule_customizations charm config option.

Each test:
  1. Provides alert rules to Prometheus via relation data (metrics-endpoint and/or
     receive-remote-write).
  2. Sets the ``alert_rule_customizations`` config option.
  3. Fires ``config_changed``.
  4. Reads the rules files written to the virtual Prometheus filesystem and asserts
     that the remove / patch / add operations have been applied correctly.
"""

import json
from typing import Any, Dict, List, Set

import yaml
from ops.model import ActiveStatus, BlockedStatus
from scenario import Relation, State

from charm import to_status

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _alert_rules_json(groups: List[Dict[str, Any]]) -> str:
    """Serialise a list of groups into the JSON format expected in relation data."""
    return json.dumps({"groups": groups})


def _metadata_json(app_name: str) -> str:
    return json.dumps(
        {
            "model": "test-model",
            "model_uuid": "20ce8299-3634-4bef-8bd8-5ace6c881234",
            "application": app_name,
            "charm_name": f"{app_name}-charm",
        }
    )


def _make_scrape_relation(app_name: str, groups: List[Dict[str, Any]]) -> Relation:
    """Build a metrics-endpoint relation carrying the given rule groups."""
    return Relation(
        "metrics-endpoint",
        remote_app_name=app_name,
        remote_app_data={
            "alert_rules": _alert_rules_json(groups),
            "scrape_metadata": _metadata_json(app_name),
        },
    )


def _make_remote_write_relation(app_name: str, groups: List[Dict[str, Any]]) -> Relation:
    """Build a receive-remote-write relation carrying the given rule groups."""
    return Relation(
        "receive-remote-write",
        remote_app_name=app_name,
        remote_app_data={
            "alert_rules": _alert_rules_json(groups),
            "scrape_metadata": _metadata_json(app_name),
        },
    )


def _read_all_rules(context, state_out) -> Dict[str, List[Dict[str, Any]]]:
    """Return all alert rules written to /etc/prometheus/rules/.

    Returns a mapping of  group_name -> list[rule_dict].
    """
    fs = state_out.get_container("prometheus").get_filesystem(context)
    rules_dir = fs / "etc" / "prometheus" / "rules"
    if not rules_dir.exists():
        return {}

    result: Dict[str, List[Dict[str, Any]]] = {}
    for rule_file in sorted(path for path in rules_dir.iterdir() if path.is_file()):
        data = yaml.safe_load(rule_file.read_text())
        for group in data.get("groups", []):
            result[group["name"]] = group.get("rules", [])
    return result


def _alert_names_in_group(rules_by_group: Dict[str, List[Dict[str, Any]]], group_name: str) -> Set[str]:
    return {r["alert"] for r in rules_by_group.get(group_name, []) if "alert" in r}


def _customization_status(state_out) -> Any:
    """Return the charm's ``alert_rules_customizations`` stored-state status."""
    charm_stored = next(
        s for s in state_out.stored_states if s.owner_path == "PrometheusCharm"
    )
    return to_status(charm_stored.content["status"]["alert_rules_customizations"])


# ---------------------------------------------------------------------------
# Shared rule fixtures
# ---------------------------------------------------------------------------

RULE_ALPHA = {
    "alert": "AlphaFiring",
    "expr": 'up{job="alpha"} == 0',
    "for": "5m",
    "labels": {"severity": "critical", "juju_application": "app-alpha"},
    "annotations": {"summary": "Alpha is down"},
}

RULE_BETA = {
    "alert": "BetaFiring",
    "expr": 'up{job="beta"} == 0',
    "for": "2m",
    "labels": {"severity": "warning", "juju_application": "app-beta"},
    "annotations": {"summary": "Beta is degraded"},
}

RULE_GAMMA = {
    "alert": "GammaFiring",
    "expr": 'rate(errors_total[5m]) > 0',
    "for": "1m",
    "labels": {"severity": "warning"},
    "annotations": {"summary": "Gamma has errors"},
}

GROUP_MAIN = {"name": "main-group", "rules": [RULE_ALPHA, RULE_BETA]}
GROUP_SECONDARY = {"name": "secondary-group", "rules": [RULE_GAMMA]}


# ---------------------------------------------------------------------------
# Tests: remove
# ---------------------------------------------------------------------------


def test_remove_by_alert_name(context, prometheus_container):
    """Removing by alert name deletes that rule; the sibling rule in the same group survives."""
    relation = _make_scrape_relation("myapp", [GROUP_MAIN])
    state_in = State(
        leader=True,
        relations=[relation],
        containers=[prometheus_container],
        config={
            "alert_rule_customizations": "remove:\n  - where:\n      alert: AlphaFiring\n"
        },
    )

    state_out = context.run(context.on.config_changed(), state_in)

    rules = _read_all_rules(context, state_out)
    assert "AlphaFiring" not in _alert_names_in_group(rules, "main-group")
    assert "BetaFiring" in _alert_names_in_group(rules, "main-group")


def test_remove_by_label(context, prometheus_container):
    """Removing by label key-value deletes every matching rule."""
    relation = _make_scrape_relation("myapp", [GROUP_MAIN])
    state_in = State(
        leader=True,
        relations=[relation],
        containers=[prometheus_container],
        config={
            "alert_rule_customizations": (
                "remove:\n"
                "  - where:\n"
                "      labels:\n"
                "        juju_application: app-alpha\n"
            )
        },
    )

    state_out = context.run(context.on.config_changed(), state_in)

    rules = _read_all_rules(context, state_out)
    assert "AlphaFiring" not in _alert_names_in_group(rules, "main-group")
    assert "BetaFiring" in _alert_names_in_group(rules, "main-group")


def test_remove_by_alert_and_label_and_semantics(context, prometheus_container):
    """All fields in a where block are ANDed: only rules matching both conditions are removed."""
    # Both RULE_ALPHA and RULE_BETA share severity=warning… but RULE_ALPHA has severity=critical.
    # Selector: alert=BetaFiring AND labels.severity=warning → only BetaFiring should be removed.
    relation = _make_scrape_relation("myapp", [GROUP_MAIN])
    state_in = State(
        leader=True,
        relations=[relation],
        containers=[prometheus_container],
        config={
            "alert_rule_customizations": (
                "remove:\n"
                "  - where:\n"
                "      alert: BetaFiring\n"
                "      labels:\n"
                "        severity: warning\n"
            )
        },
    )

    state_out = context.run(context.on.config_changed(), state_in)

    rules = _read_all_rules(context, state_out)
    assert "AlphaFiring" in _alert_names_in_group(rules, "main-group")
    assert "BetaFiring" not in _alert_names_in_group(rules, "main-group")


def test_remove_entire_group_by_group_selector(context, prometheus_container):
    """A group-only where selector drops the complete group."""
    relation = _make_scrape_relation("myapp", [GROUP_MAIN, GROUP_SECONDARY])
    state_in = State(
        leader=True,
        relations=[relation],
        containers=[prometheus_container],
        config={
            "alert_rule_customizations": (
                "remove:\n"
                "  - where:\n"
                "      group: main-group\n"
            )
        },
    )

    state_out = context.run(context.on.config_changed(), state_in)

    rules = _read_all_rules(context, state_out)
    assert "main-group" not in rules
    assert "secondary-group" in rules


def test_remove_last_rule_in_group_prunes_empty_group(context, prometheus_container):
    """When the only rule in a group is removed, the group itself is pruned from the output."""
    relation = _make_scrape_relation("myapp", [GROUP_SECONDARY])
    state_in = State(
        leader=True,
        relations=[relation],
        containers=[prometheus_container],
        config={
            "alert_rule_customizations": (
                "remove:\n"
                "  - where:\n"
                "      alert: GammaFiring\n"
            )
        },
    )

    state_out = context.run(context.on.config_changed(), state_in)

    rules = _read_all_rules(context, state_out)
    assert "secondary-group" not in rules


def test_remove_nonexistent_rule_is_noop(context, prometheus_container):
    """A where selector that matches nothing leaves all rules unchanged."""
    relation = _make_scrape_relation("myapp", [GROUP_MAIN])
    state_in = State(
        leader=True,
        relations=[relation],
        containers=[prometheus_container],
        config={
            "alert_rule_customizations": (
                "remove:\n"
                "  - where:\n"
                "      alert: TotallyMadeUpAlert\n"
            )
        },
    )

    state_out = context.run(context.on.config_changed(), state_in)

    rules = _read_all_rules(context, state_out)
    assert _alert_names_in_group(rules, "main-group") == {"AlphaFiring", "BetaFiring"}


# ---------------------------------------------------------------------------
# Tests: patch
# ---------------------------------------------------------------------------


def test_patch_for_field(context, prometheus_container):
    """Patching the 'for' field on a matched rule updates the duration on disk."""
    relation = _make_scrape_relation("myapp", [GROUP_MAIN])
    state_in = State(
        leader=True,
        relations=[relation],
        containers=[prometheus_container],
        config={
            "alert_rule_customizations": (
                "patch:\n"
                "  - where:\n"
                "      alert: AlphaFiring\n"
                "    set:\n"
                "      for: 30m\n"
            )
        },
    )

    state_out = context.run(context.on.config_changed(), state_in)

    rules = _read_all_rules(context, state_out)
    alpha_rule = next(r for r in rules["main-group"] if r.get("alert") == "AlphaFiring")
    assert alpha_rule["for"] == "30m"
    # Other rules are not affected.
    beta_rule = next(r for r in rules["main-group"] if r.get("alert") == "BetaFiring")
    assert beta_rule["for"] == "2m"


def test_patch_expr_field(context, prometheus_container):
    """Patching the 'expr' field replaces the full PromQL expression on disk."""
    new_expr = 'up{job="alpha", env="prod"} == 0'
    relation = _make_scrape_relation("myapp", [GROUP_MAIN])
    state_in = State(
        leader=True,
        relations=[relation],
        containers=[prometheus_container],
        config={
            "alert_rule_customizations": (
                "patch:\n"
                "  - where:\n"
                "      alert: AlphaFiring\n"
                "    set:\n"
                '      expr: \'up{job="alpha", env="prod"} == 0\'\n'
            )
        },
    )

    state_out = context.run(context.on.config_changed(), state_in)

    rules = _read_all_rules(context, state_out)
    alpha_rule = next(r for r in rules["main-group"] if r.get("alert") == "AlphaFiring")
    assert alpha_rule["expr"] == new_expr


def test_patch_adds_new_label(context, prometheus_container):
    """A 'set.labels' entry that contains a new key merges it into the rule's labels."""
    relation = _make_scrape_relation("myapp", [GROUP_MAIN])
    state_in = State(
        leader=True,
        relations=[relation],
        containers=[prometheus_container],
        config={
            "alert_rule_customizations": (
                "patch:\n"
                "  - where:\n"
                "      alert: AlphaFiring\n"
                "    set:\n"
                "      labels:\n"
                "        team: platform\n"
            )
        },
    )

    state_out = context.run(context.on.config_changed(), state_in)

    rules = _read_all_rules(context, state_out)
    alpha_rule = next(r for r in rules["main-group"] if r.get("alert") == "AlphaFiring")
    assert alpha_rule["labels"]["team"] == "platform"
    # Pre-existing labels are preserved.
    assert alpha_rule["labels"]["severity"] == "critical"


def test_patch_overwrites_existing_label(context, prometheus_container):
    """A 'set.labels' entry with an existing key overwrites its value."""
    relation = _make_scrape_relation("myapp", [GROUP_MAIN])
    state_in = State(
        leader=True,
        relations=[relation],
        containers=[prometheus_container],
        config={
            "alert_rule_customizations": (
                "patch:\n"
                "  - where:\n"
                "      alert: AlphaFiring\n"
                "    set:\n"
                "      labels:\n"
                "        severity: info\n"
            )
        },
    )

    state_out = context.run(context.on.config_changed(), state_in)

    rules = _read_all_rules(context, state_out)
    alpha_rule = next(r for r in rules["main-group"] if r.get("alert") == "AlphaFiring")
    assert alpha_rule["labels"]["severity"] == "info"


def test_patch_by_label_selector(context, prometheus_container):
    """Matching via where.labels targets only the rule(s) that carry those labels."""
    # RULE_BETA has severity=warning; RULE_ALPHA has severity=critical.
    # Patch by severity=warning should only touch RULE_BETA.
    relation = _make_scrape_relation("myapp", [GROUP_MAIN])
    state_in = State(
        leader=True,
        relations=[relation],
        containers=[prometheus_container],
        config={
            "alert_rule_customizations": (
                "patch:\n"
                "  - where:\n"
                "      labels:\n"
                "        severity: warning\n"
                "    set:\n"
                "      for: 10m\n"
            )
        },
    )

    state_out = context.run(context.on.config_changed(), state_in)

    rules = _read_all_rules(context, state_out)
    beta_rule = next(r for r in rules["main-group"] if r.get("alert") == "BetaFiring")
    alpha_rule = next(r for r in rules["main-group"] if r.get("alert") == "AlphaFiring")
    assert beta_rule["for"] == "10m"
    assert alpha_rule["for"] == "5m"  # Unchanged.


def test_patch_multiple_operations_each_applied(context, prometheus_container):
    """Two patch entries with distinct where selectors are each applied to their target rule."""
    relation = _make_scrape_relation("myapp", [GROUP_MAIN])
    state_in = State(
        leader=True,
        relations=[relation],
        containers=[prometheus_container],
        config={
            "alert_rule_customizations": (
                "patch:\n"
                "  - where:\n"
                "      alert: AlphaFiring\n"
                "    set:\n"
                "      for: 15m\n"
                "  - where:\n"
                "      alert: BetaFiring\n"
                "    set:\n"
                "      for: 20m\n"
            )
        },
    )

    state_out = context.run(context.on.config_changed(), state_in)

    rules = _read_all_rules(context, state_out)
    alpha_rule = next(r for r in rules["main-group"] if r.get("alert") == "AlphaFiring")
    beta_rule = next(r for r in rules["main-group"] if r.get("alert") == "BetaFiring")
    assert alpha_rule["for"] == "15m"
    assert beta_rule["for"] == "20m"

# ---------------------------------------------------------------------------
# Tests: combined operations
# ---------------------------------------------------------------------------


def test_remove_and_patch_combined(context, prometheus_container):
    """Remove one rule and patch a different rule in the same group; both effects are visible."""
    relation = _make_scrape_relation("myapp", [GROUP_MAIN])
    state_in = State(
        leader=True,
        relations=[relation],
        containers=[prometheus_container],
        config={
            "alert_rule_customizations": (
                "remove:\n"
                "  - where:\n"
                "      alert: AlphaFiring\n"
                "patch:\n"
                "  - where:\n"
                "      alert: BetaFiring\n"
                "    set:\n"
                "      for: 25m\n"
            )
        },
    )

    state_out = context.run(context.on.config_changed(), state_in)

    rules = _read_all_rules(context, state_out)
    assert "AlphaFiring" not in _alert_names_in_group(rules, "main-group")
    beta_rule = next(r for r in rules["main-group"] if r.get("alert") == "BetaFiring")
    assert beta_rule["for"] == "25m"


# ---------------------------------------------------------------------------
# Tests: error handling and edge cases
# ---------------------------------------------------------------------------


def test_invalid_yaml_config_sets_blocked_status(context, prometheus_container):
    """Malformed YAML in alert_rule_customizations causes BlockedStatus but rules are still written."""
    relation = _make_scrape_relation("myapp", [GROUP_MAIN])
    state_in = State(
        leader=True,
        relations=[relation],
        containers=[prometheus_container],
        config={
            "alert_rule_customizations": "remove: [unclosed bracket"
        },
    )

    state_out = context.run(context.on.config_changed(), state_in)

    # Status must be blocked to signal the bad config.
    assert isinstance(_customization_status(state_out), BlockedStatus)
    # Unmodified rules must still be written so alerting keeps working.
    rules = _read_all_rules(context, state_out)
    assert _alert_names_in_group(rules, "main-group") == {"AlphaFiring", "BetaFiring"}


def test_unknown_top_level_key_sets_blocked_status(context, prometheus_container):
    """A config with an unrecognised top-level key causes BlockedStatus but rules are still written."""
    relation = _make_scrape_relation("myapp", [GROUP_MAIN])
    state_in = State(
        leader=True,
        relations=[relation],
        containers=[prometheus_container],
        config={
            "alert_rule_customizations": (
                "replace:\n"
                "  - where:\n"
                "      alert: AlphaFiring\n"
            )
        },
    )

    state_out = context.run(context.on.config_changed(), state_in)

    # Status must be blocked to signal the bad config.
    assert isinstance(_customization_status(state_out), BlockedStatus)
    # Unmodified rules must still be written so alerting keeps working.
    rules = _read_all_rules(context, state_out)
    assert _alert_names_in_group(rules, "main-group") == {"AlphaFiring", "BetaFiring"}


def test_empty_config_is_noop(context, prometheus_container):
    """An empty alert_rule_customizations string is a no-op; rules are written as normal."""
    relation = _make_scrape_relation("myapp", [GROUP_MAIN])
    state_in = State(
        leader=True,
        relations=[relation],
        containers=[prometheus_container],
        config={"alert_rule_customizations": ""},
    )

    state_out = context.run(context.on.config_changed(), state_in)

    rules = _read_all_rules(context, state_out)
    assert _alert_names_in_group(rules, "main-group") == {"AlphaFiring", "BetaFiring"}
    assert isinstance(_customization_status(state_out), ActiveStatus)


def test_customizations_apply_to_both_relation_endpoints(context, prometheus_container):
    """A remove operation affects rules coming from both metrics-endpoint and receive-remote-write."""
    # Both relations provide a rule named "AlphaFiring" in different groups.
    scrape_relation = _make_scrape_relation(
        "scrape-app",
        [{"name": "scrape-group", "rules": [RULE_ALPHA, RULE_BETA]}],
    )
    remote_write_relation = _make_remote_write_relation(
        "rw-app",
        [{"name": "rw-group", "rules": [RULE_ALPHA, RULE_GAMMA]}],
    )
    state_in = State(
        leader=True,
        relations=[scrape_relation, remote_write_relation],
        containers=[prometheus_container],
        config={
            "alert_rule_customizations": (
                "remove:\n"
                "  - where:\n"
                "      alert: AlphaFiring\n"
            )
        },
    )

    state_out = context.run(context.on.config_changed(), state_in)

    rules = _read_all_rules(context, state_out)
    # AlphaFiring removed from scrape group.
    assert "AlphaFiring" not in _alert_names_in_group(rules, "scrape-group")
    assert "BetaFiring" in _alert_names_in_group(rules, "scrape-group")
    # AlphaFiring removed from remote-write group.
    assert "AlphaFiring" not in _alert_names_in_group(rules, "rw-group")
    assert "GammaFiring" in _alert_names_in_group(rules, "rw-group")
