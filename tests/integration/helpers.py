import yaml
from pytest_operator.plugin import OpsTest
from workload import Prometheus


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
    assert is_ready


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


def get_rules_for(app_name: str, rule_groups: list) -> dict:
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
    for group in rule_groups:
        if app_name in group["name"]:
            return group
    return {}
