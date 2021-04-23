#!/usr/bin/env python3
# Copyright 2020 Balbir Thomas
# See LICENSE file for licensing details.

import hashlib
import logging
import yaml
import json

from ops.charm import CharmBase
from ops.framework import StoredState
from ops.main import main
from ops.model import ActiveStatus, MaintenanceStatus, BlockedStatus
from prometheus_provider import MonitoringProvider
from prometheus_server import Prometheus

PROMETHEUS_CONFIG = "/etc/prometheus/prometheus.yml"
logger = logging.getLogger(__name__)


class PrometheusCharm(CharmBase):
    """A Juju Charm for Prometheus
    """
    _stored = StoredState()

    def __init__(self, *args):
        logger.debug('Initializing Charm')

        super().__init__(*args)

        self._stored.set_default(alertmanagers=[])
        self._stored.set_default(alertmanager_port='9093')
        self._stored.set_default(provider_ready=False)
        self._stored.set_default(prometheus_config_hash=None)

        self.framework.observe(self.on.prometheus_pebble_ready, self._on_config_changed)
        self.framework.observe(self.on.config_changed, self._on_config_changed)
        self.framework.observe(self.on.update_status, self._on_update_status)
        self.framework.observe(self.on.stop, self._on_stop)
        self.framework.observe(self.on['alertmanager'].relation_changed,
                               self._on_alertmanager_changed)
        self.framework.observe(self.on['alertmanager'].relation_broken,
                               self._on_alertmanager_broken)

        self.framework.observe(self.on['grafana-source'].relation_changed,
                               self._on_grafana_changed)

        if self._stored.provider_ready:
            self.prometheus_provider = MonitoringProvider(self, 'monitoring', self.provides)
            self.framework.observe(self.prometheus_provider.on.targets_changed,
                                   self._on_config_changed)

    def _on_config_changed(self, event):
        """Set a new Juju pod specification
        """
        logger.info("Handling config changed")
        container = self.unit.get_container("prometheus")

        missing_config = self._check_config()
        if missing_config:
            logger.error('Incomplete Configuration : {}. '
                         'Application will be blocked.'.format(missing_config))
            self.unit.status = \
                BlockedStatus('Missing configuration: {}'.format(missing_config))
            return

        prometheus_config = self._prometheus_config()
        config_hash = str(hashlib.md5(str(prometheus_config).encode('utf-8')))
        if not self._stored.prometheus_config_hash == config_hash:
            self._stored.prometheus_config_hash = config_hash
            container.push(PROMETHEUS_CONFIG, prometheus_config)
            logger.info("Pushed new configuation")

        layer = self._prometheus_layer()
        plan = container.get_plan()
        if plan.services != layer["services"]:
            container.add_layer("prometheus", layer, combine=True)

            if container.get_service("prometheus").is_running():
                container.stop("prometheus")

            container.start("prometheus")
            logger.info("Restarted prometheus container")

        self.app.status = ActiveStatus()
        self.unit.status = ActiveStatus()

    def _on_update_status(self, event):
        provided = self.provides
        if provided:
            logger.debug("Prometheus provider is available")
            logger.debug("Providing : {}".format(provided))
            if not self._stored.provider_ready:
                self._stored.provider_ready = True

    def _on_stop(self, _):
        """Mark unit is inactive
        """
        self.unit.status = MaintenanceStatus('Pod is terminating.')

    def _on_grafana_changed(self, event):
        """Provide Grafana with data source information
        """
        event.relation.data[self.unit]['port'] = str(self.model.config['port'])
        event.relation.data[self.unit]['source-type'] = 'prometheus'

    def _on_alertmanager_changed(self, event):
        """Set an alertmanager configuation
        """
        if not self.unit.is_leader():
            return

        addrs = json.loads(event.relation.data[event.app].get('addrs', '[]'))
        port = event.relation.data[event.app]['port']

        self._stored.alertmanager_port = port
        self._stored.alertmanagers = addrs

        self._on_config_changed(event)

    def _on_alertmanager_broken(self, event):
        """Remove all alertmanager configuration
        """
        if not self.unit.is_leader():
            return
        self._stored.alertmanagers.clear()
        self._on_config_changed(event)

    def _command(self):
        """Construct command to launch Prometheus
        """
        command = ["/bin/prometheus"]
        command.extend(self._cli_args())

        return " ".join(command)

    def _cli_args(self):
        """Construct command line arguments for Prometheus
        """
        config = self.model.config
        args = [
            '--config.file=/etc/prometheus/prometheus.yml',
            '--storage.tsdb.path=/var/lib/prometheus',
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

        # Enable time series database compression
        if config.get('tsdb-wal-compression'):
            args.append('--storage.tsdb.wal-compression')

        # Set time series retention time
        if config.get('tsdb-retention-time') and self._is_valid_timespec(
                config['tsdb-retention-time']):
            args.append('--storage.tsdb.retention.time={}'.format(config['tsdb-retention-time']))

        return args

    def _is_valid_timespec(self, timeval):
        """Is a time interval unit and value valid
        """
        if not timeval:
            return False

        time, unit = timeval[:-1], timeval[-1]

        if unit not in ['y', 'w', 'd', 'h', 'm', 's']:
            logger.error('Invalid unit {} in time spec'.format(unit))
            return False

        try:
            int(time)
        except ValueError:
            logger.error('Can not convert time {} to integer'.format(time))
            return False

        if not int(time) > 0:
            logger.error('Expected positive time spec but got {}'.format(time))
            return False

        return True

    def _are_valid_labels(self, json_data):
        """Are Prometheus external labels valid
        """
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

        for key, value in labels.items():
            if not isinstance(key, str) or not isinstance(value, str):
                logger.error('External label keys/values must be strings')
                return False

        return True

    def _external_labels(self):
        """Extract external labels for Prometheus from configuration
        """
        config = self.model.config
        labels = {}

        if config.get('external-labels') and self._are_valid_labels(
                config['external-labels']):
            labels = json.loads(config['external-labels'])

        return labels

    def _prometheus_global_config(self):
        """Construct Prometheus global configuration
        """
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
        """Construct Prometheus altering configuation
        """
        alerting_config = ''

        if len(self._stored.alertmanagers) < 1:
            logger.debug('No alertmanagers available')
            return alerting_config

        targets = []
        for manager in self._stored.alertmanagers:
            port = self._stored.alertmanager_port
            targets.append("{}:{}".format(manager, port))

        manager_config = {'static_configs': [{'targets': targets}]}
        alerting_config = {'alertmanagers': [manager_config]}

        return alerting_config

    def _prometheus_config(self):
        """Construct Prometheus configuration
        """
        config = self.model.config

        scrape_config = {'global': self._prometheus_global_config(),
                         'scrape_configs': []}

        alerting_config = self._alerting_config()
        if alerting_config:
            scrape_config['alerting'] = alerting_config

        scrape_config_string = config.get('scrape-config')
        if scrape_config_string:
            scrape_config_yaml = yaml.safe_load(scrape_config_string)
            for scrape_job in scrape_config_yaml['scrape_configs']:
                scrape_config['scrape_configs'].append(scrape_job)

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
                    'localhost:{}'.format(config['port'])
                ]
            }]
        }
        scrape_config['scrape_configs'].append(default_config)
        if self._stored.provider_ready:
            scrape_jobs = self.prometheus_provider.jobs()
            for job in scrape_jobs:
                scrape_config['scrape_configs'].append(job)

        logger.debug('Prometheus config : {}'.format(scrape_config))

        return yaml.dump(scrape_config)

    def _prometheus_layer(self):
        """Construct the pebble layer
        """
        logger.debug('Building pebble layer')
        layer = {
            "summary": "Prometheus layer",
            "description": "Pebble layer configuration for Prometheus",
            "services": {
                "prometheus": {
                    "override": "replace",
                    "summary": "prometheus daemon",
                    "command": self._command(),
                    "startup": "enabled",
                }
            },
        }

        return layer

    def _check_config(self):
        """Identify missing but required items in configuation

        :returns: list of missing configuration items (configuration keys)
        """
        logger.debug('Checking Config')
        config = self.model.config
        missing = []

        if config.get('prometheus-image-username') \
                and not config.get('prometheus-image-password'):
            missing.append('prometheus-image-password')

        return missing

    @property
    def provides(self):
        prometheus = Prometheus("localhost", str(self.model.config['port']))
        info = prometheus.build_info()
        if info:
            provided = {
                'provides': {'prometheus': info['version']}
            }
        else:
            provided = {}
        return provided


if __name__ == "__main__":
    main(PrometheusCharm)
