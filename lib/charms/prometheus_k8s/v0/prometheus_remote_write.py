# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.
"""# Prometheus remote-write library.

This library facilitates the integration of the prometheus_remote_write interface.

Charms that need to push data to a charm exposing the Prometheus remote_write API,
should use the `PrometheusRemoteWriteConsumer`. Charms that operate software that exposes
the Prometheus remote_write API, that is, they can receive metrics data over remote_write,
should use the `PrometheusRemoteWriteProducer`.
"""

import json
import logging
import os
import platform
import re
import socket
import subprocess
from collections import OrderedDict
from pathlib import Path
from typing import Dict, List, Optional, Union

import yaml
from ops.charm import CharmBase, HookEvent, RelationEvent, RelationMeta, RelationRole
from ops.framework import EventBase, EventSource, Object, ObjectEvents
from ops.model import Relation

# The unique Charmhub library identifier, never change it
LIBID = "f783823fa75f4b7880eb70f2077ec259"

# Increment this major API version when introducing breaking changes
LIBAPI = 0

# Increment this PATCH version before using `charmcraft publish-lib` or reset
# to 0 if you are raising the major API version
LIBPATCH = 5


logger = logging.getLogger(__name__)


DEFAULT_RELATION_NAME = "receive-remote-write"
DEFAULT_CONSUMER_NAME = "send-remote-write"
RELATION_INTERFACE_NAME = "prometheus_remote_write"

DEFAULT_ALERT_RULES_RELATIVE_PATH = "./src/prometheus_alert_rules"


class RelationNotFoundError(Exception):
    """Raised if there is no relation with the given name."""

    def __init__(self, relation_name: str):
        self.relation_name = relation_name
        self.message = "No relation named '{}' found".format(relation_name)

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
            "The '{}' relation has '{}' as its interface rather than the expected '{}'".format(
                relation_name, actual_relation_interface, expected_relation_interface
            )
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
        self.message = "The '{}' relation has role '{}' rather than the expected '{}'".format(
            relation_name, repr(actual_relation_role), repr(expected_relation_role)
        )

        super().__init__(self.message)


