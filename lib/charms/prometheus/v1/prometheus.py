import json
import logging
from ops.framework import StoredState
from ops.relation import ConsumerBase

LIBID = "1234"
LIBAPI = 1
LIBPATCH = 0
logger = logging.getLogger(__name__)


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
        self.framework.observe(events.relation_joined,
                               self._set_targets)

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

        target = address if port == 80 else address + ":" + str(port)
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
            list(self._stored.targets[rel_id]))

    def _update_targets(self, targets, rel_id):
        """Update the Prometheus scrape targets."""
        self._stored.targets[rel_id] = targets
        rel = self.framework.model.get_relation(self._relation_name, rel_id)

        logger.debug("Updating scrape targets to : %s", targets)
        rel.data[self._charm.app]["targets"] = json.dumps(list(targets))
