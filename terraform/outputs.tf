output "app_name" {
  value = juju_application.prometheus.name
}

output "endpoints" {
  value = {
    # Requires

    metrics_endpoint      = "metrics-endpoint"
    alertmanager          = "alertmanager"
    ingress               = "ingress"
    catalogue             = "catalogue"
    certificates          = "certificates"
    charm_tracing         = "charm-tracing"
    workload_tracing      = "workload-tracing"

    # Provides

    self_metrics_endpoint = "self-metrics-endpoint"
    grafana_source        = "grafana-source"
    grafana_dashboard     = "grafana-dashboard"
    receive_remote_write  = "receive-remote-write"
    send_datasource       = "send-datasource"
    prometheus_api        = "prometheus-api"
  }
}