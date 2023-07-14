# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

"""# Alertmanager library.

This library is designed to be used by a charm consuming or providing the `alertmanager_dispatch`
relation interface.

This library is published as part of the
[Alertmanager charm](https://charmhub.io/alertmanager-k8s).

You can file bugs [here](https://github.com/canonical/alertmanager-operator/issues)!

A typical example of including this library might be:

```python
# ...
from charms.alertmanager_k8s.v0.alertmanager_dispatch import AlertmanagerConsumer

class SomeApplication(CharmBase):
  def __init__(self, *args):
    # ...
    self.alertmanager_consumer = AlertmanagerConsumer(self, relation_name="alertmanager")
    # ...
```
"""
import logging
import socket
from typing import Callable, List, Optional
from urllib.parse import urlparse

import ops
from ops.charm import CharmBase, RelationEvent, RelationJoinedEvent, RelationRole
from ops.framework import EventBase, EventSource, Object, ObjectEvents
from ops.model import Relation

# The unique Charmhub library identifier, never change it
LIBID = "37f1ca6f8fe84e3092ebbf6dc2885310"

# Increment this major API version when introducing breaking changes
LIBAPI = 0

# Increment this PATCH version before using `charmcraft publish-lib` or reset
# to 0 if you are raising the major API version
LIBPATCH = 8

# Set to match metadata.yaml
INTERFACE_NAME = "alertmanager_dispatch"

logger = logging.getLogger(__name__)


class ClusterChanged(EventBase):
    """Event raised when an alertmanager cluster is changed.

    If an alertmanager unit is added to or removed from a relation,
    then a :class:`ClusterChanged` event should be emitted.
    """


class AlertmanagerConsumerEvents(ObjectEvents):
    """Event descriptor for events raised by `AlertmanagerConsumer`."""

    cluster_changed = EventSource(ClusterChanged)


class RelationManagerBase(Object):
    """Base class that represents relation ends ("provides" and "requires").

    :class:`RelationManagerBase` is used to create a relation manager. This is done by inheriting
    from :class:`RelationManagerBase` and customising the subclass as required.

    Attributes:
        name (str): consumer's relation name
    """

    def __init__(self, charm: CharmBase, relation_name: str, relation_role: RelationRole):
        super().__init__(charm, relation_name)
        self.charm = charm
        self._validate_relation(relation_name, relation_role)
        self.name = relation_name

    def _validate_relation(self, relation_name: str, relation_role: RelationRole):
        try:
            if self.charm.meta.relations[relation_name].role != relation_role:
                raise ValueError(
                    "Relation '{}' in the charm's metadata.yaml must be '{}' "
                    "to be managed by this library, but instead it is '{}'".format(
                        relation_name,
                        relation_role,
                        self.charm.meta.relations[relation_name].role,
                    )
                )
            if self.charm.meta.relations[relation_name].interface_name != INTERFACE_NAME:
                raise ValueError(
                    "Relation '{}' in the charm's metadata.yaml must use the '{}' interface "
                    "to be managed by this library, but instead it is '{}'".format(
                        relation_name,
                        INTERFACE_NAME,
                        self.charm.meta.relations[relation_name].interface_name,
                    )
                )
        except KeyError:
            raise ValueError(f"Relation '{relation_name}' is not in the charm's metadata.yaml")


class AlertmanagerConsumer(RelationManagerBase):
    """A "consumer" handler to be used by charms that relate to Alertmanager (the 'requires' side).

    To have your charm consume alertmanager cluster data, declare the interface's use in your
    charm's metadata.yaml file:

    ```yaml
    requires:
      alertmanager:
        interface: alertmanager_dispatch
    ```

    A typical example of importing this library might be

    ```python
    from charms.alertmanager_k8s.v0.alertmanager_dispatch import AlertmanagerConsumer
    ```

    In your charm's `__init__` method:

    ```python
    self.alertmanager_consumer = AlertmanagerConsumer(self, relation_name="alertmanager")
    ```

    Every change in the alertmanager cluster emits a :class:`ClusterChanged` event that the
    consumer charm can register and handle, for example:

    ```
    self.framework.observe(self.alertmanager_consumer.on.cluster_changed,
                           self._on_alertmanager_cluster_changed)
    ```

    The updated alertmanager cluster can then be obtained via the `get_cluster_info` method

    This consumer library expect the consumer charm to observe the `cluster_changed` event.

    Arguments:
            charm (CharmBase): consumer charm
            relation_name (str): from consumer's metadata.yaml

    Attributes:
            charm (CharmBase): consumer charm
    """

    on = AlertmanagerConsumerEvents()  # pyright: ignore

    def __init__(self, charm: CharmBase, relation_name: str = "alerting"):
        super().__init__(charm, relation_name, RelationRole.requires)

        self.framework.observe(
            self.charm.on[self.name].relation_changed, self._on_relation_changed
        )

        # The "alertmanagers" section in prometheus takes a list of "alertmanagers", each of which
        # has its own tls_config and a list(!) of static targets:
        # alerting:
        #   alertmanagers:
        #   - path_prefix: /model-name-app-name
        #     tls_config:
        #       ca_file: ...
        #     scheme: http
        #     static_configs:
        #     - targets:
        #       - target1
        #       - target2
        #
        # The approach we take here is:
        # - A separate instance of this library is need for every 'alerting' relation.
        # - Every alertmanager APP gets its own entry under the "alertmanagers" section.
        # - This lib (alertmanager_dispatch) communicates k8s-cluster FQDN (per unit address).
        # - All units of the same app are listed as targets under the same static_configs entry.
        #
        # Since prometheus has unit addresses in its config, we need to emit the "cluster-changed"
        # event on both relation-departed and relation-broken, because on scale-down e.g. from two
        # to one unit we'd get a relation-departed, but not a relation-broken.
        self.framework.observe(
            self.charm.on[self.name].relation_departed,
            self._on_relation_departed,
        )
        self.framework.observe(self.charm.on[self.name].relation_broken, self._on_relation_broken)

    def _on_relation_changed(self, event: ops.charm.RelationChangedEvent):
        """This hook notifies the charm that there may have been changes to the cluster."""
        if event.unit:  # event.unit may be `None` in the case of app data change
            # inform consumer about the change
            self.on.cluster_changed.emit()  # pyright: ignore

    def get_cluster_info(self) -> List[str]:
        """Returns a list of addresses of all the alertmanager units."""
        if not (relation := self.charm.model.get_relation(self.name)):
            return []

        alertmanagers: List[str] = []
        for unit in relation.units:
            address = relation.data[unit].get("public_address")
            if address:
                alertmanagers.append(address)
        return sorted(alertmanagers)

    def get_cluster_info_with_scheme(self) -> List[str]:
        """Returns a list of URLs of all the alertmanager units."""
        # FIXME: in v1 of the lib, use a dict {"url": ...} so it's extendable
        if not (relation := self.charm.model.get_relation(self.name)):
            return []

        alertmanagers: List[str] = []
        for unit in relation.units:
            address = relation.data[unit].get("public_address")
            scheme = relation.data[unit].get("scheme", "http")
            if address:
                alertmanagers.append(f"{scheme}://{address}")
        return sorted(alertmanagers)

    def _on_relation_departed(self, _):
        """This hook notifies the charm that there may have been changes to the cluster."""
        self.on.cluster_changed.emit()  # pyright: ignore

    def _on_relation_broken(self, _):
        """This hook notifies the charm that a relation has been completely removed."""
        # inform consumer about the change
        self.on.cluster_changed.emit()  # pyright: ignore


