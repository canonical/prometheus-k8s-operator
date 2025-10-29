#!/usr/bin/env python3
# Copyright 2021 Canonical Ltd.
# See LICENSE file for licensing details.

import random
import time

from prometheus_client import Summary, start_http_server

# Metric that tracks time spent and number of requests made.
REQUEST_TIME = Summary("request_processing_seconds", "Time spent processing request")


@REQUEST_TIME.time()
def process_request(t):
    """A fake function that takes a configurable amount of time to run.

    Args:
        t: integer specifying amount of time that should be
           spent in processing this request
    """
    time.sleep(t)


def main(port=8000):
    """Expose a metrics endpoint to prometheus."""
    start_http_server(port)
    while True:
        process_request(random.random())


if __name__ == "__main__":
    main()
