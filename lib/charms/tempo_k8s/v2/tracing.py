# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.
"""## Overview.

This document explains how to integrate with the Tempo charm for the purpose of pushing traces to a
tracing endpoint provided by Tempo. It also explains how alternative implementations of the Tempo charm
may maintain the same interface and be backward compatible with all currently integrated charms.

## Requirer Library Usage

Charms seeking to push traces to Tempo, must do so using the `TracingEndpointRequirer`
object from this charm library. For the simplest use cases, using the `TracingEndpointRequirer`
object only requires instantiating it, typically in the constructor of your charm. The
`TracingEndpointRequirer` constructor requires the name of the relation over which a tracing endpoint
 is exposed by the Tempo charm, and a list of protocols it intends to send traces with.
 This relation must use the `tracing` interface.
 The `TracingEndpointRequirer` object may be instantiated as follows

    from charms.tempo_k8s.v2.tracing import TracingEndpointRequirer

    def __init__(self, *args):
        super().__init__(*args)
        # ...
        self.tracing = TracingEndpointRequirer(self,
            protocols=['otlp_grpc', 'otlp_http', 'jaeger_http_thrift']
        )
        # ...

Note that the first argument (`self`) to `TracingEndpointRequirer` is always a reference to the
parent charm.

Alternatively to providing the list of requested protocols at init time, the charm can do it at
any point in time by calling the
`TracingEndpointRequirer.request_protocols(*protocol:str, relation:Optional[Relation])` method.
Using this method also allows you to use per-relation protocols.

Units of provider charms obtain the tempo endpoint to which they will push their traces by calling
`TracingEndpointRequirer.get_endpoint(protocol: str)`, where `protocol` is, for example:
- `otlp_grpc`
- `otlp_http`
- `zipkin`
- `tempo`

If the `protocol` is not in the list of protocols that the charm requested at endpoint set-up time,
the library will raise an error.

## Requirer Library Usage

The `TracingEndpointProvider` object may be used by charms to manage relations with their
trace sources. For this purposes a Tempo-like charm needs to do two things

1. Instantiate the `TracingEndpointProvider` object by providing it a
reference to the parent (Tempo) charm and optionally the name of the relation that the Tempo charm
uses to interact with its trace sources. This relation must conform to the `tracing` interface
and it is strongly recommended that this relation be named `tracing` which is its
default value.

For example a Tempo charm may instantiate the `TracingEndpointProvider` in its constructor as
follows

    from charms.tempo_k8s.v2.tracing import TracingEndpointProvider

    def __init__(self, *args):
        super().__init__(*args)
        # ...
        self.tracing = TracingEndpointProvider(self)
        # ...



"""  # noqa: W505
import json
import logging
from typing import (
    TYPE_CHECKING,
    Any,
    Dict,
    List,
    Literal,
    MutableMapping,
    Optional,
    Sequence,
    Tuple,
    cast,
)

import pydantic
from ops.charm import (
    CharmBase,
    CharmEvents,
    RelationBrokenEvent,
    RelationEvent,
    RelationRole,
)
from ops.framework import EventSource, Object
from ops.model import ModelError, Relation
from pydantic import BaseModel

# The unique Charmhub library identifier, never change it
LIBID = "12977e9aa0b34367903d8afeb8c3d85d"

# Increment this major API version when introducing breaking changes
LIBAPI = 2

# Increment this PATCH version before using `charmcraft publish-lib` or reset
# to 0 if you are raising the major API version
LIBPATCH = 5

PYDEPS = ["pydantic"]

logger = logging.getLogger(__name__)

DEFAULT_RELATION_NAME = "tracing"
RELATION_INTERFACE_NAME = "tracing"

ReceiverProtocol = Literal[
    "zipkin",
    "kafka",
    "opencensus",
    "tempo_http",
    "tempo_grpc",
    "otlp_grpc",
    "otlp_http",
    # "jaeger_grpc",
    "jaeger_thrift_compact",
    "jaeger_thrift_http",
    "jaeger_thrift_binary",
]

