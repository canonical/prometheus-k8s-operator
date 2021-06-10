# Prometheus Operator

## Description

The Prometheus Operator provides a cluster monitoring solution using
[Prometheus](https://prometheus.io), which is an open source
monitoring system and alerting toolkit.

This repository contains a [Juju](https://jaas.ai/) Charm for
deploying the monitoring component of Prometheus in a Kubernetes
cluster. The alerting component of prometheus is offered through a
separate Charm.


## Usage

The Prometheus Operator may be deployed using the Juju commandline as
in

    juju deploy prometheus-k8s

By default the Prometheus Operator monitors itself, but it also
accepts additional scrape targets over Juju relations with charms that
support the `prometheus` interface and preferably use the Prometheus
charm library. This charm library provides an `add_endpoint()` method
that creates additional scrape targets. Each scrape target is expected
to expose a `/metrics` HTTP path that exposes its metrics in a
Prometheus compatible format.

At present it is expected that all relations the Prometheus Operator
partakes in are within the same Juju model. Further development may
extend this to allow cross model scrape targets.

## Dashboard

The Prometheus dashboard may be accessed at a selectable port (by
default 9090) on the IP address of the Prometheus unit. This unit and
its IP address may be determined using the `juju status` command.

## Relations

Currently supported relations are

- [Grafana](https://github.com/canonical/grafana-operator)
- [Alertmanager](https://github.com/canonical/alertmanager-operator)

## OCI Images

This charm by default uses the latest version of the Prometheus
[Docker image](https://registry.hub.docker.com/r/prom/prometheus).

## Contributing

Please see the Juju [SDK docs](https://juju.is/docs/sdk) for guidelines
on developing enhancements to this charm following best practice guidelines.
