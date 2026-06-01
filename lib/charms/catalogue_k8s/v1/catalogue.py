# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

"""Charm for providing services catalogues to bundles or sets of charms.

This charm library contains two classes (CatalogueProvider and CatalogueConsumer) that handle
both sides of the `catalogue` relation interface.

### CatalogueConsumer

The Consumer allows sending catalogue items to a Catalogue charm.

Adding it to your charm is very simple:

    ```
    from charms.catalogue_k8s.v1.catalogue import (
        CatalogueConsumer,
        CatalogueItem,
    )

    ...
        self.catalogue = CatalogueConsumer(
            charm=self,
            relation_name="catalogue",  # optional
            item=CatalogueItem(
                name="myapp",
                url=myapp_url,
                icon="rainbow",
                description="This is a rainbow app!"
            )
        )
    ```

    The relevant events listeners are already registered by the CatalogueConsumer object.

### CatalogueProvider

The Provider helps you receive catalogue items from other charms to display them however you like.

To implement this in your charm:

    ```
    from charms.catalogue_k8s.v1.catalogue import CatalogueProvider

    ...
        self.catalogue = CatalogueProvider(
            charm=self,
            relation_name="catalogue",  # optional
        )
    ```


    The relevant events listeners are already registered by the CatalogueProvider object.
"""

import ipaddress
import json
import logging
from typing import Dict, Optional

from ops.charm import CharmBase
from ops.framework import EventBase, EventSource, Object, ObjectEvents

LIBID = "fa28b361293b46668bcd1f209ada6983"
LIBAPI = 1
LIBPATCH = 3

DEFAULT_RELATION_NAME = "catalogue"

logger = logging.getLogger(__name__)


class CatalogueItem:
    """`CatalogueItem` represents an application entry sent to a catalogue.

    icon (str): An Iconify Material Design Icon (MDI) string.
        (See: https://icon-sets.iconify.design/mdi for more details).
    api_docs (str): A URL to the docs relevant to this item (upstream or otherwise).
    api_endpoints (dict): A dictionary containing API information, where:
        - The key is a description or name of the endpoint (e.g., "Alerts").
        - The value is the actual address of the endpoint (e.g., "'http://1.2.3.4:1234/api/v1/targets/metadata'").
        - Example for setting the api_endpoints attr:
            api_endpoints={"Alerts": f"{self.external_url}/api/v1/alerts"}
    """

    def __init__(self, name: str, url: str, icon: str, description: str = "", api_docs: str = "", api_endpoints: Optional[Dict[str,str]] = None):
        self.name = name
        self.url = url
        self.icon = icon
        self.description = description
        self.api_docs = api_docs
        self.api_endpoints = api_endpoints


class CatalogueConsumer(Object):
    """`CatalogueConsumer` is used to send over a `CatalogueItem`."""

    def __init__(
        self,
        charm,
        relation_name: str = DEFAULT_RELATION_NAME,
        item: Optional[CatalogueItem] = None,
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

    def _on_relation_changed(self, _):
        self._update_relation_data()

    def _update_relation_data(self):
        if not self._charm.unit.is_leader():
            return

        if not self._item:
            return

        for relation in self._charm.model.relations[self._relation_name]:
            relation.data[self._charm.model.app]["name"] = self._item.name
            relation.data[self._charm.model.app]["description"] = self._item.description
            relation.data[self._charm.model.app]["url"] = self.unit_address(relation)
            relation.data[self._charm.model.app]["icon"] = self._item.icon
            relation.data[self._charm.model.app]["api_docs"] = self._item.api_docs
            relation.data[self._charm.model.app]["api_endpoints"] = json.dumps(self._item.api_endpoints)

    def update_item(self, item: CatalogueItem):
        """Update the catalogue item."""
        self._item = item
        self._update_relation_data()

    def unit_address(self, relation):
        """Return the unit address of the consumer, on which it is reachable.

        Requires ingress to be connected for it to be routable.
        """
        if self._item and self._item.url:
            return self._item.url
        return ""

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
                "api_docs": relation.data[relation.app].get("api_docs", ""),
                "api_endpoints": json.loads(relation.data[relation.app].get("api_endpoints", "{}")),
            }
            for relation in self._charm.model.relations[self._relation_name]
            if relation.app and relation.units
        ]
