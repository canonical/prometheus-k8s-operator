#!/usr/bin/env python3
# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

# pytest depends on this to make fixtures work
# with custom decorators
import functools
import logging
import shutil
from collections import defaultdict
from datetime import datetime
from threading import Lock

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
lock = Lock()
locks = dict()


def timed_memoizer(func):
    global lock
    global locks
    # Seems unnecessary, but pytest needs this for fixtures

    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        logger.info("Acquiring global lock")
        lock.acquire()
        fname = func.__qualname__

        # Guard locking since dict access is not in guaranteed order,
        # then reduce the locking to per-wrapped-data
        logger.info("Locking: %s" % fname)
        locks[fname] = Lock()
        locks[fname].acquire()
        lock.release()
        logger.info("Releasing global lock")
        logger.info("Started: %s" % fname)
        start_time = datetime.now()
        if fname in store.keys():
            ret = store[fname]
        else:
            logger.info("Return for {} not cached".format(fname))
            ret = await func(*args, **kwargs)
            store[fname] = ret
        logger.info("Finished: {} in: {} seconds".format(fname, datetime.now() - start_time))
        logger.info("Unlocking: %s" % fname)
        locks[fname].release()
        return ret

    return wrapper


@pytest.fixture(scope="session", autouse=True, name="store")
def _get_store():
    return store


@pytest.fixture(scope="module", autouse=True)
def copy_prometheus_library_into_tester_charm(ops_test):
    """Ensure that the tester charm uses the current Prometheus library."""
    library_path = "lib/charms/prometheus_k8s/v0/prometheus_scrape.py"
    install_path = "tests/integration/prometheus-tester/" + library_path
    shutil.copyfile(library_path, install_path)


@pytest.fixture(scope="module")
@timed_memoizer
async def prometheus_charm(ops_test):
    """Prometheus charm used for integration testing."""
    charm = await ops_test.build_charm(".")
    return charm


@pytest.fixture(scope="module")
@timed_memoizer
async def prometheus_tester_charm(ops_test):
    """A charm to integration test the Prometheus charm."""
    charm_path = "tests/integration/prometheus-tester"
    charm = await ops_test.build_charm(charm_path)
    return charm
