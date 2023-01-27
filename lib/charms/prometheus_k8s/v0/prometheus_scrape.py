# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.
"""Prometheus Scrape Library.

## Overview

This document explains how to integrate with the Prometheus charm
for the purpose of providing a metrics endpoint to Prometheus. It
also explains how alternative implementations of the Prometheus charms
may maintain the same interface and be backward compatible with all
currently integrated charms. Finally this document is the
authoritative reference on the structure of relation data that is
shared between Prometheus charms and any other charm that intends to
provide a scrape target for Prometheus.

## Source code

Source code can be found on GitHub at:
 https://github.com/canonical/prometheus-k8s-operator/tree/main/lib/charms/prometheus_k8s

## Dependencies

Using this library requires you to fetch the juju_topology library from
[observability-libs](https://charmhub.io/observability-libs/libraries/juju_topology).

`charmcraft fetch-lib charms.observability_libs.v0.juju_topology`

## Provider Library Usage

This Prometheus charm interacts with its scrape targets using its
charm library. Charms seeking to expose metric endpoints for the
Prometheus charm, must do so using the `MetricsEndpointProvider`
object from this charm library. For the simplest use cases, using the
`MetricsEndpointProvider` object only requires instantiating it,
typically in the constructor of your charm (the one which exposes a
metrics endpoint). The `MetricsEndpointProvider` constructor requires
the name of the relation over which a scrape target (metrics endpoint)
is exposed to the Prometheus charm. This relation must use the
`prometheus_scrape` interface. By default address of the metrics
endpoint is set to the unit IP address, by each unit of the
`MetricsEndpointProvider` charm. These units set their address in
response to the `PebbleReady` event of each container in the unit,
since container restarts of Kubernetes charms can result in change of
IP addresses. The default name for the metrics endpoint relation is
`metrics-endpoint`. It is strongly recommended to use the same
relation name for consistency across charms and doing so obviates the
need for an additional constructor argument. The
`MetricsEndpointProvider` object may be instantiated as follows

    from charms.prometheus_k8s.v0.prometheus_scrape import MetricsEndpointProvider

    def __init__(self, *args):
        super().__init__(*args)
        ...
        self.metrics_endpoint = MetricsEndpointProvider(self)
        ...

Note that the first argument (`self`) to `MetricsEndpointProvider` is
always a reference to the parent (scrape target) charm.

An instantiated `MetricsEndpointProvider` object will ensure that each
unit of its parent charm, is a scrape target for the
`MetricsEndpointConsumer` (Prometheus) charm. By default
`MetricsEndpointProvider` assumes each unit of the consumer charm
exports its metrics at a path given by `/metrics` on port 80. These
defaults may be changed by providing the `MetricsEndpointProvider`
constructor an optional argument (`jobs`) that represents a
Prometheus scrape job specification using Python standard data
structures. This job specification is a subset of Prometheus' own
[scrape
configuration](https://prometheus.io/docs/prometheus/latest/configuration/configuration/#scrape_config)
format but represented using Python data structures. More than one job
may be provided using the `jobs` argument. Hence `jobs` accepts a list
of dictionaries where each dictionary represents one `<scrape_config>`
object as described in the Prometheus documentation. The currently
supported configuration subset is: `job_name`, `metrics_path`,
`static_configs`

Suppose it is required to change the port on which scraped metrics are
exposed to 8000. This may be done by providing the following data
structure as the value of `jobs`.

```
[
    {
        "static_configs": [
            {
                "targets": ["*:8000"]
            }
        ]
    }
]
```

The wildcard ("*") host specification implies that the scrape targets
will automatically be set to the host addresses advertised by each
unit of the consumer charm.

It is also possible to change the metrics path and scrape multiple
ports, for example

```
[
    {
        "metrics_path": "/my-metrics-path",
        "static_configs": [
            {
                "targets": ["*:8000", "*:8081"],
            }
        ]
    }
]
```

More complex scrape configurations are possible. For example

```
[
    {
        "static_configs": [
            {
                "targets": ["10.1.32.215:7000", "*:8000"],
                "labels": {
                    "some_key": "some-value"
                }
            }
        ]
    }
]
```

This example scrapes the target "10.1.32.215" at port 7000 in addition
to scraping each unit at port 8000. There is however one difference
between wildcard targets (specified using "*") and fully qualified
targets (such as "10.1.32.215"). The Prometheus charm automatically
associates labels with metrics generated by each target. These labels
localise the source of metrics within the Juju topology by specifying
its "model name", "model UUID", "application name" and "unit
name". However unit name is associated only with wildcard targets but
not with fully qualified targets.

Multiple jobs with different metrics paths and labels are allowed, but
each job must be given a unique name:

```
[
    {
        "job_name": "my-first-job",
        "metrics_path": "one-path",
        "static_configs": [
            {
                "targets": ["*:7000"],
                "labels": {
                    "some_key": "some-value"
                }
            }
        ]
    },
    {
        "job_name": "my-second-job",
        "metrics_path": "another-path",
        "static_configs": [
            {
                "targets": ["*:8000"],
                "labels": {
                    "some_other_key": "some-other-value"
                }
            }
        ]
    }
]
```

**Important:** `job_name` should be a fixed string (e.g. hardcoded literal).
For instance, if you include variable elements, like your `unit.name`, it may break
the continuity of the metrics time series gathered by Prometheus when the leader unit
changes (e.g. on upgrade or rescale).

Additionally, it is also technically possible, but **strongly discouraged**, to
configure the following scrape-related settings, which behave as described by the
[Prometheus documentation](https://prometheus.io/docs/prometheus/latest/configuration/configuration/#scrape_config):

- `static_configs`
- `scrape_interval`
- `scrape_timeout`
- `proxy_url`
- `relabel_configs`
- `metrics_relabel_configs`
- `sample_limit`
- `label_limit`
- `label_name_length_limit`
- `label_value_length_limit`

The settings above are supported by the `prometheus_scrape` library only for the sake of
specialized facilities like the [Prometheus Scrape Config](https://charmhub.io/prometheus-scrape-config-k8s)
charm. Virtually no charms should use these settings, and charmers definitely **should not**
expose them to the Juju administrator via configuration options.

## Consumer Library Usage

The `MetricsEndpointConsumer` object may be used by Prometheus
charms to manage relations with their scrape targets. For this
purposes a Prometheus charm needs to do two things

1. Instantiate the `MetricsEndpointConsumer` object by providing it a
reference to the parent (Prometheus) charm and optionally the name of
the relation that the Prometheus charm uses to interact with scrape
targets. This relation must confirm to the `prometheus_scrape`
interface and it is strongly recommended that this relation be named
`metrics-endpoint` which is its default value.

For example a Prometheus charm may instantiate the
`MetricsEndpointConsumer` in its constructor as follows

    from charms.prometheus_k8s.v0.prometheus_scrape import MetricsEndpointConsumer

    def __init__(self, *args):
        super().__init__(*args)
        ...
        self.metrics_consumer = MetricsEndpointConsumer(self)
        ...

2. A Prometheus charm also needs to respond to the
`TargetsChangedEvent` event of the `MetricsEndpointConsumer` by adding itself as
an observer for these events, as in

    self.framework.observe(
        self.metrics_consumer.on.targets_changed,
        self._on_scrape_targets_changed,
    )

In responding to the `TargetsChangedEvent` event the Prometheus
charm must update the Prometheus configuration so that any new scrape
targets are added and/or old ones removed from the list of scraped
endpoints. For this purpose the `MetricsEndpointConsumer` object
exposes a `jobs()` method that returns a list of scrape jobs. Each
element of this list is the Prometheus scrape configuration for that
job. In order to update the Prometheus configuration, the Prometheus
charm needs to replace the current list of jobs with the list provided
by `jobs()` as follows

    def _on_scrape_targets_changed(self, event):
        ...
        scrape_jobs = self.metrics_consumer.jobs()
        for job in scrape_jobs:
            prometheus_scrape_config.append(job)
        ...

## Alerting Rules

This charm library also supports gathering alerting rules from all
related `MetricsEndpointProvider` charms and enabling corresponding alerts within the
Prometheus charm.  Alert rules are automatically gathered by `MetricsEndpointProvider`
charms when using this library, from a directory conventionally named
`prometheus_alert_rules`. This directory must reside at the top level
in the `src` folder of the consumer charm. Each file in this directory
is assumed to be in one of two formats:
- the official prometheus alert rule format, conforming to the
[Prometheus docs](https://prometheus.io/docs/prometheus/latest/configuration/alerting_rules/)
- a single rule format, which is a simplified subset of the official format,
comprising a single alert rule per file, using the same YAML fields.

The file name must have one of the following extensions:
- `.rule`
- `.rules`
- `.yml`
- `.yaml`

An example of the contents of such a file in the custom single rule
format is shown below.

```
alert: HighRequestLatency
expr: job:request_latency_seconds:mean5m{my_key=my_value} > 0.5
for: 10m
labels:
  severity: Medium
  type: HighLatency
annotations:
  summary: High request latency for {{ $labels.instance }}.
```

The `MetricsEndpointProvider` will read all available alert rules and
also inject "filtering labels" into the alert expressions. The
filtering labels ensure that alert rules are localised to the metrics
provider charm's Juju topology (application, model and its UUID). Such
a topology filter is essential to ensure that alert rules submitted by
one provider charm generates alerts only for that same charm. When
alert rules are embedded in a charm, and the charm is deployed as a
Juju application, the alert rules from that application have their
expressions automatically updated to filter for metrics coming from
the units of that application alone. This remove risk of spurious
evaluation, e.g., when you have multiple deployments of the same charm
monitored by the same Prometheus.

Not all alerts one may want to specify can be embedded in a
charm. Some alert rules will be specific to a user's use case. This is
the case, for example, of alert rules that are based on business
constraints, like expecting a certain amount of requests to a specific
API every five minutes. Such alert rules can be specified via the
[COS Config Charm](https://charmhub.io/cos-configuration-k8s),
which allows importing alert rules and other settings like dashboards
from a Git repository.

Gathering alert rules and generating rule files within the Prometheus
charm is easily done using the `alerts()` method of
`MetricsEndpointConsumer`. Alerts generated by Prometheus will
automatically include Juju topology labels in the alerts. These labels
indicate the source of the alert. The following labels are
automatically included with each alert

- `juju_model`
- `juju_model_uuid`
- `juju_application`

## Relation Data

The Prometheus charm uses both application and unit relation data to
obtain information regarding its scrape jobs, alert rules and scrape
targets. This relation data is in JSON format and it closely resembles
the YAML structure of Prometheus [scrape configuration]
(https://prometheus.io/docs/prometheus/latest/configuration/configuration/#scrape_config).

Units of Metrics provider charms advertise their names and addresses
over unit relation data using the `prometheus_scrape_unit_name` and
`prometheus_scrape_unit_address` keys. While the `scrape_metadata`,
`scrape_jobs` and `alert_rules` keys in application relation data
of Metrics provider charms hold eponymous information.

"""  # noqa: W505

