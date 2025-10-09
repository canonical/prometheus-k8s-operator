#!/usr/bin/env python3
# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

import grp
import json
import logging
import subprocess
from pathlib import Path
from typing import List

import requests
import yaml
from juju.application import Application
from juju.unit import Unit
from lightkube import Client
from lightkube.resources.core_v1 import Pod
from minio import Minio
from opentelemetry import metrics
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import SERVICE_NAME, SERVICE_VERSION, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.trace import format_trace_id
from pytest_operator.plugin import OpsTest
from tenacity import retry, stop_after_attempt, wait_exponential, wait_fixed
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
    assert ops_test.model
    status = await ops_test.model.get_status()
    return status["applications"][app_name]["units"][f"{app_name}/{unit_num}"]["address"]


async def check_prometheus_is_ready(ops_test: OpsTest, app_name: str, unit_num: int) -> bool:
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
    ops_test: OpsTest, app_name: str, unit_num: int = 0
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
        if app_name in group["name"] or app_name.replace("-", "_") in group["name"]:
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


def get_podspec(ops_test: OpsTest, app_name: str, container_name: str):
    assert ops_test.model_name
    client = Client()
    pod = client.get(Pod, name=f"{app_name}-0", namespace=ops_test.model_name)
    assert pod.spec
    podspec = next(iter(filter(lambda ctr: ctr.name == container_name, pod.spec.containers)))
    return podspec


async def has_metric(ops_test, query: str, app_name: str) -> bool:
    """Returns True if the query returns any time series; False otherwise."""
    for timeseries in await run_promql(ops_test, query, app_name):
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


async def deploy_and_configure_minio(ops_test: OpsTest) -> None:
    """Deploy and set up minio and s3-integrator needed for s3-like storage backend in the HA charms."""
    assert ops_test.model
    config = {
        "access-key": "accesskey",
        "secret-key": "secretkey",
    }
    await ops_test.model.deploy("minio", channel="edge", trust=True, config=config)
    await ops_test.model.wait_for_idle(
        apps=["minio"], status="active", timeout=2000, idle_period=45
    )
    minio_addr = await unit_address(ops_test, "minio", 0)

    mc_client = Minio(
        f"{minio_addr}:9000",
        access_key="accesskey",
        secret_key="secretkey",
        secure=False,
    )

    # create tempo bucket
    found = mc_client.bucket_exists("tempo")
    if not found:
        mc_client.make_bucket("tempo")

    # configure s3-integrator
    s3_integrator_app: Application = ops_test.model.applications["s3-integrator"]
    s3_integrator_leader: Unit = s3_integrator_app.units[0]

    await s3_integrator_app.set_config(
        {
            "endpoint": f"minio-0.minio-endpoints.{ops_test.model.name}.svc.cluster.local:9000",
            "bucket": "tempo",
        }
    )

    action = await s3_integrator_leader.run_action("sync-s3-credentials", **config)
    action_result = await action.wait()
    assert action_result.status == "completed"


async def deploy_tempo_cluster(ops_test: OpsTest):
    """Deploys tempo in its HA version together with minio and s3-integrator."""
    assert ops_test.model
    tempo_app = "tempo"
    worker_app = "tempo-worker"
    tempo_worker_charm_url, worker_channel = "tempo-worker-k8s", "edge"
    tempo_coordinator_charm_url, coordinator_channel = "tempo-coordinator-k8s", "edge"
    await ops_test.model.deploy(
        tempo_worker_charm_url, application_name=worker_app, channel=worker_channel, trust=True
    )
    await ops_test.model.deploy(
        tempo_coordinator_charm_url,
        application_name=tempo_app,
        channel=coordinator_channel,
        trust=True,
    )
    await ops_test.model.deploy("s3-integrator", channel="edge")

    await ops_test.model.integrate(tempo_app + ":s3", "s3-integrator" + ":s3-credentials")
    await ops_test.model.integrate(tempo_app + ":tempo-cluster", worker_app + ":tempo-cluster")

    await deploy_and_configure_minio(ops_test)
    async with ops_test.fast_forward():
        await ops_test.model.wait_for_idle(
            apps=[tempo_app, worker_app, "s3-integrator"],
            status="active",
            timeout=2000,
            idle_period=30,
            # TODO: remove when https://github.com/canonical/tempo-coordinator-k8s-operator/issues/90 is fixed
            raise_on_error=False,
        )


