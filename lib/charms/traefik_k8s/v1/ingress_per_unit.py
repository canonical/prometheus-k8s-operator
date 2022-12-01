# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

r"""# Interface Library for ingress_per_unit.

This library wraps relation endpoints using the `ingress_per_unit` interface
and provides a Python API for both requesting and providing per-unit
ingress.

## Getting Started

To get started using the library, you just need to fetch the library using `charmcraft`.

```shell
charmcraft fetch-lib charms.traefik_k8s.v1.ingress_per_unit
```

Add the `jsonschema` dependency to the `requirements.txt` of your charm.

```yaml
requires:
    ingress:
        interface: ingress_per_unit
        limit: 1
```

Then, to initialise the library:

```python
from charms.traefik_k8s.v1.ingress_per_unit import (IngressPerUnitRequirer,
  IngressPerUnitReadyForUnitEvent, IngressPerUnitRevokedForUnitEvent)

class SomeCharm(CharmBase):
  def __init__(self, *args):
    # ...
    self.ingress_per_unit = IngressPerUnitRequirer(self, port=80)
    # The following event is triggered when the ingress URL to be used
    # by this unit of `SomeCharm` is ready (or changes).
    self.framework.observe(
        self.ingress_per_unit.on.ready_for_unit, self._on_ingress_ready
    )
    self.framework.observe(
        self.ingress_per_unit.on.revoked_for_unit, self._on_ingress_revoked
    )

    def _on_ingress_ready(self, event: IngressPerUnitReadyForUnitEvent):
        # event.url is the same as self.ingress_per_unit.url
        logger.info("This unit's ingress URL: %s", event.url)

    def _on_ingress_revoked(self, event: IngressPerUnitRevokedForUnitEvent):
        logger.info("This unit no longer has ingress")
```

If you wish to be notified also (or instead) when another unit's ingress changes
(e.g. if you're the leader and you're doing things with your peers' ingress),
you can pass `listen_to = "all-units" | "both"` to `IngressPerUnitRequirer`
and observe `self.ingress_per_unit.on.ready` and `self.ingress_per_unit.on.revoked`.
"""

import logging
import socket
import typing
from typing import Any, Dict, Optional, Tuple, Union

import yaml
from ops.charm import CharmBase, RelationBrokenEvent, RelationEvent
from ops.framework import (
    EventSource,
    Object,
    ObjectEvents,
    StoredDict,
    StoredList,
    StoredState,
)
from ops.model import Application, ModelError, Relation, Unit

# The unique Charmhub library identifier, never change it
LIBID = "7ef06111da2945ed84f4f5d4eb5b353a"

# Increment this major API version when introducing breaking changes
LIBAPI = 1

# Increment this PATCH version before using `charmcraft publish-lib` or reset
# to 0 if you are raising the major API version
LIBPATCH = 6

log = logging.getLogger(__name__)

try:
    import jsonschema

    DO_VALIDATION = True
except ModuleNotFoundError:
    log.warning(
        "The `ingress_per_unit` library needs the `jsonschema` package to be able "
        "to do runtime data validation; without it, it will still work but validation "
        "will be disabled. \n"
        "It is recommended to add `jsonschema` to the 'requirements.txt' of your charm, "
        "which will enable this feature."
    )
    DO_VALIDATION = False

# LIBRARY GLOBS
RELATION_INTERFACE = "ingress_per_unit"
DEFAULT_RELATION_NAME = RELATION_INTERFACE.replace("_", "-")

INGRESS_REQUIRES_UNIT_SCHEMA = {
    "type": "object",
    "properties": {
        "model": {"type": "string"},
        "name": {"type": "string"},
        "host": {"type": "string"},
        "port": {"type": "string"},
        "mode": {"type": "string"},
        "strip-prefix": {"type": "string"},
    },
    "required": ["model", "name", "host", "port"],
}
INGRESS_PROVIDES_APP_SCHEMA = {
    "type": "object",
    "properties": {
        "ingress": {
            "type": "object",
            "patternProperties": {
                "": {
                    "type": "object",
                    "properties": {
                        "url": {"type": "string"},
                    },
                    "required": ["url"],
                }
            },
        }
    },
    "required": ["ingress"],
}

# TYPES
try:
    from typing import Literal, TypedDict  # type: ignore
except ImportError:
    from typing_extensions import Literal, TypedDict  # py35 compat


