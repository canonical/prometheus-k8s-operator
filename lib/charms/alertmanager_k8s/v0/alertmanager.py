#!/usr/bin/env python3
# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

""" # AlertmanagerConsumer library

This library is design to be used by a charm consuming or providing the alertmanager-k8s relation.
"""

import ops
from ops.framework import StoredState, EventSource, EventBase
from ops.relation import ConsumerBase, ProviderBase
from ops.charm import CharmBase

from typing import List
import logging

LIBID = "abcdef1234"  # Unique ID that refers to the library forever
LIBAPI = 0  # Must match the major version in the import path.
LIBPATCH = 1  # The current patch version. Must be updated when changing.

logger = logging.getLogger(__name__)


class ClusterChanged(EventBase):
    """Event raised when an alertmanager cluster is changed.

    If an alertmanager unit is added to or removed from a relation,
    then a :class:`ClusterChanged` event is raised.
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

    This consumer auto-registers relation events on behalf of the user and communicates information
    directly via `_stored`
    Every change in the alertmanager cluster emits a :class:`ClusterChanged` event that the
    consumer charm can register and handle, for example:

        self.framework.observe(self.alertmanager_lib.cluster_changed,
                               self._on_alertmanager_cluster_changed)

    The updated alertmanager cluster can then be obtained via the

    This consumer library expect the consumer charm to register the `get_cluster_info` method.

    Arguments:
            charm (CharmBase): consumer charm
            relation_name (str): from consumer's metadata.yaml
            consumes (dict): provider specifications
            multi (bool): multiple relations flag

    Attributes:
            charm (CharmBase): consumer charm
    """

    _stored: StoredState
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

        self._stored.set_default(alertmanagers={})

    def _on_relation_changed(self, event: ops.charm.RelationChangedEvent):
        """This hook stores locally the address of the newly-joined alertmanager.
        This is needed for consumers such as prometheus, which should be aware of all alertmanager
        instances.
        """
        if event.unit:  # event.unit may be `None` in the case of app data change
            # Save locally the public IP address of the alertmanager unit
            if address := event.relation.data[event.unit].get("public_address"):
                # TODO consider storing in unit data instead of StoredState
                self._stored.alertmanagers[event.unit.name] = address

                # inform consumer about the change
                self.cluster_changed.emit()

    def get_cluster_info(self) -> List[str]:
        """Returns a list of ip addresses of all the alertmanager units"""
        return sorted(list(self._stored.alertmanagers.values()))

    def _on_relation_departed(self, event: ops.charm.RelationDepartedEvent):
        """This hook removes the address of the departing alertmanager from its local store.
        This is needed for consumers such as prometheus, which should be aware of all alertmanager
        instances.
        """
        if self._stored.alertmanagers.pop(event.unit.name, None):
            # inform consumer about the change
            self.cluster_changed.emit()

    def _on_relation_broken(self, event: ops.charm.RelationBrokenEvent):
        self._stored.alertmanagers.clear()
        # inform consumer about the change
        self.cluster_changed.emit()


class AlertmanagerProvider(ProviderBase):
    """A "provider" handler to be used by the Alertmanager charm for abstracting away all the
    communication with consumers.
    This provider auto-registers relation events on behalf of the main Alertmanager charm.

    Arguments:
            charm (CharmBase): consumer charm
            service_name (str): a name for the provided service
            consumes (dict): provider specifications
            multi (bool): multiple relations flag

    Attributes:
            charm (CharmBase): the Alertmanager charm
    """

    _provider_relation_name = "alerting"

    def __init__(self, charm, service_name: str, version: str = None):
        super().__init__(charm, self._provider_relation_name, service_name, version)
        self.charm = charm  # TODO remove?
        self._service_name = service_name

        # Set default value for the public port
        # This is needed here to avoid accessing charm constructs directly
        self._api_port = 9093  # default value

        events = self.charm.on[self._provider_relation_name]

        # No need to observe `relation_departed` or `relation_broken`: data bags are auto-updated
        # so both events are address on the consumer side.
        self.framework.observe(events.relation_joined, self._on_relation_joined)

    @property
    def api_port(self):
        """Get the API port number to use for alertmanager (default: 9093)."""
        return self._api_port

    @api_port.setter
    def api_port(self, value: int):
        """Set the API port number to use for alertmanager (must match the provider charm)."""
        self._api_port = value

    def _on_relation_joined(self, event: ops.charm.RelationJoinedEvent):
        """This hook stores the public address of the newly-joined "alerting" relation in the
        corresponding data bag.
        This is needed for consumers such as prometheus, which should be aware of all alertmanager
        instances.
        """
        # "ingress-address" is auto-populated incorrectly so rolling my own, "public_address"
        event.relation.data[self.charm.unit]["public_address"] = "{}:{}".format(
            self.model.get_binding(event.relation).network.bind_address, self.api_port
        )
