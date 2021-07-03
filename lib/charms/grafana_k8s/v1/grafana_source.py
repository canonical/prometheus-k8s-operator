import json
import logging

from ops.charm import (
    CharmBase,
    CharmEvents,
    RelationBrokenEvent,
    RelationChangedEvent,
    RelationJoinedEvent,
)
from ops.framework import EventBase, EventSource, StoredState
from ops.relation import ConsumerBase, ProviderBase
from typing import Dict, List, Optional


LIBID = "987654321"
LIBAPI = 1
LIBPATCH = 0

logger = logging.getLogger(__name__)


class SourceFieldsMissingError(Exception):
    pass


class GrafanaSourcesChanged(EventBase):
    """Event emitted when Grafana sources change"""

    def __init__(self, handle, data=None):
        super().__init__(handle)
        self.data = data

    def snapshot(self) -> Dict:
        """Save grafana source information"""
        return {"data": self.data}

    def restore(self, snapshot) -> None:
        """Restore grafana source information"""
        self.data = snapshot["data"]


class GrafanaSourceEvents(CharmEvents):
    """Events raised by :class:`GrafanaSourceEvents`"""

    # We are emitting multiple events for the same thing due to the way Grafana provisions
    # datasources. There is no "convenient" way to tell Grafana to remove them outside of
    # setting a separate "deleteDatasources" key in the configuration file to tell Grafana
    # to forget about them, and the reasons why sources_to_delete -> deleteDatasources
    # would be emitted is intrinsically linked to the sources themselves
    sources_changed = EventSource(GrafanaSourcesChanged)
    sources_to_delete_changed = EventSource(GrafanaSourcesChanged)


