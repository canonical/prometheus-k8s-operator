# Copyright 2020 Canonical Ltd.
# See LICENSE file for licensing details.

import unittest

from charms.prometheus_k8s.v0.prometheus_scrape import PrometheusConfig


class TestWildcardExpansion(unittest.TestCase):
    def test_single_wildcard_target(self):
        # GIVEN scrape_configs (aka jobs) with only one, wildcard, target
        jobs = [
            {
                "job_name": "job",
                "static_configs": [{"targets": ["*:1234"]}],
            }
        ]

        hosts = {
            "unit/0": "10.10.10.10",
            "unit/1": "11.11.11.11",
        }

        # WHEN the jobs are processed
        expanded = PrometheusConfig.expand_wildcard_targets_into_individual_jobs(jobs, hosts)

        # THEN each wildcard target is extracted into its own job
        # AND the job name is suffixed by the unit number
        # AND a default metrics_path is generated
        self.assertEqual(
            expanded,
            [
                {
                    "job_name": "job-0",
                    "static_configs": [{"targets": ["10.10.10.10:1234"]}],
                    "metrics_path": "/metrics",
                },
                {
                    "job_name": "job-1",
                    "static_configs": [{"targets": ["11.11.11.11:1234"]}],
                    "metrics_path": "/metrics",
                },
            ],
        )

    def test_single_wildcard_target_with_metrics(self):
        # GIVEN scrape_configs with only one, wildcard, target, and a custom metrics path
        jobs = [
            {
                "job_name": "job",
                "static_configs": [{"targets": ["*:1234"]}],
                "metrics_path": "/custom/path",
            }
        ]

        hosts = {
            "unit/0": "10.10.10.10",
            "unit/1": "11.11.11.11",
        }

        # WHEN the jobs are processed
        expanded = PrometheusConfig.expand_wildcard_targets_into_individual_jobs(jobs, hosts)

        # THEN each wildcard target is extracted into its own job
        # AND the job name is suffixed by the unit number
        # AND the custom metrics_path is used
        self.assertEqual(
            expanded,
            [
                {
                    "job_name": "job-0",
                    "static_configs": [{"targets": ["10.10.10.10:1234"]}],
                    "metrics_path": "/custom/path",
                },
                {
                    "job_name": "job-1",
                    "static_configs": [{"targets": ["11.11.11.11:1234"]}],
                    "metrics_path": "/custom/path",
                },
            ],
        )

    def test_mixed_targets_in_same_list(self):
        # GIVEN scrape_configs with both wildcard and non-wildcard targets in the same list
        jobs = [
            {
                "job_name": "job",
                "static_configs": [
                    {"targets": ["*:1234", "*:5678", "1.1.1.1:1111", "2.2.2.2:2222"]}
                ],
            }
        ]

        hosts = {
            "unit/0": "10.10.10.10",
            "unit/1": "11.11.11.11",
        }

        # WHEN the jobs are processed
        expanded = PrometheusConfig.expand_wildcard_targets_into_individual_jobs(jobs, hosts)

        # THEN each wildcard target is extracted into its own job
        # AND all non-wildcard targets are kept in the same static config in their own job
        # AND the wildcard job names are suffixed by the unit number
        # AND the non-wildcard jobs keep the original job name
        # AND a default metrics_path is generated
        self.assertEqual(
            expanded,
            [
                {
                    "job_name": "job-0",
                    "static_configs": [{"targets": ["10.10.10.10:1234", "10.10.10.10:5678"]}],
                    "metrics_path": "/metrics",
                },
                {
                    "job_name": "job-1",
                    "static_configs": [{"targets": ["11.11.11.11:1234", "11.11.11.11:5678"]}],
                    "metrics_path": "/metrics",
                },
                {
                    "job_name": "job",
                    "static_configs": [{"targets": ["1.1.1.1:1111", "2.2.2.2:2222"]}],
                    "metrics_path": "/metrics",
                },
            ],
        )

    def test_mixed_targets_in_same_list_without_port_number(self):
        # GIVEN scrape_configs with mixed target types in the same list, and without port numbers
        jobs = [
            {
                "job_name": "job",
                "static_configs": [{"targets": ["*", "1.1.1.1"]}],
            }
        ]

        hosts = {
            "unit/0": "10.10.10.10",
            "unit/1": "11.11.11.11",
        }

        # WHEN the jobs are processed
        expanded = PrometheusConfig.expand_wildcard_targets_into_individual_jobs(jobs, hosts)

        # THEN port is also omitted in job specs
        self.assertEqual(
            expanded,
            [
                {
                    "job_name": "job-0",
                    "static_configs": [{"targets": ["10.10.10.10"]}],
                    "metrics_path": "/metrics",
                },
                {
                    "job_name": "job-1",
                    "static_configs": [{"targets": ["11.11.11.11"]}],
                    "metrics_path": "/metrics",
                },
                {
                    "job_name": "job",
                    "static_configs": [{"targets": ["1.1.1.1"]}],
                    "metrics_path": "/metrics",
                },
            ],
        )

    def test_mixed_targets_in_sepatate_lists_in_same_static_config(self):
        # GIVEN scrape_configs with both wildcard and non-wildcard targets in neighboring lists
        jobs = [
            {
                "job_name": "job",
                "static_configs": [
                    {"targets": ["*:1234", "1.1.1.1:1111"], "labels": {"static_config": "1st"}},
                    {"targets": ["*:5678", "2.2.2.2:2222"], "labels": {"static_config": "2nd"}},
                ],
            }
        ]

        hosts = {
            "unit/0": "10.10.10.10",
            "unit/1": "11.11.11.11",
        }

        # WHEN the jobs are processed
        expanded = PrometheusConfig.expand_wildcard_targets_into_individual_jobs(jobs, hosts)

        # THEN each wildcard target is extracted into its own job
        # AND all non-wildcard targets are kept in the same static configs list in their own job
        # AND the wildcard job names are suffixed by the unit number
        # AND the non-wildcard jobs keep the original job name
        # AND a default metrics_path is generated
        # NOTE: Here, just the unit number is no longer sufficient to deduplicate job names.
        #  Implicitly relying on the dedupe algorithm down the road.
        self.assertEqual(
            expanded,
            [
                {
                    "job_name": "job-0",
                    "metrics_path": "/metrics",
                    "static_configs": [
                        {
                            "labels": {"static_config": "1st"},
                            "targets": ["10.10.10.10:1234"],
                        }
                    ],
                },
                {
                    "job_name": "job-1",
                    "metrics_path": "/metrics",
                    "static_configs": [
                        {
                            "labels": {"static_config": "1st"},
                            "targets": ["11.11.11.11:1234"],
                        }
                    ],
                },
                {
                    "job_name": "job-0",
                    "metrics_path": "/metrics",
                    "static_configs": [
                        {
                            "labels": {"static_config": "2nd"},
                            "targets": ["10.10.10.10:5678"],
                        }
                    ],
                },
                {
                    "job_name": "job-1",
                    "metrics_path": "/metrics",
                    "static_configs": [
                        {
                            "labels": {"static_config": "2nd"},
                            "targets": ["11.11.11.11:5678"],
                        }
                    ],
                },
                {
                    "job_name": "job",
                    "metrics_path": "/metrics",
                    "static_configs": [
                        {"targets": ["1.1.1.1:1111"], "labels": {"static_config": "1st"}},
                        {"targets": ["2.2.2.2:2222"], "labels": {"static_config": "2nd"}},
                    ],
                },
            ],
        )
