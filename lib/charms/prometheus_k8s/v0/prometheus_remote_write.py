# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.
"""This library facilitates the integration of the prometheus_remote_write interface.

Charms that need to push data to a charm exposing the Prometheus remote_write API,
should use the `PrometheusRemoteWriteConsumer`. Charms that operate software that exposes
the Prometheus remote_write API, that is, they can receive metrics data over remote_write,
should use the `PrometheusRemoteWriteProducer`.
"""

import json
import logging
import os
from pathlib import Path
from typing import Dict, List, Optional, Union

import yaml
from ops.charm import CharmBase, RelationEvent, RelationMeta, RelationRole
from ops.framework import EventBase, EventSource, Object, ObjectEvents
from ops.model import Relation

# The unique Charmhub library identifier, never change it
LIBID = "f783823fa75f4b7880eb70f2077ec259"

# Increment this major API version when introducing breaking changes
LIBAPI = 0

# Increment this PATCH version before using `charmcraft publish-lib` or reset
# to 0 if you are raising the major API version
LIBPATCH = 1


logger = logging.getLogger(__name__)


DEFAULT_RELATION_NAME = "prometheus-remote-write"
RELATION_INTERFACE_NAME = "prometheus_remote_write"

DEFAULT_ALERT_RULES_RELATIVE_PATH = "./src/prometheus_alert_rules"


class RelationNotFoundError(Exception):
    """Raised if there is no relation with the given name."""

    def __init__(self, relation_name: str):
        self.relation_name = relation_name
        self.message = f"No relation named '{relation_name}' found"

        super().__init__(self.message)


class RelationInterfaceMismatchError(Exception):
    """Raised if the relation with the given name has a different interface."""

    def __init__(
        self,
        relation_name: str,
        expected_relation_interface: str,
        actual_relation_interface: str,
    ):
        self.relation_name = relation_name
        self.expected_relation_interface = expected_relation_interface
        self.actual_relation_interface = actual_relation_interface
        self.message = (
            f"The '{relation_name}' relation has '{actual_relation_interface}' as "
            f"interface rather than the expected '{expected_relation_interface}'"
        )

        super().__init__(self.message)


class RelationRoleMismatchError(Exception):
    """Raised if the relation with the given name has a different direction."""

    def __init__(
        self,
        relation_name: str,
        expected_relation_role: RelationRole,
        actual_relation_role: RelationRole,
    ):
        self.relation_name = relation_name
        self.expected_relation_interface = expected_relation_role
        self.actual_relation_role = actual_relation_role
        self.message = (
            f"The '{relation_name}' relation has role '{repr(actual_relation_role)}' "
            f"rather than the expected '{repr(expected_relation_role)}'"
        )

        super().__init__(self.message)


def _validate_relation_by_interface_and_direction(
    charm: CharmBase,
    relation_name: str,
    expected_relation_interface: str,
    expected_relation_role: RelationRole,
) -> str:
    """Verifies that a relation has the necessary characteristics.

    Verifies that the `relation_name` provided: (1) exists in metadata.yaml,
    (2) declares as interface the interface name passed as `relation_interface`
    and (3) has the right "direction", i.e., it is a relation that `charm`
    provides or requires.

    Args:
        charm: a `CharmBase` object to scan for the matching relation.
        relation_name: the name of the relation to be verified.
        expected_relation_interface: the interface name to be matched by the
            relation named `relation_name`.
        expected_relation_role: whether the `relation_name` must be either
            provided or required by `charm`.

    Raises:
        RelationNotFoundError: If there is no relation in the charm's metadata.yaml
            with the same name as provided via `relation_name` argument.
        RelationInterfaceMismatchError: The relation with the same name as provided
            via `relation_name` argument does not have the same relation interface
            as specified via the `expected_relation_interface` argument.
        RelationRoleMismatchError: If the relation with the same name as provided
            via `relation_name` argument does not have the same role as specified
            via the `expected_relation_role` argument.
    """
    if relation_name not in charm.meta.relations:
        raise RelationNotFoundError(relation_name)

    relation: RelationMeta = charm.meta.relations[relation_name]

    actual_relation_interface = relation.interface_name
    if actual_relation_interface != expected_relation_interface:
        raise RelationInterfaceMismatchError(
            relation_name, expected_relation_interface, actual_relation_interface
        )

    if expected_relation_role == RelationRole.provides:
        if relation_name not in charm.meta.provides:
            raise RelationRoleMismatchError(
                relation_name, RelationRole.provides, RelationRole.requires
            )
    elif expected_relation_role == RelationRole.requires:
        if relation_name not in charm.meta.requires:
            raise RelationRoleMismatchError(
                relation_name, RelationRole.requires, RelationRole.provides
            )
    else:
        raise Exception(f"Unexpected RelationDirection: {expected_relation_role}")


