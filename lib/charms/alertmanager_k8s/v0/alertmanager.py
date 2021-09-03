#!/usr/bin/env python3
# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

"""# alertmanager library.

This library is designed to be used by a charm consuming or providing the `alerting` relation.
"""

import logging
from typing import List

import ops
from ops.charm import CharmBase, RelationEvent, RelationJoinedEvent
from ops.framework import EventBase, EventSource
from ops.model import Relation
from ops.relation import ConsumerBase, ProviderBase

LIBID = "abcdef1234"  # Unique ID that refers to the library forever
LIBAPI = 0  # Must match the major version in the import path.
LIBPATCH = 1  # The current patch version. Must be updated when changing.

logger = logging.getLogger(__name__)


class ClusterChanged(EventBase):
    """Event raised when an alertmanager cluster is changed.

    If an alertmanager unit is added to or removed from a relation,
    then a :class:`ClusterChanged` event should be emitted.
    """

    def __init__(self, handle, data=None):
        super().__init__(handle)
        self.data = data

    def snapshot(self):
        """Save relation data."""
        return {"data": self.data}

    def restore(self, snapshot):
        """Restore relation data."""
        self.data = snapshot["data"]


class AlertmanagerConsumer(ConsumerBase):
    """A "consumer" handler to be used by charms that relate to Alertmanager.

    Every change in the alertmanager cluster emits a :class:`ClusterChanged` event that the
    consumer charm can register and handle, for example:

        self.framework.observe(self.alertmanager_lib.cluster_changed,
                               self._on_alertmanager_cluster_changed)

    The updated alertmanager cluster can then be obtained via the `get_cluster_info` method

    This consumer library expect the consumer charm to observe the `cluster_changed` event.

    Arguments:
            charm (CharmBase): consumer charm
            relation_name (str): from consumer's metadata.yaml
            consumes (dict): provider specifications
            multi (bool): multiple relations flag

    Attributes:
            charm (CharmBase): consumer charm
    """

    cluster_changed = EventSource(ClusterChanged)

    def __init__(self, charm: CharmBase, relation_name: str, consumes: dict, multi: bool = False):
        super().__init__(charm, relation_name, consumes, multi)
        self.charm = charm
        self._consumer_relation_name = relation_name  # from consumer's metadata.yaml

        self.framework.observe(
            self.charm.on[self._consumer_relation_name].relation_changed, self._on_relation_changed
        )
        self.framework.observe(
            self.charm.on[self._consumer_relation_name].relation_departed,
            self._on_relation_departed,
        )
        self.framework.observe(
            self.charm.on[self._consumer_relation_name].relation_broken, self._on_relation_broken
        )

    def _on_relation_changed(self, event: ops.charm.RelationChangedEvent):
        """This hook notifies the charm that there may have been changes to the cluster."""
        if event.unit:  # event.unit may be `None` in the case of app data change
            # inform consumer about the change
            self.cluster_changed.emit()

    def get_cluster_info(self) -> List[str]:
        """Returns a list of ip addresses of all the alertmanager units."""
        alertmanagers: List[str] = []
        if not (relation := self.charm.model.get_relation(self._consumer_relation_name)):
            return alertmanagers
        for unit in relation.units:
            if address := relation.data[unit].get("public_address"):
                alertmanagers.append(address)
        return sorted(alertmanagers)

    def _on_relation_departed(self, _):
        """This hook notifies the charm that there may have been changes to the cluster."""
        self.cluster_changed.emit()

    def _on_relation_broken(self, _):
        """This hook notifies the charm that a relation has been completely removed."""
        # inform consumer about the change
        self.cluster_changed.emit()


class AlertmanagerProvider(ProviderBase):
    """An alertmanager "provider" handler for abstracting away communication with consumers.

    This provider auto-registers relation events on behalf of the main Alertmanager charm.

    Arguments:
            charm (CharmBase): consumer charm
            relation_name (str): relation name (not interface name)
            service_name (str): a name for the provided service
            consumes (dict): provider specifications
            api_port (int): alertmanager server's api port; this is needed here to avoid accessing
                            charm constructs directly

    Attributes:
            charm (CharmBase): the Alertmanager charm
    """

    def __init__(
        self,
        charm,
        relation_name: str,
        service_name: str,
        version: str = None,
        api_port: int = 9093,
    ):
        super().__init__(charm, relation_name, service_name, version)
        self.charm = charm
        self._service_name = service_name

        self._api_port = api_port

        events = self.charm.on[self.name]

        # No need to observe `relation_departed` or `relation_broken`: data bags are auto-updated
        # so both events are address on the consumer side.
        self.framework.observe(events.relation_joined, self._on_relation_joined)

    @property
    def api_port(self):
        """Get the API port number to use for alertmanager."""
        return self._api_port

    def _on_relation_joined(self, event: RelationJoinedEvent):
        """This hook stores the public address of the newly-joined "alerting" relation.

        This is needed for consumers such as prometheus, which should be aware of all alertmanager
        instances.
        """
        self.update_relation_data(event)

    def _generate_relation_data(self, relation: Relation):
        """Helper function to generate relation data in the correct format."""
        public_address = f"{self.model.get_binding(relation).network.bind_address}:{self.api_port}"
        return {"public_address": public_address}

    def update_relation_data(self, event: RelationEvent = None):
        """Helper function for updating relation data bags.

        This function can be used in two different ways:
        - update relation data bag of a given event (e.g. a newly joined relation);
        - update relation data for all relations

        Args:
            event: The event whose data bag needs to be updated. If it is None, update data bags of
            all relations.
        """
        if event is None:
            # update all existing relation data
            # a single consumer charm's unit may be related to multiple providers
            if self.name in self.charm.model.relations:
                for relation in self.charm.model.relations[self.name]:
                    relation.data[self.charm.unit].update(self._generate_relation_data(relation))
        else:
            # update relation data only for the newly joined relation
            event.relation.data[self.charm.unit].update(
                self._generate_relation_data(event.relation)
            )
