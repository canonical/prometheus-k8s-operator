# Overview

This documents explains the processes and practices recommended for
contributing enhancements to the Prometheus charm.

- It is recommended that prior to developing enhancements to this charm
  an issue explaining the use case is created at the official
  Canonical [github repository](https://github.com/canonical/prometheus-operator).
- Should you require any assistance in exploring use cases or
  discussing proposed implementation you may directly engage with
  other developers in the Canonical
  [public channel](https://chat.charmhub.io/charmhub/channels/charm-dev) using
  [Mattermost](https://mattermost.com/).
- It is strongly recommended that prior to engaging in any enhancements
  to this charm you familiarise your self with the Juju
  [SDK](https://juju.is/docs/sdk) and
  [Operator Framework](https://ops.readthedocs.io/en/latest/) documentation.
- All enhancements require a code review after creating a pull request
  on Github. Pull requests may be merged after two approving reviews
  are obtained. It is strongly recommended to maintain pull requests
  rebased onto latest `main` branch so that merge commits are avoided
  and this repository retains a linear commit history.

## Developing

Create and activate a virtualenv with the development requirements:

```bash
$ virtualenv -p python3 venv
$ source venv/bin/activate
$ pip install -r requirements-dev.txt
```

### Setup

A typical setup using [snaps](https://snapcraft.io/), for deployments
to a [microk8s](https://microk8s.io/) cluster can be done using the
following commands

```bash
$ sudo snap install microk8s --classic
$ microk8s.enable dns
$ sudo snap install juju --classic
$ juju bootstrap microk8s microk8s
$ juju create-storage-pool operator-storage kubernetes storage-class=microk8s-hostpath
```

### Build

Install the charmcraft tool

```bash
$ sudo snap install charmcraft
```

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
configuation changes, changes in relations with Alertmanager, Grafana
and any scrape target. In response to any change in its configuration,
relations with Alertmanager or scrape target, `PrometheusCharm`
regenerates its config file, and restarts itself. In response to a
change in relation with Grafana `PrometheusCharm` provides Grafana its
own address and port. `PrometheusCharm` also validates most
configurations options when provided before generating its config file.

The `PrometheusCharm` object interacts with its scrape targets using a
[charm library](INTEGRATION.md). Using this library requires that
Prometheus informs it "Consumers" (scrape targets) of the actual
Prometheus version that was deployed. In order to determine this
version at runtime `PrometheuCharm` uses the
[`Prometheus`](src/prometheus_server.py) object. The `Prometheus`
object provides an interface to a running Prometheus instance. This
interface is limited to only those aspects of Prometheus required by
this charm.

## Design Choices

This Prometheus charm does not support peer relations because as yet
there is no visible use case for it. In the future should there be a
use case for
[federation](https://prometheus.io/docs/prometheus/latest/federation/),
it may be enabled through the use of peer relations. As a result of
this decision scaling Prometheus units only results in replication. By
"replication" it is meant that each Prometheus unit will scrape exactly
the same targets in the same way and interact with related charms
identically. However Prometheus scaling is as yet
[untested](https://github.com/canonical/prometheus-operator/issues/59)
and hence must be used with caution.

## Use Cases

- Configure a new scrape target by adding a relation.
- Enable alerting through a relation with Alertmanager.
- Support metrics visualisation through Grafana.

## Road Map

- Enhance configurability of scrape targets.
- Enhance configurability of alerts.
- Support aggregation using [Cortex](https://cortexmetrics.io/).
- Support aggregation using [Loki](https://grafana.com/oss/loki/).
