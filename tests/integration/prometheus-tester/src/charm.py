#!/usr/bin/env python3
# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

"""A Charm to functionally test the Prometheus Operator."""

import logging

from charms.prometheus_k8s.v0.prometheus_scrape import MetricsEndpointProvider
from ops.charm import CharmBase
from ops.main import main
from ops.model import ActiveStatus, BlockedStatus
from ops.pebble import Layer

logger = logging.getLogger(__name__)


class PrometheusTesterCharm(CharmBase):
    """Charm the service."""

    def __init__(self, *args):
        super().__init__(*args)
        self._name = "prometheus-tester"
        jobs = [
            {
                "scrape_interval": "1s",
                "static_configs": [{"targets": ["*:8000"], "labels": {"status": "testing"}}],
            }
        ]
        self.prometheus = MetricsEndpointProvider(self, jobs=jobs)
        self.framework.observe(
            self.on.prometheus_tester_pebble_ready, self._on_prometheus_tester_pebble_ready
        )
        self.framework.observe(self.on.config_changed, self._on_config_changed)

    def _on_prometheus_tester_pebble_ready(self, event):
        container = event.workload
        layer = self._tester_pebble_layer()
        container.add_layer(self._name, layer, combine=True)
        container.restart(self._name)
        self.unit.status = ActiveStatus()

    def _on_config_changed(self, event):
        container = self.unit.get_container(self._name)
        if not container.can_connect():
            self.unit.status = BlockedStatus("Waiting for Pebble ready")
            event.defer()
            return

        current_services = container.get_plan().services
        new_layer = self._tester_pebble_layer()
        if current_services != new_layer.services:
            container.add_layer(self._name, new_layer, combine=True)
            logger.debug("Added tester layer to container")

            container.restart(self._name)
            logger.info("Restarted tester service")

        self.unit.status = ActiveStatus()

    def _tester_pebble_layer(self):
        layer_spec = {
            "summary": "prometheus tester",
            "description": "a test data generator for Prometheus",
            "services": {
                self._name: {
                    "override": "replace",
                    "summary": "tester service",
                    "command": "python /tester/tester.py",
                    "startup": "enabled",
                }
            },
        }
        return Layer(layer_spec)


if __name__ == "__main__":
    main(PrometheusTesterCharm)
