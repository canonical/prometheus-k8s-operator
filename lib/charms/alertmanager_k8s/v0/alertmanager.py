#!/usr/bin/env python3
# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

""" # AlertmanagerConsumer library

This library is design to be used by a charm consuming or providing the alertmanager-k8s relation.
"""

import ops
from ops.framework import StoredState
from ops.relation import ConsumerBase, ProviderBase
from ops.charm import CharmBase

from typing import List
import logging

LIBID = "abcdef1234"  # Unique ID that refers to the library forever
LIBAPI = 0    # Must match the major version in the import path.
LIBPATCH = 1  # The current patch version. Must be updated when changing.

logger = logging.getLogger(__name__)


class AlertmanagerConsumer(ConsumerBase):
    """A "consumer" handler to be used by charms that relate to Alertmanager.
    This consumer auto-registers relation events on behalf of the user and communicates information
    directly via `_stored` TODO: have a documented contract and act on it in the "available" hook.

    Arguments:
            charm (CharmBase): consumer charm
            relation_name (str): from consumer's metadata.yaml
            consumes (dict): provider specifications
            multi (bool): multiple relations flag

    Attributes:
            charm (CharmBase): consumer charm
    """
    _stored: StoredState

    def __init__(self, charm: CharmBase, relation_name: str, consumes: dict, multi: bool = False):
        super().__init__(charm, relation_name, consumes, multi)
        self.charm = charm
        self._consumer_relation_name = relation_name  # from consumer's metadata.yaml
        # self._provider_relation_name = "alerting"  # from alertmanager's metadata.yaml

        self.framework.observe(self.charm.on[self._consumer_relation_name].relation_changed,
                               self._on_relation_changed)
        self.framework.observe(self.charm.on[self._consumer_relation_name].relation_departed,
                               self._on_relation_departed)
        self.framework.observe(self.charm.on[self._consumer_relation_name].relation_broken,
                               self._on_relation_broken)

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
                # manually emitting the "available" event until scale-up/scale-down "ready" flag is fixed
                self.on.available.emit()

    def get_cluster_info(self) -> List[str]:
        """Returns a list of ip addresses of all the alertmanager units
        """
        return sorted(list(self._stored.alertmanagers.values()))

    def _on_relation_departed(self, event: ops.charm.RelationDepartedEvent):
        """This hook removes the address of the departing alertmanager from its local store.
        This is needed for consumers such as prometheus, which should be aware of all alertmanager
        instances.
        """
        if self._stored.alertmanagers.pop(event.unit.name, None):
            # inform consumer about the change
            # manually emitting the "available" event until scale-up/scale-down "ready" flag is fixed
            self.on.available.emit()

    def _on_relation_broken(self, event: ops.charm.RelationBrokenEvent):
        self._stored.alertmanagers.clear()
        # inform consumer about the change
        # manually emitting the "available" event until scale-up/scale-down "ready" flag is fixed
        self.on.available.emit()


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
    _public_api_port: int = 9093  # public port may not be the same as AlertmanagerCharm._api_port

    def __init__(self, charm, service_name: str, version: str = None):
        super().__init__(charm, self._provider_relation_name, service_name, version)
        self.charm = charm
        self._service_name = service_name

        events = self.charm.on[self._provider_relation_name]
        self.framework.observe(events.relation_joined, self._on_relation_joined)

        # No need to observe `relation_departed` or `relation_broken`: data bags are auto-updated
        # so both events are address on the consumer side.
        self.framework.observe(events.relation_joined, self._on_relation_joined)

    def _on_relation_joined(self, event: ops.charm.RelationJoinedEvent):
        """This hook stores the public address of the newly-joined "alerting" relation in the
        corresponding data bag.
        This is needed for consumers such as prometheus, which should be aware of all alertmanager
        instances.
        """
        # "ingress-address" is auto-populated incorrectly so rolling my own, "public_address"
        event.relation.data[self.charm.unit]["public_address"] = "{}:{}".format(
            self.model.get_binding(event.relation).network.bind_address,
            self._public_api_port
        )
