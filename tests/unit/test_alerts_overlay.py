# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Unit tests for src/alerts_overlay.py.

The interesting surface here is `apply(base, diff)`: given the same shape of
rules the charm gets from relation data (`dict[topology, rules_file]`), the
merged output must reflect the diff per the rules in
specs/adr/0006-diff-document-schema.md.

`load_diff` schema-validation is covered too, but the bulk of the tests
exercise `apply` directly — it's the one the charm calls per reconcile.
"""

import copy

import pytest

from alerts_overlay import Diff, OverlayError, apply, load_diff


# Two-topology base used by most tests. Mirrors the structure the charm builds
# from `{**metrics_consumer.alerts, **remote_write_provider.alerts}` — each
# topology key holds a Prometheus rules file (one `groups:` list per topology).
def _base_rules():
    return {
        "kube-state-metrics/0": {
            "groups": [
                {
                    "name": "kubernetes-apps",
                    "rules": [
                        {
                            "alert": "KubePodCrashLooping",
                            "expr": "rate(kube_pod_container_status_restarts_total[5m]) > 0",
                            "for": "15m",
                            "labels": {"severity": "warning", "team": "platform"},
                            "annotations": {
                                "summary": "Pod is crash looping",
                                "description": "{{ $labels.namespace }} has a pod looping",
                            },
                        },
                        {
                            "alert": "NoisyAlert",
                            "expr": "vector(1)",
                            "for": "0m",
                            "labels": {"severity": "info"},
                            "annotations": {"summary": "always firing"},
                        },
                    ],
                },
            ],
        },
        "node-exporter/0": {
            "groups": [
                {
                    "name": "node",
                    "rules": [
                        {
                            "alert": "HostDown",
                            "expr": "up == 0",
                            "for": "10m",
                            "labels": {"severity": "warning"},
                            "annotations": {"summary": "host is down"},
                        },
                        {
                            "alert": "DiskWillFillIn4Hours",
                            "expr": "predict_linear(node_filesystem_free_bytes[1h], 4*3600) < 0",
                            "for": "30m",
                            "labels": {"severity": "warning"},
                            "annotations": {"summary": "disk filling"},
                        },
                    ],
                },
            ],
        },
    }


def _diff(remove=None, patch=None):
    return Diff(remove=remove or [], patch=patch or [])


def _alert_names(rules):
    """Flatten all alert names across all topologies/groups for assertions."""
    out = []
    for rules_file in rules.values():
        for group in rules_file["groups"]:
            for rule in group["rules"]:
                if "alert" in rule:
                    out.append(rule["alert"])
    return sorted(out)


def _find_rule(rules, alert_name):
    for rules_file in rules.values():
        for group in rules_file["groups"]:
            for rule in group["rules"]:
                if rule.get("alert") == alert_name:
                    return rule
    raise AssertionError(f"no rule named {alert_name!r} in {rules!r}")


# -- apply: removals -----------------------------------------------------------


def test_remove_drops_only_the_named_rule():
    base = _base_rules()
    diff = _diff(remove=[{"match": {"alert": "NoisyAlert"}}])

    out = apply(base, diff)

    assert _alert_names(out) == sorted(
        ["KubePodCrashLooping", "HostDown", "DiskWillFillIn4Hours"]
    )


def test_remove_leaves_other_topologies_untouched():
    """Removing a rule from one topology must not perturb sibling topologies."""
    base = _base_rules()
    diff = _diff(remove=[{"match": {"alert": "NoisyAlert"}}])

    out = apply(base, diff)

    # node-exporter/0 had NoisyAlert nowhere — it should be byte-equal to input.
    assert out["node-exporter/0"] == base["node-exporter/0"]


def test_remove_multiple_rules_in_one_pass():
    base = _base_rules()
    diff = _diff(
        remove=[
            {"match": {"alert": "NoisyAlert"}},
            {"match": {"alert": "DiskWillFillIn4Hours"}},
        ]
    )

    out = apply(base, diff)

    assert _alert_names(out) == ["HostDown", "KubePodCrashLooping"]


def test_remove_no_match_is_a_no_op_not_an_error():
    """ADR-0006 D3: if a selector matches nothing, log + carry on."""
    base = _base_rules()
    diff = _diff(remove=[{"match": {"alert": "RuleThatDoesNotExist"}}])

    out = apply(base, diff)

    assert out == base


def test_remove_ambiguous_match_raises():
    """ADR-0006 D4: same name in two producers' rules → hard error."""
    base = {
        "producer-a/0": {
            "groups": [{"name": "g", "rules": [{"alert": "Duplicate", "expr": "x"}]}]
        },
        "producer-b/0": {
            "groups": [{"name": "g", "rules": [{"alert": "Duplicate", "expr": "y"}]}]
        },
    }
    diff = _diff(remove=[{"match": {"alert": "Duplicate"}}])

    with pytest.raises(OverlayError, match="ambiguous match: 2 rules named 'Duplicate'"):
        apply(base, diff)


