# Copyright 2022 Canonical Ltd.
# See LICENSE file for licensing details.

import copy
import unittest
from unittest import mock

import deepdiff

# FIXME: We should **NOT** move methods to the top level to make writing tests
# more convenient. Mock it with `create_autospec`. See `setUp()`
from charms.prometheus_k8s.v0.prometheus_scrape import MetricsEndpointConsumer


class TestFunctions(unittest.TestCase):
    def setUp(self):
        self.consumer = mock.create_autospec(MetricsEndpointConsumer)
        self.consumer._dedupe_job_names = lambda x: MetricsEndpointConsumer._dedupe_job_names(
            self.consumer, x
        )

    def test_dedupe_job_names(self):
        jobs = [
            {
                "job_name": "job0",
                "static_configs": [{"targets": ["localhost:9090"]}],
                "scrape_interval": "5s",
            },
            {
                "job_name": "job0",
                "static_configs": [{"targets": ["localhost:9090"]}],
                "scrape_interval": "5s",
            },
            {
                "job_name": "job1",
                "static_configs": [{"targets": ["localhost:9090"]}],
                "scrape_interval": "5s",
            },
            {
                "job_name": "job0",
                "static_configs": [{"targets": ["localhost:9090"]}],
                "scrape_interval": "10s",
            },
            {
                "job_name": "job0",
                "static_configs": [{"targets": ["localhost:9091"]}],
                "scrape_interval": "5s",
            },
        ]
        jobs_original = copy.deepcopy(jobs)
        expected = [
            {
                "job_name": "job0_6f9f1c305506707b952aef3885fa099fe36158f6359b8a06634068270645aefd",
                "scrape_interval": "5s",
                "static_configs": [{"targets": ["localhost:9090"]}],
            },
            {
                "job_name": "job0_c651cf3a8cd1b85abc0cf7620e058b87ef43e2296d1520328ce5a796e9b20993",
                "scrape_interval": "10s",
                "static_configs": [{"targets": ["localhost:9090"]}],
            },
            {
                "job_name": "job0_546b5bbb56e719d894b0a557975e0926ed093ea547c87051595d953122d2a7d6",
                "scrape_interval": "5s",
                "static_configs": [{"targets": ["localhost:9091"]}],
            },
            {
                "job_name": "job1",
                "scrape_interval": "5s",
                "static_configs": [{"targets": ["localhost:9090"]}],
            },
        ]
        self.assertTrue(
            len(deepdiff.DeepDiff(self.consumer._dedupe_job_names(jobs), expected)) == 0
        )
        # Make sure the function does not modify its argument
        self.assertEqual(jobs, jobs_original)
