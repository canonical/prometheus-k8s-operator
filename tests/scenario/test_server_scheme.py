# Copyright 2023 Canonical Ltd.
# See LICENSE file for licensing details.

"""Feature: The workload's scheme is reflected in the pebble command and in relation data.

This feature spans:
- manifest generation (pebble layer)
- schema generation (relation data)

Prometheus can serve over HTTP or HTTPS.
"""

import json
from unittest.mock import patch

import pytest
from helpers import add_relation_sequence, begin_with_initial_hooks_isolated
from scenario import Relation, State


@pytest.mark.parametrize("fqdn", ["localhost", "am-0.endpoints.cluster.local"])
@pytest.mark.parametrize("leader", [True, False])
class TestServerScheme:
    """Scenario: The workload is deployed to operate in HTTP mode, then switched to HTTPS."""

    @pytest.fixture
    def initial_state(self, context, fqdn, leader) -> State:
        """This is the initial state for this test class."""
        # GIVEN an isolated charm after the startup sequence is complete

        # No "tls-certificates" relation, no config options
        with patch("socket.getfqdn", new=lambda *args: fqdn):
            state = begin_with_initial_hooks_isolated(context, leader=leader)

            # Add relations
            rels = [
                Relation("self-metrics-endpoint"),  # external self-monitoring
                Relation("grafana-source"),  # grafana
                Relation("receive-remote-write"),  # grafana-agent
            ]
            for rel in rels:
                state = add_relation_sequence(context, state, rel)

            yield state  # keep the patch active for so long as this fixture is needed

    def test_initial_state_has_http_scheme_in_pebble_layer(self, context, initial_state, fqdn):
        # THEN the pebble command has 'http' and the correct hostname in the 'web.external-url' arg
        container = initial_state.get_container("prometheus")
        command = container.layers["prometheus"].services["prometheus"].command
        assert f"--web.external-url=http://{fqdn}:9090" in command

    @pytest.mark.skip(reason="xfail")
    def test_pebble_layer_scheme_becomes_https_if_tls_relation_added(
        self, context, initial_state, fqdn
    ):
        # WHEN a tls_certificates relation joins
        ca = Relation(
            "certificates",
            id=100,
            remote_app_data={
                "certificates": json.dumps(
                    [
                        {
                            # fixme: the problem is: instead of "placeholder" here we need a forward ref to the
                            #  CSR that AM will generate on certificates_relation_joined.
                            #  Otherwise, as it stands, charms/tls_certificates_interface/v2/tls_certificates.py:1336 will not find
                            #  this csr and ignore it. Hence no handlers are triggered.
                            "certificate": "placeholder",
                            "certificate_signing_request": "placeholder",
                            "ca": "placeholder",
                            "chain": ["first", "second"],
                        }
                    ]
                )
            },
        )  # TODO figure out how to easily figure out structure of remote data
        state = add_relation_sequence(context, initial_state, ca)
        # TODO figure out why relation-changed observer in tls_certificates is not being called

        # TODO how to manually emit the `cert_handler.on.cert_changed` event?
        state = context.run("cert_handler.on.cert_changed", state)

        # THEN the pebble command has 'https' in the 'web.external-url' arg
        container = state.get_container("prometheus")
        command = container.layers["prometheus"].services["prometheus"].command
        assert f"--web.external-url=https://{fqdn}:9090" in command