RawReceiver = Tuple[ReceiverProtocol, int]
BUILTIN_JUJU_KEYS = {"ingress-address", "private-address", "egress-subnets"}


class TracingError(Exception):
    """Base class for custom errors raised by this library."""


class NotReadyError(TracingError):
    """Raised by the provider wrapper if a requirer hasn't published the required data (yet)."""


class ProtocolNotRequestedError(TracingError):
    """Raised if the user attempts to obtain an endpoint for a protocol it did not request."""


class DataValidationError(TracingError):
    """Raised when data validation fails on IPU relation data."""


class AmbiguousRelationUsageError(TracingError):
    """Raised when one wrongly assumes that there can only be one relation on an endpoint."""


if int(pydantic.version.VERSION.split(".")[0]) < 2:

    class DatabagModel(BaseModel):  # type: ignore
        """Base databag model."""

        class Config:
            """Pydantic config."""

            # ignore any extra fields in the databag
            extra = "ignore"
            """Ignore any extra fields in the databag."""
            allow_population_by_field_name = True
            """Allow instantiating this class by field name (instead of forcing alias)."""

        _NEST_UNDER = None

        @classmethod
        def load(cls, databag: MutableMapping):
            """Load this model from a Juju databag."""
            if cls._NEST_UNDER:
                return cls.parse_obj(json.loads(databag[cls._NEST_UNDER]))

            try:
                data = {
                    k: json.loads(v)
                    for k, v in databag.items()
                    # Don't attempt to parse model-external values
                    if k in {f.alias for f in cls.__fields__.values()}
                }
            except json.JSONDecodeError as e:
                msg = f"invalid databag contents: expecting json. {databag}"
                logger.error(msg)
                raise DataValidationError(msg) from e

            try:
                return cls.parse_raw(json.dumps(data))  # type: ignore
            except pydantic.ValidationError as e:
                msg = f"failed to validate databag: {databag}"
                logger.debug(msg, exc_info=True)
                raise DataValidationError(msg) from e

        def dump(self, databag: Optional[MutableMapping] = None, clear: bool = True):
            """Write the contents of this model to Juju databag.

            :param databag: the databag to write the data to.
            :param clear: ensure the databag is cleared before writing it.
            """
            if clear and databag:
                databag.clear()

            if databag is None:
                databag = {}

            if self._NEST_UNDER:
                databag[self._NEST_UNDER] = self.json(by_alias=True)
                return databag

            dct = self.dict()
            for key, field in self.__fields__.items():  # type: ignore
                value = dct[key]
                databag[field.alias or key] = json.dumps(value)

            return databag

else:
    from pydantic import ConfigDict

    class DatabagModel(BaseModel):
        """Base databag model."""

        model_config = ConfigDict(
            # ignore any extra fields in the databag
            extra="ignore",
            # Allow instantiating this class by field name (instead of forcing alias).
            populate_by_name=True,
            # Custom config key: whether to nest the whole datastructure (as json)
            # under a field or spread it out at the toplevel.
            _NEST_UNDER=None,  # type: ignore
        )
        """Pydantic config."""

        @classmethod
        def load(cls, databag: MutableMapping):
            """Load this model from a Juju databag."""
            nest_under = cls.model_config.get("_NEST_UNDER")  # type: ignore
            if nest_under:
                return cls.model_validate(json.loads(databag[nest_under]))  # type: ignore

            try:
                data = {
                    k: json.loads(v)
                    for k, v in databag.items()
                    # Don't attempt to parse model-external values
                    if k in {(f.alias or n) for n, f in cls.__fields__.items()}
                }
            except json.JSONDecodeError as e:
                msg = f"invalid databag contents: expecting json. {databag}"
                logger.error(msg)
                raise DataValidationError(msg) from e

            try:
                return cls.model_validate_json(json.dumps(data))  # type: ignore
            except pydantic.ValidationError as e:
                msg = f"failed to validate databag: {databag}"
                logger.debug(msg, exc_info=True)
                raise DataValidationError(msg) from e

        def dump(self, databag: Optional[MutableMapping] = None, clear: bool = True):
            """Write the contents of this model to Juju databag.

            :param databag: the databag to write the data to.
            :param clear: ensure the databag is cleared before writing it.
            """
            if clear and databag:
                databag.clear()

            if databag is None:
                databag = {}
            nest_under = self.model_config.get("_NEST_UNDER")
            if nest_under:
                databag[nest_under] = self.model_dump_json(  # type: ignore
                    by_alias=True,
                    # skip keys whose values are default
                    exclude_defaults=True,
                )
                return databag

            dct = self.model_dump()  # type: ignore
            for key, field in self.model_fields.items():  # type: ignore
                value = dct[key]
                if value == field.default:
                    continue
                databag[field.alias or key] = json.dumps(value)

            return databag


