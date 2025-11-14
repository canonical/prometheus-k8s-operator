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
        },
        "peers": {"peers": {"interface": "grafana_agent_replica"}},
    }

def test_remote_write_absent_alert_duplicated_for_units():
    context = Context(charm_type=RemoteWriteConsumerCharm, meta=META)
    remote_relation = Relation(
        endpoint="send-remote-write",
    )

    peer_relation = PeerRelation(endpoint="peers", peers_data={1: {}, 2: {}, 3: {}},)

    state = State(relations={remote_relation, peer_relation}, leader=True)
    state_out = context.run(context.on.relation_joined(remote_relation), state)

    remote_write_relation = next((obj for obj in state_out.relations if obj.endpoint == "send-remote-write"), None)

    remote_write_relation_json = json.loads(getattr(remote_write_relation, "local_app_data", {}).get("alert_rules", {}))
    assert remote_write_relation_json

    # Expecting the HostMetricsMissing rule to be duplicated for each unit: we should have three in total.
    # The expr field and alert labels should include the expected juju_unit value.
    expected_units = {'test/0', 'test/1', 'test/2'}
    matching_rules = []
    for group in remote_write_relation_json.get('groups', []):
        for rule in group.get('rules', []):
            if rule.get('alert') == 'HostMetricsMissing':
                labels = rule.get('labels', {})
                unit = labels.get('juju_unit')
                expr = rule.get('expr', '')
                if unit in expected_units and unit in expr:
                    matching_rules.append((unit, rule))

    # Here we assert that we have found exactly three matching rules for the three units.
    assert len(matching_rules) == 3, f"Expected 3 rules, found {len(matching_rules)}"
    assert {unit for unit, _ in matching_rules} == expected_units, "Missing some expected units"
