#!/usr/bin/env python3
# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.
"""TODO: add docstring."""

import functools
import logging
import time

PROM = "prometheus-k8s"
PROM_TESTER = "prometheus-tester"


def retry(retry_num, retry_sleep_sec):

    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            for _ in range(retry_num):
                try:
                    return func(*args, **kwargs)
                except Exception:
                    time.sleep(retry_sleep_sec)
            logging.error("func %s retry failed", func)
            raise Exception("Exceed max retry num: {} failed".format(retry_num))

        return wrapper

    return decorator
