# Copyright 2020 Canonical Ltd.
# See LICENSE file for licensing details.

import os
import tempfile
from typing import Callable, Tuple
from unittest.mock import patch


class TempFolderSandbox:
    """A helper class for creating files in a temporary folder (sandbox)."""

    def __init__(self):
        self.root = tempfile.mkdtemp()

    def put_file(self, rel_path: str, contents: str):
        """Write string to file.

        Args:
            rel_path: path to file, relative to the sandbox root.
            contents: the data to write to file.
        """
        file_path = os.path.join(self.root, rel_path)
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        with open(file_path, "wt") as f:
            f.write(contents)

    def put_files(self, *args: Tuple[str, str]):
        """Write strings to files. A vectorized version of `put_file`.

        Args:
            args: a tuple of path and contents.
        """
        for rel_path, contents in args:
            self.put_file(rel_path, contents)

    def remove(self, rel_path: str):
        """Delete file from disk.

        Args:
            rel_path: path to file, relative to the sandbox root.
        """
        file_path = os.path.join(self.root, rel_path)
        os.remove(file_path)

    def rmdir(self, rel_path):
        """Delete an empty dir.

        Args:
            rel_path: path to dir, relative to the sandbox root.
        """
        dir_path = os.path.join(self.root, rel_path)
        os.rmdir(dir_path)


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
    _is_patched=lambda *a, **kw: True,
    is_ready=lambda *a, **kw: True,
)