class JujuTopology:
    """Class for storing and formatting juju topology information."""

    STUB = "%%juju_topology%%"

    def __new__(cls, *args, **kwargs):
        """Reject instantiation of a base JujuTopology class. Children only."""
        if cls is JujuTopology:
            raise TypeError("only children of '{}' may be instantiated".format(cls.__name__))
        return object.__new__(cls)

    def __init__(
        self,
        model: str,
        model_uuid: str,
        application: str,
        unit: Optional[str] = "",
        charm_name: Optional[str] = "",
    ):
        """Build a JujuTopology object.

        A `JujuTopology` object is used for storing and transforming
        Juju Topology information. This information is used to
        annotate Prometheus scrape jobs and alert rules. Such
        annotation when applied to scrape jobs helps in identifying
        the source of the scrapped metrics. On the other hand when
        applied to alert rules topology information ensures that
        evaluation of alert expressions is restricted to the source
        (charm) from which the alert rules were obtained.

        Args:
            model: a string name of the Juju model
            model_uuid: a globally unique string identifier for the Juju model
            application: an application name as a string
            unit: a unit name as a string
            charm_name: name of charm as a string

        Note:
            `JujuTopology` should not be constructed directly by charm code. Please
            use `ProviderTopology` or `AggregatorTopology`.
        """
        self.model = model
        self.model_uuid = model_uuid
        self.application = application
        self.charm_name = charm_name
        self.unit = unit

    @classmethod
    def from_charm(cls, charm):
        """Factory method for creating `JujuTopology` children from a given charm.

        Args:
            charm: a `CharmBase` object for which the `JujuTopology` has to be constructed

        Returns:
            a `JujuTopology` object.
        """
        return cls(
            model=charm.model.name,
            model_uuid=charm.model.uuid,
            application=charm.model.app.name,
            unit=charm.model.unit.name,
            charm_name=charm.meta.name,
        )

    @classmethod
    def from_relation_data(cls, data: dict):
        """Factory method for creating `JujuTopology` children from a dictionary.

        Args:
            data: a dictionary with four keys providing topology information. The keys are
                - "model"
                - "model_uuid"
                - "application"
                - "unit"
                - "charm_name"

                `unit` and `charm_name` may be empty, but will result in more limited
                labels. However, this allows us to support payload-only charms.

        Returns:
            a `JujuTopology` object.
        """
        return cls(
            model=data["model"],
            model_uuid=data["model_uuid"],
            application=data["application"],
            unit=data.get("unit", ""),
            charm_name=data.get("charm_name", ""),
        )

    @property
    def identifier(self) -> str:
        """Format the topology information into a terse string."""
        # This is odd, but may have `None` as a model key
        return "_".join([str(val) for val in self.as_promql_label_dict().values()]).replace(
            "/", "_"
        )

    @property
    def promql_labels(self) -> str:
        """Format the topology information into a verbose string."""
        return ", ".join(
            ['{}="{}"'.format(key, value) for key, value in self.as_promql_label_dict().items()]
        )

    def as_dict(self, rename_keys: Optional[Dict[str, str]] = None) -> OrderedDict:
        """Format the topology information into a dict.

        Use an OrderedDict so we can rely on the insertion order on Python 3.5 (and 3.6,
        which still does not guarantee it).

        Args:
            rename_keys: A dictionary mapping old key names to new key names, which will
                be substituted when invoked.
        """
        ret = OrderedDict(
            [
                ("model", self.model),
                ("model_uuid", self.model_uuid),
                ("application", self.application),
                ("unit", self.unit),
                ("charm_name", self.charm_name),
            ]
        )

        ret["unit"] or ret.pop("unit")
        ret["charm_name"] or ret.pop("charm_name")

        # If a key exists in `rename_keys`, replace the value
        if rename_keys:
            ret = OrderedDict(
                (rename_keys.get(k), v) if rename_keys.get(k) else (k, v) for k, v in ret.items()  # type: ignore
            )

        return ret

    def as_promql_label_dict(self):
        """Format the topology information into a dict with keys having 'juju_' as prefix."""
        vals = {
            "juju_{}".format(key): val
            for key, val in self.as_dict(rename_keys={"charm_name": "charm"}).items()
        }
        # The leader is the only unit that sets alert rules, if "juju_unit" is present,
        # then the rules will only be evaluated for that unit
        if "juju_unit" in vals:
            vals.pop("juju_unit")

        return vals

    def render(self, template: str):
        """Render a juju-topology template string with topology info."""
        return template.replace(JujuTopology.STUB, self.promql_labels)


class AggregatorTopology(JujuTopology):
    """Class for initializing topology information for MetricsEndpointAggregator."""

    @classmethod
    def create(cls, model: str, model_uuid: str, application: str, unit: str):
        """Factory method for creating the `AggregatorTopology` dataclass from a given charm.

        Args:
            model: a string representing the model
            model_uuid: the model UUID as a string
            application: the application name
            unit: the unit name
        Returns:
            a `AggregatorTopology` object.
        """
        return cls(
            model=model,
            model_uuid=model_uuid,
            application=application,
            unit=unit,
        )

    def as_promql_label_dict(self):
        """Format the topology information into a dict with keys having 'juju_' as prefix."""
        vals = {"juju_{}".format(key): val for key, val in self.as_dict().items()}

        # FIXME: Why is this different? I have no idea. The uuid length should be the same
        vals["juju_model_uuid"] = vals["juju_model_uuid"][:7]

        return vals


class ProviderTopology(JujuTopology):
    """Class for initializing topology information for MetricsEndpointProvider."""

    @property
    def scrape_identifier(self):
        """Format the topology information into a scrape identifier."""
        # This is used only by Metrics[Consumer|Provider] and does not need a
        # unit name, so only check for the charm name
        return "juju_{}_prometheus_scrape".format(
            "_".join([self.model, self.model_uuid[:7], self.application, self.charm_name])  # type: ignore
        )


