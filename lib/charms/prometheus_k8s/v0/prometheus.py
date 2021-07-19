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
objects from the Operator Framework. This implies charms seeking to
expose a metric endpoints for the Prometheus charm, must do so using
the `PrometheusConsumer` object from this charm library. For the
simplest use case using the `PrometheusConsumer` object only requires
instantiating it, typically in the constructor of your charm (the one
which exposes the metrics endpoint). The `PrometheusConsumer`
constructor requires the name of the relation over which a scrape
target (metrics endpoint) is exposed to the Prometheus charm. This is
relation that must use the `prometheus_scrape` interface. The address
of the metrics endpoint is set to the unit address, by each unit of
the consumer charm. These units set their address in response to a
`CharmEvent`. Hence instantiating the `PrometheusConsumer` also requires
a `CharmEvent` object in response to which each unit will post its address
into the unit's relation data for the Prometheus charm. In addition the
constructor also requires a `consumes` specification, which is a
dictionary with key `prometheus` (also see Provider Library Usage
below) and a value that represents the minimum acceptable version of
Prometheus. This version string can be in any format that is
compatible with Python [Semantic Version
module](https://pypi.org/project/semantic-version/).  For example,
assuming your charm exposes a metrics endpoint over a relation named
"monitoring", you may instantiate `PrometheusConsumer` as follows

    from charms.prometheus_k8s.v0.prometheus import PrometheusConsumer

    def __init__(self, *args):
        super().__init__(*args)
        ...
        self.prometheus = PrometheusConsumer(self, "monitoring",
                                             {"prometheus": ">=2.0"},
                                             self.on.my_service_pebble_ready)
        ...

In this example `my_service_pebble_ready` is the `PebbleReady` event
in response to which each unit will advertise its address. Also this
example hard codes the consumes dictionary argument containing the
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
`/metrics` on port 80. The defaults may be changed by
providing the `PrometheusConsumer` constructor an optional argument
(`jobs`) that represents list of Prometheus scrape job specification
using Python standard data structures. This job specification is a
subset of Prometheus' own [scrape
configuration](https://prometheus.io/docs/prometheus/latest/configuration/configuration/#scrape_config)
format but represented using Python data structures. More than one job
may be provided using the `jobs` argument. Hence `jobs` accepts a list
of dictionaries where each dictionary represents one `<scrape_config>`
object as described in the Prometheus documentation. The current supported
configuration subset is:
* `job_name`
* `metrics_path`
* `static_configs`

Suppose it is required to change the port on which scraped metrics are
exposed to 8000. This may be done by providing the following data
structure as the value of `jobs`.

```
[
    {
        "static_configs": [
            {
                "targets": ["*:8000"]
            }
        ]
    }
]
```

The wildcard ("*") host specification implies that the scrape targets
will automatically be set to the host addresses advertised by each
unit of the consumer charm.

It is also possible to change the metrics path and scrape multiple
ports, for example

```
[
    {
        "metrics_path": "/my-metrics-path",
        "static_configs": [
            {
                "targets": ["*:8000", "*:8081"],
            }
        ]
    }
]
```

More complex scrape configurations are possible. For example

```
[
    {
        "static_configs": [
            {
                "targets": ["10.1.32.215:7000", "*:8000"],
                "labels": {
                    "some-key": "some-value"
                }
            }
        ]
    }
]
```

This example scrapes the target "10.1.32.215" at port 7000 in addition
to scraping each unit at port 8000. There is however one difference
between wildcard targets (specified using "*") and fully qualified
targets (such as "10.1.32.215"). The Prometheus charm automatically
associates labels with metrics generated by each target. These labels
localise the source of metrics within the Juju topology by specifying
its "model name", "model UUID", "application name" and "unit
name". However unit name is associated only with wildcard targets but
not with fully qualified targets.

Multiple jobs with different metrics paths and labels are allowed, but
each job must be given a unique name. For example

```
[
    {
        "job_name": "my-first-job",
        "metrics_path": "one-path",
        "static_configs": [
            {
                "targets": ["*:7000"],
                "labels": {
                    "some-key": "some-value"
                }
            }
        ]
    },
    {
        "job_name": "my-second-job",
        "metrics_path": "another-path",
        "static_configs": [
            {
                "targets": ["*:8000"],
                "labels": {
                    "some-other-key": "some-other-value"
                }
            }
        ]
    }
]
```

It is also possible to configure other scrape related parameters using
these job specifications as described by the Prometheus
[documentation](https://prometheus.io/docs/prometheus/latest/configuration/configuration/#scrape_config).

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

The Prometheus charm uses both application and unit relation data to
obtain information regarding its scrape jobs and scrape targets. This
relation data is in JSON format and it closely resembles the YAML
structure of Prometheus [scrape configuration]
(https://prometheus.io/docs/prometheus/latest/configuration/configuration/#scrape_config).

Units of consumer charm advertise their address over unit relation
data using the `prometheus_scrape_host` key. While the
`scrape_metadata` and `scrape_jobs` keys in application relation data
provide eponymous information.
"""

import json
import logging
from ops.framework import EventSource, EventBase, ObjectEvents
from ops.relation import ProviderBase, ConsumerBase

# The unique Charmhub library identifier, never change it
LIBID = "bc84295fef5f4049878f07b131968ee2"

# Increment this major API version when introducing breaking changes
LIBAPI = 0

# Increment this PATCH version before using `charmcraft publish-lib` or reset
# to 0 if you are raising the major API version
LIBPATCH = 1

logger = logging.getLogger(__name__)


def _sanitize_scrape_configuration(job):
    return {
        "job_name": job.get("job_name"),
        "metrics_path": job.get("metrics_path"),
        "static_configs": job.get("static_configs"),
    }


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
            static_scrape_jobs = self._static_scrape_config(relation)
            if static_scrape_jobs:
                scrape_jobs.extend(static_scrape_jobs)

        return scrape_jobs

    def _static_scrape_config(self, relation):
        """Generate the static scrape configuration for a single relation.

        Args:
            relation: an `ops.model.Relation` object whose static
                scrape configuration is required.

        Returns:

            A list (possibly empty) of scrape jobs. Each job is a
            valid Prometheus scrape configuration for that job,
            represented as a Python dictionary.
        """
        if len(relation.units) == 0:
            return []

        scrape_jobs = json.loads(relation.data[relation.app].get("scrape_jobs", "[]"))

        if not scrape_jobs:
            return []

        scrape_metadata = json.loads(relation.data[relation.app].get("scrape_metadata"))

        job_name_prefix = "juju_{}_{}_{}_prometheus_{}_scrape".format(
            scrape_metadata["model"],
            scrape_metadata["model_uuid"][:7],
            scrape_metadata["application"],
            relation.id,
        )

        hosts = self._relation_hosts(relation)

        labeled_job_configs = []
        for job in scrape_jobs:
            config = self._labeled_static_job_config(
                _sanitize_scrape_configuration(job),
                job_name_prefix,
                hosts,
                scrape_metadata,
            )
            labeled_job_configs.append(config)

        return labeled_job_configs

    def _relation_hosts(self, relation):
        """Fetch host names and address of all consumer units for a single relation.

        Args:

            relation: An `ops.model.Relation` object for which the host name to
                address mapping is required.

        Returns:

            A dictionary that maps unit names to unit addresses for
            the specified relation.
        """
        hosts = {}
        for unit in relation.units:
            host_address = relation.data[unit].get("prometheus_scrape_host")
            if not host_address:
                continue
            hosts[unit.name] = host_address
        return hosts

    def _labeled_static_job_config(self, job, job_name_prefix, hosts, scrape_metadata):
        """Construct labeled job configuration for a single job.

        Args:

            job: a dictionary representing the job configuration as obtained from
                `PrometheusConsumer` over relation data.
            job_name_prefix: a string that may either be used as the
                job name if none is provided or used as a prefix for
                the provided job name.
            hosts: a dictionary mapping host names to host address for
                all units of the relation for which this job configuration
                must be constructed.
            scrape_metadata: scrape configuration metadata obtained
                from `PrometheusConsumer` from the same relation for
                which this job configuration is being constructed.

        Returns:

            A dictionary representing a Prometheus job configuration
            for a single job.
        """
        name = job.get("job_name")
        job_name = "job_name_prefix_{}".format(name) if name else job_name_prefix

        config = {"job_name": job_name}

        static_configs = job.get("static_configs")
        config["static_configs"] = []

        for static_config in static_configs:
            labels = static_config.get("labels", {}) if static_configs else {}
            all_targets = static_config.get("targets", [])

            ports = []
            unitless_targets = []
            for target in all_targets:
                host, port = target.split(":")
                if host.strip() == "*":
                    ports.append(port.strip())
                else:
                    unitless_targets.append(target)

            if unitless_targets:
                unitless_config = self._labeled_unitless_config(
                    unitless_targets, labels, scrape_metadata
                )
                config["static_configs"].append(unitless_config)

            for host_name, host_address in hosts.items():
                static_config = self._labeled_unit_config(
                    host_name, host_address, ports, labels, scrape_metadata
                )
                config["static_configs"].append(static_config)

        return config

    def _set_juju_labels(self, labels, scrape_metadata):
        """Create a copy of metric labels with Juju topology information.

        Args:

            labels: a dictionary containing Prometheus metric labels.
            scrape_metadata: scrape related metadata provied by
                `PrometheusConsumer`.

        Returns:

            a copy of the `labels` dictionary augmented with Juju
            topology information with the exception of unit name.
        """
        juju_labels = labels.copy()  # deep copy not needed
        juju_labels["juju_model"] = "{}".format(scrape_metadata["model"])
        juju_labels["juju_model_uuid"] = "{}".format(scrape_metadata["model_uuid"])
        juju_labels["juju_application"] = "{}".format(scrape_metadata["application"])

        return juju_labels

    def _labeled_unitless_config(self, targets, labels, scrape_metadata):
        """Static scrape configuration for fully qualified host addresses.

        Fully qualified hosts are those scrape targets for which the
        address are not automatically determined by
        `PrometheusProvider` but instead are specified by the client
        of `PrometheusConsumer`.

        Args:

            targets: a list of addresses of fully qualified hosts.
            labels: labels specified by `PrometheusConsumer` clients
                 which are associated with `targets`.
            scrape_metadata: scrape related metadata provied by `PrometheusConsumer`.

        Returns:

            A dictionary containing the static scrape configuration
            for a list of fully qualified hosts.
        """
        juju_labels = self._set_juju_labels(labels, scrape_metadata)
        unitless_config = {"targets": targets, "labels": juju_labels}
        return unitless_config

    def _labeled_unit_config(
        self, host_name, host_address, ports, labels, scrape_metadata
    ):
        """Static scrape configuration for a wildcard host.

        Wildcard hosts are those scrape targets whose address is
        automatically determined by `PrometheusProvider`.

        Args:

            host_name: a string representing the unit name of the wildcard host.
            host_address: a string representing the address of the wildcard host.
            ports: list of ports on which this wildcard host exposes its metrics.
            labels: a dictionary of labels provided by
                `PrometheusConsumer` intended to be associated with
                this wildcard host.
            scrape_metadata: scrape related metadata provied by `PrometheusConsumer`.

        Returns:

            A dictionary containing the static scrape configuration
            for a single wildcard host.
        """
        juju_labels = self._set_juju_labels(labels, scrape_metadata)
        juju_labels["juju_unit"] = "{}".format(host_name)

        static_config = {"labels": juju_labels}

        if ports:
            targets = []
            for port in ports:
                targets.append("{}:{}".format(host_address, port))
            static_config["targets"] = targets
        else:
            static_config["targets"] = [host_address]

        return static_config


class PrometheusConsumer(ConsumerBase):
    def __init__(self, charm, name, consumes, service_event, jobs=[], multi=False):
        """Construct a Prometheus charm client.

        The `PrometheusConsumer` object provides scrape configurations
        to a Prometheus charm. A charm instantiating this object has
        metrics from each of its units scraped by the related Prometheus
        charms. The scraped metrics are automatically tagged by the
        Prometheus charms with Juju topology data via the
        `juju_model_name`, `juju_model_uuid`, `juju_application_name`
        and `juju_unit` labels.

        The `PrometheusConsumer` can be instantiated as follows:

            self.prometheus = PrometheusConsumer(self, "monitoring",
                                                 {"prometheus": ">=2.0"}
                                                 self.my_service_pebble_ready)
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
            service: a `CharmEvent` in response to which each unit
                must advertise its address.
            jobs: an optional list of dictionaries where each
                dictionary represents the Prometheus scrape
                configuration for a single job. When not provided, a
                default scrape configuration is provided for the
                `/metrics` endpoint pooling using port `80`.
            multi: an optional (default False) flag to indicate if
                this object must support interaction with multiple
                Prometheus monitoring service providers.

        """
        super().__init__(charm, name, consumes, multi)

        self._charm = charm
        self._service_event = service_event
        self._relation_name = name
        # Sanitize job configurations to the supported subset of parameters
        self._jobs = [_sanitize_scrape_configuration(job) for job in jobs]
        self._multi_mode = multi

        events = self._charm.on[self._relation_name]
        self.framework.observe(events.relation_joined, self._set_scrape_metadata)
        self.framework.observe(self._service_event, self._set_unit_ip)

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

        event.relation.data[self._charm.app]["scrape_metadata"] = json.dumps(
            self._scrape_metadata
        )
        event.relation.data[self._charm.app]["scrape_jobs"] = json.dumps(
            self._scrape_jobs
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
    def _scrape_jobs(self):
        """Fetch list of scrape jobs.

        Returns:

           A list of dictionaries, where each dictionary specifies a
           single scrape job for Prometheus.
        """
        default_job = [{"metrics_path": "/metrics"}]
        return self._jobs if self._jobs else default_job

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
        }
        return metadata
