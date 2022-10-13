# Prometheus Charmed Operator for K8s

## Description

The Prometheus Charmed Operator provides a cluster monitoring solution using
[Prometheus](https://prometheus.io), which is an open source
monitoring system and alerting toolkit.

This repository contains a [Juju](https://juju.is/) Charm for
deploying the monitoring component of Prometheus in a Kubernetes
cluster. An [alerting service](https://charmhub.io/alertmanager-k8s)
for Prometheus is offered through a separate Charm.


## Usage

The Prometheus Operator may be deployed using the Juju command line:

```sh
$ juju deploy prometheus-k8s --trust
```

By default, the Prometheus Operator monitors itself, but it also
accepts additional scrape targets over Juju relations with charms that
support the `prometheus_scrape` interface and preferably use the
Prometheus charm library. This [charm library](lib/charms/prometheus_k8s/v0/prometheus_scrape.py)
provides an `add_endpoint()` method that creates additional scrape
targets. Each scrape target is expected to expose a `/metrics` HTTP
path that exposes its metrics in a Prometheus compatible format. For
example, the
[kube-state-metrics](https://charmhub.io/kube-state-metrics) charm
integrates with the Prometheus K8S charm in a way that allows you
to import metrics about resources in a Kubernetes cluster by doing:

```sh
$ juju deploy kube-state-metrics
$ juju relate kube-state-metrics prometheus-k8s
```

In a similar manner any charm that exposes a scrape target may be
related to the Prometheus charm.

> Note: At present it is expected that all relations that Prometheus is
> part of are within the same Juju model. For cross-model relations,
> please set up a Grafana Agent in the remote model and use `remote_write`
> to get the metrics into Prometheus.

## Dashboard

The Prometheus dashboard may be accessed at a configurable port (default: `9090`)
on the IP address of the Prometheus unit. This unit and
its IP address may be determined using the `juju status` command.


## Use Cases Supported

- Configure scrape targets through Juju relations.
- Configure alerting rules through relations with scrape target charms.
- Enable alert forwarding through a relation with Alertmanager.
- Support metrics visualisation through Grafana.

## OCI Images

This charm by default uses the latest version of the
[ubuntu/prometheus](https://hub.docker.com/r/ubuntu/prometheus) image.
