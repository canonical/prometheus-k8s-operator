# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""Feature: the self-monitoring scrape job always points at the workload, never at the ingress.

See https://github.com/canonical/prometheus-k8s-operator/issues/870.
"""

import json
from unittest.mock import patch

import pytest
import yaml
from ops.testing import Relation, State

from charm import PrometheusCharm, TLSConfig

CA_CERT = "-----BEGIN CERTIFICATE-----\nca\n-----END CERTIFICATE-----"
FQDN = "prometheus-k8s-0.prometheus-k8s-endpoints.test-model.svc.cluster.local"
PORT = 9090
INGRESS_URL = "{scheme}://traefik.example.com/test-model-prometheus-k8s-0"


@pytest.fixture(autouse=True)
def fqdn():
    """Pretend we have a k8s-style FQDN, as we would in a real deployment."""
    with patch("socket.getfqdn", new=lambda *_: FQDN):
        yield


@pytest.fixture
def tls(request):
    """Make TLS certs (un)available to the charm; `_update_cert` writes to disk, so skip it."""
    tls_config = TLSConfig("server-cert", CA_CERT, "private-key") if request.param else None
    with patch.object(
        PrometheusCharm, "_tls_config", property(lambda _: tls_config)
    ), patch.object(PrometheusCharm, "_update_cert"):
        yield request.param


@pytest.mark.parametrize("tls", (False, True), indirect=True, ids=("prom_http", "prom_https"))
@pytest.mark.parametrize("ingress_scheme", (None, "http", "https"))
def test_self_scrape_job_is_in_cluster(context, prometheus_container, tls, ingress_scheme):
    # GIVEN prometheus serves http or https, behind an ingress that may serve either scheme
    relations = [Relation("self-metrics-endpoint", remote_app_name="otelcol")]
    if ingress_scheme:
        relations.append(
            Relation(
                "ingress",
                remote_app_name="traefik",
                remote_app_data={
                    "ingress": yaml.safe_dump({
                        "prometheus-k8s/0": {"url": INGRESS_URL.format(scheme=ingress_scheme)}
                    })
                },
            )
        )
    state = State(leader=True, containers={prometheus_container}, relations=relations)

    # WHEN the charm reconciles
    out = context.run(context.on.update_status(), state)
    relation = out.get_relations("self-metrics-endpoint")[0]
    job = json.loads(relation.local_app_data["scrape_jobs"])[0]

    # THEN the target is the workload's own FQDN, port and scheme - the ingress plays no part
    internal_url = f"{'https' if tls else 'http'}://{FQDN}:{PORT}"
    assert job["scheme"] == ("https" if tls else "http")
    assert job["static_configs"] == [{"targets": [f"{FQDN}:{PORT}"]}]
    assert job.get("tls_config") == ({"ca_file": CA_CERT} if tls else None)

    # AND the scraper is not pointed at the ingress url either
    assert relation.local_unit_data["prometheus_scrape_unit_fqdn"] == FQDN

    # AND no path is provided since the ingress url is not used for scraping
    assert relation.local_unit_data.get("prometheus_scrape_unit_path", "") == ""

    # AND YET the ingress url is still what prometheus serves its UI on
    command = out.get_container("prometheus").layers["prometheus"].services["prometheus"].command
    external_url = INGRESS_URL.format(scheme=ingress_scheme) if ingress_scheme else internal_url
    assert f"--web.external-url={external_url}" in command