# todo use models from charm-relation-interfaces
class Receiver(BaseModel):  # noqa: D101
    """Receiver data structure."""

    protocol: ReceiverProtocol
    port: int


class TracingProviderAppData(DatabagModel):  # noqa: D101
    """Application databag model for the tracing provider."""

    host: str
    """Server hostname (local fqdn)."""

    receivers: List[Receiver]
    """Enabled receivers and ports at which they are listening."""

    external_url: Optional[str] = None
    """Server url. If an ingress is present, it will be the ingress address."""

    internal_scheme: Optional[str] = None
    """Scheme for internal communication. If it is present, it will be protocol accepted by the provider."""


class TracingRequirerAppData(DatabagModel):  # noqa: D101
    """Application databag model for the tracing requirer."""

    receivers: List[ReceiverProtocol]
    """Requested receivers."""


class _AutoSnapshotEvent(RelationEvent):
    __args__: Tuple[str, ...] = ()
    __optional_kwargs__: Dict[str, Any] = {}

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


class RelationNotFoundError(Exception):
    """Raised if no relation with the given name is found."""

    def __init__(self, relation_name: str):
        self.relation_name = relation_name
        self.message = "No relation named '{}' found".format(relation_name)
        super().__init__(self.message)


class RelationInterfaceMismatchError(Exception):
    """Raised if the relation with the given name has an unexpected interface."""

    def __init__(
        self,
        relation_name: str,
        expected_relation_interface: str,
        actual_relation_interface: str,
    ):
        self.relation_name = relation_name
        self.expected_relation_interface = expected_relation_interface
        self.actual_relation_interface = actual_relation_interface
        self.message = (
            "The '{}' relation has '{}' as interface rather than the expected '{}'".format(
                relation_name, actual_relation_interface, expected_relation_interface
            )
        )

        super().__init__(self.message)


class RelationRoleMismatchError(Exception):
    """Raised if the relation with the given name has a different role than expected."""

    def __init__(
        self,
        relation_name: str,
        expected_relation_role: RelationRole,
        actual_relation_role: RelationRole,
    ):
        self.relation_name = relation_name
        self.expected_relation_interface = expected_relation_role
        self.actual_relation_role = actual_relation_role
        self.message = "The '{}' relation has role '{}' rather than the expected '{}'".format(
            relation_name, repr(actual_relation_role), repr(expected_relation_role)
        )

        super().__init__(self.message)


