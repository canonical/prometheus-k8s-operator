#!/usr/bin/env python3
# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

"""A Charm to functionally test the Prometheus Operator."""

import logging
from pathlib import Path

from ops.charm import CharmBase
from ops.main import main
from ops.model import ActiveStatus, BlockedStatus
from ops.pebble import Layer
from prometheus_scrape import MetricsEndpointProvider

logger = logging.getLogger(__name__)


class PrometheusTesterCharm(CharmBase):
    """A Charm used to test the Prometheus charm."""

    def __init__(self, *args):
        super().__init__(*args)
        self._name = "prometheus-tester"
        self._pip_path = "/usr/local/bin/pip"
        self._metrics_exporter_script = Path("src/metrics.py")
        jobs = [
            {
                "scrape_interval": self.model.config["scrape-interval"],
                "static_configs": [{"targets": ["*:8000"], "labels": {"name": self._name}}],
            }
        ]
        self.prometheus = MetricsEndpointProvider(self, jobs=jobs)
        self.framework.observe(
            self.on.prometheus_tester_pebble_ready, self._on_prometheus_tester_pebble_ready
        )
        self.framework.observe(self.on.config_changed, self._on_config_changed)

    def _on_prometheus_tester_pebble_ready(self, event):
        """Install the metrics exporter script and its dependencies."""
        container = event.workload

        self._install_prometheus_client()
        metrics_endpoint_script = self._metrics_exporter()
        container.push("/metrics.py", metrics_endpoint_script)
        logger.info("Pushed metrics exporter")

        layer = self._tester_pebble_layer()
        container.add_layer(self._name, layer, combine=True)
        container.restart(self._name)

        self.unit.status = ActiveStatus()

    def _on_config_changed(self, event):
        """Reconfigure the Prometheus tester."""
        container = self.unit.get_container(self._name)
        if not container.can_connect():
            self.unit.status = BlockedStatus("Waiting for Pebble ready")
            return

        self._install_prometheus_client()
        metrics_endpoint_script = self._metrics_exporter()
        container.push("/metrics.py", metrics_endpoint_script)
        logger.info("Pushed metrics exporter")

        current_services = container.get_plan().services
        new_layer = self._tester_pebble_layer()
        if current_services != new_layer.services:
            container.add_layer(self._name, new_layer, combine=True)
            logger.debug("Added tester layer to container")

            container.restart(self._name)
            logger.info("Restarted tester service")

        self.unit.status = ActiveStatus()

    def _tester_pebble_layer(self):
        """Generate Prometheus tester pebble layer."""
        layer_spec = {
            "summary": "prometheus tester",
            "description": "a test data generator for Prometheus",
            "services": {
                self._name: {
                    "override": "replace",
                    "summary": "metrics exporter service",
                    "command": "python /metrics.py",
                    "startup": "enabled",
                }
            },
        }
        return Layer(layer_spec)

    def _install_prometheus_client(self):
        """Install Prometheus tester dependencies."""
        container = self.unit.get_container(self._name)
        if not container.can_connect():
            self.unit.status = BlockedStatus("Waiting for Pebble ready")
            return

        process = container.exec([self._pip_path, "install", "prometheus_client"])
        process.wait()
        logger.debug("Installed prometheus client")

    def _metrics_exporter(self):
        """Generate the metrics exporter script."""
        with self._metrics_exporter_script.open() as script:
            return script.read()


if __name__ == "__main__":
    main(PrometheusTesterCharm)
