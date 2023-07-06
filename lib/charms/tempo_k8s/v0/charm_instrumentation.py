#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.
"""This charm library contains utilities to instrument your Charm (yes! charm code, not workload code!) with
opentelemetry tracing data collection.

This means that, if your charm is related to, for example, COS' Tempo charm, you will be able to inspect
in real time from the Grafana dashboard the execution flow of your charm.

To start using this library, you need to do two things:
1) decorate your charm class with

`@trace_charm(tempo_endpoint="tempo_endpoint")`

2) add to your charm a "tempo_endpoint" (you can name this attribute whatever you like) property
that returns a tempo otlp grpc endpoint. If you are using the `TracingEndpointProvider` as
`self.tracing = TracingEndpointProvider(self)`, the implementation would be:

```
    @property
    def tempo_endpoint(self) -> Optional[str]:
        '''Tempo endpoint for charm tracing'''
        return self.tracing.otlp_grpc_endpoint
```

At this point your charm will be automatically instrumented so that:
- charm execution starts a trace, containing
    - every event as a span (including custom events)
    - every charm method call (except dunders) as a span

if you wish to add more fine-grained information to the trace, you can do so by getting a hold of the tracer like so:
```
import opentelemetry
...
    @property
    def tracer(self) -> opentelemetry.trace.Tracer:
        return opentelemetry.trace.get_tracer(type(self).__name__)
```

By default, the tracer is named after the charm type. If you wish to override that, you can pass
a different `service_name` argument to `trace_charm`.

"""
import functools
import inspect
import logging
import os
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Union, Type, Callable, TypeVar, Optional

import opentelemetry
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider, Span
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace import get_current_span as otlp_get_current_span
from ops.charm import CharmBase
from ops.framework import Framework, Handle

# The unique Charmhub library identifier, never change it
LIBID = "0a8cf1b7b95d4cfcb90055f2d84897b3"  # TODO: register new uuid; this is FAKE

# Increment this major API version when introducing breaking changes
LIBAPI = 0

# Increment this PATCH version before using `charmcraft publish-lib` or reset
# to 0 if you are raising the major API version
LIBPATCH = 1

PYDEPS = [
    "opentelemetry-exporter-otlp-proto-grpc"
]

logger = logging.getLogger('tracing')

tracer: ContextVar[opentelemetry.trace.Tracer] = ContextVar("tracer")
# redefine it here to expose it as a toplevel module name


def get_current_span() -> Union[Span, None]:
    """The currently active Span, if there is one, else None.

    If you'd rather keep your logic unconditional, you can use opentelemetry.trace.get_current_span,
    which will return an object that behaves like a span but records no data.
    """
    span = otlp_get_current_span()
    if span is opentelemetry.trace.INVALID_SPAN:
        return None
    return span


def _get_tracer() -> Optional[opentelemetry.trace.Tracer]:
    try:
        return tracer.get()
    except LookupError:
        return None


@contextmanager
def _span(name: str) -> Optional[Span]:
    """Context to create a span if there is a tracer, otherwise do nothing."""
    if tracer := _get_tracer():
        with tracer.start_as_current_span(name) as span:
            yield span
    else:
        yield None


_C = TypeVar("_C", bound=Type[CharmBase])
_T = TypeVar("_T", bound=type)
_F = TypeVar("_F", bound=Type[Callable])


class TracingError(RuntimeError):
    """Base class for errors raised by this module."""


class UntraceableObject(TracingError):
    """Raised when an object you're attempting to instrument cannot be autoinstrumented."""


