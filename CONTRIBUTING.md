# Contributing

## Overview

This documents explains the processes and practices recommended for
contributing enhancements to the Prometheus Charmed Operator.

- Generally, before developing enhancements to this charm, you should consider
  [opening an issue ](https://github.com/canonical/prometheus-operator) explaining
  your use case.
- If you would like to chat with us about your use-cases or proposed
  implementation, you can reach us at
  [Canonical Mattermost public channel](https://chat.charmhub.io/charmhub/channels/charm-dev)
  or [Discourse](https://discourse.charmhub.io/).
- Familiarising yourself with the
  [Charmed Operator Framework](https://juju.is/docs/sdk)
  library will help you a lot when working on new features or bug fixes.
- All enhancements require review before being merged. Code review
  typically examines
  + code quality
  + test coverage
  + user experience for Juju administrators.
- Please help us out in ensuring easy to review branches by rebasing
  your pull request branch onto the `main` branch. This also avoids merge commits and creates a linear Git commit history.


## Setup

A typical development setup for charms created with the [Charmed Operator Framework](https://juju.is/docs/sdk) contains:


- [Charmcraft](https://github.com/canonical/charmcraft) - Developer tooling for creating, building and publishing Charmed Operators
- [Juju](https://juju.is/) - a Charmed Operator Lifecycle Manager (OLM), used for deploying and managing operators
- [Multipass](https://multipass.run/) - a lightweight Ubuntu virtual machine manager (optional)
- [MicroK8s](https://microk8s.io/) - a low-ops Kubernetes distribution we’ll use for testing our Charmed Operator (optional if developing a Charmed Operator for Kubernetes)

Please [follow this guide](https://juju.is/docs/sdk/dev-setup) which will walk through the installation of these tools to get you started with charm development.


### Testing

All default tests can be executed by running `tox` without arguments.

You can also manually run specific test environment:

```bash
tox -e lint         # check your code complies to linting rules
tox -e static       # run static analysis
tox -e unit         # run unit tests
tox -e integration  # run integration tests
tox -e fmt          # update your code according to linting rules
```

Unit tests are written with the Operator Framework [test harness](https://ops.readthedocs.io/en/latest/#module-ops.testing).


### Build

In order to pack the charm locally so it could be deployed from a local path we use
[charmcraft](https://juju.is/docs/sdk/setting-up-charmcraft).

From the charm's root folder:

```bash
$ charmcraft pack
Packing the charm
Created 'prometheus-k8s_ubuntu-20.04-amd64.charm'.
Charms packed:
    prometheus-k8s_ubuntu-20.04-amd64.charm
```


### Deploy

```bash
$ juju deploy --trust \
    ./prometheus-k8s_ubuntu-20.04-amd64.charm \
    --resource prometheus-image=ubuntu/prometheus:latest
```



## Code Overview

The core implementation of this charm is represented by the
[`PrometheusCharm`](src/charm.py) class. `PrometheusCharm` responds to

- [Pebble](https://github.com/canonical/pebble/) ready
- configuration changes,
- charm upgrade
- changes in relations with [Alertmanager](https://github.com/canonical/alertmanager-k8s-operator)
- changes in relations with [Grafana](https://github.com/canonical/grafana-k8s-operator)
- chamges in relation with [Traefik](https://github.com/canonical/traefik-k8s-operator) (Ingress)
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
