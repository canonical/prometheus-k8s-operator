# Copyright 2020 Canonical Ltd.
# See LICENSE file for licensing details.

from typing import Callable
from unittest.mock import patch


def patch_network_get(private_address="10.1.157.116") -> Callable:
    def network_get(*args, **kwargs) -> dict:
        """Patch for the not-yet-implemented testing backend needed for `bind_address`.

        This patch decorator can be used for cases such as:
        self.model.get_binding(event.relation).network.bind_address
        """
        return {
            "bind-addresses": [
                {
                    "mac-address": "",
                    "interface-name": "",
                    "addresses": [{"hostname": "", "value": private_address, "cidr": ""}],
                }
            ],
            "egress-subnets": ["10.152.183.65/32"],
            "ingress-addresses": ["10.152.183.65"],
        }

    return patch("ops.testing._TestingModelBackend.network_get", network_get)


k8s_resource_multipatch = patch.multiple(
    "charm.KubernetesComputeResourcesPatch",
    _namespace="test-namespace",
    _patch=lambda *a, **kw: True,
    is_ready=lambda *a, **kw: True,
)


class ExecMock:
    def __init__(self, args):
        pass

    def wait_output(self):
        return ("stdout", "")


prom_multipatch = patch.multiple(
    "charm.PrometheusCharm",
    _promtail_check_config=lambda *_: ("stdout", ""),
    _prometheus_version="0.1.0",
)
