#!/usr/bin/env python3
# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

import grp
import logging
import subprocess
from pathlib import Path
from typing import List

import yaml
from juju import Juju
from lightkube import Client
from lightkube.resources.core_v1 import Pod
from pytest_operator.plugin import OpsTest

from src.prometheus_client import Prometheus

log = logging.getLogger(__name__)


TESTER_ALERT_RULES_PATH = "tests/integration/prometheus-tester/src/prometheus_alert_rules"


def unit_address(app_name: str, unit_num: int) -> str:
    """Find unit address for any application.

    Args:
        ops_test: pytest-operator plugin
        app_name: string name of application
        unit_num: integer number of a juju unit

    Returns:
        unit address as a string
    """
    status = Juju.status()
    return status["applications"][app_name]["units"][f"{app_name}/{unit_num}"]["address"]


def check_prometheus_is_ready(app_name: str, unit_num: int) -> bool:
    """Check if Prometheus server responds to HTTP API requests.

    Args:
        app_name: string name of Prometheus application
        unit_num: integer number of a Prometheus juju unit

    Returns:
        True if Prometheus is responsive else False
    """
    host = unit_address(app_name, unit_num)
    prometheus = Prometheus(host)
    is_ready = prometheus.is_ready()
    return is_ready


async def get_head_stats(ops_test: OpsTest, app_name: str, unit_num: int) -> dict:
    """Get prometheus head stats.

    Args:
        ops_test: pytest-operator plugin
        app_name: string name of Prometheus application
        unit_num: integer number of a Prometheus juju unit

    Returns:
        A dict of headStats.
    """
    host = unit_address(app_name, unit_num)
    prometheus = Prometheus(host)
    return prometheus.tsdb_head_stats()


def get_prometheus_config(app_name: str, unit_num: int) -> str:
    """Fetch Prometheus configuration.

    Args:
        app_name: string name of Prometheus application
        unit_num: integer number of a Prometheus juju unit

    Returns:
        Prometheus YAML configuration in string format.
    """
    host = unit_address(app_name, unit_num)
    prometheus = Prometheus(host)
    config = prometheus.config()
    return config


def get_prometheus_active_targets(app_name: str, unit_num: int = 0) -> List[dict]:
    """Fetch Prometheus active scrape targets.

    Args:
        ops_test: pytest-operator plugin
        app_name: string name of Prometheus application
        unit_num: integer number of a Prometheus juju unit

    Returns:
        Prometheus YAML configuration in string format.
    """
    host = unit_address(app_name, unit_num)
    prometheus = Prometheus(host=host)
    targets = prometheus.active_targets()
    return targets


def run_promql( promql_query: str, app_name: str, unit_num: int = 0):
    """Run a PromQL query in Prometheus.

    Args:
        ops_test: pytest-operator plugin
        promql_query: promql query expression
        app_name: string name of Prometheus application
        unit_num: integer number of a Prometheus juju unit

    Returns:
        Result of the query
    """
    host = unit_address(app_name, unit_num)
    prometheus = Prometheus(host)
    result = prometheus.run_promql(promql_query)
    return result


def get_prometheus_rules(app_name: str, unit_num: int) -> list:
    """Fetch all Prometheus rules.

    Args:
        app_name: string name of Prometheus application
        unit_num: integer number of a Prometheus juju unit

    Returns:
        a list of rule groups.
    """
    host = unit_address(app_name, unit_num)
    prometheus = Prometheus(host)
    rules = prometheus.rules()
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


def uk8s_group() -> str:
    try:
        # Classically confined microk8s
        uk8s_group = grp.getgrnam("microk8s").gr_name
    except KeyError:
        # Strictly confined microk8s
        uk8s_group = "snap_microk8s"
    return uk8s_group


def initial_workload_is_ready(app_names) -> bool:
    """Checks that the initial workload (ie. x/0) is ready.

    Args:
        ops_test: pytest-operator plugin
        app_names: array of application names to check for

    Returns:
        whether the workloads are active or not
    """
    return all(Juju._unit_statuses(name)[0].workload_status == "active" for name in app_names)


def get_podspec(ops_test: OpsTest, app_name: str, container_name: str):
    client = Client()
    pod = client.get(Pod, name=f"{app_name}-0", namespace=ops_test.model_name)
    podspec = next(iter(filter(lambda ctr: ctr.name == container_name, pod.spec.containers)))
    return podspec


async def has_metric(ops_test, query: str, app_name: str) -> bool:
    """Returns True if the query returns any time series; False otherwise."""
    for timeseries in run_promql( query, app_name):
        if timeseries.get("metric"):
            return True

    return False


def get_workload_file(
    model_name: str, app_name: str, unit_num: int, container_name: str, filepath: str
) -> bytes:
    cmd = [
        "juju",
        "ssh",
        "--model",
        model_name,
        "--container",
        container_name,
        f"{app_name}/{unit_num}",
        "cat",
        filepath,
    ]
    try:
        res = subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    except subprocess.CalledProcessError as e:
        log.error(e.stdout.decode())
        raise e
    return res.stdout
