# Copyright 2020 Balbir Thomas
# See LICENSE file for licensing details.

import unittest
import yaml
import json

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
        self.harness.begin()

    def test_image_path_is_required(self):
        missing_image_config = {
            'prometheus-image-path': '',
            'prometheus-image-username': '',
            'prometheus-image-password': ''
        }
        with self.assertLogs(level='ERROR') as logger:
            self.harness.update_config(missing_image_config)
            expected_logs = [
                "ERROR:charm:Incomplete Configuration : ['prometheus-image-path']. "
                "Application will be blocked."
            ]
            self.assertEqual(sorted(logger.output), expected_logs)

        missing = self.harness.charm._check_config()
        expected = ['prometheus-image-path']
        self.assertEqual(missing, expected)

    def test_password_is_required_when_username_is_set(self):
        missing_password_config = {
            'prometheus-image-path': 'prom/prometheus:latest',
            'prometheus-image-username': 'some-user',
            'prometheus-image-password': '',
        }
        with self.assertLogs(level='ERROR') as logger:
            self.harness.update_config(missing_password_config)
            expected_logs = [
                "ERROR:charm:Incomplete Configuration : ['prometheus-image-password']. "
                "Application will be blocked."
            ]
            self.assertEqual(sorted(logger.output), expected_logs)

        missing = self.harness.charm._check_config()
        expected = ['prometheus-image-password']
        self.assertEqual(missing, expected)

    def test_alerting_config_is_updated_by_alertmanager_relation(self):
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

    def test_grafana_is_provided_port_and_source(self):
        self.harness.set_leader(True)
        self.harness.update_config(MINIMAL_CONFIG)
        rel_id = self.harness.add_relation('grafana-source', 'grafana')
        self.harness.add_relation_unit(rel_id, 'grafana/0')
        self.harness.update_relation_data(rel_id, 'grafana/0', {})
        data = self.harness.get_relation_data(rel_id, self.harness.model.unit.name)
        self.assertEqual(int(data['port']), MINIMAL_CONFIG['advertised-port'])
        self.assertEqual(data['source-type'], 'prometheus')

    def test_default_cli_log_level_is_info(self):
        self.harness.set_leader(True)
        self.harness.update_config(MINIMAL_CONFIG)
        pod_spec = self.harness.get_pod_spec()
        self.assertEqual(cli_arg(pod_spec, '--log.level'), 'info')

    def test_invalid_log_level_defaults_to_debug(self):
        self.harness.set_leader(True)
        bad_log_config = MINIMAL_CONFIG.copy()
        bad_log_config['log-level'] = 'bad-level'
        with self.assertLogs(level='ERROR') as logger:
            self.harness.update_config(bad_log_config)
            expected_logs = [
                "ERROR:root:Invalid loglevel: bad-level given, "
                "debug/info/warn/error/fatal allowed. "
                "defaulting to DEBUG loglevel."
            ]
            self.assertEqual(sorted(logger.output), expected_logs)

        pod_spec = self.harness.get_pod_spec()
        self.assertEqual(cli_arg(pod_spec, '--log.level'), 'debug')

    def test_valid_log_level_is_accepted(self):
        self.harness.set_leader(True)
        valid_log_config = MINIMAL_CONFIG.copy()
        valid_log_config['log-level'] = 'warn'
        self.harness.update_config(valid_log_config)
        pod_spec = self.harness.get_pod_spec()
        self.assertEqual(cli_arg(pod_spec, '--log.level'), 'warn')

    def test_web_admin_api_can_be_enabled(self):
        self.harness.set_leader(True)

        # without web admin enabled
        self.harness.update_config(MINIMAL_CONFIG)
        pod_spec = self.harness.get_pod_spec()
        self.assertEqual(cli_arg(pod_spec, '--web.enable-admin-api'),
                         None)

        # with web admin enabled
        admin_api_config = MINIMAL_CONFIG.copy()
        admin_api_config['web-enable-admin-api'] = True
        self.harness.update_config(admin_api_config)
        pod_spec = self.harness.get_pod_spec()
        self.assertEqual(cli_arg(pod_spec, '--web.enable-admin-api'),
                         '--web.enable-admin-api')

    def test_web_page_title_can_be_set(self):
        self.harness.set_leader(True)
        web_config = MINIMAL_CONFIG.copy()
        web_config['web-page-title'] = 'Prometheus Test Page'
        self.harness.update_config(web_config)
        pod_spec = self.harness.get_pod_spec()
        self.assertEqual(cli_arg(pod_spec, '--web.page-title')[1:-1],  # striping quotes
                         web_config['web-page-title'])

    def test_tsdb_compression_is_not_enabled_by_default(self):
        self.harness.set_leader(True)
        compress_config = MINIMAL_CONFIG.copy()
        self.harness.update_config(compress_config)
        pod_spec = self.harness.get_pod_spec()
        self.assertEqual(cli_arg(pod_spec, '--storage.tsdb.wal-compression'),
                         None)

    def test_tsdb_compression_can_be_enabled(self):
        self.harness.set_leader(True)
        compress_config = MINIMAL_CONFIG.copy()
        compress_config['tsdb-wal-compression'] = True
        self.harness.update_config(compress_config)
        pod_spec = self.harness.get_pod_spec()
        self.assertEqual(cli_arg(pod_spec, '--storage.tsdb.wal-compression'),
                         '--storage.tsdb.wal-compression')

    def test_valid_tsdb_retention_times_can_be_set(self):
        self.harness.set_leader(True)
        retention_time_config = MINIMAL_CONFIG.copy()
        acceptable_units = ['y', 'w', 'd', 'h', 'm', 's']
        for unit in acceptable_units:
            retention_time = '{}{}'.format(1, unit)
            retention_time_config['tsdb-retention-time'] = retention_time
            self.harness.update_config(retention_time_config)
            pod_spec = self.harness.get_pod_spec()
            self.assertEqual(cli_arg(pod_spec, '--storage.tsdb.retention.time'),
                             retention_time)

    def test_invalid_tsdb_retention_times_can_not_be_set(self):
        self.harness.set_leader(True)
        retention_time_config = MINIMAL_CONFIG.copy()

        # invalid unit
        retention_time = '{}{}'.format(1, 'x')
        retention_time_config['tsdb-retention-time'] = retention_time
        with self.assertLogs(level='ERROR') as logger:
            self.harness.update_config(retention_time_config)
            expected_logs = ["ERROR:charm:Invalid unit x in time spec"]
            self.assertEqual(sorted(logger.output), expected_logs)

        pod_spec = self.harness.get_pod_spec()
        self.assertEqual(cli_arg(pod_spec, '--storage.tsdb.retention.time'),
                         None)

        # invalid time value
        retention_time = '{}{}'.format(0, 'd')
        retention_time_config['tsdb-retention-time'] = retention_time
        with self.assertLogs(level='ERROR') as logger:
            self.harness.update_config(retention_time_config)
            expected_logs = ["ERROR:charm:Expected positive time spec but got 0"]
            self.assertEqual(sorted(logger.output), expected_logs)

        pod_spec = self.harness.get_pod_spec()
        self.assertEqual(cli_arg(pod_spec, '--storage.tsdb.retention.time'),
                         None)

    def test_max_web_connections_can_be_set(self):
        self.harness.set_leader(True)
        maxcon_config = MINIMAL_CONFIG.copy()
        maxcon_config['web-max-connections'] = 512
        self.harness.update_config(maxcon_config)
        pod_spec = self.harness.get_pod_spec()
        self.assertEqual(int(cli_arg(pod_spec, '--web.max-connections')),
                         maxcon_config['web-max-connections'])

    def test_alertmanager_queue_capacity_can_be_set(self):
        self.harness.set_leader(True)
        queue_config = MINIMAL_CONFIG.copy()
        queue_config['alertmanager-notification-queue-capacity'] = 512
        self.harness.update_config(queue_config)
        pod_spec = self.harness.get_pod_spec()
        self.assertEqual(int(cli_arg(pod_spec, '--alertmanager.notification-queue-capacity')),
                         queue_config['alertmanager-notification-queue-capacity'])

    def test_alertmanager_timeout_can_be_set(self):
        self.harness.set_leader(True)
        timeout_config = MINIMAL_CONFIG.copy()
        acceptable_units = ['y', 'w', 'd', 'h', 'm', 's']
        for unit in acceptable_units:
            timeout_config['alertmanager-timeout'] = '{}{}'.format(1, unit)
            self.harness.update_config(timeout_config)
            pod_spec = self.harness.get_pod_spec()
            self.assertEqual(cli_arg(pod_spec, '--alertmanager.timeout'),
                             timeout_config['alertmanager-timeout'])

    def test_global_scrape_interval_can_be_set(self):
        self.harness.set_leader(True)
        scrapeint_config = MINIMAL_CONFIG.copy()
        acceptable_units = ['y', 'w', 'd', 'h', 'm', 's']
        for unit in acceptable_units:
            scrapeint_config['scrape-interval'] = '{}{}'.format(1, unit)
            self.harness.update_config(scrapeint_config)
            pod_spec = self.harness.get_pod_spec()
            gconfig = global_config(pod_spec)
            self.assertEqual(gconfig['scrape_interval'],
                             scrapeint_config['scrape-interval'])

    def test_global_scrape_timeout_can_be_set(self):
        self.harness.set_leader(True)
        scrapetime_config = MINIMAL_CONFIG.copy()
        acceptable_units = ['y', 'w', 'd', 'h', 'm', 's']
        for unit in acceptable_units:
            scrapetime_config['scrape-timeout'] = '{}{}'.format(1, unit)
            self.harness.update_config(scrapetime_config)
            pod_spec = self.harness.get_pod_spec()
            gconfig = global_config(pod_spec)
            self.assertEqual(gconfig['scrape_timeout'],
                             scrapetime_config['scrape-timeout'])

    def test_global_evaluation_interval_can_be_set(self):
        self.harness.set_leader(True)
        evalint_config = MINIMAL_CONFIG.copy()
        acceptable_units = ['y', 'w', 'd', 'h', 'm', 's']
        for unit in acceptable_units:
            evalint_config['evaluation-interval'] = '{}{}'.format(1, unit)
            self.harness.update_config(evalint_config)
            pod_spec = self.harness.get_pod_spec()
            gconfig = global_config(pod_spec)
            self.assertEqual(gconfig['evaluation_interval'],
                             evalint_config['evaluation-interval'])

    def test_valid_external_labels_can_be_set(self):
        self.harness.set_leader(True)
        label_config = MINIMAL_CONFIG.copy()
        labels = {'name1': 'value1',
                  'name2': 'value2'}
        label_config['external-labels'] = json.dumps(labels)
        self.harness.update_config(label_config)
        pod_spec = self.harness.get_pod_spec()
        gconfig = global_config(pod_spec)
        self.assertIsNotNone(gconfig['external_labels'])
        self.assertEqual(labels, gconfig['external_labels'])

    def test_invalid_external_labels_can_not_be_set(self):
        self.harness.set_leader(True)
        label_config = MINIMAL_CONFIG.copy()
        # label value must be string
        labels = {'name': 1}
        label_config['external-labels'] = json.dumps(labels)
        with self.assertLogs(level='ERROR') as logger:
            self.harness.update_config(label_config)
            expected_logs = ["ERROR:charm:External label keys/values must be strings"]
            self.assertEqual(sorted(logger.output), expected_logs)

        pod_spec = self.harness.get_pod_spec()
        gconfig = global_config(pod_spec)
        self.assertIsNone(gconfig.get('external_labels'))

    def test_default_scrape_config_is_always_set(self):
        self.harness.set_leader(True)
        self.harness.update_config(MINIMAL_CONFIG)
        pod_spec = self.harness.get_pod_spec()
        prometheus_scrape_config = scrape_config(pod_spec, 'prometheus')
        self.assertIsNotNone(prometheus_scrape_config, 'No default config found')

    def test_k8s_scrape_config_can_be_set(self):
        self.harness.set_leader(True)
        k8s_config = MINIMAL_CONFIG.copy()
        k8s_config['monitor-k8s'] = True
        self.harness.update_config(k8s_config)
        pod_spec = self.harness.get_pod_spec()
        k8s_api_scrape_config = scrape_config(pod_spec, 'kubernetes-apiservers')
        self.assertIsNotNone(k8s_api_scrape_config, 'No k8s API server scrape config found')
        k8s_node_scrape_config = scrape_config(pod_spec, 'kubernetes-nodes')
        self.assertIsNotNone(k8s_node_scrape_config, 'No k8s nodes scrape config found')
        k8s_ca_scrape_config = scrape_config(pod_spec, 'kubernetes-cadvisor')
        self.assertIsNotNone(k8s_ca_scrape_config, 'No k8s cAdvisor scrape config found')
        k8s_ep_scrape_config = scrape_config(pod_spec, 'kubernetes-service-endpoints')
        self.assertIsNotNone(k8s_ep_scrape_config, 'No k8s service endpoints scrape config found')
        k8s_svc_scrape_config = scrape_config(pod_spec, 'kubernetes-services')
        self.assertIsNotNone(k8s_svc_scrape_config, 'No k8s services scrape config found')
        k8s_in_scrape_config = scrape_config(pod_spec, 'kubernetes-ingresses')
        self.assertIsNotNone(k8s_in_scrape_config, 'No k8s ingress scrape config found')
        k8s_pod_scrape_config = scrape_config(pod_spec, 'kubernetes-pods')
        self.assertIsNotNone(k8s_pod_scrape_config, 'No k8s pods scrape config found')


