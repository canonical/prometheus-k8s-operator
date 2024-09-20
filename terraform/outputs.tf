# Copyright 2024 Canonical Ltd.
# See LICENSE file for licensing details.

output "app_name" {
  description = "Name of the deployed application."
  value       = juju_application.prometheus.name
}

# Required integration endpoints

output "metrics_endpoint" {
  description = "Name of the endpoint used by Prometheus to get metrics from client applications."
  value       = "metrics-endpoint"
}

output "alertmanager_endpoint" {
  description = "Name of the endpoint used by Prometheus to send out the alerts."
  value       = "alertmanager"
}

output "ingress_endpoint" {
  description = "Name of the endpoint used by Prometheus for the ingress configuration."
  value       = "ingress"
}

output "catalogue_endpoint" {
  description = "Name of the endpoint used by Prometheus for the Catalogue integration."
  value       = "catalogue"
}

output "certificates_endpoint" {
  description = "Name of the endpoint used to integrate with the TLS certificates provider."
  value       = "certificates"
}

output "tracing_endpoint" {
  description = "Name of the endpoint used by Grafana for pushing traces to a tracing endpoint provided by Tempo."
  value       = "tracing"
}

# Provided integration endpoints

output "self_metrics_endpoint" {
  description = "Exposes the Prometheus metrics endpoint providing telemetry about this Prometheus instance."
  value       = "self-metrics-endpoint"
}

output "grafana_dashboard_endpoint" {
  description = "Forwards the built-in Grafana dashboard(s) for monitoring Prometheus."
  value       = "grafana-dashboard"
}

output "grafana_source_endpoint" {
  description = "Name of the endpoint used by Prometheus to create a datasource in Grafana."
  value       = "grafana-source"
}

output "receive_remote_write_endpoint" {
  description = "Name of the endpoint used by Prometheus to accept data from remote-write-compatible agents."
  value       = "receive-remote-write"
}