import copy
import hashlib
import ipaddress
import json
import logging
import os
import platform
import re
import socket
import subprocess
import tempfile
from collections import defaultdict
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple, Union
from urllib.parse import urlparse

import yaml
from charms.observability_libs.v0.juju_topology import JujuTopology
from ops.charm import CharmBase, RelationRole
from ops.framework import (
    BoundEvent,
    EventBase,
    EventSource,
    Object,
    ObjectEvents,
    StoredDict,
    StoredList,
    StoredState,
)
from ops.model import Relation

# The unique Charmhub library identifier, never change it
LIBID = "bc84295fef5f4049878f07b131968ee2"

# Increment this major API version when introducing breaking changes
LIBAPI = 0

# Increment this PATCH version before using `charmcraft publish-lib` or reset
# to 0 if you are raising the major API version
LIBPATCH = 32

logger = logging.getLogger(__name__)


ALLOWED_KEYS = {
    "job_name",
    "metrics_path",
    "static_configs",
    "scrape_interval",
    "scrape_timeout",
    "proxy_url",
    "relabel_configs",
    "metrics_relabel_configs",
    "sample_limit",
    "label_limit",
    "label_name_length_limit",
    "label_value_length_limit",
    "scheme",
    "basic_auth",
    "tls_config",
}
DEFAULT_JOB = {
    "metrics_path": "/metrics",
    "static_configs": [{"targets": ["*:80"]}],
}


DEFAULT_RELATION_NAME = "metrics-endpoint"
RELATION_INTERFACE_NAME = "prometheus_scrape"

DEFAULT_ALERT_RULES_RELATIVE_PATH = "./src/prometheus_alert_rules"


class PrometheusConfig:
    """A namespace for utility functions for manipulating the prometheus config dict."""

    # relabel instance labels so that instance identifiers are globally unique
    # stable over unit recreation
    topology_relabel_config = {
        "source_labels": ["juju_model", "juju_model_uuid", "juju_application"],
        "separator": "_",
        "target_label": "instance",
        "regex": "(.*)",
    }

    topology_relabel_config_wildcard = {
        "source_labels": ["juju_model", "juju_model_uuid", "juju_application", "juju_unit"],
        "separator": "_",
        "target_label": "instance",
        "regex": "(.*)",
    }

    @staticmethod
    def sanitize_scrape_config(job: dict) -> dict:
        """Restrict permissible scrape configuration options.

        If job is empty then a default job is returned. The
        default job is

        ```
        {
            "metrics_path": "/metrics",
            "static_configs": [{"targets": ["*:80"]}],
        }
        ```

        Args:
            job: a dict containing a single Prometheus job
                specification.

        Returns:
            a dictionary containing a sanitized job specification.
        """
        sanitized_job = DEFAULT_JOB.copy()
        sanitized_job.update({key: value for key, value in job.items() if key in ALLOWED_KEYS})
        return sanitized_job

    @staticmethod
    def sanitize_scrape_configs(scrape_configs: List[dict]) -> List[dict]:
        """A vectorized version of `sanitize_scrape_config`."""
        return [PrometheusConfig.sanitize_scrape_config(job) for job in scrape_configs]

    @staticmethod
    def prefix_job_names(scrape_configs: List[dict], prefix: str) -> List[dict]:
        """Adds the given prefix to all the job names in the given scrape_configs list."""
        modified_scrape_configs = []
        for scrape_config in scrape_configs:
            job_name = scrape_config.get("job_name")
            modified = scrape_config.copy()
            modified["job_name"] = prefix + "_" + job_name if job_name else prefix
            modified_scrape_configs.append(modified)

        return modified_scrape_configs

    @staticmethod
    def expand_wildcard_targets_into_individual_jobs(
        scrape_jobs: List[dict],
        hosts: Dict[str, Tuple[str, str]],
        topology: Optional[JujuTopology] = None,
    ) -> List[dict]:
        """Extract wildcard hosts from the given scrape_configs list into separate jobs.

        Args:
            scrape_jobs: list of scrape jobs.
            hosts: a dictionary mapping host names to host address for
                all units of the relation for which this job configuration
                must be constructed.
            topology: optional arg for adding topology labels to scrape targets.
        """
        # hosts = self._relation_hosts(relation)

        modified_scrape_jobs = []
        for job in scrape_jobs:
            static_configs = job.get("static_configs")
            if not static_configs:
                continue

            # When a single unit specified more than one wildcard target, then they are expanded
            # into a static_config per target
            non_wildcard_static_configs = []

            for static_config in static_configs:
                targets = static_config.get("targets")
                if not targets:
                    continue

                # All non-wildcard targets remain in the same static_config
                non_wildcard_targets = []

                # All wildcard targets are extracted to a job per unit. If multiple wildcard
                # targets are specified, they remain in the same static_config (per unit).
                wildcard_targets = []

                for target in targets:
                    match = re.compile(r"\*(?:(:\d+))?").match(target)
                    if match:
                        # This is a wildcard target.
                        # Need to expand into separate jobs and remove it from this job here
                        wildcard_targets.append(target)
                    else:
                        # This is not a wildcard target. Copy it over into its own static_config.
                        non_wildcard_targets.append(target)

                # All non-wildcard targets remain in the same static_config
                if non_wildcard_targets:
                    non_wildcard_static_config = static_config.copy()
                    non_wildcard_static_config["targets"] = non_wildcard_targets

                    if topology:
                        # When non-wildcard targets (aka fully qualified hostnames) are specified,
                        # there is no reliable way to determine the name (Juju topology unit name)
                        # for such a target. Therefore labeling with Juju topology, excluding the
                        # unit name.
                        non_wildcard_static_config["labels"] = {
                            **non_wildcard_static_config.get("labels", {}),
                            **topology.label_matcher_dict,
                        }

                    non_wildcard_static_configs.append(non_wildcard_static_config)

                # Extract wildcard targets into individual jobs
                if wildcard_targets:
                    for unit_name, (unit_hostname, unit_path) in hosts.items():
                        modified_job = job.copy()
                        modified_job["static_configs"] = [static_config.copy()]
                        modified_static_config = modified_job["static_configs"][0]
                        modified_static_config["targets"] = [
                            target.replace("*", unit_hostname) for target in wildcard_targets
                        ]

                        unit_num = unit_name.split("/")[-1]
                        job_name = modified_job.get("job_name", "unnamed-job") + "-" + unit_num
                        modified_job["job_name"] = job_name
                        modified_job["metrics_path"] = unit_path + (
                            job.get("metrics_path") or "/metrics"
                        )

                        if topology:
                            # Add topology labels
                            modified_static_config["labels"] = {
                                **modified_static_config.get("labels", {}),
                                **topology.label_matcher_dict,
                                **{"juju_unit": unit_name},
                            }

                            # Instance relabeling for topology should be last in order.
                            modified_job["relabel_configs"] = modified_job.get(
                                "relabel_configs", []
                            ) + [PrometheusConfig.topology_relabel_config_wildcard]

                        modified_scrape_jobs.append(modified_job)

            if non_wildcard_static_configs:
                modified_job = job.copy()
                modified_job["static_configs"] = non_wildcard_static_configs
                modified_job["metrics_path"] = modified_job.get("metrics_path") or "/metrics"

                if topology:
                    # Instance relabeling for topology should be last in order.
                    modified_job["relabel_configs"] = modified_job.get("relabel_configs", []) + [
                        PrometheusConfig.topology_relabel_config
                    ]

                modified_scrape_jobs.append(modified_job)

        return modified_scrape_jobs

    @staticmethod
    def render_alertmanager_static_configs(alertmanagers: List[str]):
        """Render the alertmanager static_configs section from a list of URLs.

        Each target must be in the hostname:port format, and prefixes are specified in a separate
        key. Therefore, with ingress in place, would need to extract the path into the
        `path_prefix` key, which is higher up in the config hierarchy.

        https://prometheus.io/docs/prometheus/latest/configuration/configuration/#alertmanager_config

        Args:
            alertmanagers: List of alertmanager URLs.

        Returns:
            A dict representation for the static_configs section.
        """
        # Make sure it's a valid url so urlparse could parse it.
        scheme = re.compile(r"^https?://")
        sanitized = [am if scheme.search(am) else "http://" + am for am in alertmanagers]

        # Create a mapping from paths to netlocs
        # Group alertmanager targets into a dictionary of lists:
        # {path: [netloc1, netloc2]}
        paths = defaultdict(list)  # type: Dict[str, List[str]]
        for parsed in map(urlparse, sanitized):
            path = parsed.path or "/"
            paths[path].append(parsed.netloc)

        return {
            "alertmanagers": [
                {"path_prefix": path_prefix, "static_configs": [{"targets": netlocs}]}
                for path_prefix, netlocs in paths.items()
            ]
        }