# -- apply: patching, one field at a time --------------------------------------
#
# These are the explicit "patching works regardless of which field is changed"
# tests the user asked for. Each one mutates exactly one field on `HostDown` and
# asserts that the other fields are preserved byte-for-byte.


def test_patch_for_only():
    base = _base_rules()
    diff = _diff(
        patch=[{"match": {"alert": "HostDown"}, "set": {"for": "40m"}}]
    )

    out = apply(base, diff)
    rule = _find_rule(out, "HostDown")

    assert rule["for"] == "40m"
    # everything else is unchanged
    assert rule["expr"] == "up == 0"
    assert rule["labels"] == {"severity": "warning"}
    assert rule["annotations"] == {"summary": "host is down"}


def test_patch_expr_only():
    base = _base_rules()
    diff = _diff(
        patch=[
            {
                "match": {"alert": "HostDown"},
                "set": {"expr": "up{job='node'} == 0"},
            }
        ]
    )

    out = apply(base, diff)
    rule = _find_rule(out, "HostDown")

    assert rule["expr"] == "up{job='node'} == 0"
    assert rule["for"] == "10m"
    assert rule["labels"] == {"severity": "warning"}
    assert rule["annotations"] == {"summary": "host is down"}


def test_patch_labels_deep_merges():
    """ADR-0006 D2: labels are merged by key; keys not mentioned survive."""
    base = _base_rules()
    diff = _diff(
        patch=[
            {
                "match": {"alert": "KubePodCrashLooping"},
                "set": {"labels": {"severity": "critical", "page": "true"}},
            }
        ]
    )

    out = apply(base, diff)
    rule = _find_rule(out, "KubePodCrashLooping")

    assert rule["labels"] == {
        "severity": "critical",  # overwritten
        "team": "platform",      # survived (not in `set`)
        "page": "true",          # added
    }
    # other fields untouched
    assert rule["for"] == "15m"
    assert rule["expr"].startswith("rate(kube_pod_container_status_restarts_total")
    assert rule["annotations"]["summary"] == "Pod is crash looping"


def test_patch_annotations_deep_merges():
    """ADR-0006 D2: annotations behave like labels — merged by key."""
    base = _base_rules()
    diff = _diff(
        patch=[
            {
                "match": {"alert": "KubePodCrashLooping"},
                "set": {
                    "annotations": {
                        "summary": "Pod is in CrashLoopBackOff",
                        "runbook_url": "https://example/runbook",
                    }
                },
            }
        ]
    )

    out = apply(base, diff)
    rule = _find_rule(out, "KubePodCrashLooping")

    assert rule["annotations"] == {
        "summary": "Pod is in CrashLoopBackOff",  # overwritten
        "description": "{{ $labels.namespace }} has a pod looping",  # survived
        "runbook_url": "https://example/runbook",  # added
    }
    # labels block must not be touched by an annotations-only patch
    assert rule["labels"] == {"severity": "warning", "team": "platform"}


def test_patch_all_four_fields_at_once():
    """One patch entry can carry every mutable field."""
    base = _base_rules()
    diff = _diff(
        patch=[
            {
                "match": {"alert": "HostDown"},
                "set": {
                    "for": "40m",
                    "expr": "up{instance=~'.+'} == 0",
                    "labels": {"severity": "critical"},
                    "annotations": {"summary": "node unreachable"},
                },
            }
        ]
    )

    out = apply(base, diff)
    rule = _find_rule(out, "HostDown")

    assert rule["for"] == "40m"
    assert rule["expr"] == "up{instance=~'.+'} == 0"
    assert rule["labels"] == {"severity": "critical"}
    assert rule["annotations"] == {"summary": "node unreachable"}


