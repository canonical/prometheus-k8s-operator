#!/usr/bin/env python3
# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

import logging

import aiohttp
from prometheus_api_client import PrometheusConnect

logger = logging.getLogger(__name__)


class Prometheus:
    """A class that represents a running instance of Prometheus."""

    def __init__(self, host="localhost", port=9090):
        """Utility to manage a Prometheus application.

        Args:
            host: Optional; host address of Prometheus application.
            port: Optional; port on which Prometheus service is exposed.
        """
        self.base_url = f"http://{host}:{port}"

    async def is_ready(self) -> bool:
        """Send a GET request to check readiness.

        Returns:
          True if Prometheus is ready (returned 200 OK); False otherwise.
        """
        url = f"{self.base_url}/-/ready"
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as response:
                return response.status == 200

    async def config(self) -> str:
        """Send a GET request to get Prometheus configuration.

        Returns:
          YAML config in string format or empty string
        """
        url = f"{self.base_url}/api/v1/status/config"
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as response:
                result = await response.json()
                return result["data"]["yaml"] if result["status"] == "success" else ""

    async def rules(self) -> list:
        """Send a GET request to get Prometheus rules.

        Returns:
          Rule Groups list or empty list
        """
        url = f"{self.base_url}/api/v1/rules"
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as response:
                result = await response.json()
                return result["data"]["groups"] if result["status"] == "success" else []

    async def run_promql(self, query: str, disable_ssl: bool = True) -> list:
        prometheus = PrometheusConnect(url=self.base_url, disable_ssl=disable_ssl)
        return prometheus.custom_query(query=query)
