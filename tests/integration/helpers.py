#!/usr/bin/env python3
# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
from pathlib import Path
from typing import List

import yaml
from pytest_operator.plugin import OpsTest
from workload import Prometheus

log = logging.getLogger(__name__)


TESTER_ALERT_RULES_PATH = "tests/integration/prometheus-tester/src/prometheus_alert_rules"


async def unit_address(ops_test: OpsTest, app_name: str, unit_num: int) -> str:
    """Find unit address for any application.

    Args:
        ops_test: pytest-operator plugin
        app_name: string name of application
        unit_num: integer number of a juju unit

    Returns:
        unit address as a string
    """
    status = await ops_test.model.get_status()
    return status["applications"][app_name]["units"][f"{app_name}/{unit_num}"]["address"]


async def check_prometheus_is_ready(ops_test: OpsTest, app_name: str, unit_num: int):
    """Check if Prometheus server responds to HTTP API requests.

    Args:
        ops_test: pytest-operator plugin
        app_name: string name of Prometheus application
        unit_num: integer number of a Prometheus juju unit

    Returns:
        True if Prometheus is responsive else False
    """
    host = await unit_address(ops_test, app_name, unit_num)
    prometheus = Prometheus(host=host)
    is_ready = await prometheus.is_ready()
    assert is_ready


async def get_head_stats(ops_test: OpsTest, app_name: str, unit_num: int) -> dict:
    """Get prometheus head stats.

    Args:
        ops_test: pytest-operator plugin
        app_name: string name of Prometheus application
        unit_num: integer number of a Prometheus juju unit

    Returns:
        A dict of headStats.
    """
    host = await unit_address(ops_test, app_name, unit_num)
    prometheus = Prometheus(host=host)
    return await prometheus.tsdb_head_stats()


async def get_prometheus_config(ops_test: OpsTest, app_name: str, unit_num: int) -> str:
    """Fetch Prometheus configuration.

    Args:
        ops_test: pytest-operator plugin
        app_name: string name of Prometheus application
        unit_num: integer number of a Prometheus juju unit

    Returns:
        Prometheus YAML configuration in string format.
    """
    host = await unit_address(ops_test, app_name, unit_num)
    prometheus = Prometheus(host=host)
    config = await prometheus.config()
    return config


async def get_prometheus_active_targets(
    ops_test: OpsTest, app_name: str, unit_num: int
) -> List[dict]:
    """Fetch Prometheus active scrape targets.

    Args:
        ops_test: pytest-operator plugin
        app_name: string name of Prometheus application
        unit_num: integer number of a Prometheus juju unit

    Returns:
        Prometheus YAML configuration in string format.
    """
    host = await unit_address(ops_test, app_name, unit_num)
    prometheus = Prometheus(host=host)
    targets = await prometheus.active_targets()
    return targets


async def run_promql(ops_test: OpsTest, promql_query: str, app_name: str, unit_num: int = 0):
    """Run a PromQL query in Prometheus.

    Args:
        ops_test: pytest-operator plugin
        promql_query: promql query expression
        app_name: string name of Prometheus application
        unit_num: integer number of a Prometheus juju unit

    Returns:
        Result of the query
    """
    host = await unit_address(ops_test, app_name, unit_num)
    prometheus = Prometheus(host=host)
    result = await prometheus.run_promql(promql_query)
    return result


async def get_prometheus_rules(ops_test: OpsTest, app_name: str, unit_num: int) -> list:
    """Fetch all Prometheus rules.

    Args:
        ops_test: pytest-operator plugin
        app_name: string name of Prometheus application
        unit_num: integer number of a Prometheus juju unit

    Returns:
        a list of rule groups.
    """
    host = await unit_address(ops_test, app_name, unit_num)
    prometheus = Prometheus(host=host)
    rules = await prometheus.rules()
    return rules


def get_job_config_for(app_name: str, job_config: str) -> dict:
    """Find scrape configuration for a specific application.

    A Prometheus scrape configuration may have multiple "jobs". The
    prometheus charm creates a separate job for each related scrape
    target charm. This functions finds the scrape job for a particular
    application.

    Args:
        app_name: string name of a scrape target application
        job_config: Prometheus scrape configuration as a YAML string

    Returns:
        a dictionary (possibly empty) representing a scrape job
    """
    jobs = yaml.safe_load(job_config)
    for job in jobs["scrape_configs"]:
        if app_name in job["job_name"]:
            return job
    return {}


def get_rules_for(app_name: str, rule_groups: list) -> list:
    """Find rule group for a specific application.

    Prometheus charm creates a rule group for each related scrape
    target. This method finds the rule group for one specific
    application.

    Args:
        app_name: string name of scrape target application
        rule_groups: list of Prometheus rule groups

    Returns:
        a dictionary (possibly empty) representing the rule group
    """
    groups = []
    for group in rule_groups:
        if app_name in group["name"]:
            groups.append(group)
    return groups