def test_patch_adds_labels_when_rule_has_none():
    """A rule without a `labels:` block should still accept a labels patch."""
    base = {
        "producer/0": {
            "groups": [
                {
                    "name": "g",
                    "rules": [{"alert": "Bare", "expr": "x", "for": "5m"}],
                }
            ]
        }
    }
    diff = _diff(
        patch=[{"match": {"alert": "Bare"}, "set": {"labels": {"severity": "info"}}}]
    )

    out = apply(base, diff)
    rule = _find_rule(out, "Bare")

    assert rule["labels"] == {"severity": "info"}


def test_patch_no_match_is_a_no_op_not_an_error():
    base = _base_rules()
    diff = _diff(
        patch=[{"match": {"alert": "DoesNotExist"}, "set": {"for": "1h"}}]
    )

    out = apply(base, diff)

    assert out == base


def test_patch_ambiguous_match_raises():
    base = {
        "producer-a/0": {
            "groups": [{"name": "g", "rules": [{"alert": "Dup", "expr": "a"}]}]
        },
        "producer-b/0": {
            "groups": [{"name": "g", "rules": [{"alert": "Dup", "expr": "b"}]}]
        },
    }
    diff = _diff(patch=[{"match": {"alert": "Dup"}, "set": {"for": "5m"}}])

    with pytest.raises(OverlayError, match="ambiguous match: 2 rules named 'Dup'"):
        apply(base, diff)


# -- apply: combined remove + patch --------------------------------------------


def test_remove_and_patch_on_different_rules():
    base = _base_rules()
    diff = _diff(
        remove=[{"match": {"alert": "NoisyAlert"}}],
        patch=[{"match": {"alert": "HostDown"}, "set": {"for": "40m"}}],
    )

    out = apply(base, diff)

    assert "NoisyAlert" not in _alert_names(out)
    assert _find_rule(out, "HostDown")["for"] == "40m"


def test_remove_wins_over_patch_for_same_alert():
    """D5: remove runs before patch. A removed rule cannot be patched — the
    patch becomes a missing-match no-op."""
    base = _base_rules()
    diff = _diff(
        remove=[{"match": {"alert": "HostDown"}}],
        patch=[{"match": {"alert": "HostDown"}, "set": {"for": "999m"}}],
    )

    out = apply(base, diff)

    assert "HostDown" not in _alert_names(out)


# -- apply: purity / immutability ----------------------------------------------


def test_apply_does_not_mutate_input_base():
    base = _base_rules()
    snapshot = copy.deepcopy(base)
    diff = _diff(
        remove=[{"match": {"alert": "NoisyAlert"}}],
        patch=[{"match": {"alert": "HostDown"}, "set": {"labels": {"severity": "critical"}}}],
    )

    apply(base, diff)

    assert base == snapshot, "apply() must not mutate its input"


def test_empty_diff_returns_deep_copy_equal_to_base():
    base = _base_rules()

    out = apply(base, _diff())

    assert out == base
    # the deep-copy guarantee means we can mutate `out` without touching `base`.
    out["kube-state-metrics/0"]["groups"][0]["rules"].clear()
    assert base["kube-state-metrics/0"]["groups"][0]["rules"], "deep copy broke"


def test_none_diff_returns_deep_copy_equal_to_base():
    base = _base_rules()

    out = apply(base, None)

    assert out == base


# -- load_diff: schema validation ----------------------------------------------


def test_load_diff_none_and_empty_return_none():
    assert load_diff(None) is None
    assert load_diff("") is None
    assert load_diff("   \n   ") is None


def test_load_diff_round_trips_a_well_formed_document():
    out = load_diff(
        """
        schemaVersion: 1
        remove:
          - match: {alert: Foo}
        patch:
          - match: {alert: Bar}
            set:
              for: 5m
              labels: {severity: critical}
        """
    )

    assert out == Diff(
        remove=[{"match": {"alert": "Foo"}}],
        patch=[{"match": {"alert": "Bar"}, "set": {"for": "5m", "labels": {"severity": "critical"}}}],
    )


