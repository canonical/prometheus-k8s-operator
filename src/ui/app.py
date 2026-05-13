"""Alerts editor UI — Milestone 3 edit + remove + save (writes ``diff.yaml``).

Implements the model described in
specs/adr/0004-ui-workload-design.md D4-D6 and the schema in
specs/adr/0006-diff-document-schema.md.

The UI maintains three pieces of state:

- ``disk_rules`` — rules parsed from ``/etc/prometheus/rules/juju_*.rules`` on each
  request. Authoritative for what Prometheus is *currently* evaluating.
- ``current_diff`` — the parsed contents of ``diff.yaml`` at bootstrap.
- ``working_diff`` — a mutable copy of ``current_diff``; operator interactions
  mutate it directly, and ``POST /save`` serialises it back to disk.

State is held in a single module-level dict (single-process, single-worker
uvicorn per ADR-0004 D4). The schema validator in ``src/alerts_overlay.py``
is the charm-side backstop; we keep this file self-contained because the
Dockerfile only ships ``app.py``.
"""

from __future__ import annotations

import copy
import html
import logging
import os
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any

import yaml
from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

logger = logging.getLogger(__name__)

RULES_DIR = Path("/etc/prometheus/rules")
DIFF_FILENAME = "diff.yaml"
TEMPLATES_DIR = Path(__file__).parent / "templates"
STATIC_DIR = Path(__file__).parent / "static"

SCHEMA_VERSION = 1

# Pebble custom notice the UI fires after a successful save so the charm can
# apply the new diff without waiting for the next update-status. Must match
# the constant in src/charm.py (DIFF_SAVED_NOTICE_KEY).
DIFF_SAVED_NOTICE_KEY = "canonical.com/alerts-editor/diff-saved"

# Prometheus duration: one or more `<int><unit>` segments. Empty string is allowed
# (means "no `for`" — same as omitting the field).
_DURATION_RE = re.compile(r"^(\d+[smhdwy])+$")
# Prometheus label/annotation key grammar — same as alerts_overlay.
_KEY_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")

app = FastAPI(title="Prometheus alerts editor")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
if STATIC_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

_STATE: dict[str, Any] = {
    "bootstrapped": False,
    "current_diff": None,
    "working_diff": None,
    "load_error": None,  # banner text if diff.yaml was malformed at bootstrap
}


def _empty_diff() -> dict[str, Any]:
    return {"schemaVersion": SCHEMA_VERSION, "remove": [], "patch": []}


def _ensure_bootstrapped() -> None:
    """Parse ``diff.yaml`` once (per ADR-0004 D6); subsequent calls are no-ops."""
    if _STATE["bootstrapped"]:
        return
    _STATE["bootstrapped"] = True

    diff_path = RULES_DIR / DIFF_FILENAME
    if not diff_path.is_file():
        _STATE["current_diff"] = _empty_diff()
        _STATE["working_diff"] = _empty_diff()
        return

    try:
        doc = yaml.safe_load(diff_path.read_text()) or _empty_diff()
        if not isinstance(doc, dict):
            raise ValueError("top-level YAML must be a mapping")
        # Normalise the shape so the rest of the code can rely on lists existing.
        doc.setdefault("schemaVersion", SCHEMA_VERSION)
        doc["remove"] = list(doc.get("remove") or [])
        doc["patch"] = list(doc.get("patch") or [])
        _STATE["current_diff"] = doc
        _STATE["working_diff"] = copy.deepcopy(doc)
    except (yaml.YAMLError, ValueError) as exc:
        _STATE["load_error"] = (
            f"Existing {DIFF_FILENAME} could not be parsed ({exc}); starting fresh."
        )
        _STATE["current_diff"] = _empty_diff()
        _STATE["working_diff"] = _empty_diff()


def _working_diff() -> dict[str, Any]:
    _ensure_bootstrapped()
    return _STATE["working_diff"]


# ---------------------------------------------------------------------------
# Disk rules
# ---------------------------------------------------------------------------