# Model of the data a unit implementing the requirer will need to provide.
RequirerData = TypedDict(
    "RequirerData",
    {
        "model": str,
        "name": str,
        "host": str,
        "port": int,
        "mode": Optional[Literal["tcp", "http"]],
        "strip-prefix": Optional[bool],
    },
    total=False,
)


RequirerUnitData = Dict[Unit, "RequirerData"]
KeyValueMapping = Dict[str, str]
ProviderApplicationData = Dict[str, KeyValueMapping]


def _type_convert_stored(obj):
    """Convert Stored* to their appropriate types, recursively."""
    if isinstance(obj, StoredList):
        return list(map(_type_convert_stored, obj))
    elif isinstance(obj, StoredDict):
        rdict = {}  # type: Dict[Any, Any]
        for k in obj.keys():
            rdict[k] = _type_convert_stored(obj[k])
        return rdict
    else:
        return obj


def _validate_data(data, schema):
    """Checks whether `data` matches `schema`.

    Will raise DataValidationError if the data is not valid, else return None.
    """
    if not DO_VALIDATION:
        return
    try:
        jsonschema.validate(instance=data, schema=schema)
    except jsonschema.ValidationError as e:
        raise DataValidationError(data, schema) from e


# EXCEPTIONS
class DataValidationError(RuntimeError):
    """Raised when data validation fails on IPU relation data."""


class RelationException(RuntimeError):
    """Base class for relation exceptions from this library.

    Attributes:
        relation: The Relation which caused the exception.
        entity: The Application or Unit which caused the exception.
    """

    def __init__(self, relation: Relation, entity: Union[Application, Unit]):
        super().__init__(relation)
        self.args = (
            "There is an error with the relation {}:{} with {}".format(
                relation.name, relation.id, entity.name
            ),
        )
        self.relation = relation
        self.entity = entity


class RelationDataMismatchError(RelationException):
    """Data from different units do not match where they should."""


class RelationPermissionError(RelationException):
    """Ingress is requested to do something for which it lacks permissions."""

    def __init__(self, relation: Relation, entity: Union[Application, Unit], message: str):
        super(RelationPermissionError, self).__init__(relation, entity)
        self.args = (
            "Unable to write data to relation '{}:{}' with {}: {}".format(
                relation.name, relation.id, entity.name, message
            ),
        )


class _IngressPerUnitBase(Object):
    """Base class for IngressPerUnit interface classes."""

    def __init__(self, charm: CharmBase, relation_name: str = DEFAULT_RELATION_NAME):
        """Constructor for _IngressPerUnitBase.

        Args:
            charm: The charm that is instantiating the instance.
            relation_name: The name of the relation name to bind to
                (defaults to "ingress-per-unit").
        """
        super().__init__(charm, relation_name)
        self.charm = charm  # type: CharmBase

        self.relation_name = relation_name
        self.app = self.charm.app
        self.unit = self.charm.unit

        observe = self.framework.observe
        rel_events = charm.on[relation_name]
        observe(rel_events.relation_created, self._handle_relation)
        observe(rel_events.relation_joined, self._handle_relation)
        observe(rel_events.relation_changed, self._handle_relation)
        observe(rel_events.relation_broken, self._handle_relation_broken)
        observe(charm.on.leader_elected, self._handle_upgrade_or_leader)  # type: ignore
        observe(charm.on.upgrade_charm, self._handle_upgrade_or_leader)  # type: ignore

    @property
    def relations(self):
        """The list of Relation instances associated with this relation_name."""
        return list(self.charm.model.relations[self.relation_name])

    def _handle_relation(self, event):
        """Subclasses should implement this method to handle a relation update."""
        pass

    def _handle_relation_broken(self, event):
        """Subclasses should implement this method to handle a relation breaking."""
        pass

    def _handle_upgrade_or_leader(self, event):
        """Subclasses should implement this method to handle upgrades or leadership change."""
        pass

    def is_ready(self, relation: Optional[Relation] = None) -> bool:
        """Checks whether the given relation is ready.

        A relation is ready if the remote side has sent valid data.
        """
        if relation is None:
            return any(map(self.is_ready, self.relations))
        if relation.app is None:
            # No idea why, but this happened once.
            return False
        if not relation.app.name:  # type: ignore
            # Juju doesn't provide JUJU_REMOTE_APP during relation-broken
            # hooks. See https://github.com/canonical/operator/issues/693
            return False
        return True