def _is_official_alert_rule_format(rules_dict: dict) -> bool:
    """Are alert rules in the upstream format as supported by Prometheus.

    Alert rules in dictionary format are in "official" form if they
    contain a "groups" key, since this implies they contain a list of
    alert rule groups.

    Args:
        rules_dict: a set of alert rules in Python dictionary format

    Returns:
        True if alert rules are in official Prometheus file format.
    """
    return "groups" in rules_dict


def _is_single_alert_rule_format(rules_dict: dict) -> bool:
    """Are alert rules in single rule format.

    The Prometheus charm library supports reading of alert rules in a
    custom format that consists of a single alert rule per file. This
    does not conform to the official Prometheus alert rule file format
    which requires that each alert rules file consists of a list of
    alert rule groups and each group consists of a list of alert
    rules.

    Alert rules in dictionary form are considered to be in single rule
    format if in the least it contains two keys corresponding to the
    alert rule name and alert expression.

    Returns:
        True if alert rule is in single rule file format.
    """
    # one alert rule per file
    return set(rules_dict) >= {"alert", "expr"}


class AlertRules:
    """Utility class for amalgamating prometheus alert rule files and injecting juju topology.

    An `AlertRules` object supports aggregating alert rules from files and directories in both
    official and single rule file formats using the `add_path()` method. All the alert rules
    read are annotated with Juju topology labels and amalgamated into a single data structure
    in the form of a Python dictionary using the `as_dict()` method. Such a dictionary can be
    easily dumped into JSON format and exchanged over relation data. The dictionary can also
    be dumped into YAML format and written directly into an alert rules file that is read by
    Prometheus. Note that multiple `AlertRules` objects must not be written into the same file,
    since Prometheus allows only a single list of alert rule groups per alert rules file.
    The official Prometheus format is a YAML file conforming to the Prometheus documentation
    (https://prometheus.io/docs/prometheus/latest/configuration/alerting_rules/).
    The custom single rule format is a subsection of the official YAML, having a single alert
    rule, effectively "one alert per file".
    """

    # This class uses the following terminology for the various parts of a rule file:
    # - alert rules file: the entire groups[] yaml, including the "groups:" key.
    # - alert groups (plural): the list of groups[] (a list, i.e. no "groups:" key) - it is a list
    #   of dictionaries that have the "name" and "rules" keys.
    # - alert group (singular): a single dictionary that has the "name" and "rules" keys.
    # - alert rules (plural): all the alerts in a given alert group - a list of dictionaries with
    #   the "alert" and "expr" keys.
    # - alert rule (singular): a single dictionary that has the "alert" and "expr" keys.

    def __init__(self, topology: Optional[JujuTopology] = None):
        """Build and alert rule object.

        Args:
            topology: an optional `JujuTopology` instance that is used to annotate all alert rules.
        """
        self.topology = topology
        self.alert_groups = []  # type: List[dict]

    def _from_file(self, root_path: Path, file_path: Path) -> List[dict]:
        """Read a rules file from path, injecting juju topology.

        Args:
            root_path: full path to the root rules folder (used only for generating group name)
            file_path: full path to a *.rule file.

        Returns:
            A list of dictionaries representing the rules file, if file is valid (the structure is
            formed by `yaml.safe_load` of the file); an empty list otherwise.
        """
        with file_path.open() as rf:
            # Load a list of rules from file then add labels and filters
            try:
                rule_file = yaml.safe_load(rf)

            except Exception as e:
                logger.error("Failed to read alert rules from %s: %s", file_path.name, e)
                return []

            if _is_official_alert_rule_format(rule_file):
                alert_groups = rule_file["groups"]
            elif _is_single_alert_rule_format(rule_file):
                # convert to list of alert groups
                # group name is made up from the file name
                alert_groups = [{"name": file_path.stem, "rules": [rule_file]}]
            else:
                # invalid/unsupported
                logger.error("Invalid rules file: %s", file_path.name)
                return []

            # update rules with additional metadata
            for alert_group in alert_groups:
                if not self._is_already_modified(alert_group["name"]):
                    # update group name with topology and sub-path
                    alert_group["name"] = self._group_name(
                        str(root_path),
                        str(file_path),
                        alert_group["name"],
                    )

                # add "juju_" topology labels
                for alert_rule in alert_group["rules"]:
                    if "labels" not in alert_rule:
                        alert_rule["labels"] = {}

                    if self.topology:
                        # only insert labels that do not already exist
                        for label, val in self.topology.as_promql_label_dict().items():
                            if label not in alert_rule["labels"]:
                                alert_rule["labels"][label] = val
                        # insert juju topology filters into a prometheus alert rule
                        alert_rule["expr"] = self.topology.render(alert_rule["expr"])

            return alert_groups

    def _group_name(self, root_path: str, file_path: str, group_name: str) -> str:
        """Generate group name from path and topology.

        The group name is made up of the relative path between the root dir_path, the file path,
        and topology identifier.

        Args:
            root_path: path to the root rules dir.
            file_path: path to rule file.
            group_name: original group name to keep as part of the new augmented group name

        Returns:
            New group name, augmented by juju topology and relative path.
        """
        rel_path = os.path.relpath(os.path.dirname(file_path), root_path)
        rel_path = "" if rel_path == "." else rel_path.replace(os.path.sep, "_")

        # Generate group name:
        #  - name, from juju topology
        #  - suffix, from the relative path of the rule file;
        group_name_parts = [self.topology.identifier] if self.topology else []
        group_name_parts.extend([rel_path, group_name, "alerts"])
        # filter to remove empty strings
        return "_".join(filter(None, group_name_parts))

    def _is_already_modified(self, name: str) -> bool:
        """Detect whether a group name has already been modified with juju topology."""
        modified_matcher = re.compile(r"^.*?_[\da-f]{8}-([\da-f]{4}-){3}[\da-f]{12}_.*?alerts$")
        if modified_matcher.match(name) is not None:
            return True
        return False

    @classmethod
    def _multi_suffix_glob(
        cls, dir_path: Path, suffixes: List[str], recursive: bool = True
    ) -> list:
        """Helper function for getting all files in a directory that have a matching suffix.

        Args:
            dir_path: path to the directory to glob from.
            suffixes: list of suffixes to include in the glob (items should begin with a period).
            recursive: a flag indicating whether a glob is recursive (nested) or not.

        Returns:
            List of files in `dir_path` that have one of the suffixes specified in `suffixes`.
        """
        all_files_in_dir = dir_path.glob("**/*" if recursive else "*")
        return list(filter(lambda f: f.is_file() and f.suffix in suffixes, all_files_in_dir))

    def _from_dir(self, dir_path: Path, recursive: bool) -> List[dict]:
        """Read all rule files in a directory.

        All rules from files for the same directory are loaded into a single
        group. The generated name of this group includes juju topology.
        By default, only the top directory is scanned; for nested scanning, pass `recursive=True`.

        Args:
            dir_path: directory containing *.rule files (alert rules without groups).
            recursive: flag indicating whether to scan for rule files recursively.

        Returns:
            a list of dictionaries representing prometheus alert rule groups, each dictionary
            representing an alert group (structure determined by `yaml.safe_load`).
        """
        alert_groups = []  # type: List[dict]

        # Gather all alerts into a list of groups
        for file_path in self._multi_suffix_glob(dir_path, [".rule", ".rules"], recursive):
            alert_groups_from_file = self._from_file(dir_path, file_path)
            if alert_groups_from_file:
                logger.debug("Reading alert rule from %s", file_path)
                alert_groups.extend(alert_groups_from_file)

        return alert_groups

    def add_path(self, path: str, *, recursive: bool = False) -> None:
        """Add rules from a dir path.

        All rules from files are aggregated into a data structure representing a single rule file.
        All group names are augmented with juju topology.

        Args:
            path: either a rules file or a dir of rules files.
            recursive: whether to read files recursively or not (no impact if `path` is a file).

        Returns:
            True if path was added else False.
        """
        path = Path(path)  # type: Path
        if path.is_dir():
            self.alert_groups.extend(self._from_dir(path, recursive))
        elif path.is_file():
            self.alert_groups.extend(self._from_file(path.parent, path))
        else:
            logger.debug("Alert rules path does not exist: %s", path)

    def as_dict(self) -> dict:
        """Return standard alert rules file in dict representation.

        Returns:
            a dictionary containing a single list of alert rule groups.
            The list of alert rule groups is provided as value of the
            "groups" dictionary key.
        """
        return {"groups": self.alert_groups} if self.alert_groups else {}


