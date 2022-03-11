# Contributing

## Overview

This documents explains the processes and practices recommended for
contributing enhancements to the Prometheus charm.

- Generally, before developing enhancements to this charm, you should consider
  [opening an issue ](https://github.com/canonical/prometheus-operator) explaining
  your use case.
- If you would like to chat with us about your use-cases or proposed
  implementation, you can reach us at
  [Canonical Mattermost public channel](https://chat.charmhub.io/charmhub/channels/charm-dev)
  or [Discourse](https://discourse.charmhub.io/).
  The primary author of this charm is available on the Mattermost channel as
  `@balbir-thomas`.
- Familiarising yourself with the
  [Charmed Operator Framework](https://juju.is/docs/sdk)
  library will help you a lot when working on new features or bug fixes.
- All enhancements require review before being merged. Code review
  typically examines
  + code quality
  + test coverage
  + user experience for Juju administrators
  this charm.
- Please help us out in ensuring easy to review branches by rebasing
  your pull request branch onto the `main` branch. This also avoids
  merge commits and creates a linear Git commit history.

## Developing

Create and activate a virtualenv with the development requirements:

```bash
$ virtualenv -p python3 venv
$ source venv/bin/activate
```

### Charm Specific Setup

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
$ charmcraft pack
```

### Deploy

There are two ways of deploying the prometheus-k8s operator, with and without
promql-transform.  Deploying the charm without PromQL Transform means you won't
get any Juju topology labels  injected into your alert rule expressions.

#### Without PromQL Transform

```bash
$ juju deploy \
    ./prometheus-k8s_ubuntu-20.04-amd64.charm \
    --resource prometheus-image=ubuntu/prometheus:latest
```

#### With PromQL Transform

Place the binary of your selected promql-transform version in the root of the prometheus-k8s
charm directory. Official binaries are available from the
[promql-transform repository](https://github.com/canonical/promql-transform).

```bash
$ juju deploy \
    ./prometheus-k8s_ubuntu-20.04-amd64.charm \
    --resource prometheus-image=ubuntu/prometheus:latest \
    --resource promql-transform-amd64=./promql-transform
```

or, using a `tox` environment,

```shell
$ tox -e deploy-amd64
```

## Linting
Flake8 and black linters may be run to check charm and test source code using the
command

```bash
tox -e lint
```

## Testing

Unit tests are implemented using the Operator Framework test
[harness](https://ops.readthedocs.io/en/latest/#module-ops.testing). These
tests may executed by doing

```bash
$ tox -e unit
```

It is expected that unit tests should provide at least 80% code coverage.

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
[charm library](lib/charms/prometheus_k8s/v0/prometheus_scrape.py).

### Library Details

The Prometheus charm library facilitates two things

1. For metrics providers to forward configuration such as scrape jobs,
   alert rules and related metadata to the Prometheus charm.
2. For metrics consumers (the Prometheus charm) to assimilate information
   provided by the scrape targets, so that it may be used to configure
   Prometheus.

The Prometheus charm library exposes a consumer and provider object -
`MetricsEndpointConsumer` and `MetricsEndpointProvider` along with the custom
charm event `TargetsChanged` within the `MonitoringEvents` event
descriptor. `MetricsEndpointConsumer` emits the `TargetsChanged` event in
response to relation changed and departed events. It is expected that
the Prometheus charm would respond to these events and regenerate the
Prometheus configuration using information provided by the `jobs()`
and `alerts()` methods of the `MetricsEndpointConsumer`.

The `jobs()` method gathers a list of scrape jobs from all related
scrape target charms, generating a unique job name for each job and associates
Juju topology labels with it. The labeling differs for scrape targets whose
host address was automatically gathered and for addresses that were explicitly
specified.

The `MetricsEndpointProvider` is responsible for forwarding scrape
configuration, scrape target addresses, scrape metadata and alert
rules to the Prometheus provider. In doing so it also ensures that the
alert rules have Juju topology labels and filters injected into
them. The `_set_unit_ip()` methods forwards scrape target host
addresses using unit relation data. The `_set_scrape_metadata()`
method forwards all the other information using application relation
data.

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
  layer is generated using `_command()` method.
- Restarting the workload container or reloading Prometheus
  configuration and setting charm status.

Generation of the Prometheus configuration is split across multiple
functions which are invoked by `_prometheus_config()`.

- `_prometheus_global_config()` generates the global
  configuration. Configuration options are validated using the
  `_is_valid_timespec()` and `_are_valid_labels()`.
- `_alerting_config()` generates configuration related to
  Alertmanager(s), using the Alertmanager charm library.
- `jobs()` and `alerts()` methods of the `MetricsEndpointConsumer`
  object.

## Design Choices

This charm manages a [Prometheus](https://prometheus.io) workload and
in doing so it obtains configuration data through its relations with
other charms. The key design choice here was to ensure that the
structure of this data exchanged closely mirrors the format of
Prometheus' own configuration. This ensures that these relation data
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
