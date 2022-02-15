# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

"""Helper for interacting with Prometheus throughout the charm's lifecycle."""

import logging

from requests import Session, get
from requests.adapters import HTTPAdapter
from requests.exceptions import ConnectionError, ConnectTimeout, HTTPError, ReadTimeout
from requests.packages.urllib3.exceptions import MaxRetryError  # type: ignore
from requests.packages.urllib3.util.retry import Retry  # type: ignore

logger = logging.getLogger(__name__)


class Prometheus:
    """A class that represents a running instance of Prometheus."""

    def __init__(self, host: str = "localhost", port: int = 9090, api_timeout=2.0):
        """Utility to manage a Prometheus application.

        Args:
            host: Optional; host address of Prometheus application.
            port: Optional; port on which Prometheus service is exposed.
            api_timeout: Optional; timeout (in seconds) to observe when interacting with the API.
        """
        self.base_url = f"http://{host}:{port}"
        self.api_timeout = api_timeout

    def reload_configuration(self) -> bool:
        """Send a POST request to to hot-reload the config.

        This reduces down-time compared to restarting the service.

        Returns:
          True if reload succeeded (returned 200 OK); False otherwise.
        """
        url = f"{self.base_url}/-/reload"
        # http status codes see:
        # https://www.iana.org/assignments/http-status-codes/http-status-codes.xhtml
        http_errors_codes = list(range(400, 452)) + list(range(500, 512))
        retries = 5
        try:
            s = Session()
            retry = Retry(
                total=retries,
                read=retries,
                connect=retries,
                backoff_factor=0.1,
                status_forcelist=http_errors_codes,
            )
            s.mount("http://", HTTPAdapter(max_retries=retry))
            response = s.post(url)
            response.raise_for_status()

            if response.status_code == 200:
                return True
        except (ConnectionError, ConnectTimeout, ReadTimeout, HTTPError, MaxRetryError) as e:
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
