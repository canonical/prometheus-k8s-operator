# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.
"""Provides side of ingress-unit relation."""

import logging
from pathlib import Path

import sborl
from ops.charm import CharmBase, RelationEvent
from ops.framework import EventSource
from ops.model import Relation, Unit

try:
    # introduced in 3.9
    from functools import cache
except ImportError:
    from functools import lru_cache

    cache = lru_cache(maxsize=None)

log = logging.getLogger(__name__)


class IngressUnitRequestEvent(RelationEvent):
    """Event representing an incoming request.

    This is equivalent to the "ready" event, but is more semantically meaningful.
    """


class IngressUnitProviderEvents(sborl.events.EndpointWrapperEvents):
    """Container for IUP events."""

    request = EventSource(IngressUnitRequestEvent)


class IngressUnitProvider(sborl.EndpointWrapper):
    """Implementation of the provider of ingress-unit."""

    ROLE = "provides"
    INTERFACE = "ingress-unit"
    SCHEMA = Path(__file__).parent / "schema.yaml"

    on = IngressUnitProviderEvents()

    def __init__(self, charm: CharmBase, endpoint: str = None):
        """Constructor for IngressUnitProvider.

        Args:
            charm: The charm that is instantiating the instance.
            endpoint: The name of the relation endpoint to bind to
                (defaults to "ingress-unit").
        """
        super().__init__(charm, endpoint)
        self.framework.observe(self.on.ready, self._emit_request_event)

    def _emit_request_event(self, event):
        self.on.request.emit(event.relation)

    def get_request(self, relation: Relation):
        """Get the IngressRequest for the given Relation."""
        return IngressRequest(self, relation)

    @cache
    def is_failed(self, relation: Relation = None):
        """Checks whether the given relation, or any relation if not specified, has an error."""
        if relation is None:
            return any(self.is_failed(relation) for relation in self.relations)
        if not relation.units:
            return False
        if super().is_failed(relation):
            return True
        data = self.unwrap(relation)
        prev_fields = None
        for unit in relation.units:
            if not data[unit]:
                continue
            new_fields = {field: data[unit][field] for field in ("model", "port", "rewrite")}
            if prev_fields is None:
                prev_fields = new_fields
            if new_fields != prev_fields:
                raise RelationDataMismatchError(relation, unit)
        return False


class IngressRequest:
    """A request for per-unit ingress."""

    def __init__(self, provider: IngressUnitProvider, relation: Relation):
        """Construct an IngressRequest."""
        self._provider = provider
        self._relation = relation
        self._data = provider.unwrap(relation)

    @property
    def app(self):
        """The remote application."""
        return self._relation.app

    @property
    def units(self):
        """The remote units."""
        return sorted(self._relation.units, key=lambda unit: unit.name)

    @property
    def model(self):
        """The name of the model the request was made from."""
        return self._data[self.units[0]]["model"]

    @property
    def app_name(self):
        """The name of the remote app.

        Note: This is not the same as `self.app.name` when using CMR relations,
        since `self.app.name` is replaced by a UUID to avoid ambiguity.
        """
        return self._data[self.units[0]]["name"].split("/")[0]

    @property
    def port(self):
        """The backend port."""
        return self._data[self.units[0]]["port"]

    @property
    def rewrite(self):
        """The backend path."""
        return self._data[self.units[0]]["rewrite"]

    def get_prefix(self, unit: Unit):
        """Return the prefix for the given unit."""
        return self._data[unit]["prefix"]

    def get_ip(self, unit: Unit):
        """Return the IP of the given unit."""
        return self._data[unit]["ip"]

    def respond(self, unit: Unit, url: str):
        """Send URL back for the given unit.

        Note: only the leader can send URLs.
        """
        # Can't use `unit.name` because with CMR it's a UUID.
        remote_unit_name = self._data[unit]["name"]
        ingress = self._data[self._provider.charm.app].setdefault("ingress", {})
        ingress.setdefault(remote_unit_name, {})["url"] = url
        self._provider.wrap(self._relation, self._data)


class RelationDataMismatchError(sborl.errors.RelationDataError):
    """Data from different units do not match where they should."""
