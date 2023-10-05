# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

"""Charm for providing services catalogues to bundles or sets of charms."""

import ipaddress
import logging
import socket
import warnings
from typing import List, Optional, Union

from ops.charm import CharmBase
from ops.framework import BoundEvent, EventBase, EventSource, Object, ObjectEvents

LIBID = "fa28b361293b46668bcd1f209ada6983"
LIBAPI = 0
LIBPATCH = 6

DEFAULT_RELATION_NAME = "catalogue"

logger = logging.getLogger(__name__)


class CatalogueItem:
    """`CatalogueItem` represents an application entry sent to a catalogue."""

    def __init__(self, name: str, url: str, icon: str, description: str = ""):
        self.name = name
        self.url = url
        self.icon = icon
        self.description = description


class CatalogueConsumer(Object):
    """`CatalogueConsumer` is used to send over a `CatalogueItem`."""

    def __init__(
        self,
        charm,
        relation_name: str = DEFAULT_RELATION_NAME,
        item: Optional[CatalogueItem] = None,
        refresh_event: Optional[Union[BoundEvent, List[BoundEvent]]] = None,
    ):
        super().__init__(charm, relation_name)
        self._charm = charm
        self._relation_name = relation_name
        self._item = item

        events = self._charm.on[self._relation_name]
        self.framework.observe(events.relation_joined, self._on_relation_changed)
        self.framework.observe(events.relation_broken, self._on_relation_changed)
        self.framework.observe(events.relation_changed, self._on_relation_changed)
        self.framework.observe(events.relation_departed, self._on_relation_changed)
        self.framework.observe(events.relation_created, self._on_relation_changed)

        self._register_refresh_event(refresh_event)

        warnings.warn(
            "charms.catalogue_k8s.v0.catalogue is deprecated. "
            "Use charms.catalogue_k8s.v1.catalogue instead. "
            "For more details, see https://github.com/canonical/catalogue-k8s-operator/issues/41.",
            category=DeprecationWarning,
        )

    def _register_refresh_event(
        self, refresh_event: Optional[Union[BoundEvent, List[BoundEvent]]] = None
    ):
        if not refresh_event:
            if len(self._charm.meta.containers) == 1:
                if "kubernetes" in self._charm.meta.series:
                    # This is a podspec charm
                    refresh_event = [self._charm.on.update_status]
                else:
                    # This is a sidecar/pebble charm
                    container = list(self._charm.meta.containers.values())[0]
                    refresh_event = [self._charm.on[container.name.replace("-", "_")].pebble_ready]
            else:
                logger.warning(
                    "%d containers are present in metadata.yaml and "
                    "refresh_event was not specified. Defaulting to update_status. "
                    "External address may not be set in a timely fashion.",
                    len(self._charm.meta.containers),
                )
                refresh_event = [self._charm.on.update_status]

        else:
            if not isinstance(refresh_event, list):
                refresh_event = [refresh_event]

        for ev in refresh_event:
            self.framework.observe(ev, self._on_relation_changed)

    def _on_relation_changed(self, event):
        if not self._charm.unit.is_leader():
            return

        if not self._item:
            return

        for relation in self._charm.model.relations[self._relation_name]:
            relation.data[self._charm.model.app]["name"] = self._item.name
            relation.data[self._charm.model.app]["description"] = self._item.description
            relation.data[self._charm.model.app]["url"] = self.unit_address(relation)
            relation.data[self._charm.model.app]["icon"] = self._item.icon

    def unit_address(self, relation):
        """The unit address of the consumer, on which it is reachable.

        Requires ingress to be connected for it to be routable.
        """
        if self._item and self._item.url:
            return self._item.url

        unit_ip = str(self._charm.model.get_binding(relation).network.bind_address)
        if self._is_valid_unit_address(unit_ip):
            return unit_ip

        return socket.getfqdn()

    def _is_valid_unit_address(self, address: str) -> bool:
        """Validate a unit address.

        At present only IP address validation is supported, but
        this may be extended to DNS addresses also, as needed.

        Args:
            address: a string representing a unit address
        """
        try:
            _ = ipaddress.ip_address(address)
        except ValueError:
            return False

        return True


class CatalogueItemsChangedEvent(EventBase):
    """Event emitted when the catalogue entries change."""

    def __init__(self, handle, items):
        super().__init__(handle)
        self.items = items

    def snapshot(self):
        """Save catalogue entries information."""
        return {"items": self.items}

    def restore(self, snapshot):
        """Restore catalogue entries information."""
        self.items = snapshot["items"]


class CatalogueEvents(ObjectEvents):
    """Events raised by `CatalogueConsumer`."""

    items_changed = EventSource(CatalogueItemsChangedEvent)


class CatalogueProvider(Object):
    """`CatalogueProvider` is the side of the relation that serves the actual service catalogue."""

    on = CatalogueEvents()  # pyright: ignore

    def __init__(self, charm: CharmBase, relation_name: str = DEFAULT_RELATION_NAME):
        super().__init__(charm, relation_name)
        self._charm = charm
        self._relation_name = relation_name
        events = self._charm.on[self._relation_name]
        self.framework.observe(events.relation_changed, self._on_relation_changed)
        self.framework.observe(events.relation_joined, self._on_relation_changed)
        self.framework.observe(events.relation_departed, self._on_relation_changed)
        self.framework.observe(events.relation_broken, self._on_relation_broken)

    def _on_relation_broken(self, event):
        self.on.items_changed.emit(items=self.items)  # pyright: ignore

    def _on_relation_changed(self, event):
        self.on.items_changed.emit(items=self.items)  # pyright: ignore

    @property
    def items(self):
        """A list of apps sent over relation data."""
        return [
            {
                "name": relation.data[relation.app].get("name", ""),
                "url": relation.data[relation.app].get("url", ""),
                "icon": relation.data[relation.app].get("icon", ""),
                "description": relation.data[relation.app].get("description", ""),
            }
            for relation in self._charm.model.relations[self._relation_name]
            if relation.app and relation.units
        ]
