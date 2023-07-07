# Copyright 2020 Canonical Ltd.
# See LICENSE file for licensing details.

import logging
import unittest
import uuid

from charms.observability_libs.v0.juju_topology import JujuTopology
from charms.prometheus_k8s.v0.prometheus_scrape import PrometheusConfig

logger = logging.getLogger(__name__)


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
            "unit/0": ("10.10.10.10", ""),
            "unit/1": ("11.11.11.11", ""),
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
            "unit/0": ("10.10.10.10", ""),
            "unit/1": ("11.11.11.11", ""),
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
            "unit/0": ("10.10.10.10", ""),
            "unit/1": ("11.11.11.11", ""),
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
            "unit/0": ("10.10.10.10", ""),
            "unit/1": ("11.11.11.11", ""),
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
            "unit/0": ("10.10.10.10", ""),
            "unit/1": ("11.11.11.11", ""),
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


class TestWildcardExpansionWithTopology(unittest.TestCase):
    """Similar to `TestWildcardExpansion`, but with rendering topology labels."""

    def test_mixed_targets_with_topology(self):
        # GIVEN scrape_configs with mixed target types in the same list, and without port numbers
        jobs = [
            {
                "job_name": "job",
                "static_configs": [{"targets": ["*", "1.1.1.1"]}],
            }
        ]

        hosts = {
            "unit/0": ("10.10.10.10", ""),
            "unit/1": ("11.11.11.11", ""),
        }

        # AND some topology
        topology = JujuTopology(
            model="model",
            model_uuid=str(uuid.uuid4()),
            application="app",
            charm_name="charm",
        )

        # WHEN the jobs are processed
        expanded = PrometheusConfig.expand_wildcard_targets_into_individual_jobs(
            jobs, hosts, topology
        )

        # THEN fully-qualified hosts have topology labels, excluding the unit
        # AND wildcard hosts have topology labels, including the unit
        self.assertEqual(
            expanded,
            [
                {
                    "job_name": "job-0",
                    "metrics_path": "/metrics",
                    "static_configs": [
                        {
                            "targets": ["10.10.10.10"],
                            "labels": {**topology.label_matcher_dict, **{"juju_unit": "unit/0"}},
                        }
                    ],
                    "relabel_configs": [PrometheusConfig.topology_relabel_config_wildcard],
                },
                {
                    "job_name": "job-1",
                    "metrics_path": "/metrics",
                    "static_configs": [
                        {
                            "targets": ["11.11.11.11"],
                            "labels": {**topology.label_matcher_dict, **{"juju_unit": "unit/1"}},
                        }
                    ],
                    "relabel_configs": [PrometheusConfig.topology_relabel_config_wildcard],
                },
                {
                    "job_name": "job",
                    "metrics_path": "/metrics",
                    "static_configs": [
                        {
                            "targets": ["1.1.1.1"],
                            "labels": topology.label_matcher_dict,
                        }
                    ],
                    "relabel_configs": [PrometheusConfig.topology_relabel_config],
                },
            ],
        )


class TestWildcardExpansionWithPathPrefix(unittest.TestCase):
    """Similar to `TestWildcardExpansion`, but with path prefix."""

    def test_default_metrics_endpoint_with_ingress_per_unit(self):
        # GIVEN scrape_configs and per-unit path prefix
        jobs = [
            {
                "job_name": "job",
                "static_configs": [{"targets": ["*", "1.1.1.1"]}],
            }
        ]

        hosts = {
            "unit/0": ("10.10.10.10", "/model-unit-0"),
            "unit/1": ("11.11.11.11", "/model-unit-1"),
        }

        # WHEN the jobs are processed
        expanded = PrometheusConfig.expand_wildcard_targets_into_individual_jobs(jobs, hosts)

        # THEN wildcard targets have the ingress prefixed to the default metrics_path
        # AND fully-qualified targets have the default metrics_path
        self.assertEqual(
            expanded,
            [
                {
                    "job_name": "job-0",
                    "static_configs": [{"targets": ["10.10.10.10"]}],
                    "metrics_path": "/model-unit-0/metrics",
                },
                {
                    "job_name": "job-1",
                    "static_configs": [{"targets": ["11.11.11.11"]}],
                    "metrics_path": "/model-unit-1/metrics",
                },
                {
                    "job_name": "job",
                    "static_configs": [{"targets": ["1.1.1.1"]}],
                    "metrics_path": "/metrics",
                },
            ],
        )

    def test_custom_metrics_endpoint_with_ingress_per_unit(self):
        # urlunparse(json.loads(json.dumps(urlparse("http://a.b/c")))) == "http://a.b/c"

        # GIVEN scrape_configs and per-unit path prefix
        jobs = [
            {
                "job_name": "job",
                "metrics_path": "/custom/path",
                "static_configs": [{"targets": ["*", "1.1.1.1"]}],
            }
        ]

        hosts = {
            "unit/0": ("10.10.10.10", "/model-unit-0"),
            "unit/1": ("11.11.11.11", "/model-unit-1"),
        }

        # WHEN the jobs are processed
        expanded = PrometheusConfig.expand_wildcard_targets_into_individual_jobs(jobs, hosts)

        # THEN wildcard targets have the ingress prefixed to the default metrics_path
        # AND fully-qualified targets have the default metrics_path
        self.assertEqual(
            expanded,
            [
                {
                    "job_name": "job-0",
                    "static_configs": [{"targets": ["10.10.10.10"]}],
                    "metrics_path": "/model-unit-0/custom/path",
                },
                {
                    "job_name": "job-1",
                    "static_configs": [{"targets": ["11.11.11.11"]}],
                    "metrics_path": "/model-unit-1/custom/path",
                },
                {
                    "job_name": "job",
                    "static_configs": [{"targets": ["1.1.1.1"]}],
                    "metrics_path": "/custom/path",
                },
            ],
        )


