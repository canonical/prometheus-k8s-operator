# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

"""# Ingress Interface Library.
"""

import logging
from functools import cached_property
from pathlib import Path

import yaml

from ops.charm import CharmBase
from ops.framework import EventBase, EventSource, Object, ObjectEvents
from ops.model import BlockedStatus, WaitingStatus
from serialized_data_interface import (
    get_schema,
    SerializedDataInterface,
    NoCompatibleVersions,
    NoVersionsListed,
)

logger = logging.getLogger(__name__)

# The unique Charmhub library identifier, never change it
LIBID = "b521889515b34432b952f75c21e96dfc"

# Increment this major API version when introducing breaking changes
LIBAPI = 0

# Increment this PATCH version before using `charmcraft publish-lib` or reset
# to 0 if you are raising the major API version
LIBPATCH = 1


SCHEMA_URL_BASE = "https://raw.githubusercontent.com/canonical/operator-schemas"
# SCHEMA_URL = f"{SCHEMA_URL_BASE}/master/ingress.yaml"
SCHEMA_URL = f"{SCHEMA_URL_BASE}/1ed74c640bc289b71f261cda67177ee5209a1562/ingress.yaml"
SCHEMA_VERSIONS = {"v3"}

DEFAULT_RELATION_NAME = "ingress"


class IngressProviderAvailableEvent(EventBase):
    """Event triggered when the ingress provider is ready for requests."""


class IngressReadyEvent(EventBase):
    """Event triggered when the ingress provider has returned the requested URL(s)."""


class IngressFailedEvent(EventBase):
    """Event triggered when something went wrong with the ingress relation."""


class IngressRemovedEvent(EventBase):
    """Event triggered when the ingress relation is removed."""


class IngressRequirerEvents(ObjectEvents):
    available = EventSource(IngressProviderAvailableEvent)
    ready = EventSource(IngressReadyEvent)
    failed = EventSource(IngressFailedEvent)
    removed = EventSource(IngressRemovedEvent)


