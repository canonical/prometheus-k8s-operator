# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

from textwrap import dedent
from unittest.mock import Mock

from charms.traefik_k8s.v0.ingress_unit import IngressUnitProvider
from charms.traefik_k8s.v0.ingress_unit.testing import MockIPURequirer
from ops.charm import CharmBase
from ops.model import Binding
from ops.testing import Harness


class MockProviderCharm(CharmBase):
    META = dedent(
        """\
        name: test-provider
        provides:
          ingress-unit:
            interface: ingress-unit
            limit: 1
        """
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.ipu = IngressUnitProvider(self)


def test_ingress_provider(monkeypatch):
    monkeypatch.setattr(Binding, "network", Mock(bind_address="10.10.10.10"))
    harness = Harness(MockProviderCharm, meta=MockProviderCharm.META)
    harness._backend.model_name = "test-model"
    harness.set_leader(False)
    harness.begin_with_initial_hooks()
    provider = harness.charm.ipu
    requirer = MockIPURequirer(harness)

    assert not provider.is_available()
    assert not provider.is_ready()
    assert not provider.is_failed()
    assert not requirer.is_available()
    assert not requirer.is_ready()
    assert not requirer.is_failed()

    relation = requirer.relate()
    assert provider.is_available(relation)
    assert not provider.is_ready(relation)
    assert not provider.is_failed(relation)
    assert not requirer.is_available(relation)
    assert not requirer.is_ready(relation)
    assert requirer.is_failed(relation)  # because it has a unit but no versions

    harness.set_leader(True)
    assert provider.is_available(relation)
    assert not provider.is_ready(relation)
    assert not provider.is_failed(relation)
    assert requirer.is_available(relation)
    assert not requirer.is_ready(relation)
    assert not requirer.is_failed(relation)

    requirer.request(port=80)
    assert provider.is_available(relation)
    assert provider.is_ready(relation)
    assert not provider.is_failed(relation)
    assert requirer.is_available(relation)
    assert not requirer.is_ready(relation)
    assert not requirer.is_failed(relation)

    request = provider.get_request(relation)
    assert request.units[0] is requirer.charm.unit
    assert request.app_name == "ingress-unit-remote"
    request.respond(requirer.charm.unit, "http://url/")
    assert requirer.is_available(relation)
    assert requirer.is_ready(relation)
    assert not requirer.is_failed(relation)
    assert requirer.urls == {"ingress-unit-remote/0": "http://url/"}
    assert requirer.url == "http://url/"
