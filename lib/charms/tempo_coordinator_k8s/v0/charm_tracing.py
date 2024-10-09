#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

"""This charm library contains utilities to instrument your Charm with opentelemetry tracing data collection.

(yes! charm code, not workload code!)

This means that, if your charm is related to, for example, COS' Tempo charm, you will be able to inspect
in real time from the Grafana dashboard the execution flow of your charm.

# Quickstart
Fetch the following charm libs (and ensure the minimum version/revision numbers are satisfied):

    charmcraft fetch-lib charms.tempo_coordinator_k8s.v0.tracing  # >= 1.10
    charmcraft fetch-lib charms.tempo_coordinator_k8s.v0.charm_tracing  # >= 2.7

Then edit your charm code to include:

```python
# import the necessary charm libs
from charms.tempo_coordinator_k8s.v0.tracing import TracingEndpointRequirer, charm_tracing_config
from charms.tempo_coordinator_k8s.v0.charm_tracing import charm_tracing

# decorate your charm class with charm_tracing:
@charm_tracing(
    # forward-declare the instance attributes that the instrumentor will look up to obtain the
    # tempo endpoint and server certificate
    tracing_endpoint="tracing_endpoint",
    server_cert="server_cert"
)
class MyCharm(CharmBase):
    _path_to_cert = "/path/to/cert.crt"
    # path to cert file **in the charm container**. Its presence will be used to determine whether
    # the charm is ready to use tls for encrypting charm traces. If your charm does not support tls,
    # you can ignore this and pass None to charm_tracing_config.
    # If you do support TLS, you'll need to make sure that the server cert is copied to this location
    # and kept up to date so the instrumentor can use it.

    def __init__(self, ...):
        ...
        self.tracing = TracingEndpointRequirer(self, ...)
        self.tracing_endpoint, self.server_cert = charm_tracing_config(self.tracing, self._path_to_cert)
```

# Detailed usage
To use this library, you need to do two things:
1) decorate your charm class with

`@trace_charm(tracing_endpoint="my_tracing_endpoint")`

2) add to your charm a "my_tracing_endpoint" (you can name this attribute whatever you like)
**property**, **method** or **instance attribute** that returns an otlp http/https endpoint url.
If you are using the ``charms.tempo_coordinator_k8s.v0.tracing.TracingEndpointRequirer`` as
``self.tracing = TracingEndpointRequirer(self)``, the implementation could be:

```
    @property
    def my_tracing_endpoint(self) -> Optional[str]:
        '''Tempo endpoint for charm tracing'''
        if self.tracing.is_ready():
            return self.tracing.get_endpoint("otlp_http")
        else:
            return None
```

At this point your charm will be automatically instrumented so that:
- charm execution starts a trace, containing
    - every event as a span (including custom events)
    - every charm method call (except dunders) as a span


## TLS support
If your charm integrates with a TLS provider which is also trusted by the tracing provider (the Tempo charm),
you can configure ``charm_tracing`` to use TLS by passing a ``server_cert`` parameter to the decorator.

If your charm is not trusting the same CA as the Tempo endpoint it is sending traces to,
you'll need to implement a cert-transfer relation to obtain the CA certificate from the same
CA that Tempo is using.

For example:
```
from charms.tempo_coordinator_k8s.v0.charm_tracing import trace_charm
@trace_charm(
    tracing_endpoint="my_tracing_endpoint",
    server_cert="_server_cert"
)
class MyCharm(CharmBase):
    self._server_cert = "/path/to/server.crt"
    ...

    def on_tls_changed(self, e) -> Optional[str]:
        # update the server cert on the charm container for charm tracing
        Path(self._server_cert).write_text(self.get_server_cert())

    def on_tls_broken(self, e) -> Optional[str]:
        # remove the server cert so charm_tracing won't try to use tls anymore
        Path(self._server_cert).unlink()
```


## More fine-grained manual instrumentation
if you wish to add more spans to the trace, you can do so by getting a hold of the tracer like so:
```
import opentelemetry
...
def get_tracer(self) -> opentelemetry.trace.Tracer:
    return opentelemetry.trace.get_tracer(type(self).__name__)
```

By default, the tracer is named after the charm type. If you wish to override that, you can pass
a different ``service_name`` argument to ``trace_charm``.

See the official opentelemetry Python SDK documentation for usage:
https://opentelemetry-python.readthedocs.io/en/latest/

## Upgrading from `v0`

If you are upgrading from `charm_tracing` v0, you need to take the following steps (assuming you already
have the newest version of the library in your charm):
1) If you need the dependency for your tests, add the following dependency to your charm project
(or, if your project had a dependency on `opentelemetry-exporter-otlp-proto-grpc` only because
of `charm_tracing` v0, you can replace it with):

`opentelemetry-exporter-otlp-proto-http>=1.21.0`.

2) Update the charm method referenced to from ``@trace`` and ``@trace_charm``,
to return from ``TracingEndpointRequirer.get_endpoint("otlp_http")`` instead of ``grpc_http``.
For example:

```
    from charms.tempo_coordinator_k8s.v0.charm_tracing import trace_charm

    @trace_charm(
        tracing_endpoint="my_tracing_endpoint",
    )
    class MyCharm(CharmBase):

    ...

        @property
        def my_tracing_endpoint(self) -> Optional[str]:
            '''Tempo endpoint for charm tracing'''
            if self.tracing.is_ready():
                return self.tracing.otlp_grpc_endpoint() #  OLD API, DEPRECATED.
            else:
                return None
```

needs to be replaced with:

```
    from charms.tempo_coordinator_k8s.v0.charm_tracing import trace_charm

    @trace_charm(
        tracing_endpoint="my_tracing_endpoint",
    )
    class MyCharm(CharmBase):

    ...

        @property
        def my_tracing_endpoint(self) -> Optional[str]:
            '''Tempo endpoint for charm tracing'''
            if self.tracing.is_ready():
                return self.tracing.get_endpoint("otlp_http")  # NEW API, use this.
            else:
                return None
```

3) If you were passing a certificate (str) using `server_cert`, you need to change it to
provide an *absolute* path to the certificate file instead.
"""


