# Copyright 2020 Canonical Ltd.
# See LICENSE file for licensing details.

import subprocess
import unittest
from pathlib import PosixPath

from charms.prometheus_k8s.v0.prometheus_scrape import PromqlTransformer
from ops.charm import CharmBase
from ops.testing import Harness

META = """
resources:
  promql-transform-amd64:
    type: file
    description: test
"""


# noqa: E302
# pylint: disable=too-few-public-methods
class TransformProviderCharm(CharmBase):
    """Container charm for running the integration test."""

    def __init__(self, *args):
        super().__init__(*args)
        self.transformer = PromqlTransformer(self)


class TestTransform(unittest.TestCase):
    """Test that the promql-transform implementation works."""

    def setUp(self):
        self.harness = Harness(TransformProviderCharm, meta=META)
        self.harness.set_model_name("transform")
        self.addCleanup(self.harness.cleanup)
        self.harness.add_resource("promql-transform-amd64", "dummy resource")
        self.harness.begin()

    # pylint: disable=protected-access
    @unittest.mock.patch("platform.processor", lambda: "teakettle")
    def test_disable_on_invalid_arch(self):
        transform = self.harness.charm.transformer
        self.assertIsNone(transform.path)
        self.assertTrue(transform._disabled)

    # pylint: disable=protected-access
    @unittest.mock.patch("platform.processor", lambda: "x86_64")
    def test_gives_path_on_valid_arch(self):
        """When given a valid arch, it should return the resource path."""
        transformer = self.harness.charm.transformer
        self.assertIsInstance(transformer.path, PosixPath)

    @unittest.mock.patch("platform.processor", lambda: "x86_64")
    def test_setup_transformer(self):
        """When setup it should know the path to the binary."""
        transform = self.harness.charm.transformer

        self.assertIsInstance(transform.path, PosixPath)

        p = str(transform.path)
        self.assertTrue(p.startswith("/") and p.endswith("promql-transform-amd64"))

    @unittest.mock.patch("platform.processor", lambda: "x86_64")
    @unittest.mock.patch("subprocess.run")
    def test_returns_original_expression_when_subprocess_call_errors(self, mocked_run):
        mocked_run.side_effect = subprocess.CalledProcessError(
            returncode=10, cmd="promql-transform", stderr=""
        )

        transform = self.harness.charm.transformer
        output = transform.apply_label_matchers(
            {
                "groups": [
                    {
                        "alert": "CPUOverUse",
                        "expr": "process_cpu_seconds_total > 0.12",
                        "for": "0m",
                        "labels": {
                            "severity": "Low",
                            "juju_model": "None",
                            "juju_model_uuid": "f2c1b2a6-e006-11eb-ba80-0242ac130004",
                            "juju_application": "consumer-tester",
                        },
                        "annotations": {
                            "summary": "Instance {{ $labels.instance }} CPU over use",
                            "description": "{{ $labels.instance }} of job "
                            "{{ $labels.job }} has used too much CPU.",
                        },
                    }
                ]
            }
        )
        self.assertEqual(output["groups"][0]["expr"], "process_cpu_seconds_total > 0.12")

    @unittest.mock.patch("platform.processor", lambda: "invalid")
    def test_uses_original_expression_when_resource_missing(self):
        transform = self.harness.charm.transformer
        output = transform.apply_label_matchers(
            {
                "groups": [
                    {
                        "alert": "CPUOverUse",
                        "expr": "process_cpu_seconds_total > 0.12",
                        "for": "0m",
                        "labels": {
                            "severity": "Low",
                            "juju_model": "None",
                            "juju_model_uuid": "f2c1b2a6-e006-11eb-ba80-0242ac130004",
                            "juju_application": "consumer-tester",
                        },
                        "annotations": {
                            "summary": "Instance {{ $labels.instance }} CPU over use",
                            "description": "{{ $labels.instance }} of job "
                            "{{ $labels.job }} has used too much CPU.",
                        },
                    }
                ]
            }
        )
        self.assertEqual(output["groups"][0]["expr"], "process_cpu_seconds_total > 0.12")

    @unittest.mock.patch("platform.processor", lambda: "x86_64")
    def test_fetches_the_correct_expression(self):
        self.harness.add_resource(
            "promql-transform-amd64",
            open("./promql-transform", "rb").read(),
        )
        transform = self.harness.charm.transformer
        
        output = transform._apply_label_matcher("up", {"juju_model": "some_juju_model"})
        assert output == 'up{juju_model="some_juju_model"}'

    @unittest.mock.patch("platform.processor", lambda: "x86_64")
    def test_handles_comparisons(self):
        self.harness.add_resource(
            "promql-transform-amd64",
            open("./promql-transform", "rb").read(),
        )
        transform = self.harness.charm.transformer
        output = transform._apply_label_matcher("up > 1", {"juju_model": "some_juju_model"})
        assert output == 'up{juju_model="some_juju_model"} > 1'

    @unittest.mock.patch("platform.processor", lambda: "x86_64")
    def test_handles_multiple_labels(self):
        self.harness.add_resource(
            "promql-transform-amd64",
            open("./promql-transform", "rb").read(),
        )
        transform = self.harness.charm.transformer
        output = transform._apply_label_matcher(
            "up > 1",
            {
                "juju_model": "some_juju_model",
                "juju_model_uuid": "123ABC",
                "juju_application": "some_application",
                "juju_unit": "some_application/1",
            },
        )
        assert (
            output == 'up{juju_application="some_application",juju_model="some_juju_model"'
            ',juju_model_uuid="123ABC",juju_unit="some_application/1"} > 1'
        )
