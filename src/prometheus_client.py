# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

"""Helper for interacting with Prometheus throughout the charm's lifecycle."""

import logging
from typing import Union, Literal, List

import requests
from requests.exceptions import ConnectionError, ConnectTimeout, ReadTimeout

logger = logging.getLogger(__name__)


class Prometheus:
    """A class that represents a running instance of Prometheus."""

    def __init__(
        self,
        endpoint_url: str = "http://localhost:9090",
        api_timeout=2.0,
    ):
        """Utility to manage a Prometheus application.

        Args:
            endpoint_url: Prometheus endpoint URL.
            api_timeout: Timeout (in seconds) to observe when interacting with the API.
        """
        # Make sure the URL str does not end with a '/'
        self.base_url = endpoint_url.rstrip("/")
        self.api_timeout = api_timeout

    def reload_configuration(self) -> Union[bool, str]:
        """Send a POST request to hot-reload the config.

        This reduces down-time compared to restarting the service.

        Returns:
          True if reload succeeded (returned 200 OK);
          "read_timeout" on a read timeout.
          False on error.
        """
        url = f"{self.base_url}/-/reload"
        try:
            response = requests.post(url, timeout=self.api_timeout, verify=False)

            if response.status_code == 200:
                return True
        except ReadTimeout as e:
            logger.info("config reload timed out via {}: {}".format(url, str(e)))
            return "read_timeout"
        except (ConnectionError, ConnectTimeout) as e:
            logger.error("config reload error via %s: %s", url, str(e))

        return False

    def _build_info(self) -> dict:
        """Fetch build information from Prometheus.

        Returns:
            a dictionary containing build information (for instance
            version) of the Prometheus application. If the Prometheus
            instance is not reachable then an empty dictionary is
            returned.
        """
        url = f"{self.base_url}/api/v1/status/buildinfo"

        try:
            response = requests.get(url, timeout=self.api_timeout, verify=False)

            if response.status_code == 200:
                info = response.json()
                if info and info["status"] == "success":
                    return info["data"]
        except Exception:
            # Nothing worth logging, seriously
            pass

        return {}

    def version(self) -> str:
        """Fetch Prometheus server version.

        Returns:
            a string consisting of the Prometheus version information or
            empty string if Prometheus server is not reachable.
        """
        info = self._build_info()
        return info.get("version", "")

    def is_ready(self) -> bool:
        """Send a GET request to check readiness.

        Returns:
          True if Prometheus is ready (returned 200 OK); False otherwise.
        """
        url = f"{self.base_url}/-/ready"
        response = requests.get(url, timeout=self.api_timeout, verify=False)
        return response.status_code == 200

    def config(self) -> str:
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
        response = requests.get(url, timeout=self.api_timeout, verify=False)
        result = response.json()
        return result["data"]["yaml"] if result["status"] == "success" else ""

    def rules(self, rules_type: Literal["alert", "record"] = None) -> list:
        """Send a GET request to get Prometheus rules.

        Args:
          rules_type: the type of rules to fetch, or all types if not provided.

        Returns:
          Rule Groups list or empty list
        """
        url = f"{self.base_url}/api/v1/rules{'?type=' + rules_type if rules_type else ''}"
        response = requests.get(url, timeout=self.api_timeout, verify=False)
        result = response.json()
        # response looks like this:
        # {"status":"success","data":{"groups":[]}
        return result["data"]["groups"] if result["status"] == "success" else []

    def labels(self) -> List[str]:
        """Send a GET request to get labels.

        Returns:
          List of labels
        """
        url = f"{self.base_url}/api/v1/labels"
        response = requests.get(url, timeout=self.api_timeout, verify=False)
        result = response.json()

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

    def alerts(self) -> List[dict]:
        """Send a GET request to get alerts.

        Returns:
          List of alerts
        """
        url = f"{self.base_url}/api/v1/alerts"
        response = requests.get(url, timeout=self.api_timeout, verify=False)
        result = response.json()

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

    def active_targets(self) -> List[dict]:
        """Send a GET request to get active scrape targets.

        Returns:
          A lists of targets.
        """
        url = f"{self.base_url}/api/v1/targets"
        response = requests.get(url, timeout=self.api_timeout, verify=False)
        result = response.json()

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

    def tsdb_head_stats(self) -> dict:
        """Send a GET request to get the TSDB headStats.

        Returns:
          The headStats dict.
        """
        url = f"{self.base_url}/api/v1/status/tsdb"
        response = requests.get(url, timeout=self.api_timeout, verify=False)
        result = response.json()

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

    def run_promql(self, query: str, disable_ssl: bool = True) -> list:
        url = f"{self.base_url}/api/v1/query"
        response = requests.get(url, timeout=self.api_timeout, verify=False, params={"query": query})
        result = response.json()
        return result
