#!/usr/bin/env python3
# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
from typing import List, Literal

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

        # Set a timeout of 5 second - should be sufficient for all the checks here.
        # The default (5 min) prolongs itests unnecessarily.
        self.timeout = aiohttp.ClientTimeout(total=5)

    async def is_ready(self) -> bool:
        """Send a GET request to check readiness.

        Returns:
          True if Prometheus is ready (returned 200 OK); False otherwise.
        """
        url = f"{self.base_url}/-/ready"

        async with aiohttp.ClientSession(timeout=self.timeout) as session:
            async with session.get(url) as response:
                return response.status == 200

    async def config(self) -> str:
        """Send a GET request to get Prometheus configuration.

        Returns:
          YAML config in string format or empty string
        """
        url = f"{self.base_url}/api/v1/status/config"
        # Response looks like this:
        # {
        #   "status": "success",
        #   "data": {
        #     "yaml": "global:\n
        #       scrape_interval: 1m\n
        #       scrape_timeout: 10s\n
        #       evaluation_interval: 1m\n
        #       rule_files:\n
        #       - /etc/prometheus/rules/juju_*.rules\n
        #       scrape_configs:\n
        #       - job_name: prometheus\n
        #       honor_timestamps: true\n
        #       scrape_interval: 5s\n
        #       scrape_timeout: 5s\n
        #       metrics_path: /metrics\n
        #       scheme: http\n
        #       static_configs:\n
        #       - targets:\n
        #       - localhost:9090\n"
        #   }
        # }
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as response:
                result = await response.json()
                return result["data"]["yaml"] if result["status"] == "success" else ""

    async def rules(self, rules_type: Literal["alert", "record"] = None) -> list:
        """Send a GET request to get Prometheus rules.

        Args:
          rules_type: the type of rules to fetch, or all types if not provided.

        Returns:
          Rule Groups list or empty list
        """
        url = f"{self.base_url}/api/v1/rules{'?type=' + rules_type if rules_type else ''}"
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as response:
                result = await response.json()
                # response looks like this:
                # {"status":"success","data":{"groups":[]}
                return result["data"]["groups"] if result["status"] == "success" else []

    async def labels(self) -> List[str]:
        """Send a GET request to get labels.

        Returns:
          List of labels
        """
        url = f"{self.base_url}/api/v1/labels"
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as response:
                result = await response.json()
                # response looks like this:
                # {
                #   "status": "success",
                #   "data": [
                #     "__name__",
                #     "alertname",
                #     "alertstate",
                #     ...
                #     "juju_application",
                #     "juju_charm",
                #     "juju_model",
                #     "juju_model_uuid",
                #     ...
                #     "version"
                #   ]
                # }
                return result["data"] if result["status"] == "success" else []

    async def alerts(self) -> List[dict]:
        """Send a GET request to get alerts.

        Returns:
          List of alerts
        """
        url = f"{self.base_url}/api/v1/alerts"
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as response:
                result = await response.json()
                # response looks like this:
                #
                # {
                #   "status": "success",
                #   "data": {
                #     "alerts": [
                #       {
                #         "labels": {
                #           "alertname": "AlwaysFiring",
                #           "job": "non_existing_job",
                #           "juju_application": "avalanche-k8s",
                #           "juju_charm": "avalanche-k8s",
                #           "juju_model": "remotewrite",
                #           "juju_model_uuid": "5d2582f6-f8c9-4496-835b-675431d1fafe",
                #           "severity": "High"
                #         },
                #         "annotations": {
                #           "description": " of job non_existing_job is firing the dummy alarm.",
                #           "summary": "Instance  dummy alarm (always firing)"
                #         },
                #         "state": "firing",
                #         "activeAt": "2022-01-13T18:53:12.808550042Z",
                #         "value": "1e+00"
                #       }
                #     ]
                #   }
                # }
                return result["data"]["alerts"] if result["status"] == "success" else []

    async def active_targets(self) -> List[dict]:
        """Send a GET request to get active scrape targets.

        Returns:
          A lists of targets.
        """
        url = f"{self.base_url}/api/v1/targets"
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as response:
                result = await response.json()
                # response looks like this:
                #
                # {
                #   "status": "success",
                #   "data": {
                #     "activeTargets": [
                #       {
                #         "discoveredLabels": {
                #           "__address__": "localhost:9090",
                #           "__metrics_path__": "/metrics",
                #           "__scheme__": "http",
                #           "job": "prometheus"
                #         },
                #         "labels": {
                #           "instance": "localhost:9090",
                #           "job": "prometheus"
                #         },
                #         "scrapePool": "prometheus",
                #         "scrapeUrl": "http://localhost:9090/metrics",
                #         "globalUrl": "http://prom-0....local:9090/metrics",
                #         "lastError": "",
                #         "lastScrape": "2022-05-12T16:54:19.019386006Z",
                #         "lastScrapeDuration": 0.003985463,
                #         "health": "up"
                #       }
                #     ],
                #     "droppedTargets": []
                #   }
                # }
                return result["data"]["activeTargets"] if result["status"] == "success" else []

    async def tsdb_head_stats(self) -> dict:
        """Send a GET request to get the TSDB headStats.

        Returns:
          The headStats dict.
        """
        url = f"{self.base_url}/api/v1/status/tsdb"
        async with aiohttp.ClientSession(timeout=self.timeout) as session:
            async with session.get(url) as response:
                result = await response.json()
                # response looks like this:
                #
                # {
                #   "status": "success",
                #   "data": {
                #     "headStats": {
                #       "numSeries": 610,
                #       "numLabelPairs": 367,
                #       "chunkCount": 5702,
                #       "minTime": 1652720232481,
                #       "maxTime": 1652724527481
                #     },
                #     "seriesCountByMetricName": [ ... ]
                #     ...
                #   }
                # }
                return result["data"]["headStats"] if result["status"] == "success" else {}

    async def run_promql(self, query: str, disable_ssl: bool = True) -> list:
        prometheus = PrometheusConnect(url=self.base_url, disable_ssl=disable_ssl)
        return prometheus.custom_query(query=query)