def _remove_stale_otel_sdk_packages():
    """Hack to remove stale opentelemetry sdk packages from the charm's python venv.

    See https://github.com/canonical/grafana-agent-operator/issues/146 and
    https://bugs.launchpad.net/juju/+bug/2058335 for more context. This patch can be removed after
    this juju issue is resolved and sufficient time has passed to expect most users of this library
    have migrated to the patched version of juju.  When this patch is removed, un-ignore rule E402 for this file in the pyproject.toml (see setting
    [tool.ruff.lint.per-file-ignores] in pyproject.toml).

    This only has an effect if executed on an upgrade-charm event.
    """
    # all imports are local to keep this function standalone, side-effect-free, and easy to revert later
    import os

    if os.getenv("JUJU_DISPATCH_PATH") != "hooks/upgrade-charm":
        return

    import logging
    import shutil
    from collections import defaultdict

    from importlib_metadata import distributions

    otel_logger = logging.getLogger("charm_tracing_otel_patcher")
    otel_logger.debug("Applying _remove_stale_otel_sdk_packages patch on charm upgrade")
    # group by name all distributions starting with "opentelemetry_"
    otel_distributions = defaultdict(list)
    for distribution in distributions():
        name = distribution._normalized_name  # type: ignore
        if name.startswith("opentelemetry_"):
            otel_distributions[name].append(distribution)

    otel_logger.debug(f"Found {len(otel_distributions)} opentelemetry distributions")

    # If we have multiple distributions with the same name, remove any that have 0 associated files
    for name, distributions_ in otel_distributions.items():
        if len(distributions_) <= 1:
            continue

        otel_logger.debug(f"Package {name} has multiple ({len(distributions_)}) distributions.")
        for distribution in distributions_:
            if not distribution.files:  # Not None or empty list
                path = distribution._path  # type: ignore
                otel_logger.info(f"Removing empty distribution of {name} at {path}.")
                shutil.rmtree(path)

    otel_logger.debug("Successfully applied _remove_stale_otel_sdk_packages patch. ")


_remove_stale_otel_sdk_packages()

import functools
import inspect
import logging
import os
from contextlib import contextmanager
from contextvars import Context, ContextVar, copy_context
from pathlib import Path
from typing import (
    Any,
    Callable,
    Generator,
    Optional,
    Sequence,
    Type,
    TypeVar,
    Union,
    cast,
)

import opentelemetry
import ops
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import Span, TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace import INVALID_SPAN, Tracer
from opentelemetry.trace import get_current_span as otlp_get_current_span
from opentelemetry.trace import (
    get_tracer,
    get_tracer_provider,
    set_span_in_context,
    set_tracer_provider,
)
from ops.charm import CharmBase
from ops.framework import Framework

# The unique Charmhub library identifier, never change it
LIBID = "01780f1e588c42c3976d26780fdf9b89"