class IngressDataReadyEvent(RelationEvent):
    """Event triggered when the requirer has provided valid ingress data.

    Also emitted when the data has changed.
    If you receive this, you should handle it as if the data being
    provided was new.
    """


class IngressDataRemovedEvent(RelationEvent):
    """Event triggered when a requirer has wiped its ingress data.

    Also emitted when the requirer data has become incomplete or invalid.
    If you receive this, you should handle it as if the remote unit no longer
    wishes to receive ingress.
    """


class IngressPerUnitProviderEvents(ObjectEvents):
    """Container for events for IngressPerUnit."""

    data_provided = EventSource(IngressDataReadyEvent)
    data_removed = EventSource(IngressDataRemovedEvent)


class IngressPerUnitProvider(_IngressPerUnitBase):
    """Implementation of the provider of ingress_per_unit."""

    on = IngressPerUnitProviderEvents()

    def _handle_relation(self, event):
        relation = event.relation
        try:
            self.validate(relation)
        except RelationDataMismatchError as e:
            self.on.data_removed.emit(relation)  # type: ignore
            log.warning(
                "relation data mismatch: {} " "data_removed ingress for {}.".format(e, relation)
            )
            return

        if self.is_ready(relation):
            self.on.data_provided.emit(relation)  # type: ignore
        else:
            self.on.data_removed.emit(relation)  # type: ignore

    def _handle_relation_broken(self, event):
        # relation broken -> we revoke in any case
        self.on.data_removed.emit(event.relation)  # type: ignore

    def is_ready(self, relation: Optional[Relation] = None) -> bool:
        """Checks whether the given relation is ready.

        Or any relation if not specified.
        A given relation is ready if SOME remote side has sent valid data.
        """
        if relation is None:
            return any(map(self.is_ready, self.relations))

        if not super().is_ready(relation):
            return False

        try:
            requirer_units_data = self._requirer_units_data(relation)
        except Exception:
            log.exception("Cannot fetch ingress data for the '{}' relation".format(relation))
            return False

        return any(requirer_units_data.values())

    def validate(self, relation: Relation):
        """Checks whether the given relation is failed.

        Or any relation if not specified.
        """
        # verify that all remote units (requirer's side) publish the same model.
        # We do not validate the port because, in case of changes to the configuration
        # of the charm or a new version of the charmed workload, e.g. over an upgrade,
        # the remote port may be different among units.
        expected_model = None  # It may be none for units that have not yet written data

        remote_units_data = self._requirer_units_data(relation)
        for remote_unit, remote_unit_data in remote_units_data.items():
            if "model" in remote_unit_data:
                remote_model = remote_unit_data["model"]
                if not expected_model:
                    expected_model = remote_model
                elif expected_model != remote_model:
                    raise RelationDataMismatchError(relation, remote_unit)

    def is_unit_ready(self, relation: Relation, unit: Unit) -> bool:
        """Report whether the given unit has shared data in its unit data bag."""
        # sanity check: this should not occur in production, but it may happen
        # during testing: cfr https://github.com/canonical/traefik-k8s-operator/issues/39
        assert unit in relation.units, (
            "attempting to get ready state " "for unit that does not belong to relation"
        )
        try:
            self._get_requirer_unit_data(relation, unit)
        except (KeyError, DataValidationError):
            return False
        return True

    def get_data(self, relation: Relation, unit: Unit) -> "RequirerData":
        """Fetch the data shared by the specified unit on the relation (Requirer side)."""
        return self._get_requirer_unit_data(relation, unit)

    def publish_url(self, relation: Relation, unit_name: str, url: str):
        """Place the ingress url in the application data bag for the units on the requires side.

        Assumes that this unit is leader.
        """
        assert self.unit.is_leader(), "only leaders can do this"

        raw_data = relation.data[self.app].get("ingress", None)
        data = yaml.safe_load(raw_data) if raw_data else {}
        ingress = {"ingress": data}

        # we ensure that the application databag has the shape we think it
        # should have; to catch any inconsistencies early on.
        try:
            _validate_data(ingress, INGRESS_PROVIDES_APP_SCHEMA)
        except DataValidationError as e:
            log.error(
                "unable to publish url to {}: corrupted application databag ({})".format(
                    unit_name, e
                )
            )
            return

        # we update the data with a new url
        data[unit_name] = {"url": url}

        # we validate the data **again**, to ensure that we respected the schema
        # and did not accidentally corrupt our own databag.
        _validate_data(ingress, INGRESS_PROVIDES_APP_SCHEMA)
        relation.data[self.app]["ingress"] = yaml.safe_dump(data)

    def wipe_ingress_data(self, relation):
        """Remove all published ingress data.

        Assumes that this unit is leader.
        """
        assert self.unit.is_leader(), "only leaders can do this"
        try:
            relation.data
        except ModelError as e:
            log.warning(
                "error {} accessing relation data for {!r}. "
                "Probably a ghost of a dead relation is still "
                "lingering around.".format(e, relation.name)
            )
            return
        del relation.data[self.app]["ingress"]

    def _requirer_units_data(self, relation: Relation) -> RequirerUnitData:
        """Fetch and validate the requirer's units databag."""
        if not relation.app or not relation.app.name:
            # Handle edge case where remote app name can be missing, e.g.,
            # relation_broken events.
            # FIXME https://github.com/canonical/traefik-k8s-operator/issues/34
            return {}

        remote_units = [unit for unit in relation.units if unit.app is not self.app]

        requirer_units_data = {}
        for remote_unit in remote_units:
            try:
                remote_data = self._get_requirer_unit_data(relation, remote_unit)
            except KeyError:
                # this remote unit didn't share data yet
                log.warning("Remote unit {} not ready.".format(remote_unit.name))
                continue
            except DataValidationError as e:
                # this remote unit sent invalid data.
                log.error("Remote unit {} sent invalid data ({}).".format(remote_unit.name, e))
                continue

            remote_data["port"] = int(remote_data["port"])
            requirer_units_data[remote_unit] = remote_data
        return requirer_units_data

    def _get_requirer_unit_data(self, relation: Relation, remote_unit: Unit) -> RequirerData:  # type: ignore
        """Fetch and validate the requirer unit data for this unit.

        For convenience, we convert 'port' to integer.
        """
        if not relation.app or not relation.app.name:
            # Handle edge case where remote app name can be missing, e.g.,
            # relation_broken events.
            # FIXME https://github.com/canonical/traefik-k8s-operator/issues/34
            return {}

        databag = relation.data[remote_unit]
        remote_data = {}  # type: Dict[str, Union[int, str]]
        for k in ("port", "host", "model", "name", "mode", "strip-prefix"):
            v = databag.get(k)
            if v is not None:
                remote_data[k] = v
        _validate_data(remote_data, INGRESS_REQUIRES_UNIT_SCHEMA)
        remote_data["port"] = int(remote_data["port"])
        remote_data["strip-prefix"] = bool(remote_data.get("strip-prefix", False))
        return remote_data

    def _provider_app_data(self, relation: Relation) -> ProviderApplicationData:
        """Fetch and validate the provider's app databag."""
        if not relation.app or not relation.app.name:
            # Handle edge case where remote app name can be missing, e.g.,
            # relation_broken events.
            # FIXME https://github.com/canonical/traefik-k8s-operator/issues/34
            return {}

        # we start by looking at the provider's app databag
        if self.unit.is_leader():
            # only leaders can read their app's data
            data = relation.data[self.app].get("ingress")
            if not data:
                return {}

            deserialized = yaml.safe_load(data)
            _validate_data({"ingress": deserialized}, INGRESS_PROVIDES_APP_SCHEMA)
            return deserialized

        return {}

    @property
    def proxied_endpoints(self) -> dict:
        """The ingress settings provided to units by this provider.

        For example, when this IngressPerUnitProvider has provided the
        `http://foo.bar/my-model.my-app-1` and
        `http://foo.bar/my-model.my-app-2` URLs to the two units of the
        my-app application, the returned dictionary will be:

        ```
        {
            "my-app/1": {
                "url": "http://foo.bar/my-model.my-app-1"
            },
            "my-app/2": {
                "url": "http://foo.bar/my-model.my-app-2"
            }
        }
        ```
        """
        results = {}

        for ingress_relation in self.relations:
            provider_app_data = self._provider_app_data(ingress_relation)
            results.update(provider_app_data)

        return results


