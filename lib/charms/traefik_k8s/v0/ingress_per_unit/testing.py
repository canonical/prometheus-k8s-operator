# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.
"""Helpers for unit testing charms which use this library."""

from ops.model import Relation
from sborl.testing import MockRemoteRelationMixin

from .provides import IngressPerUnitProvider, IngressRequest
from .requires import IngressPerUnitRequirer


class MockIPUProvider(MockRemoteRelationMixin, IngressPerUnitProvider):
    """Class to help with unit testing ingress requirer charms.

    Exactly the same as the normal IngressPerUnitProvider but, acts as if it's on
    the remote side of any relation, and it automatically triggers events when
    responses are sent.
    """

    def get_request(self, relation: Relation):
        """Get the IngressRequest for the given Relation."""
        # reflect the relation for the request so that it appears remote
        return MockIngressRequest(self, relation)


class MockIngressRequest(IngressRequest):
    """Testing wrapper for an IngressRequest.

    Exactly the same as the normal IngressRequest but acts as if it's on the
    remote side of any relation, and it automatically triggers events when
    responses are sent.
    """

    @property
    def app(self):
        """The remote application."""
        return self._provider.harness.charm.app

    @property
    def units(self):
        """The remote units."""
        return [self._provider.harness.charm.unit]


class MockIPURequirer(MockRemoteRelationMixin, IngressPerUnitRequirer):
    """Class to help with unit testing ingress provider charms.

    Exactly the same as the normal IngressPerUnitRequirer, but acts as if it's on
    the remote side of any relation, and it automatically triggers events when
    requests are sent.
    """

    @property
    def urls(self):
        """The full ingress URLs to reach every unit.

        May return an empty dict if the URLs aren't available yet.
        """
        with self.remote_context(self.relation):
            return super().urls