# Increment this major API version when introducing breaking changes
LIBAPI = 0

# Increment this PATCH version before using `charmcraft publish-lib` or reset
# to 0 if you are raising the major API version

LIBPATCH = 2

PYDEPS = ["opentelemetry-exporter-otlp-proto-http==1.21.0"]

logger = logging.getLogger("tracing")
dev_logger = logging.getLogger("tracing-dev")

# set this to 0 if you are debugging/developing this library source
dev_logger.setLevel(logging.CRITICAL)

_CharmType = Type[CharmBase]  # the type CharmBase and any subclass thereof
_C = TypeVar("_C", bound=_CharmType)
_T = TypeVar("_T", bound=type)
_F = TypeVar("_F", bound=Type[Callable])
tracer: ContextVar[Tracer] = ContextVar("tracer")
_GetterType = Union[Callable[[_CharmType], Optional[str]], property]

CHARM_TRACING_ENABLED = "CHARM_TRACING_ENABLED"


def is_enabled() -> bool:
    """Whether charm tracing is enabled."""
    return os.getenv(CHARM_TRACING_ENABLED, "1") == "1"


@contextmanager
def charm_tracing_disabled():
    """Contextmanager to temporarily disable charm tracing.

    For usage in tests.
    """
    previous = os.getenv(CHARM_TRACING_ENABLED, "1")
    os.environ[CHARM_TRACING_ENABLED] = "0"
    yield
    os.environ[CHARM_TRACING_ENABLED] = previous


def get_current_span() -> Union[Span, None]:
    """Return the currently active Span, if there is one, else None.

    If you'd rather keep your logic unconditional, you can use opentelemetry.trace.get_current_span,
    which will return an object that behaves like a span but records no data.
    """
    span = otlp_get_current_span()
    if span is INVALID_SPAN:
        return None
    return cast(Span, span)


def _get_tracer_from_context(ctx: Context) -> Optional[ContextVar]:
    tracers = [v for v in ctx if v is not None and v.name == "tracer"]
    if tracers:
        return tracers[0]
    return None


def _get_tracer() -> Optional[Tracer]:
    """Find tracer in context variable and as a fallback locate it in the full context."""
    try:
        return tracer.get()
    except LookupError:
        # fallback: this course-corrects for a user error where charm_tracing symbols are imported
        # from different paths (typically charms.tempo_coordinator_k8s... and lib.charms.tempo_coordinator_k8s...)
        try:
            ctx: Context = copy_context()
            if context_tracer := _get_tracer_from_context(ctx):
                logger.warning(
                    "Tracer not found in `tracer` context var. "
                    "Verify that you're importing all `charm_tracing` symbols from the same module path. \n"
                    "For example, DO"
                    ": `from charms.lib...charm_tracing import foo, bar`. \n"
                    "DONT: \n"
                    " \t - `from charms.lib...charm_tracing import foo` \n"
                    " \t - `from lib...charm_tracing import bar` \n"
                    "For more info: https://python-notes.curiousefficiency.org/en/latest/python"
                    "_concepts/import_traps.html#the-double-import-trap"
                )
                return context_tracer.get()
            else:
                return None
        except LookupError:
            return None


@contextmanager
def _span(name: str) -> Generator[Optional[Span], Any, Any]:
    """Context to create a span if there is a tracer, otherwise do nothing."""
    if tracer := _get_tracer():
        with tracer.start_as_current_span(name) as span:
            yield cast(Span, span)
    else:
        yield None


class TracingError(RuntimeError):
    """Base class for errors raised by this module."""


class UntraceableObjectError(TracingError):
    """Raised when an object you're attempting to instrument cannot be autoinstrumented."""


def _get_tracing_endpoint(
    tracing_endpoint_attr: str,
    charm_instance: object,
    charm_type: type,
):
    _tracing_endpoint = getattr(charm_instance, tracing_endpoint_attr)
    if callable(_tracing_endpoint):
        tracing_endpoint = _tracing_endpoint()
    else:
        tracing_endpoint = _tracing_endpoint

    if tracing_endpoint is None:
        return

    elif not isinstance(tracing_endpoint, str):
        raise TypeError(
            f"{charm_type.__name__}.{tracing_endpoint_attr} should resolve to a tempo endpoint (string); "
            f"got {tracing_endpoint} instead."
        )

    dev_logger.debug(f"Setting up span exporter to endpoint: {tracing_endpoint}/v1/traces")
    return f"{tracing_endpoint}/v1/traces"


