# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

import json

import yaml
from scenario import Container, Exec, Relation, State


def test_alert_expression_labels(context):
    """Check that juju_charm is not in the alert expression."""
    relation_data = {
        "alert_rules": json.dumps(
            {
                "groups": [
                    {
                        "name": "foobar-group",
                        "rules": [
                            {
                                "alert": "Foobar",
                                "expr": "up == 0",
                                "for": "0m",
                                "labels": {
                                    "juju_application": "remote-app",
                                    "juju_charm": "remote-charm",
                                    "juju_model": "foobar-model",
                                    "juju_model_uuid": "d07df316-6fc2-483a-bdee-69cbb9b1e7f2",
                                },
                            }
                        ],
                    }
                ]
            }
        )
    }

    remote_write_relation = Relation(
        endpoint="receive-remote-write",
        remote_app_name="remote-app",
        remote_app_data=relation_data,
    )
    container = Container(
        name="prometheus",
        can_connect=True,
        execs={Exec(["update-ca-certificates", "--fresh"], return_code=0, stdout="")},
    )
    state = State(containers=[container], relations=[remote_write_relation])
    context.run(context.on.relation_changed(remote_write_relation), state=state)
    rules_file = (
        container.get_filesystem(context)
        / "etc/prometheus/rules/juju_foobar-model_d07df316_remote-app.rules"
    )
    with rules_file.open() as f:
        alert_data = yaml.safe_load(f)
        assert "juju_charm" not in alert_data["groups"][0]["rules"][0]["expr"]