def _validate_relation_by_interface_and_direction(
    charm: CharmBase,
    relation_name: str,
    expected_relation_interface: str,
    expected_relation_role: RelationRole,
):
    """Validate a relation.

    Verifies that the `relation_name` provided: (1) exists in metadata.yaml,
    (2) declares as interface the interface name passed as `relation_interface`
    and (3) has the right "direction", i.e., it is a relation that `charm`
    provides or requires.

    Args:
        charm: a `CharmBase` object to scan for the matching relation.
        relation_name: the name of the relation to be verified.
        expected_relation_interface: the interface name to be matched by the
            relation named `relation_name`.
        expected_relation_role: whether the `relation_name` must be either
            provided or required by `charm`.

    Raises:
        RelationNotFoundError: If there is no relation in the charm's metadata.yaml
            with the same name as provided via `relation_name` argument.
        RelationInterfaceMismatchError: The relation with the same name as provided
            via `relation_name` argument does not have the same relation interface
            as specified via the `expected_relation_interface` argument.
        RelationRoleMismatchError: If the relation with the same name as provided
            via `relation_name` argument does not have the same role as specified
            via the `expected_relation_role` argument.
    """
    if relation_name not in charm.meta.relations:
        raise RelationNotFoundError(relation_name)

    relation = charm.meta.relations[relation_name]

    # fixme: why do we need to cast here?
    actual_relation_interface = cast(str, relation.interface_name)

    if actual_relation_interface != expected_relation_interface:
        raise RelationInterfaceMismatchError(
            relation_name, expected_relation_interface, actual_relation_interface
        )

    if expected_relation_role is RelationRole.provides:
        if relation_name not in charm.meta.provides:
            raise RelationRoleMismatchError(
                relation_name, RelationRole.provides, RelationRole.requires
            )
    elif expected_relation_role is RelationRole.requires:
        if relation_name not in charm.meta.requires:
            raise RelationRoleMismatchError(
                relation_name, RelationRole.requires, RelationRole.provides
            )
    else:
        raise TypeError("Unexpected RelationDirection: {}".format(expected_relation_role))


class RequestEvent(RelationEvent):
    """Event emitted when a remote requests a tracing endpoint."""

    @property
    def requested_receivers(self) -> List[ReceiverProtocol]:
        """List of receiver protocols that have been requested."""
        relation = self.relation
        app = relation.app
        if not app:
            raise NotReadyError("relation.app is None")

        return TracingRequirerAppData.load(relation.data[app]).receivers


class TracingEndpointProviderEvents(CharmEvents):
    """TracingEndpointProvider events."""

    request = EventSource(RequestEvent)


