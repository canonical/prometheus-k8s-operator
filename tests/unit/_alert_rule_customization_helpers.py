# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Shared helpers for the alert_rule_customizations BDD feature tests.

These helpers are reused by :mod:`tests.unit.test_alert_rule_customizations_bdd`
to drive the charm through the scenario framework and assert on the resulting
alert rule files and charm status.
"""

import json
from typing import Any, Dict, List

import yaml
from scenario import Relation

from charm import to_status

# ---------------------------------------------------------------------------
# Relation construction
# ---------------------------------------------------------------------------


def _make_scrape_relation(app_name: str, groups: List[Dict[str, Any]]) -> Relation:
    """Build a metrics-endpoint relation carrying the given rule groups."""
    return Relation(
        "metrics-endpoint",
        remote_app_name=app_name,
        remote_app_data={
            "alert_rules": json.dumps({"groups": groups}),
            "scrape_metadata": json.dumps(
                {
                    "model": "test-model",
                    "model_uuid": "20ce8299-3634-4bef-8bd8-5ace6c881234",
                    "application": app_name,
                    "charm_name": f"{app_name}-charm",
                }
            ),
        },
    )


def _make_remote_write_relation(app_name: str, groups: List[Dict[str, Any]]) -> Relation:
    """Build a receive-remote-write relation carrying the given rule groups."""
    return Relation(
        "receive-remote-write",
        remote_app_name=app_name,
        remote_app_data={
            "alert_rules": json.dumps({"groups": groups}),
            "scrape_metadata": json.dumps(
                {
                    "model": "test-model",
                    "model_uuid": "20ce8299-3634-4bef-8bd8-5ace6c881234",
                    "application": app_name,
                    "charm_name": f"{app_name}-charm",
                }
            ),
        },
    )


# ---------------------------------------------------------------------------
# Reading results
# ---------------------------------------------------------------------------


def read_all_rules(context, state_out) -> Dict[str, List[Dict[str, Any]]]:
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


def customization_status(state_out) -> Any:
    """Return the charm's ``alert_rules_customizations`` stored-state status."""
    charm_stored = next(
        s for s in state_out.stored_states if s.owner_path == "PrometheusCharm"
    )
    return to_status(charm_stored.content["status"]["alert_rules_customizations"])