class RelationNotFoundError(Exception):
    """Raised if there is no relation with the given name is found."""

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
            "The '{}' relation has '{}' as interface rather than the expected '{}'".format(
                relation_name, actual_relation_interface, expected_relation_interface
            )
        )

        super().__init__(self.message)


class RelationRoleMismatchError(Exception):
    """Raised if the relation with the given name has a different role."""

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


class InvalidAlertRuleEvent(EventBase):
    """Event emitted when alert rule files are not parsable.

    Enables us to set a clear status on the provider.
    """

    def __init__(self, handle, errors: str = "", valid: bool = False):
        super().__init__(handle)
        self.errors = errors
        self.valid = valid

    def snapshot(self) -> Dict:
        """Save alert rule information."""
        return {
            "valid": self.valid,
            "errors": self.errors,
        }

    def restore(self, snapshot):
        """Restore alert rule information."""
        self.valid = snapshot["valid"]
        self.errors = snapshot["errors"]


class MetricsEndpointProviderEvents(ObjectEvents):
    """Events raised by :class:`InvalidAlertRuleEvent`s."""

    alert_rule_status_changed = EventSource(InvalidAlertRuleEvent)


def _type_convert_stored(obj):
    """Convert Stored* to their appropriate types, recursively."""
    if isinstance(obj, StoredList):
        return list(map(_type_convert_stored, obj))
    elif isinstance(obj, StoredDict):
        rdict = {}  # type: Dict[Any, Any]
        for k in obj.keys():
            rdict[k] = _type_convert_stored(obj[k])
        return rdict
    else:
        return obj


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

    relation = charm.meta.relations[relation_name]

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


class InvalidAlertRulePathError(Exception):
    """Raised if the alert rules folder cannot be found or is otherwise invalid."""

    def __init__(
        self,
        alert_rules_absolute_path: Path,
        message: str,
    ):
        self.alert_rules_absolute_path = alert_rules_absolute_path
        self.message = message

        super().__init__(self.message)


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
        self.tool = CosTool(None)
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

            if not rule_file:
                logger.warning("Empty rules file: %s", file_path.name)
                return []
            if not isinstance(rule_file, dict):
                logger.error("Invalid rules file (must be a dict): %s", file_path.name)
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
                        alert_rule["labels"].update(self.topology.label_matcher_dict)
                        # insert juju topology filters into a prometheus alert rule
                        alert_rule["expr"] = self.tool.inject_label_matchers(
                            re.sub(r"%%juju_topology%%,?", "", alert_rule["expr"]),
                            self.topology.label_matcher_dict,
                        )

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
        for file_path in self._multi_suffix_glob(
            dir_path, [".rule", ".rules", ".yml", ".yaml"], recursive
        ):
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


class TargetsChangedEvent(EventBase):
    """Event emitted when Prometheus scrape targets change."""

    def __init__(self, handle, relation_id):
        super().__init__(handle)
        self.relation_id = relation_id

    def snapshot(self):
        """Save scrape target relation information."""
        return {"relation_id": self.relation_id}

    def restore(self, snapshot):
        """Restore scrape target relation information."""
        self.relation_id = snapshot["relation_id"]


class MonitoringEvents(ObjectEvents):
    """Event descriptor for events raised by `MetricsEndpointConsumer`."""

    targets_changed = EventSource(TargetsChangedEvent)


