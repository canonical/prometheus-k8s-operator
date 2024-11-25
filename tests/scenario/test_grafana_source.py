# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

import json

import pytest
from scenario import Container, ExecOutput, Relation, State


@pytest.mark.parametrize("this_app", ("prometheus", "prom"))
@pytest.mark.parametrize("this_unit_id", (0, 42))
def test_remote_write_dashboard_uid_propagation(context, this_app, this_unit_id):
    """Check that the grafana dashboard UIds are propagated over remote-write."""
    # GIVEN a remote-write relation

    remote_write_relation = Relation(
        endpoint="receive-remote-write",
    )

    # AND a grafana-source relation
    grafana_source_relation = Relation(
        endpoint="grafana-source",
        remote_app_name="grafana",
        local_unit_data={
            "grafana_source_host": "some-hostname"
        },
        local_app_data={
            "grafana_source_data": json.dumps(
                {"model": "foo", "model_uuid": "bar", "application": "baz", "type": "tempo"}
            )
        },

        remote_app_data={
            # the datasources provisioned by grafana for this relation
            "datasource_uids": json.dumps(
                {
                    f"{this_app}/{this_unit_id}": f"juju_foo_bar_{this_app}_{this_unit_id}",
                    # some peer unit
                    f"{this_app}/{this_unit_id+1}": f"juju_foo_bar_{this_app}_{this_unit_id+1}",
                 }
            )
    }
    )

    container = Container(
        name="prometheus",
        can_connect=True,
        exec_mock={("update-ca-certificates", "--fresh"): ExecOutput(return_code=0, stdout="")},
    )
    state = State(leader=True, containers=[container], relations=[remote_write_relation, grafana_source_relation])

    state_out = context.run(event=grafana_source_relation.changed_event, state=state)

    remote_write_out = state_out.get_relations("receive-remote-write")[0]
    shared_ds_uids = remote_write_out.local_app_data.get("datasource_uids")
    assert shared_ds_uids