class IngressRequirer(Object):
    on = IngressRequirerEvents()

    def __init__(
        self,
        charm: CharmBase,
        relation_name: str = DEFAULT_RELATION_NAME,
        *,
        port: int = None,
        service: str = None,
        prefix: str = None,
        rewrite: str = None,
        namespace: str = None,
        per_unit_routes: bool = False,
    ):
        """Constructor for IngressRequirer.

        The request args can be used to specify the ingress properties when the
        instance is created. If any are set, at least `port` is required, and
        they will be sent to the ingress provider as soon as it is available.
        All request args must be given as keyword args.

        Args:
            charm: the charm that is instantiating the library.
            relation_name: the name of the relation endpoint to bind to
                (defaults to "ingress"; relation must be of interface type
                "ingress" and have "limit: 1")
        Request Args:
            service: the name of the target K8s service to route to; defaults to the
                charm's automatically created service (i.e., the application name)
            port: the port of the service (required)
            prefix: the path used to match this service for requests to the gateway;
                must not conflict with other services; defaults to f"/{service}/"
            rewrite: the path on the target service to map the request to; defaults
                to "/"
            namespace: the namespace the service is in; default to the current model
            per_unit_routes: whether or not to create URLs which map to specific units;
                the URLs will have their own prefix of f"{prefix}-unit-{unit_num}" (with
                tailing slashes handled appropriately)
        """
        super().__init__(charm, f"ingress-requirer-{relation_name}")
        self.charm = charm
        self.relation_name = relation_name

        self._validate_relation_meta()

        self.status = self._get_status()

        self._request_args = {
            "port": port,
            "service": service,
            "prefix": prefix,
            "rewrite": rewrite,
            "namespace": namespace,
            "per_unit_routes": per_unit_routes,
        }
        if any(self._request_args.values()) and not self._request_args["port"]:
            raise TypeError("Missing required argument: 'port'")

        self.framework.observe(charm.on[relation_name].relation_created, self._check_provider)
        self.framework.observe(charm.on[relation_name].relation_changed, self._check_provider)
        self.framework.observe(charm.on[relation_name].relation_broken, self._lost_provider)
        self.framework.observe(charm.on.leader_elected, self._check_provider)

    def _get_status(self):
        if not self.charm.model.relations[self.relation_name]:
            # the key will always exist but may be an empty list
            return BlockedStatus(f"Missing relation: {self.relation_name}")
        try:
            self._get_interface()
        except NoCompatibleVersions:
            return BlockedStatus(f"Relation version not compatible: {self.relation_name}")
        except NoVersionsListed:
            return WaitingStatus(f"Waiting on relation: {self.relation_name}")
        else:
            return None

    def _get_interface(self):
        """Get the SDI instance for the relation.

        This provides defaults for the schema URL and supported versions so that
        every client charm doesn't need to specify it, since they're already using
        the versioned library which is inherently tied to a schema & version. It
        still defers to what's in the metadata.yaml, however, so that local_sdi.py
        can be used to inline the schema into the charm to avoid runtime network
        access, if desired.
        """
        # Can't use self.charm.meta, unfortunately, because it doesn't preserve
        # the schema or versions fields.
        meta = yaml.safe_load(Path("metadata.yaml").read_text())
        endpoint_spec = meta["requires"][self.relation_name]
        schema = get_schema(endpoint_spec.get("schema", SCHEMA_URL))
        versions = endpoint_spec.get("versions", SCHEMA_VERSIONS)
        return SerializedDataInterface(
            self.charm,
            self.relation_name,
            schema,
            versions,
            "requires",
        )

    @property
    def is_available(self):
        return self.charm.unit.is_leader() and self.status is None

    @property
    def is_ready(self):
        return self.status is None and self.url

    def _check_provider(self, event):
        if self.is_ready:
            self.on.ready.emit()
        elif self.is_available:
            if any(self._request_args.values()):
                self.request(**self._request_args)
            self.on.available.emit()
        elif isinstance(self.status, BlockedStatus):
            self.on.failed.emit()

    def _lost_provider(self, event):
        # The relation technically still exists during the -broken hook, but we want
        # the status to reflect that it has gone away.
        self.status = BlockedStatus(f"Missing relation: {self.relation_name}")
        self.on.removed.emit()

    def request(
        self,
        *,
        port: int,
        service: str = None,
        prefix: str = None,
        rewrite: str = None,
        namespace: str = None,
        per_unit_routes: bool = False,
    ):
        """Request ingress to a service.

        Note: only the leader unit can send the request.

        Args:
            service: the name of the target K8s service to route to; defaults to the
                charm's automatically created service (i.e., the application name)
            port: the port of the service (required)
            prefix: the path used to match this service for requests to the gateway;
                must not conflict with other services; defaults to f"/{service}/"
            rewrite: the path on the target service to map the request to; defaults
                to "/"
            namespace: the namespace the service is in; default to the current model
            per_unit_routes: whether or not to create URLs which map to specific units;
                the URLs will have their own prefix of f"{prefix}-unit-{unit_num}" (with
                tailing slashes handled appropriately)
        """
        if not self.charm.unit.is_leader():
            raise RequestFailed(
                WaitingStatus(f"Only leader can request ingress: {self.relation_name}")
            )
        if self.status is not None:
            raise RequestFailed(self.status)
        ingress = self._get_interface()
        ingress.send_data(
            {
                "namespace": namespace or self.model.name,
                "prefix": prefix or f"/{self.charm.app.name}/",
                "rewrite": rewrite or "/",
                "service": service or self.charm.app.name,
                "port": port,
                "per_unit_routes": per_unit_routes,
            },
        )

    @cached_property
    def url(self):
        """The full ingress URL to reach the target service by.

        May return None if the URL isn't available yet.
        """
        try:
            ingress = self._get_interface()
            if not ingress:
                return None
        except (NoCompatibleVersions, NoVersionsListed):
            return None
        all_data = ingress.get_data()
        for (rel, app), data in all_data.items():
            if app is self.charm.app:
                continue
            return data["url"]
        else:
            return None

    @cached_property
    def unit_urls(self):
        """The full ingress URLs which map to each indvidual unit.

        May return None if the URLs aren't available yet, or if per-unit routing
        was not requested. Otherwise, returns a map of unit name to URL.
        """
        try:
            ingress = self._get_interface()
            if not ingress:
                return None
        except (NoCompatibleVersions, NoVersionsListed):
            return None
        all_data = ingress.get_data()
        for (rel, app), data in all_data.items():
            if app is self.charm.app:
                continue
            cmr_unit_urls = data.get("unit_urls")
            if cmr_unit_urls is None:
                return None
            # Workaround the fact that the other side of a CMR relation can't know
            # our proper unit name, by using the fact that the unit numbers will be
            # consistent, at least.
            unit_urls = {}
            for unit_name, unit_url in cmr_unit_urls.items():
                unit_name = f"{self.charm.app.name}/{unit_name.split('/')[-1]}"
                unit_urls[unit_name] = unit_url
            return unit_urls
        else:
            return None

    @cached_property
    def unit_url(self):
        """The full ingress URL which map to the current unit.

        May return None if the URLs aren't available yet, or if per-unit routing
        was not requested. Otherwise, returns a URL string.
        """
        return (self.unit_urls or {}).get(self.charm.unit.name)

    def _validate_relation_meta(self):
        """Validate that the relation is setup properly in the metadata."""
        # This should really be done as a build-time hook, if that were possible.
        assert (
            self.relation_name in self.charm.meta.requires
        ), "IngressRequirer must be used on a 'requires' relation"
        rel_meta = self.charm.meta.relations[self.relation_name]
        assert (
            rel_meta.interface_name == "ingress"
        ), "IngressRequirer must be used on an 'ingress' relation'"
        assert rel_meta.limit == 1, "IngressRequirer must be used on a 'limit: 1' relation"


class RequestFailed(Exception):
    def __init__(self, status):
        super().__init__(status.message)
        self.status = status
