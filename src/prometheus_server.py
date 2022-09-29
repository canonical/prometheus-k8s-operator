# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

"""Helper for interacting with Prometheus throughout the charm's lifecycle."""

import logging
from typing import Union
from urllib.parse import urljoin

import requests
from requests.exceptions import ConnectionError, ConnectTimeout, ReadTimeout

logger = logging.getLogger(__name__)


class Prometheus:
    """A class that represents a running instance of Prometheus."""

    def __init__(
        self,
        host: str = "localhost",
        port: int = 9090,
        web_route_prefix: str = "",
        api_timeout=2.0,
    ):
        """Utility to manage a Prometheus application.

        Args:
            host: Optional; host address of Prometheus application.
            port: Optional; port on which Prometheus service is exposed.
            web_route_prefix: Optional; the root path added to the Prometheus API path, e.g.,
              when we relate to an ingress.
            api_timeout: Optional; timeout (in seconds) to observe when interacting with the API.
        """
        web_route_prefix = web_route_prefix.lstrip("/").rstrip("/")
        self.base_url = f"http://{host.rstrip('/')}:{port}/" + web_route_prefix
        if not self.base_url.endswith("/"):
            self.base_url += "/"

        self.api_timeout = api_timeout

    def reload_configuration(self) -> Union[bool, str]:
        """Send a POST request to hot-reload the config.

        This reduces down-time compared to restarting the service.

        Returns:
          True if reload succeeded (returned 200 OK);
          "read_timeout" on a read timeout.
          False on error.
        """
        url = urljoin(self.base_url, "-/reload")
        try:
            response = requests.post(url, timeout=self.api_timeout)

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
        url = urljoin(self.base_url, "api/v1/status/buildinfo")

        try:
            response = requests.get(url, timeout=self.api_timeout)

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
