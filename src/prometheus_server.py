# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

"""Helper for interacting with Prometheus throughout the charm's lifecycle."""

import logging
from urllib.parse import urljoin

from requests import get, post
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
        if web_route_prefix and not web_route_prefix.endswith("/"):
            # If we do not add the '/' and the end, we will lose the last
            # bit of the path:
            #
            # BAD:
            #
            # >>> urljoin('http://some/more', 'thing')
            #   'http://some/thing'
            #
            # GOOD:
            #
            # >>> urljoin('http://some/more/', 'thing')
            #   'http://some/more/thing'
            #
            web_route_prefix = f"{web_route_prefix}/"

        self.base_url = urljoin(f"http://{host}:{port}", web_route_prefix)
        logger.error(f"Base URL: {self.base_url}")
        self.api_timeout = api_timeout

    def reload_configuration(self) -> bool:
        """Send a POST request to to hot-reload the config.

        This reduces down-time compared to restarting the service.

        Returns:
          True if reload succeeded (returned 200 OK); False otherwise.
        """
        url = urljoin(self.base_url, "-/reload")
        try:
            response = post(url, timeout=self.api_timeout)

            if response.status_code == 200:
                return True
        except (ConnectionError, ConnectTimeout, ReadTimeout) as e:
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
            response = get(url, timeout=self.api_timeout)

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
