"""
## Overview

This document explains how to integrate with the Prometheus charm
for the purposes of providing a metrics endpoint to Prometheus. It
also explains how alternative implementations of the Prometheus charm
may maintain the same interface and be backward compatible with all
currently integrated charms. Finally this document is the
authoritative reference on the structure of relation data that is
shared between Prometheus charms and any other charm that intends to
provide a scrape target for Prometheus.

## Consumer Library Usage

This Prometheus charm interacts with its scrape targets using this
charm library This charm library is constructed using the [Provider
and Consumer](https://ops.readthedocs.io/en/latest/#module-ops.relation)
objects from the Operator Framework. This implies charms that would
like to expose metric endpoints for the Prometheus charm must use the
`PrometheusConsumer` object from the charm library to do so. Using the
`PrometheusConsumer` object requires instantiating it, typically in
the constructor of your charm (the one which exposes the metrics
endpoint). The `PrometheusConsumer` constructor requires the name of
the relation over which a scrape target (metrics endpoint) is exposed
to the Promtheus charm. This relation must use the `prometheus_scrape`
interface. In addition the constructor also requires a `consumes`
specification, which is a dictionary with key `prometheus` (also see
Provider Library Usage below) and a value that represents the minimum
acceptable version of Prometheus. This version string can be in any
format that is compatible with Python [Semantic Version
module](https://pypi.org/project/semantic-version/).  For example,
assuming your charm exposes a metrics endpoint over a relation named
"monitoring", you may instantiate `PrometheusConsumer` as follows

    from charms.prometheus_k8s.v0.prometheus import PrometheusConsumer

    def __init__(self, *args):
        super().__init__(*args)
        ...
        self.prometheus = PrometheusConsumer(self, "monitoring", {"prometheus": ">=2.0"})
        ...

This example hard codes the consumes dictionary argument containing the
minimal Prometheus version required, however you may want to consider
generating this dictionary by some other means, such as a
`self.consumes` property in your charm. This is because the minimum
required Prometheus version may change when you upgrade your charm. Of
course it is expected that you will keep this version string updated
as you develop newer releases of you charm. If the version string can
be determined at run time by inspecting the actual deployed version of
your charmed application, this would be ideal.

An instantiated `PrometheusConsumer` object may be used to add
or remove Prometheus scrape targets.  Adding and removing scrape
targets may be done using the `add_endpoint()` and `remove_endpoint()`
methods. Both these methods require the host address (usually IP) of
the scrape target, but optionally also accept a port (default 80) on
which the metrics endpoint is exposed. At present it is assumed that
the metrics endpoint will be exposed with a URL path `/metrics` at the
specified host and port. This is the default behaviour of Prometheus
that most compatible metrics exporters confirm to. As an example to
add a metrics endpoint using the instantiated `PrometheusConsumer`
object in your charms `StartEvent` handler you may do

    def _on_start(self, event):
        self.prometheus.add_endpoint(my_ip)

There is no reason that metrics endpoint need to be added in the start
event handler. This may be done in any event handler or even the charm
constructor. However this does require that the host address is known
at that point in time. Both the `add_endpoint()` and
`remove_endpoint()` methods are idempotent and invoking them multiple
times with the same host address and port has no adverse effect, no
exceptions are thrown and no events generated. The
`PrometheusConsumer` object caches lists of unique scrape targets,
indexed by relation IDs in its stored state. Both the methods exchange
information with Prometheus charm application relation data. Hence
both of these methods trigger `RelationChangedEvents` for the
Prometheus charm when new scrape targets are added or old ones
removed.

## Provider Library Usage

The `PrometheusProvider` object may be used by Prometheus
charms to manage relations with their scrape targets. For this
purposes a Prometheus charm needs to do two things

1. Instantiate the `PrometheusProvider` object providing it
with three key pieces of information

- Name of the relation that the Prometheus charm uses to interact with
  scrape targets. This relation must confirm to the
  `prometheus_scrape` interface.

- A service name. Although this is an arbitrary string, it must be the
  same string that scrape targets will use as the key of their
  `consumes` specification. Hence by convention it is recommended that
  this key be `prometheus`.

- The Prometheus application version. Since a system administrator may
  choose to deploy the Prometheus charm with a non default version of
  Prometheus, it is strongly recommended that the version string be
  determined by actually querying the running instances of
  Prometheus.

For example a Prometheus charm may instantiate the
`PrometheusProvider` in its constructor as follows

    from charms.prometheus_k8s.v0.prometheus import PrometheusProvider

    def __init__(self, *args):
        super().__init__(*args)
        ...
        self.prometheus_provider = PrometheusProvider(
                self, "monitoring", "prometheus", self.version
            )
        ...

2. A Prometheus charm also needs to respond to the
`TargetsChanged` event of the `PrometheusProvider` by adding itself as
and observer for these events, as in

    self.framework.observe(
        self.prometheus_provider.on.targets_changed,
        self._on_scrape_targets_changed,
    )

In responding to the `TargetsChanged` event the Prometheus
charm must update the Prometheus configuration so that any new scrape
targets are added and/or old ones removed from the list of scraped
endpoints. For this purpose the `PrometheusProvider` object
exposes a `jobs()` method that returns a list of scrape jobs. Each
element of this list is the Prometheus scrape configuration for that
job. In order to update the Prometheus configuration, the Prometheus
charm needs to replace the current list of jobs with the list provided
by `jobs()` as follows

    def _on_scrape_targets_changed(self, event):
        ...
        scrape_jobs = self.prometheus_provider.jobs()
        for job in scrape_jobs:
            prometheus_scrape_config.append(job)
        ...

## Relation Data

The Prometheus charm uses application relation data to obtain its list
of scrape targets. For each relation there exists a key `targets` in
application relation data whose value is a list encoded as a JSON
string. Each element of this list provides the address (including
port) of a scrape target. As an example the relation data may be

    "targets": "['10.1.12.115:8080', '10.1.12.116:80']"
"""