class PrometheusRemoteWriteEndpointsChangedEvent(EventBase):
    """Event emitted when Prometheus remote_write endpoints change."""

    def __init__(self, handle, relation_id):
        super().__init__(handle)
        self.relation_id = relation_id

    def snapshot(self):
        """Save scrape Prometheus remote_write information."""
        return {"relation_id": self.relation_id}

    def restore(self, snapshot):
        """Restore scrape Prometheus remote_write information."""
        self.relation_id = snapshot["relation_id"]


class InvalidAlertRuleFolderPathError(Exception):
    """Raised if the alert rules folder cannot be found or is otherwise invalid."""

    def __init__(
        self,
        alert_rules_absolute_path: str,
        message: str,
    ):
        self.alert_rules_absolute_path = alert_rules_absolute_path
        self.message = message

        super().__init__(self.message)


def _resolve_dir_against_charm_path(charm: CharmBase, *path_elements: str) -> str:
    """Resolve the provided path items against the directory of the main file.

    Look up the directory of the main .py file being executed. This is normally
    going to be the charm.py file of the charm including this library. Then, resolve
    the provided path elements and, if the result path exists and is a directory,
    return its absolute path; otherwise, return `None`.
    """
    charm_dir = Path(charm.charm_dir)
    if not charm_dir.exists() or not charm_dir.is_dir():
        # Operator Framework does not currently expose a robust
        # way to determine the top level charm source directory
        # that is consistent across deployed charms and unit tests
        # Hence for unit tests the current working directory is used
        # TODO: updated this logic when the following ticket is resolved
        # https://github.com/canonical/operator/issues/643
        charm_dir = Path(os.getcwd())

    alerts_dir_path = charm_dir.absolute().joinpath(*path_elements)

    if not alerts_dir_path.exists():
        raise InvalidAlertRuleFolderPathError(alerts_dir_path, "directory does not exist")
    if not alerts_dir_path.is_dir():
        raise InvalidAlertRuleFolderPathError(alerts_dir_path, "is not a directory")

    return str(alerts_dir_path)


class PrometheusRemoteWriteConsumerEvents(ObjectEvents):
    """Event descriptor for events raised by `PrometheusRemoteWriteConsumer`."""

    endpoints_changed = EventSource(PrometheusRemoteWriteEndpointsChangedEvent)


