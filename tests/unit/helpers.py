# Copyright 2020 Canonical Ltd.
# See LICENSE file for licensing details.

import os
import tempfile
from typing import Tuple


class Sandbox:
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
