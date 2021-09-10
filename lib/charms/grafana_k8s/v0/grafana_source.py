# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

"""A library for working with Grafana datasources for charm authors."""

import json
import logging
from typing import Dict, List, Optional

from ops.charm import CharmBase, CharmEvents, RelationDepartedEvent, RelationJoinedEvent
from ops.framework import EventBase, EventSource, Object, ObjectEvents, StoredState
from ops.model import Relation

# The unique Charmhub library identifier, never change it
LIBID = "974705adb86f40228298156e34b460dc"

# Increment this major API version when introducing breaking changes
LIBAPI = 0

# Increment this PATCH version before using `charmcraft publish-lib` or reset
# to 0 if you are raising the major API version
LIBPATCH = 1

logger = logging.getLogger(__name__)


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


class GrafanaSourceConsumer(Object):
    """A consumer object for Grafana datasources."""

    _stored = StoredState()

    def __init__(
        self,
        charm: CharmBase,
        name: str,
        refresh_event: CharmEvents,
        source_type: Optional[str] = "prometheus",
        source_port: Optional[str] = "9090",
    ) -> None:
        """Construct a Grafana charm client.

        The :class:`GrafanaSourceConsumer` object provides an interface
        to Grafana. This interface supports providing additional
        sources for Grafana to monitor. For example, if a charm
        exposes some metrics which are consumable by an ingestor
        (such as Prometheus), then an additional source can be added
        by instantiating a :class:`GrafanaSourceConsumer` object and
        adding its datasources as follows:

            self.grafana = GrafanaSourceConsumer(
                self, "grafana-datasource", {"grafana_datasource"}: ">=2.0"}
            )
            self.grafana.add_source(
                address=<address>,
                port=<port>
            )

        Args:
            charm: a :class:`CharmBase` object which manages this
                :class:`GrafanaSourceConsumer` object. Generally this is
                `self` in the instantiating class.
            name: a :string: name of the relation between `charm`
                the Grafana charmed service.
            refresh_event: a :class:`CharmEvents` event on which the IP
                address should be refreshed in case of pod or
                machine/VM restart.
            source_type: an optional (default `prometheus`) source type
                required for Grafana configuration
            source_port: an optional (default `9090`) source port
                required for Grafana configuration
        """
        super().__init__(charm, name)
        self.charm = charm
        self.name = name
        events = self.charm.on[name]

        self._source_type = source_type
        self._source_port = source_port

        self.framework.observe(events.relation_joined, self._set_sources)
        self.framework.observe(refresh_event, self._set_unit_ip)

    def _set_sources(self, event: RelationJoinedEvent):
        """Inform the provider about the source configuration."""
        self._set_unit_ip(event)

        if not self.charm.unit.is_leader():
            return

        logger.debug("Setting Grafana data sources: %s", self._scrape_data)
        event.relation.data[self.charm.app]["grafana_source_data"] = json.dumps(self._scrape_data)

    @property
    def _scrape_data(self) -> Dict:
        """Generate source metadata.

        Returns:
            Source configuration data for Grafana.
        """
        data = {
            "model": str(self.charm.model.name),
            "model_uuid": str(self.charm.model.uuid),
            "application": str(self.charm.model.app.name),
            "type": self._source_type,
        }
        return data

    def _set_unit_ip(self, event: CharmEvents):
        """Set unit host address.

        Each time a consumer charm container is restarted it updates its own host address in the
        unit relation data for the Prometheus provider.
        """
        for relation in self.charm.model.relations[self.name]:
            relation.data[self.charm.unit]["grafana_source_host"] = "{}:{}".format(
                str(self.charm.model.get_binding(relation).network.bind_address),
                self._source_port,
            )


class GrafanaSourceProvider(Object):
    """A provider object for working with Grafana datasources."""

    on = GrafanaSourceEvents()
    _stored = StoredState()

    def __init__(self, charm: CharmBase, name: str) -> None:
        """A Grafana based Monitoring service consumer.

        Args:
            charm: a :class:`CharmBase` instance that manages this
                instance of the Grafana source service.
            name: string name of the relation that is provides the
                Grafana source service.
        """
        super().__init__(charm, name)
        self.name = name
        self.charm = charm
        events = self.charm.on[name]

        self._stored.set_default(
            sources=dict(),
            sources_to_delete=set(),
        )

        self.framework.observe(events.relation_changed, self._on_grafana_source_relation_changed)
        self.framework.observe(events.relation_departed, self._on_grafana_source_relation_departed)

    def _on_grafana_source_relation_changed(self, event: CharmEvents) -> None:
        """Handle relation changes in related consumers.

        If there are changes in relations between Grafana source providers
        and consumers, this event handler (if the unit is the leader) will
        get data for an incoming grafana-source relation through a
        :class:`GrafanaSourcesChanged` event, and make the relation data
        is available in the app's datastore object. This data is set using
        Juju application topology.

        The Grafana charm can then respond to the event to update its
        configuration.
        """
        if not self.charm.unit.is_leader():
            return

        sources = {}

        for rel in self.charm.model.relations[self.name]:
            source = self._get_source_config(rel)
            if source:
                sources[rel.id] = source

        self._stored.sources = sources

        self.on.sources_changed.emit()

    def _get_source_config(self, rel: Relation):
        """Generate configuration from data stored in relation data by consumers."""
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
                "source-name": unique_source_name,
                "source-type": source_data["type"],
                "url": "http://{}".format(host_addr),
            }

            if host_data["source-name"] in self._stored.sources_to_delete:
                self._stored.sources_to_delete.remove(host_data["source-name"])

            data.append(host_data)
        return data

    def _relation_hosts(self, rel: Relation) -> Dict:
        """Fetch host names and address of all consumer units for a single relation.

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
        """Update job config when consumers depart.

        When a Grafana source consumer departs, the configuration
        for that consumer is removed from the list of sources jobs,
        added to a list of sources to remove, and other consumers
        are informed through a :class:`GrafanaSourcesChanged` event.
        """
        if not self.charm.unit.is_leader():
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
                self._remove_source(dead_unit["source-name"])

                # Re-update the list of stored sources
                self._stored.sources[rel_id] = [
                    dict(s) for s in removed_source if s["unit"] != event.unit.name
                ]
            else:
                for host in removed_source:
                    self._remove_source(host["source-name"])

            self.on.sources_to_delete_changed.emit()

    def _remove_source(self, source_name: str) -> None:
        """Remove a datasource by name."""
        self._stored.sources_to_delete.add(source_name)

    @property
    def sources(self) -> List[dict]:
        """Returns an array of sources the source_provider knows about."""
        sources = []
        for source in self._stored.sources.values():
            sources.extend([host for host in source])

        return sources

    def update_port(self, relation_name: str, port: int) -> None:
        """Updates the port grafana-k8s is listening on."""
        if self.charm.unit.is_leader():
            for relation in self.charm.model.relations[relation_name]:
                logger.debug("Setting grafana-k8s address data for relation", relation)
                if str(port) != relation.data[self.charm.app].get("port", None):
                    relation.data[self.charm.app]["port"] = str(port)

    @property
    def sources_to_delete(self) -> List[str]:
        """Returns an array of source names which have been removed."""
        sources_to_delete = []
        for source in self._stored.sources_to_delete:
            sources_to_delete.append(source)

        return sources_to_delete