def _setup_root_span_initializer(charm: Type[CharmBase],
                                 tempo_endpoint: str,
                                 service_name: Optional[str] = None
                                 ):
    """Patches the charm's initializer."""
    original_init = charm.__init__

    @functools.wraps(original_init)
    def wrap_init(self: CharmBase, framework: Framework, *args, **kwargs):

        # already init some attrs that will be reinited later by calling original_init:
        self.framework = framework
        self.handle = Handle(None, self.handle_kind, None)

        original_event_context = framework._event_context

        logging.debug('Initializing opentelemetry tracer...')
        _service_name = service_name or charm.__name__

        resource = Resource.create(attributes={
            "service.name": _service_name,
            "compose_service": _service_name
        })
        provider = TracerProvider(resource=resource)

        tempo = getattr(self, tempo_endpoint)
        if tempo is None:
            logger.warning(f'{charm}.{tempo_endpoint} returned {tempo}; '
                           f'continuing with tracing DISABLED.')
            return

        elif not isinstance(tempo, str):
            raise TypeError(
                f'{charm}.{tempo_endpoint} should return a tempo endpoint (string); '
                f'got {tempo} instead.'
            )
        else:
            logger.debug(f'Setting up span exporter to endpoint: {tempo}')
            exporter = OTLPSpanExporter(endpoint=tempo)

        processor = BatchSpanProcessor(exporter)
        provider.add_span_processor(processor)
        opentelemetry.trace.set_tracer_provider(provider)
        _tracer = opentelemetry.trace.get_tracer(service_name)
        _tracer_token = tracer.set(_tracer)

        dispatch_path = os.getenv("JUJU_DISPATCH_PATH", '')

        # all these shenanigans are to work around the fact that the opentelemetry tracing API is built
        # on the assumption that spans will be used as contextmanagers.
        # Since we don't (as we need to close the span on framework.commit),
        # we need to manually set the root span as current.
        span = _tracer.start_span(
            'charm exec',
            attributes={
                'juju.dispatch_path': dispatch_path
            }
        )
        ctx = opentelemetry.trace.set_span_in_context(span)
        span_token = opentelemetry.context.attach(ctx)

        @contextmanager
        def wrap_event_context(event_name: str):
            # when the framework enters an event context, we create a span.
            with _span("event: " + event_name) as event_context_span:
                if event_context_span:
                    # todo: figure out how to inject event attrs in here
                    event_context_span.add_event(event_name)
                yield original_event_context(event_name)

        framework._event_context = wrap_event_context

        original_close = framework.close

        @functools.wraps(original_close)
        def wrap_close():
            span.end()
            opentelemetry.context.detach(span_token)
            tracer.reset(_tracer_token)
            tp: TracerProvider = opentelemetry.trace.get_tracer_provider()
            tp.force_flush()
            tp.shutdown()
            original_close()

        framework.close = wrap_close

        original_init(self, framework, *args, **kwargs)
        return

    charm.__init__ = wrap_init


def trace_charm(tempo_endpoint: str, service_name: str = None) -> Callable[[_C], _C]:
    """Setup tracing on this charm class."""

    def trace_charm_type(charm: _C) -> _C:
        """Prepares the charm as tracing root: when the charm is run, the root span will open."""

        logger.info(f'instrumenting {charm}')
        # check that it is in dir(charm).
        if not hasattr(charm, tempo_endpoint):
            raise RuntimeError(f'you passed tempo_endpoint={tempo_endpoint} to '
                               f'@trace_charm; but {charm}.{tempo_endpoint} was not found.')

        _setup_root_span_initializer(charm, tempo_endpoint, service_name=service_name)
        trace_type(charm)
        return charm

    return trace_charm_type


def trace_type(cls: _T) -> _T:
    logger.info(f'instrumenting {cls}')
    for name, method in inspect.getmembers(cls, predicate=inspect.isfunction):
        logger.info(f'discovered {method}')

        if method.__name__.startswith("__"):
            logger.info(f"skipping (dunder)")
            continue

        setattr(cls, name, trace_function(method))

    return cls


def trace_function(function: _F) -> _F:
    logger.info(f'instrumenting {function}')

    # sig = inspect.signature(function)
    @functools.wraps(function)
    def wrapped_function(*args, **kwargs):
        with _span("method call: " + function.__name__):
            return function(*args, **kwargs)

    # wrapped_function.__signature__ = sig
    return wrapped_function


def trace(obj: Union[Type, Callable]):
    """Decorator to trace an object and send the resulting spans to Tempo."""
    if isinstance(obj, type):
        return trace_type(obj)
    else:
        try:
            return trace_function(obj)
        except:
            raise UntraceableObject(
                f'cannot create span from {type(obj)}; instrument {obj} manually.'
            )