class PrometheusRemoteWriteConsumer(Object):
    """API that manages a required `prometheus_remote_write` relation.

    The `PrometheusRemoteWriteConsumer` is intended to be used by charms that need to push data to
    other charms over the Prometheus remote_write API.

    The `PrometheusRemoteWriteConsumer` object can be instantiated as follows in your charm:

    ```
    from charms.prometheus_k8s.v0.prometheus_remote_write import PrometheusRemoteWriteConsumer

    def __init__(self, *args):
        ...
        self.remote_write_consumer = PrometheusRemoteWriteConsumer(self)
        ...
    ```

    The `PrometheusRemoteWriteConsumer` assumes that, in the `metadata.yaml` of your charm,
    you declare a required relation as follows:

    ```
    requires:
        prometheus-remote-write:  # Relation name
            interface: prometheus_remote_write  # Relation interface
    ```

    The charmed operator uses the `PrometheusRemoteWriteConsumer` as follows:

    ```
    def __init__(self, *args):
        ...
        self.remote_write_consumer = PrometheusRemoteWriteConsumer(self)
        ...

        self.framework.observe(
            self.remote_write_consumer.on.endpoints_changed,
            _handle_endpoints_changed,
        )
    ```

    Then, inside the logic of `_handle_endpoints_changed`, the updated endpoint list is
    retrieved with with:

    ```
    self.remote_write_consumer.endpoints
    ```

    which returns a dictionary structured like the Prometheus configuration object (see
    https://prometheus.io/docs/prometheus/latest/configuration/configuration/#remote_write).

    About the name of the relation managed by this library: technically, you *could* change
    the relation name, `prometheus-remote-write`, but that requires you to provide the new
    relation name to the `PrometheusRemoteWriteConsumer` via the `relation_name` constructor
    argument. (The relation interface, on the other hand, is immutable and, if you were to change
    it, your charm would not be able to relate with other charms using the right relation
    interface. The library prevents you from doing that by raising an exception.) In any case, it
    is strongly discouraged to change the relation name: having consistent relation names across
    charms that do similar things is a very good thing for the people that will use your charm.
    The one exception to the rule above, is if you charm needs to both consume and provide a
    relation using the `prometheus_remote_write` interface, in which case changing the relation
    name to differentiate between "incoming" and "outgoing" remote write interactions is necessary.

    It is also possible to specify alert rules. By default, this library will look
    into the `<charm_parent_dir>/prometheus_alert_rules`, which in standard charm
    layouts resolves to `src/prometheus_alert_rules`. Each alert rule goes into a
    separate `*.rule` file. If the syntax of a rule is invalid,
    the  `MetricsEndpointProvider` logs an error and does not load the particular
    rule.

    To avoid false positives and negatives in the evaluation of your alert rules,
    you must always add the `%%juju_topology%%` token as label filters in the
    PromQL expression, e.g.:

        alert: UnitUnavailable
        expr: up{%%juju_topology%%} < 1
        for: 0m
        labels:
            severity: critical
        annotations:
            summary: Unit {{ $labels.juju_model }}/{{ $labels.juju_unit }} unavailable
            description: >
            The unit {{ $labels.juju_model }} {{ $labels.juju_unit }} is unavailable

    The `%%juju_topology%%` token will be replaced with label filters ensuring that
    the only timeseries evaluated are those scraped from this charm, and no other.
    Failing to ensure that the `%%juju_topology%%` token is applied to each and every
    of the queries timeseries will lead to unpredictable alert rule evaluation
    if your charm is deployed multiple times and various of its instances are
    monitored by the same Prometheus.
    """

    on = PrometheusRemoteWriteConsumerEvents()

    def __init__(
        self,
        charm: CharmBase,
        relation_name: str = DEFAULT_RELATION_NAME,
        alert_rules_path: str = DEFAULT_ALERT_RULES_RELATIVE_PATH,
    ):
        """API to manage a required relation with the `prometheus_remote_write` interface.

        Args:
            charm: The charm object that instantiated this class.
            relation_name: Name of the relation with the `prometheus_remote_write` interface as
                defined in metadata.yaml.

        Raises:
            RelationNotFoundError: If there is no relation in the charm's metadata.yaml
                with the same name as provided via `relation_name` argument.
            RelationInterfaceMismatchError: The relation with the same name as provided
                via `relation_name` argument does not have the `prometheus_scrape` relation
                interface.
            RelationRoleMismatchError: If the relation with the same name as provided
                via `relation_name` argument does not have the `RelationRole.requires`
                role.
        """
        _validate_relation_by_interface_and_direction(
            charm, relation_name, RELATION_INTERFACE_NAME, RelationRole.requires
        )

        try:
            alert_rules_path = _resolve_dir_against_charm_path(charm, alert_rules_path)
        except InvalidAlertRuleFolderPathError as e:
            logger.debug(
                "Invalid Prometheus alert rules folder at %s: %s",
                e.alert_rules_absolute_path,
                e.message,
            )

        super().__init__(charm, relation_name)
        self._charm = charm
        self._relation_name = relation_name
        self._alert_rules_path = alert_rules_path

        self.framework.observe(
            self._charm.on[self._relation_name].relation_joined,
            self._handle_endpoints_changed,
        )
        self.framework.observe(
            self._charm.on[self._relation_name].relation_changed,
            self._handle_endpoints_changed,
        )
        self.framework.observe(
            self._charm.on[self._relation_name].relation_departed,
            self._handle_endpoints_changed,
        )
        self.framework.observe(
            self._charm.on[self._relation_name].relation_broken,
            self._handle_endpoints_changed,
        )

        self.framework.observe(
            self._charm.on[self._relation_name].relation_joined,
            self._set_alerts_on_relation_changed,
        )
        self.framework.observe(
            self._charm.on.upgrade_charm,
            self._set_alerts_to_all_relation,
        )

    def _handle_endpoints_changed(self, event: RelationEvent):
        self.on.endpoints_changed.emit(relation_id=event.relation.id)

    def _set_alerts_on_relation_changed(self, event: RelationEvent):
        self._set_alerts_to_relation(event.relation)

    def _set_alerts_to_all_relation(self, _):
        for relation in self.model.relations[self._relation_name]:
            self._set_alerts_to_relation(relation)

    def _set_alerts_to_relation(self, relation: Relation):
        if alert_groups := self._labeled_alert_groups:
            relation.data[self._charm.app]["alert_rules"] = json.dumps({"groups": alert_groups})

    @property
    def endpoints(self) -> List[Dict[str, str]]:
        """A config object ready to be dropped in to a prometheus config file.

        Returns:
            A list of remote_write endpoints.
        """
        endpoints = []
        for relation in self.model.relations[self._relation_name]:
            for unit in relation.units:
                if unit.app is self._charm.app:
                    # This is a peer unit
                    continue

                if remote_write := relation.data[unit].get("remote_write"):
                    deserialized_remote_write = json.loads(remote_write)
                    endpoints.append(
                        {
                            "url": deserialized_remote_write["url"],
                        }
                    )

        return endpoints

    def _label_alert_topology(self, rule) -> dict:
        """Insert juju topology labels into an alert rule.

        Args:
            rule: a dictionary representing a prometheus alert rule.

        Returns:
            a dictionary representing prometheus alert rule with juju
            topology labels.
        """
        metadata = self._consumer_metadata
        labels = rule.get("labels", {})
        labels["juju_model"] = metadata["model"]
        labels["juju_model_uuid"] = metadata["model_uuid"]
        labels["juju_application"] = metadata["application"]
        rule["labels"] = labels
        return rule

    def _label_alert_expression(self, rule) -> dict:
        """Insert juju topology filters into a prometheus alert rule.

        Args:
            rule: a dictionary representing a prometheus alert rule.

        Returns:
            a dictionary representing a prometheus alert rule that filters based
            on juju topology.
        """
        metadata = self._consumer_metadata
        topology = 'juju_model="{}", juju_model_uuid="{}", juju_application="{}"'.format(
            metadata["model"], metadata["model_uuid"], metadata["application"]
        )

        if expr := rule.get("expr", None):
            expr = expr.replace("%%juju_topology%%", topology)
            rule["expr"] = expr
        else:
            logger.error("Invalid alert expression in %s", rule.get("alert"))

        return rule

    @property
    def _labeled_alert_groups(self) -> list:
        """Load alert rules from rule files.

        All rules from files for a consumer charm are loaded into a single
        group. the generated name of this group includes juju topology
        prefixes.

        Returns:
            a list of prometheus alert rule groups.
        """
        alerts = []
        for path in Path(self._alert_rules_path).glob("*.rule"):
            if not path.is_file():
                continue

            logger.debug("Reading alert rule from %s", path)
            with path.open() as rule_file:
                # Load a list of rules from file then add labels and filters
                try:
                    rule = yaml.safe_load(rule_file)
                    rule = self._label_alert_topology(rule)
                    rule = self._label_alert_expression(rule)
                    alerts.append(rule)
                except Exception as e:
                    logger.error("Failed to read alert rules from %s: %s", path.name, str(e))

        # Gather all alerts into a list of one group since Prometheus
        # requires alerts be part of some group
        groups = []
        if alerts:
            metadata = self._consumer_metadata
            group = {
                "name": "{model}_{model_uuid}_{application}_alerts".format(**metadata),
                "rules": alerts,
            }
            groups.append(group)
        return groups

    @property
    def _consumer_metadata(self) -> dict:
        """Generate scrape metadata.

        Returns:
            Scrape configuration metadata for the charm using this PrometheusRemoteWriteConsumer.
        """
        metadata = {
            "model": f"{self._charm.model.name}",
            "model_uuid": f"{self._charm.model.uuid}",
            "application": f"{self._charm.model.app.name}",
            "charm_name": f"{self._charm.meta.name}",
        }
        return metadata