class _IPUEvent(RelationEvent):
    __args__ = ()  # type: Tuple[str, ...]
    __optional_kwargs__ = {}  # type: Dict[str, Any]

    @classmethod
    def __attrs__(cls):
        return cls.__args__ + tuple(cls.__optional_kwargs__.keys())

    def __init__(self, handle, relation, *args, **kwargs):
        super().__init__(handle, relation)

        if not len(self.__args__) == len(args):
            raise TypeError("expected {} args, got {}".format(len(self.__args__), len(args)))

        for attr, obj in zip(self.__args__, args):
            setattr(self, attr, obj)
        for attr, default in self.__optional_kwargs__.items():
            obj = kwargs.get(attr, default)
            setattr(self, attr, obj)

    def snapshot(self) -> dict:
        dct = super().snapshot()
        for attr in self.__attrs__():
            obj = getattr(self, attr)
            try:
                dct[attr] = obj
            except ValueError as e:
                raise ValueError(
                    "cannot automagically serialize {}: "
                    "override this method and do it "
                    "manually.".format(obj)
                ) from e
        return dct

    def restore(self, snapshot: dict) -> None:
        super().restore(snapshot)
        for attr, obj in snapshot.items():
            setattr(self, attr, obj)


class IngressPerUnitReadyEvent(_IPUEvent):
    """Ingress is ready (or has changed) for some unit.

    Attrs:
        `unit_name`: name of the unit for which ingress has been
            provided/has changed.
        `url`: the (new) url for that unit.
    """

    __args__ = ("unit_name", "url")
    if typing.TYPE_CHECKING:
        unit_name = ""
        url = ""


