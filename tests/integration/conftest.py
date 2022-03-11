#!/usr/bin/env python3
# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

import pytest


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
