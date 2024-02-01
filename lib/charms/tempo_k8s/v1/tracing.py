# Copyright 2022 Pietro Pasotti
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
 is exposed by the Tempo charm. This relation must use the
`tracing` interface.
 The `TracingEndpointRequirer` object may be instantiated as follows

    from charms.tempo_k8s.v1.tracing import TracingEndpointRequirer

    def __init__(self, *args):
        super().__init__(*args)
        # ...
        self.tracing = TracingEndpointRequirer(self)
        # ...

Note that the first argument (`self`) to `TracingEndpointRequirer` is always a reference to the
parent charm.

Units of provider charms obtain the tempo endpoint to which they will push their traces by using one
of these  `TracingEndpointRequirer` attributes, depending on which protocol they support:
- otlp_grpc_endpoint
- otlp_http_endpoint
- zipkin_endpoint
- tempo_endpoint

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

    from charms.tempo_k8s.v1.tracing import TracingEndpointProvider

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
from pydantic import BaseModel, ConfigDict

# The unique Charmhub library identifier, never change it
LIBID = "12977e9aa0b34367903d8afeb8c3d85d"

# Increment this major API version when introducing breaking changes
LIBAPI = 1

# Increment this PATCH version before using `charmcraft publish-lib` or reset
# to 0 if you are raising the major API version
LIBPATCH = 2

PYDEPS = ["pydantic>=2"]

logger = logging.getLogger(__name__)

DEFAULT_RELATION_NAME = "tracing"
RELATION_INTERFACE_NAME = "tracing"

IngesterProtocol = Literal[
    "otlp_grpc", "otlp_http", "zipkin", "tempo", "jaeger_http_thrift", "jaeger_grpc"
]

RawIngester = Tuple[IngesterProtocol, int]
BUILTIN_JUJU_KEYS = {"ingress-address", "private-address", "egress-subnets"}


class TracingError(RuntimeError):
    """Base class for custom errors raised by this library."""


class DataValidationError(TracingError):
    """Raised when data validation fails on IPU relation data."""


class AmbiguousRelationUsageError(TracingError):
    """Raised when one wrongly assumes that there can only be one relation on an endpoint."""


class DatabagModel(BaseModel):
    """Base databag model."""

    model_config = ConfigDict(
        # Allow instantiating this class by field name (instead of forcing alias).
        populate_by_name=True,
        # Custom config key: whether to nest the whole datastructure (as json)
        # under a field or spread it out at the toplevel.
        _NEST_UNDER=None,
    )  # type: ignore
    """Pydantic config."""

    @classmethod
    def load(cls, databag: MutableMapping):
        """Load this model from a Juju databag."""
        nest_under = cls.model_config.get("_NEST_UNDER")
        if nest_under:
            return cls.parse_obj(json.loads(databag[nest_under]))

        try:
            data = {k: json.loads(v) for k, v in databag.items() if k not in BUILTIN_JUJU_KEYS}
        except json.JSONDecodeError as e:
            msg = f"invalid databag contents: expecting json. {databag}"
            logger.error(msg)
            raise DataValidationError(msg) from e

        try:
            return cls.parse_raw(json.dumps(data))  # type: ignore
        except pydantic.ValidationError as e:
            msg = f"failed to validate databag: {databag}"
            logger.error(msg, exc_info=True)
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
            databag[nest_under] = self.json()

        dct = self.model_dump()
        for key, field in self.model_fields.items():  # type: ignore
            value = dct[key]
            databag[field.alias or key] = json.dumps(value)

        return databag


# todo use models from charm-relation-interfaces
class Ingester(BaseModel):  # noqa: D101
    """Ingester data structure."""

    protocol: IngesterProtocol
    port: int


class TracingProviderAppData(DatabagModel):  # noqa: D101
    """Application databag model for the tracing provider."""

    host: str
    ingesters: List[Ingester]


class _AutoSnapshotEvent(RelationEvent):
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


