# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Feature: the self-monitoring scrape job is always in-cluster.

Regardless of whether prometheus is ingressed, and regardless of the scheme the ingress is
serving, the scrape job prometheus hands out over "self-metrics-endpoint" must point at the
workload itself (unit FQDN and workload port), with the scheme reflecting the workload's own TLS
configuration.

See https://github.com/canonical/prometheus-k8s-operator/issues/870.
"""

import json
from unittest.mock import patch

import pytest
import yaml
from ops.testing import PeerRelation, Relation, State

from charm import PrometheusCharm, TLSConfig

CA_CERT = "-----BEGIN CERTIFICATE-----\nca\n-----END CERTIFICATE-----"
FQDN = "prometheus-k8s-0.prometheus-k8s-endpoints.test-model.svc.cluster.local"
PORT = 9090
INGRESS_HOST = "traefik.example.com"
INGRESS_PATH = "/test-model-prometheus-k8s-0"


@pytest.fixture(autouse=True)
def fqdn():
    """Pretend we have a k8s-style FQDN, as we would in a real deployment."""
    with patch("socket.getfqdn", new=lambda *_: FQDN):
        yield


@pytest.fixture
def tls(request):
    """Optionally make TLS certs available to the charm (request.param is a bool)."""
    enabled = request.param
    tls_config = TLSConfig("server-cert", CA_CERT, "private-key") if enabled else None
    # `_update_cert` is patched out because it writes to, and refreshes, the charm container's
    # trust store, which is not something this test is concerned with.
    with patch.object(
        PrometheusCharm, "_tls_config", property(lambda _: tls_config)
    ), patch.object(PrometheusCharm, "_update_cert"):
        yield enabled


def ingress_relation(scheme: str) -> Relation:
    """An ingress relation with traefik serving the given scheme."""
    return Relation(
        "ingress",
        remote_app_name="traefik",
        remote_app_data={
            "ingress": yaml.safe_dump({
                "prometheus-k8s/0": {"url": f"{scheme}://{INGRESS_HOST}{INGRESS_PATH}"}
            })
        },
    )


def scrape_jobs_of(state: State) -> list:
    relation = state.get_relations("self-metrics-endpoint")[0]
    return json.loads(relation.local_app_data["scrape_jobs"])


def unit_data_of(state: State) -> dict:
    relation = state.get_relations("self-metrics-endpoint")[0]
    return dict(relation.local_unit_data)


@pytest.mark.parametrize("tls", (False, True), indirect=True, ids=("prom_http", "prom_https"))
@pytest.mark.parametrize("ingress", (None, "http", "https"))
def test_self_scrape_job_is_in_cluster(context, prometheus_container, tls, ingress):
    # GIVEN prometheus is (optionally) ingressed, with the ingress serving `ingress` scheme,
    # AND prometheus itself is serving http or https (the `tls` fixture)
    self_metrics = Relation("self-metrics-endpoint", remote_app_name="otelcol")
    relations = [self_metrics, PeerRelation("prometheus-peers")]
    if ingress:
        relations.append(ingress_relation(ingress))
    state = State(leader=True, containers={prometheus_container}, relations=relations)

    # WHEN any event is emitted
    out = context.run(context.on.update_status(), state)

    # THEN the scrape job points at the workload itself, over the workload's own scheme
    expected_scheme = "https" if tls else "http"
    jobs = scrape_jobs_of(out)
    assert len(jobs) == 1
    assert jobs[0]["scheme"] == expected_scheme
    assert jobs[0]["static_configs"] == [{"targets": [f"{FQDN}:{PORT}"]}]

    # AND the CA cert is included if, and only if, prometheus is serving https
    if tls:
        assert jobs[0]["tls_config"] == {"ca_file": CA_CERT}
    else:
        assert "tls_config" not in jobs[0]

    # AND the unit databag does not route the scraper through the ingress
    # (an empty path is written as an absent key, since juju deletes empty values)
    unit_data = unit_data_of(out)
    assert unit_data.get("prometheus_scrape_unit_path", "") == ""
    assert unit_data["prometheus_scrape_unit_fqdn"] == FQDN
    assert INGRESS_HOST not in unit_data["prometheus_scrape_unit_address"]


@pytest.mark.parametrize("tls", (False, True), indirect=True, ids=("prom_http", "prom_https"))
@pytest.mark.parametrize("ingress_scheme", ("http", "https"))
def test_ingress_scheme_does_not_leak_into_scrape_job(
    context, prometheus_container, tls, ingress_scheme
):
    # GIVEN prometheus is ingressed
    self_metrics = Relation("self-metrics-endpoint", remote_app_name="otelcol")
    state = State(
        leader=True,
        containers={prometheus_container},
        relations=[
            self_metrics,
            PeerRelation("prometheus-peers"),
            ingress_relation(ingress_scheme),
        ],
    )

    # WHEN any event is emitted
    out = context.run(context.on.update_status(), state)

    # THEN the ingress url is still used as the workload's external url
    container = out.get_container("prometheus")
    command = container.layers["prometheus"].services["prometheus"].command
    assert f"--web.external-url={ingress_scheme}://{INGRESS_HOST}{INGRESS_PATH}" in command

    # AND YET neither the ingress' scheme nor its ports (80/443) made it into the scrape job
    jobs = scrape_jobs_of(out)
    assert jobs[0]["scheme"] == ("https" if tls else "http")
    targets = jobs[0]["static_configs"][0]["targets"]
    assert targets == [f"{FQDN}:{PORT}"]

