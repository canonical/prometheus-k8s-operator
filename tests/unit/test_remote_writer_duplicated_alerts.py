import json
import logging

from charms.prometheus_k8s.v1.prometheus_remote_write import (
    PrometheusRemoteWriteConsumer,
)
from helpers import (
    UNITTEST_DIR,
    patch_cos_tool_path,
)
from ops.charm import CharmBase
from scenario import Context, PeerRelation, Relation, State

logger = logging.getLogger(__name__)

class RemoteWriteConsumerCharm(CharmBase):
    @patch_cos_tool_path
    def __init__(self, *args, **kwargs):
        super().__init__(*args)
        self.remote_write_consumer = PrometheusRemoteWriteConsumer(
            self,
            relation_name = "send-remote-write",
            alert_rules_path=str(UNITTEST_DIR / "prometheus_alert_rules"),
            peer_relation_name = "peers"
        )
        self.framework.observe(
            self.remote_write_consumer.on.endpoints_changed,
            self._handle_endpoints_changed,
        )

    def _handle_endpoints_changed(self, _):
        pass

META = {
        "name": "test",
        "requires": {
            "send-remote-write": {"interface": "prometheus_remote_write"},
            "metrics-endpoint": {"interface": "prometheus_scrape"},
        },
        "peers": {"peers": {"interface": "grafana_agent_replica"}},
    }


def test_remote_write_absent_alert_duplicated_for_units():
    context = Context(charm_type=RemoteWriteConsumerCharm, meta=META)
    remote_relation = Relation(
        endpoint="send-remote-write",
    )
    # GIVEN four total units for the remote writer: one leader and three non-leader peers.
    peer_relation = PeerRelation(endpoint="peers", peers_data={1: {}, 2: {}, 3: {}}) # Simulate three non-leader units (ref: https://github.com/canonical/operator/blob/5e752be44086c580a449a2b07e2327ddbf6783d0/docs/howto/manage-relations.md?plain=1#L316).

    state = State(relations={remote_relation, peer_relation}, leader=True)

    # WHEN the remote writer joins a relation to a remote writer provider and updates relation data.
    state_out = context.run(context.on.relation_joined(remote_relation), state)

    remote_write_relation = next((obj for obj in state_out.relations if obj.endpoint == "send-remote-write"), None)

    remote_write_relation_json = json.loads(getattr(remote_write_relation, "local_app_data", {}).get("alert_rules", {}))
    assert remote_write_relation_json

    # THEN we expect the HostMetricsMissing rule to be duplicated for each unit: we should have four in total.
    # Three for the peers and one for the leader = 4 total.
    # AND the expr field and alert labels should include the expected juju_unit value.
    expected_units = {'test/0', 'test/1', 'test/2', 'test/3'}

    total_host_metrics_missing_rules = 0
    matching_rules = []
    for group in remote_write_relation_json.get('groups', []):
        for rule in group.get('rules', []):
            if rule.get('alert') == 'HostMetricsMissing':
                total_host_metrics_missing_rules += 1
                labels = rule.get('labels', {})
                unit = labels.get('juju_unit')
                expr = rule.get('expr', '')
                if unit in expected_units and unit in expr:
                    matching_rules.append((unit, rule))

    # AND we find exactly four matching rules for the four total units.
    assert len(matching_rules) == 4
    assert {unit for unit, _ in matching_rules} == expected_units

    # AND we should have in total five HostMetricsMissing rules.
    assert total_host_metrics_missing_rules == 5

def test_remote_write_no_alert_duplication_when_no_peers():
    context = Context(charm_type=RemoteWriteConsumerCharm, meta=META)
    # GIVEN only one unit for the remote writer, which is the leader itself.
    remote_relation = Relation(
        endpoint="send-remote-write",
    )

    peer_relation = PeerRelation(endpoint="peers", peers_data={}) # No peer units.

    state = State(relations={remote_relation, peer_relation}, leader=True)

    # WHEN the remote writer joins a relation to a remote writer provider and updates relation data.
    state_out = context.run(context.on.relation_joined(remote_relation), state)

    remote_write_relation = next((obj for obj in state_out.relations if obj.endpoint == "send-remote-write"), None)

    remote_write_relation_json = json.loads(getattr(remote_write_relation, "local_app_data", {}).get("alert_rules", {}))
    assert remote_write_relation_json

    # Expecting the HostMetricsMissing rule NOT to be duplicated.
    total_host_metrics_missing_rules = 0
    matching_rules = []
    for group in remote_write_relation_json.get('groups', []):
        for rule in group.get('rules', []):
            labels = rule.get('labels', {})
            unit = labels.get('juju_unit')
            expr = rule.get('expr', '')
            app = labels.get('juju_application')
            # THEN because we only have one remote writer unit, there should be no duplication.
            # AND there should be no juju_unit label or mention in expr.
            if rule.get('alert') == 'HostMetricsMissing':
                total_host_metrics_missing_rules += 1
                if unit is None and 'juju_unit' not in expr and app == 'test':
                    matching_rules.append(rule)

    # AND we find exactly one matching rule.
    assert len(matching_rules) == 1

    # AND we should have in total two HostMetricsMissing rules:
    # one for the remote writer itself and one for the scraped charm.
    assert total_host_metrics_missing_rules == 2