class TracingEndpointProvider(Object):
    """Class representing a trace ingester service."""

    def __init__(
        self,
        charm: CharmBase,
        host: str,
        ingesters: List[RawIngester],
        relation_name: str = DEFAULT_RELATION_NAME,
    ):
        """Initialize.

        Args:
            charm: a `CharmBase` instance that manages this instance of the Tempo service.
            relation_name: an optional string name of the relation between `charm`
                and the Tempo charmed service. The default is "tracing".

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

        super().__init__(charm, relation_name)
        self._charm = charm
        self._host = host
        self._ingesters = ingesters
        self._relation_name = relation_name
        events = self._charm.on[relation_name]
        self.framework.observe(events.relation_created, self._on_relation_event)
        self.framework.observe(events.relation_joined, self._on_relation_event)

    def _on_relation_event(self, _):
        # Generic relation event handler.

        try:
            if self._charm.unit.is_leader():
                for relation in self._charm.model.relations[self._relation_name]:
                    TracingProviderAppData(
                        host=self._host,
                        ingesters=[
                            Ingester(port=port, protocol=protocol)
                            for protocol, port in self._ingesters
                        ],
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
                    return
            raise


class EndpointRemovedEvent(RelationBrokenEvent):
    """Event representing a change in one of the ingester endpoints."""


class EndpointChangedEvent(_AutoSnapshotEvent):
    """Event representing a change in one of the ingester endpoints."""

    __args__ = ("host", "_ingesters")

    if TYPE_CHECKING:
        host = ""  # type: str
        _ingesters = []  # type: List[dict]

    @property
    def ingesters(self) -> List[Ingester]:
        """Cast ingesters back from dict."""
        return [Ingester(**i) for i in self._ingesters]


class TracingEndpointEvents(CharmEvents):
    """TracingEndpointRequirer events."""

    endpoint_changed = EventSource(EndpointChangedEvent)
    endpoint_removed = EventSource(EndpointRemovedEvent)


class TracingEndpointRequirer(Object):
    """A tracing endpoint for Tempo."""

    on = TracingEndpointEvents()  # type: ignore

    def __init__(
        self,
        charm: CharmBase,
        relation_name: str = DEFAULT_RELATION_NAME,
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
            TracingProviderAppData.load(relation.data[relation.app])
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
        self.on.endpoint_changed.emit(relation, data.host, [i.dict() for i in data.ingesters])  # type: ignore

    def _on_tracing_relation_broken(self, event: RelationBrokenEvent):
        """Notify the providers that the endpoint is broken."""
        relation = event.relation
        self.on.endpoint_removed.emit(relation)  # type: ignore

    def get_all_endpoints(
        self, relation: Optional[Relation] = None
    ) -> Optional[TracingProviderAppData]:
        """Unmarshalled relation data."""
        if not self.is_ready(relation or self._relation):
            return
        return TracingProviderAppData.load(relation.data[relation.app])  # type: ignore

    def _get_ingester(
        self, relation: Optional[Relation], protocol: IngesterProtocol, ssl: bool = False
    ):
        ep = self.get_all_endpoints(relation)
        if not ep:
            return None
        try:
            ingester: Ingester = next(filter(lambda i: i.protocol == protocol, ep.ingesters))
            if ingester.protocol in ["otlp_grpc", "jaeger_grpc"]:
                if ssl:
                    logger.warning("unused ssl argument - was the right protocol called?")
                return f"{ep.host}:{ingester.port}"
            if ssl:
                return f"https://{ep.host}:{ingester.port}"
            return f"http://{ep.host}:{ingester.port}"
        except StopIteration:
            logger.error(f"no ingester found with protocol={protocol!r}")
            return None

    def otlp_grpc_endpoint(self, relation: Optional[Relation] = None) -> Optional[str]:
        """Ingester endpoint for the ``otlp_grpc`` protocol."""
        return self._get_ingester(relation or self._relation, protocol="otlp_grpc")

    def otlp_http_endpoint(
        self, relation: Optional[Relation] = None, ssl: bool = False
    ) -> Optional[str]:
        """Ingester endpoint for the ``otlp_http`` protocol.

        The provided endpoint does not contain the endpoint suffix. If the instrumenting library needs the full path,
        your endpoint code needs to add the ``/v1/traces`` suffix.
        """
        return self._get_ingester(relation or self._relation, protocol="otlp_http", ssl=ssl)

    def zipkin_endpoint(
        self, relation: Optional[Relation] = None, ssl: bool = False
    ) -> Optional[str]:
        """Ingester endpoint for the ``zipkin`` protocol.

        The provided endpoint does not contain the endpoint suffix. If the instrumenting library needs the full path,
        your endpoint code needs to add the ``/api/v2/spans`` suffix.
        """
        return self._get_ingester(relation or self._relation, protocol="zipkin", ssl=ssl)

    def tempo_endpoint(
        self, relation: Optional[Relation] = None, ssl: bool = False
    ) -> Optional[str]:
        """Ingester endpoint for the ``tempo`` protocol."""
        return self._get_ingester(relation or self._relation, protocol="tempo", ssl=ssl)

    def jaeger_http_thrift_endpoint(
        self, relation: Optional[Relation] = None, ssl: bool = False
    ) -> Optional[str]:
        """Ingester endpoint for the ``jaeger_http_thrift`` protocol.

        The provided endpoint does not contain the endpoint suffix. If the instrumenting library needs the full path,
        your endpoint code needs to add the ``/api/traces`` suffix.
        """
        return self._get_ingester(relation or self._relation, "jaeger_http_thrift", ssl=ssl)

    def jaeger_grpc_endpoint(self, relation: Optional[Relation] = None) -> Optional[str]:
        """Ingester endpoint for the ``jaeger_grpc`` protocol."""
        return self._get_ingester(relation or self._relation, "jaeger_grpc")
