# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

"""## Overview.

This document explains how to integrate with the Grafana charm
for the purpose of providing a datasource which can be used by
Grafana dashboards. It also explains the structure of the data
expected by the `grafana-source` interface, and may provide a
mechanism or reference point for providing a compatible interface
or library by providing a definitive reference guide to the
structure of relation data which is shared between the Grafana
charm and any charm providing datasource information.

## Provider Library Usage

The Grafana charm interacts with its datasources using its charm
library. The goal of this library is to be as simple to use as
possible, and instantiation of the class with or without changing
the default arguments provides a complete use case. For the simplest
use case of a Prometheus (or Prometheus-compatible) datasource
provider in a charm which `provides: grafana-source`, creation of a
`GrafanaSourceProvider` object with the default arguments is sufficient.

The default arguments are:

    `charm`: `self` from the charm instantiating this library
    `source_type`: None
    `source_port`: None
    `source_url`: None
    `relation_name`: grafana-source
    `refresh_event`: A `PebbleReady` event from `charm`, used to refresh
        the IP address sent to Grafana on a charm lifecycle event or
        pod restart

The value of `source_url` should be a fully-resolvable URL for a valid Grafana
source, e.g., `http://example.com/api` or similar.

If your configuration requires any changes from these defaults, they
may be set from the class constructor. It may be instantiated as
follows:

    from charms.grafana_k8s.v0.grafana_source import GrafanaSourceProvider

    class FooCharm:
        def __init__(self, *args):
            super().__init__(*args, **kwargs)
            ...
            self.grafana_source_provider = GrafanaSourceProvider(
                self, source_type="prometheus", source_port="9090"
            )
            ...

The first argument (`self`) should be a reference to the parent (datasource)
charm, as this charm's model will be used for relation data, IP addresses,
and lifecycle events.

An instantiated `GrafanaSourceProvider` will ensure that each unit of its
parent charm is added as a datasource in the Grafana configuration once a
relation is established, using the [Grafana datasource provisioning](
https://grafana.com/docs/grafana/latest/administration/provisioning/#data-sources)
specification via YAML files.

This information is added to the relation data for the charms as serialized JSON
from a dict, with a structure of:
```
{
    "application": {
        "model": charm.model.name, # from `charm` in the constructor
        "model_uuid": charm.model.uuid,
        "application": charm.model.app.name,
        "type": source_type,
    },
    "unit/0": {
        "uri": {ip_address}:{port}{path} # `ip_address` is derived at runtime, `port` from the constructor,
                                         # and `path` from the constructor, if specified
    },
```

This is ingested by :class:`GrafanaSourceConsumer`, and is sufficient for configuration.


## Consumer Library Usage

The `GrafanaSourceConsumer` object may be used by Grafana
charms to manage relations with available datasources. For this
purpose, a charm consuming Grafana datasource information should do
the following things:

1. Instantiate the `GrafanaSourceConsumer` object by providing it a
reference to the parent (Grafana) charm and, optionally, the name of
the relation that the Grafana charm uses to interact with datasources.
This relation must confirm to the `grafana-source` interface.

For example a Grafana charm may instantiate the
`GrafanaSourceConsumer` in its constructor as follows

    from charms.grafana_k8s.v0.grafana_source import GrafanaSourceConsumer

    def __init__(self, *args):
        super().__init__(*args)
        ...
        self.grafana_source_consumer = GrafanaSourceConsumer(self)
        ...

2. A Grafana charm also needs to listen to the
`GrafanaSourceEvents` events emitted by the `GrafanaSourceConsumer`
by adding itself as an observer for these events:

    self.framework.observe(
        self.grafana_source_consumer.on.sources_changed,
        self._on_sources_changed,
    )
    self.framework.observe(
        self.grafana_source_consumer.on.sources_to_delete_changed,
        self._on_sources_to_delete_change,
    )

The reason for two separate events is that Grafana keeps track of
removed datasources in its [datasource provisioning](
https://grafana.com/docs/grafana/latest/administration/provisioning/#data-sources).

If your charm is merely implementing a `grafana-source`-compatible API,
and is does not follow exactly the same semantics as Grafana, observing these
events may not be needed.
"""

import json
import logging
import re
from typing import Any, Dict, List, Optional, Union

from ops.charm import (
    CharmBase,
    CharmEvents,
    RelationChangedEvent,
    RelationDepartedEvent,
    RelationEvent,
    RelationJoinedEvent,
    RelationRole,
)
from ops.framework import (
    BoundEvent,
    EventBase,
    EventSource,
    Object,
    ObjectEvents,
    StoredDict,
    StoredList,
    StoredState,
)
from ops.model import Relation