class PrometheusRemoteWriteProvider(Object):
    """API that manages a provided `prometheus_remote_write` relation.

    The `PrometheusRemoteWriteProvider` is intended to be used by charms that need to receive data
    from other charms over the Prometheus remote_write API.

    The `PrometheusRemoteWriteProvider` object can be instantiated as follows in your charm:

    ```
    from charms.prometheus_k8s.v0.prometheus_remote_write import PrometheusRemoteWriteProvider

    def __init__(self, *args):
        ...
        self.remote_write_provider = PrometheusRemoteWriteProvider(self)
        ...
    ```

    The `PrometheusRemoteWriteProvider` assumes that, in the `metadata.yaml` of your charm,
    you declare a provided relation as follows:

    ```
    provides:
        prometheus-remote-write:  # Relation name
            interface: prometheus_remote_write  # Relation interface
    ```

    About the name of the relation managed by this library: technically, you *could* change
    the relation name, `prometheus-remote-write`, but that requires you to provide the new
    relation name to the `PrometheusRemoteWriteProducer` via the `relation_name` constructor
    argument. (The relation interface, on the other hand, is immutable and, if you were to change
    it, your charm would not be able to relate with other charms using the right relation
    interface. The library prevents you from doing that by raising an exception.) In any case, it
    is strongly discouraged to change the relation name: having consistent relation names across
    charms that do similar things is a very good thing for the people that will use your charm.
    The one exception to the rule above, is if you charm needs to both consume and provide a
    relation using the `prometheus_remote_write` interface, in which case changing the relation
    name to differentiate between "incoming" and "outgoing" remote write interactions is necessary.
    """

    def __init__(
        self,
        charm: CharmBase,
        relation_name: str = DEFAULT_RELATION_NAME,
        endpoint_schema: str = "http",
        endpoint_address: Optional[str] = None,
        endpoint_port: Union[str, int] = 9090,
        endpoint_path: str = "/api/v1/write",
    ):
        """API to manage a provided relation with the `prometheus_remote_write` interface.

        Args:
            charm: The charm object that instantiated this class.
            relation_name: Name of the relation with the `prometheus_remote_write` interface as
                defined in metadata.yaml.
            endpoint_schema: The URL schema for your remote_write endpoint. Defaults to `http`.
            endpoint_address: The URL host for your remote_write endpoint as reachable
                from the client. This might be either the pod IP, or you might want to
                expose an address routable from outside the Kubernetes cluster, e.g., the
                host address of an Ingress. If not provided, it defaults to the relation's
                `bind_address`.
            endpoint_port: The URL port for your remote_write endpoint. Defaults to `9090`.
            endpoint_path: The URL path for your remote_write endpoint.
                Defaults to `/api/v1/write`.

        Raises:
            RelationNotFoundError: If there is no relation in the charm's metadata.yaml
                with the same name as provided via `relation_name` argument.
            RelationInterfaceMismatchError: The relation with the same name as provided
                via `relation_name` argument does not have the `prometheus_scrape` relation
                interface.
            RelationRoleMismatchError: If the relation with the same name as provided
                via `relation_name` argument does not have the `RelationRole.requires`
                role.
        """
        _validate_relation_by_interface_and_direction(
            charm, relation_name, RELATION_INTERFACE_NAME, RelationRole.provides
        )

        super().__init__(charm, relation_name)
        self._charm = charm
        self._relation_name = relation_name
        self._endpoint_schema = endpoint_schema
        self._endpoint_address = endpoint_address
        self._endpoint_port = int(endpoint_port)
        self._endpoint_path = endpoint_path

        relation_events = self._charm.on[self._relation_name]
        self.framework.observe(
            relation_events.relation_created,
            self._set_endpoint_on_relation_change,
        )
        self.framework.observe(
            relation_events.relation_joined,
            self._set_endpoint_on_relation_change,
        )

    def update_endpoint(self, relation: Optional[Relation] = None) -> None:
        """Triggers programmatically the update of the relation data.

        This method should be used when the charm relying on this library needs
        to update the relation data in response to something occurring outside
        of the `prometheus_remote_write` relation lifecycle, e.g., in case of an
        host address change because the charmed operator becomes connected to an
        Ingress after the `prometheus_remote_write` relation is established.

        Args:
            relation: An optional instance of `class:ops.model.Relation` to update.
                If not provided, all instances of the `prometheus_remote_write`
                relation are updated.
        """
        relations = [relation] if relation else self.model.relations[self._relation_name]

        for relation in relations:
            self._set_endpoint_on_relation(relation)

    def _set_endpoint_on_relation_change(self, event: RelationEvent) -> None:
        self._set_endpoint_on_relation(event.relation)

    def _set_endpoint_on_relation(self, relation: Relation) -> None:
        """Set the the remote_write endpoint on relations.

        Args:
            relation: Optional relation. If provided, only this relation will be
                updated. Otherwise, all instances of the `prometheus_remote_write`
                relation managed by this `PrometheusRemoteWriteProvider` will be
                updated.
        """
        address = self._endpoint_address or self._get_relation_bind_address()

        path = self._endpoint_path or ""
        if path and not path.startswith("/"):
            path = f"/{path}"

        endpoint_url = f"{self._endpoint_schema}://{address}:{str(self._endpoint_port)}{path}"

        relation.data[self._charm.unit]["remote_write"] = json.dumps(
            {
                "url": endpoint_url,
            }
        )

    def _get_relation_bind_address(self):
        network_binding = self._charm.model.get_binding(self._relation_name)
        return network_binding.network.bind_address

    def alerts(self) -> dict:
        """Fetch alert rules from all relations.

        A Prometheus alert rules file consists of a list of "groups". Each
        group consists of a list of alerts (`rules`) that are sequentially
        executed. This method returns all the alert rules provided by each
        related metrics provider charm. These rules may be used to generate a
        separate alert rules file for each relation since the returned list
        of alert groups are indexed by relation ID. Also for each relation ID
        associated scrape metadata such as Juju model, UUID and application
        name are provided so the a unique name may be generated for the rules
        file. For each relation the structure of data returned is a dictionary
        with four keys

        - groups
        - model
        - model_uuid
        - application

        The value of the `groups` key is such that it may be used to generate
        a Prometheus alert rules file directly using `yaml.dump` but the
        `groups` key itself must be included as this is required by Prometheus,
        for example as in `yaml.dump({"groups": alerts["groups"]})`.

        The `PrometheusRemoteWriteProvider` accepts a list of rules and these
        rules are all placed into one group.

        Returns:
            a dictionary mapping the name of an alert rule group to the group.
        """
        alerts = {}
        for relation in self._charm.model.relations[self._relation_name]:
            if not relation.units:
                continue

            alert_rules = json.loads(relation.data[relation.app].get("alert_rules", "{}"))

            if not alert_rules:
                continue

            try:
                for group in alert_rules["groups"]:
                    alerts[group["name"]] = group
            except KeyError as e:
                logger.error(
                    "Relation %s has invalid data : %s",
                    relation.id,
                    e,
                )

        return alerts
