# Copyright 2020 Canonical Ltd.
# See LICENSE file for licensing details.

import os
import tempfile
from typing import Tuple


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
