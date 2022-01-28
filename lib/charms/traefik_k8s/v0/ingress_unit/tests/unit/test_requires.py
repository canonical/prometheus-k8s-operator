# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

from ipaddress import IPv4Address
from textwrap import dedent
from unittest.mock import Mock

from charms.traefik_k8s.v0.ingress_unit import IngressUnitRequirer
from charms.traefik_k8s.v0.ingress_unit.testing import MockIPUProvider
from ops.charm import CharmBase
from ops.model import Binding
from ops.testing import Harness


class MockRequirerCharm(CharmBase):
    META = dedent(
        """\
        name: test-requirer
        requires:
          ingress-unit:
            interface: ingress-unit
            limit: 1
        """
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.ipu = IngressUnitRequirer(self, port=80)


def test_ingress_requirer(monkeypatch):
    monkeypatch.setattr(Binding, "network", Mock(bind_address=IPv4Address("10.10.10.10")))
    harness = Harness(MockRequirerCharm, meta=MockRequirerCharm.META)
    harness._backend.model_name = "test-model"
    harness.set_leader(False)
    harness.begin_with_initial_hooks()
    requirer = harness.charm.ipu
    provider = MockIPUProvider(harness)

    assert not requirer.is_available()
    assert not requirer.is_ready()
    assert not requirer.is_failed()
    assert not provider.is_available()
    assert not provider.is_ready()
    assert not provider.is_failed()

    relation = provider.relate()
    assert requirer.is_available(relation)
    assert not requirer.is_ready(relation)
    assert not requirer.is_failed(relation)
    assert not provider.is_available(relation)
    assert not provider.is_ready(relation)
    assert provider.is_failed(relation)  # because it has a unit but no versions

    harness.set_leader(True)
    assert requirer.is_available(relation)
    assert not requirer.is_ready(relation)
    assert not requirer.is_failed(relation)
    assert provider.is_available(relation)
    assert provider.is_ready(relation)
    assert not provider.is_failed(relation)

    request = provider.get_request(relation)
    assert request.units[0] is requirer.charm.unit
    assert request.app_name == "test-requirer"
    request.respond(requirer.charm.unit, "http://url/")
    assert requirer.is_available(relation)
    assert requirer.is_ready(relation)
    assert not requirer.is_failed(relation)
    assert requirer.urls == {"test-requirer/0": "http://url/"}
    assert requirer.url == "http://url/"
