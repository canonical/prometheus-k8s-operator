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
COLLECTOR_CHARM = "opentelemetry-collector-k8s"
ALERT_RULES = {
    "groups": [
        {
            "name": "test-model_e674af04-0e76-4c11-92a0-f219fa8b4386_remote_writer",
            "rules": [
                {
                    "alert": "HostMetricsMissing",
                    "expr": 'absent(up{juju_application="remote_writer",juju_model="test-model",juju_model_uuid="e674af04-0e76-4c11-92a0-f219fa8b4386"}) == 0',
                    "for": "0m",
                    "labels": {
                        "severity": "critical",
                        "juju_model": "test-model",
                        "juju_model_uuid": "e674af04-0e76-4c11-92a0-f219fa8b4386",
                        "juju_application": "remote_writer",
                        "juju_charm": COLLECTOR_CHARM,
                    },
                    "annotations": {
                        "summary": "Prometheus target missing (instance {{ $labels.instance }})",
                        "description": "A Prometheus target has disappeared."
                        "VALUE = {{ $value }}\n  LABELS = {{ $labels }}",
                    },
                },

            ],
        }
    ]
}

EXPECTED_ALERTS = {
    "groups": [
        {
            "name": "test-model_e674af04-0e76-4c11-92a0-f219fa8b4386_remote_writer",
            "rules": [
                {
                    "alert": "HostMetricsMissing",
                    "expr": 'absent(up{juju_application="remote_writer",juju_model="test-model",juju_model_uuid="e674af04-0e76-4c11-92a0-f219fa8b4386",juju_unit="remote_writer/0"}) == 0',
                    "for": "0m",
                    "labels": {
                        "severity": "critical",
                        "juju_model": "test-model",
                        "juju_model_uuid": "e674af04-0e76-4c11-92a0-f219fa8b4386",
                        "juju_application": "remote_writer",
                        "juju_charm": COLLECTOR_CHARM,
                        "juju_unit": "remote_writer/0",
                    },
                    "annotations": {
                        "summary": "Prometheus target missing (instance {{ $labels.instance }})",
                        "description": "A Prometheus target has disappeared."
                        "VALUE = {{ $value }}\n  LABELS = {{ $labels }}",
                    },
                },
                {
                    "alert": "HostMetricsMissing",
                    "expr": 'absent(up{juju_application="remote_writer",juju_model="test-model",juju_model_uuid="e674af04-0e76-4c11-92a0-f219fa8b4386",juju_unit="remote_writer/1"}) == 0',
                    "for": "0m",
                    "labels": {
                        "severity": "critical",
                        "juju_model": "test-model",
                        "juju_model_uuid": "e674af04-0e76-4c11-92a0-f219fa8b4386",
                        "juju_application": "remote_writer",
                        "juju_charm": COLLECTOR_CHARM,
                        "juju_unit": "remote_writer/1",
                    },
                    "annotations": {
                        "summary": "Prometheus target missing (instance {{ $labels.instance }})",
                        "description": "A Prometheus target has disappeared."
                        "VALUE = {{ $value }}\n  LABELS = {{ $labels }}",
                    },
                },
                {
                    "alert": "HostMetricsMissing",
                    "expr": 'absent(up{juju_application="remote_writer",juju_model="test-model",juju_model_uuid="e674af04-0e76-4c11-92a0-f219fa8b4386",juju_unit="remote_writer/2"}) == 0',
                    "for": "0m",
                    "labels": {
                        "severity": "critical",
                        "juju_model": "test-model",
                        "juju_model_uuid": "e674af04-0e76-4c11-92a0-f219fa8b4386",
                        "juju_application": "remote_writer",
                        "juju_charm": COLLECTOR_CHARM,
                        "juju_unit": "remote_writer/2",
                    },
                    "annotations": {
                        "summary": "Prometheus target missing (instance {{ $labels.instance }})",
                        "description": "A Prometheus target has disappeared."
                        "VALUE = {{ $value }}\n  LABELS = {{ $labels }}",
                    },
                },
            ],
        },

    ]
}

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
        remote_app_data={"alert_rules": json.dumps(ALERT_RULES)},
    )
    peer_relation = PeerRelation(endpoint="peers", peers_data={1: {}, 2: {}, 3: {}},)

    state = State(relations={remote_relation, peer_relation}, leader=True)
    state_out = context.run(context.on.relation_joined(remote_relation), state)

    remote_write_relation = next((obj for obj in state_out.relations if obj.endpoint == "send-remote-write"), None)

    assert remote_write_relation
    logger.info("Remote write relation app data: %s", remote_write_relation.remote_app_data)
    logger.info("Expected alerts: %s", EXPECTED_ALERTS)
    assert remote_write_relation.remote_app_data == EXPECTED_ALERTS