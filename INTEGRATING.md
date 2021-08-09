## Integrating Prometheus

Prometheus integrates with the following

1. Any charm that supports the `prometheus_scrape` interface in
serving as a scrape target for Prometheus. This integration is done
using the Prometheus Charm library. The documentation of the charm
library, available through
[Charmhub](https://charmhub.io/prometheus-k8s) provides further
details on how this integration may be done.

This Prometheus also supports raising alerts and forwarding them to
Alertmanager. The rules that define when alerts are raised are read
from a directory named `prometheus_alert_rules`, if present at
the top level, within any charm supporting the `prometheus_scrape`
interface.

2. Prometheus integrates with
[Grafana](https://charmhub.io/grafana-k8s) which provides a dashboard
for viewing metrics aggregated by Prometheus. These dasboards may be
customised by charms that relate to Grafana.

3. Prometheus forwards alerts to one or more
[Alertmanagers](https://charmhub.io/alertmanager-k8s) that are related
to it.
