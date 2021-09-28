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

from typing import List, Optional, Union

from ops.charm import CharmBase
from ops.framework import Object
from ops.model import BlockedStatus


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
    def endpoints(self) -> List[str]:
        """A list of remote write endpoints.

        Returns:
            A list of remote write endpoints.
        """
        endpoints = []
        for relation in self.model.relations[self._relation_name]:
            for unit in relation.units:
                # If external-address is provided use that, else use ingress-address
                if (address := relation.data[unit].get("address")) is None:
                    continue
                if (port := relation.data[unit].get("port")) is None:
                    continue
                endpoints.append(f"http://{address}:{port}/api/v1/write")
        return endpoints

    @property
    def configs(self) -> list:
        """A config object ready to be dropped in to a prometheus config file.

        Returns:
            A list of remote_write configs.
        """
        return [{"url": endpoint} for endpoint in self.endpoints]


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

    def set_endpoint(
        self,
        port: Union[str, int],
        address: Optional[str] = None,
        ingress_relation: Optional[str] = None,
        ingress_address: Optional[str] = None,
    ) -> None:
        """Set the address and port on which you will serve prometheus remote write.

        If address is provided, all automatic logic will be skipped and the address provided will
        be used. Otherwise the method will attempt to use the ingress information if it is
        provided. Finally it will fall back to a predictable hostname if neither of the other two
        methods worked.

        Args:
            port: The port number
            address: The address of the remote write server
            ingress_relation: The name of the ingress relation to use
            ingress_address: The ingress address
        """
        if not address:
            # Remote write needs to address each individual pod but the ingress relation does not
            # expose pods. Thus we can only use the ingress relation if scale is 1 at the moment
            if (
                ingress_relation is not None
                and ingress_address is not None
                and self.model.relations[ingress_relation]
            ):
                if self._charm.app.planned_units() > 1:
                    self._charm.unit.status = BlockedStatus(
                        "Ingress does not support scale greater than 1"
                    )
                    return
                address = ingress_address
            else:
                address = f"{self._charm.unit.name.replace('/','-')}.{self._charm.app.name}-endpoints.{self._charm.model.name}.svc.cluster.local"
        for relation in self.model.relations[self._relation_name]:
            relation.data[self._charm.unit]["address"] = address
            relation.data[self._charm.unit]["port"] = str(port)
