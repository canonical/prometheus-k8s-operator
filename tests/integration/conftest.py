import asyncio
import shutil

import pytest


@pytest.fixture(scope="module", autouse=True)
def copy_prometheus_library_into_tester_charm(ops_test):
    """Ensure that the tester charm uses the current Prometheus library."""
    library_path = "lib/charms/prometheus_k8s/v0/prometheus_scrape.py"
    install_path = "tests/integration/prometheus-tester/" + library_path
    shutil.copyfile(library_path, install_path)


@pytest.fixture(scope="module")
async def prometheus_charm(ops_test):
    """Prometheus charm used for integration testing."""
    charm = await ops_test.build_charm(".")
    return charm


@pytest.fixture(scope="module")
async def prometheus_tester_charm(ops_test):
    """A charm to integration test the Prometheus charm."""
    charm_path = "tests/integration/prometheus-tester"
    charm = await ops_test.build_charm(charm_path)
    return charm


@pytest.fixture(scope="module")
async def prometheus_charms(ops_test):
    """Builds both charms in parallel."""
    charm_path = "tests/integration/prometheus-tester"

    prometheus, tester = await asyncio.gather(
        ops_test.build_charm("."),
        ops_test.build_charm(charm_path),
    )

    return prometheus, tester