def _get_server_cert(
    server_cert_attr: str,
    charm_instance: ops.CharmBase,
    charm_type: Type[ops.CharmBase],
):
    _server_cert = getattr(charm_instance, server_cert_attr)
    if callable(_server_cert):
        server_cert = _server_cert()
    else:
        server_cert = _server_cert

    if server_cert is None:
        logger.warning(
            f"{charm_type}.{server_cert_attr} is None; sending traces over INSECURE connection."
        )
        return
    elif not Path(server_cert).is_absolute():
        raise ValueError(
            f"{charm_type}.{server_cert_attr} should resolve to a valid tls cert absolute path (string | Path)); "
            f"got {server_cert} instead."
        )
    return server_cert


def _setup_root_span_initializer(
    charm_type: _CharmType,
    tracing_endpoint_attr: str,
    server_cert_attr: Optional[str],
    service_name: Optional[str] = None,
):
    """Patch the charm's initializer."""
    original_init = charm_type.__init__

    @functools.wraps(original_init)
    def wrap_init(self: CharmBase, framework: Framework, *args, **kwargs):
        # we're using 'self' here because this is charm init code, makes sense to read what's below
        # from the perspective of the charm. Self.unit.name...

        original_init(self, framework, *args, **kwargs)
        # we call this from inside the init context instead of, say, _autoinstrument, because we want it to
        # be checked on a per-charm-instantiation basis, not on a per-type-declaration one.
        if not is_enabled():
            # this will only happen during unittesting, hopefully, so it's fine to log a
            # bit more verbosely
            logger.info("Tracing DISABLED: skipping root span initialization")
            return

        # already init some attrs that will be reinited later by calling original_init:
        # self.framework = framework
        # self.handle = Handle(None, self.handle_kind, None)

        original_event_context = framework._event_context
        # default service name isn't just app name because it could conflict with the workload service name
        _service_name = service_name or f"{self.app.name}-charm"

        unit_name = self.unit.name
        # apply hacky patch to remove stale opentelemetry sdk packages on upgrade-charm.
        # it could be trouble if someone ever decides to implement their own tracer parallel to
        # ours and before the charm has inited. We assume they won't.
        resource = Resource.create(
            attributes={
                "service.name": _service_name,
                "compose_service": _service_name,
                "charm_type": type(self).__name__,
                # juju topology
                "juju_unit": unit_name,
                "juju_application": self.app.name,
                "juju_model": self.model.name,
                "juju_model_uuid": self.model.uuid,
            }
        )
        provider = TracerProvider(resource=resource)

        # if anything goes wrong with retrieving the endpoint, we let the exception bubble up.
        tracing_endpoint = _get_tracing_endpoint(tracing_endpoint_attr, self, charm_type)

        if not tracing_endpoint:
            # tracing is off if tracing_endpoint is None
            return

        server_cert: Optional[Union[str, Path]] = (
            _get_server_cert(server_cert_attr, self, charm_type) if server_cert_attr else None
        )

        if tracing_endpoint.startswith("https://") and not server_cert:
            logger.error(
                "Tracing endpoint is https, but no server_cert has been passed."
                "Please point @trace_charm to a `server_cert` attr. "
                "This might also mean that the tracing provider is related to a "
                "certificates provider, but this application is not (yet). "
                "In that case, you might just have to wait a bit for the certificates "
                "integration to settle. "
            )
            return

        exporter = OTLPSpanExporter(
            endpoint=tracing_endpoint,
            certificate_file=str(Path(server_cert).absolute()) if server_cert else None,
            timeout=2,
        )

        processor = BatchSpanProcessor(exporter)
        provider.add_span_processor(processor)
        set_tracer_provider(provider)
        _tracer = get_tracer(_service_name)  # type: ignore
        _tracer_token = tracer.set(_tracer)

        dispatch_path = os.getenv("JUJU_DISPATCH_PATH", "")  # something like hooks/install
        event_name = dispatch_path.split("/")[1] if "/" in dispatch_path else dispatch_path
        root_span_name = f"{unit_name}: {event_name} event"
        span = _tracer.start_span(root_span_name, attributes={"juju.dispatch_path": dispatch_path})

        # all these shenanigans are to work around the fact that the opentelemetry tracing API is built
        # on the assumption that spans will be used as contextmanagers.
        # Since we don't (as we need to close the span on framework.commit),
        # we need to manually set the root span as current.
        ctx = set_span_in_context(span)

        # log a trace id, so we can pick it up from the logs (and jhack) to look it up in tempo.
        root_trace_id = hex(span.get_span_context().trace_id)[2:]  # strip 0x prefix
        logger.debug(f"Starting root trace with id={root_trace_id!r}.")

        span_token = opentelemetry.context.attach(ctx)  # type: ignore

        @contextmanager
        def wrap_event_context(event_name: str):
            dev_logger.info(f"entering event context: {event_name}")
            # when the framework enters an event context, we create a span.
            with _span("event: " + event_name) as event_context_span:
                if event_context_span:
                    # todo: figure out how to inject event attrs in here
                    event_context_span.add_event(event_name)
                yield original_event_context(event_name)

        framework._event_context = wrap_event_context  # type: ignore

        original_close = framework.close

        @functools.wraps(original_close)
        def wrap_close():
            dev_logger.info("tearing down tracer and flushing traces")
            span.end()
            opentelemetry.context.detach(span_token)  # type: ignore
            tracer.reset(_tracer_token)
            tp = cast(TracerProvider, get_tracer_provider())
            tp.force_flush(timeout_millis=1000)  # don't block for too long
            tp.shutdown()
            original_close()

        framework.close = wrap_close
        return

    charm_type.__init__ = wrap_init  # type: ignore


