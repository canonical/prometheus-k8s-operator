import json
import urllib3


class Prometheus:
    def __init__(self, host, port):
        """Utility to manage a Prometheus application.
        Args:
            host: host address of Prometheus application.
            port: port on which Prometheus service is exposed.
        """
        self.host = host
        self.port = port
        self.http = urllib3.PoolManager()

    def build_info(self):
        """Fetch build information from Prometheus.

        Returns:
            a dictionary containing build information (for instance
            version) of the Prometheus application. If the Prometheus
            instance is not reachable then an empty dictionary is
            returned.
        """
        api_path = "api/v1/status/buildinfo"
        url = "http://{}:{}/{}".format(self.host, self.port, api_path)

        try:
            response = self.http.request("GET", url)
        except urllib3.exceptions.MaxRetryError:
            return {}

        info = json.loads(response.data.decode("utf-8"))
        if info["status"] == "success":
            return info["data"]
        else:
            return {}