class MetricsEndpointConsumer(Object):
    """A Prometheus based Monitoring service."""

    on = MonitoringEvents()

    def __init__(self, charm: CharmBase, relation_name: str = DEFAULT_RELATION_NAME):
        """A Prometheus based Monitoring service.

        Args:
            charm: a `CharmBase` instance that manages this
                instance of the Prometheus service.
            relation_name: an optional string name of the relation between `charm`
                and the Prometheus charmed service. The default is "metrics-endpoint".
                It is strongly advised not to change the default, so that people
                deploying your charm will have a consistent experience with all
                other charms that consume metrics endpoints.

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

        super().__init__(charm, relation_name)
        self._charm = charm
        self._relation_name = relation_name
        self._tool = CosTool(self._charm)
        events = self._charm.on[relation_name]
        self.framework.observe(events.relation_changed, self._on_metrics_provider_relation_changed)
        self.framework.observe(
            events.relation_departed, self._on_metrics_provider_relation_departed
        )

    def _on_metrics_provider_relation_changed(self, event):
        """Handle changes with related metrics providers.

        Anytime there are changes in relations between Prometheus
        and metrics provider charms the Prometheus charm is informed,
        through a `TargetsChangedEvent` event. The Prometheus charm can
        then choose to update its scrape configuration.

        Args:
            event: a `CharmEvent` in response to which the Prometheus
                charm must update its scrape configuration.
        """
        rel_id = event.relation.id

        self.on.targets_changed.emit(relation_id=rel_id)

    def _on_metrics_provider_relation_departed(self, event):
        """Update job config when a metrics provider departs.

        When a metrics provider departs the Prometheus charm is informed
        through a `TargetsChangedEvent` event so that it can update its
        scrape configuration to ensure that the departed metrics provider
        is removed from the list of scrape jobs and

        Args:
            event: a `CharmEvent` that indicates a metrics provider
               unit has departed.
        """
        rel_id = event.relation.id
        self.on.targets_changed.emit(relation_id=rel_id)

    def jobs(self) -> list:
        """Fetch the list of scrape jobs.

        Returns:
            A list consisting of all the static scrape configurations
            for each related `MetricsEndpointProvider` that has specified
            its scrape targets.
        """
        scrape_jobs = []

        for relation in self._charm.model.relations[self._relation_name]:
            static_scrape_jobs = self._static_scrape_config(relation)
            if static_scrape_jobs:
                scrape_jobs.extend(static_scrape_jobs)

        scrape_jobs = _dedupe_job_names(scrape_jobs)

        if not self._tool.validate_scrape_jobs(scrape_jobs):
            return []

        return scrape_jobs

    @property
    def alerts(self) -> dict:
        """Fetch alerts for all relations.

        A Prometheus alert rules file consists of a list of "groups". Each
        group consists of a list of alerts (`rules`) that are sequentially
        executed. This method returns all the alert rules provided by each
        related metrics provider charm. These rules may be used to generate a
        separate alert rules file for each relation since the returned list
        of alert groups are indexed by that relations Juju topology identifier.
        The Juju topology identifier string includes substrings that identify
        alert rule related metadata such as the Juju model, model UUID and the
        application name from where the alert rule originates. Since this
        topology identifier is globally unique, it may be used for instance as
        the name for the file into which the list of alert rule groups are
        written. For each relation, the structure of data returned is a dictionary
        representation of a standard prometheus rules file:

        {"groups": [{"name": ...}, ...]}

        per official prometheus documentation
        https://prometheus.io/docs/prometheus/latest/configuration/alerting_rules/

        The value of the `groups` key is such that it may be used to generate
        a Prometheus alert rules file directly using `yaml.dump` but the
        `groups` key itself must be included as this is required by Prometheus.

        For example the list of alert rule groups returned by this method may
        be written into files consumed by Prometheus as follows

        ```
        for topology_identifier, alert_rule_groups in self.metrics_consumer.alerts().items():
            filename = "juju_" + topology_identifier + ".rules"
            path = os.path.join(PROMETHEUS_RULES_DIR, filename)
            rules = yaml.safe_dump(alert_rule_groups)
            container.push(path, rules, make_dirs=True)
        ```

        Returns:
            A dictionary mapping the Juju topology identifier of the source charm to
            its list of alert rule groups.
        """
        alerts = {}  # type: Dict[str, dict] # mapping b/w juju identifiers and alert rule files
        for relation in self._charm.model.relations[self._relation_name]:
            if not relation.units or not relation.app:
                continue

            alert_rules = json.loads(relation.data[relation.app].get("alert_rules", "{}"))
            if not alert_rules:
                continue

            alert_rules = self._inject_alert_expr_labels(alert_rules)

            identifier, topology = self._get_identifier_by_alert_rules(alert_rules)
            if not topology:
                try:
                    scrape_metadata = json.loads(relation.data[relation.app]["scrape_metadata"])
                    identifier = JujuTopology.from_dict(scrape_metadata).identifier
                    alerts[identifier] = self._tool.apply_label_matchers(alert_rules)  # type: ignore

                except KeyError as e:
                    logger.debug(
                        "Relation %s has no 'scrape_metadata': %s",
                        relation.id,
                        e,
                    )

            if not identifier:
                logger.error(
                    "Alert rules were found but no usable group or identifier was present."
                )
                continue

            _, errmsg = self._tool.validate_alert_rules(alert_rules)
            if errmsg:
                relation.data[self._charm.app]["event"] = json.dumps({"errors": errmsg})
                continue

            alerts[identifier] = alert_rules

        return alerts

    def _get_identifier_by_alert_rules(
        self, rules: dict
    ) -> Tuple[Union[str, None], Union[JujuTopology, None]]:
        """Determine an appropriate dict key for alert rules.

        The key is used as the filename when writing alerts to disk, so the structure
        and uniqueness is important.

        Args:
            rules: a dict of alert rules
        Returns:
            A tuple containing an identifier, if found, and a JujuTopology, if it could
            be constructed.
        """
        if "groups" not in rules:
            logger.debug("No alert groups were found in relation data")
            return None, None

        # Construct an ID based on what's in the alert rules if they have labels
        for group in rules["groups"]:
            try:
                labels = group["rules"][0]["labels"]
                topology = JujuTopology(
                    # Don't try to safely get required constructor fields. There's already
                    # a handler for KeyErrors
                    model_uuid=labels["juju_model_uuid"],
                    model=labels["juju_model"],
                    application=labels["juju_application"],
                    unit=labels.get("juju_unit", ""),
                    charm_name=labels.get("juju_charm", ""),
                )
                return topology.identifier, topology
            except KeyError:
                logger.debug("Alert rules were found but no usable labels were present")
                continue

        logger.warning(
            "No labeled alert rules were found, and no 'scrape_metadata' "
            "was available. Using the alert group name as filename."
        )
        try:
            for group in rules["groups"]:
                return group["name"], None
        except KeyError:
            logger.debug("No group name was found to use as identifier")

        return None, None

    def _inject_alert_expr_labels(self, rules: Dict[str, Any]) -> Dict[str, Any]:
        """Iterate through alert rules and inject topology into expressions.

        Args:
            rules: a dict of alert rules
        """
        if "groups" not in rules:
            return rules

        modified_groups = []
        for group in rules["groups"]:
            # Copy off rules, so we don't modify an object we're iterating over
            rules_copy = group["rules"]
            for idx, rule in enumerate(rules_copy):
                labels = rule.get("labels")

                if labels:
                    try:
                        topology = JujuTopology(
                            # Don't try to safely get required constructor fields. There's already
                            # a handler for KeyErrors
                            model_uuid=labels["juju_model_uuid"],
                            model=labels["juju_model"],
                            application=labels["juju_application"],
                            unit=labels.get("juju_unit", ""),
                            charm_name=labels.get("juju_charm", ""),
                        )

                        # Inject topology and put it back in the list
                        rule["expr"] = self._tool.inject_label_matchers(
                            re.sub(r"%%juju_topology%%,?", "", rule["expr"]),
                            topology.label_matcher_dict,
                        )
                    except KeyError:
                        # Some required JujuTopology key is missing. Just move on.
                        pass

                    group["rules"][idx] = rule

            modified_groups.append(group)

        rules["groups"] = modified_groups
        return rules

    def _static_scrape_config(self, relation) -> list:
        """Generate the static scrape configuration for a single relation.

        If the relation data includes `scrape_metadata` then the value
        of this key is used to annotate the scrape jobs with Juju
        Topology labels before returning them.

        Args:
            relation: an `ops.model.Relation` object whose static
                scrape configuration is required.

        Returns:
            A list (possibly empty) of scrape jobs. Each job is a
            valid Prometheus scrape configuration for that job,
            represented as a Python dictionary.
        """
        if not relation.units:
            return []

        scrape_jobs = json.loads(relation.data[relation.app].get("scrape_jobs", "[]"))

        if not scrape_jobs:
            return []

        scrape_metadata = json.loads(relation.data[relation.app].get("scrape_metadata", "{}"))

        if not scrape_metadata:
            return scrape_jobs

        topology = JujuTopology.from_dict(scrape_metadata)

        job_name_prefix = "juju_{}_prometheus_scrape".format(topology.identifier)
        scrape_jobs = PrometheusConfig.prefix_job_names(scrape_jobs, job_name_prefix)
        scrape_jobs = PrometheusConfig.sanitize_scrape_configs(scrape_jobs)

        hosts = self._relation_hosts(relation)

        scrape_jobs = PrometheusConfig.expand_wildcard_targets_into_individual_jobs(
            scrape_jobs, hosts, topology
        )

        return scrape_jobs

    def _relation_hosts(self, relation: Relation) -> Dict[str, Tuple[str, str]]:
        """Returns a mapping from unit names to (address, path) tuples, for the given relation."""
        hosts = {}
        for unit in relation.units:
            # TODO deprecate and remove unit.name
            unit_name = relation.data[unit].get("prometheus_scrape_unit_name") or unit.name
            # TODO deprecate and remove "prometheus_scrape_host"
            unit_address = relation.data[unit].get(
                "prometheus_scrape_unit_address"
            ) or relation.data[unit].get("prometheus_scrape_host")
            unit_path = relation.data[unit].get("prometheus_scrape_unit_path", "")
            if unit_name and unit_address:
                hosts.update({unit_name: (unit_address, unit_path)})

        return hosts

    def _target_parts(self, target) -> list:
        """Extract host and port from a wildcard target.

        Args:
            target: a string specifying a scrape target. A
              scrape target is expected to have the format
              "host:port". The host part may be a wildcard
              "*" and the port part can be missing (along
              with ":") in which case port is set to 80.

        Returns:
            a list with target host and port as in [host, port]
        """
        if ":" in target:
            parts = target.split(":")
        else:
            parts = [target, "80"]

        return parts


def _dedupe_job_names(jobs: List[dict]):
    """Deduplicate a list of dicts by appending a hash to the value of the 'job_name' key.

    Additionally, fully de-duplicate any identical jobs.

    Args:
        jobs: A list of prometheus scrape jobs
    """
    jobs_copy = copy.deepcopy(jobs)

    # Convert to a dict with job names as keys
    # I think this line is O(n^2) but it should be okay given the list sizes
    jobs_dict = {
        job["job_name"]: list(filter(lambda x: x["job_name"] == job["job_name"], jobs_copy))
        for job in jobs_copy
    }

    # If multiple jobs have the same name, convert the name to "name_<hash-of-job>"
    for key in jobs_dict:
        if len(jobs_dict[key]) > 1:
            for job in jobs_dict[key]:
                job_json = json.dumps(job)
                hashed = hashlib.sha256(job_json.encode()).hexdigest()
                job["job_name"] = "{}_{}".format(job["job_name"], hashed)
    new_jobs = []
    for key in jobs_dict:
        new_jobs.extend([i for i in jobs_dict[key]])

    # Deduplicate jobs which are equal
    # Again this in O(n^2) but it should be okay
    deduped_jobs = []
    seen = []
    for job in new_jobs:
        job_json = json.dumps(job)
        hashed = hashlib.sha256(job_json.encode()).hexdigest()
        if hashed in seen:
            continue
        seen.append(hashed)
        deduped_jobs.append(job)

    return deduped_jobs


def _resolve_dir_against_charm_path(charm: CharmBase, *path_elements: str) -> str:
    """Resolve the provided path items against the directory of the main file.

    Look up the directory of the `main.py` file being executed. This is normally
    going to be the charm.py file of the charm including this library. Then, resolve
    the provided path elements and, if the result path exists and is a directory,
    return its absolute path; otherwise, raise en exception.

    Raises:
        InvalidAlertRulePathError, if the path does not exist or is not a directory.
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
        raise InvalidAlertRulePathError(alerts_dir_path, "directory does not exist")
    if not alerts_dir_path.is_dir():
        raise InvalidAlertRulePathError(alerts_dir_path, "is not a directory")

    return str(alerts_dir_path)


