# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Feature: compression of the alert rules published over prometheus_remote_write.

The consumer LZMA-compresses and base64-encodes its alert rules, but only if the
provider advertises that it is able to read them that way. This keeps a consumer
running a recent version of the library compatible with a provider running an older
one, which only understands plain JSON.
"""

import dataclasses
import json
from typing import cast

import pytest
from charms.prometheus_k8s.v1.prometheus_remote_write import (
    ALERT_RULES_ENCODINGS_KEY,
    ALERT_RULES_KEY,
    JSON_ENCODING,
    LZMA_ENCODING,
    SUPPORTED_ALERT_RULES_ENCODINGS,
    PrometheusRemoteWriteConsumer,
    PrometheusRemoteWriteProvider,
    _decode_alert_rules,
    _encode_alert_rules,
)
from cosl import LZMABase64
from helpers import UNITTEST_DIR, patch_cos_tool_path
from ops.charm import CharmBase
from scenario import Context, Model, PeerRelation, Relation, State

CONSUMER_META = {
    "name": "consumer-tester",
    "requires": {"send-remote-write": {"interface": "prometheus_remote_write"}},
    "peers": {"peers": {"interface": "consumer_peers"}},
}

PROVIDER_META = {
    "name": "provider-tester",
    "provides": {"receive-remote-write": {"interface": "prometheus_remote_write"}},
}

# Pinned so that the topology labels injected into the alert rules are deterministic.
MODEL = Model("test-model", uuid="e674af04-0e76-4c11-92a0-f219fa8b4386")

LZMA_ADVERTISED = {ALERT_RULES_ENCODINGS_KEY: json.dumps([LZMA_ENCODING, JSON_ENCODING])}

ALERT_RULES = {
    "groups": [
        {
            "name": "test-model_e674af04_consumer-tester_alerts",
            "rules": [
                {
                    "alert": "CPUOverUse",
                    "expr": 'process_cpu_seconds_total{juju_application="consumer-tester",'
                    'juju_model="test-model",'
                    'juju_model_uuid="e674af04-0e76-4c11-92a0-f219fa8b4386"} > 0.12',
                    "for": "0m",
                    "labels": {
                        "severity": "Low",
                        "juju_model": "test-model",
                        "juju_model_uuid": "e674af04-0e76-4c11-92a0-f219fa8b4386",
                        "juju_application": "consumer-tester",
                    },
                }
            ],
        }
    ]
}


class RemoteWriteConsumerCharm(CharmBase):
    @patch_cos_tool_path
    def __init__(self, *args, **kwargs):
        super().__init__(*args)
        self.remote_write_consumer = PrometheusRemoteWriteConsumer(
            self,
            alert_rules_path=str(UNITTEST_DIR / "prometheus_alert_rules"),
            peer_relation_name="peers",
        )


class RemoteWriteProviderCharm(CharmBase):
    @patch_cos_tool_path
    def __init__(self, *args, **kwargs):
        super().__init__(*args)
        self.remote_write_provider = PrometheusRemoteWriteProvider(self)


@pytest.fixture
def consumer_ctx() -> Context[RemoteWriteConsumerCharm]:
    return Context(charm_type=RemoteWriteConsumerCharm, meta=CONSUMER_META)


@pytest.fixture
def provider_ctx() -> Context[RemoteWriteProviderCharm]:
    return Context(charm_type=RemoteWriteProviderCharm, meta=PROVIDER_META)


def _get_relation(state: State, relation: Relation) -> Relation:
    return cast(Relation, state.get_relation(relation.id))


def _published_rules(state: State, relation: Relation) -> str:
    return _get_relation(state, relation).local_app_data[ALERT_RULES_KEY]


def _replace_relation(state: State, relation: Relation) -> State:
    """Return a copy of `state` in which `relation` replaces the relation with its id."""
    others = {r for r in state.relations if r.id != relation.id}
    return dataclasses.replace(state, relations=others | {relation})  # pyright: ignore


# --- Encoding and decoding ---


def test_lzma_encoded_rules_round_trip():
    # GIVEN a set of alert rules
    # WHEN they are encoded with the lzma encoding
    encoded = _encode_alert_rules(ALERT_RULES, LZMA_ENCODING)

    # THEN the payload is not plain JSON
    with pytest.raises(json.JSONDecodeError):
        json.loads(encoded)

    # AND decoding it returns the original rules
    assert _decode_alert_rules(encoded) == ALERT_RULES


def test_json_encoded_rules_round_trip():
    # GIVEN a set of alert rules
    # WHEN they are encoded with the json encoding
    encoded = _encode_alert_rules(ALERT_RULES, JSON_ENCODING)

    # THEN the payload is plain JSON, as written by every version of the library
    assert json.loads(encoded) == ALERT_RULES

    # AND decoding it returns the original rules
    assert _decode_alert_rules(encoded) == ALERT_RULES


def test_unknown_encoding_falls_back_to_json():
    # GIVEN an encoding this library does not know about
    # WHEN alert rules are encoded with it
    encoded = _encode_alert_rules(ALERT_RULES, "brotli")

    # THEN they are stored as plain JSON, which any provider can read
    assert json.loads(encoded) == ALERT_RULES


def test_decoding_json_encoded_compressed_rules():
    # GIVEN compressed rules that were JSON-encoded, as pydantic based libraries write them
    encoded = json.dumps(LZMABase64.compress(json.dumps(ALERT_RULES)))

    # WHEN they are decoded
    # THEN the original rules are returned
    assert _decode_alert_rules(encoded) == ALERT_RULES


@pytest.mark.parametrize("raw", ["", "{}"])
def test_decoding_empty_rules(raw: str):
    # GIVEN an empty databag value
    # WHEN it is decoded
    # THEN no rules are returned, and nothing is raised
    assert _decode_alert_rules(raw) == {}


def test_decoding_unreadable_rules_raises():
    # GIVEN a databag value that is neither JSON nor a compressed payload
    # WHEN it is decoded
    # THEN an error is raised for the caller to handle
    with pytest.raises(Exception):
        _decode_alert_rules("!!! not rules !!!")


def test_compression_shrinks_the_payload():
    # GIVEN a large set of alert rules, as produced by a large deployment
    groups = []
    for i in range(200):
        group = json.loads(json.dumps(ALERT_RULES["groups"][0]))
        group["name"] = f"group_{i}"
        groups.append(group)
    rules = {"groups": groups}

    # WHEN they are compressed
    plain = _encode_alert_rules(rules, JSON_ENCODING)
    compressed = _encode_alert_rules(rules, LZMA_ENCODING)

    # THEN the payload is an order of magnitude smaller
    assert len(compressed) < len(plain) / 10


# --- Consumer: choosing an encoding ---


@pytest.mark.parametrize(
    "remote_app_data",
    [
        pytest.param({}, id="no_advertisement"),
        pytest.param({ALERT_RULES_ENCODINGS_KEY: json.dumps([JSON_ENCODING])}, id="json_only"),
        pytest.param({ALERT_RULES_ENCODINGS_KEY: json.dumps(["brotli"])}, id="unknown_encoding"),
        pytest.param({ALERT_RULES_ENCODINGS_KEY: "not json"}, id="malformed_advertisement"),
        pytest.param({ALERT_RULES_ENCODINGS_KEY: json.dumps({"lzma": True})}, id="not_a_list"),
    ],
)
def test_consumer_writes_plain_json_unless_lzma_is_advertised(
    consumer_ctx: Context[RemoteWriteConsumerCharm], remote_app_data: dict
):
    # GIVEN a provider that does not advertise support for compressed alert rules
    relation = Relation("send-remote-write", remote_app_data=remote_app_data)
    state = State(relations={relation, PeerRelation("peers")}, leader=True, model=MODEL)

    # WHEN the relation is joined
    state_out = consumer_ctx.run(consumer_ctx.on.relation_joined(relation), state)

    # THEN the alert rules are published as plain JSON
    published = json.loads(_published_rules(state_out, relation))
    assert published["groups"]


def test_consumer_compresses_when_lzma_is_advertised(
    consumer_ctx: Context[RemoteWriteConsumerCharm],
):
    # GIVEN a provider that advertises support for compressed alert rules
    relation = Relation("send-remote-write", remote_app_data=LZMA_ADVERTISED)
    state = State(relations={relation, PeerRelation("peers")}, leader=True, model=MODEL)

    # WHEN the relation is joined
    state_out = consumer_ctx.run(consumer_ctx.on.relation_joined(relation), state)

    # THEN the alert rules are compressed
    published = _published_rules(state_out, relation)
    with pytest.raises(json.JSONDecodeError):
        json.loads(published)

    # AND they hold the same rules as the uncompressed ones
    legacy_relation = Relation("send-remote-write")
    legacy_state = consumer_ctx.run(
        consumer_ctx.on.relation_joined(legacy_relation),
        State(relations={legacy_relation, PeerRelation("peers")}, leader=True, model=MODEL),
    )
    assert _decode_alert_rules(published) == json.loads(
        _published_rules(legacy_state, legacy_relation)
    )


def test_consumer_switches_to_compressed_when_provider_starts_advertising(
    consumer_ctx: Context[RemoteWriteConsumerCharm],
):
    # GIVEN a provider that does not advertise anything yet
    relation = Relation("send-remote-write")
    state = State(relations={relation, PeerRelation("peers")}, leader=True, model=MODEL)

    # WHEN the relation is joined
    state_out = consumer_ctx.run(consumer_ctx.on.relation_joined(relation), state)

    # THEN the alert rules are published as plain JSON
    assert json.loads(_published_rules(state_out, relation))

    # AND WHEN the provider later advertises support for compressed alert rules
    advertising = dataclasses.replace(
        _get_relation(state_out, relation), remote_app_data=LZMA_ADVERTISED
    )
    state_out = consumer_ctx.run(
        consumer_ctx.on.relation_changed(advertising),
        _replace_relation(state_out, advertising),
    )

    # THEN the alert rules are re-published, compressed
    published = _published_rules(state_out, relation)
    with pytest.raises(json.JSONDecodeError):
        json.loads(published)
    assert _decode_alert_rules(published).get("groups")


def test_consumer_follower_does_not_publish_rules(
    consumer_ctx: Context[RemoteWriteConsumerCharm],
):
    # GIVEN a non-leader unit and a provider that advertises support for compression
    relation = Relation("send-remote-write", remote_app_data=LZMA_ADVERTISED)
    state = State(relations={relation, PeerRelation("peers")}, leader=False, model=MODEL)

    # WHEN the relation is joined
    state_out = consumer_ctx.run(consumer_ctx.on.relation_joined(relation), state)

    # THEN nothing is written to the application databag
    assert ALERT_RULES_KEY not in _get_relation(state_out, relation).local_app_data


# --- Provider: advertising the encodings it can read ---


@pytest.mark.parametrize("event_name", ["relation_created", "relation_joined"])
def test_provider_advertises_encodings_on_relation_events(
    provider_ctx: Context[RemoteWriteProviderCharm], event_name: str
):
    # GIVEN a leader provider unit
    relation = Relation("receive-remote-write")
    state = State(relations={relation}, leader=True, model=MODEL)

    # WHEN a consumer relates
    state_out = provider_ctx.run(
        getattr(provider_ctx.on, event_name)(relation),
        state,
    )

    # THEN the encodings this library can read are advertised
    advertised = _get_relation(state_out, relation).local_app_data[ALERT_RULES_ENCODINGS_KEY]
    assert json.loads(advertised) == list(SUPPORTED_ALERT_RULES_ENCODINGS)


@pytest.mark.parametrize("event_name", ["upgrade_charm", "leader_elected"])
def test_provider_advertises_encodings_after_upgrade_and_leader_election(
    provider_ctx: Context[RemoteWriteProviderCharm], event_name: str
):
    # GIVEN an existing relation with nothing advertised, e.g. because the relation was
    # created before the provider was upgraded to a library version that can read
    # compressed alert rules
    relation = Relation("receive-remote-write")
    state = State(relations={relation}, leader=True, model=MODEL)

    # WHEN the charm is upgraded, or a new leader is elected
    state_out = provider_ctx.run(getattr(provider_ctx.on, event_name)(), state)

    # THEN the encodings this library can read are advertised
    advertised = _get_relation(state_out, relation).local_app_data[ALERT_RULES_ENCODINGS_KEY]
    assert json.loads(advertised) == list(SUPPORTED_ALERT_RULES_ENCODINGS)


def test_provider_follower_does_not_advertise_encodings(
    provider_ctx: Context[RemoteWriteProviderCharm],
):
    # GIVEN a non-leader provider unit
    relation = Relation("receive-remote-write")
    state = State(relations={relation}, leader=False, model=MODEL)

    # WHEN a consumer relates
    state_out = provider_ctx.run(provider_ctx.on.relation_joined(relation), state)

    # THEN nothing is advertised, because only the leader can write to app data
    assert ALERT_RULES_ENCODINGS_KEY not in _get_relation(state_out, relation).local_app_data


# --- Provider: reading the alert rules ---


@pytest.mark.parametrize(
    "published",
    [
        pytest.param(json.dumps(ALERT_RULES), id="plain_json"),
        pytest.param(LZMABase64.compress(json.dumps(ALERT_RULES)), id="compressed"),
        pytest.param(
            json.dumps(LZMABase64.compress(json.dumps(ALERT_RULES))),
            id="json_encoded_compressed",
        ),
    ],
)
@patch_cos_tool_path
def test_provider_reads_alert_rules_in_any_encoding(
    provider_ctx: Context[RemoteWriteProviderCharm], published: str
):
    # GIVEN a consumer that published its alert rules, compressed or not
    relation = Relation("receive-remote-write", remote_app_data={ALERT_RULES_KEY: published})
    state = State(relations={relation}, leader=True, model=MODEL)

    # WHEN the provider reads the alerts
    with provider_ctx(provider_ctx.on.update_status(), state) as mgr:
        mgr.run()
        alerts = mgr.charm.remote_write_provider.alerts

    # THEN the rules are keyed by the consumer's topology identifier
    assert list(alerts) == ["test-model_e674af04_consumer-tester"]
    # AND no rule was dropped
    assert alerts["test-model_e674af04_consumer-tester"] == ALERT_RULES


@patch_cos_tool_path
def test_provider_skips_relations_with_unreadable_alert_rules(
    provider_ctx: Context[RemoteWriteProviderCharm],
):
    # GIVEN a consumer that published alert rules in an encoding the provider cannot read
    unreadable = Relation(
        "receive-remote-write", remote_app_data={ALERT_RULES_KEY: "!!! not rules !!!"}
    )
    readable = Relation(
        "receive-remote-write", remote_app_data={ALERT_RULES_KEY: json.dumps(ALERT_RULES)}
    )
    state = State(relations={unreadable, readable}, leader=True, model=MODEL)

    # WHEN the provider reads the alerts
    with provider_ctx(provider_ctx.on.update_status(), state) as mgr:
        mgr.run()
        alerts = mgr.charm.remote_write_provider.alerts

    # THEN the unreadable rules are skipped instead of breaking the provider
    # AND the rules of the other consumers are still returned
    assert list(alerts) == ["test-model_e674af04_consumer-tester"]


@patch_cos_tool_path
def test_compressed_rules_published_by_the_consumer_are_read_by_the_provider(
    consumer_ctx: Context[RemoteWriteConsumerCharm],
    provider_ctx: Context[RemoteWriteProviderCharm],
):
    # GIVEN a consumer related to a provider that advertises support for compression
    consumer_relation = Relation("send-remote-write", remote_app_data=LZMA_ADVERTISED)
    consumer_state = State(
        relations={consumer_relation, PeerRelation("peers")},
        leader=True,
        model=MODEL,
    )

    # WHEN the consumer publishes its compressed alert rules
    consumer_state_out = consumer_ctx.run(
        consumer_ctx.on.relation_joined(consumer_relation), consumer_state
    )
    published = _published_rules(consumer_state_out, consumer_relation)

    # AND the provider reads them back
    provider_relation = Relation(
        "receive-remote-write", remote_app_data={ALERT_RULES_KEY: published}
    )
    with provider_ctx(
        provider_ctx.on.update_status(),
        State(relations={provider_relation}, leader=True, model=MODEL),
    ) as mgr:
        mgr.run()
        alerts = mgr.charm.remote_write_provider.alerts

        # AND no validation error was reported back to the consumer
        assert not mgr.charm.remote_write_provider.has_invalid_alert_rules()

    # THEN the provider ends up with the rules the consumer published
    assert alerts
    published_groups = {
        group["name"] for group in _decode_alert_rules(published).get("groups", [])
    }
    read_groups = {group["name"] for rules in alerts.values() for group in rules["groups"]}
    assert published_groups == read_groups
