#!/usr/bin/env python3
# Copyright 2024 Jon Seager (@jnsgruk)
# See LICENSE file for licensing details.


import json
import subprocess
import time
from typing import Dict, List


class Juju:
    @classmethod
    def model_name(cls):
        return cls.status()["model"]["name"]

    @classmethod
    def status(cls):
        args = ["status", "--format", "json"]
        result = cls.cli(*args)
        return json.loads(result.stdout)

    @classmethod
    def deploy(
        cls,
        charm: str,
        *,
        alias: str | None = None,
        channel: str | None = None,
        config: Dict[str, str] = {},
        resources: Dict[str, str] = {},
        trust: bool = False,
    ):
        args = ["deploy", charm]

        if alias:
            args = [*args, alias]

        if channel:
            args = [*args, "--channel", channel]

        if config:
            for k, v in config.items():
                args = [*args, "--config", f"{k}={v}"]

        if resources:
            for k, v in resources.items():
                args = [*args, "--resource", f"{k}={v}"]

        if trust:
            args = [*args, "--trust"]

        return cls.cli(*args)

    @classmethod
    def integrate(cls, requirer: str, provider: str):
        args = ["integrate", requirer, provider]
        return cls.cli(*args)

    @classmethod
    def run(cls, unit: str, action: str):
        args = ["run", "--format", "json", unit, action]
        act = cls.cli(*args)
        result = json.loads(act.stdout)
        return result[unit]["results"]

    @classmethod
    def wait_for_idle(cls, applications: List[str], timeout: int):
        start = time.time()
        while time.time() - start < timeout:
            try:
                results = []
                for a in applications:
                    results.extend(cls._unit_statuses(a))
                if set(results) != {"active/idle"}:
                    raise Exception
                else:
                    break
            except Exception:
                time.sleep(1)

    @classmethod
    def cli(cls, *args):
        proc = subprocess.run(
            ["/snap/bin/juju", *args],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env={"NO_COLOR": "true"},
        )
        return proc

    @classmethod
    def _unit_statuses(cls, application: str):
        units = cls.status()["applications"][application]["units"]
        return [
            f"{units[u]['workload-status']['current']}/{units[u]['juju-status']['current']}"
            for u in units
        ]
