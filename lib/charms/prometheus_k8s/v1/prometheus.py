"""## Overview

This document explains how to integrate with the Prometheus charm
for the purposes of providing a metrics endpoint to Prometheus. It
also explains how alternative implementations of the Prometheus charm
may maintain the same interface and be backward compatible with all
currently integrated charms. Finally this document is the
authoritative reference on the structure of relation data that is
shared between Prometheus charms and any other charm that intends to
provide a scrape target for Prometheus.

## Consumer Library Usage

This Prometheus charm interacts with its scrape targets using its
charm library. This charm library is constructed using the [Provider
and
Consumer](https://ops.readthedocs.io/en/latest/#module-ops.relation)
objects from the Operator Framework. This implies charms that would
like to expose metric endpoints for the Prometheus charm must use the
`PrometheusConsumer` object from the charm library to do so. Using the
`PrometheusConsumer` object requires instantiating it, typically in
the constructor of your charm (the one which exposes the metrics
endpoint). The `PrometheusConsumer` constructor requires the name of
the relation over which a scrape target (metrics endpoint) is exposed
to the Promtheus charm. This relation must use the `prometheus_scrape`
interface. The address of the metrics endpoint is set to the unit
address, by each unit of the consumer charm. Hence instantiating the
consumer also requires providing it the Pebble service name of the
consumer. In addition the constructor also requires a `consumes`
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

An instantiated `PrometheusConsumer` object will ensure that each unit
of the consumer charm, is a scrape target for the
`PrometheusProvider`. By default `PrometheusConsumer` assumes each
unit of the consumer charm exports its metrics at a path given by
`/metrics` on port 80. This is the default behaviour off most
Prometheus metrics exporters so typically the defaults do not need to
be changed. However if required the defaults may be changed by
providing the `PrometheusConsumer` constructor an optional argument
(`config`) that represents its configuration in Python dictionary
format.

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
of scrape targets. This relation data is in JSON format and it closely
resembles the YAML structure of Prometheus [scrape configuration]
(https://prometheus.io/docs/prometheus/latest/configuration/configuration/#scrape_config).
"""

import json
import logging
from ops.framework import EventSource, EventBase, ObjectEvents
from ops.relation import ProviderBase, ConsumerBase

LIBID = "1234"
LIBAPI = 1
LIBPATCH = 0
logger = logging.getLogger(__name__)


class TargetsChanged(EventBase):
    """Event emitted when Prometheus scrape targets change."""

    def __init__(self, handle, relation_id):
        super().__init__(handle)
        self.relation_id = relation_id

    def snapshot(self):
        """Save scrape target relation information."""
        return {"relation_id": self.relation_id}

    def restore(self, snapshot):
        """Restore scrape target relation information."""
        self.relation_id = snapshot["relation_id"]


class MonitoringEvents(ObjectEvents):
    """Event descriptor for events raised by `PrometheusProvider`."""

    targets_changed = EventSource(TargetsChanged)