# The unique Charmhub library identifier, never change it
LIBID = "974705adb86f40228298156e34b460dc"

# Increment this major API version when introducing breaking changes
LIBAPI = 0

# Increment this PATCH version before using `charmcraft publish-lib` or reset
# to 0 if you are raising the major API version
LIBPATCH = 9

logger = logging.getLogger(__name__)

DEFAULT_RELATION_NAME = "grafana-source"
DEFAULT_PEER_NAME = "grafana"
RELATION_INTERFACE_NAME = "grafana_datasource"


def _type_convert_stored(obj):
    """Convert Stored* to their appropriate types, recursively."""
    if isinstance(obj, StoredList):
        return list(map(_type_convert_stored, obj))
    elif isinstance(obj, StoredDict):
        rdict = {}
        for k in obj.keys():
            rdict[k] = _type_convert_stored(obj[k])
        return rdict
    else:
        return obj


class RelationNotFoundError(Exception):
    """Raised if there is no relation with the given name."""

    def __init__(self, relation_name: str):
        self._relation_name = relation_name
        self.message = "No relation named '{}' found".format(relation_name)

        super().__init__(self.message)


class RelationInterfaceMismatchError(Exception):
    """Raised if the relation with the given name has a different interface."""

    def __init__(
        self,
        relation_name: str,
        expected_relation_interface: str,
        actual_relation_interface: str,
    ):
        self._relation_name = relation_name
        self.expected_relation_interface = expected_relation_interface
        self.actual_relation_interface = actual_relation_interface
        self.message = (
            "The '{}' relation has '{}' as "
            "interface rather than the expected '{}'".format(
                relation_name, actual_relation_interface, expected_relation_interface
            )
        )

        super().__init__(self.message)


class RelationRoleMismatchError(Exception):
    """Raised if the relation with the given name has a different direction."""

    def __init__(
        self,
        relation_name: str,
        expected_relation_role: RelationRole,
        actual_relation_role: RelationRole,
    ):
        self._relation_name = relation_name
        self.expected_relation_interface = expected_relation_role
        self.actual_relation_role = actual_relation_role
        self.message = "The '{}' relation has role '{}' rather than the expected '{}'".format(
            relation_name, repr(actual_relation_role), repr(expected_relation_role)
        )

        super().__init__(self.message)


def _validate_relation_by_interface_and_direction(
    charm: CharmBase,
    relation_name: str,
    expected_relation_interface: str,
    expected_relation_role: RelationRole,
) -> None:
    """Verifies that a relation has the necessary characteristics.

    Verifies that the `relation_name` provided: (1) exists in metadata.yaml,
    (2) declares as interface the interface name passed as `relation_interface`
    and (3) has the right "direction", i.e., it is a relation that `charm`
    provides or requires.

    Args:
        charm: a `CharmBase` object to scan for the matching relation.
        relation_name: the name of the relation to be verified.
        expected_relation_interface: the interface name to be matched by the
            relation named `relation_name`.
        expected_relation_role: whether the `relation_name` must be either
            provided or required by `charm`.
    """
    if relation_name not in charm.meta.relations:
        raise RelationNotFoundError(relation_name)

    relation = charm.meta.relations[relation_name]

    actual_relation_interface = relation.interface_name
    if actual_relation_interface != expected_relation_interface:
        raise RelationInterfaceMismatchError(
            relation_name, expected_relation_interface, actual_relation_interface
        )

    if expected_relation_role == RelationRole.provides:
        if relation_name not in charm.meta.provides:
            raise RelationRoleMismatchError(
                relation_name, RelationRole.provides, RelationRole.requires
            )
    elif expected_relation_role == RelationRole.requires:
        if relation_name not in charm.meta.requires:
            raise RelationRoleMismatchError(
                relation_name, RelationRole.requires, RelationRole.provides
            )
    else:
        raise Exception("Unexpected RelationDirection: {}".format(expected_relation_role))


class SourceFieldsMissingError(Exception):
    """An exception to indicate there a missing fields from a Grafana datsource definition."""

    pass


class GrafanaSourcesChanged(EventBase):
    """Event emitted when Grafana sources change."""

    def __init__(self, handle, data=None):
        super().__init__(handle)
        self.data = data

    def snapshot(self) -> Dict:
        """Save grafana source information."""
        return {"data": self.data}

    def restore(self, snapshot) -> None:
        """Restore grafana source information."""
        self.data = snapshot["data"]