def test_load_diff_rejects_wrong_schema_version():
    with pytest.raises(OverlayError, match="unsupported schemaVersion"):
        load_diff("schemaVersion: 2\nremove: []\n")


def test_load_diff_rejects_missing_schema_version():
    with pytest.raises(OverlayError, match="unsupported schemaVersion"):
        load_diff("remove: []\n")


def test_load_diff_rejects_non_empty_add():
    """ADR-0006 D8: `add:` is reserved but not implemented in MVP."""
    with pytest.raises(OverlayError, match="'add' is not yet implemented"):
        load_diff(
            """
            schemaVersion: 1
            add:
              groups:
                - name: custom
                  rules:
                    - alert: NewRule
                      expr: vector(1)
            """
        )


def test_load_diff_accepts_empty_add_block():
    """Reserved-but-empty `add:` should not break parsing."""
    out = load_diff(
        """
        schemaVersion: 1
        add:
          groups: []
        """
    )
    assert out == Diff()


def test_load_diff_rejects_match_with_extra_keys():
    """ADR-0006 D1: MVP `match:` accepts exactly one key, `alert`."""
    with pytest.raises(OverlayError, match="must contain exactly one key 'alert'"):
        load_diff(
            """
            schemaVersion: 1
            remove:
              - match: {alert: Foo, labels: {severity: warning}}
            """
        )


def test_load_diff_rejects_match_without_alert_key():
    with pytest.raises(OverlayError):
        load_diff(
            """
            schemaVersion: 1
            remove:
              - match: {producer: foo}
            """
        )


def test_load_diff_rejects_empty_set_block():
    with pytest.raises(OverlayError, match="'set' must be a non-empty mapping"):
        load_diff(
            """
            schemaVersion: 1
            patch:
              - match: {alert: Foo}
                set: {}
            """
        )


def test_load_diff_rejects_unknown_set_keys():
    with pytest.raises(OverlayError, match="unsupported keys in 'set'"):
        load_diff(
            """
            schemaVersion: 1
            patch:
              - match: {alert: Foo}
                set: {severity: critical}
            """
        )


def test_load_diff_rejects_for_as_non_string():
    with pytest.raises(OverlayError, match="'set.for' must be a string"):
        load_diff(
            """
            schemaVersion: 1
            patch:
              - match: {alert: Foo}
                set: {for: 40}
            """
        )


def test_load_diff_rejects_labels_as_non_mapping():
    with pytest.raises(OverlayError, match="'set.labels' must be a mapping"):
        load_diff(
            """
            schemaVersion: 1
            patch:
              - match: {alert: Foo}
                set: {labels: [severity, critical]}
            """
        )


def test_load_diff_rejects_two_patches_for_same_alert():
    """ADR-0006 D6: charm-side defence-in-depth against UI bugs."""
    with pytest.raises(OverlayError, match="two 'patch' entries both target alert 'Foo'"):
        load_diff(
            """
            schemaVersion: 1
            patch:
              - match: {alert: Foo}
                set: {for: 5m}
              - match: {alert: Foo}
                set: {expr: up == 0}
            """
        )


def test_load_diff_rejects_invalid_yaml():
    with pytest.raises(OverlayError, match="not valid YAML"):
        load_diff("schemaVersion: 1\nremove: [::oops")


# -- load_diff + apply integration --------------------------------------------


def test_end_to_end_yaml_to_merged_rules():
    """The shape the charm actually exercises: YAML in → merged dict out."""
    base = _base_rules()
    diff = load_diff(
        """
        schemaVersion: 1
        remove:
          - match: {alert: NoisyAlert}
        patch:
          - match: {alert: HostDown}
            set:
              for: 40m
              labels:
                severity: critical
              annotations:
                summary: node unreachable
        """
    )

    out = apply(base, diff)

    assert "NoisyAlert" not in _alert_names(out)

    host_down = _find_rule(out, "HostDown")
    assert host_down["for"] == "40m"
    assert host_down["labels"] == {"severity": "critical"}
    assert host_down["annotations"] == {"summary": "node unreachable"}
    # expr was not in `set` → must be the original value
    assert host_down["expr"] == "up == 0"