class PrometheusProvider(ProviderBase):
    on = MonitoringEvents()

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
        self._relation_name = name
        events = self._charm.on[name]
        self.framework.observe(
            events.relation_changed, self._on_scrape_target_relation_changed
        )
        self.framework.observe(
            events.relation_departed, self._on_scrape_target_relation_departed
        )

    def _on_scrape_target_relation_changed(self, event):
        """Handle changes in related consumers.

        Anytime there are changes in relations between Prometheus
        provider and consumer charms the Prometheus charm is informed,
        through a `TargetsChanged` event. The Prometheus charm can
        then choose to update its scrape configuration.
        """
        rel_id = event.relation.id

        self.on.targets_changed.emit(relation_id=rel_id)

    def _on_scrape_target_relation_departed(self, event):
        """Update job config when consumers depart.

        When a Prometheus consumer departs the scrape configuration
        for that consumer is removed from the list of scrape jobs and
        the Prometheus is informed through a `TargetsChanged`
        event.
        """
        rel_id = event.relation.id
        self.on.targets_changed.emit(relation_id=rel_id)

    def jobs(self):
        """Fetch the list of scrape jobs.

        Returns:

            A list consisting of all the static scrape configurations
            for each related `PrometheusConsumer` that has specified
            its scrape targets.
        """
        scrape_jobs = []

        for relation in self._charm.model.relations[self._relation_name]:
            job = self._static_scrape_config(relation)
            if job:
                scrape_jobs.append(job)

        return scrape_jobs

    def _static_scrape_config(self, relation):
        """Generate the static scrape configuration for a relation.

        Args:
            relation: an `ops.model.Relation` object whose static
                scrape configuration is required.

        Returns:
            A static scrape configuration for a specific relation.
        """
        scrape_metadata = json.loads(
            relation.data[relation.app].get("prometheus_scrape_metadata")
        )

        if not scrape_metadata:
            return None

        job_name = "juju_prometheus_scrape_{}_{}_{}".format(
            scrape_metadata["model"], scrape_metadata["application"], relation.id
        )

        hosts = {}
        for unit in relation.units:
            host_address = relation.data[unit].get("prometheus_scrape_host")
            if not host_address:
                continue
            hosts[unit.name] = host_address

        scrape_config = {
            "job_name": job_name,
            "metrics_path": scrape_metadata["static_scrape_path"],
            "static_configs": [],
        }

        for host_name, host_address in hosts.items():
            metrics_url = "{}:{}".format(
                host_address, scrape_metadata["static_scrape_port"]
            )

            config = {
                "targets": [metrics_url],
                "labels": {
                    "juju_model": "{}".format(scrape_metadata["model"]),
                    "juju_model_uuid": "{}".format(scrape_metadata["model_uuid"]),
                    "juju_application": "{}".format(scrape_metadata["application"]),
                    "juju_unit": "{}".format(host_name),
                },
            }
            scrape_config["static_configs"].append(config)

        return scrape_config


class PrometheusConsumer(ConsumerBase):
    def __init__(self, charm, name, consumes, service, config={}, multi=False):
        """Construct a Prometheus charm client.

        The `PrometheusConsumer` object provides an interface to
        Prometheus. Any charm instantiating this object has metrics
        from each of its units aggregated by a related Prometheus
        charm
            self.prometheus = PrometheusConsumer(self, "monitoring", {"prometheus": ">=2.0"})
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
            service: string name of Pebble service of consumer charm.
            config: a optional dictionary with keys that are
                Prometheus scrape configuration options, for example
                metrics path and port.
            multi: an optional (default False) flag to indicate if
                this object must support interaction with multiple
                Prometheus monitoring service providers.
        """
        super().__init__(charm, name, consumes, multi)

        self._charm = charm
        self._service = service
        self._relation_name = name
        self._static_scrape_port = config.get("static_scrape_port", 80)
        self._static_scrape_path = config.get("static_scrape_path", "/metrics")
        self._multi_mode = multi

        events = self._charm.on[self._relation_name]
        self.framework.observe(events.relation_joined, self._set_scrape_metadata)
        self.framework.observe(
            self._charm.on[self._service].pebble_ready, self._set_unit_ip
        )

    def _set_scrape_metadata(self, event):
        """Ensure scrape targets metadata is made available to Prometheus.

        When a consumer charm is related to a Prometheus provider, the
        consumer sets metadata related to its own scrape
        configutation.  This metadata is set using Juju application
        data.  In addition each of the consumer units also sets its own
        host address in Juju unit relation data.
        """
        event.relation.data[self._charm.unit]["prometheus_scrape_host"] = str(
            self._charm.model.get_binding(event.relation).network.bind_address
        )

        if not self._charm.unit.is_leader():
            return

        event.relation.data[self._charm.app]["prometheus_scrape_metadata"] = json.dumps(
            self._scrape_metadata
        )

    def _set_unit_ip(self, event):
        """Set unit host address

        Each time a consumer charm container is restarted it updates its own
        host address in the unit relation data for the Prometheus provider.
        """
        for relation in self._charm.model.relations[self._relation_name]:
            relation.data[self._charm.unit]["prometheus_scrape_host"] = str(
                self._charm.model.get_binding(relation).network.bind_address
            )

    @property
    def _scrape_metadata(self):
        """Generate scrape metadata.

        Returns:
            Scrape configutation metadata for this Prometheus consumer charm.
        """
        metadata = {
            "model": "{}".format(self._charm.model.name),
            "model_uuid": "{}".format(self._charm.model.uuid),
            "application": "{}".format(self._charm.model.app.name),
            "static_scrape_port": self._static_scrape_port,
            "static_scrape_path": self._static_scrape_path,
        }
        return metadata
