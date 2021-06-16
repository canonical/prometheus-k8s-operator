# Prometheus Operator

## Description

The Prometheus Operator provides a cluster monitoring solution using
[Prometheus](https://prometheus.io), which is an open source
monitoring system and alerting toolkit.

This repository contains a [Juju](https://jaas.ai/) Charm for
deploying the monitoring component of Prometheus in a Kubernetes
cluster. The alerting component of Prometheus is offered through a
separate Charm.


## Usage

The Prometheus Operator may be deployed using the Juju command line as
in

    juju deploy prometheus-k8s

By default the Prometheus Operator monitors itself, but it also
accepts additional scrape targets over Juju relations with charms that
support the `prometheus` interface and preferably use the Prometheus
charm library. This charm library provides an `add_endpoint()` method
that creates additional scrape targets. Each scrape target is expected
to expose a `/metrics` HTTP path that exposes its metrics in a
Prometheus compatible format.

For example if it desired to scrape metrics regarding the state of
objects in a Kubernetes cluster, the
[kube-state-metrics](https://charmhub.io/kube-state-metrics) charm may
be used for this purpose. All that is required, in addition to
deploying Prometheus as above, is to deploy the `kube-state-metrics`
charm and add a relation with the Prometheus charm as shown below.


    juju deploy kube-state-metrics
    juju relate kube-state-metrics prometheus-k8s

In a similar manner any charm that exposes a scrape target may be
related to the Prometheus charm.

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
- In addition this Prometheus charm does allow relations with any charm
that supports the `prometheus_scrape` relation.

## OCI Images

This charm by default uses the latest version of the
[ubuntu/prometheus](https://hub.docker.com/r/ubuntu/prometheus) image.

## Contributing

Please see the Juju [SDK docs](https://juju.is/docs/sdk) for guidelines
on developing enhancements to this charm following best practice guidelines.