import json
import logging
from ops.framework import StoredState, EventSource, EventBase, ObjectEvents
from ops.relation import ProviderBase, ConsumerBase

LIBID = "1234"
LIBAPI = 1
LIBPATCH = 0
logger = logging.getLogger(__name__)


class TargetsChanged(EventBase):
    """Event emitted when Prometheus scrape targets change."""

    def __init__(self, handle, data=None):
        super().__init__(handle)
        self.data = data

    def snapshot(self):
        """Save scrape target information."""
        return {"data": self.data}

    def restore(self, snapshot):
        """Restore scrape target information."""
        self.data = snapshot["data"]


class MonitoringEvents(ObjectEvents):
    """Event descriptor for events raised by `PrometheusProvider`."""

    targets_changed = EventSource(TargetsChanged)


class PrometheusProvider(ProviderBase):
    on = MonitoringEvents()
    _stored = StoredState()

    def __init__(self, charm, name, service, version=None):
        """A Prometheus based Monitoring service provider.

        Args:
            charm: a `CharmBase` instance that manages this
                instance of the Prometheus service.
            name: string name of the relation that is provides the
                Prometheus monitoring service.
            service: string name of service provided. This is used by
                `PrometheusConsumer` to validate this service as
                acceptable. Hence the string name must match one of the
                acceptable service names in the `PrometheusConsumer`s
                `consumes` argument. Typically this string is just "prometheus".
            version: a string providing the semantic version of the Prometheus
                application being provided.
        """
        super().__init__(charm, name, service, version)
        self._charm = charm
        self._stored.set_default(jobs={})
        events = self._charm.on[name]
        self.framework.observe(
            events.relation_changed, self._on_scrape_target_relation_changed
        )
        self.framework.observe(
            events.relation_broken, self._on_scrape_target_relation_broken
        )

    def _on_scrape_target_relation_changed(self, event):
        """Handle changes in related consumers.

        Anytime there are changes in relations between Prometheus
        provider and consumer charms the scrape job config is updated
        and the Prometheus charm is informed, through a
        `TargetsChanged` event. The Prometheus charm can then
        choose to update its scrape configuration.
        """
        if not self._charm.unit.is_leader():
            return

        rel_id = event.relation.id
        data = event.relation.data[event.app]

        targets = json.loads(data.get("targets", "[]"))
        if not targets:
            return

        job_name = data.get("job_name", "")
        unique_name = "juju_{}_{}_{}".format(
            self._charm.model.name, self._charm.app.name, rel_id
        )
        if job_name:
            job_name += "_{}".format(unique_name)
        else:
            job_name = unique_name

        job_config = {"job_name": job_name, "static_configs": [{"targets": targets}]}

        self._stored.jobs["rel_id"] = json.dumps(job_config)
        logger.debug("New job config on relation change : %s", job_config)
        self.on.targets_changed.emit()

    def _on_scrape_target_relation_broken(self, event):
        """Update job config when consumers depart.

        When a Prometheus consumer departs the scrape configuration
        for that consumer is remove from the list of scrape jobs and
        the Prometheus is informed through a `TargetsChanged`
        event.
        """
        if not self._charm.unit.is_leader():
            return

        rel_id = event.relation.id
        try:
            del self._stored.jobs[rel_id]
            self.on.targets_changed.emit()
        except KeyError:
            pass

    def jobs(self):
        """Fetch the list of scrape jobs.

        Returns:

            A list consisting of all the static scrape configurations
            for each related `PrometheusConsumer` that has specified
            its scrape targets.
        """
        scrape_jobs = []
        for job in self._stored.jobs.values():
            scrape_jobs.append(json.loads(job))

        return scrape_jobs


