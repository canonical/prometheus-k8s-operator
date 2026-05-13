"""Alerts editor UI — Milestone 2 read-only rule list.

Parses every ``juju_*.rules`` file on the shared ``/etc/prometheus/rules`` volume
and renders the flat list of alert rules. No editing yet — that lands in M3.

See specs/plans/0001-alerts-editor-implementation.md.
"""

from pathlib import Path
from typing import Any

import yaml
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

RULES_DIR = Path("/etc/prometheus/rules")
TEMPLATES_DIR = Path(__file__).parent / "templates"

app = FastAPI(title="Prometheus alerts editor")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))


def _load_disk_rules(rules_dir: Path | None = None) -> tuple[list[dict[str, Any]], list[str]]:
    """Walk ``juju_*.rules`` files and return ``(rules, parse_errors)``.

    Each rule is flattened to a dict with ``source_file``, ``group``, ``alert``, ``expr``,
    ``for``, ``labels``, ``annotations``. Non-alert entries (recording rules) are skipped.
    Files that fail to parse are reported in ``parse_errors`` rather than crashing the page.
    """
    if rules_dir is None:
        rules_dir = RULES_DIR

    rules: list[dict[str, Any]] = []
    errors: list[str] = []

    if not rules_dir.is_dir():
        return rules, errors

    for path in sorted(rules_dir.glob("juju_*.rules")):
        try:
            doc = yaml.safe_load(path.read_text()) or {}
        except yaml.YAMLError as exc:
            errors.append(f"{path.name}: {exc}")
            continue

        groups = doc.get("groups") or []
        if not isinstance(groups, list):
            errors.append(f"{path.name}: top-level 'groups' is not a list")
            continue

        for group in groups:
            if not isinstance(group, dict):
                continue
            group_name = group.get("name", "")
            for rule in group.get("rules") or []:
                if not isinstance(rule, dict) or "alert" not in rule:
                    # Skip recording rules and malformed entries.
                    continue
                rules.append(
                    {
                        "source_file": path.name,
                        "group": group_name,
                        "alert": rule.get("alert", ""),
                        "expr": rule.get("expr", ""),
                        "for": rule.get("for", ""),
                        "labels": rule.get("labels") or {},
                        "annotations": rule.get("annotations") or {},
                    }
                )

    return rules, errors


@app.get("/", response_class=HTMLResponse)
def index(request: Request) -> HTMLResponse:
    """Render the read-only list of alert rules currently on disk."""
    rules, parse_errors = _load_disk_rules()
    return templates.TemplateResponse(
        "index.html.j2",
        {
            "request": request,
            "rules": rules,
            "parse_errors": parse_errors,
            "rules_dir": str(RULES_DIR),
            "rules_dir_mounted": RULES_DIR.is_dir(),
        },
    )


@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok"}
