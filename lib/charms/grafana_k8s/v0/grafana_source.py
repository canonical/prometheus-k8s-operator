# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

"""A library for working with Grafana datasources for charm authors."""

import json
import logging
from typing import Dict, List, Optional, Union

from ops.charm import (
    CharmBase,
    CharmEvents,
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
LIBPATCH = 7

logger = logging.getLogger(__name__)

DEFAULT_RELATION_NAME = "grafana-source"
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

    _stored = StoredState()

    def __init__(
        self,
        charm: CharmBase,
        refresh_event: BoundEvent,
        relation_name: str = DEFAULT_RELATION_NAME,
        source_type: Optional[str] = "prometheus",
        source_port: Optional[str] = "9090",
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
            relation_name: string name of the relation that is provides the
                Grafana source service. It is strongly advised not to change
                the default, so that people deploying your charm will have a
                consistent experience with all other charms that provide
                Grafana datasources.
            refresh_event: a :class:`CharmEvents` event on which the IP
                address should be refreshed in case of pod or
                machine/VM restart.
            source_type: an optional (default `prometheus`) source type
                required for Grafana configuration. The value must match
                the DataSource type from the Grafana perspective.
            source_port: an optional (default `9090`) source port
                required for Grafana configuration.
        """
        _validate_relation_by_interface_and_direction(
            charm, relation_name, RELATION_INTERFACE_NAME, RelationRole.provides
        )

        super().__init__(charm, relation_name)
        self._charm = charm
        self._relation_name = relation_name
        events = self._charm.on[relation_name]

        self._source_type = source_type
        self._source_port = source_port

        self.framework.observe(events.relation_joined, self._set_sources)
        self.framework.observe(refresh_event, self._set_unit_ip)

    def _set_sources(self, event: RelationJoinedEvent):
        """Inform the consumer about the source configuration."""
        self._set_unit_ip(event)

        if not self._charm.unit.is_leader():
            return

        logger.debug("Setting Grafana data sources: %s", self._scrape_data)
        event.relation.data[self._charm.app]["grafana_source_data"] = json.dumps(self._scrape_data)

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

    def _set_unit_ip(self, _: Union[BoundEvent, RelationEvent]):
        """Set unit host address.

        Each time a provider charm container is restarted it updates its own host address in the
        unit relation data for the Prometheus consumer.
        """
        for relation in self._charm.model.relations[self._relation_name]:
            # network.bind_address can return `None` and give us a bad string, so make sure
            # that it's valid before passing it. Otherwise, we'll catch is on pebble_ready.
            # The provider side already skips adding it if `grafana_source_host` is not set,
            # so no additional guards needed
            address = self._charm.model.get_binding(relation).network.bind_address
            if address:
                relation.data[self._charm.unit]["grafana_source_host"] = "{}:{}".format(
                    str(address),
                    self._source_port,
                )


class GrafanaSourceConsumer(Object):
    """A consumer object for working with Grafana datasources."""

    on = GrafanaSourceEvents()
    _stored = StoredState()

    def __init__(self, charm: CharmBase, relation_name: str = DEFAULT_RELATION_NAME) -> None:
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

        self._stored.set_default(
            sources=dict(),
            sources_to_delete=set(),
        )

        self.framework.observe(events.relation_changed, self._on_grafana_source_relation_changed)
        self.framework.observe(events.relation_departed, self._on_grafana_source_relation_departed)

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
        if not self._charm.unit.is_leader():
            return

        sources = {}

        for rel in self._charm.model.relations[self._relation_name]:
            source = self._get_source_config(rel)
            if source:
                sources[rel.id] = source

        self._stored.sources = sources

        self.on.sources_changed.emit()

    def _get_source_config(self, rel: Relation):
        """Generate configuration from data stored in relation data by providers."""
        source_data = json.loads(rel.data[rel.app].get("grafana_source_data", "{}"))
        if not source_data:
            return

        data = []

        for unit_name, host_addr in self._relation_hosts(rel).items():
            unique_source_name = "juju_{}_{}_{}_{}".format(
                source_data["model"],
                source_data["model_uuid"],
                source_data["application"],
                unit_name.split("/")[1],
            )

            host_data = {
                "unit": unit_name,
                "source_name": unique_source_name,
                "source_type": source_data["type"],
                "url": "http://{}".format(host_addr),
            }

            if host_data["source_name"] in self._stored.sources_to_delete:
                self._stored.sources_to_delete.remove(host_data["source_name"])

            data.append(host_data)
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
        if not self._charm.unit.is_leader():
            return

        self._remove_source_from_datastore(event)

    def _remove_source_from_datastore(self, event: RelationDepartedEvent) -> None:
        """Remove the grafana-source from the datastore.

        Add the name to the list of sources to remove when a relation is broken.
        """
        rel_id = event.relation.id
        logger.debug("Removing all data for relation: {}".format(rel_id))

        removed_source = self._stored.sources.pop(rel_id, None)
        if removed_source:
            if event.unit:
                # Remove one unit only
                dead_unit = [s for s in removed_source if s["unit"] == event.unit.name][0]
                self._remove_source(dead_unit["source_name"])

                # Re-update the list of stored sources
                self._stored.sources[rel_id] = [
                    dict(s) for s in removed_source if s["unit"] != event.unit.name
                ]
            else:
                for host in removed_source:
                    self._remove_source(host["source_name"])

            self.on.sources_to_delete_changed.emit()

    def _remove_source(self, source_name: str) -> None:
        """Remove a datasource by name."""
        self._stored.sources_to_delete.add(source_name)

    def upgrade_keys(self) -> None:
        """On upgrade, ensure stored data maintains compatibility."""
        # self._stored.sources may have hyphens instead of underscores in key names.
        # Make sure they reconcile.
        sources = _type_convert_stored(self._stored.sources)
        for rel_id in sources.keys():
            for i in range(len(sources[rel_id])):
                sources[rel_id][i].update(
                    {k.replace("-", "_"): v for k, v in sources[rel_id][i].items()}
                )

        self._stored.sources = sources

    @property
    def sources(self) -> List[dict]:
        """Returns an array of sources the source_consumer knows about."""
        sources = []
        for source in self._stored.sources.values():
            sources.extend([host for host in _type_convert_stored(source)])

        return sources

    @property
    def sources_to_delete(self) -> List[str]:
        """Returns an array of source names which have been removed."""
        return [_type_convert_stored(source) for source in self._stored.sources_to_delete]
