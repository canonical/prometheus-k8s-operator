# Copyright 2025 Canonical Ltd.
# See LICENSE file for licensing details.


from unittest.mock import patch

import pytest
from ops.testing import ActiveStatus, BlockedStatus, State, Storage


@pytest.mark.parametrize(
    "disk_space,expected_status",
    [
        (1024**4, ActiveStatus()),
        (1024**3, ActiveStatus()),
        (1024**3 - 1, BlockedStatus("<1 GiB disk space remaining")),
        (0, BlockedStatus("<1 GiB disk space remaining")),
        (-1, BlockedStatus("<1 GiB disk space remaining")),
    ],
)
def test_datasource_send(context, prometheus_container, disk_space, expected_status):
    state = State(
        containers=[prometheus_container], storages=[Storage(name="database")], leader=True
    )
    with patch("shutil.disk_usage") as mock_disk_usage, patch(
        "charm.PrometheusCharm._get_pvc_capacity"
    ) as get_pvc_mock:
        mock_disk_usage.return_value.free = disk_space
        get_pvc_mock.return_value = "1Gi"

        state_out = context.run(context.on.update_status(), state)
        assert state_out.unit_status == expected_status