def oci_image(metadata_file: str, image_name: str) -> str:
    """Find upstream source for a container image.

    Args:
        metadata_file: string path of metadata YAML file relative
            to top level charm directory
        image_name: OCI container image string name as defined in
            metadata.yaml file

    Returns:
        upstream image source

    Raises:
        FileNotFoundError: if metadata_file path is invalid
        ValueError: if upstream source for image name can not be found
    """
    metadata = yaml.safe_load(Path(metadata_file).read_text())

    resources = metadata.get("resources", {})
    if not resources:
        raise ValueError("No resources found")

    image = resources.get(image_name, {})
    if not image:
        raise ValueError(f"{image_name} image not found")

    upstream_source = image.get("upstream-source", "")
    if not upstream_source:
        raise ValueError("Upstream source not found")

    return upstream_source


def initial_workload_is_ready(ops_test, app_names) -> bool:
    """Checks that the initial workload (ie. x/0) is ready.

    Args:
        ops_test: pytest-operator plugin
        app_names: array of application names to check for

    Returns:
        whether the workloads are active or not
    """
    return all(
        ops_test.model.applications[name].units[0].workload_status == "active"
        for name in app_names
    )


def write_tester_alert_rule_file(rule, name):
    """Inject a new alert rule into Prometheus Tester.

    Args:
        rule: a string containing Prometheus alert rule in YAML format.
        name: a string name of alert rule file
    """
    rules_path = Path(TESTER_ALERT_RULES_PATH).joinpath(name)
    with rules_path.open(mode="w") as f:
        f.write(rule)


def remove_tester_alert_rule_file(name):
    """Remove an alert rule file from Prometheus Tester.

    Args:
        rule: a string containing Prometheus alert rule in YAML format.
        name: a string name of alert rule file
    """
    rules_path = Path(TESTER_ALERT_RULES_PATH).joinpath(name)
    rules_path.unlink()


async def rebuild_prometheus_tester(ops_test):
    """Build the Prometheus Tester charm.

    Args:
        ops_test: pytest-operator plugin

    Returns:
        pytest operator handle to the Prometheus tester charm
    """
    charm_path = "tests/integration/prometheus-tester"
    charm = await ops_test.build_charm(charm_path)
    return charm


class IPAddressWorkaround:
    """Context manager for deploying a charm that needs to have its IP address.

    Due to a juju bug, occasionally some charms finish a startup sequence without
    having an ip address returned by `bind_address`.
    https://bugs.launchpad.net/juju/+bug/1929364

    On entry, the context manager changes the update status interval to the minimum 10s, so that
    the update_status hook is trigger shortly.
    On exit, the context manager restores the interval to its previous value.
    """

    def __init__(self, ops_test: OpsTest):
        self.ops_test = ops_test

    async def __aenter__(self):
        """On entry, the update status interval is set to the minimum 10s."""
        config = await self.ops_test.model.get_config()
        self.revert_to = config["update-status-hook-interval"]
        await self.ops_test.model.set_config({"update-status-hook-interval": "10s"})
        return self

    async def __aexit__(self, exc_type, exc_value, exc_traceback):
        """On exit, the update status interval is reverted to its original value."""
        await self.ops_test.model.set_config({"update-status-hook-interval": self.revert_to})


async def juju_show_unit(
    ops_test: OpsTest,
    unit_name: str,
    *,
    endpoint: str = None,
    related_unit: str = None,
    app_data_only: bool = False,
) -> dict:
    """Helper function for obtaining output of `juju show-unit`.

    Args:
        ops_test: pytest-operator fixture,
        unit_name: app name and unit num, e.g. "loki-tester/0".
        endpoint: limit output to relation data for this relation only, e.g. "logging-consumer".
        related_unit: limit output to relation data for this unit only, e.g. "loki/0".
        app_data_only: limit output to application relation data.
    See https://github.com/juju/python-libjuju/issues/642.
    """
    endpoint_arg = f"--endpoint {endpoint}" if endpoint else ""
    related_unit_arg = f"--related-unit {related_unit}" if related_unit else ""
    app_data_arg = "--app" if app_data_only else ""
    cmd = filter(
        None,
        f"juju show-unit {unit_name} {endpoint_arg} {related_unit_arg} {app_data_arg}".split(" "),
    )

    retcode, stdout, stderr = await ops_test.run(*cmd)
    assert retcode == 0, f"`juju show-unit` failed: {(stderr or stdout).strip()}"

    # Response looks like this:
    #
    # $ juju show-unit grafana-agent-k8s/0
    # grafana-agent-k8s/0:
    #   opened-ports: []
    #   charm: ch:amd64/focal/grafana-agent-k8s-7
    #   leader: true
    #   relation-info:
    #   - endpoint: logging-consumer
    #     related-endpoint: logging
    #     application-data:
    #       endpoints: '[{"url": "http://loki-k8s-0...local:3100/loki/api/v1/push"}]'
    #       promtail_binary_zip_url: https://.../promtail-linux-amd64.zip
    #     related-units:
    #       loki-k8s/0:
    #         in-scope: true
    #         data:
    #           egress-subnets: 10.152.183.143/32
    #           ingress-address: 10.152.183.143
    #           private-address: 10.152.183.143
    #   provider-id: grafana-agent-k8s-0
    #   address: 10.1.50.210

    # Return the dict without the top-level key (which is the unit itself)
    return yaml.safe_load(stdout)[unit_name]
