# Prometheus Operator

## Description

The Prometheus Operator provides a cluster monitoring solution using
[Prometheus](https://prometheus.io), which is an open source
monitoring system and alerting toolkit.

This repository contains a [Juju](https://jaas.ai/) Charm for
deploying the monitoring component of Prometheus in a Kubernetes
cluster. The alerting component of prometheus is offered through a
separate Charm.


## Configuration and Usage

By default the Prometheus Operator monitors itself. There are two ways
to provide additional scrape targets to this Prometheus charm.

1. Using Juju the command line configuration option `scrape-config`.
2. Using Juju relations with charms that support the `prometheus`
   interface and preferably use the Prometheus charm library. This
   charm library provides a `add_endpoint()` method to provide
   additional scrape targets to Prometheus over relation data.

## Dashboard

The Prometheus dashboard may be accessed at port 9090 on the IP
address of the Prometheus leader unit. This unit and its IP address
may be determined using the `juju status` command.

## Relations

Currently supported relations are

- [Grafana](https://github.com/canonical/grafana-operator)
- [Alertmanager](https://github.com/canonical/alertmanager-operator)

## OCI Images

This charm by default uses the latest version of the Prometheus
[Docker image](https://registry.hub.docker.com/r/prom/prometheus).

## Contributing

Please see the Juju [SDK docs](https://juju.is/docs/sdk) for guidlines
on developing enhancements to this charm following best practice guidelines.
