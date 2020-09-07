#!/usr/bin/env python3
# Copyright 2020 Balbir Thomas
# See LICENSE file for licensing details.

import logging
import yaml
import json

from ops.charm import CharmBase
from ops.framework import StoredState
from ops.main import main
from ops.model import ActiveStatus, MaintenanceStatus, BlockedStatus

logger = logging.getLogger(__name__)


class PrometheusCharm(CharmBase):

    stored = StoredState()

    def __init__(self, *args):
        logger.debug('Initializing Charm')

        super().__init__(*args)
        self.stored.set_default(alertmanagers=dict())

        self.framework.observe(self.on.config_changed, self._on_config_changed)
        self.framework.observe(self.on.stop, self._on_stop)
        self.framework.observe(self.on['alertmanager'].relation_changed,
                               self.on_alertmanager_changed)
        self.framework.observe(self.on['alertmanager'].relation_departed,
                               self.on_alertmanager_departed)

    def _on_config_changed(self, _):
        self.configure_pod()

    def _on_stop(self, _):
        self.unit.status = MaintenanceStatus('Pod is terminating.')

    def on_alertmanager_changed(self, event):
        if not self.unit.is_leader():
            logger.debug('{} is not leader. '
                         'Not handling alertmanager change.'.format(
                             self.unit.name))
            return

        if event.unit is None:
            self.stored.alertmanagers.pop(event.relation.id)
            logger.warning('Got null event unit on alertmanager changed')
            return

        alerting_config = event.relation.data[event.unit].get('alerting_config', {})
        logger.debug('Received alerting config: {}'.format(alerting_config))

        if not alerting_config:
            logger.warning('Got empty alerting config for relation id {}'.format(
                event.relation.id))
            return

        self.stored.alertmanagers.update({event.relation.id: alerting_config})

        self.configure_pod()

    def on_alertmanager_departed(self, event):
        if not self.unit.is_leader():
            logger.debug('{} is not leader. '
                         'Not handling alertmanager departed.'.format(
                             self.unit.name))
            return

        self.stored.alertmanagers.pop(event.relation.id)
        self.configure_pod()

    def _cli_args(self):
        config = self.model.config
        args = [
            '--config.file=/etc/prometheus/prometheus.yml',
            '--storage.tsdb.path=/prometheus',
            '--web.enable-lifecycle',
            '--web.console.templates=/usr/share/prometheus/consoles',
            '--web.console.libraries=/usr/share/prometheus/console_libraries'
        ]

        # get log level
        allowed_log_levels = ['debug', 'info', 'warn', 'error', 'fatal']
        if config.get('log-level'):
            log_level = config['log-level'].lower()
        else:
            log_level = 'info'

        # If log level is invalid set it to debug
        if log_level not in allowed_log_levels:
            logging.error(
                'Invalid loglevel: {0} given, {1} allowed. '
                'defaulting to DEBUG loglevel.'.format(
                    log_level, '/'.join(allowed_log_levels)
                )
            )
            log_level = 'debug'

        # set log level
        args.append(
            '--log.level={0}'.format(log_level)
        )

        # Expose Prometheus Adminstration API only if requested
        if config.get('web-enable-admin-api'):
            args.append('--web.enable-admin-api')

        # User specified Prometheus web page title
        if config.get('web-page-title'):
            # TODO: Validate and sanitize input
            args.append(
                '--web.page-title="{0}"'.format(
                    config['web-page-title']
                )
            )

        # Enable time series database compression
        if config.get('tsdb-wal-compression'):
            args.append('--storage.tsdb.wal-compression')

        # Set time series retention time
        if config.get('tsdb-retention-time'):
            args.append('--storage.tsdb.retention.time={}'.format(config['tsdb-retention-time']))

        # Set maximum number of connections to prometheus server
        if config.get('web-max-connections'):
            args.append('--web.max-connections={}'.format(config['web-max-connections']))

        # Set maximum number of pending alerts
        if config.get('alertmanager-notification-queue-capacity'):
            args.append('--alertmanager.notification-queue-capacity={}'.format(
                config['alertmanager-notification-queue-capacity']))

        # Set timeout for alerts
        if config.get('alertmanager-timeout'):
            args.append('--alertmanager.timeout={}'.format(config['alertmanager-timeout']))

        logger.debug("CLI args: {0}".format(' '.join(args)))

        return args

    def _is_valid_timespec(self, timeval):
        if not timeval:
            return False

        time, unit = timeval[:-1], timeval[-1]

        # TODO 'ms' - bug in original charm ?
        if unit not in ['y', 'w', 'd', 'h', 'm', 's']:
            logger.error('Invalid unit {} in time spec'.format(unit))
            return False

        try:
            int(time)
        except ValueError:
            logger.error('Can not convert time {} to integer'.format(time))
            return False

        return True

    def _are_valid_labels(self, json_data):
        if not json_data:
            return False

        try:
            labels = json.loads(json_data)
        except (ValueError, TypeError):
            logger.error('Can not parse external labels : {}'.format(json_data))
            return False

        if not isinstance(labels, dict):
            logger.error('Expected label dictionary but got : {}'.format(labels))
            return False

        for key, value in labels:
            if not isinstance(key, str) or not isinstance(value, str):
                logger.error('External label keys/values must be strings')
                return False

        return True

    def _external_labels(self):
        config = self.model.config
        labels = {}

        if config.get('external-labels') and self._are_valid_labels(
                config['external-labels']):
            labels = json.loads(config['external-labels'])

        return labels

    def _prometheus_global_config(self):
        config = self.model.config
        global_config = {}

        labels = self._external_labels()
        if labels:
            global_config['external_labels'] = labels

        if config.get('scrape-interval') and self._is_valid_timespec(
                config['scrape-interval']):
            global_config['scrape_interval'] = config['scrape-interval']

        if config.get('scrape-timeout') and self._is_valid_timespec(
                config['scrape-timeout']):
            global_config['scrape_timeout'] = config['scrape-timeout']

        if config.get('evaluation-interval') and self._is_valid_timespec(
                config['evaluation-interval']):
            global_config['evaluation_interval'] = config['evaluation-interval']

        return global_config

    def _alerting_config(self):
        alerting_config = ''

        if len(self.stored.alertmanagers) < 1:
            logger.debug('No alertmanagers available')
            return alerting_config

        if len(self.stored.alertmanagers) > 1:
            logger.warning('More than one altermanager found. Using first!')

        manager = list(self.stored.alertmanagers.keys())[0]
        alerting_config = self.stored.alertmanagers.get(manager, '')

        return alerting_config

    def _prometheus_config(self):
        config = self.model.config
        scrape_config = {'global': self._prometheus_global_config(),
                         'scrape_configs': [],
                         'alerting': self._alerting_config()}

        # By default only monitor prometheus server itself
        default_config = {
            'job_name': 'prometheus',
            'scrape_interval': '5s',
            'scrape_timeout': '5s',
            'metrics_path': '/metrics',
            'honor_timestamps': True,
            'scheme': 'http',
            'static_configs': [{
                'targets': [
                    'localhost:{}'.format(config['advertised-port'])
                ]
            }]
        }
        scrape_config['scrape_configs'].append(default_config)

        # If monitoring of k8s is requested gather all scraping configuration for k8s
        if config.get('monitor-k8s'):
            with open('config/prometheus-k8s.yml') as yaml_file:
                k8s_scrape_configs = yaml.safe_load(yaml_file).get('scrape_configs', [])
            for k8s_config in k8s_scrape_configs:
                scrape_config.append(k8s_config)

        logger.debug('Prometheus config : {}'.format(scrape_config))

        return yaml.dump(scrape_config)

    def _build_pod_spec(self):
        logger.debug('Building Pod Spec')
        config = self.model.config
        spec = {
            'containers': [{
                'name': self.app.name,
                'imageDetails': {
                    'imagePath': config['prometheus-image-path'],
                    'username': config.get('prometheus-image-username', ''),
                    'password': config.get('prometheus-image-password', '')
                },
                'args': self._cli_args(),
                'readinessProbe': {
                    'httpGet': {
                        'path': '/-/ready',
                        'port': config['advertised-port']
                    },
                    'initialDelaySeconds': 10,
                    'timeoutSeconds': 30
                },
                'livenessProbe': {
                    'httpGet': {
                        'path': '/-/healthy',
                        'port': config['advertised-port']
                    },
                    'initialDelaySeconds': 30,
                    'timeoutSeconds': 30
                },
                'ports': [{
                    'containerPort': config['advertised-port'],
                    'name': 'prometheus-http',
                    'protocol': 'TCP'
                }],
                'files': [{
                    'name': 'prometheus-config',
                    'mountPath': '/etc/prometheus',
                    'files': {
                        'prometheus.yml': self._prometheus_config()
                    }
                }]
            }]
        }

        return spec

    def _check_config(self):
        """Identify missing but required items in configuation

        :returns: list of missing configuration items (configuration keys)
        """
        logger.debug('Checking Config')
        config = self.model.config
        missing = []

        if not config.get('prometheus-image-path'):
            missing.append('prometheus-image-path')

        if config.get('prometheus-image-username') \
                and not config.get('prometheus-image-password'):
            missing.append('prometheus-image-password')

        if missing:
            self.unit.status = \
                BlockedStatus('Missing configuration: {}'.format(missing))

        return missing

    def configure_pod(self):
        logger.debug('Configuring Pod')
        missing_config = self._check_config()
        if missing_config:
            logger.error('Incomplete Configuration : {}. '
                         'Application will be blocked.'.format(missing_config))
            self.unit.status = \
                BlockedStatus('Missing configuration: {}'.format(missing_config))

        if not self.unit.is_leader():
            self.unit.status = ActiveStatus('Prometheus unit is ready')
            return

        self.unit.status = MaintenanceStatus('Setting pod spec.')
        pod_spec = self._build_pod_spec()

        self.model.pod.set_spec(pod_spec)
        self.app.status = ActiveStatus('Prometheus Application is ready')
        self.unit.status = ActiveStatus('Prometheus leader unit is ready')


if __name__ == "__main__":
    main(PrometheusCharm)
