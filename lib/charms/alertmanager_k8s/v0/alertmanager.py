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
from ops.framework import EventBase, EventSource, Object, ObjectEvents
from ops.model import Relation

LIBID = "abcdef1234"  # Unique ID that refers to the library forever
LIBAPI = 0  # Must match the major version in the import path.
LIBPATCH = 1  # The current patch version. Must be updated when changing.

logger = logging.getLogger(__name__)


class ClusterChanged(EventBase):
    """Event raised when an alertmanager cluster is changed.

    If an alertmanager unit is added to or removed from a relation,
    then a :class:`ClusterChanged` event should be emitted.
    """


class AlertmanagerConsumerEvents(ObjectEvents):
    """Event descriptor for events raised by `AlertmanagerConsumer`."""

    cluster_changed = EventSource(ClusterChanged)


class RelationManagerBase(Object):
    """Base class that represents relation ends ("provides" and "requires").

    :class:`RelationManagerBase` is used to create a relation manager. This is done by inheriting
    from :class:`RelationManagerBase` and customising the sub class as required.

    Attributes:
        name (str): consumer's relation name
    """

    def __init__(self, charm: CharmBase, relation_name):
        super().__init__(charm, relation_name)
        self.name = relation_name


class AlertmanagerConsumer(RelationManagerBase):
    """A "consumer" handler to be used by charms that relate to Alertmanager (the 'requires' side).

    To have your charm consume alertmanager cluster data, declare the interface's use in your
    charm's metadata.yaml file:

    ```yaml
    requires:
      alertmanager:
        interface: alertmanager_dispatch
    ```

    A typical example of importing this library might be

    ```python
    from charms.alertmanager_k8s.v0.alertmanager import AlertmanagerConsumer
    ```

    In your charm's `__init__` method:

    ```python
    self.alertmanager_consumer = AlertmanagerConsumer(self, relation_name="alertmanager")
    ```

    Every change in the alertmanager cluster emits a :class:`ClusterChanged` event that the
    consumer charm can register and handle, for example:

    ```
    self.framework.observe(self.alertmanager_consumer.on.cluster_changed,
                           self._on_alertmanager_cluster_changed)
    ```

    The updated alertmanager cluster can then be obtained via the `get_cluster_info` method

    This consumer library expect the consumer charm to observe the `cluster_changed` event.

    Arguments:
            charm (CharmBase): consumer charm
            relation_name (str): from consumer's metadata.yaml

    Attributes:
            charm (CharmBase): consumer charm
    """

    on = AlertmanagerConsumerEvents()

    def __init__(self, charm: CharmBase, relation_name: str):
        super().__init__(charm, relation_name)
        self.charm = charm

        self.framework.observe(
            self.charm.on[self.name].relation_changed, self._on_relation_changed
        )
        self.framework.observe(
            self.charm.on[self.name].relation_departed,
            self._on_relation_departed,
        )
        self.framework.observe(self.charm.on[self.name].relation_broken, self._on_relation_broken)

    def _on_relation_changed(self, event: ops.charm.RelationChangedEvent):
        """This hook notifies the charm that there may have been changes to the cluster."""
        if event.unit:  # event.unit may be `None` in the case of app data change
            # inform consumer about the change
            self.on.cluster_changed.emit()

    def get_cluster_info(self) -> List[str]:
        """Returns a list of ip addresses of all the alertmanager units."""
        alertmanagers: List[str] = []
        if not (relation := self.charm.model.get_relation(self.name)):
            return alertmanagers
        for unit in relation.units:
            if address := relation.data[unit].get("public_address"):
                alertmanagers.append(address)
        return sorted(alertmanagers)

    def _on_relation_departed(self, _):
        """This hook notifies the charm that there may have been changes to the cluster."""
        self.on.cluster_changed.emit()

    def _on_relation_broken(self, _):
        """This hook notifies the charm that a relation has been completely removed."""
        # inform consumer about the change
        self.on.cluster_changed.emit()


class AlertmanagerProvider(RelationManagerBase):
    """A "provider" handler to be used by charms that relate to Alertmanager (the 'provides' side).

    To have your charm provide alertmanager cluster data, declare the interface's use in your
    charm's metadata.yaml file:

    ```yaml
    provides:
      alerting:
        interface: alertmanager_dispatch
    ```

    A typical example of importing this library might be

    ```python
    from charms.alertmanager_k8s.v0.alertmanager import AlertmanagerProvider
    ```

    In your charm's `__init__` method:

    ```python
    self.alertmanager_provider = AlertmanagerProvider(self, self._relation_name, self._api_port)
    ```

    Then inform consumers on any update to alertmanager cluster data via

    ```python
    self.alertmanager_provider.update_relation_data()
    ```

    This provider auto-registers relation events on behalf of the main Alertmanager charm.

    Arguments:
            charm (CharmBase): consumer charm
            relation_name (str): relation name (not interface name)
            api_port (int): alertmanager server's api port; this is needed here to avoid accessing
                            charm constructs directly

    Attributes:
            charm (CharmBase): the Alertmanager charm
    """

    def __init__(self, charm, relation_name: str, api_port: int = 9093):
        super().__init__(charm, relation_name)
        self.charm = charm

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
        public_address = (
            f"{self.charm.model.get_binding(relation).network.bind_address}:{self.api_port}"
        )
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