def _validate_relation_by_interface_and_direction(
    charm: CharmBase,
    relation_name: str,
    expected_relation_interface: str,
    expected_relation_role: RelationRole,
):
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

    relation = charm.meta.relations[relation_name]  # type: RelationMeta

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
        raise Exception("Unexpected RelationDirection: {}".format(expected_relation_role))


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


class InvalidAlertRulePathError(Exception):
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
    charm_dir = Path(str(charm.charm_dir))
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
        raise InvalidAlertRulePathError(str(alerts_dir_path), "directory does not exist")
    if not alerts_dir_path.is_dir():
        raise InvalidAlertRulePathError(str(alerts_dir_path), "is not a directory")

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
        receive-remote-write:  # Relation name
            interface: prometheus_remote_write  # Relation interface
    ```

    The charmed operator is expected to use the `PrometheusRemoteWriteConsumer` as follows:

    ```
    def __init__(self, *args):
        ...
        self.remote_write_consumer = PrometheusRemoteWriteConsumer(self)
        ...

        self.framework.observe(
            self.remote_write_consumer.on.endpoints_changed,
            self._handle_endpoints_changed,
        )
    ```
    The `endpoints_changed` event will fire in situations such as provider ip change (e.g.
    relation created, provider upgrade, provider pod churn) or provider config change (e.g.
    metadata settings).

    Then, inside the logic of `_handle_endpoints_changed`, the updated endpoint list is
    retrieved with with:

    ```
    self.remote_write_consumer.endpoints
    ```

    which returns a dictionary structured like the Prometheus configuration object (see
    https://prometheus.io/docs/prometheus/latest/configuration/configuration/#remote_write).

    Regarding the default relation name, `receive-remote-write`: if you choose to change it,
    you would need to explicitly provide it to the `PrometheusRemoteWriteConsumer` via the
    `relation_name` constructor argument. (The relation interface, on the other hand, is
    fixed and, if you were to change it, your charm would not be able to relate with other
    charms using the correct relation interface. The library prevents you from doing that by
    raising an exception.)

    In any case, it is strongly discouraged to change the relation name: having consistent
    relation names across charms that do similar things is good practice and more
    straightforward for the users of your charm. The one exception to the rule above,
    is if your charm needs to both consume and provide a relation using the
    `prometheus_remote_write` interface, in which case changing the relation name to
    differentiate between "incoming" and "outgoing" remote write interactions is necessary.

    It is also possible to specify alert rules. By default, this library will search
    `<charm_parent_dir>/prometheus_alert_rules`, which in standard charm
    layouts resolves to `src/prometheus_alert_rules`. Each set of alert rules, grouped
    by the topology identifier, goes into a separate `*.rule` file.

    If the syntax of a rule is invalid, the `MetricsEndpointProvider` logs an error and
    does not load the particular rule.

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
        relation_name: str = DEFAULT_CONSUMER_NAME,
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
        except InvalidAlertRulePathError as e:
            logger.debug(
                "Invalid Prometheus alert rules folder at %s: %s",
                e.alert_rules_absolute_path,
                e.message,
            )

        super().__init__(charm, relation_name)
        self._charm = charm
        self._relation_name = relation_name
        self._alert_rules_path = alert_rules_path

        self.topology = ProviderTopology.from_charm(charm)

        on_relation = self._charm.on[self._relation_name]

        self.framework.observe(on_relation.relation_joined, self._handle_endpoints_changed)
        self.framework.observe(on_relation.relation_changed, self._handle_endpoints_changed)
        self.framework.observe(on_relation.relation_departed, self._handle_endpoints_changed)
        self.framework.observe(on_relation.relation_broken, self._handle_endpoints_changed)
        self.framework.observe(on_relation.relation_joined, self._push_alerts_on_relation_joined)
        self.framework.observe(
            self._charm.on.leader_elected, self._push_alerts_to_all_relation_databags
        )
        self.framework.observe(
            self._charm.on.upgrade_charm, self._push_alerts_to_all_relation_databags
        )

    def _handle_endpoints_changed(self, event: RelationEvent) -> None:
        self.on.endpoints_changed.emit(relation_id=event.relation.id)

    def _push_alerts_on_relation_joined(self, event: RelationEvent) -> None:
        self._push_alerts_to_relation_databag(event.relation)

    def _push_alerts_to_all_relation_databags(self, _: Optional[HookEvent]) -> None:
        for relation in self.model.relations[self._relation_name]:
            self._push_alerts_to_relation_databag(relation)

    def _push_alerts_to_relation_databag(self, relation: Relation) -> None:
        if not self._charm.unit.is_leader():
            return

        alert_rules = AlertRules(self.topology)
        alert_rules.add_path(self._alert_rules_path, recursive=False)

        alert_rules_as_dict = alert_rules.as_dict()

        if alert_rules_as_dict:
            relation.data[self._charm.app]["alert_rules"] = json.dumps(alert_rules_as_dict)

    def reload_alerts(self) -> None:
        """Reload alert rules from disk and push to relation data."""
        self._push_alerts_to_all_relation_databags(None)

    @property
    def endpoints(self) -> List[Dict[str, str]]:
        """A config object ready to be dropped into a prometheus config file.

        The format of the dict is specified in the official prometheus docs:
        https://prometheus.io/docs/prometheus/latest/configuration/configuration/#remote_write

        Returns:
            A list of dictionaries where each dictionary provides information about
            a single remote_write endpoint.
        """
        endpoints = []
        for relation in self.model.relations[self._relation_name]:
            for unit in relation.units:
                if unit.app is self._charm.app:
                    # This is a peer unit
                    continue

                remote_write = relation.data[unit].get("remote_write")
                if remote_write:
                    deserialized_remote_write = json.loads(remote_write)
                    endpoints.append(
                        {
                            "url": deserialized_remote_write["url"],
                        }
                    )

        return endpoints


class PrometheusRemoteWriteProvider(Object):
    """API that manages a provided `prometheus_remote_write` relation.

    The `PrometheusRemoteWriteProvider` is intended to be used by charms whose workloads need
    to receive data from other charms' workloads over the Prometheus remote_write API.

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
        receive-remote-write:  # Relation name
            interface: prometheus_remote_write  # Relation interface
    ```

    About the name of the relation managed by this library: technically, you *could* change
    the relation name, `receive-remote-write`, but that requires you to provide the new
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
        endpoint_address: str = "",
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
                host address of an Ingress. If not provided, it defaults to the unit's FQDN.
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
        self._transformer = PromqlTransformer(self._charm)
        self._relation_name = relation_name
        self._endpoint_schema = endpoint_schema
        self._endpoint_address = endpoint_address
        self._endpoint_port = int(endpoint_port)
        self._endpoint_path = endpoint_path

        on_relation = self._charm.on[self._relation_name]
        self.framework.observe(
            on_relation.relation_created,
            self._on_relation_change,
        )
        self.framework.observe(
            on_relation.relation_joined,
            self._on_relation_change,
        )

    def _on_relation_change(self, event: RelationEvent) -> None:
        self.update_endpoint(event.relation)

    def update_endpoint(self, relation: Relation = None) -> None:
        """Triggers programmatically the update of the relation data.

        This method should be used when the charm relying on this library needs
        to update the relation data in response to something occurring outside
        of the `prometheus_remote_write` relation lifecycle, e.g., in case of a
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

    def _set_endpoint_on_relation(self, relation: Relation) -> None:
        """Set the remote_write endpoint on relations.

        Args:
            relation: The relation whose data to update.
        """
        address = self._endpoint_address or socket.getfqdn()

        path = self._endpoint_path or ""
        if path and not path.startswith("/"):
            path = "/{}".format(path)

        endpoint_url = "{}://{}:{}{}".format(
            self._endpoint_schema, address, str(self._endpoint_port), path
        )

        relation.data[self._charm.unit]["remote_write"] = json.dumps(
            {
                "url": endpoint_url,
            }
        )

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
        alerts = {}  # type: Dict[str, dict] # mapping b/w juju identifiers and alert rule files
        for relation in self._charm.model.relations[self._relation_name]:
            if not relation.units or not relation.app:
                continue

            alert_rules = json.loads(relation.data[relation.app].get("alert_rules", "{}"))

            if not alert_rules:
                continue

            if "groups" not in alert_rules:
                logger.debug("No alert groups were found in relation data")
                continue
            # Construct an ID based on what's in the alert rules
            for group in alert_rules["groups"]:
                try:
                    labels = group["rules"][0]["labels"]
                    identifier = "{}_{}_{}".format(
                        labels["juju_model"],
                        labels["juju_model_uuid"],
                        labels["juju_application"],
                    )
                    if identifier not in alerts:
                        alerts[identifier] = {"groups": [group]}
                    else:
                        alerts[identifier]["groups"].append(group)
                except KeyError:
                    logger.error("Alert rules were found but no usable labels were present")

        return alerts


# Copy/pasted from prometheus_scrape.py
class PromqlTransformer:
    """Uses promql-transform to inject label matchers into alert rule expressions."""

    _path = None
    _disabled = False

    @property
    def path(self):
        """Lazy lookup of the path of promql-transform."""
        if self._disabled:
            return None
        if not self._path:
            self._path = self._get_transformer_path()
            if not self._path:
                logger.debug("Skipping injection of juju topology as label matchers")
                self._disabled = True
        return self._path

    def __init__(self, charm):
        self._charm = charm

    def apply_label_matchers(self, rules):
        """Will apply label matchers to the expression of all alerts in all supplied groups."""
        if not self.path:
            return rules
        for group in rules["groups"]:
            rules_in_group = group.get("rules", [])
            for rule in rules_in_group:
                topology = {}
                # if the user for some reason has provided juju_unit, we'll need to honor it
                # in most cases, however, this will be empty
                for label in [
                    "juju_model",
                    "juju_model_uuid",
                    "juju_application",
                    "juju_charm",
                    "juju_unit",
                ]:
                    if label in rule["labels"]:
                        topology[label] = rule["labels"][label]

                rule["expr"] = self._apply_label_matcher(rule["expr"], topology)
        return rules

    def _apply_label_matcher(self, expression, topology):
        if not topology:
            return expression
        if not self.path:
            logger.debug(
                "`promql-transform` unavailable. leaving expression unchanged: %s", expression
            )
            return expression
        args = [str(self.path)]
        args.extend(
            ["--label-matcher={}={}".format(key, value) for key, value in topology.items()]
        )

        args.extend(["{}".format(expression)])
        # noinspection PyBroadException
        try:
            return self._exec(args)
        except Exception as e:
            logger.debug('Applying the expression failed: "%s", falling back to the original', e)
            return expression

    def _get_transformer_path(self) -> Optional[Path]:
        arch = platform.processor()
        arch = "amd64" if arch == "x86_64" else arch
        res = "promql-transform-{}".format(arch)
        try:
            path = Path(res).resolve()
            path.chmod(0o777)
            return path
        except NotImplementedError:
            logger.debug("System lacks support for chmod")
        except FileNotFoundError:
            logger.debug('Could not locate promql transform at: "{}"'.format(res))
        return None

    def _exec(self, cmd):
        result = subprocess.run(cmd, check=False, stdout=subprocess.PIPE)
        output = result.stdout.decode("utf-8").strip()
        return output