class TracingEndpointProvider(Object):
    """Class representing a trace receiver service."""

    on = TracingEndpointProviderEvents()  # type: ignore

    def __init__(
        self,
        charm: CharmBase,
        host: str,
        external_url: Optional[str] = None,
        relation_name: str = DEFAULT_RELATION_NAME,
        internal_scheme: Optional[Literal["http", "https"]] = "http",
    ):
        """Initialize.

        Args:
            charm: a `CharmBase` instance that manages this instance of the Tempo service.
            host: address of the node hosting the tempo server.
            external_url: external address of the node hosting the tempo server,
                if an ingress is present.
            relation_name: an optional string name of the relation between `charm`
                and the Tempo charmed service. The default is "tracing".
            internal_scheme: scheme to use with internal urls.

        Raises:
            RelationNotFoundError: If there is no relation in the charm's metadata.yaml
                with the same name as provided via `relation_name` argument.
            RelationInterfaceMismatchError: The relation with the same name as provided
                via `relation_name` argument does not have the `tracing` relation
                interface.
            RelationRoleMismatchError: If the relation with the same name as provided
                via `relation_name` argument does not have the `RelationRole.requires`
                role.
        """
        _validate_relation_by_interface_and_direction(
            charm, relation_name, RELATION_INTERFACE_NAME, RelationRole.provides
        )

        super().__init__(charm, relation_name + "tracing-provider-v2")
        self._charm = charm
        self._host = host
        self._external_url = external_url
        self._relation_name = relation_name
        self._internal_scheme = internal_scheme
        self.framework.observe(
            self._charm.on[relation_name].relation_joined, self._on_relation_event
        )
        self.framework.observe(
            self._charm.on[relation_name].relation_created, self._on_relation_event
        )
        self.framework.observe(
            self._charm.on[relation_name].relation_changed, self._on_relation_event
        )

    def _on_relation_event(self, e: RelationEvent):
        """Handle relation created/joined/changed events."""
        if self.is_v2(e.relation):
            self.on.request.emit(e.relation)

    def is_v2(self, relation: Relation):
        """Attempt to determine if this relation is a tracing v2 relation.

        Assumes that the V2 requirer will, as soon as possible (relation-created),
        publish the list of requested ingestion receivers (can be empty too).
        """
        try:
            self._get_requested_protocols(relation)
        except NotReadyError:
            return False
        return True

    @staticmethod
    def _get_requested_protocols(relation: Relation):
        app = relation.app
        if not app:
            raise NotReadyError("relation.app is None")

        try:
            databag = TracingRequirerAppData.load(relation.data[app])
        except (json.JSONDecodeError, pydantic.ValidationError, DataValidationError):
            logger.info(f"relation {relation} is not ready to talk tracing v2")
            raise NotReadyError()
        return databag.receivers

    def requested_protocols(self):
        """All receiver protocols that have been requested by our related apps."""
        requested_protocols = set()
        for relation in self.relations:
            try:
                protocols = self._get_requested_protocols(relation)
            except NotReadyError:
                continue
            requested_protocols.update(protocols)
        return requested_protocols

    @property
    def relations(self) -> List[Relation]:
        """All v2 relations active on this endpoint."""
        return [r for r in self._charm.model.relations[self._relation_name] if self.is_v2(r)]

    def publish_receivers(self, receivers: Sequence[RawReceiver]):
        """Let all requirers know that these receivers are active and listening."""
        if not self._charm.unit.is_leader():
            raise RuntimeError("only leader can do this")

        for relation in self.relations:
            try:
                TracingProviderAppData(
                    host=self._host,
                    external_url=self._external_url or None,
                    receivers=[
                        Receiver(port=port, protocol=protocol) for protocol, port in receivers
                    ],
                    internal_scheme=self._internal_scheme,
                ).dump(relation.data[self._charm.app])

            except ModelError as e:
                # args are bytes
                msg = e.args[0]
                if isinstance(msg, bytes):
                    if msg.startswith(
                        b"ERROR cannot read relation application settings: permission denied"
                    ):
                        logger.error(
                            f"encountered error {e} while attempting to update_relation_data."
                            f"The relation must be gone."
                        )
                        continue
                raise


class EndpointRemovedEvent(RelationBrokenEvent):
    """Event representing a change in one of the receiver endpoints."""


class EndpointChangedEvent(_AutoSnapshotEvent):
    """Event representing a change in one of the receiver endpoints."""

    __args__ = ("host", "external_url", "_receivers")

    if TYPE_CHECKING:
        host = ""  # type: str
        external_url = ""  # type: str
        _receivers = []  # type: List[dict]

    @property
    def receivers(self) -> List[Receiver]:
        """Cast receivers back from dict."""
        return [Receiver(**i) for i in self._receivers]


class TracingEndpointRequirerEvents(CharmEvents):
    """TracingEndpointRequirer events."""

    endpoint_changed = EventSource(EndpointChangedEvent)
    endpoint_removed = EventSource(EndpointRemovedEvent)