class AlertmanagerProvider(RelationManagerBase):
    """A "provider" handler to be used by charms that relate to Alertmanager (the 'provides' side).

    To have your charm provide alertmanager cluster data, declare the interface's use in your
    charm's metadata.yaml file:

    ```yaml
    provides:
      alerting:
        interface: alertmanager_dispatch
    ```

    A typical example of importing this library might be

    ```python
    from charms.alertmanager_k8s.v0.alertmanager_dispatch import AlertmanagerProvider
    ```

    In your charm's `__init__` method:

    ```python
    self.alertmanager_provider = AlertmanagerProvider(self, self._relation_name, self._api_port)
    ```

    Then inform consumers on any update to alertmanager cluster data via

    ```python
    self.alertmanager_provider.update_relation_data()
    ```

    This provider auto-registers relation events on behalf of the main Alertmanager charm.

    Arguments:
            charm (CharmBase): consumer charm
            relation_name (str): relation name (not interface name)
            api_port (int): alertmanager server's api port; this is needed here to avoid accessing
                            charm constructs directly

    Attributes:
            charm (CharmBase): the Alertmanager charm
    """

    def __init__(
        self,
        charm,
        relation_name: str = "alerting",
        api_port: int = 9093,  # TODO: breaking change: drop this arg
        *,
        external_url: Optional[Callable] = None,  # TODO: breaking change: make this mandatory
    ):
        # TODO: breaking change: force keyword-only args from relation_name onwards
        super().__init__(charm, relation_name, RelationRole.provides)

        # TODO: only use fqdn?
        # We don't need to worry about the literal "http" here because the external_url arg is set
        # by the charm. TODO: drop it after external_url becomes a mandatory arg.
        self._external_url = external_url or (lambda: f"http://{socket.getfqdn()}:{api_port}")

        events = self.charm.on[self.name]

        # No need to observe `relation_departed` or `relation_broken`: data bags are auto-updated
        # so both events are address on the consumer side.
        self.framework.observe(events.relation_joined, self._on_relation_joined)

    def _on_relation_joined(self, event: RelationJoinedEvent):
        """This hook stores the public address of the newly-joined "alerting" relation.

        This is needed for consumers such as prometheus, which should be aware of all alertmanager
        instances.
        """
        self.update_relation_data(event)

    def _generate_relation_data(self, relation: Relation):
        """Helper function to generate relation data in the correct format.

        Addresses are without scheme.
        """
        # FIXME when `_external_url` is an ingress URL, we have a problem: we get the same URL for
        #  both units, because alertmanager is ingress per unit. On prometheus side we can
        #  deduplicate so that the config file only has one entry, but ideally the
        #  "alertmanagers.[].static_configs.targets" section in the prometheus config should list
        #  all units.
        parsed = urlparse(self._external_url())
        return {
            "public_address": f"{parsed.hostname}:{parsed.port or 80}{parsed.path}",
            "scheme": parsed.scheme,
        }

    def update_relation_data(self, event: Optional[RelationEvent] = None):
        """Helper function for updating relation data bags.

        This function can be used in two different ways:
        - update relation data bag of a given event (e.g. a newly joined relation);
        - update relation data for all relations

        Args:
            event: The event whose data bag needs to be updated. If it is None, update data bags of
              all relations.
        """
        if event is None:
            # update all existing relation data
            # a single consumer charm's unit may be related to multiple providers
            for relation in self.charm.model.relations.get(self.name, []):
                # Sometimes (e.g. when an app is removed with `--force`), there is a dangling
                # relation, for which we get the following error:
                # ops.model.ModelError: b'ERROR relation 17 not found (not found)\n'
                # when trying to `network-get alerting`.
                relation.data[self.charm.unit].update(self._generate_relation_data(relation))

        else:
            # update relation data only for the newly joined relation
            event.relation.data[self.charm.unit].update(
                self._generate_relation_data(event.relation)
            )
