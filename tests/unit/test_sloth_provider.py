from dataclasses import replace

import yaml
from ops.testing import Relation, State

SLOS_SPEC = """
version: "prometheus/v1"
service: "prometheus"
labels:
  repo: "canonical/prometheus-k8s-operator"
slos:
  # HTTP API availability - Track non-5xx responses
  - name: "http-availability"
    objective: 99.0
    description: "Availability of the Prometheus HTTP API (non-5xx responses)"
    sli:
      events:
        error_query: sum(rate(prometheus_http_requests_total{code=~"5.."}[{{.window}}]))
        total_query: sum(rate(prometheus_http_requests_total[{{.window}}]))
      alerting:
        name: PrometheusHttpAvailability
        page_alert:
          disable: true
        ticket_alert:
          disable: true

  # Rule evaluation reliability - Track evaluation failures
  - name: "rule-evaluation-success"
    objective: 95.0
    description: "Successful rule evaluations (excluding failures)"
    sli:
      events:
        error_query: sum(rate(prometheus_rule_evaluation_failures_total[{{.window}}]))
        total_query: sum(rate(prometheus_rule_evaluations_total[{{.window}}]))
    alerting:
      name: PrometheusRuleEvaluationSuccess
      page_alert:
        disable: true
      ticket_alert:
        disable: true

  # TSDB compaction reliability - Track compaction failures
  - name: "tsdb-compaction-success"
    objective: 90.0
    description: "Successful TSDB compactions (excluding failures)"
    sli:
      events:
        error_query: sum(rate(prometheus_tsdb_compactions_failed_total[{{.window}}]))
        total_query: sum(rate(prometheus_tsdb_compactions_total[{{.window}}]))
    alerting:
      name: PrometheusTsdbCompactionSuccess
      page_alert:
        disable: true
      ticket_alert:
        disable: true
"""


def test_slos_relation_sends_spec(context, prometheus_container, prometheus_peers):
    """Test that SLO spec is sent when slos relation changes."""
    base_state = State(containers={prometheus_container}, relations={prometheus_peers})
    relation = Relation(endpoint="send-slos", remote_app_name="sloth")

    state_out = context.run(
        context.on.config_changed(),
        replace(
            base_state,
            leader=True,
            relations={relation},
            config={"slos": SLOS_SPEC},
        ),
    )

    # Check that the relation has data
    rel_out = state_out.get_relation(relation.id)
    # The SlothProvider stores data as a YAML-encoded list in the "slos" field
    assert "slos" in rel_out.local_app_data

    # Verify it's valid YAML containing a list of SLO specs
    slo_list = yaml.safe_load(rel_out.local_app_data["slos"])
    assert isinstance(slo_list, list)
    assert len(slo_list) > 0
    # Each item in the list should be a complete SLO spec
    assert slo_list[0]["service"] == "prometheus"
