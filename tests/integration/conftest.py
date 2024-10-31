#!/usr/bin/env python3
# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

import functools
import logging
import shutil
from collections import defaultdict
from datetime import datetime
from pathlib import Path
import os
import pytest

logger = logging.getLogger(__name__)


class Store(defaultdict):
    def __init__(self):
        super(Store, self).__init__(Store)

    def __getattr__(self, key):
        """Override __getattr__ so dot syntax works on keys."""
        try:
            return self[key]
        except KeyError:
            raise AttributeError(key)

    def __setattr__(self, key, value):
        """Override __setattr__ so dot syntax works on keys."""
        self[key] = value


store = Store()


def timed_memoizer(func):
    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        fname = func.__qualname__
        logger.info("Started: %s" % fname)
        start_time = datetime.now()
        if fname in store.keys():
            ret = store[fname]
        else:
            logger.info("Return for {} not cached".format(fname))
            ret = await func(*args, **kwargs)
            store[fname] = ret
        logger.info("Finished: {} in: {} seconds".format(fname, datetime.now() - start_time))
        return ret

    return wrapper


@pytest.fixture(scope="module", autouse=True)
def copy_prometheus_library_into_tester_charm(ops_test):
    """Ensure that the tester charm uses the current Prometheus library."""
    library_path = "lib/charms/prometheus_k8s/v0/prometheus_scrape.py"
    install_path = "tests/integration/prometheus-tester/" + library_path
    shutil.copyfile(library_path, install_path)


@pytest.fixture(scope="module", autouse=True)
def remove_leftover_alert_rules(ops_test):
    """Ensure that the tester charm uses the current Prometheus library."""
    rules_path = Path("tests/integration/prometheus-tester/src/prometheus_alert_rules")

    for f in rules_path.glob("*.rule"):
        if "cpu_overuse" not in f.name:
            f.unlink()


@fixture(scope="module")
@timed_memoizer
def prometheus_charm(request):
    """Zinc charm used for integration testing."""
    charm_file = request.config.getoption("--charm-path")
    if charm_file:
        return charm_file

    subprocess.run(
        ["/snap/bin/charmcraft", "pack", "--verbose"],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    return next(Path.glob(Path("."), "prometheus-k8s*.charm")).absolute()


@fixture(scope="module")
def prometheus_oci_image():
    meta = yaml.safe_load(Path("./metadata.yaml").read_text())
    return meta["resources"]["prometheus-image"]["upstream-source"]


@fixture(scope="module")
@timed_memoizer
def prometheus_tester_charm(request):
    """Zinc charm used for integration testing."""
    charm_file = request.config.getoption("--charm-path")
    if charm_file:
        return charm_file

    subprocess.run(
        ["/snap/bin/charmcraft", "--project-dir=tests/integration/prometheus-tester", "pack", "--verbose"],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    return next(Path.glob(Path("."), "prometheus-tester*.charm")).absolute()