class IngressPerUnitReadyForUnitEvent(_IPUEvent):
    """Ingress is ready (or has changed) for this unit.

    Is only fired on the unit(s) for which ingress has been provided or
    has changed.
    Attrs:
        `url`: the (new) url for this unit.
    """

    __args__ = ("url",)
    if typing.TYPE_CHECKING:
        url = ""


class IngressPerUnitRevokedEvent(_IPUEvent):
    """Ingress is revoked (or has changed) for some unit.

    Attrs:
        `unit_name`: the name of the unit whose ingress has been revoked.
            this could be "THIS" unit, or a peer.
    """

    __args__ = ("unit_name",)

    if typing.TYPE_CHECKING:
        unit_name = ""


class IngressPerUnitRevokedForUnitEvent(RelationEvent):
    """Ingress is revoked (or has changed) for this unit.

    Is only fired on the unit(s) for which ingress has changed.
    """


class IngressPerUnitRequirerEvents(ObjectEvents):
    """Container for IUP events."""

    ready = EventSource(IngressPerUnitReadyEvent)
    revoked = EventSource(IngressPerUnitRevokedEvent)
    ready_for_unit = EventSource(IngressPerUnitReadyForUnitEvent)
    revoked_for_unit = EventSource(IngressPerUnitRevokedForUnitEvent)


