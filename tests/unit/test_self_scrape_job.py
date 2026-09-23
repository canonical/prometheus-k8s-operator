# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.

"""The self-monitoring scrape job advertises the scheme/port scrapers should use.

That comes from the ingress URL (Traefik) when there is one, not from Prometheus' own TLS:
an ingress serving plain HTTP in front of a TLS-serving Prometheus must advertise HTTP.

See https://github.com/canonical/prometheus-k8s-operator/issues/870.
"""

import json
from unittest.mock import patch
from urllib.parse import urlparse

import pytest
import yaml
from scenario import Relation, State

from charm import PrometheusCharm, TLSConfig

CA_CERT = "ca-cert"
FQDN = "prometheus-k8s-0.prometheus-k8s-endpoints.test-model.svc.cluster.local"
PORT = 9090

# ingress URL -> expected (scheme, port) it should make the scraper use
CASES = {
    "no_ingress": (None, None),
    "ingress_http": ("http://traefik/cos-prom-0", ("http", 80)),
    "ingress_http_port": ("http://traefik:8080/cos-prom-0", ("http", 8080)),
    "ingress_https": ("https://traefik/cos-prom-0", ("https", 443)),
    "ingress_https_port": ("https://traefik:8443/cos-prom-0", ("https", 8443)),
}


@pytest.fixture(autouse=True)
def fqdn():
    with patch("socket.getfqdn", new=lambda *_: FQDN):
        yield


@pytest.fixture
def tls(request):
    config = TLSConfig("server-cert", CA_CERT, "private-key") if request.param else None
    # `_update_cert` writes to disk, so skip it
    with patch.object(PrometheusCharm, "_tls_config", property(lambda _: config)), patch.object(
        PrometheusCharm, "_update_cert"
    ):
        yield request.param


@pytest.mark.parametrize("tls", (False, True), indirect=True, ids=("prom_http", "prom_https"))
@pytest.mark.parametrize("case", CASES)
def test_self_scrape_job_scheme_follows_ingress(context, prometheus_container, tls, case):
    ingress_url, expected = CASES[case]
    expected = expected or (("https" if tls else "http"), PORT)

    # GIVEN prometheus serves http or https, behind an ingress serving its own scheme
    relations = [Relation("self-metrics-endpoint", remote_app_name="otelcol")]
    if ingress_url:
        relations.append(
            Relation(
                "ingress",
                remote_app_name="traefik",
                remote_app_data={"ingress": yaml.safe_dump({"prometheus-k8s/0": {"url": ingress_url}})},
            )
        )

    # WHEN the charm reconciles
    out = context.run(context.on.update_status(), State(leader=True, containers={prometheus_container}, relations=relations))
    rel = out.get_relations("self-metrics-endpoint")[0]
    job = json.loads(rel.local_app_data["scrape_jobs"])[0]

    # THEN the scheme/port follow the ingress (not our own TLS), tls_config only on https-with-certs
    assert job["scheme"] == expected[0]
    assert job["static_configs"] == [{"targets": [f"*:{expected[1]}"]}]
    assert job.get("tls_config") == ({"ca_file": CA_CERT} if tls and expected[0] == "https" else None)

    # AND the target host/path are the ingress's when there is one
    if ingress_url:
        parsed = urlparse(ingress_url)
        assert rel.local_unit_data["prometheus_scrape_unit_address"] == parsed.hostname
        assert rel.local_unit_data["prometheus_scrape_unit_path"] == parsed.path
    else:
        assert rel.local_unit_data.get("prometheus_scrape_unit_path", "") == ""