def trace_charm(
    tracing_endpoint: str,
    server_cert: Optional[str] = None,
    service_name: Optional[str] = None,
    extra_types: Sequence[type] = (),
) -> Callable[[_T], _T]:
    """Autoinstrument the decorated charm with tracing telemetry.

    Use this function to get out-of-the-box traces for all events emitted on this charm and all
    method calls on instances of this class.

    Usage:
    >>> from charms.tempo_coordinator_k8s.v0.charm_tracing import trace_charm
    >>> from charms.tempo_coordinator_k8s.v0.tracing import TracingEndpointRequirer
    >>> from ops import CharmBase
    >>>
    >>> @trace_charm(
    >>>         tracing_endpoint="tempo_otlp_http_endpoint",
    >>> )
    >>> class MyCharm(CharmBase):
    >>>
    >>>     def __init__(self, framework: Framework):
    >>>         ...
    >>>         self.tracing = TracingEndpointRequirer(self)
    >>>
    >>>     @property
    >>>     def tempo_otlp_http_endpoint(self) -> Optional[str]:
    >>>         if self.tracing.is_ready():
    >>>             return self.tracing.otlp_http_endpoint()
    >>>         else:
    >>>             return None
    >>>

    :param tracing_endpoint: name of a method, property or attribute  on the charm type that returns an
        optional (fully resolvable) tempo url to which the charm traces will be pushed.
        If None, tracing will be effectively disabled.
    :param server_cert: name of a method, property or attribute on the charm type that returns an
        optional absolute path to a CA certificate file to be used when sending traces to a remote server.
        If it returns None, an _insecure_ connection will be used. To avoid errors in transient
        situations where the endpoint is already https but there is no certificate on disk yet, it
        is recommended to disable tracing (by returning None from the tracing_endpoint) altogether
        until the cert has been written to disk.
    :param service_name: service name tag to attach to all traces generated by this charm.
        Defaults to the juju application name this charm is deployed under.
    :param extra_types: pass any number of types that you also wish to autoinstrument.
        For example, charm libs, relation endpoint wrappers, workload abstractions, ...
    """

    def _decorator(charm_type: _T) -> _T:
        """Autoinstrument the wrapped charmbase type."""
        _autoinstrument(
            charm_type,
            tracing_endpoint_attr=tracing_endpoint,
            server_cert_attr=server_cert,
            service_name=service_name,
            extra_types=extra_types,
        )
        return charm_type

    return _decorator