class TracingEndpointRequirer(Object):
    """A tracing endpoint for Tempo."""

    on = TracingEndpointRequirerEvents()  # type: ignore

    def __init__(
        self,
        charm: CharmBase,
        relation_name: str = DEFAULT_RELATION_NAME,
        protocols: Optional[List[ReceiverProtocol]] = None,
    ):
        """Construct a tracing requirer for a Tempo charm.

        If your application supports pushing traces to a distributed tracing backend, the
        `TracingEndpointRequirer` object enables your charm to easily access endpoint information
        exchanged over a `tracing` relation interface.

        Args:
            charm: a `CharmBase` object that manages this
                `TracingEndpointRequirer` object. Typically, this is `self` in the instantiating
                class.
            relation_name: an optional string name of the relation between `charm`
                and the Tempo charmed service. The default is "tracing". It is strongly
                advised not to change the default, so that people deploying your charm will have a
                consistent experience with all other charms that provide tracing endpoints.
            protocols: optional list of protocols that the charm intends to send traces with.
                The provider will enable receivers for these and only these protocols,
                so be sure to enable all protocols the charm or its workload are going to need.

        Raises:
            RelationNotFoundError: If there is no relation in the charm's metadata.yaml
                with the same name as provided via `relation_name` argument.
            RelationInterfaceMismatchError: The relation with the same name as provided
                via `relation_name` argument does not have the `tracing` relation
                interface.
            RelationRoleMismatchError: If the relation with the same name as provided
                via `relation_name` argument does not have the `RelationRole.provides`
                role.
        """
        _validate_relation_by_interface_and_direction(
            charm, relation_name, RELATION_INTERFACE_NAME, RelationRole.requires
        )

        super().__init__(charm, relation_name)

        self._is_single_endpoint = charm.meta.relations[relation_name].limit == 1

        self._charm = charm
        self._relation_name = relation_name

        events = self._charm.on[self._relation_name]
        self.framework.observe(events.relation_changed, self._on_tracing_relation_changed)
        self.framework.observe(events.relation_broken, self._on_tracing_relation_broken)

        if protocols:
            self.request_protocols(protocols)

    def request_protocols(
        self, protocols: Sequence[ReceiverProtocol], relation: Optional[Relation] = None
    ):
        """Publish the list of protocols which the provider should activate."""
        # todo: should we check if _is_single_endpoint and len(self.relations) > 1 and raise, here?
        relations = [relation] if relation else self.relations

        if not protocols:
            # empty sequence
            raise ValueError(
                "You need to pass a nonempty sequence of protocols to `request_protocols`."
            )

        try:
            if self._charm.unit.is_leader():
                for relation in relations:
                    TracingRequirerAppData(
                        receivers=list(protocols),
                    ).dump(relation.data[self._charm.app])

        except ModelError as e:
            # args are bytes
            msg = e.args[0]
            if isinstance(msg, bytes):
                if msg.startswith(
                    b"ERROR cannot read relation application settings: permission denied"
                ):
                    logger.error(
                        f"encountered error {e} while attempting to request_protocols."
                        f"The relation must be gone."
                    )
                    return
            raise

    @property
    def relations(self) -> List[Relation]:
        """The tracing relations associated with this endpoint."""
        return self._charm.model.relations[self._relation_name]

    @property
    def _relation(self) -> Optional[Relation]:
        """If this wraps a single endpoint, the relation bound to it, if any."""
        if not self._is_single_endpoint:
            objname = type(self).__name__
            raise AmbiguousRelationUsageError(
                f"This {objname} wraps a {self._relation_name} endpoint that has "
                "limit != 1. We can't determine what relation, of the possibly many, you are "
                f"talking about. Please pass a relation instance while calling {objname}, "
                "or set limit=1 in the charm metadata."
            )
        relations = self.relations
        return relations[0] if relations else None

    def is_ready(self, relation: Optional[Relation] = None):
        """Is this endpoint ready?"""
        relation = relation or self._relation
        if not relation:
            logger.debug(f"no relation on {self._relation_name !r}: tracing not ready")
            return False
        if relation.data is None:
            logger.error(f"relation data is None for {relation}")
            return False
        if not relation.app:
            logger.error(f"{relation} event received but there is no relation.app")
            return False
        try:
            databag = dict(relation.data[relation.app])
            # "ingesters" Might be populated if the provider sees a v1 relation before a v2 requirer has had time to
            # publish the 'receivers' list. This will make Tempo incorrectly assume that this is a v1
            # relation, and act accordingly. Later, when the requirer publishes the requested receivers,
            # tempo will be able to course-correct.
            if "ingesters" in databag:
                del databag["ingesters"]
            TracingProviderAppData.load(databag)

        except (json.JSONDecodeError, pydantic.ValidationError, DataValidationError):
            logger.info(f"failed validating relation data for {relation}")
            return False
        return True

    def _on_tracing_relation_changed(self, event):
        """Notify the providers that there is new endpoint information available."""
        relation = event.relation
        if not self.is_ready(relation):
            self.on.endpoint_removed.emit(relation)  # type: ignore
            return

        data = TracingProviderAppData.load(relation.data[relation.app])
        self.on.endpoint_changed.emit(  # type: ignore
            relation, data.host, data.external_url, [i.dict() for i in data.receivers]
        )

    def _on_tracing_relation_broken(self, event: RelationBrokenEvent):
        """Notify the providers that the endpoint is broken."""
        relation = event.relation
        self.on.endpoint_removed.emit(relation)  # type: ignore

    def get_all_endpoints(
        self, relation: Optional[Relation] = None
    ) -> Optional[TracingProviderAppData]:
        """Unmarshalled relation data."""
        relation = relation or self._relation
        if not self.is_ready(relation):
            return
        return TracingProviderAppData.load(relation.data[relation.app])  # type: ignore

    def _get_endpoint(
        self, relation: Optional[Relation], protocol: ReceiverProtocol
    ) -> Optional[str]:
        app_data = self.get_all_endpoints(relation)
        if not app_data:
            return None
        receivers: List[Receiver] = list(
            filter(lambda i: i.protocol == protocol, app_data.receivers)
        )
        if not receivers:
            logger.error(f"no receiver found with protocol={protocol!r}")
            return
        if len(receivers) > 1:
            logger.error(
                f"too many receivers with protocol={protocol!r}; using first one. Found: {receivers}"
            )
            return

        receiver = receivers[0]
        # if there's an external_url argument (v2.5+), use that. Otherwise, we use the tempo local fqdn
        if app_data.external_url:
            url = f"{app_data.external_url}:{receiver.port}"
        else:
            # if we didn't receive a scheme (old provider), we assume HTTP is used
            url = f"{app_data.internal_scheme or 'http'}://{app_data.host}:{receiver.port}"

        if receiver.protocol.endswith("grpc"):
            # TCP protocols don't want an http/https scheme prefix
            url = url.split("://")[1]

        return url

    def get_endpoint(
        self, protocol: ReceiverProtocol, relation: Optional[Relation] = None
    ) -> Optional[str]:
        """Receiver endpoint for the given protocol."""
        endpoint = self._get_endpoint(relation or self._relation, protocol=protocol)
        if not endpoint:
            requested_protocols = set()
            relations = [relation] if relation else self.relations
            for relation in relations:
                try:
                    databag = TracingRequirerAppData.load(relation.data[self._charm.app])
                except DataValidationError:
                    continue

                requested_protocols.update(databag.receivers)

            if protocol not in requested_protocols:
                raise ProtocolNotRequestedError(protocol, relation)

            return None
        return endpoint

    # for backwards compatibility with earlier revisions:
    def otlp_grpc_endpoint(self):
        """Use TracingEndpointRequirer.get_endpoint('otlp_grpc') instead."""
        logger.warning(
            "`TracingEndpointRequirer.otlp_grpc_endpoint` is deprecated. "
            "Use `TracingEndpointRequirer.get_endpoint('otlp_grpc') instead.`"
        )
        return self.get_endpoint("otlp_grpc")

    def otlp_http_endpoint(self):
        """Use TracingEndpointRequirer.get_endpoint('otlp_http') instead."""
        logger.warning(
            "`TracingEndpointRequirer.otlp_http_endpoint` is deprecated. "
            "Use `TracingEndpointRequirer.get_endpoint('otlp_http') instead.`"
        )
        return self.get_endpoint("otlp_http")
