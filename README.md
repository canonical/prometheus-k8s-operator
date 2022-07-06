# Prometheus Operator with Prometheus Configurer

## Description

The Prometheus Operator provides a cluster monitoring solution using 
[Prometheus](https://prometheus.io), which is an open source monitoring system and alerting 
toolkit.

This repository is a fork of the
[prometheus-k8s-operator](https://github.com/canonical/prometheus-k8s-operator).
It contains a [Juju](https://juju.is/) Charm for deploying the monitoring component 
of Prometheus in a Kubernetes cluster along with an additional 
[prometheus-configurer](https://github.com/facebookarchive/prometheus-configmanager) container, 
providing an HTTP API for managing Prometheus's alerting rules.<br>
An [alerting service](https://charmhub.io/alertmanager-k8s)
for Prometheus is offered through a separate Charm.

## Usage

### Deployment

The Prometheus Operator with Prometheus Configurer may be deployed using the Juju command line as
in

```sh
$ juju deploy prometheus-with-configurer
```

### Additional scrape targets

By default the Prometheus Operator monitors itself, but it also accepts additional scrape targets 
over Juju relations with charms that support the `prometheus_scrape` interface and preferably use 
the Prometheus charm library. This 
[charm library](lib/charms/prometheus_k8s/v0/prometheus_scrape.py) provides an `add_endpoint()` 
method that creates additional scrape targets. Each scrape target is expected to expose 
a `/metrics` HTTP path that exposes its metrics in a Prometheus compatible format. For example, the
[kube-state-metrics](https://charmhub.io/kube-state-metrics) charm integrates with the 
Prometheus k8s charm in a way that allows you import metrics about resources in a Kubernetes 
cluster by doing:

```sh
$ juju deploy kube-state-metrics
$ juju relate kube-state-metrics prometheus-with-configurer
```

In a similar manner any charm that exposes a scrape target may be related to the Prometheus charm.

At present it is expected that all relations the Prometheus Operator partakes in are within the 
same Juju model.
[Further development](https://github.com/canonical/prometheus-operator/issues/58) may extend this 
to allow cross model scrape targets.

### Configuring alert rules via prometheus-configurer

Prometheus Configurer exposes an HTTP API which allows managing Prometheus's alerting rules. 
The API is available at port 9100 on the IP address of the charm unit. This unit and its IP address
may be determined using the `juju status` command.<br>
Full description of Prometheus Configurer's API is available in 
[github](https://github.com/facebookarchive/prometheus-configmanager/blob/main/prometheus/docs/swagger-v1.yml).

By default, Prometheus Configurer supports multitenancy, hence all alerting rules added using
Prometheus Configurer will be augmented with the `tenant_id` passed in the endpoint URL.<br>
Example:
```yaml
alert: CPUOverUse
expr: process_cpu_seconds_total > 0.12
for: 0m
labels:
  severity: Low
annotations:
  summary: "Rule summary."
  description: "Rule description."
```
Adding above rule using Prometheus Configurer can be done by running below POST:
```bash
curl -X POST http://<PROMETHEUS CHARM UNIT IP>:9100/<TENANT_ID>/alert 
  -H 'Content-Type: application/json' 
  -d '{"alert": "CPUOverUse", "expr": "process_cpu_seconds_total > 0.12", "for": "0m", "labels": {"severity": "Low"}, "annotations": {"summary": "Rule summary.", "description": "Rule description."}}'
```

## Dashboard

The Prometheus dashboard may be accessed at port 9090 on the IP address of the Prometheus unit. 
This unit and its IP address may be determined using the `juju status` command.

## Relations

Currently supported relations are

- [Grafana](https://github.com/canonical/grafana-operator) aggregates
  metrics scraped by Prometheus and provides a versatile dashboard to
  view these metrics in configurable ways. Prometheus relates to
  Grafana over the `grafana_datasource` interface.
- [Alertmanager](https://github.com/canonical/alertmanager-operator)
  receives alerts from Prometheus, aggregates and deduplicates them,
  then forwards them to specified targets. Prometheus relates to
  Alertmanager over the `alertmanager` interface.
- Access to Prometheus from outside the Kubernetes cluster can be
  provided via `ingress` relation with the
  [Nginx Ingress Integrator](https://charmhub.io/nginx-ingress-integrator).
  This relation is **experimental**, and there is a chance the charm
  will evolve to use some other mechanism to be reachable from the outside
  of the hosting Kubernetes cluster.
- In addition, this Prometheus charm allows relations with any
  charm that supports the `prometheus_scrape` relation.
- This Prometheus charm does not as yet support federation. This
  implies scaling the number of Prometheus units results in each unit
  scrape the same targets.

## Use Cases Supported

- Configure scrape targets through Juju relations.
- Configure alerting rules through relations with scrape target charms.
- Enable alert forwarding through a relation with Alertmanager.
- Support metrics visualisation through Grafana.

## OCI Images

- [ubuntu/prometheus](https://hub.docker.com/r/ubuntu/prometheus)
- [facebookincubator/prometheus-configurer](https://hub.docker.com/r/facebookincubator/prometheus-configurer)
