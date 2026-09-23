#!/usr/bin/env python3
# Copyright 2026 Canonical Ltd.
# See LICENSE file for licensing details.
"""Prometheus is exposed through a Traefik door and checked by otelcol.

First a one-time deployment wires up:

* Prometheus, the metrics database.
* otelcol, a monitoring bot that reads Prometheus' self-metrics and posts them back
  into Prometheus (so we can check the round trip in Prometheus' own database).
* Traefik, the public door in front of Prometheus.
* Two signers that mint the encryption certificates: one for Prometheus
  (ssc-prom), one for Traefik (ssc-traefik).

The four small tests below are a checklist. Each one changes how much encryption is
turned on, then verifies the same simple thing and proves it is the *new* configuration
that works: we first record the newest round-trip sample currently in Prometheus'
database (``up{juju_application="prometheus"}``), apply the change, then wait for a
sample that is both successful (value ``1``) and strictly newer. Only otelcol can create
it, so it must have scraped Prometheus through the Traefik door with the new setup.

  1. encryption off everywhere
  2. encryption on Prometheus only
  3. encryption on Prometheus and Traefik
  4. encryption on Traefik only  (the case that was broken, issue #870)
"""

import jubilant
import pytest
import requests
from helpers import has_new_success_scrape, oci_image, parse_up_samples
from observability_clients import Prometheus

APP = "prometheus"
OTEL = "otelcol"
TRAEFIK = "traefik"
PROM_CA = "ssc-prom"
TRAEFIK_CA = "ssc-traefik"
PROMETHEUS_RESOURCES = {"prometheus-image": oci_image("./charmcraft.yaml", "prometheus-image")}


def _self_up_samples(juju: jubilant.Juju) -> list[tuple[float, float]]:
    """Newest ``(timestamp, value)`` of every self-metrics ``up`` series in the DB.

    Returns an empty list when Prometheus is unreachable right now (the caller retries),
    or when the response is not the expected instant-vector shape (also retry).
    """
    address = juju.status().apps[APP].units[f"{APP}/0"].address
    for scheme in ("https", "http"):
        try:
            requests.get(f"{scheme}://{address}:9090", timeout=30, verify=False)
        except requests.RequestException:
            continue
        try:
            result = Prometheus(url=f"{scheme}://{address}:9090").query(
                f'up{{juju_application="{APP}"}}'
            )
        except requests.RequestException:
            return []
        return parse_up_samples(result)
    return []


def _self_up_timestamp(juju: jubilant.Juju) -> float:
    """Newest sample timestamp of the self-metrics ``up`` series (0.0 if none yet)."""
    samples = _self_up_samples(juju)
    return max((timestamp for timestamp, _ in samples), default=0.0)


def _monitorable(juju: jubilant.Juju, previously_seen: float) -> bool:
    """Whether a successful sample strictly newer than ``previously_seen`` arrived."""
    return has_new_success_scrape(_self_up_samples(juju), previously_seen)


def _check(juju: jubilant.Juju, previously_seen: float) -> None:
    """Wait for a new successful round trip to reach Prometheus (give up after 5 min)."""
    juju.wait(lambda _status: _monitorable(juju, previously_seen), timeout=300, delay=10)


@pytest.mark.abort_on_fail
def test_setup(juju: jubilant.Juju, prometheus_charm):
    """Deploy everything and wire the otelcol round trip plus the Traefik door."""
    juju.deploy(prometheus_charm, app=APP, resources=PROMETHEUS_RESOURCES, trust=True)
    juju.deploy(
        "opentelemetry-collector-k8s",
        app=OTEL,
        channel="2/edge",
        trust=True,
        config={"global_scrape_interval": "5s", "tls_insecure_skip_verify": True},
    )
    juju.deploy("traefik-k8s", app=TRAEFIK, channel="edge", trust=True)
    juju.deploy("self-signed-certificates", app=PROM_CA, channel="1/stable", trust=True)
    juju.deploy("self-signed-certificates", app=TRAEFIK_CA, channel="1/stable", trust=True)

    juju.integrate(f"{APP}:self-metrics-endpoint", f"{OTEL}:metrics-endpoint")
    juju.integrate(f"{OTEL}:send-remote-write", f"{APP}:receive-remote-write")
    juju.integrate(f"{APP}:ingress", TRAEFIK)

    _check(juju, previously_seen=0.0)


@pytest.mark.abort_on_fail
def test_encryption_off(juju: jubilant.Juju):
    """Scenario 1: no encryption anywhere."""
    _check(juju, _self_up_timestamp(juju))


@pytest.mark.abort_on_fail
def test_encryption_on_prometheus_only(juju: jubilant.Juju):
    """Scenario 2: Prometheus encrypts, Traefik stays plain (give Traefik the CA)."""
    previously_seen = _self_up_timestamp(juju)
    juju.integrate(f"{APP}:certificates", f"{PROM_CA}:certificates")
    juju.integrate(f"{TRAEFIK}:receive-ca-cert", f"{PROM_CA}:send-ca-cert")
    _check(juju, previously_seen)


@pytest.mark.abort_on_fail
def test_encryption_everywhere(juju: jubilant.Juju):
    """Scenario 3: Prometheus and Traefik both encrypt."""
    previously_seen = _self_up_timestamp(juju)
    juju.integrate(f"{TRAEFIK}:certificates", f"{TRAEFIK_CA}:certificates")
    _check(juju, previously_seen)


@pytest.mark.abort_on_fail
def test_encryption_on_traefik_only(juju: jubilant.Juju):
    """Scenario 4: Traefik still encrypts, Prometheus goes back to plain HTTP."""
    previously_seen = _self_up_timestamp(juju)
    juju.remove_relation(f"{APP}:certificates", PROM_CA)
    _check(juju, previously_seen)