def get_traces(tempo_host: str, service_name="tracegen-otlp_http", tls=True):
    """Get traces directly from Tempo REST API."""
    url = f"{'https' if tls else 'http'}://{tempo_host}:3200/api/search?tags=service.name={service_name}"
    req = requests.get(
        url,
        verify=False,
    )
    assert req.status_code == 200
    traces = json.loads(req.text)["traces"]
    return traces


@retry(stop=stop_after_attempt(15), wait=wait_exponential(multiplier=1, min=4, max=10))
async def get_traces_patiently(tempo_host, service_name="tracegen-otlp_http", tls=True):
    """Get traces directly from Tempo REST API, but also try multiple times.

    Useful for cases when Tempo might not return the traces immediately (its API is known for returning data in
    random order).
    """
    traces = get_traces(tempo_host, service_name=service_name, tls=tls)
    assert len(traces) > 0
    return traces


async def get_application_ip(ops_test: OpsTest, app_name: str) -> str:
    """Get the application IP address."""
    assert ops_test.model
    status = await ops_test.model.get_status()
    app = status["applications"][app_name]
    return app.public_address


async def push_to_otelcol(ops_test: OpsTest, metric_name: str) -> str:
    """Push a metric along with a trace ID to an Opentelemetry Collector that is related to Prometheus so that the exemplar can be stored in Prometheus.

    This block creates an exemplars by attaching a trace ID provided by the Opentelemetry SDK to a metric.
    Please visit https://opentelemetry.io/docs/languages/python/instrumentation/ for more info on how the instrumentation works and/or how to modify it.
    """
    otel_url = await unit_address(ops_test, "otelcol", 0)
    collector_endpoint = f"http://{otel_url}:4318/v1/metrics"

    resource = Resource(attributes={
        SERVICE_NAME: "service",
        SERVICE_VERSION: "1.0.0"
    })

    otlp_exporter = OTLPMetricExporter(endpoint=collector_endpoint)
    metric_reader = PeriodicExportingMetricReader(otlp_exporter, export_interval_millis=5000)
    meter_provider = MeterProvider(resource=resource, metric_readers=[metric_reader])
    metrics.set_meter_provider(meter_provider)
    meter = metrics.get_meter("meter", "1.0.0")
    counter = meter.create_counter(metric_name, description="A placeholder counter metric")
    tracer_provider = TracerProvider()

    with tracer_provider.get_tracer("service").start_as_current_span("generate_metrics_span") as span:
        span_ctx = span.get_span_context()
        trace_id = span_ctx.trace_id

        trace_id_hex = format_trace_id(trace_id)

        counter.add(100, {"trace_id":trace_id_hex})

    return trace_id_hex


@retry(wait=wait_fixed(20), stop=stop_after_attempt(6))
async def query_exemplars(
    ops_test: OpsTest, query_name: str, app: str
):

    backend_url = await unit_address(ops_test, app, 0)

    response = requests.get(f"http://{backend_url}:9090/api/v1/query_exemplars", params={'query': f"{query_name}_total"})

    assert response.status_code == 200

    response_data = response.json()

    assert response_data.get("data", []), "No exemplar data found in API."

    # Check if the exemplar with the trace_id is present in the response
    exemplars = response_data["data"][0].get("exemplars", [])

    assert exemplars, "No exemplars found in returned data"
    assert exemplars[0].get("labels", {})

    # Find the `trace_id` from the first exemplar's labels
    assert exemplars[0].get("labels").get("trace_id"), "No trace_id found in returned data"
    trace_id = exemplars[0].get("labels").get("trace_id")

    return trace_id
