import pytest


@pytest.fixture(scope="module")
async def prometheus_charm(ops_test):
    """Prometheus charm used for integration testing."""
    charm = await ops_test.build_charm(".")
    return charm
