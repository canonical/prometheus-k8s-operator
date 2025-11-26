"""Feature: Prometheus can form TLS connections with HTTPS servers."""

import json
import logging
import time

import jubilant
from helpers import oci_image
from requests import request

logger = logging.getLogger(__name__)


PROMETHEUS_RESOURCES = {"prometheus-image": oci_image("./charmcraft.yaml", "prometheus-image")}


async def test_unknown_authority(juju: jubilant.Juju, prometheus_charm: str):
    """Scenario: Prometheus fails to scrape metrics from a server signed by unknown authority."""
    # GIVEN a scrape target signed by a self-signed certificate
    # WHEN related to prometheus
    juju.deploy("alertmanager-k8s", app="am", channel="2/edge", trust=True)
    juju.deploy("self-signed-certificates", app="ca", channel="1/stable", trust=True)
    juju.deploy(prometheus_charm, app="prom", resources=PROMETHEUS_RESOURCES, trust=True)
    juju.integrate("am:certificates", "ca:certificates")
    juju.integrate("am:self-metrics-endpoint", "prom:metrics-endpoint")
    juju.wait(jubilant.all_active, delay=10, timeout=600)

    logger.info("Waiting for scrape interval (1 minute) to elapse...")
    scrape_interval = 60  # seconds!
    lookback_window = scrape_interval + 10  # seconds!
    time.sleep(lookback_window)

    # THEN scrape fails
    prom_ip = juju.status().apps["prom"].units["prom/0"].address
    response = request("GET", f"http://{prom_ip}:9090/api/v1/targets").text
    data = json.loads(response)["data"]
    for target in data["activeTargets"]:
        if "am" in target["discoveredLabels"]["juju_application"]:
            assert target["health"] == "down"
            assert "x509: certificate signed by unknown authority" in target["lastError"]


def test_with_ca_cert_forwarded(juju: jubilant.Juju):
    """Scenario: Prometheus succeeds to scrape metrics from a server signed by a CA that Prometheus trusts."""
    # WHEN Prometheus trusts the CA that signed the scrape target
    juju.integrate("ca:send-ca-cert", "prom:receive-ca-cert")
    juju.wait(jubilant.all_active, delay=10, timeout=600)

    # Wait for scrape interval (1 minute) to elapse
    scrape_interval = 60  # seconds!
    lookback_window = scrape_interval + 10  # seconds!
    time.sleep(lookback_window)

    # THEN scrape succeeds
    prom_ip = juju.status().apps["prom"].units["prom/0"].address
    response = request("GET", f"http://{prom_ip}:9090/api/v1/targets").text
    data = json.loads(response)["data"]
    for target in data["activeTargets"]:
        if "am" in target["discoveredLabels"]["juju_application"]:
            assert target["health"] == "up"
