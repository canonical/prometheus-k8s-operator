# Copyright 2020 Canonical Ltd.
# See LICENSE file for licensing details.

import json
import textwrap

import yaml
from charms.prometheus_k8s.v0.prometheus_scrape import PrometheusRulesProvider
from ops.charm import CharmBase
from scenario import Context, Relation, State

NO_ALERTS = json.dumps({})

# use a short-form free-standing alert, for brevity
ALERT = yaml.safe_dump({"alert": "free_standing", "expr": "avg(some_vector[5m]) > 5"})


def _make_consumer_charm(alert_rules_path: str):
    class ConsumerCharm(CharmBase):
        metadata_yaml = textwrap.dedent(
            """
            provides:
              metrics-endpoint:
                interface: prometheus_scrape
            """
        )

        def __init__(self, *args, **kwargs):
            super().__init__(*args)
            self.rules_provider = PrometheusRulesProvider(self, dir_path=alert_rules_path)

    return ConsumerCharm


def _relation_local_app_alerts(state_out, endpoint_name="metrics-endpoint"):
    rel = next((r for r in state_out.relations if getattr(r, "endpoint", None) == endpoint_name), None)
    return getattr(rel, "local_app_data", {}).get("alert_rules")


def test_reload_when_dir_is_still_empty_changes_nothing(tmp_path):
    alert_dir = str(tmp_path)
    consumer_charm = _make_consumer_charm(alert_dir)

    context = Context(charm_type=consumer_charm, meta=yaml.safe_load(consumer_charm.metadata_yaml))
    rel = Relation(endpoint="metrics-endpoint")
    state = State(relations={rel}, leader=True)

    state_out = context.run(context.on.relation_joined(rel), state)

    assert _relation_local_app_alerts(state_out) == NO_ALERTS


def test_reload_after_dir_is_populated_updates_relation_data(tmp_path):
    alert_dir = str(tmp_path)
    consumer_charm = _make_consumer_charm(alert_dir)

    # create an alert file
    (tmp_path / "alert.rule").write_text(ALERT)

    context = Context(charm_type=consumer_charm, meta=yaml.safe_load(consumer_charm.metadata_yaml))
    rel = Relation(endpoint="metrics-endpoint")
    state = State(relations={rel}, leader=True)

    state_out = context.run(context.on.relation_joined(rel), state)

    assert _relation_local_app_alerts(state_out) != NO_ALERTS


def test_reload_after_dir_is_emptied_updates_relation_data(tmp_path):
    alert_dir = str(tmp_path)
    consumer_charm = _make_consumer_charm(alert_dir)

    # create alert then remove it
    p = tmp_path / "alert.rule"
    p.write_text(ALERT)

    context = Context(charm_type=consumer_charm, meta=yaml.safe_load(consumer_charm.metadata_yaml))
    rel = Relation(endpoint="metrics-endpoint")
    state = State(relations={rel}, leader=True)

    # initial run -> non-empty
    state_out = context.run(context.on.relation_joined(rel), state)
    assert _relation_local_app_alerts(state_out) != NO_ALERTS

    # remove files
    p.unlink()

    # run update again
    state_out = context.run(context.on.relation_joined(rel), state)
    assert _relation_local_app_alerts(state_out) == NO_ALERTS


def test_only_files_with_rule_or_rules_suffixes_are_loaded(tmp_path):
    alert_dir = str(tmp_path)
    consumer_charm = _make_consumer_charm(alert_dir)

    filenames = [
        "alert.rule",
        "alert.rules",
        "alert.ruless",
        "alertrule",
        "alertrules",
        "alert.yml",
        "alert.yaml",
        "alert.txt",
        "alert.json",
    ]
    for filename in filenames:
        rule_file = yaml.safe_dump({"alert": filename, "expr": "avg(some_vector[5m]) > 5"})
        (tmp_path / filename).write_text(rule_file)

    context = Context(charm_type=consumer_charm, meta=yaml.safe_load(consumer_charm.metadata_yaml))
    rel = Relation(endpoint="metrics-endpoint")
    state = State(relations={rel}, leader=True)

    state_out = context.run(context.on.relation_joined(rel), state)

    alert_rules = json.loads(_relation_local_app_alerts(state_out) or "{}")
    alert_names = [groups["rules"][0]["alert"] for groups in alert_rules.get("groups", [])]
    assert set(alert_names) == {"alert.rule", "alert.rules", "alert.yml", "alert.yaml"}


def test_reload_with_empty_rules(tmp_path):
    alert_dir = str(tmp_path)
    consumer_charm = _make_consumer_charm(alert_dir)

    # write empty file
    (tmp_path / "alert.rule").write_text("")

    context = Context(charm_type=consumer_charm, meta=yaml.safe_load(consumer_charm.metadata_yaml))
    rel = Relation(endpoint="metrics-endpoint")
    state = State(relations={rel}, leader=True)

    state_out = context.run(context.on.relation_joined(rel), state)

    assert _relation_local_app_alerts(state_out) == NO_ALERTS
