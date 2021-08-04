# Overview

This documents explains the processes and practices recommended for
contributing enhancements to the Prometheus charm.

- Generally, before developing enhancements to this charm, you should consider
  [opening an issue ](https://github.com/canonical/prometheus-operator) explaining
  your use case.
- If you would like to chat with us about your use-cases or proposed
  implementation, you can reach us at
  [Canonical Mattermost public channel](https://chat.charmhub.io/charmhub/channels/charm-dev)
  or [Discourse](https://discourse.charmhub.io/).
- It is strongly recommended that prior to engaging in any enhancements
  to this charm you familiarise your self with Juju.
- Familiarising yourself with the
  [Charmed Operator Framework](https://juju.is/docs/sdk)
  library will help you a lot when working on PRs.
- All enhancements require review before being merged. Besides the
  code quality and test coverage, the review will also take into
  account the resulting user experience for Juju administrators using
  this charm. Please help us out in having easier reviews by rebasing
  onto the `main` branch, avoid merge commits and enjoy a linear Git
  history.

## Developing

Create and activate a virtualenv with the development requirements:

```bash
$ virtualenv -p python3 venv
$ source venv/bin/activate
$ pip install -r requirements-dev.txt
```

### Setup

A typical setup using [Snap](https://snapcraft.io/), for deployments
to a [microk8s](https://microk8s.io/) cluster can be achieved by
following instructions in the Juju SDK
[development setup](https://juju.is/docs/sdk/dev-setup).

It is also essential that a Juju storage pool is created as follows

```bash
$ juju create-storage-pool operator-storage kubernetes storage-class=microk8s-hostpath
```

### Build

Build the charm in this git repository

```bash
$ charmcraft build
```

### Deploy

```bash
$ juju deploy ./prometheus-k8s.charm --resource prometheus-image=ubuntu/prometheus:latest
```

## Testing

Unit tests are implemented using the Operator Framework test
[harness](https://ops.readthedocs.io/en/latest/#module-ops.testing). These
tests may executed by doing

```bash
$ ./run_tests
```

## Code Overview

The core implementation of this charm is represented by the
[`PrometheusCharm`](src/charm.py) class. `PrometheusCharm` responds to

- configuration changes,
- changes in relations with Alertmanager,
- changes in relations with Grafana
- changes in relations with any scrape target.

In response to any change in its configuration, relations with
Alertmanager or scrape target, `PrometheusCharm` regenerates its
config file, and restarts itself.

In response to a change in relation with Grafana `PrometheusCharm`
provides Grafana its own address and port. `PrometheusCharm` also
validates all configurations options when provided before generating
its config file.

The `PrometheusCharm` object interacts with its scrape targets using a
[charm library](lib/charms/prometheus_k8s/v1/prometheus.py). Using this
library requires that Prometheus informs its "Consumers" (scrape targets)
of the actual Prometheus version that was deployed. In order to determine
this version at runtime `PrometheuCharm` uses the
[`Prometheus`](src/prometheus_server.py) object. The `Prometheus`
object provides an interface to a running Prometheus instance. This
interface is limited to only those aspects of Prometheus required by
this charm.

### Library Details

The Prometheus charm library exposes a provider and consumer object -
`PrometheusProvider` and `PrometheusConsumer` along with the custom
charm event `TargetsChanged` within the `MonitoringEvents` event
descriptor. `PrometheusProvider` emits the `TargetsChagned` event in
response to relation changed and departed events. It is expected that
the provider charm would respond to this event and regenerate the
Prometheus configuration using information provided by the `jobs()`
and `alerts()` methods of the `PrometheusProvider`.

The `jobs()` method gathers a list of scrape jobs from all related
consumer charms. In doing so it invokes the `_static_scrape_config()`
method for each such relation. `_static_scrape_config()` generates a
unique job name for each job, sanitizes the job and associates Juju
topology labels with it. Labeling of Juju topology is done by
`_labeled_static_job_config()`. However the labeling differs for
scrape targets whose host address was automatically gathered and those
addresses were explicitly specified. Hence three separate
functions are required for labeling `_set_juju_labels()` for labels
common to both but `_labeled_unitless_config()` and
`_labeled_unit_config()` for the differing labels. The list of
automatically gathered host address is provided by
`_relation_hosts()`.

The `PrometheusConsumer` is responsible for forwarding scrape
configuration, scrape target addresses, scrape metadata and alert
rules to the Prometheus provider. In doing so it also ensures that the
alert rules have Juju topology labels and filters injected into
them. The `_set_unit_ip()` methods forwards scrape target host
addresses using unit relation data. The `_set_scrape_metadata()`
method forwards all the other information using application relation
data. The list of scrape jobs is gathered by the `_scrape_jobs()`
method and Juju topology information is constructed using the
`_scrape_metadata()` method. Finally `_labeled_alert_groups()` loads
alert rules from files and ensures they include Juju topology labels
and filters respectively by invoking `_label_alert_topology()` and
`_label_alert_expression()`.

### Charm Details

The primary way in which the Prometheus charm responds to various
events is by re-configuring itself through an invocation of the
`_configure()` method. This method is responsible for

- Pushing a new Prometheus configuration generated using
  `_prometheus_config()`.
- Pushing alert rule files into the Prometheus container using
  `_set_alerts()`.
- Pushing the Pebble layer configuration generated using
  `_prometheus_layer()`. The Prometheus command line in this Pebble
  layer is generated using `_command()` and `_cli_args()`.
- Restarting the workload container and setting charm status.

Generation of the Prometheus configuration is split across multiple
functions which are invoked by `_prometheus_config()`.

- `_prometheus_global_config()` generates the global
  configuration. Configuration options are validated using the
  `_is_valid_timespec()` and `_are_valid_labels()`.
- `_alerting_config()` generates configuration related to
  Alertmanager(s), using the Alertmanager charm library.
- `jobs()` and `alerts()` methods of the `PrometheusProvider`
  object.

## Design Choices

This charm manages a [Prometheus](https://prometheus.io) workload and
in doing so it obtains configuration data through its relations with
other charms. The key design choice here was to ensure that the
structure of this data exchanged closely mirrors the format of
Prometheus' own configuration. This ensures that these relational data
structures are at least as extensible as Prometheus' own
configuration. Besides, these data structure would already be familiar
to Prometheus domain experts.

This Prometheus charm does not support peer relations because as yet
there is no visible use case for it. In the future should there be a
use case for
[federation](https://prometheus.io/docs/prometheus/latest/federation/),
it may be enabled through the use of peer relations. As a result of
this decision scaling Prometheus units only results in replication.
Replicating units will lead to the standard Prometheus "share-nothing"
replication, in which all units independently scrape all
targets. However Prometheus scaling is as yet
[untested](https://github.com/canonical/prometheus-operator/issues/59)
and hence must be used with caution.

## Use Cases

- Configure scrape targets through Juju relations.
- Configure alerting rules through relations with scrape target charms.
- Enable alert forwarding through a relation with Alertmanager.
- Support metrics visualisation through Grafana.

