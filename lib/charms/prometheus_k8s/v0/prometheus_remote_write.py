# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.
"""This library facilitates the prometheus_remote_write interface.

For the provider charm no communication is necesssary. For the consumer charm,
instantite a PrometheusRemoteWriteConsumer in the __init__ method of your charm
class:

```
from charms.prometheus_k8s.v0.prometheus_remote_write import PrometheusRemoteWriteConsumer

def __init__(self, *args):
    ...
    self.remote_write = PrometheusRemoteWriteConsumer(self, "remote-write")
    ...
```

Then access the endpoints with:
`self.remote_write.endpoints`
or access a prometheus style config object with:
`self.remote_write.configs`
"""

from typing import Generator, Union

from ops.charm import CharmBase
from ops.framework import Object


class PrometheusRemoteWriteConsumer(Object):
    """A prometheus remote write consumer."""

    def __init__(self, charm: CharmBase, relation_name: str):
        """A prometheus remote write consumer.

        Args:
            charm: The charm object that instantiated this class.
            relation_name: The relation name as defined in metadata.yaml.
        """
        super().__init__(charm, relation_name)
        self._relation_name = relation_name

    @property
    def endpoints(self) -> Generator[str, None, None]:
        """A list of remote write endpoints.

        Returns:
            A list of remote write endpoints.
        """
        for relation in self.model.relations[self._relation_name]:
            for unit in relation.units:
                # If external-address is provided use that, else use ingress-address
                if (address := relation.data[unit].get("address")) is None:
                    continue
                if (port := relation.data[unit].get("port")) is None:
                    continue
                yield f"http://{address}:{port}/api/v1/write"

    @property
    def configs(self) -> Generator[dict, None, None]:
        """A config object ready to be dropped in to a prometheus config file.

        Returns:
            A list of remote_write configs.
        """
        for endpoint in self.endpoints:
            yield {"url": endpoint}


class PrometheusRemoteWriteProvider(Object):
    """A prometheus remote write provider."""

    def __init__(self, charm: CharmBase, relation_name: str):
        """A prometheus remote write provider.

        Args:
            charm: The charm object that instantiated this class.
            relation_name: The relation name as defined in metadata.yaml.
        """
        super().__init__(charm, relation_name)
        self._charm = charm
        self._relation_name = relation_name

    def set_endpoint(self, address: str, port: Union[str, int]) -> None:
        """Set the address and port on which you will serve prometheus remote write.

        Args:
            address: The address of the remote write server
            port: The port number
        """
        for relation in self.model.relations[self._relation_name]:
            relation.data[self._charm.unit]["address"] = address
            relation.data[self._charm.unit]["port"] = str(port)
