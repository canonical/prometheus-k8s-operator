# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.


import json

from ops.testing import Relation, State

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