class IngressPerUnitRequirer(_IngressPerUnitBase):
    """Implementation of the requirer of ingress_per_unit."""

    on = IngressPerUnitRequirerEvents()  # type: IngressPerUnitRequirerEvents
    # used to prevent spurious urls to be sent out if the event we're currently
    # handling is a relation-broken one.
    _stored = StoredState()

    def __init__(
        self,
        charm: CharmBase,
        relation_name: str = DEFAULT_RELATION_NAME,
        *,
        host: Optional[str] = None,
        port: Optional[int] = None,
        mode: Literal["tcp", "http"] = "http",
        listen_to: Literal["only-this-unit", "all-units", "both"] = "only-this-unit",
        strip_prefix: bool = False,
    ):
        """Constructor for IngressPerUnitRequirer.

        The request args can be used to specify the ingress properties when the
        instance is created. If any are set, at least `port` is required, and
        they will be sent to the ingress provider as soon as it is available.
        All request args must be given as keyword args.

        Args:
            `charm`: the charm that is instantiating the library.
            `relation_name`: the name of the relation name to bind to
                (defaults to "ingress-per-unit"; relation must be of interface
                type "ingress_per_unit" and have "limit: 1")
            `host`: Hostname to be used by the ingress provider to address the
                requirer unit; if unspecified, the FQDN of the unit will be
                used instead
            `port`: port to be used by the ingress provider to address the
                    requirer unit.
            `listen_to`: Choose which events should be fired on this unit:
                "only-this-unit": this unit will only be notified when ingress
                  is ready/revoked for this unit.
                "all-units": this unit will be notified when ingress is
                  ready/revoked for any unit of this application, including
                  itself.
                "all": this unit will receive both event types (which means it
                  will be notified *twice* of changes to this unit's ingress!)
        """  # noqa: D417
        super().__init__(charm, relation_name)
        self._stored.set_default(current_urls=None)  # type: ignore

        # if instantiated with a port, and we are related, then
        # we immediately publish our ingress data  to speed up the process.
        self._host = host
        self._port = port
        self._mode = mode
        self._strip_prefix = strip_prefix

        self.listen_to = listen_to

        self.framework.observe(
            self.charm.on[self.relation_name].relation_changed, self._handle_relation
        )
        self.framework.observe(
            self.charm.on[self.relation_name].relation_broken, self._handle_relation
        )

    def _handle_relation(self, event: RelationEvent):
        # we calculate the diff between the urls we were aware of
        # before and those we know now
        previous_urls = self._stored.current_urls or {}  # type: ignore
        current_urls = (
            {} if isinstance(event, RelationBrokenEvent) else self._urls_from_relation_data
        )
        self._stored.current_urls = current_urls  # type: ignore

        removed = previous_urls.keys() - current_urls.keys()  # type: ignore
        changed = {a for a in current_urls if current_urls[a] != previous_urls.get(a)}  # type: ignore

        this_unit_name = self.unit.name
        if self.listen_to in {"only-this-unit", "both"}:
            if this_unit_name in changed:
                self.on.ready_for_unit.emit(  # type: ignore
                    self.relation, current_urls[this_unit_name]
                )

            if this_unit_name in removed:
                self.on.revoked_for_unit.emit(self.relation)  # type: ignore

        if self.listen_to in {"all-units", "both"}:
            for unit_name in changed:
                self.on.ready.emit(  # type: ignore
                    self.relation, unit_name, current_urls[unit_name]
                )

            for unit_name in removed:
                self.on.revoked.emit(self.relation, unit_name)  # type: ignore

        self._publish_auto_data()

    def _handle_upgrade_or_leader(self, event):
        if self.relations:
            self._publish_auto_data()

    def _publish_auto_data(self):
        if self._port:
            self.provide_ingress_requirements(host=self._host, port=self._port)

    @property
    def relation(self) -> Optional[Relation]:
        """The established Relation instance, or None if still unrelated."""
        return self.relations[0] if self.relations else None

    def is_ready(self) -> bool:
        """Checks whether the given relation is ready.

        Or any relation if not specified.
        A given relation is ready if the remote side has sent valid data.
        """
        if not self.relation:
            return False
        if super().is_ready(self.relation) is False:
            return False
        return bool(self.url)

    def provide_ingress_requirements(self, *, host: Optional[str] = None, port: int):
        """Publishes the data that Traefik needs to provide ingress.

        Args:
            host: Hostname to be used by the ingress provider to address the
             requirer unit; if unspecified, FQDN will be used instead
            port: the port of the service (required)
        """
        assert self.relation, "no relation"

        if not host:
            host = socket.getfqdn()

        data = {
            "model": self.model.name,
            "name": self.unit.name,
            "host": host,
            "port": str(port),
            "mode": self._mode,
        }

        if self._strip_prefix:
            data["strip-prefix"] = "true"

        _validate_data(data, INGRESS_REQUIRES_UNIT_SCHEMA)
        self.relation.data[self.unit].update(data)

    @property
    def _urls_from_relation_data(self) -> Dict[str, str]:
        """The full ingress URLs to reach every unit.

        May return an empty dict if the URLs aren't available yet.
        """
        relation = self.relation
        if not relation:
            return {}

        if not all((relation.app, relation.app.name)):  # type: ignore
            # FIXME Workaround for https://github.com/canonical/operator/issues/693
            # We must be in a relation_broken hook
            return {}
        assert isinstance(relation.app, Application)  # type guard

        try:
            raw = relation.data.get(relation.app, {}).get("ingress")
        except ModelError as e:
            log.debug(
                "Error {} attempting to read remote app data; "
                "probably we are in a relation_departed hook".format(e)
            )
            return {}

        if not raw:
            # remote side didn't send yet
            return {}

        data = yaml.safe_load(raw)
        _validate_data({"ingress": data}, INGRESS_PROVIDES_APP_SCHEMA)

        return {unit_name: unit_data["url"] for unit_name, unit_data in data.items()}

    @property
    def urls(self) -> Dict[str, str]:
        """The full ingress URLs to reach every unit.

        May return an empty dict if the URLs aren't available yet.
        """
        current_urls = self._urls_from_relation_data
        return current_urls

    @property
    def url(self) -> Optional[str]:
        """The full ingress URL to reach the current unit.

        May return None if the URL isn't available yet.
        """
        urls = self.urls
        if not urls:
            return None
        return urls.get(self.charm.unit.name)
