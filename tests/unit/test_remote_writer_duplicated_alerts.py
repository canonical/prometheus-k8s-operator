import json
from pathlib import Path

import yaml
from scenario import Container, Context, Exec, Relation, State

COLLECTOR_CHARM = "opentelemetry-collector-k8s"
ALERT_RULES = {
    "groups": [
        {
            "name": "test-model_e674af04-0e76-4c11-92a0-f219fa8b4386_remote_writer",
            "rules": [
                {
                    "alert": "HostMetricsMissing",
                    "expr": 'absent(up{juju_application="remote_writer",juju_model="test-model",juju_model_uuid="e674af04-0e76-4c11-92a0-f219fa8b4386"}) == 0',
                    "for": "0m",
                    "labels": {
                        "severity": "critical",
                        "juju_model": "test-model",
                        "juju_model_uuid": "e674af04-0e76-4c11-92a0-f219fa8b4386",
                        "juju_application": "remote_writer",
                        "juju_charm": COLLECTOR_CHARM,
                    },
                    "annotations": {
                        "summary": "Prometheus target missing (instance {{ $labels.instance }})",
                        "description": "A Prometheus target has disappeared."
                        "VALUE = {{ $value }}\n  LABELS = {{ $labels }}",
                    },
                },

            ],
        }
    ]
}
"""
{
    "alert": "HostMetricsMissing",
    "expr": 'absent(up{juju_application="not_collector",juju_model="test-model",juju_model_uuid="e674af04-0e76-4c11-92a0-f219fa8b4386"}) == 0',
    "for": "0m",
    "labels": {
        "severity": "critical",
        "juju_model": "test-model",
        "juju_model_uuid": "e674af04-0e76-4c11-92a0-f219fa8b4386",
        "juju_application": "not_collector",
        "juju_charm": "non_remote_writer_k8s",
    },
    "annotations": {
        "summary": "Prometheus target missing (instance {{ $labels.instance }})",
        "description": "A Prometheus target has disappeared."
        "VALUE = {{ $value }}\n  LABELS = {{ $labels }}",
    },
},
"""

EXPECTED_ALERTS = {
    "groups": [
        {
            "name": "test-model_e674af04-0e76-4c11-92a0-f219fa8b4386_remote_writer",
            "rules": [
                {
                    "alert": "HostMetricsMissing",
                    "expr": 'absent(up{juju_application="remote_writer",juju_model="test-model",juju_model_uuid="e674af04-0e76-4c11-92a0-f219fa8b4386",juju_unit="remote_writer/0"}) == 0',
                    "for": "0m",
                    "labels": {
                        "severity": "critical",
                        "juju_model": "test-model",
                        "juju_model_uuid": "e674af04-0e76-4c11-92a0-f219fa8b4386",
                        "juju_application": "remote_writer",
                        "juju_charm": COLLECTOR_CHARM,
                        "juju_unit": "remote_writer/0",
                    },
                    "annotations": {
                        "summary": "Prometheus target missing (instance {{ $labels.instance }})",
                        "description": "A Prometheus target has disappeared."
                        "VALUE = {{ $value }}\n  LABELS = {{ $labels }}",
                    },
                },
                {
                    "alert": "HostMetricsMissing",
                    "expr": 'absent(up{juju_application="remote_writer",juju_model="test-model",juju_model_uuid="e674af04-0e76-4c11-92a0-f219fa8b4386",juju_unit="remote_writer/1"}) == 0',
                    "for": "0m",
                    "labels": {
                        "severity": "critical",
                        "juju_model": "test-model",
                        "juju_model_uuid": "e674af04-0e76-4c11-92a0-f219fa8b4386",
                        "juju_application": "remote_writer",
                        "juju_charm": COLLECTOR_CHARM,
                        "juju_unit": "remote_writer/1",
                    },
                    "annotations": {
                        "summary": "Prometheus target missing (instance {{ $labels.instance }})",
                        "description": "A Prometheus target has disappeared."
                        "VALUE = {{ $value }}\n  LABELS = {{ $labels }}",
                    },
                },
                {
                    "alert": "HostMetricsMissing",
                    "expr": 'absent(up{juju_application="remote_writer",juju_model="test-model",juju_model_uuid="e674af04-0e76-4c11-92a0-f219fa8b4386",juju_unit="remote_writer/2"}) == 0',
                    "for": "0m",
                    "labels": {
                        "severity": "critical",
                        "juju_model": "test-model",
                        "juju_model_uuid": "e674af04-0e76-4c11-92a0-f219fa8b4386",
                        "juju_application": "remote_writer",
                        "juju_charm": COLLECTOR_CHARM,
                        "juju_unit": "remote_writer/2",
                    },
                    "annotations": {
                        "summary": "Prometheus target missing (instance {{ $labels.instance }})",
                        "description": "A Prometheus target has disappeared."
                        "VALUE = {{ $value }}\n  LABELS = {{ $labels }}",
                    },
                },
            ],
        },

    ]
}

def test_remote_write_absent_alert_duplicated_for_units(context: Context):
    # WHEN any event happens on prometheus with a default config
    relation = Relation(
        id=1,
        endpoint="receive-remote-write",
        remote_app_data={"alert_rules": json.dumps(ALERT_RULES)},
        remote_units_data={0: {}, 1: {}, 2: {}}, # Simulate 3 units (ref: https://github.com/canonical/operator/blob/5e752be44086c580a449a2b07e2327ddbf6783d0/testing/tests/test_e2e/test_relations.py#L430-L436)
    )
    container = Container(
        "prometheus",
        can_connect=True,
        execs={Exec(["update-ca-certificates", "--fresh"], return_code=0, stdout="")},
    )
    state = State(containers=[container], relations=[relation])
    state_out = context.run(context.on.upgrade_charm(), state)
    prometheus = state_out.get_container("prometheus")

    fs = prometheus.get_filesystem(context)
    rules_path = "/etc/prometheus/rules"
    rules_dir = fs.joinpath(*rules_path.strip("/").split("/"))

    # Get the files inside the /etc/prometheus/rules dir
    files = [str(f) for f in rules_dir.iterdir() if f.is_file()]

    # In this test, we only have one remote write relation so we should only get one rule file.
    assert files[0]

    # AND the content of the rule file is equal to the expected rule.
    # This means that the one alert rule coming from relation data for HostMetricsMissing should've now been duplicated for all units of the collector/aggregator.
    # In this case, since we have 3 units, we expect to get 3 alerts.
    rules = yaml.safe_load(Path(files[0]).read_text())
    assert rules == EXPECTED_ALERTS