class GrafanaSourceEvents(ObjectEvents):
    """Events raised by :class:`GrafanaSourceEvents."""

    # We are emitting multiple events for the same thing due to the way Grafana provisions
    # datasources. There is no "convenient" way to tell Grafana to remove them outside of
    # setting a separate "deleteDatasources" key in the configuration file to tell Grafana
    # to forget about them, and the reasons why sources_to_delete -> deleteDatasources
    # would be emitted is intrinsically linked to the sources themselves
    sources_changed = EventSource(GrafanaSourcesChanged)
    sources_to_delete_changed = EventSource(GrafanaSourcesChanged)


class GrafanaSourceProvider(Object):
    """A provider object for Grafana datasources."""

    def __init__(
        self,
        charm: CharmBase,
        source_type: str,
        source_port: Optional[str] = "",
        source_url: Optional[str] = "",
        refresh_event: Optional[BoundEvent] = None,
        relation_name: str = DEFAULT_RELATION_NAME,
    ) -> None:
        """Construct a Grafana charm client.

        The :class:`GrafanaSourceProvider` object provides an interface
        to Grafana. This interface supports providing additional
        sources for Grafana to monitor. For example, if a charm
        exposes some metrics which are consumable by an ingestor
        (such as Prometheus), then an additional source can be added
        by instantiating a :class:`GrafanaSourceProvider` object and
        adding its datasources as follows:

            self.grafana = GrafanaSourceProvider(self)
            self.grafana.add_source(
                address=<address>,
                port=<port>
            )

        Args:
            charm: a :class:`CharmBase` object which manages this
                :class:`GrafanaSourceProvider` object. Generally this is
                `self` in the instantiating class.
            source_type: an optional (default `prometheus`) source type
                required for Grafana configuration. The value must match
                the DataSource type from the Grafana perspective.
            source_port: an optional (default `9090`) source port
                required for Grafana configuration.
            source_url: an optional source URL which can be used, for example, if
                ingress for a source is enabled, or a URL path to the API consumed
                by the datasource must be specified for another reason. If set,
                'source_port' will not be used.
            relation_name: string name of the relation that is provides the
                Grafana source service. It is strongly advised not to change
                the default, so that people deploying your charm will have a
                consistent experience with all other charms that provide
                Grafana datasources.
            refresh_event: a :class:`CharmEvents` event on which the IP
                address should be refreshed in case of pod or
                machine/VM restart.
        """
        _validate_relation_by_interface_and_direction(
            charm, relation_name, RELATION_INTERFACE_NAME, RelationRole.provides
        )

        super().__init__(charm, relation_name)
        self._charm = charm
        self._relation_name = relation_name
        events = self._charm.on[relation_name]

        self._source_type = source_type

        if not refresh_event:
            if len(self._charm.meta.containers) == 1:
                container = list(self._charm.meta.containers.values())[0]
                refresh_event = self._charm.on[container.name.replace("-", "_")].pebble_ready

        if source_port and source_url:
            logger.warning(
                "Both `source_port` and `source_url` were specified! Using "
                "`source_url` as the address."
            )

        if source_url and not re.match(r"^\w+://", source_url):
            logger.warning(
                "'source_url' should start with a scheme, such as "
                "'http://'. Assuming 'http://' since none is present."
            )
            source_url = "http://{}".format(source_url)

        self._source_port = source_port
        self._source_url = source_url

        self.framework.observe(events.relation_joined, self._set_sources_from_event)
        if refresh_event:
            self.framework.observe(refresh_event, self._set_unit_details)

    def update_source(self, source_url: Optional[str] = ""):
        """Trigger the update of relation data."""
        if source_url:
            self._source_url = source_url

        rel = self._charm.model.get_relation(self._relation_name)

        if not rel:
            return

        self._set_sources(rel)

    def _set_sources_from_event(self, event: RelationJoinedEvent) -> None:
        """Get a `Relation` object from the event to pass on."""
        self._set_sources(event.relation)

    def _set_sources(self, rel: Relation):
        """Inform the consumer about the source configuration."""
        self._set_unit_details(rel)

        if not self._charm.unit.is_leader():
            return

        logger.debug("Setting Grafana data sources: %s", self._scrape_data)
        rel.data[self._charm.app]["grafana_source_data"] = json.dumps(self._scrape_data)

    @property
    def _scrape_data(self) -> Dict:
        """Generate source metadata.

        Returns:
            Source configuration data for Grafana.
        """
        data = {
            "model": str(self._charm.model.name),
            "model_uuid": str(self._charm.model.uuid),
            "application": str(self._charm.model.app.name),
            "type": self._source_type,
        }
        return data

    def _set_unit_details(self, _: Union[BoundEvent, RelationEvent, Relation]):
        """Set unit host details.

        Each time a provider charm container is restarted it updates its own host address in the
        unit relation data for the Prometheus consumer.
        """
        for relation in self._charm.model.relations[self._relation_name]:
            # network.bind_address can return `None` and give us a bad string, so make sure
            # that it's valid before passing it. Otherwise, we'll catch is on pebble_ready.
            # The provider side already skips adding it if `grafana_source_host` is not set,
            # so no additional guards needed
            url = None
            if self._source_url:
                url = self._source_url
            else:
                address = self._charm.model.get_binding(relation).network.bind_address
                if address:
                    url = "{}:{}".format(str(address), self._source_port)

            # If _source_url was not set in the constructor and there are no units in the
            # relation or pebble or address was not bound, this may not be set
            if url:
                relation.data[self._charm.unit]["grafana_source_host"] = url


