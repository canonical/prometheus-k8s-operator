import json
import logging
from ops.charm import CharmEvents
from ops.framework import StoredState, EventSource, EventBase
from ops.relation import ProviderBase
logger = logging.getLogger(__name__)


class TargetsChanged(EventBase):
    def __init__(self, handle, data=None):
        super().__init__(handle)
        self.data = data

    def snapshot(self):
        return {"data": self.data}

    def restore(self, snapshot):
        self.data = snapshot["data"]


class MonitoringEvents(CharmEvents):
    targets_changed = EventSource(TargetsChanged)


class MonitoringProvider(ProviderBase):
    on = MonitoringEvents()
    _stored = StoredState()

    def __init__(self, charm, name, service, version=None):
        super().__init__(charm, name, service, version)
        self._charm = charm
        self._stored.set_default(jobs={})
        events = self._charm.on[name]
        self.framework.observe(events.relation_changed,
                               self._on_scrape_target_relation_changed)
        self.framework.observe(events.relation_broken,
                               self._on_scrape_target_relation_broken)

    def _on_scrape_target_relation_changed(self, event):
        if not self._charm.unit.is_leader():
            return

        rel_id = event.relation.id
        data = event.relation.data[event.app]

        targets = json.loads(data.get('targets', '[]'))
        if not targets:
            return

        job_name = data.get('job_name', "")
        unique_name = "relation_{}".format(rel_id)
        if job_name:
            job_name += "_{}".format(unique_name)
        else:
            job_name = unique_name

        job_config = {
            'job_name': job_name,
            'static_configs': [{
                'targets': targets
            }]
        }

        self._stored.jobs['rel_id'] = json.dumps(job_config)
        logger.debug("New job config on relation change : %s", job_config)
        self.on.targets_changed.emit()

    def _on_scrape_target_relation_broken(self, event):
        if not self._charm.unit.is_leader():
            return

        rel_id = event.relation.id
        try:
            del self._stored.jobs[rel_id]
            self.on.targets_changed.emit()
        except KeyError:
            pass

    def jobs(self):
        scrape_jobs = []
        for job in self._stored.jobs.values():
            scrape_jobs.append(json.loads(job))

        return scrape_jobs