class MetricsEndpointProvider(Object):
    """A metrics endpoint for Prometheus."""

    on = MetricsEndpointProviderEvents()

    def __init__(
        self,
        charm,
        relation_name: str = DEFAULT_RELATION_NAME,
        jobs=None,
        alert_rules_path: str = DEFAULT_ALERT_RULES_RELATIVE_PATH,
        refresh_event: Optional[Union[BoundEvent, List[BoundEvent]]] = None,
        external_url: str = "",
        lookaside_jobs_callable: Optional[Callable] = None,
    ):
        """Construct a metrics provider for a Prometheus charm.

        If your charm exposes a Prometheus metrics endpoint, the
        `MetricsEndpointProvider` object enables your charm to easily
        communicate how to reach that metrics endpoint.

        By default, a charm instantiating this object has the metrics
        endpoints of each of its units scraped by the related Prometheus
        charms. The scraped metrics are automatically tagged by the
        Prometheus charms with Juju topology data via the
        `juju_model_name`, `juju_model_uuid`, `juju_application_name`
        and `juju_unit` labels. To support such tagging `MetricsEndpointProvider`
        automatically forwards scrape metadata to a `MetricsEndpointConsumer`
        (Prometheus charm).

        Scrape targets provided by `MetricsEndpointProvider` can be
        customized when instantiating this object. For example in the
        case of a charm exposing the metrics endpoint for each of its
        units on port 8080 and the `/metrics` path, the
        `MetricsEndpointProvider` can be instantiated as follows:

            self.metrics_endpoint_provider = MetricsEndpointProvider(
                self,
                jobs=[{
                    "static_configs": [{"targets": ["*:8080"]}],
                }])

        The notation `*:<port>` means "scrape each unit of this charm on port
        `<port>`.

        In case the metrics endpoints are not on the standard `/metrics` path,
        a custom path can be specified as follows:

            self.metrics_endpoint_provider = MetricsEndpointProvider(
                self,
                jobs=[{
                    "metrics_path": "/my/strange/metrics/path",
                    "static_configs": [{"targets": ["*:8080"]}],
                }])

        Note how the `jobs` argument is a list: this allows you to expose multiple
        combinations of paths "metrics_path" and "static_configs" in case your charm
        exposes multiple endpoints, which could happen, for example, when you have
        multiple workload containers, with applications in each needing to be scraped.
        The structure of the objects in the `jobs` list is one-to-one with the
        `scrape_config` configuration item of Prometheus' own configuration (see
        https://prometheus.io/docs/prometheus/latest/configuration/configuration/#scrape_config
        ), but with only a subset of the fields allowed. The permitted fields are
        listed in `ALLOWED_KEYS` object in this charm library module.

        It is also possible to specify alert rules. By default, this library will look
        into the `<charm_parent_dir>/prometheus_alert_rules`, which in a standard charm
        layouts resolves to `src/prometheus_alert_rules`. Each alert rule goes into a
        separate `*.rule` file. If the syntax of a rule is invalid,
        the  `MetricsEndpointProvider` logs an error and does not load the particular
        rule.

        To avoid false positives and negatives in the evaluation of alert rules,
        all ingested alert rule expressions are automatically qualified using Juju
        Topology filters. This ensures that alert rules provided by your charm, trigger
        alerts based only on data scrapped from your charm. For example an alert rule
        such as the following

            alert: UnitUnavailable
            expr: up < 1
            for: 0m

        will be automatically transformed into something along the lines of the following

            alert: UnitUnavailable
            expr: up{juju_model=<model>, juju_model_uuid=<uuid-prefix>, juju_application=<app>} < 1
            for: 0m

        An attempt will be made to validate alert rules prior to loading them into Prometheus.
        If they are invalid, an event will be emitted from this object which charms can respond
        to in order to set a meaningful status for administrators.

        This can be observed via `consumer.on.alert_rule_status_changed` which contains:
            - The error(s) encountered when validating as `errors`
            - A `valid` attribute, which can be used to reset the state of charms if alert rules
              are updated via another mechanism (e.g. `cos-config`) and refreshed.

        Args:
            charm: a `CharmBase` object that manages this
                `MetricsEndpointProvider` object. Typically, this is
                `self` in the instantiating class.
            relation_name: an optional string name of the relation between `charm`
                and the Prometheus charmed service. The default is "metrics-endpoint".
                It is strongly advised not to change the default, so that people
                deploying your charm will have a consistent experience with all
                other charms that provide metrics endpoints.
            jobs: an optional list of dictionaries where each
                dictionary represents the Prometheus scrape
                configuration for a single job. When not provided, a
                default scrape configuration is provided for the
                `/metrics` endpoint polling all units of the charm on port `80`
                using the `MetricsEndpointProvider` object.
            alert_rules_path: an optional path for the location of alert rules
                files.  Defaults to "./prometheus_alert_rules",
                resolved relative to the directory hosting the charm entry file.
                The alert rules are automatically updated on charm upgrade.
            refresh_event: an optional bound event or list of bound events which
                will be observed to re-set scrape job data (IP address and others)
            external_url: an optional argument that represents an external url that
                can be generated by an Ingress or a Proxy.
            lookaside_jobs_callable: an optional `Callable` which should be invoked
                when the job configuration is built as a secondary mapping. The callable
                should return a `List[Dict]` which is syntactically identical to the
                `jobs` parameter, but can be updated out of step initialization of
                this library without disrupting the 'global' job spec.

        Raises:
            RelationNotFoundError: If there is no relation in the charm's metadata.yaml
                with the same name as provided via `relation_name` argument.
            RelationInterfaceMismatchError: The relation with the same name as provided
                via `relation_name` argument does not have the `prometheus_scrape` relation
                interface.
            RelationRoleMismatchError: If the relation with the same name as provided
                via `relation_name` argument does not have the `RelationRole.provides`
                role.
        """
        _validate_relation_by_interface_and_direction(
            charm, relation_name, RELATION_INTERFACE_NAME, RelationRole.provides
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
        self.topology = JujuTopology.from_charm(charm)

        self._charm = charm
        self._alert_rules_path = alert_rules_path
        self._relation_name = relation_name
        # sanitize job configurations to the supported subset of parameters
        jobs = [] if jobs is None else jobs
        self._jobs = PrometheusConfig.sanitize_scrape_configs(jobs)

        if external_url:
            external_url = (
                external_url if urlparse(external_url).scheme else ("http://" + external_url)
            )
        self.external_url = external_url
        self._lookaside_jobs = lookaside_jobs_callable

        events = self._charm.on[self._relation_name]
        self.framework.observe(events.relation_changed, self._on_relation_changed)

        if not refresh_event:
            # FIXME remove once podspec charms are verified.
            # `self.set_scrape_job_spec()` is called every re-init so this should not be needed.
            if len(self._charm.meta.containers) == 1:
                if "kubernetes" in self._charm.meta.series:
                    # This is a podspec charm
                    refresh_event = [self._charm.on.update_status]
                else:
                    # This is a sidecar/pebble charm
                    container = list(self._charm.meta.containers.values())[0]
                    refresh_event = [self._charm.on[container.name.replace("-", "_")].pebble_ready]
            else:
                logger.warning(
                    "%d containers are present in metadata.yaml and "
                    "refresh_event was not specified. Defaulting to update_status. "
                    "Metrics IP may not be set in a timely fashion.",
                    len(self._charm.meta.containers),
                )
                refresh_event = [self._charm.on.update_status]

        else:
            if not isinstance(refresh_event, list):
                refresh_event = [refresh_event]

        self.framework.observe(events.relation_joined, self.set_scrape_job_spec)
        for ev in refresh_event:
            self.framework.observe(ev, self.set_scrape_job_spec)

    def _on_relation_changed(self, event):
        """Check for alert rule messages in the relation data before moving on."""
        if self._charm.unit.is_leader():
            ev = json.loads(event.relation.data[event.app].get("event", "{}"))

            if ev:
                valid = bool(ev.get("valid", True))
                errors = ev.get("errors", "")

                if valid and not errors:
                    self.on.alert_rule_status_changed.emit(valid=valid)
                else:
                    self.on.alert_rule_status_changed.emit(valid=valid, errors=errors)

    def update_scrape_job_spec(self, jobs):
        """Update scrape job specification."""
        self._jobs = PrometheusConfig.sanitize_scrape_configs(jobs)
        self.set_scrape_job_spec()

    def set_scrape_job_spec(self, _=None):
        """Ensure scrape target information is made available to prometheus.

        When a metrics provider charm is related to a prometheus charm, the
        metrics provider sets specification and metadata related to its own
        scrape configuration. This information is set using Juju application
        data. In addition, each of the consumer units also sets its own
        host address in Juju unit relation data.
        """
        self._set_unit_ip()

        if not self._charm.unit.is_leader():
            return

        alert_rules = AlertRules(topology=self.topology)
        alert_rules.add_path(self._alert_rules_path, recursive=True)
        alert_rules_as_dict = alert_rules.as_dict()

        for relation in self._charm.model.relations[self._relation_name]:
            relation.data[self._charm.app]["scrape_metadata"] = json.dumps(self._scrape_metadata)
            relation.data[self._charm.app]["scrape_jobs"] = json.dumps(self._scrape_jobs)

            if alert_rules_as_dict:
                # Update relation data with the string representation of the rule file.
                # Juju topology is already included in the "scrape_metadata" field above.
                # The consumer side of the relation uses this information to name the rules file
                # that is written to the filesystem.
                relation.data[self._charm.app]["alert_rules"] = json.dumps(alert_rules_as_dict)

    def _set_unit_ip(self, _=None):
        """Set unit host address.

        Each time a metrics provider charm container is restarted it updates its own
        host address in the unit relation data for the prometheus charm.

        The only argument specified is an event, and it ignored. This is for expediency
        to be able to use this method as an event handler, although no access to the
        event is actually needed.
        """
        for relation in self._charm.model.relations[self._relation_name]:
            unit_ip = str(self._charm.model.get_binding(relation).network.bind_address)

            # TODO store entire url in relation data, instead of only select url parts.

            if self.external_url:
                parsed = urlparse(self.external_url)
                unit_address = parsed.hostname
                path = parsed.path
            elif self._is_valid_unit_address(unit_ip):
                unit_address = unit_ip
                path = ""
            else:
                unit_address = socket.getfqdn()
                path = ""

            relation.data[self._charm.unit]["prometheus_scrape_unit_address"] = unit_address
            relation.data[self._charm.unit]["prometheus_scrape_unit_path"] = path
            relation.data[self._charm.unit]["prometheus_scrape_unit_name"] = str(
                self._charm.model.unit.name
            )

    def _is_valid_unit_address(self, address: str) -> bool:
        """Validate a unit address.

        At present only IP address validation is supported, but
        this may be extended to DNS addresses also, as needed.

        Args:
            address: a string representing a unit address
        """
        try:
            _ = ipaddress.ip_address(address)
        except ValueError:
            return False

        return True

    @property
    def _scrape_jobs(self) -> list:
        """Fetch list of scrape jobs.

        Returns:
           A list of dictionaries, where each dictionary specifies a
           single scrape job for Prometheus.
        """
        jobs = self._jobs if self._jobs else [DEFAULT_JOB]
        if callable(self._lookaside_jobs):
            return jobs + PrometheusConfig.sanitize_scrape_configs(self._lookaside_jobs())
        else:
            return jobs

    @property
    def _scrape_metadata(self) -> dict:
        """Generate scrape metadata.

        Returns:
            Scrape configuration metadata for this metrics provider charm.
        """
        return self.topology.as_dict()


class PrometheusRulesProvider(Object):
    """Forward rules to Prometheus.

    This object may be used to forward rules to Prometheus. At present it only supports
    forwarding alert rules. This is unlike :class:`MetricsEndpointProvider`, which
    is used for forwarding both scrape targets and associated alert rules. This object
    is typically used when there is a desire to forward rules that apply globally (across
    all deployed charms and units) rather than to a single charm. All rule files are
    forwarded using the same 'prometheus_scrape' interface that is also used by
    `MetricsEndpointProvider`.

    Args:
        charm: A charm instance that `provides` a relation with the `prometheus_scrape` interface.
        relation_name: Name of the relation in `metadata.yaml` that
            has the `prometheus_scrape` interface.
        dir_path: Root directory for the collection of rule files.
        recursive: Whether to scan for rule files recursively.
    """

    def __init__(
        self,
        charm: CharmBase,
        relation_name: str = DEFAULT_RELATION_NAME,
        dir_path: str = DEFAULT_ALERT_RULES_RELATIVE_PATH,
        recursive=True,
    ):
        super().__init__(charm, relation_name)
        self._charm = charm
        self._relation_name = relation_name
        self._recursive = recursive

        try:
            dir_path = _resolve_dir_against_charm_path(charm, dir_path)
        except InvalidAlertRulePathError as e:
            logger.debug(
                "Invalid Prometheus alert rules folder at %s: %s",
                e.alert_rules_absolute_path,
                e.message,
            )
        self.dir_path = dir_path

        events = self._charm.on[self._relation_name]
        event_sources = [
            events.relation_joined,
            events.relation_changed,
            self._charm.on.leader_elected,
            self._charm.on.upgrade_charm,
        ]

        for event_source in event_sources:
            self.framework.observe(event_source, self._update_relation_data)

    def _reinitialize_alert_rules(self):
        """Reloads alert rules and updates all relations."""
        self._update_relation_data(None)

    def _update_relation_data(self, _):
        """Update application relation data with alert rules for all relations."""
        if not self._charm.unit.is_leader():
            return

        alert_rules = AlertRules()
        alert_rules.add_path(self.dir_path, recursive=self._recursive)
        alert_rules_as_dict = alert_rules.as_dict()

        logger.info("Updating relation data with rule files from disk")
        for relation in self._charm.model.relations[self._relation_name]:
            relation.data[self._charm.app]["alert_rules"] = json.dumps(
                alert_rules_as_dict,
                sort_keys=True,  # sort, to prevent unnecessary relation_changed events
            )


class MetricsEndpointAggregator(Object):
    """Aggregate metrics from multiple scrape targets.

    `MetricsEndpointAggregator` collects scrape target information from one
    or more related charms and forwards this to a `MetricsEndpointConsumer`
    charm, which may be in a different Juju model. However, it is
    essential that `MetricsEndpointAggregator` itself resides in the same
    model as its scrape targets, as this is currently the only way to
    ensure in Juju that the `MetricsEndpointAggregator` will be able to
    determine the model name and uuid of the scrape targets.

    `MetricsEndpointAggregator` should be used in place of
    `MetricsEndpointProvider` in the following two use cases:

    1. Integrating one or more scrape targets that do not support the
    `prometheus_scrape` interface.

    2. Integrating one or more scrape targets through cross model
    relations. Although the [Scrape Config Operator](https://charmhub.io/cos-configuration-k8s)
    may also be used for the purpose of supporting cross model
    relations.

    Using `MetricsEndpointAggregator` to build a Prometheus charm client
    only requires instantiating it. Instantiating
    `MetricsEndpointAggregator` is similar to `MetricsEndpointProvider` except
    that it requires specifying the names of three relations: the
    relation with scrape targets, the relation for alert rules, and
    that with the Prometheus charms. For example

    ```python
    self._aggregator = MetricsEndpointAggregator(
        self,
        {
            "prometheus": "monitoring",
            "scrape_target": "prometheus-target",
            "alert_rules": "prometheus-rules"
        }
    )
    ```

    `MetricsEndpointAggregator` assumes that each unit of a scrape target
    sets in its unit-level relation data two entries with keys
    "hostname" and "port". If it is required to integrate with charms
    that do not honor these assumptions, it is always possible to
    derive from `MetricsEndpointAggregator` overriding the `_get_targets()`
    method, which is responsible for aggregating the unit name, host
    address ("hostname") and port of the scrape target.
    `MetricsEndpointAggregator` also assumes that each unit of a
    scrape target sets in its unit-level relation data a key named
    "groups". The value of this key is expected to be the string
    representation of list of Prometheus Alert rules in YAML format.
    An example of a single such alert rule is

    ```yaml
    - alert: HighRequestLatency
      expr: job:request_latency_seconds:mean5m{job="myjob"} > 0.5
      for: 10m
      labels:
        severity: page
      annotations:
        summary: High request latency
    ```

    Once again if it is required to integrate with charms that do not
    honour these assumptions about alert rules then an object derived
    from `MetricsEndpointAggregator` may be used by overriding the
    `_get_alert_rules()` method.

    `MetricsEndpointAggregator` ensures that Prometheus scrape job
    specifications and alert rules are annotated with Juju topology
    information, just like `MetricsEndpointProvider` and
    `MetricsEndpointConsumer` do.

    By default, `MetricsEndpointAggregator` ensures that Prometheus
    "instance" labels refer to Juju topology. This ensures that
    instance labels are stable over unit recreation. While it is not
    advisable to change this option, if required it can be done by
    setting the "relabel_instance" keyword argument to `False` when
    constructing an aggregator object.
    """

    _stored = StoredState()

    def __init__(
        self,
        charm,
        relation_names: Optional[dict] = None,
        relabel_instance=True,
        resolve_addresses=False,
    ):
        """Construct a `MetricsEndpointAggregator`.

        Args:
            charm: a `CharmBase` object that manages this
                `MetricsEndpointAggregator` object. Typically, this is
                `self` in the instantiating class.
            relation_names: a dictionary with three keys. The value
                of the "scrape_target" and "alert_rules" keys are
                the relation names over which scrape job and alert rule
                information is gathered by this `MetricsEndpointAggregator`.
                And the value of the "prometheus" key is the name of
                the relation with a `MetricsEndpointConsumer` such as
                the Prometheus charm.
            relabel_instance: A boolean flag indicating if Prometheus
                scrape job "instance" labels must refer to Juju Topology.
            resolve_addresses: A boolean flag indiccating if the aggregator
                should attempt to perform DNS lookups of targets and append
                a `dns_name` label
        """
        self._charm = charm

        relation_names = relation_names or {}

        self._prometheus_relation = relation_names.get(
            "prometheus", "downstream-prometheus-scrape"
        )
        self._target_relation = relation_names.get("scrape_target", "prometheus-target")
        self._alert_rules_relation = relation_names.get("alert_rules", "prometheus-rules")

        super().__init__(charm, self._prometheus_relation)
        self._stored.set_default(jobs=[], alert_rules=[])

        self._relabel_instance = relabel_instance
        self._resolve_addresses = resolve_addresses

        # manage Prometheus charm relation events
        prometheus_events = self._charm.on[self._prometheus_relation]
        self.framework.observe(prometheus_events.relation_joined, self._set_prometheus_data)

        # manage list of Prometheus scrape jobs from related scrape targets
        target_events = self._charm.on[self._target_relation]
        self.framework.observe(target_events.relation_changed, self._on_prometheus_targets_changed)
        self.framework.observe(
            target_events.relation_departed, self._on_prometheus_targets_departed
        )

        # manage alert rules for Prometheus from related scrape targets
        alert_rule_events = self._charm.on[self._alert_rules_relation]
        self.framework.observe(alert_rule_events.relation_changed, self._on_alert_rules_changed)
        self.framework.observe(alert_rule_events.relation_departed, self._on_alert_rules_departed)

    def _set_prometheus_data(self, event):
        """Ensure every new Prometheus instances is updated.

        Any time a new Prometheus unit joins the relation with
        `MetricsEndpointAggregator`, that Prometheus unit is provided
        with the complete set of existing scrape jobs and alert rules.
        """
        if not self._charm.unit.is_leader():
            return

        jobs = [] + _type_convert_stored(
            self._stored.jobs
        )  # list of scrape jobs, one per relation
        for relation in self.model.relations[self._target_relation]:
            targets = self._get_targets(relation)
            if targets and relation.app:
                jobs.append(self._static_scrape_job(targets, relation.app.name))

        groups = [] + _type_convert_stored(self._stored.alert_rules)  # list of alert rule groups
        for relation in self.model.relations[self._alert_rules_relation]:
            unit_rules = self._get_alert_rules(relation)
            if unit_rules and relation.app:
                appname = relation.app.name
                rules = self._label_alert_rules(unit_rules, appname)
                group = {"name": self.group_name(appname), "rules": rules}
                groups.append(group)

        event.relation.data[self._charm.app]["scrape_jobs"] = json.dumps(jobs)
        event.relation.data[self._charm.app]["alert_rules"] = json.dumps({"groups": groups})

    def _on_prometheus_targets_changed(self, event):
        """Update scrape jobs in response to scrape target changes.

        When there is any change in relation data with any scrape
        target, the Prometheus scrape job, for that specific target is
        updated.
        """
        targets = self._get_targets(event.relation)
        if not targets:
            return

        # new scrape job for the relation that has changed
        self.set_target_job_data(targets, event.relation.app.name)

    def set_target_job_data(self, targets: dict, app_name: str, **kwargs) -> None:
        """Update scrape jobs in response to scrape target changes.

        When there is any change in relation data with any scrape
        target, the Prometheus scrape job, for that specific target is
        updated. Additionally, if this method is called manually, do the
        same.

        Args:
            targets: a `dict` containing target information
            app_name: a `str` identifying the application
        """
        if not self._charm.unit.is_leader():
            return

        # new scrape job for the relation that has changed
        updated_job = self._static_scrape_job(targets, app_name, **kwargs)

        for relation in self.model.relations[self._prometheus_relation]:
            jobs = json.loads(relation.data[self._charm.app].get("scrape_jobs", "[]"))
            # list of scrape jobs that have not changed
            jobs = [job for job in jobs if updated_job["job_name"] != job["job_name"]]
            jobs.append(updated_job)
            relation.data[self._charm.app]["scrape_jobs"] = json.dumps(jobs)

            if not _type_convert_stored(self._stored.jobs) == jobs:
                self._stored.jobs = jobs

    def _on_prometheus_targets_departed(self, event):
        """Remove scrape jobs when a target departs.

        Any time a scrape target departs, any Prometheus scrape job
        associated with that specific scrape target is removed.
        """
        job_name = self._job_name(event.relation.app.name)
        unit_name = event.unit.name
        self.remove_prometheus_jobs(job_name, unit_name)

    def remove_prometheus_jobs(self, job_name: str, unit_name: Optional[str] = ""):
        """Given a job name and unit name, remove scrape jobs associated.

        The `unit_name` parameter is used for automatic, relation data bag-based
        generation, where the unit name in labels can be used to ensure that jobs with
        similar names (which are generated via the app name when scanning relation data
        bags) are not accidentally removed, as their unit name labels will differ.
        For NRPE, the job name is calculated from an ID sent via the NRPE relation, and is
        sufficient to uniquely identify the target.
        """
        if not self._charm.unit.is_leader():
            return

        for relation in self.model.relations[self._prometheus_relation]:
            jobs = json.loads(relation.data[self._charm.app].get("scrape_jobs", "[]"))
            if not jobs:
                continue

            changed_job = [j for j in jobs if j.get("job_name") == job_name]
            if not changed_job:
                continue
            changed_job = changed_job[0]

            # list of scrape jobs that have not changed
            jobs = [job for job in jobs if job.get("job_name") != job_name]

            # list of scrape jobs for units of the same application that still exist
            configs_kept = [
                config
                for config in changed_job["static_configs"]  # type: ignore
                if config.get("labels", {}).get("juju_unit") != unit_name
            ]

            if configs_kept:
                changed_job["static_configs"] = configs_kept  # type: ignore
                jobs.append(changed_job)

            relation.data[self._charm.app]["scrape_jobs"] = json.dumps(jobs)

            if not _type_convert_stored(self._stored.jobs) == jobs:
                self._stored.jobs = jobs

    def _job_name(self, appname) -> str:
        """Construct a scrape job name.

        Each relation has its own unique scrape job name. All units in
        the relation are scraped as part of the same scrape job.

        Args:
            appname: string name of a related application.

        Returns:
            a string Prometheus scrape job name for the application.
        """
        return "juju_{}_{}_{}_prometheus_scrape".format(
            self.model.name, self.model.uuid[:7], appname
        )

    def _get_targets(self, relation) -> dict:
        """Fetch scrape targets for a relation.

        Scrape target information is returned for each unit in the
        relation. This information contains the unit name, network
        hostname (or address) for that unit, and port on which a
        metrics endpoint is exposed in that unit.

        Args:
            relation: an `ops.model.Relation` object for which scrape
                targets are required.

        Returns:
            a dictionary whose keys are names of the units in the
            relation. There values associated with each key is itself
            a dictionary of the form
            ```
            {"hostname": hostname, "port": port}
            ```
        """
        targets = {}
        for unit in relation.units:
            port = relation.data[unit].get("port", 80)
            hostname = relation.data[unit].get("hostname")
            if hostname:
                targets.update({unit.name: {"hostname": hostname, "port": port}})

        return targets

    def _static_scrape_job(self, targets, application_name, **kwargs) -> dict:
        """Construct a static scrape job for an application.

        Args:
            targets: a dictionary providing hostname and port for all
                scrape target. The keys of this dictionary are unit
                names. Values corresponding to these keys are
                themselves a dictionary with keys "hostname" and
                "port".
            application_name: a string name of the application for
                which this static scrape job is being constructed.

        Returns:
            A dictionary corresponding to a Prometheus static scrape
            job configuration for one application. The returned
            dictionary may be transformed into YAML and appended to
            the list of any existing list of Prometheus static configs.
        """
        juju_model = self.model.name
        juju_model_uuid = self.model.uuid

        job = {
            "job_name": self._job_name(application_name),
            "static_configs": [
                {
                    "targets": ["{}:{}".format(target["hostname"], target["port"])],
                    "labels": {
                        "juju_model": juju_model,
                        "juju_model_uuid": juju_model_uuid,
                        "juju_application": application_name,
                        "juju_unit": unit_name,
                        "host": target["hostname"],
                        **self._static_config_extra_labels(target),
                    },
                }
                for unit_name, target in targets.items()
            ],
            "relabel_configs": self._relabel_configs + kwargs.get("relabel_configs", []),
        }
        job.update(kwargs.get("updates", {}))

        return job

    def _static_config_extra_labels(self, target: Dict[str, str]) -> Dict[str, str]:
        """Build a list of extra static config parameters, if specified."""
        extra_info = {}

        if self._resolve_addresses:
            try:
                dns_name = socket.gethostbyaddr(target["hostname"])[0]
            except OSError:
                logger.debug("Could not perform DNS lookup for %s", target["hostname"])
                dns_name = target["hostname"]
            extra_info["dns_name"] = dns_name

        return extra_info

    @property
    def _relabel_configs(self) -> list:
        """Create Juju topology relabeling configuration.

        Using Juju topology for instance labels ensures that these
        labels are stable across unit recreation.

        Returns:
            a list of Prometheus relabeling configurations. Each item in
            this list is one relabel configuration.
        """
        return (
            [
                {
                    "source_labels": [
                        "juju_model",
                        "juju_model_uuid",
                        "juju_application",
                        "juju_unit",
                    ],
                    "separator": "_",
                    "target_label": "instance",
                    "regex": "(.*)",
                }
            ]
            if self._relabel_instance
            else []
        )

    def _on_alert_rules_changed(self, event):
        """Update alert rules in response to scrape target changes.

        When there is any change in alert rule relation data for any
        scrape target, the list of alert rules for that specific
        target is updated.
        """
        unit_rules = self._get_alert_rules(event.relation)
        if not unit_rules:
            return

        app_name = event.relation.app.name
        self.set_alert_rule_data(app_name, unit_rules)

    def set_alert_rule_data(self, name: str, unit_rules: dict, label_rules: bool = True) -> None:
        """Update alert rule data.

        The unit rules should be a dict, which is has additional Juju topology labels added. For
        rules generated by the NRPE exporter, they are pre-labeled so lookups can be performed.
        """
        if not self._charm.unit.is_leader():
            return

        if label_rules:
            rules = self._label_alert_rules(unit_rules, name)
        else:
            rules = [unit_rules]
        updated_group = {"name": self.group_name(name), "rules": rules}

        for relation in self.model.relations[self._prometheus_relation]:
            alert_rules = json.loads(relation.data[self._charm.app].get("alert_rules", "{}"))
            groups = alert_rules.get("groups", [])
            # list of alert rule groups that have not changed
            for group in groups:
                if group["name"] == updated_group["name"]:
                    group["rules"] = [r for r in group["rules"] if r not in updated_group["rules"]]
                    group["rules"].extend(updated_group["rules"])

            if updated_group["name"] not in [g["name"] for g in groups]:
                groups.append(updated_group)
            relation.data[self._charm.app]["alert_rules"] = json.dumps({"groups": groups})

            if not _type_convert_stored(self._stored.alert_rules) == groups:
                self._stored.alert_rules = groups

    def _on_alert_rules_departed(self, event):
        """Remove alert rules for departed targets.

        Any time a scrape target departs any alert rules associated
        with that specific scrape target is removed.
        """
        group_name = self.group_name(event.relation.app.name)
        unit_name = event.unit.name
        self.remove_alert_rules(group_name, unit_name)

    def remove_alert_rules(self, group_name: str, unit_name: str) -> None:
        """Remove an alert rule group from relation data."""
        if not self._charm.unit.is_leader():
            return

        for relation in self.model.relations[self._prometheus_relation]:
            alert_rules = json.loads(relation.data[self._charm.app].get("alert_rules", "{}"))
            if not alert_rules:
                continue

            groups = alert_rules.get("groups", [])
            if not groups:
                continue

            changed_group = [group for group in groups if group["name"] == group_name]
            if not changed_group:
                continue
            changed_group = changed_group[0]

            # list of alert rule groups that have not changed
            groups = [group for group in groups if group["name"] != group_name]

            # list of alert rules not associated with departing unit
            rules_kept = [
                rule
                for rule in changed_group.get("rules")  # type: ignore
                if rule.get("labels").get("juju_unit") != unit_name
            ]

            if rules_kept:
                changed_group["rules"] = rules_kept  # type: ignore
                groups.append(changed_group)

            relation.data[self._charm.app]["alert_rules"] = (
                json.dumps({"groups": groups}) if groups else "{}"
            )

            if not _type_convert_stored(self._stored.alert_rules) == groups:
                self._stored.alert_rules = groups

    def _get_alert_rules(self, relation) -> dict:
        """Fetch alert rules for a relation.

        Each unit of the related scrape target may have its own
        associated alert rules. Alert rules for all units are returned
        indexed by unit name.

        Args:
            relation: an `ops.model.Relation` object for which alert
                rules are required.

        Returns:
            a dictionary whose keys are names of the units in the
            relation. There values associated with each key is a list
            of alert rules. Each rule is in dictionary format. The
            structure "rule dictionary" corresponds to single
            Prometheus alert rule.
        """
        rules = {}
        for unit in relation.units:
            unit_rules = yaml.safe_load(relation.data[unit].get("groups", ""))
            if unit_rules:
                rules.update({unit.name: unit_rules})

        return rules

    def group_name(self, unit_name: str) -> str:
        """Construct name for an alert rule group.

        Each unit in a relation may define its own alert rules. All
        rules, for all units in a relation are grouped together and
        given a single alert rule group name.

        Args:
            unit_name: string name of a related application.

        Returns:
            a string Prometheus alert rules group name for the unit.
        """
        unit_name = re.sub(r"/", "_", unit_name)
        return "juju_{}_{}_{}_alert_rules".format(self.model.name, self.model.uuid[:7], unit_name)

    def _label_alert_rules(self, unit_rules, app_name: str) -> list:
        """Apply juju topology labels to alert rules.

        Args:
            unit_rules: a list of alert rules, where each rule is in
                dictionary format.
            app_name: a string name of the application to which the
                alert rules belong.

        Returns:
            a list of alert rules with Juju topology labels.
        """
        labeled_rules = []
        for unit_name, rules in unit_rules.items():
            for rule in rules:
                # the new JujuTopology removed this, so build it up by hand
                matchers = {
                    "juju_{}".format(k): v
                    for k, v in JujuTopology(self.model.name, self.model.uuid, app_name, unit_name)
                    .as_dict(excluded_keys=["charm_name"])
                    .items()
                }
                rule["labels"].update(matchers.items())
                labeled_rules.append(rule)

        return labeled_rules


class CosTool:
    """Uses cos-tool to inject label matchers into alert rule expressions and validate rules."""

    _path = None
    _disabled = False

    def __init__(self, charm):
        self._charm = charm

    @property
    def path(self):
        """Lazy lookup of the path of cos-tool."""
        if self._disabled:
            return None
        if not self._path:
            self._path = self._get_tool_path()
            if not self._path:
                logger.debug("Skipping injection of juju topology as label matchers")
                self._disabled = True
        return self._path

    def apply_label_matchers(self, rules) -> dict:
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

                rule["expr"] = self.inject_label_matchers(rule["expr"], topology)
        return rules

    def validate_alert_rules(self, rules: dict) -> Tuple[bool, str]:
        """Will validate correctness of alert rules, returning a boolean and any errors."""
        if not self.path:
            logger.debug("`cos-tool` unavailable. Not validating alert correctness.")
            return True, ""

        with tempfile.TemporaryDirectory() as tmpdir:
            rule_path = Path(tmpdir + "/validate_rule.yaml")
            rule_path.write_text(yaml.dump(rules))

            args = [str(self.path), "validate", str(rule_path)]
            # noinspection PyBroadException
            try:
                self._exec(args)
                return True, ""
            except subprocess.CalledProcessError as e:
                logger.debug("Validating the rules failed: %s", e.output)
                return False, ", ".join(
                    [
                        line
                        for line in e.output.decode("utf8").splitlines()
                        if "error validating" in line
                    ]
                )

    def validate_scrape_jobs(self, jobs):
        """Validate scrape jobs using cos-tool."""
        conf = {"scrape_configs": jobs}
        with tempfile.NamedTemporaryFile() as tmpfile:
            with open(tmpfile.name, "w") as f:
                f.write(yaml.safe_dump(conf))
            try:
                self._exec([str(self.path), "validate-config", tmpfile.name])
            except subprocess.CalledProcessError as e:
                logger.error("Validating scrape jobs failed: {}".format(e.output))
                return False
        return True

    def inject_label_matchers(self, expression, topology) -> str:
        """Add label matchers to an expression."""
        if not topology:
            return expression
        if not self.path:
            logger.debug("`cos-tool` unavailable. Leaving expression unchanged: %s", expression)
            return expression
        args = [str(self.path), "transform"]
        args.extend(
            ["--label-matcher={}={}".format(key, value) for key, value in topology.items()]
        )

        args.extend(["{}".format(expression)])
        # noinspection PyBroadException
        try:
            return self._exec(args)
        except subprocess.CalledProcessError as e:
            logger.debug('Applying the expression failed: "%s", falling back to the original', e)
            return expression

    def _get_tool_path(self) -> Optional[Path]:
        arch = platform.machine()
        arch = "amd64" if arch == "x86_64" else arch
        res = "cos-tool-{}".format(arch)
        try:
            path = Path(res).resolve()
            path.chmod(0o777)
            return path
        except NotImplementedError:
            logger.debug("System lacks support for chmod")
        except FileNotFoundError:
            logger.debug('Could not locate cos-tool at: "{}"'.format(res))
        return None

    def _exec(self, cmd) -> str:
        result = subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
        return result.stdout.decode("utf-8").strip()
