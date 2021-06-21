import json
import logging
from ops.charm import CharmEvents
from ops.framework import StoredState, EventSource, EventBase
from ops.relation import ProviderBase, ConsumerBase

LIBID = "1234"
LIBAPI = 1
LIBPATCH = 0
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
    """Event descriptor for events raised by :class:`PrometheusProvider`."""

    targets_changed = EventSource(TargetsChanged)


class PrometheusProvider(ProviderBase):
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
            self._charm.model.name, self._charm.app.name, rel_id
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


class PrometheusConsumer(ConsumerBase):
    _stored = StoredState()

    def __init__(self, charm, name, consumes, multi=False):
        """Construct a Prometheus charm client.

        The :class:`PrometheusConsumer` object provides an interface
        to Prometheus. This interface supports providing additional
        scrape targets to the Prometheus monitoring service. For
        example suppose a charm's units exposes Prometheus metrics on
        port 8000. This charm may then have its metrics aggregated by
        a related Prometheus charm by instantiating a
        :class:`PrometheusConsumer` object and adding its units as
        scrape endpoints as follows

            self.prometheus = PrometheusConsumer(self, "monitoring", {"prometheus": ">=2.0"})
            self.prometheus.add_endpoint(<ip-adderss>, port=8000)

        Args:

            charm: a :class:`CharmBase` object that manages this
                :class:`PrometheusConsumer` object. Typically this is
                `self` in the instantiating class.
            name: a string name of the relation between `charm` and
                the Prometheus charmed service.
            consumes: a dictionary of acceptable monitoring service
                providers. The keys of the dictionary are string names
                of monitoring service providers. For prometheus, this
                is typically "prometheus". The values of the
                dictionary are corresponding minimal acceptable
                semantic version specfications for the monitoring
                service.
            multi: an optional (default False) flag to indicate if
                this object must support interaction with multiple
                Prometheus monitoring service providers.

        """
        super().__init__(charm, name, consumes, multi)
        self._charm = charm
        self._relation_name = name
        self._stored.set_default(targets={})
        events = self._charm.on[self._relation_name]
        self.framework.observe(events.relation_joined, self._set_targets)

    def add_endpoint(self, address, port=80, rel_id=None):
        """Add an additional scrape to the Prometheus monitroing service.

        Args:
            address: a string host address (usually IP) of the endpoint that
                that must be monitored by Prometheus.
            port: an optional (default 80) integer providing the port
                on which the scrapped endpoint exposes its Prometheus
                metrics.
            rel_id: an optional integer providing the relation ID for
                the related Prometheus monitoring service
                provider. This is only necessary if the
                :class:`PrometheusConsumer` has been instantiated in
                `multi` mode.
        """
        if rel_id is None:
            rel_id = self.relation_id

        targets = self._stored.targets.get(rel_id, [])
        if address in targets:
            return

        target = address + ":" + str(port)
        targets.append(target)
        self._update_targets(targets, rel_id)

    def remove_endpoint(self, address, port=80, rel_id=None):
        """Remove an endpoint from the list of Prometheus scrape targets.
        Args:
            address: a string host address (usually IP) of the endpoint that
                that must be excluded from being monitored by Prometheus.
            port: an optional (default 80) integer providing the port
                on which the scrapped endpoint exposes its Prometheus
                metrics.
            rel_id: an optional integer providing the relation ID for
                the related Prometheus monitoring service
                provider. This is only necessary if the
                :class:`PrometheusConsumer` has been instantiated in
                `multi` mode.
        """
        if rel_id is None:
            rel_id = self.relation_id

        targets = self._stored.targets.get(rel_id, [])
        target = address + ":" + str(port)
        if target not in targets:
            return

        targets.remove(target)
        self._update_targets(targets, rel_id)

    def _set_targets(self, event):
        """Set the Prometheus scrape targets."""
        rel_id = event.relation.id
        if not self._stored.targets.get(rel_id, []):
            return

        logger.debug("Setting scrape targets : %s", self._stored.targets[rel_id])
        event.relation.data[self._charm.app]["targets"] = json.dumps(
            list(self._stored.targets[rel_id])
        )

    def _update_targets(self, targets, rel_id):
        """Update the Prometheus scrape targets."""
        self._stored.targets[rel_id] = targets
        rel = self.framework.model.get_relation(self._relation_name, rel_id)

        logger.debug("Updating scrape targets to : %s", targets)
        rel.data[self._charm.app]["targets"] = json.dumps(list(targets))