def _load_disk_rules(
    rules_dir: Path | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
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


# ---------------------------------------------------------------------------
# Diff manipulation helpers
# ---------------------------------------------------------------------------


def _find_patch(diff: dict[str, Any], alert: str) -> dict[str, Any] | None:
    for entry in diff["patch"]:
        if entry.get("match", {}).get("alert") == alert:
            return entry
    return None


def _is_removed(diff: dict[str, Any], alert: str) -> bool:
    return any(e.get("match", {}).get("alert") == alert for e in diff["remove"])


def _drop_patch(diff: dict[str, Any], alert: str) -> None:
    diff["patch"] = [
        e for e in diff["patch"] if e.get("match", {}).get("alert") != alert
    ]


def _drop_remove(diff: dict[str, Any], alert: str) -> None:
    diff["remove"] = [
        e for e in diff["remove"] if e.get("match", {}).get("alert") != alert
    ]


def _effective_view(
    rule: dict[str, Any], diff: dict[str, Any]
) -> dict[str, Any]:
    """Overlay ``working_diff`` onto a disk rule for rendering inputs.

    Per ADR-0004 D4: pre-populate inputs with the patched values so the operator
    sees the state they last saved (not the pre-merge values).
    """
    patch = _find_patch(diff, rule["alert"])
    view = {
        "alert": rule["alert"],
        "group": rule["group"],
        "source_file": rule["source_file"],
        "expr": rule["expr"],
        "for": rule.get("for", ""),
        "labels": dict(rule.get("labels") or {}),
        "annotations": dict(rule.get("annotations") or {}),
        "patched": patch is not None,
        "removed": _is_removed(diff, rule["alert"]),
        "ambiguous": False,  # filled in by caller
    }
    if patch:
        set_ = patch.get("set") or {}
        if "for" in set_:
            view["for"] = set_["for"]
        if "expr" in set_:
            view["expr"] = set_["expr"]
        if isinstance(set_.get("labels"), dict):
            view["labels"].update(set_["labels"])
        if isinstance(set_.get("annotations"), dict):
            view["annotations"].update(set_["annotations"])
    return view


def _render_kv(d: dict[str, Any]) -> str:
    """Render a label/annotation dict as `key: value` lines for a textarea."""
    return "\n".join(f"{k}: {v}" for k, v in d.items())


def _parse_kv_textarea(text: str) -> tuple[dict[str, str], list[str]]:
    """Parse a textarea of ``key: value`` lines. Returns ``(parsed, errors)``."""
    parsed: dict[str, str] = {}
    errors: list[str] = []
    for lineno, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line:
            continue
        if ":" not in line:
            errors.append(f"line {lineno}: expected 'key: value', got {raw!r}")
            continue
        key, _, value = line.partition(":")
        key = key.strip()
        value = value.strip()
        if not _KEY_RE.match(key):
            errors.append(
                f"line {lineno}: key {key!r} must match [a-zA-Z_][a-zA-Z0-9_]*"
            )
            continue
        parsed[key] = value
    return parsed, errors


def _validate_duration(value: str) -> str | None:
    """Return an error string if ``value`` is not a valid Prometheus duration."""
    if value == "":
        return None
    if not _DURATION_RE.match(value):
        return f"{value!r} is not a valid Prometheus duration (e.g. 30s, 5m, 1h)"
    return None


def _upsert_patch(diff: dict[str, Any], alert: str, set_block: dict[str, Any]) -> None:
    """Insert or update a patch entry for ``alert`` with the given ``set`` block."""
    existing = _find_patch(diff, alert)
    if existing is None:
        diff["patch"].append({"match": {"alert": alert}, "set": set_block})
    else:
        existing["set"] = set_block


# ---------------------------------------------------------------------------
# Rendering helpers
# ---------------------------------------------------------------------------


def _build_views(
    disk_rules: list[dict[str, Any]], diff: dict[str, Any]
) -> list[dict[str, Any]]:
    """Compute per-rule view dicts + flag ambiguous alert names."""
    counts: dict[str, int] = {}
    for r in disk_rules:
        counts[r["alert"]] = counts.get(r["alert"], 0) + 1

    views = []
    for r in disk_rules:
        v = _effective_view(r, diff)
        v["ambiguous"] = counts[r["alert"]] > 1
        v["labels_text"] = _render_kv(v["labels"])
        v["annotations_text"] = _render_kv(v["annotations"])
        views.append(v)
    return views


def _render_card(view: dict[str, Any], request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        "_rule_card.html.j2",
        {"request": request, "rule": view},
    )


def _view_for(alert: str, request: Request) -> HTMLResponse | None:
    disk_rules, _ = _load_disk_rules()
    views = _build_views(disk_rules, _working_diff())
    for v in views:
        if v["alert"] == alert:
            return _render_card(v, request)
    return None


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@app.get("/", response_class=HTMLResponse)
def index(request: Request) -> HTMLResponse:
    _ensure_bootstrapped()
    disk_rules, parse_errors = _load_disk_rules()
    diff = _working_diff()
    views = _build_views(disk_rules, diff)
    return templates.TemplateResponse(
        "index.html.j2",
        {
            "request": request,
            "rules": views,
            "parse_errors": parse_errors,
            "rules_dir": str(RULES_DIR),
            "rules_dir_mounted": RULES_DIR.is_dir(),
            "load_error": _STATE["load_error"],
            "removed_count": len(diff["remove"]),
            "patched_count": len(diff["patch"]),
        },
    )


@app.post("/rules/{alert_name}/remove", response_class=HTMLResponse)
def remove_rule(alert_name: str, request: Request) -> HTMLResponse:
    diff = _working_diff()
    # Removing supersedes any patch on the same rule (ADR-0004 D4).
    _drop_patch(diff, alert_name)
    if not _is_removed(diff, alert_name):
        diff["remove"].append({"match": {"alert": alert_name}})
    card = _view_for(alert_name, request)
    if card is None:
        return HTMLResponse(f"rule {html.escape(alert_name)!r} not found", status_code=404)
    return card


@app.post("/rules/{alert_name}/undo-remove", response_class=HTMLResponse)
def undo_remove(alert_name: str, request: Request) -> HTMLResponse:
    _drop_remove(_working_diff(), alert_name)
    card = _view_for(alert_name, request)
    if card is None:
        return HTMLResponse(f"rule {html.escape(alert_name)!r} not found", status_code=404)
    return card


@app.post("/rules/{alert_name}/patch", response_class=HTMLResponse)
def patch_rule(
    alert_name: str,
    request: Request,
    for_value: str = Form("", alias="for"),
    expr: str = Form(""),
    labels: str = Form(""),
    annotations: str = Form(""),
) -> HTMLResponse:
    """Diff the submitted form against the disk rule and upsert a patch.

    Only fields that differ from the disk version end up in ``set``. If nothing
    differs, the patch entry is dropped — this lets an operator revert by
    editing back to the on-disk values.
    """
    disk_rules, _ = _load_disk_rules()
    disk = next((r for r in disk_rules if r["alert"] == alert_name), None)
    if disk is None:
        return HTMLResponse(f"rule {html.escape(alert_name)!r} not found", status_code=404)

    diff = _working_diff()
    # Editing un-removes — operator intent is clearly "I want this rule".
    _drop_remove(diff, alert_name)

    errors: list[str] = []

    for_value = for_value.strip()
    err = _validate_duration(for_value)
    if err:
        errors.append(f"for: {err}")

    expr = expr.strip()

    parsed_labels, label_errors = _parse_kv_textarea(labels)
    errors.extend(f"labels: {e}" for e in label_errors)
    parsed_annotations, ann_errors = _parse_kv_textarea(annotations)
    errors.extend(f"annotations: {e}" for e in ann_errors)

    if errors:
        view = _effective_view(disk, diff)
        view["ambiguous"] = sum(1 for r in disk_rules if r["alert"] == alert_name) > 1
        view["labels_text"] = labels
        view["annotations_text"] = annotations
        view["for"] = for_value
        view["expr"] = expr
        view["errors"] = errors
        return _render_card(view, request)

    set_block: dict[str, Any] = {}
    if for_value != (disk.get("for") or ""):
        set_block["for"] = for_value
    if expr != disk["expr"]:
        set_block["expr"] = expr

    disk_labels = disk.get("labels") or {}
    label_overrides = {
        k: v for k, v in parsed_labels.items() if disk_labels.get(k) != v
    }
    if label_overrides:
        set_block["labels"] = label_overrides

    disk_annotations = disk.get("annotations") or {}
    annotation_overrides = {
        k: v for k, v in parsed_annotations.items() if disk_annotations.get(k) != v
    }
    if annotation_overrides:
        set_block["annotations"] = annotation_overrides

    if set_block:
        _upsert_patch(diff, alert_name, set_block)
    else:
        _drop_patch(diff, alert_name)

    return _view_for(alert_name, request)  # type: ignore[return-value]


@app.post("/save", response_class=HTMLResponse)
def save(request: Request) -> HTMLResponse:
    """Validate ``working_diff`` and atomically write it to ``diff.yaml``."""
    diff = _working_diff()
    errors = _validate_diff(diff)
    if errors:
        return templates.TemplateResponse(
            "_save_status.html.j2",
            {"request": request, "errors": errors, "saved": False},
            status_code=400,
        )

    doc = _serialise_diff(diff)
    target = RULES_DIR / DIFF_FILENAME
    try:
        _atomic_write_yaml(target, doc)
    except OSError as exc:
        return templates.TemplateResponse(
            "_save_status.html.j2",
            {
                "request": request,
                "errors": [f"could not write {target}: {exc}"],
                "saved": False,
            },
            status_code=500,
        )

    _STATE["current_diff"] = copy.deepcopy(diff)
    _notify_charm_of_save()

    return templates.TemplateResponse(
        "_save_status.html.j2",
        {"request": request, "errors": [], "saved": True, "path": str(target)},
    )


def _notify_charm_of_save() -> None:
    """Fire a Pebble custom notice so the charm reconciles immediately.

    Best-effort: the file is already written, so a failed notice just means the
    charm picks up the change on its next update-status hook instead of right
    away. We never fail the HTTP request on a missing/broken pebble.
    """
    try:
        subprocess.run(
            ["/charm/bin/pebble", "notify", DIFF_SAVED_NOTICE_KEY],
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        logger.warning("could not fire pebble notice %r: %s", DIFF_SAVED_NOTICE_KEY, exc)


@app.post("/discard", response_class=HTMLResponse)
def discard(request: Request) -> HTMLResponse:
    """Reset ``working_diff`` to ``current_diff`` and re-render the page body."""
    _ensure_bootstrapped()
    _STATE["working_diff"] = copy.deepcopy(_STATE["current_diff"])
    return index(request)


@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok"}


# ---------------------------------------------------------------------------
# Save: validation + serialisation
# ---------------------------------------------------------------------------


def _validate_diff(diff: dict[str, Any]) -> list[str]:
    """Re-validate ``working_diff`` before write. UI should keep it valid, but
    this is defence-in-depth — the charm side runs the same checks (ADR-0006).
    """
    errors: list[str] = []
    patch_alerts: set[str] = set()
    for entry in diff["patch"]:
        alert = entry.get("match", {}).get("alert", "")
        if not alert:
            errors.append("patch: missing match.alert")
            continue
        if alert in patch_alerts:
            errors.append(f"patch: duplicate entry for {alert!r}")
        patch_alerts.add(alert)
        set_block = entry.get("set") or {}
        if not set_block:
            errors.append(f"patch[{alert}]: 'set' is empty")
            continue
        if "for" in set_block:
            err = _validate_duration(set_block["for"])
            if err:
                errors.append(f"patch[{alert}].for: {err}")
        for kind in ("labels", "annotations"):
            block = set_block.get(kind) or {}
            for key in block:
                if not _KEY_RE.match(key):
                    errors.append(
                        f"patch[{alert}].{kind}: key {key!r} must match "
                        f"[a-zA-Z_][a-zA-Z0-9_]*"
                    )
    remove_alerts: set[str] = set()
    for entry in diff["remove"]:
        alert = entry.get("match", {}).get("alert", "")
        if not alert:
            errors.append("remove: missing match.alert")
            continue
        if alert in remove_alerts:
            errors.append(f"remove: duplicate entry for {alert!r}")
        remove_alerts.add(alert)
    return errors


def _serialise_diff(diff: dict[str, Any]) -> dict[str, Any]:
    """Project ``working_diff`` into the schema shape we write to disk.

    Always pins ``schemaVersion``; omits empty top-level lists by writing them
    as ``[]`` (the schema says omitting is equivalent — but a present-but-empty
    list is friendlier to skim).
    """
    return {
        "schemaVersion": SCHEMA_VERSION,
        "remove": list(diff.get("remove") or []),
        "patch": list(diff.get("patch") or []),
    }


def _atomic_write_yaml(path: Path, doc: dict[str, Any]) -> None:
    """Write YAML atomically: tmp file in the same dir, fsync, rename."""
    path.parent.mkdir(parents=True, exist_ok=True)
    body = yaml.safe_dump(doc, sort_keys=False, default_flow_style=False)
    # Use a NamedTemporaryFile in the same directory so os.replace stays atomic
    # (rename across filesystems is not).
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent)
    )
    try:
        with os.fdopen(fd, "w") as f:
            f.write(body)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_name, path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise
