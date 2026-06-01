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
from charms.alertmanager_k8s.v1.alertmanager_dispatch import AlertmanagerConsumer

class SomeApplication(CharmBase):
  def __init__(self, *args):
    # ...
    self.alertmanager_consumer = AlertmanagerConsumer(self, relation_name="alertmanager")
    # ...
```
"""
import logging
from typing import Dict, Optional, Set
from urllib.parse import urlparse

import ops
import pydantic
from ops.charm import CharmBase, RelationEvent, RelationJoinedEvent, RelationRole
from ops.framework import EventBase, EventSource, Object, ObjectEvents
from ops.model import Relation
from pydantic import computed_field

# The unique Charmhub library identifier, never change it
LIBID = "37f1ca6f8fe84e3092ebbf6dc2885310"

# Increment this major API version when introducing breaking changes
LIBAPI = 1

# Increment this PATCH version before using `charmcraft publish-lib` or reset
# to 0 if you are raising the major API version
LIBPATCH = 2

PYDEPS = ["pydantic>=2"]

# Set to match metadata.yaml
INTERFACE_NAME = "alertmanager_dispatch"

logger = logging.getLogger(__name__)


class _ProviderSchemaV0(pydantic.BaseModel):
    # Currently, the provider splits the URL and the consumer merges. That's why we switched to v1.
    public_address: str
    scheme: str = "http"


class _ProviderSchemaV1(pydantic.BaseModel):
    url: str

    @computed_field
    @property
    def public_address(self) -> Optional[str]:
        # v0 relic
        parsed = urlparse(self.url)
        port = ":" + str(parsed.port) if parsed.port else ""
        return f"{parsed.hostname}{port}{parsed.path}"

    @computed_field
    @property
    def scheme(self) -> Optional[str]:
        # v0 relic
        parsed = urlparse(self.url)
        return parsed.scheme


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
    from charms.alertmanager_k8s.v1.alertmanager_dispatch import AlertmanagerConsumer
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

    def __init__(self, charm: CharmBase, *, relation_name: str = "alerting"):
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
        # - A separate instance of this library is needed for every 'alerting' relation.
        # - Every alertmanager APP gets its own entry under the "alertmanagers" section.
        # - This lib (alertmanager_dispatch) advertises its highest priority URL. Note that this
        #   means that with an ingress (per app) in place, there will be one address for all units,
        #   while without ingress, k8s-cluster FQDN will be advertised, so there will be on per
        #   unit. In the FQDN case, all units of the same app are listed as targets under the same
        #   static_configs entry.
        #
        # Since prometheus may have unit addresses in its config, we need to emit the
        # "cluster-changed" event on both relation-departed and relation-broken, because on
        # scale-down e.g. from two to one unit we'd get a relation-departed, but not a
        # relation-broken.
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

    def get_cluster_info(self) -> Set[str]:
        """Returns a list of URLs of all alertmanager units."""
        if not (relation := self.charm.model.get_relation(self.name)):
            return set()

        alertmanagers: Set[str] = set()
        for unit in relation.units:
            if rel_data := relation.data[unit]:
                try:  # v1
                    data = _ProviderSchemaV1(**rel_data)
                except pydantic.ValidationError as ev1:
                    try:  # v0
                        data = _ProviderSchemaV0(**rel_data)
                    except pydantic.ValidationError as ev0:
                        logger.warning("Relation data failed validation for v1: %s", ev1)
                        logger.warning("Relation data failed validation for v0: %s", ev0)
                    else:
                        alertmanagers.add(f"{data.scheme}://{data.public_address}")
                else:
                    alertmanagers.add(data.url)
        return alertmanagers

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
    from charms.alertmanager_k8s.v1.alertmanager_dispatch import AlertmanagerProvider
    ```

    In your charm's `__init__` method:

    ```python
    self.alertmanager_provider = AlertmanagerProvider(
        self, relation_name=self._relation_name, external_url=f"http://{socket.getfqdn()}:9093"
    )
    ```

    Then inform consumers on any update to alertmanager cluster data via

    ```python
    self.alertmanager_provider.update(external_url=self.ingress.url)
    ```

    This provider auto-registers relation events on behalf of the main Alertmanager charm.

    Arguments:
            charm: consumer charm
            external_url: URL for this unit's workload API endpoint
            relation_name: relation name (not interface name)
    """

    def __init__(
        self,
        charm: CharmBase,
        *,
        external_url: str,
        relation_name: str = "alerting",
    ):
        super().__init__(charm, relation_name, RelationRole.provides)
        self._external_url = external_url

        events = self.charm.on[self.name]

        # No need to observe `relation_departed` or `relation_broken`: data bags are auto-updated
        # so both events are address on the consumer side.
        self.framework.observe(events.relation_joined, self._on_relation_joined)

    def _on_relation_joined(self, event: RelationJoinedEvent):
        """This hook stores the public address of the newly-joined "alerting" relation.

        This is needed for consumers such as prometheus, which should be aware of all alertmanager
        instances.
        """
        self._update_relation_data(event)

    def _generate_relation_data(self, relation: Relation) -> Dict[str, str]:
        """Helper function to generate relation data in the correct format.

        Addresses are without scheme.
        """
        # FIXME when `_external_url` is an ingress URL, we have a problem: we get the same URL for
        #  both units, because alertmanager is ingress per app. On prometheus side we can
        #  deduplicate so that the config file only has one entry, but ideally the
        #  "alertmanagers.[].static_configs.targets" section in the prometheus config should list
        #  all units.
        data = _ProviderSchemaV1(url=self._external_url)
        return data.model_dump()

    def _update_relation_data(self, event: Optional[RelationEvent] = None):
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

    def update(self, *, external_url: str):
        """Update data pertaining to this relation manager (similar args to __init__)."""
        self._external_url = external_url
        self._update_relation_data()