class PrometheusConsumer(ConsumerBase):
    _stored = StoredState()

    def __init__(self, charm, name, consumes, multi=False):
        """Construct a Prometheus charm client.

        The `PrometheusConsumer` object provides an interface
        to Prometheus. This interface supports providing additional
        scrape targets to the Prometheus monitoring service. For
        example suppose a charm's units exposes Prometheus metrics on
        port 8000. This charm may then have its metrics aggregated by
        a related Prometheus charm by instantiating a
        `PrometheusConsumer` object and adding its units as
        scrape endpoints as follows

            self.prometheus = PrometheusConsumer(self, "monitoring", {"prometheus": ">=2.0"})
            self.prometheus.add_endpoint(<ip-address>, port=8000)

        Args:

            charm: a `CharmBase` object that manages this
                `PrometheusConsumer` object. Typically this is
                `self` in the instantiating class.
            name: a string name of the relation between `charm` and
                the Prometheus charmed service.
            consumes: a dictionary of acceptable monitoring service
                providers. The keys of the dictionary are string names
                of monitoring service providers. For prometheus, this
                is typically "prometheus". The values of the
                dictionary are corresponding minimal acceptable
                semantic version specfications for the monitoring
                service.
            multi: an optional (default False) flag to indicate if
                this object must support interaction with multiple
                Prometheus monitoring service providers.

        """
        super().__init__(charm, name, consumes, multi)
        self._charm = charm
        self._relation_name = name
        self._stored.set_default(targets={})
        events = self._charm.on[self._relation_name]
        self.framework.observe(events.relation_joined, self._set_targets)

    def add_endpoint(self, address, port=80, rel_id=None):
        """Add an additional scrape to the Prometheus monitroing service.

        Args:
            address: a string host address (usually IP) of the endpoint that
                that must be monitored by Prometheus.
            port: an optional (default 80) integer providing the port
                on which the scrapped endpoint exposes its Prometheus
                metrics.
            rel_id: an optional integer providing the relation ID for
                the related Prometheus monitoring service
                provider. This is only necessary if the
                `PrometheusConsumer` has been instantiated in
                `multi` mode.
        """
        if rel_id is None:
            rel_id = self.relation_id

        targets = self._stored.targets.get(rel_id, [])
        if address in targets:
            return

        target = address + ":" + str(port)
        targets.append(target)
        self._update_targets(targets, rel_id)

    def remove_endpoint(self, address, port=80, rel_id=None):
        """Remove an endpoint from the list of Prometheus scrape targets.
        Args:
            address: a string host address (usually IP) of the endpoint that
                that must be excluded from being monitored by Prometheus.
            port: an optional (default 80) integer providing the port
                on which the scrapped endpoint exposes its Prometheus
                metrics.
            rel_id: an optional integer providing the relation ID for
                the related Prometheus monitoring service
                provider. This is only necessary if the
                `PrometheusConsumer` has been instantiated in
                `multi` mode.
        """
        if rel_id is None:
            rel_id = self.relation_id

        targets = self._stored.targets.get(rel_id, [])
        target = address + ":" + str(port)
        if target not in targets:
            return

        targets.remove(target)
        self._update_targets(targets, rel_id)

    @property
    def endpoints(self, rel_id=None):
        """Returns a list of Prometheus scrape target endpoints.
        Args:
            rel_id: an optional integer providing the relation ID for
                the related Prometheus monitoring service
                provider. This is only necessary if the
                `PrometheusConsumer` has been instantiated in
                `multi` mode.
        """

        if rel_id is None:
            rel_id = self.relation_id
        return self._stored.targets.get(rel_id, [])

    def _set_targets(self, event):
        """Set the Prometheus scrape targets."""
        rel_id = event.relation.id
        if not self._stored.targets.get(rel_id, []):
            return

        logger.debug("Setting scrape targets : %s", self._stored.targets[rel_id])
        event.relation.data[self._charm.app]["targets"] = json.dumps(
            list(self._stored.targets[rel_id])
        )

    def _update_targets(self, targets, rel_id):
        """Update the Prometheus scrape targets."""
        self._stored.targets[rel_id] = targets
        rel = self.framework.model.get_relation(self._relation_name, rel_id)

        logger.debug("Updating scrape targets to : %s", targets)
        rel.data[self._charm.app]["targets"] = json.dumps(list(targets))
