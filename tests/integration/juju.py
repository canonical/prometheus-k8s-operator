#!/usr/bin/env python3
# Copyright 2024 Jon Seager (@jnsgruk)
# See LICENSE file for licensing details.


import json
import subprocess
import time
from typing import Dict, List, Optional


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
        alias: Optional[str] = None,
        channel: Optional[str] = None,
        config: Dict[str, str] = None,
        resources: Dict[str, str] = None,
        trust: bool = False,
        num_units: int = 1,
        base: str = None,
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

        if base:
            args = [*args, "--base", base]

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
    def config(cls, app: str, options: List[str]):
        args = ["config", app, *options]
        return cls.cli(*args)

    @classmethod
    def add_units(cls, app: str, units: int = 1):
        args = ["add-unit", app, "--num-units", units]
        return cls.cli(*args)

    @classmethod
    def remove_units(cls, app: str, units: int = 1):
        args = ["remove-unit", app, "--num-units", units]
        return cls.cli(*args)


    @classmethod
    def refresh(cls, app:str, path: str="", resources:  Dict[str, str] = {}, channel: str=""):
        args = ["refresh", app]
        if path:
            args = [*args, "--path", path]
        if resources:
            for k, v in resources.items():
                args = [*args, "--resource", f"{k}={v}"]
        if channel:
            args = [*args, "--channel", channel]
        return cls.cli(*args)

    @classmethod
    def wait_for_idle(cls, applications: List[str], timeout: int):
        # TODO: accomodate for the case when units are being removed/added(i.e: wait_for_exact_units)
        start = time.time()
        while time.time() - start < timeout:
            try:
                results = []
                for a in applications:
                    results.extend(cls._unit_statuses(a))
                if set(results) != {"active/idle"}:
                    raise Exception
                break
            except Exception:
                time.sleep(1)

    @classmethod
    def cli(cls, *args):
        proc = subprocess.run(
            ["/snap/bin/juju", "--model", cls.model_name, *args],
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