class GrafanaSourceConsumer(Object):
    """A consumer object for working with Grafana datasources."""

    on = GrafanaSourceEvents()
    _stored = StoredState()

    def __init__(
        self,
        charm: CharmBase,
        relation_name: str = DEFAULT_RELATION_NAME,
    ) -> None:
        """A Grafana based Monitoring service consumer, i.e., the charm that uses a datasource.

        Args:
            charm: a :class:`CharmBase` instance that manages this
                instance of the Grafana source service.
            relation_name: string name of the relation that is provides the
                Grafana source service. It is strongly advised not to change
                the default, so that people deploying your charm will have a
                consistent experience with all other charms that provide
                Grafana datasources.
        """
        _validate_relation_by_interface_and_direction(
            charm, relation_name, RELATION_INTERFACE_NAME, RelationRole.requires
        )

        super().__init__(charm, relation_name)
        self._relation_name = relation_name
        self._charm = charm
        events = self._charm.on[relation_name]

        # We're stuck with this forever now so upgrades work, or until such point as we can
        # break compatibility
        self._stored.set_default(
            sources=dict(),
            sources_to_delete=set(),
        )

        self.framework.observe(events.relation_changed, self._on_grafana_source_relation_changed)
        self.framework.observe(events.relation_departed, self._on_grafana_source_relation_departed)
        self.framework.observe(
            self._charm.on[DEFAULT_PEER_NAME].relation_changed,
            self._on_grafana_peer_changed,
        )

    def _on_grafana_source_relation_changed(self, event: CharmEvents) -> None:
        """Handle relation changes in related providers.

        If there are changes in relations between Grafana source consumers
        and providers, this event handler (if the unit is the leader) will
        get data for an incoming grafana-source relation through a
        :class:`GrafanaSourcesChanged` event, and make the relation data
        is available in the app's datastore object. This data is set using
        Juju application topology.

        The Grafana charm can then respond to the event to update its
        configuration.
        """
        if self._charm.unit.is_leader():
            sources = {}

            for rel in self._charm.model.relations[self._relation_name]:
                source = self._get_source_config(rel)
                if source:
                    sources[rel.id] = source

            self.set_peer_data("sources", sources)

        self.on.sources_changed.emit()

    def _on_grafana_peer_changed(self, _: RelationChangedEvent) -> None:
        """Emit source events on peer events so secondary charm data updates."""
        if self._charm.unit.is_leader():
            return
        self.on.sources_changed.emit()
        self.on.sources_to_delete_changed.emit()

    def _get_source_config(self, rel: Relation):
        """Generate configuration from data stored in relation data by providers."""
        source_data = json.loads(rel.data[rel.app].get("grafana_source_data", "{}"))
        if not source_data:
            return

        data = []

        sources_to_delete = self.get_peer_data("sources_to_delete")
        for unit_name, host_addr in self._relation_hosts(rel).items():
            unique_source_name = "juju_{}_{}_{}_{}".format(
                source_data["model"],
                source_data["model_uuid"],
                source_data["application"],
                unit_name.split("/")[1],
            )

            host = (
                "http://{}".format(host_addr) if not re.match(r"^\w+://", host_addr) else host_addr
            )

            host_data = {
                "unit": unit_name,
                "source_name": unique_source_name,
                "source_type": source_data["type"],
                "url": host,
            }

            if host_data["source_name"] in sources_to_delete:
                sources_to_delete.remove(host_data["source_name"])

            data.append(host_data)
        self.set_peer_data("sources_to_delete", list(sources_to_delete))
        return data

    def _relation_hosts(self, rel: Relation) -> Dict:
        """Fetch host names and address of all provider units for a single relation.

        Args:
            rel: An `ops.model.Relation` object for which the host name to
                address mapping is required.

        Returns:
            A dictionary that maps unit names to unit addresses for
            the specified relation.
        """
        hosts = {}
        for unit in rel.units:
            host_address = rel.data[unit].get("grafana_source_host")
            if not host_address:
                continue
            hosts[unit.name] = host_address
        return hosts

    def _on_grafana_source_relation_departed(self, event: RelationDepartedEvent) -> None:
        """Update job config when providers depart.

        When a Grafana source provider departs, the configuration
        for that provider is removed from the list of sources jobs,
        added to a list of sources to remove, and other providers
        are informed through a :class:`GrafanaSourcesChanged` event.
        """
        removed_source = False
        if self._charm.unit.is_leader():
            removed_source = self._remove_source_from_datastore(event)

        if removed_source:
            self.on.sources_to_delete_changed.emit()

    def _remove_source_from_datastore(self, event: RelationDepartedEvent) -> bool:
        """Remove the grafana-source from the datastore.

        Add the name to the list of sources to remove when a relation is broken.

        Returns a boolean indicating whether an event should be emitted.
        """
        rel_id = event.relation.id
        logger.debug("Removing all data for relation: {}".format(rel_id))

        stored_sources = self.get_peer_data("sources")

        removed_source = stored_sources.pop(str(rel_id), None)
        if removed_source:
            if event.unit:
                # Remove one unit only
                dead_unit = [s for s in removed_source if s["unit"] == event.unit.name][0]
                self._remove_source(dead_unit["source_name"])

                # Re-update the list of stored sources
                stored_sources[rel_id] = [
                    dict(s) for s in removed_source if s["unit"] != event.unit.name
                ]
            else:
                for host in removed_source:
                    self._remove_source(host["source_name"])

            self.set_peer_data("sources", stored_sources)
            return True
        return False

    def _remove_source(self, source_name: str) -> None:
        """Remove a datasource by name."""
        sources_to_delete = self.get_peer_data("sources_to_delete")
        if source_name not in sources_to_delete:
            sources_to_delete.append(source_name)
            self.set_peer_data("sources_to_delete", sources_to_delete)

    def upgrade_keys(self) -> None:
        """On upgrade, ensure stored data maintains compatibility."""
        # self._stored.sources may have hyphens instead of underscores in key names.
        # Make sure they reconcile.
        self._set_default_data()
        sources = _type_convert_stored(self._stored.sources)
        for rel_id in sources.keys():
            for i in range(len(sources[rel_id])):
                sources[rel_id][i].update(
                    {k.replace("-", "_"): v for k, v in sources[rel_id][i].items()}
                )

        # If there's stored data, merge it and purge it
        if self._stored.sources:
            self._stored.sources = {}
            peer_sources = self.get_peer_data("sources")
            sources.update(peer_sources)
            self.set_peer_data("sources", sources)

        if self._stored.sources_to_delete:
            old_sources_to_delete = _type_convert_stored(self._stored.sources_to_delete)
            self._stored.sources_to_delete = set()
            peer_sources_to_delete = set(self.get_peer_data("sources_to_delete"))
            sources_to_delete = set.union(old_sources_to_delete, peer_sources_to_delete)
            self.set_peer_data("sources_to_delete", sources_to_delete)

    @property
    def sources(self) -> List[dict]:
        """Returns an array of sources the source_consumer knows about."""
        sources = []
        stored_sources = self.get_peer_data("sources")
        for source in stored_sources.values():
            sources.extend([host for host in _type_convert_stored(source)])

        return sources

    @property
    def sources_to_delete(self) -> List[str]:
        """Returns an array of source names which have been removed."""
        return self.get_peer_data("sources_to_delete")

    def _set_default_data(self) -> None:
        """Set defaults if they are not in peer relation data."""
        data = {"sources": {}, "sources_to_delete": []}  # type: ignore
        for k, v in data.items():
            if not self.get_peer_data(k):
                self.set_peer_data(k, v)

    def set_peer_data(self, key: str, data: Any) -> None:
        """Put information into the peer data bucket instead of `StoredState`."""
        self._charm.peers.data[self._charm.app][key] = json.dumps(data)  # type: ignore

    def get_peer_data(self, key: str) -> Any:
        """Retrieve information from the peer data bucket instead of `StoredState`."""
        data = self._charm.peers.data[self._charm.app].get(key, "")  # type: ignore
        return json.loads(data) if data else {}
