#!/usr/bin/env python3
# Copyright 2020 Balbir Thomas
# See LICENSE file for licensing details.

import logging
import yaml

from ops.charm import CharmBase
from ops.main import main
from ops.model import ActiveStatus, MaintenanceStatus, BlockedStatus

logger = logging.getLogger(__name__)


class PrometheusCharm(CharmBase):

    def __init__(self, *args):
        logger.debug('Initializing Charm')
        super().__init__(*args)
        self.framework.observe(self.on.config_changed, self._on_config_changed)
        self.framework.observe(self.on.stop, self._on_stop)

    def _on_config_changed(self, _):
        self.configure_pod()

    def _on_stop(self, _):
        self.unit.status = MaintenanceStatus('Pod is terminating.')

    def _set_prometheus_config(self, spec):
        config = self.model.config
        scrape_config = {'global': {},
                         'scrape_configs': [],
                         'alerting': ''}
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
        spec['containers'][0]['files'][0]['files']['prometheus.yml'] = yaml.dump(scrape_config)

        return spec

    def _build_pod_spec(self):
        logger.debug('Building Pod Spec')
        config = self.model.config
        spec = {
            'containers': [{
                'name': self.app.name,
                'imageDetails': {
                    'imagePath': config['prometheus-image-path'],
                    'username': config['prometheus-image-username'],
                    'password': config['prometheus-image-password']
                },
                'args': ['--config.file=/etc/prometheus/prometheus.yml',
                         '--storage.tsdb.path=/prometheus',
                         '--web.enable-lifecycle',
                         '--web.console.templates=/usr/share/prometheus/consoles',
                         '--web.console.libraries=/usr/share/prometheus/console_libraries'],
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
                        'prometheus.yml': ''
                    }
                }]
            }]
        }

        spec = self._set_prometheus_config(spec)

        return spec

    def _check_config(self):
        """Identify missing but required items in configuation

        :returns: list of missing configuration items (configuration keys)
        """
        logger.debug('Checking Config')
        config = self.model.config
        missing = []

        if not config['prometheus-image-path']:
            missing.append('prometheus-image-path')

        if config['prometheus-image-username'] \
                and not config['prometheus-image-password']:
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
