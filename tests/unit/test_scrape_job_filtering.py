# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.

import dataclasses
import json

import yaml
from ops.model import ActiveStatus, BlockedStatus
from scenario import Relation, State

from charm import to_status


# To test that invalid scrape jobs are filtered out and the charm goes into blocked
# status, we create two `metrics-endpoint` relations, one with a valid scrape job and
# one with an invalid scrape job. The invalid scrape job has a `sample_limit` set to
# a dict instead of a number, which cos-tool rejects.
def _scrape_jobs(job_name: str, valid: bool) -> str:
    job = {
        "job_name": job_name,
        "metrics_path": "/metrics",
        "static_configs": [{"targets": ["192.0.2.1:9090"]}],
    }
    if not valid:
        # `sample_limit` must be a number; a dict makes the scrape job invalid.
        job["sample_limit"] = {"not_a_key": "not_a_value"}
    return json.dumps([job])


def _metadata(app_name: str) -> str:
    return json.dumps(
        {
            "model": "test",
            "model_uuid": "20ce8299-3634-4bef-8bd8-5ace6c8816b4",
            "application": app_name,
            "charm_name": f"{app_name}-charm",
        }
    )


VALID_SCRAPE_JOB_RELATION = Relation(
    "metrics-endpoint",
    remote_app_name="scrape-job-valid",
    remote_app_data={
        "scrape_jobs": _scrape_jobs("valid-job", valid=True),
        "scrape_metadata": _metadata("scrape-job-valid"),
    },
)

INVALID_SCRAPE_JOB_RELATION = Relation(
    "metrics-endpoint",
    remote_app_name="scrape-job-invalid",
    remote_app_data={
        "scrape_jobs": _scrape_jobs("invalid-job", valid=False),
        "scrape_metadata": _metadata("scrape-job-invalid"),
    },
)


def _scrape_job_names(context, state_out):
    """Read the scrape job names written to the prometheus config on disk."""
    fs = state_out.get_container("prometheus").get_filesystem(context)
    prometheus_config = fs.joinpath("etc", "prometheus", "prometheus.yml")
    if not prometheus_config.exists():
        return set()

    config = yaml.safe_load(prometheus_config.read_text())
    return {job.get("job_name") for job in config.get("scrape_configs", [])}


def _scrape_jobs_status(state_out):
    """Return only the scrape-jobs status, ignoring unrelated unit statuses."""
    charm_stored_state = next(
        stored_state
        for stored_state in state_out.stored_states
        if stored_state.owner_path == "PrometheusCharm"
    )
    return to_status(charm_stored_state.content["status"]["scrape_jobs"])


def test_valid_scrape_job_relation_remains_active(context, prometheus_container):
    # GIVEN a scrape relation with a valid scrape job
    state_in = State(
        leader=True,
        relations=[VALID_SCRAPE_JOB_RELATION],
        containers=[prometheus_container],
    )

    # WHEN the relation changed event is processed
    state_out = context.run(context.on.relation_changed(VALID_SCRAPE_JOB_RELATION), state_in)

    # THEN the valid job is written and the scrape-jobs status remains active
    assert any("valid-job" in name for name in _scrape_job_names(context, state_out))
    assert isinstance(_scrape_jobs_status(state_out), ActiveStatus)


def test_invalid_scrape_job_relation_blocks(context, prometheus_container):
    # GIVEN a scrape relation with an invalid scrape job
    state_in = State(
        leader=True,
        relations=[INVALID_SCRAPE_JOB_RELATION],
        containers=[prometheus_container],
    )

    # WHEN the relation changed event is processed
    state_out = context.run(context.on.relation_changed(INVALID_SCRAPE_JOB_RELATION), state_in)

    # THEN the invalid job is filtered out and the scrape-jobs status is blocked
    assert not any("invalid-job" in name for name in _scrape_job_names(context, state_out))
    assert isinstance(_scrape_jobs_status(state_out), BlockedStatus)


def test_invalid_scrape_job_relation_broken_recovers_to_active(
    context, prometheus_container
):
    # GIVEN an invalid scrape relation has already blocked the charm
    state_in = State(
        leader=True,
        relations=[INVALID_SCRAPE_JOB_RELATION],
        containers=[prometheus_container],
    )

    blocked_state = context.run(
        context.on.relation_changed(INVALID_SCRAPE_JOB_RELATION), state_in
    )

    assert isinstance(_scrape_jobs_status(blocked_state), BlockedStatus)

    # WHEN the invalid scrape relation is removed
    invalid_relation_out = blocked_state.get_relation(INVALID_SCRAPE_JOB_RELATION.id)
    state_out = context.run(
        context.on.relation_broken(invalid_relation_out),
        blocked_state,
    )

    # THEN the charm status must be active again
    assert isinstance(_scrape_jobs_status(state_out), ActiveStatus)


def test_invalid_scrape_job_relation_becoming_valid_recovers_to_active(
    context, prometheus_container
):
    # GIVEN a scrape relation with invalid jobs has already blocked the charm
    state_in = State(
        leader=True,
        relations=[INVALID_SCRAPE_JOB_RELATION],
        containers=[prometheus_container],
    )

    blocked_state = context.run(
        context.on.relation_changed(INVALID_SCRAPE_JOB_RELATION), state_in
    )

    assert isinstance(_scrape_jobs_status(blocked_state), BlockedStatus)

    # WHEN the same scrape relation updates its jobs to become valid
    relation_after_invalid = blocked_state.get_relation(INVALID_SCRAPE_JOB_RELATION.id)
    now_valid_relation = dataclasses.replace(
        relation_after_invalid,
        remote_app_data={
            **relation_after_invalid.remote_app_data,
            "scrape_jobs": VALID_SCRAPE_JOB_RELATION.remote_app_data["scrape_jobs"],
        },
    )

    recovered_state = context.run(
        context.on.relation_changed(now_valid_relation),
        dataclasses.replace(blocked_state, relations=[now_valid_relation]),
    )

    # THEN the previous invalid status is cleared and valid jobs are written
    assert any("valid-job" in name for name in _scrape_job_names(context, recovered_state))
    assert isinstance(_scrape_jobs_status(recovered_state), ActiveStatus)