class TestAlertmanagerStaticConfigs(unittest.TestCase):
    def test_ip_address_only(self):
        # GIVEN a hostname only
        alertmanagers = ["1.1.1.1", "2.2.2.2"]

        # WHEN rendered
        static_configs = PrometheusConfig.render_alertmanager_static_configs(alertmanagers)

        # THEN all targets are under the same static_config
        # AND the default path_prefix is rendered
        self.assertEqual(
            static_configs,
            {
                "alertmanagers": [
                    {"scheme": "http", "path_prefix": "/", "static_configs": [{"targets": ["1.1.1.1", "2.2.2.2"]}]},
                ],
            },
        )

    def test_ip_address_and_port(self):
        # GIVEN a hostname:port
        alertmanagers = ["1.1.1.1:1111", "2.2.2.2:2222"]

        # WHEN rendered
        static_configs = PrometheusConfig.render_alertmanager_static_configs(alertmanagers)

        # THEN all targets are under the same static_config
        # AND port makes part of the target string
        # AND the default path_prefix is rendered
        self.assertEqual(
            static_configs,
            {
                "alertmanagers": [
                    {
                        "scheme": "http",
                        "path_prefix": "/",
                        "static_configs": [{"targets": ["1.1.1.1:1111", "2.2.2.2:2222"]}],
                    },
                ],
            },
        )

    def test_ip_address_port_and_same_path_prefix(self):
        # GIVEN a hostname:port/path, all with the same path
        alertmanagers = ["1.1.1.1:1111/some/path", "2.2.2.2:2222/some/path"]

        # WHEN rendered
        static_configs = PrometheusConfig.render_alertmanager_static_configs(alertmanagers)

        # THEN all targets are under the same static_config
        # AND port makes part of the target string
        # AND a path_prefix is rendered
        self.assertEqual(
            static_configs,
            {
                "alertmanagers": [
                    {
                        "scheme": "http",
                        "path_prefix": "/some/path",
                        "static_configs": [{"targets": ["1.1.1.1:1111", "2.2.2.2:2222"]}],
                    },
                ],
            },
        )

    def test_ip_address_port_and_same_path_prefix_with_scheme(self):
        # GIVEN a hostname:port/path, all with the same path
        alertmanagers = ["http://1.1.1.1:1111/some/path", "https://2.2.2.2:2222/some/path"]

        # WHEN rendered
        static_configs = PrometheusConfig.render_alertmanager_static_configs(alertmanagers)

        # THEN all targets are under the same static_config
        # AND port makes part of the target string
        # AND a path_prefix is rendered
        self.assertEqual(
            static_configs,
            {
                "alertmanagers": [
                    {
                        "scheme": "http",
                        "path_prefix": "/some/path",
                        "static_configs": [{"targets": ["1.1.1.1:1111"]}],
                    },
                    {
                        "scheme": "https",
                        "path_prefix": "/some/path",
                        "static_configs": [{"targets": ["2.2.2.2:2222"]}],
                    },
                ],
            },
        )

    def test_ip_address_port_and_different_path_prefix(self):
        # GIVEN a hostname:port/path, all with the same path
        alertmanagers = ["1.1.1.1:1111/some/path", "2.2.2.2:2222/some/other/path", "3.3.3.3"]

        # WHEN rendered
        static_configs = PrometheusConfig.render_alertmanager_static_configs(alertmanagers)

        # THEN each target is under its own static_config with its own path_prefix
        # AND port makes part of the target string
        self.assertEqual(
            static_configs,
            {
                "alertmanagers": [
                    {
                        "scheme": "http",
                        "path_prefix": "/some/path",
                        "static_configs": [{"targets": ["1.1.1.1:1111"]}],
                    },
                    {
                        "scheme": "http",
                        "path_prefix": "/some/other/path",
                        "static_configs": [{"targets": ["2.2.2.2:2222"]}],
                    },
                    {
                        "scheme": "http",
                        "path_prefix": "/",
                        "static_configs": [{"targets": ["3.3.3.3"]}],
                    },
                ],
            },
        )
