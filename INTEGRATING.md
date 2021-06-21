## Integrating Prometheus

Prometheus integrates with the following

1. Any charm that supports the `prometheus_scrape` interface in
serving as a scrape target for Prometheus. This integration is done
using the Prometheus Charm library. The documentation of the charm
library, available through
[Charmhub](https://charmhub.io/prometheus-k8s) provides further
details on how this integration may be done.

2. Grafana

3. Alertmanager
