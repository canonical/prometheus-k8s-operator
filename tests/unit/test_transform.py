# Copyright 2020 Canonical Ltd.
# See LICENSE file for licensing details.

import subprocess
import unittest
from pathlib import PosixPath

from charms.prometheus_k8s.v0.prometheus_scrape import CosTool
from ops.charm import CharmBase
from ops.testing import Harness


# noqa: E302
# pylint: disable=too-few-public-methods
class ToolProviderCharm(CharmBase):
    """Container charm for running the integration test."""

    def __init__(self, *args):
        super().__init__(*args)
        self.tool = CosTool(self)


class TestTransform(unittest.TestCase):
    """Test that the cos-tool implementation works."""

    def setUp(self):
        self.harness = Harness(ToolProviderCharm)
        self.harness.set_model_name("transform")
        self.addCleanup(self.harness.cleanup)
        self.harness.begin()

    # pylint: disable=protected-access
    @unittest.mock.patch("platform.machine", lambda: "teakettle")
    def test_disable_on_invalid_arch(self):
        tool = self.harness.charm.tool
        self.assertIsNone(tool.path)
        self.assertTrue(tool._disabled)

    # pylint: disable=protected-access
    @unittest.mock.patch("platform.machine", lambda: "x86_64")
    def test_gives_path_on_valid_arch(self):
        """When given a valid arch, it should return the binary path."""
        transformer = self.harness.charm.tool
        self.assertIsInstance(transformer.path, PosixPath)

    @unittest.mock.patch("platform.machine", lambda: "x86_64")
    def test_setup_transformer(self):
        """When setup it should know the path to the binary."""
        tool = self.harness.charm.tool

        self.assertIsInstance(tool.path, PosixPath)

        p = str(tool.path)
        self.assertTrue(p.endswith("cos-tool-amd64"))

    @unittest.mock.patch("platform.machine", lambda: "x86_64")
    @unittest.mock.patch("subprocess.run")
    def test_returns_original_expression_when_subprocess_call_errors(self, mocked_run):
        mocked_run.side_effect = subprocess.CalledProcessError(
            returncode=10, cmd="cos-tool", stderr=""
        )

        tool = self.harness.charm.tool
        output = tool.apply_label_matchers(
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

    @unittest.mock.patch("platform.machine", lambda: "invalid")
    def test_uses_original_expression_when_binary_missing(self):
        tool = self.harness.charm.tool
        output = tool.apply_label_matchers(
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

    @unittest.mock.patch("platform.machine", lambda: "x86_64")
    def test_fetches_the_correct_expression(self):
        tool = self.harness.charm.tool

        output = tool.inject_label_matchers("up", {"juju_model": "some_juju_model"})
        assert output == 'up{juju_model="some_juju_model"}'

    @unittest.mock.patch("platform.machine", lambda: "x86_64")
    def test_handles_comparisons(self):
        tool = self.harness.charm.tool
        output = tool.inject_label_matchers("up > 1", {"juju_model": "some_juju_model"})
        assert output == 'up{juju_model="some_juju_model"} > 1'

    @unittest.mock.patch("platform.machine", lambda: "x86_64")
    def test_handles_multiple_labels(self):
        tool = self.harness.charm.tool
        output = tool.inject_label_matchers(
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


class TestValidateAlerts(unittest.TestCase):
    """Test that the cos-tool validation works."""

    def setUp(self):
        self.harness = Harness(ToolProviderCharm)
        self.harness.set_model_name("validate")
        self.addCleanup(self.harness.cleanup)
        self.harness.begin()

    @unittest.mock.patch("platform.machine", lambda: "x86_64")
    def test_returns_errors_on_bad_rule_file(self):
        tool = self.harness.charm.tool
        valid, errs = tool.validate_alert_rules(
            {
                "groups": [
                    {
                        "alert": "BadSyntax",
                        "expr": "process_cpu_seconds_total{) > 0.12",
                    }
                ]
            }
        )
        self.assertEqual(valid, False)
        self.assertIn("error validating", errs)

    @unittest.mock.patch("platform.machine", lambda: "x86_64")
    def test_successfully_validates_good_alert_rules(self):
        tool = self.harness.charm.tool
        valid, errs = tool.validate_alert_rules(
            {
                "groups": [
                    {
                        "name": "group_name",
                        "rules": [
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
                        ],
                    }
                ]
            }
        )
        self.assertEqual(errs, "")
        self.assertEqual(valid, True)