def alerting_config(pod_spec):
    config_yaml = pod_spec[0]['containers'][0]['files'][0]['files']['prometheus.yml']
    config_dict = yaml.safe_load(config_yaml)
    alerting_yaml = config_dict.get('alerting')
    alerting = str()
    if alerting_yaml:
        alerting = yaml.safe_load(alerting_yaml)
    return alerting


def global_config(pod_spec):
    config_yaml = pod_spec[0]['containers'][0]['files'][0]['files']['prometheus.yml']
    config_dict = yaml.safe_load(config_yaml)
    return config_dict['global']


def scrape_config(pod_spec, job_name):
    config_yaml = pod_spec[0]['containers'][0]['files'][0]['files']['prometheus.yml']
    config_dict = yaml.safe_load(config_yaml)
    scrape_configs = config_dict['scrape_configs']
    for config in scrape_configs:
        if config['job_name'] == job_name:
            return config
    return None


def cli_arg(pod_spec, cli_opt):
    args = pod_spec[0]['containers'][0]['args']
    for arg in args:
        opt_list = arg.split('=')
        if len(opt_list) == 2 and opt_list[0] == cli_opt:
            return opt_list[1]
        if len(opt_list) == 1 and opt_list[0] == cli_opt:
            return opt_list[0]
    return None
