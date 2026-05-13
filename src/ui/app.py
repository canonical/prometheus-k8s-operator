"""Alerts editor UI — Milestone 1 stub.

Serves a single page confirming the sidecar container is alive and that the shared
`/etc/prometheus/rules` volume is mounted. Rule parsing and the diff write-path land
in later milestones — see specs/plans/0001-alerts-editor-implementation.md.
"""

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

RULES_DIR = Path("/etc/prometheus/rules")

app = FastAPI(title="Prometheus alerts editor (stub)")


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    """Render the M1 stub page: container heartbeat plus shared-volume diagnostics."""
    rules_mounted = RULES_DIR.is_dir()
    rule_files = sorted(p.name for p in RULES_DIR.glob("juju_*.rules")) if rules_mounted else []
    rule_files_html = (
        "<ul>" + "".join(f"<li><code>{name}</code></li>" for name in rule_files) + "</ul>"
        if rule_files
        else "<p><em>(no rule files yet — relate a producer charm)</em></p>"
    )
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Alerts editor</title>
  <style>
    body {{ font-family: system-ui, sans-serif; max-width: 720px; margin: 2rem auto; padding: 0 1rem; }}
    code {{ background: #f3f3f3; padding: 0.1rem 0.3rem; border-radius: 3px; }}
    .ok {{ color: #137333; }}
    .warn {{ color: #b06000; }}
  </style>
</head>
<body>
  <h1>Alerts editor &mdash; stub page</h1>
  <p>The <code>alerts-editor</code> sidecar container is alive on port 8080.</p>
  <h2>Shared rules volume</h2>
  <p>
    <code>/etc/prometheus/rules</code>:
    {'<span class="ok">mounted</span>' if rules_mounted else '<span class="warn">missing</span>'}
  </p>
  <p>Discovered rule files:</p>
  {rule_files_html}
  <hr>
  <p><small>
    Milestone 1 of <code>specs/plans/0001-alerts-editor-implementation.md</code>.
    Rule editing arrives in M2/M3.
  </small></p>
</body>
</html>
"""


@app.get("/healthz")
def healthz() -> dict:
    return {"status": "ok"}
