import json
import logging

from ops.charm import (
    CharmBase,
    CharmEvents,
    RelationBrokenEvent,
    RelationChangedEvent,
    RelationJoinedEvent,
)
from ops.framework import EventBase, EventSource, ObjectEvents, StoredState
from ops.model import Relation
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


class GrafanaSourceEvents(ObjectEvents):
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
        self,
        charm: CharmBase,
        name: str,
        consumes: dict,
        refresh_event: CharmEvents,
        source_type: Optional[str] = "prometheus",
        source_port: Optional[str] = "9090",
        multi: Optional[bool] = False,
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
            refresh_event: a :class:`CharmEvents` event on which the IP
                address should be refreshed in case of pod or
                machine/VM restart.
            source_type an optional (default `prometheus`) source type
                required for Grafana configuration
            source_port an optional (default `9090`) source port
                required for Grafana configuration
            multi: an optional (default `False`) flag to indicate if
                this object should support interacting with multiple
                service providers.
        """
        super().__init__(charm, name, consumes, multi)

        self.charm = charm
        events = self.charm.on[name]

        self._source_type = source_type
        self._source_port = source_port

        self.framework.observe(events.relation_joined, self._set_sources)
        self.framework.observe(refresh_event, self._set_unit_ip)

    def _set_sources(self, event: RelationJoinedEvent):
        """
        On a relation_joined event, inform the provider about the source
        configuration
        """
        self._set_unit_ip(event)

        if not self.charm.unit.is_leader():
            return

        logger.debug("Setting Grafana data sources: %s", self._scrape_data)
        event.relation.data[self.charm.app]["grafana_source_data"] = json.dumps(
            self._scrape_data
        )

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
        """Set unit host address

        Each time a consumer charm container is restarted it updates its own
        host address in the unit relation data for the Prometheus provider.
        """
        for relation in self.charm.model.relations[self.name]:
            relation.data[self.charm.unit]["grafana_source_host"] = "{}:{}".format(
                str(self.charm.model.get_binding(relation).network.bind_address),
                self._source_port,
            )


class GrafanaSourceProvider(ProviderBase):
    on = GrafanaSourceEvents()
    _stored = StoredState()

    def __init__(
        self, charm: CharmBase, name: str, service: str, version: Optional[str] = None
    ) -> None:
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

        self._stored.set_default(
            sources=dict(),
            sources_to_delete=set(),
        )

        self.framework.observe(
            events.relation_changed, self._on_grafana_source_relation_changed
        )
        self.framework.observe(
            events.relation_broken, self._on_grafana_source_relation_broken
        )

    def _on_grafana_source_relation_changed(self, event: RelationChangedEvent) -> None:
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
        """
        Generate configuration from data stored in relation data by
        consumers which we can pass back to the charm
        """

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
                "source-name": unique_source_name,
                "source-type": source_data["type"],
                "url": "http://{}".format(host_addr),
            }

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

    def _on_grafana_source_relation_broken(self, event: RelationBrokenEvent) -> None:
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

        removed_source = self._stored.sources.pop(rel_id, None)
        if removed_source:
            for host in removed_source:
                self._remove_source(host["source-name"])
            self.on.sources_to_delete_changed.emit()

    def _remove_source(self, source_name: str) -> None:
        """Remove a datasource by name"""
        self._stored.sources_to_delete.add(source_name)

    @property
    def sources(self) -> List[dict]:
        """Returns an array of sources the source_provider knows about"""
        sources = []
        for source in self._stored.sources.values():
            sources.extend([host for host in source])

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
