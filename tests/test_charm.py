# Copyright 2020 Balbir Thomas
# See LICENSE file for licensing details.

import unittest
import yaml

from ops.testing import Harness
from charm import PrometheusCharm

MINIMAL_CONFIG = {
    'prometheus-image-path': 'prom/prometheus',
    'advertised-port': 9090
}

SMTP_ALERTING_CONFIG = {
    'globals': {
        'smtp_smarthost': 'localhost:25',
        'smtp_from': 'alertmanager@example.org',
        'smtp_auth_username': 'alertmanager',
        'smtp_auth_password': 'password',
    }
}


class TestCharm(unittest.TestCase):
    def setUp(self):
        self.harness = Harness(PrometheusCharm)
        self.addCleanup(self.harness.cleanup)

    def test_image_path_is_required(self):
        self.harness.begin()
        missing_image_config = {
            'prometheus-image-path': '',
            'prometheus-image-username': '',
            'prometheus-image-password': ''
        }
        self.harness.update_config(missing_image_config)

        missing = self.harness.charm._check_config()
        expected = ['prometheus-image-path']
        self.assertEqual(missing, expected)

    def test_password_is_required_when_username_is_set(self):
        self.harness.begin()
        missing_password_config = {
            'prometheus-image-path': 'prom/prometheus:latest',
            'prometheus-image-username': 'some-user',
            'prometheus-image-password': '',
        }
        self.harness.update_config(missing_password_config)

        missing = self.harness.charm._check_config()
        expected = ['prometheus-image-password']
        self.assertEqual(missing, expected)

    def test_alerting_config_is_updated_by_alertmanager_relation(self):
        self.harness.begin()
        self.harness.set_leader(True)

        # check alerting config is empty without alertmanager relation
        self.harness.update_config(MINIMAL_CONFIG)
        self.assertEqual(self.harness.charm.stored.alertmanagers, {})
        rel_id = self.harness.add_relation('alertmanager', 'smtp')
        self.assertIsInstance(rel_id, int)
        self.harness.add_relation_unit(rel_id, 'smtp/0')
        pod_spec = self.harness.get_pod_spec()
        self.assertEqual(alerting_config(pod_spec), str())

        # check alerting config is updated when a alertmanager joins
        self.harness.update_relation_data(rel_id,
                                          'smtp/0',
                                          {
                                              'alerting_config':
                                              yaml.dump(SMTP_ALERTING_CONFIG)
                                          })

        pod_spec = self.harness.get_pod_spec()
        self.assertEqual(alerting_config(pod_spec), SMTP_ALERTING_CONFIG)

    def test_alerting_config_is_removed_when_alertmanager_departs(self):
        self.harness.begin()
        self.harness.set_leader(True)

        # ensure there is a non-empty alerting config
        self.harness.update_config(MINIMAL_CONFIG)
        rel_id = self.harness.add_relation('alertmanager', 'smtp')
        rel = self.harness.model.get_relation('alertmanager')
        self.assertIsInstance(rel_id, int)
        self.harness.add_relation_unit(rel_id, 'smtp/0')
        self.harness.update_relation_data(rel_id,
                                          'smtp/0',
                                          {
                                              'alerting_config':
                                              yaml.dump(SMTP_ALERTING_CONFIG)
                                          })
        pod_spec = self.harness.get_pod_spec()
        self.assertEqual(alerting_config(pod_spec), SMTP_ALERTING_CONFIG)

        # check alerting config is removed when relation departs
        self.harness.charm.on.alertmanager_relation_departed.emit(rel)
        pod_spec = self.harness.get_pod_spec()
        self.assertEqual(alerting_config(pod_spec), str())

    def test_default_cli_log_level_is_info(self):
        self.harness.begin()
        self.harness.set_leader(True)
        self.harness.update_config(MINIMAL_CONFIG)
        pod_spec = self.harness.get_pod_spec()
        self.assertEqual(cli_arg(pod_spec, '--log.level'), 'info')

    def test_invalid_log_level_defaults_to_debug(self):
        self.harness.begin()
        self.harness.set_leader(True)
        bad_log_config = MINIMAL_CONFIG
        bad_log_config['log-level'] = 'bad-level'
        self.harness.update_config(bad_log_config)
        pod_spec = self.harness.get_pod_spec()
        self.assertEqual(cli_arg(pod_spec, '--log.level'), 'debug')

    def test_valid_log_level_is_accepted(self):
        self.harness.begin()
        self.harness.set_leader(True)
        valid_log_config = MINIMAL_CONFIG
        valid_log_config['log-level'] = 'warn'
        self.harness.update_config(valid_log_config)
        pod_spec = self.harness.get_pod_spec()
        self.assertEqual(cli_arg(pod_spec, '--log.level'), 'warn')


def alerting_config(pod_spec):
    config_yaml = pod_spec[0]['containers'][0]['files'][0]['files']['prometheus.yml']
    config_dict = yaml.safe_load(config_yaml)
    alerting_yaml = config_dict['alerting']
    alerting = yaml.safe_load(alerting_yaml) if alerting_yaml else str()
    return alerting


def cli_arg(pod_spec, cli_opt):
    args = pod_spec[0]['containers'][0]['args']
    for arg in args:
        opt_list = arg.split('=')
        if len(opt_list) == 2 and opt_list[0] == cli_opt:
            return opt_list[1]
        if len(opt_list) == 1 and opt_list[0] == cli_opt:
            return opt_list[0]
    return None