class GrafanaSourceConsumer(ConsumerBase):
    _stored = StoredState()

    def __init__(
        self, charm: CharmBase, name: str, consumes: dict, multi=False
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
            consumes: a :dict: of acceptable monitoring service
                providers. The keys of the dictionary are :string:
                names of grafana source service providers. Typically,
                this is `grafana-source`. The values of the dictionary
                are corresponding minimal acceptable semantic versions
                for the service.
            multi: an optional (default `False`) flag to indicate if
                this object should support interacting with multiple
                service providers.

        """
        super().__init__(charm, name, consumes, multi)

        self.charm = charm

        self._stored.set_default(sources=dict())  # available data sources
        self._stored.set_default(sources_to_delete=set())
        events = self.charm.on[name]
        self.framework.observe(events.relation_joined, self._set_sources)

    def add_source(self, address: str, port: str,
                   source_type: str = "prometheus", source_name: Optional[str] = None,
                   rel_id: Optional[int] = None) -> None:
        """Add an additional source to the Grafana source service.

        Args:
            address: a :str: which gives address of the target
            port: a :str: which gives the port of the target
            source_type: a :str: indicating the source type. Defaults to "prometheus"
            source_name: a :str: specifying the source name. Otherwise this is calculated
            rel_id: an optional integer specifying the relation ID
                for the grafana source service, only required if the
                :class:`GrafanaSourceConsumer` has been instantiated in
                `multi` mode.

        """
        rel = self.framework.model.get_relation(self.name, rel_id)
        rel_id = rel_id if rel_id is not None else rel.id

        unique_source_name = "juju_{}_{}_{}".format(
            self.charm.model.name,
            self.charm.app.name,
            rel_id
        )
        if not source_name or self._source_name_in_use(source_name):
            logger.warning(
                "'source-name' not specified' or provided name is already in use. "
                "Using safe default: {}.".format(unique_source_name)
            )
            source_name = unique_source_name

        data = {
            "address": address,
            "port": port,
            "source-type": source_type,
            "source-name": source_name
        }

        self._update_sources(data, rel_id)

    def remove_source(self, rel_id=None) -> None:
        """Removes a source relation.

        Args:
            rel_id: an optional integer specifying the relation ID
                for the grafana-k8s source service, only required if the
                :class:`GrafanaSourceConsumer` has been instantiated in
                `multi` mode.
        """
        rel = self.framework.model.get_relation(self.name, rel_id)

        if rel_id is None:
            rel_id = rel.id

        source = self._stored.sources.pop(rel_id)

        if source is not None:
            self._stored.sources_to_delete.add(source["source-name"])

        self._update_sources({}, rel_id)

    def list_sources(self) -> List[dict]:
        """Returns an array of currently valid sources"""
        sources = []
        for source in self._stored.sources.values():
            sources.append(source)

        return sources

    def _set_sources(self, event: RelationJoinedEvent):
        """
        On a relation_joined event, check to see whether or not we already have stored data
        and update the relation data bag if we know about anything
        """
        rel_id = event.relation.id
        if not self._stored.sources.get(rel_id, {}):
            return

        logger.debug("Setting Grafana data sources: %s", self._stored.sources[rel_id])
        event.relation.data[self.charm.app]["sources"] = json.dumps(
            self._stored.sources[rel_id]
        )

    def _update_sources(self, data: Dict, rel_id: int) -> None:
        """Updates the event data bucket with new data"""
        self._stored.sources[rel_id] = data
        rel = self.framework.model.get_relation(self.name, rel_id)

        logger.debug("Updating Grafana source data to {}".format(data))
        rel.data[self.charm.app]["sources"] = json.dumps(data)

    def _source_name_in_use(self, source_name) -> bool:
        return any(
            [s["source-name"] == source_name for s in self._stored.sources.values()]
        )


class GrafanaSourceProvider(ProviderBase):
    on = GrafanaSourceEvents()
    _stored = StoredState()

    def __init__(self, charm: CharmBase, name: str, service: str, version=None) -> None:
        """A Grafana based Monitoring service consumer

        Args:
            charm: a :class:`CharmBase` instance that manages this
                instance of the Grafana source service.
            name: string name of the relation that is provides the
                Grafana source service.
            service: string name of service provided. This is used by
                :class:`GrafanaSourceProvider` to validate this service as
                acceptable. Hence the string name must match one of the
                acceptable service names in the :class:`GrafanaSourceProvider`s
                `consumes` argument. Typically this string is just "grafana".
            version: a string providing the semantic version of the Grafana
                source being provided.

        """
        super().__init__(charm, name, service, version)
        self.charm = charm
        events = self.charm.on[name]

        self._stored.set_default(sources=dict())  # available data sources
        self._stored.set_default(sources_to_delete=set())

        self.framework.observe(
            events.relation_changed, self.on_grafana_source_relation_changed
        )
        self.framework.observe(
            events.relation_broken, self.on_grafana_source_relation_broken
        )

    def on_grafana_source_relation_changed(self, event: RelationChangedEvent) -> None:
        """Handle relation changes in related consumers.

        If there are changes in relations between Grafana source providers
        and consumers, this event handler (if the unit is the leader) will
        get data for an incoming grafana-source relation through a
        :class:`GrafanaSourcesChanged` event, and make the relation data
        is available in the app's datastore object. The Grafana charm can
        then respond to the event to update its configuration
        """
        if not self.charm.unit.is_leader():
            return

        rel = event.relation
        data = (
            json.loads(event.relation.data[event.app].get("sources", {}))
            if event.relation.data[event.app].get("sources", {})
            else None
        )
        if not data:
            logger.debug("No grafana source data in relation data bag")
            return

        # This is due to a double fire on relation_joined calling
        # the consumer, which calls relation_changed, and the actual data may be
        # the same, but we'll see the source name in use later, try to set it again,
        # and get double relation names
        if (
            self._stored.sources.get(rel.id, None)
            and len(set(data.items()) ^ set(self._stored.sources[rel.id].items())) == 0
        ):
            logger.debug("Relation data unchanged. Doing nothing")
            return

        # Grafana expects the first datasource to have an "isDefault" field set, otherwise
        # none of the ingestion will actually work

        data["isDefault"] = (
            "false" if dict(self._stored.sources) else "true"
        )

        self._stored.sources[rel.id] = data
        self.on.sources_changed.emit()

    def on_grafana_source_relation_broken(self, event: RelationBrokenEvent) -> None:
        """Update job config when consumers depart.

        When a Grafana source consumer departs, the configuration
        for that consumer is removed from the list of sources jobs,
        added to a list of sources to remove, and other consumers
        are informed through a :class:`GrafanaSourcesChanged` event.
        """
        if not self.charm.unit.is_leader():
            return

        rel_id = event.relation.id
        self._remove_source_from_datastore(rel_id)

    def _remove_source_from_datastore(self, rel_id: int) -> None:
        """Remove the grafana-source from the datastore. and add the
        name to the list of sources to remove when a relation is
        broken.
        """

        logger.debug("Removing all data for relation: {}".format(rel_id))

        try:
            removed_source = self._stored.sources.pop(rel_id, None)
            if removed_source:
                self._stored.sources_to_delete.add(removed_source["source-name"])
                self.on.sources_to_delete_changed.emit()
        except KeyError:
            logger.warning("Could not remove source for relation: {}".format(rel_id))

    @property
    def sources(self) -> List[dict]:
        """Returns an array of sources the source_provider knows about"""
        sources = []
        for source in self._stored.sources.values():
            sources.append(source)

        return sources

    def update_port(self, relation_name: str, port: int) -> None:
        """Updates the port grafana-k8s is listening on"""
        if self.charm.unit.is_leader():
            for relation in self.charm.model.relations[relation_name]:
                logger.debug("Setting grafana-k8s address data for relation", relation)
                if str(port) != relation.data[self.charm.app].get("port", None):
                    relation.data[self.charm.app]["port"] = str(port)

    @property
    def sources_to_delete(self) -> List[str]:
        """Returns an array of source names which have been removed"""
        sources_to_delete = []
        for source in self._stored.sources_to_delete:
            sources_to_delete.append(source)

        return sources_to_delete
