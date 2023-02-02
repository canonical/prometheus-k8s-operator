# Prometheus Charmed Operator for Kubernetes


[![Release to Edge](https://github.com/canonical/prometheus-k8s-operator/actions/workflows/release-edge.yaml/badge.svg)](https://github.com/canonical/prometheus-k8s-operator/actions/workflows/release-edge.yaml)


## Description

The Prometheus Charmed Operator for [Juju](https://juju.is) provides a monitoring solution using [Prometheus](https://prometheus.io), which is an open-source monitoring system and alerting toolkit. Besides it handles instantiation, scaling, configuration, and Day 2 operations specific to Prometheus.

This Charm is also part of the [Canonical Observability Stack](https://charmhub.io/topics/canonical-observability-stack) and deploys only the monitoring component of Prometheus in a Kubernetes cluster. An [alerting service](https://charmhub.io/alertmanager-k8s) for Prometheus is offered through a separate Charm.



## Getting Started

### Basic Deployment

Create a Juju model for your operator, say "observability"

```sh
juju add-model observability
```

The Prometheus Charmed Operator may now be deployed using the Juju command line as in

```sh
juju deploy prometheus-k8s --channel=stable
```


### Checking deployment status

Progress of the Prometheus charm deployment and its current status may be viewed anytime using the Juju command line.

```sh
juju status --color --relations
```

Once the Prometheus charm deployments completes, you may expect to see a status result such as

```sh
$ juju status --relations

Model  Controller           Cloud/Region        Version  SLA          Timestamp
cos    charm-dev-batteries  microk8s/localhost  3.0.2    unsupported  14:27:58-03:00

App             Version  Status  Scale  Charm           Channel  Rev  Address         Exposed  Message
prometheus-k8s  2.33.5   active      1  prometheus-k8s  stable    79  10.152.183.227  no

Unit               Workload  Agent  Address     Ports  Message
prometheus-k8s/0*  active    idle   10.1.36.90

Relation provider                Requirer                         Interface         Type  Message
prometheus-k8s:prometheus-peers  prometheus-k8s:prometheus-peers  prometheus_peers  peer
```


### Accessing the Prometheus User Interface

Prometheus provides a user interface that let us explore the data that has collected such as metrics and associated alerts.
This UI is accessed on port 9090 at the Prometheus charm's address. This assumes the Prometheus host address is accessible from the host your browser is running on. For example the Juju status message shown above is from a `microk8s` cluster, hence navigating to `http://10.152.183.227:9090` will show us the Prometheus UI.


### Adding scrape targets

When Prometheus is deployed it will only scrape metrics from itself. This is the default behavior of Prometheus. Additional metrics endpoints may be added to the Prometheus charm through relations with other charms. Currently the following charms are supported

- Any charm that uses the `prometheus_scrape` interface to provide a metrics endpoint and optionally alert rules for Prometheus.
- The [Prometheus Scrape Target]() charm may be used to scrape metrics endpoint that are not part of any Juju Model.
- The [Prometheus Scrape Config]() charm may be used to scrape metrics endpoints across different Juju models. The charm also support overriding some of the scrape job configurations provided by metrics endpoints.



## Relations

At present the Prometheus Charmed Operator for Kubernetes supports eight relations.


### Requires

#### Metrics Endpoint:

```yaml
  metrics-endpoint:
    interface: prometheus_scrape
```
Charms may forward information about their metrics endpoints and associated alert rules to the Prometheus charm over the `metrics-endpoint` relation using the [`prometheus_scrape`](https://charmhub.io/prometheus-k8s/libraries/prometheus_scrape) interface. In order for these metrics to be aggregated by this Prometheus charm all that is required is to relate the two charms as in:

```shell
juju relate kube-state-metrics-k8s prometheus-k8s
```

Charms that seek to provide metrics endpoints and alert rules for Prometheus must do so using the provided [`prometheus_scrape`](https://charmhub.io/prometheus-k8s/libraries/prometheus_scrape) charm library.  This library by implementing the `metrics-endpoint` relation, not only ensures that scrape jobs and alert rules are forward to Prometheus but also that these are updated any time the metrics provider charm is upgraded. For example new alert rules may be added or old ones removed by updating and releasing a new version of the metrics provider charm. While it is safe to update alert rules as desired, care must be taken when updating scrape job specifications as this has the potential to break the continuity of the scraped metrics time series. In particular changing the following keys in the scrape job can break time series continuity
- `job_name`
- `relabel_configs`
- `metrics_relabel_configs`
- Any label set by `static_configs`

Evaluation of alert rules forwarded through the [`prometheus_scrape`](https://charmhub.io/prometheus-k8s/libraries/prometheus_scrape) interface are automatically limited to the charmed application that provided these rules. This ensures that alert rule evaluation is scoped down to the charm providing the rules.

#### Alerting

```yaml
  alertmanager:
    interface: alertmanager_dispatch
```

The [Alertmanager Charm](https://charmhub.io/alertmanager-k8s) aggregates, deduplicates, groups and routes alerts to selected "receivers". Alertmanager receives its alerts from Prometheus and this interaction is set up and configured using the `alertmanager` relation through the [`alertmanager_dispatch`](https://charmhub.io/alertmanager-k8s/libraries/alertmanager_dispatch) interface. Over this relation the Alertmanager charm keeps Prometheus informed of all Alertmanager instances (units) to which alerts must be forwarded.  If your charm sets any alert rules then almost always it would need a relation with an Alertmanager charm which had been configured to forward alerts to specific receivers. In the absence of such a relation alerts even when raised will only be visible in the Prometheus user interface. A prudent approach to setting up an Observability stack is to do so in a manner such that it draws your attention to alarms as and when they are raised, without you having to periodically check a dashboard. 

#### Ingress

```yaml
  ingress:
    interface: ingress_per_unit
    limit: 1
```

Interactions with the Prometheus charm can not be assumed to originate within the same Juju model, let alone the same Kubernetes cluster, or even the same Juju cloud. Hence the Prometheus charm also supports an Ingress relation. There are multiple use cases that require an ingress, in particular
- Using the Prometheus remote write endpoint across network boundaries.
- Querying the Prometheus HTTP API endpoint across network boundaries.
- Self monitoring of Prometheus that *must* happen across network boundaries to ensure robustness of self monitoring.
- Supporting the Loki push API.
- Exposing the Prometheus remote write endpoint to Grafana agent.

Prometheus typical needs a "per unit" Ingress. This per unit ingress is necessary since Prometheus exposes a remote write endpoint on a per unit basis. A per unit ingress relation is available in the [traefik-k8s](https://charmhub.io/traefik-k8s) charm and this Prometheus charm does support that relation over [`ingress_per_unit`](https://charmhub.io/traefik-k8s/libraries/ingress_per_unit) interface.


#### Catalogue

```yaml
  catalogue:
    interface: catalogue
```

Through this relation, Prometheus provides its URL to [Catalogue K8s Charmed Operator](https://charmhub.io/catalogue-k8s) which is a landing page that helps users to locate the user interfaces of charms it relates to.


## Provides

### Grafana Source

```yaml
  grafana-source:
    interface: grafana_datasource
```

The [Grafana Charm](https://charmhub.io/grafana-k8s) provides a data visualization solution  for metrics aggregated by Prometheus and supports the creation of bespoke dashboards for such visualization. Grafana requires a data source for its dashboards and this Prometheus charm provides the data source through the `grafana-source` relation using the [`grafana_datasource`](https://charmhub.io/grafana-k8s/libraries/grafana_source) interface. To visualize your charms metrics using Grafana  the following steps are required 
- Add a relation between your charm (say `cassandra-k8s`) and Prometheus so that Prometheus can aggregate the metrics.
- Add a relation between the Grafana and Prometheus charm so that metrics are forwarded to Grafana.
- Add a relation between your charm and Grafana so that your charm can forward dashboards for its metrics to Grafana.

For example 
```
juju relate cassandra-k8s prometheus-k8s
juju relate prometheus-k8s grafana-k8s
juju relate cassandra-k8s grafana-k8s
```

#### Remote Write

```yaml
  receive-remote-write:
    interface: prometheus_remote_write
```

Metrics may also be pushed to this Prometheus charm through the `receive-remote-write` relation using the [`prometheus_remote_write`](https://charmhub.io/prometheus-k8s/libraries/prometheus_remote_write) interface, which can be used with the [Grafana Agent Charm](https://charmhub.io/grafana-agent-k8s) to have metrics scraped by the Grafana Agent sent over to Prometheus.

#### Self metrics endpoint


```yaml
self-metrics-endpoint:
    interface: prometheus_scrape
```
This Prometheus charm may forward information about its metrics endpoint and associated alert rules to another Prometheus charm over the `self-metrics-endpoint` relation using the [`prometheus_scrape`](https://charmhub.io/prometheus-k8s/libraries/prometheus_scrape) interface. In order for these metrics to be aggregated by the remote Prometheus charm all that is required is to relate the two charms as in:

```bash
juju relate \
    prometheus-k8s:self-metrics-endpoint \
    remote-prometheus-charm:metrics-endpoint
```

#### Grafana dashboard

```yaml
  grafana-dashboard:
    interface: grafana_dashboard
```

Over the `grafana-dashboard` relation using the [`grafana-dashboard`](https://charmhub.io/grafana-k8s/libraries/grafana_dashboard) interface, this Prometheus charm also provides meaningful dashboards about its metrics to be shown in a [Grafana Charm ](https://charmhub.io/grafana-k8s).

In order to add these dashboards to Grafana all that is required is to relate the two charms in the following way:

```bash
juju relate \
    prometheus-k8s:grafana-dashboard \
    grafana-k8s:grafana-dashboard
```


## OCI Images

This charm by default uses the latest version of the
[canonical/prometheus](https://ghcr.io/canonical/prometheus) image.
