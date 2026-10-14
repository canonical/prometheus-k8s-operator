# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.


import json
from unittest.mock import patch

from ops.testing import Container, Exec, Relation, State

from src.charm import RECV_CA_CERT_FOLDER_PATH


def test_no_recv_ca_cert_relations_present(context, prometheus_container):
    # GIVEN the charm is deployed in isolation
    state = State(
        leader=True,
        containers={prometheus_container},
    )

    # WHEN any event is emitted
    out = context.run(context.on.update_status(), state)

    # THEN no recv_ca_cert-associated certs are present
    container = out.get_container("prometheus")
    fs = container.get_filesystem(context)
    assert not fs.joinpath(RECV_CA_CERT_FOLDER_PATH.lstrip("/")).exists()


def test_ca_forwarded_over_rel_data(context, prometheus_container):
    # Relation 1
    cert1a = "-----BEGIN CERTIFICATE-----\n ... cert1a ... \n-----END CERTIFICATE-----"
    cert1b = "-----BEGIN CERTIFICATE-----\n ... cert1b ... \n-----END CERTIFICATE-----"

    # Relation 2
    cert2a = "-----BEGIN CERTIFICATE-----\n ... cert2a ... \n-----END CERTIFICATE-----"
    cert2b = "-----BEGIN CERTIFICATE-----\n ... cert2b ... \n-----END CERTIFICATE-----"

    # GIVEN the charm is related to a CA
    relations = [
        Relation(
            "receive-ca-cert", remote_app_data={"certificates": json.dumps([cert1a, cert1b])}
        ),
        Relation(
            "receive-ca-cert", remote_app_data={"certificates": json.dumps([cert2a, cert2b])}
        ),
    ]
    state = State(leader=True, containers={prometheus_container}, relations=relations)

    # WHEN a certificate_set_updated event is emitted
    out_1 = context.run(context.on.relation_changed(relations[0]), state)

    # THEN recv_ca_cert-associated certs are present
    container = out_1.get_container("prometheus")
    fs = container.get_filesystem(context)
    certs_dir = fs.joinpath(RECV_CA_CERT_FOLDER_PATH.lstrip("/"))
    assert certs_dir.exists()
    certs = {file.read_text() for file in certs_dir.glob("*.crt")}
    assert certs == {cert1a, cert1b, cert2a, cert2b}

    # AND WHEN one relation is removed, i.e. a certificates_removed event is emitted
    state = State(leader=True, containers={prometheus_container}, relations=relations)
    out_2 = context.run(context.on.relation_broken(relations[0]), out_1)

    # THEN its certs are removed, but the others remain
    container = out_2.get_container("prometheus")
    fs = container.get_filesystem(context)
    certs_dir = fs.joinpath(RECV_CA_CERT_FOLDER_PATH.lstrip("/"))
    assert certs_dir.exists()
    certs = {file.read_text() for file in certs_dir.glob("*.crt")}
    assert certs == {cert2a, cert2b}


def test_ca_trust_survives_a_workload_container_restart(context, prometheus_container):
    cert = "-----BEGIN CERTIFICATE-----\n ... cert ... \n-----END CERTIFICATE-----"

    # GIVEN a `receive-ca-cert` relation whose CA was already trusted...
    relation = Relation("receive-ca-cert", remote_app_data={"certificates": json.dumps([cert])})
    state = State(leader=True, containers={prometheus_container}, relations=[relation])

    # ...but the workload container's filesystem is fresh (no CA files on disk),
    # simulating a restarted container whose relation data hasn't changed.
    assert not prometheus_container.get_filesystem(context).joinpath(
        RECV_CA_CERT_FOLDER_PATH.lstrip("/")
    ).exists()

    # WHEN only `pebble-ready` fires (no relation event)
    out = context.run(context.on.pebble_ready(prometheus_container), state)

    # THEN the CA trust bundle is (re)written anyway
    fs = out.get_container("prometheus").get_filesystem(context)
    certs_dir = fs.joinpath(RECV_CA_CERT_FOLDER_PATH.lstrip("/"))
    assert certs_dir.exists()
    assert {f.read_text() for f in certs_dir.glob("*.crt")} == {cert}


def test_update_ca_certs_is_a_noop_when_nothing_changed(context, prometheus_container):
    cert = "-----BEGIN CERTIFICATE-----\n ... cert ... \n-----END CERTIFICATE-----"
    relation = Relation("receive-ca-cert", remote_app_data={"certificates": json.dumps([cert])})
    state = State(leader=True, containers={prometheus_container}, relations=[relation])

    with context(context.on.pebble_ready(prometheus_container), state) as manager:
        charm = manager.charm

        # GIVEN the certs have already been written to the workload container once
        charm._update_ca_certs()
        fs = charm.unit.get_container("prometheus").list_files(RECV_CA_CERT_FOLDER_PATH)
        assert {f.path for f in fs} == {RECV_CA_CERT_FOLDER_PATH + "/0.crt"}

        # WHEN `_update_ca_certs` is called again with nothing changed
        with (
            patch("ops.model.Container.exec") as mock_exec,
            patch("ops.model.Container.restart") as mock_restart,
            patch("ops.model.Container.remove_path") as mock_remove_path,
        ):
            charm._update_ca_certs()

        # THEN none of the cert-refresh/restart machinery is invoked a second time
        mock_exec.assert_not_called()
        mock_restart.assert_not_called()
        mock_remove_path.assert_not_called()


def test_pebble_ready_does_not_crash_before_the_service_exists(context):
    """`_update_ca_certs` must not blow up restarting a service that was never started.

    On the very first `pebble-ready` of a fresh unit (before `_configure` has ever added the
    pebble layer), there is no "prometheus" service yet to restart.
    """
    container = Container(
        "prometheus",
        can_connect=True,
        execs={Exec(["update-ca-certificates", "--fresh"], return_code=0, stdout="")},
    )
    cert = "-----BEGIN CERTIFICATE-----\n ... cert ... \n-----END CERTIFICATE-----"
    relation = Relation("receive-ca-cert", remote_app_data={"certificates": json.dumps([cert])})
    state = State(leader=True, containers={container}, relations=[relation])

    # WHEN pebble-ready fires before any layer/service has ever been added
    out = context.run(context.on.pebble_ready(container), state)

    # THEN the charm doesn't crash, and the CA cert is still written to disk
    fs = out.get_container("prometheus").get_filesystem(context)
    certs_dir = fs.joinpath(RECV_CA_CERT_FOLDER_PATH.lstrip("/"))
    assert {f.read_text() for f in certs_dir.glob("*.crt")} == {cert}
