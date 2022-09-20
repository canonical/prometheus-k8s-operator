"""Charm for providing landing pages to bundles."""

import ipaddress
import socket
from ops.framework import BoundEvent, EventBase, EventSource, Object, ObjectEvents
from ops.charm import CharmBase

import logging

LIBID = "7e5cd3b1e1264c2689f09f772c9af026"
LIBAPI = 0
LIBPATCH = 2

DEFAULT_RELATION_NAME = "landing-page"

logger = logging.getLogger(__name__)

class LandingPageApp:
    name: str
    url: str
    icon: str
    description: str

    def __init__(self, name, url, icon, description = ""):
        self.name = name
        self.url = url
        self.icon = icon
        self.description = description

class LandingPageConsumer(Object):

    def __init__(
        self, 
        charm,
        relation_name: str = DEFAULT_RELATION_NAME, 
        app: LandingPageApp = None
    ):
        super().__init__(charm, relation_name)
        self._charm = charm
        self._relation_name = relation_name
        self._app = app

        events = self._charm.on[self._relation_name]
        self.framework.observe(events.relation_joined, self._on_relation_changed)
        self.framework.observe(events.relation_broken, self._on_relation_changed)
        self.framework.observe(events.relation_changed, self._on_relation_changed)
        self.framework.observe(events.relation_departed, self._on_relation_changed)
        self.framework.observe(events.relation_created, self._on_relation_changed)



    def _on_relation_changed(self, event):
        if not self._charm.unit.is_leader():
            return
        
        if not self._app:
            return
        
        for relation in self._charm.model.relations[self._relation_name]:
            relation.data[self._charm.model.app]["name"] = self._app.name
            relation.data[self._charm.model.app]["description"] = self._app.description
            relation.data[self._charm.model.app]["url"] = self.unit_address(relation)
            relation.data[self._charm.model.app]["icon"] = self._app.icon

    def unit_address(self, relation):
        if self._app and self._app.url:
            return self._app.url
        
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

class AppsChangedEvent(EventBase):
    """Event emitted when landing page app entries change."""

    def __init__(self, handle, apps):
        super().__init__(handle)
        self.apps  = apps

    def snapshot(self):
        """Save landing page apps information."""
        return {"apps": self.apps}

    def restore(self, snapshot):
        """Restore landing page apps information."""
        self.apps = snapshot["apps"]


class LandingPageEvents(ObjectEvents):
    """Events raised by `LandingPageConsumer`"""

    apps_changed = EventSource(AppsChangedEvent)

class LandingPageProvider(Object):

    on = LandingPageEvents()

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
        self.on.apps_changed.emit(apps=self.apps)

    def _on_relation_changed(self, event):
        
        self.on.apps_changed.emit(apps=self.apps)

    @property
    def apps(self):
        return [
            {
                "name": relation.data[relation.app].get("name", ""),
                "url": relation.data[relation.app].get("url", ""),
                "icon": relation.data[relation.app].get("icon", ""), 
                "description": relation.data[relation.app].get("description", "")
            }
            for relation in self._charm.model.relations[self._relation_name]
            if relation.app and relation.units
        ]
