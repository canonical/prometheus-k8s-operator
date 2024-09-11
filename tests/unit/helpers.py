# Copyright 2020 Canonical Ltd.
# See LICENSE file for licensing details.
import logging
from functools import wraps
from pathlib import Path
from typing import Callable
from unittest.mock import patch

import requests
from charms.prometheus_k8s.v0.prometheus_scrape import CosTool as _CosTool_scrape
from charms.prometheus_k8s.v1.prometheus_remote_write import (
    CosTool as _CosTool_remote_write,
)

PROJECT_DIR = Path(__file__).resolve().parent.parent.parent
UNITTEST_DIR = Path(__file__).resolve().parent
COS_TOOL_URL = "https://github.com/canonical/cos-tool/releases/latest/download/cos-tool-amd64"


def patch_cos_tool_path(func) -> Callable:
    """Patch cos tool path.

    Downloads from GitHub, if it does not exist locally.
    Updates CosTool class internal `_path`, otherwise it will always look in CWD
    (execution directory).

    Returns:
        Patch object for CosTool class in both prometheus_scrape and prometheus_remote_write
    """
    cos_path = PROJECT_DIR / "cos-tool-amd64"
    if not cos_path.exists():
        logging.debug("cos-tool was not found, download it")
        with requests.get(COS_TOOL_URL, stream=True) as r:
            r.raise_for_status()
            with open(cos_path, "wb") as f:
                for chunk in r.iter_content(chunk_size=1024):
                    f.write(chunk)

    cos_path.chmod(0o777)

    path1 = patch.object(
        target=_CosTool_remote_write,
        attribute="_path",
        new=str(cos_path),
    )
    path2 = patch.object(
        target=_CosTool_scrape,
        attribute="_path",
        new=str(cos_path),
    )

    @wraps(func)
    def wrapper_decorator(*args, **kwargs):
        with path1, path2:
            value = func(*args, **kwargs)
        return value

    return wrapper_decorator


def cli_arg(plan, cli_opt):
    plan_dict = plan.to_dict()
    args = plan_dict["services"]["prometheus"]["command"].split()
    for arg in args:
        opt_list = arg.split("=")
        if len(opt_list) == 2 and opt_list[0] == cli_opt:
            return opt_list[1]
        if len(opt_list) == 1 and opt_list[0] == cli_opt:
            return opt_list[0]
    return None


k8s_resource_multipatch = patch.multiple(
    "charm.KubernetesComputeResourcesPatch",
    _namespace="test-namespace",
    _patch=lambda *a, **kw: True,
    is_ready=lambda *a, **kw: True,
)


prom_multipatch = patch.multiple(
    "charm.PrometheusCharm",
    _promtool_check_config=lambda *_: ("stdout", ""),
    _prometheus_version="0.1.0",
)
