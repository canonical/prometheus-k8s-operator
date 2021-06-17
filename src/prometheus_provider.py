import json
import logging
from ops.charm import CharmEvents
from ops.framework import StoredState, EventSource, EventBase
from ops.relation import ProviderBase

logger = logging.getLogger(__name__)


class TargetsChanged(EventBase):
    """Event emitted when Prometheus scrape targets change."""

    def __init__(self, handle, data=None):
        super().__init__(handle)
        self.data = data

    def snapshot(self):
        """Save scrape target information."""
        return {"data": self.data}

    def restore(self, snapshot):
        """Restore scrape target information."""
        self.data = snapshot["data"]


class MonitoringEvents(CharmEvents):
    """Event descriptor for events raised by :class:`MonitoringProvider`."""

    targets_changed = EventSource(TargetsChanged)


class MonitoringProvider(ProviderBase):
    on = MonitoringEvents()
    _stored = StoredState()

    def __init__(self, charm, name, service, version=None):
        """A Prometheus based Monitoring service provider.

        Args:
            charm: a :class:`CharmBase` instance that manages this
                instance of the Prometheus service.
            name: string name of the relation that is provides the
                Prometheus monitoring service.
            service: string name of service provided. This is used by
                :class:`PrometheusConsumer` to validate this service as
                acceptable. Hence the string name must match one of the
                acceptable service names in the :class:`PrometheusConsumer`s
                `consumes` argument. Typically this string is just "prometheus".
            version: a string providing the semantic version of the Prometheus
                application being provided.
        """
        super().__init__(charm, name, service, version)
        self._charm = charm
        self._stored.set_default(jobs={})
        events = self._charm.on[name]
        self.framework.observe(
            events.relation_changed, self._on_scrape_target_relation_changed
        )
        self.framework.observe(
            events.relation_broken, self._on_scrape_target_relation_broken
        )

    def _on_scrape_target_relation_changed(self, event):
        """Handle changes in related consumers.

        Anytime there are changes in relations between Prometheus
        provider and consumer charms the scrape job config is updated
        and the Prometheus charm is informed, through a
        :class:`TargetsChanged` event. The Prometheus charm can then
        choose to update its scrape configuration.
        """
        if not self._charm.unit.is_leader():
            return

        rel_id = event.relation.id
        data = event.relation.data[event.app]

        targets = json.loads(data.get("targets", "[]"))
        if not targets:
            return

        job_name = data.get("job_name", "")
        unique_name = "juju_{}_{}_{}".format(
            self._charm.model.name,
            self._charm.app.name,
            rel_id
        )
        if job_name:
            job_name += "_{}".format(unique_name)
        else:
            job_name = unique_name

        job_config = {"job_name": job_name, "static_configs": [{"targets": targets}]}

        self._stored.jobs["rel_id"] = json.dumps(job_config)
        logger.debug("New job config on relation change : %s", job_config)
        self.on.targets_changed.emit()

    def _on_scrape_target_relation_broken(self, event):
        """Update job config when consumers depart.

        When a Prometheus consumer departs the scrape configuration
        for that consumer is remove from the list of scrape jobs and
        the Prometheus is informed through a :class:`TargetsChanged`
        event.
        """
        if not self._charm.unit.is_leader():
            return

        rel_id = event.relation.id
        try:
            del self._stored.jobs[rel_id]
            self.on.targets_changed.emit()
        except KeyError:
            pass

    def jobs(self):
        """Fetch the list of scrape jobs.

        Returns:

            A list consisting of all the static scrape configurations
            for each related :class:`PrometheusConsumer` that has specified
            its scrape targets.
        """
        scrape_jobs = []
        for job in self._stored.jobs.values():
            scrape_jobs.append(json.loads(job))

        return scrape_jobs