def _autoinstrument(
    charm_type: _T,
    tracing_endpoint_attr: str,
    server_cert_attr: Optional[str] = None,
    service_name: Optional[str] = None,
    extra_types: Sequence[type] = (),
) -> _T:
    """Set up tracing on this charm class.

    Use this function to get out-of-the-box traces for all events emitted on this charm and all
    method calls on instances of this class.

    Usage:

    >>> from charms.tempo_coordinator_k8s.v0.charm_tracing import _autoinstrument
    >>> from ops.main import main
    >>> _autoinstrument(
    >>>         MyCharm,
    >>>         tracing_endpoint_attr="tempo_otlp_http_endpoint",
    >>>         service_name="MyCharm",
    >>>         extra_types=(Foo, Bar)
    >>> )
    >>> main(MyCharm)

    :param charm_type: the CharmBase subclass to autoinstrument.
    :param tracing_endpoint_attr: name of a method, property or attribute  on the charm type that returns an
        optional (fully resolvable) tempo url to which the charm traces will be pushed.
        If None, tracing will be effectively disabled.
    :param server_cert_attr: name of a method, property or attribute on the charm type that returns an
        optional absolute path to a CA certificate file to be used when sending traces to a remote server.
        If it returns None, an _insecure_ connection will be used. To avoid errors in transient
        situations where the endpoint is already https but there is no certificate on disk yet, it
        is recommended to disable tracing (by returning None from the tracing_endpoint) altogether
        until the cert has been written to disk.
    :param service_name: service name tag to attach to all traces generated by this charm.
        Defaults to the juju application name this charm is deployed under.
    :param extra_types: pass any number of types that you also wish to autoinstrument.
        For example, charm libs, relation endpoint wrappers, workload abstractions, ...
    """
    dev_logger.info(f"instrumenting {charm_type}")
    _setup_root_span_initializer(
        charm_type,
        tracing_endpoint_attr,
        server_cert_attr=server_cert_attr,
        service_name=service_name,
    )
    trace_type(charm_type)
    for type_ in extra_types:
        trace_type(type_)

    return charm_type


def trace_type(cls: _T) -> _T:
    """Set up tracing on this class.

    Use this decorator to get out-of-the-box traces for all method calls on instances of this class.
    It assumes that this class is only instantiated after a charm type decorated with `@trace_charm`
    has been instantiated.
    """
    dev_logger.info(f"instrumenting {cls}")
    for name, method in inspect.getmembers(cls, predicate=inspect.isfunction):
        dev_logger.info(f"discovered {method}")

        if method.__name__.startswith("__"):
            dev_logger.info(f"skipping {method} (dunder)")
            continue

        # the span title in the general case should be:
        #   method call: MyCharmWrappedMethods.b
        # if the method has a name (functools.wrapped or regular method), let
        # _trace_callable use its default algorithm to determine what name to give the span.
        trace_method_name = None
        try:
            qualname_c0 = method.__qualname__.split(".")[0]
            if not hasattr(cls, method.__name__):
                # if the callable doesn't have a __name__ (probably a decorated method),
                # it probably has a bad qualname too (such as my_decorator.<locals>.wrapper) which is not
                # great for finding out what the trace is about. So we use the method name instead and
                # add a reference to the decorator name. Result:
                #   method call: @my_decorator(MyCharmWrappedMethods.b)
                trace_method_name = f"@{qualname_c0}({cls.__name__}.{name})"
        except Exception:  # noqa: failsafe
            pass

        new_method = trace_method(method, name=trace_method_name)

        if isinstance(inspect.getattr_static(cls, name), staticmethod):
            new_method = staticmethod(new_method)
        setattr(cls, name, new_method)

    return cls


def trace_method(method: _F, name: Optional[str] = None) -> _F:
    """Trace this method.

    A span will be opened when this method is called and closed when it returns.
    """
    return _trace_callable(method, "method", name=name)


def trace_function(function: _F, name: Optional[str] = None) -> _F:
    """Trace this function.

    A span will be opened when this function is called and closed when it returns.
    """
    return _trace_callable(function, "function", name=name)


def _trace_callable(callable: _F, qualifier: str, name: Optional[str] = None) -> _F:
    dev_logger.info(f"instrumenting {callable}")

    # sig = inspect.signature(callable)
    @functools.wraps(callable)
    def wrapped_function(*args, **kwargs):  # type: ignore
        name_ = name or getattr(
            callable, "__qualname__", getattr(callable, "__name__", str(callable))
        )
        with _span(f"{qualifier} call: {name_}"):  # type: ignore
            return callable(*args, **kwargs)  # type: ignore

    # wrapped_function.__signature__ = sig
    return wrapped_function  # type: ignore


def trace(obj: Union[Type, Callable]):
    """Trace this object and send the resulting spans to Tempo.

    It will dispatch to ``trace_type`` if the decorated object is a class, otherwise
    ``trace_function``.
    """
    if isinstance(obj, type):
        if issubclass(obj, CharmBase):
            raise ValueError(
                "cannot use @trace on CharmBase subclasses: use @trace_charm instead "
                "(we need some arguments!)"
            )
        return trace_type(obj)
    else:
        try:
            return trace_function(obj)
        except Exception:
            raise UntraceableObjectError(
                f"cannot create span from {type(obj)}; instrument {obj} manually."
            )
