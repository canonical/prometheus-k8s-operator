import logging
from requests import get, post
from requests.exceptions import ConnectionError, ConnectTimeout
from typing import Dict, Union

logger = logging.getLogger(__name__)


class Prometheus:
    def __init__(self, host: str, port: int, api_timeout=2.0):
        """Utility to manage a Prometheus application.
        Args:
            host: host address of Prometheus application.
            port: port on which Prometheus service is exposed.
        """
        self.base_url = "http://{}:{}".format(host, port)
        self.api_timeout = api_timeout

    def reload_configuration(self) -> bool:
        """Send a POST request to to hot-reload the config.
        This reduces down-time compared to restarting the service.
        Returns:
          True if reload succeeded (returned 200 OK); False otherwise.
        """
        url = "{}/-/reload".format(self.base_url)
        try:
            response = post(url, timeout=self.api_timeout)

            if response.status_code == 200:
                return True
        except (ConnectionError, ConnectTimeout) as e:
            logger.debug("config reload error via %s: %s", url, str(e))

        return False

    def build_info(self):
        """Fetch build information from Prometheus.

        Returns:
            a dictionary containing build information (for instance
            version) of the Prometheus application. If the Prometheus
            instance is not reachable then an empty dictionary is
            returned.
        """
        url = "{}/api/v1/status/buildinfo".format(self.base_url)

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
