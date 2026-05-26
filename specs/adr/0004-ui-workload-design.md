# ADR 0004 — UI workload design

**Status:** Proposed
**Date:** 2026-05-13
**Related:** [spec/0001](../0001-alerts-editor.md), [ADR-0001](0001-packaging-sidecar-vs-separate-charm.md), [ADR-0002](0002-diff-storage.md), [ADR-0006](0006-diff-document-schema.md)

## Context

The UI is its own container in the Prometheus pod ([ADR-0001](0001-packaging-sidecar-vs-separate-charm.md)). It must:

- Serve a single web page resembling Prometheus's Alerts page.
- List every alert rule currently loaded by Prometheus.
- Per rule, show editable fields for `for`, `expr`, `labels`, `annotations`, plus a "remove" button.
- On save, write a YAML diff (per [ADR-0006](0006-diff-document-schema.md)) to `/etc/prometheus/rules/diff.yaml`.
- Be small, easy to containerize, and trivial to demo.

This ADR covers the UI workload's own design. It does **not** cover where the diff is stored ([ADR-0002](0002-diff-storage.md)), how the charm picks it up ([ADR-0003](0003-ui-to-charm-transport.md)), or the diff schema ([ADR-0006](0006-diff-document-schema.md)).

## Decisions

### D1. Source of "current rules" data — shared volume, not HTTP

The UI reads rule files directly from the shared `rules` storage at `/etc/prometheus/rules/juju_*.rules`. These are the post-merge files the charm has written (relation-supplied rules with any prior overlay already applied). The UI does **not** call Prometheus's HTTP API.

Reasoning:

- Per team decision: no HTTP dependency on the Prometheus workload.
- Both containers mount the same Juju storage at `/etc/prometheus/rules/`, so the UI sees the same files Prometheus is loading.
- One fewer moving part: no HTTP client, no waiting for Prometheus to be ready, no TLS/auth concerns when TLS is later enabled.

The rule files are Prometheus's standard YAML group format:

```yaml
groups:
  - name: kubernetes-apps
    rules:
      - alert: KubePodCrashLooping
        expr: ...
        for: 15m
        labels:
          severity: warning
        annotations:
          summary: ...
```

The UI walks every `juju_*.rules` file → every group → every rule, building a flat list. It tracks the source file and group of each rule so the round-trip back to a diff knows which producer a rule came from.

### D2. Tech stack

**Recommended: FastAPI + Jinja2 + htmx, single Python process, served by uvicorn.**

Reasoning unchanged from prior draft:

- FastAPI for routing and small JSON endpoints used by htmx.
- Jinja2 for server-rendered HTML — much faster to iterate than a JS framework for an 8-hour deadline.
- htmx for inline "remove" and "save" interactions without a JS build pipeline.

Alternatives:

- **Streamlit** — fastest to bootstrap (~30 min) but harder to make "look like the Prometheus alerts page." Team's call to flip; schema and storage decisions don't care.
- **SPA (React/Vue)** — too much setup cost.
- **Plain HTML + tiny API** — viable; htmx is a thin sugar layer over this.

### D3. Page layout

Single page, list of rule "cards" mimicking the Prometheus alerts page:

```
┌─ KubePodCrashLooping ─────────────────────────── [Remove] ┐
│  Source: juju_kube-state-metrics.rules / kubernetes-apps  │
│  expr:  [ rate(kube_pod_container_status_restarts...) ]   │
│  for:   [ 15m   ]                                          │
│  labels:                                                   │
│    severity: [ warning  ]                                  │
│    [+ add label]                                           │
│  annotations:                                              │
│    summary:     [ Pod is crash looping                  ]  │
│    description: [ {{ $labels.namespace }} / ...         ]  │
│    [+ add annotation]                                      │
└────────────────────────────────────────────────────────────┘
```

A small badge ("patched" / "removed") appears on rules already touched by the current `diff.yaml`. Header has a single "Save all changes" button; optional "Discard" reloads from disk.

### D4. Diff computation — diff document as first-class state

This is the part that needs care because the UI reads **post-merge** state from disk but writes a diff intended as "what to do **to the pre-merge** rules". The two views are not directly comparable, so the UI must treat `diff.yaml` as its own piece of authoritative state, not derive it from scratch.

**Model:**

The UI maintains three state objects in memory:

1. **`disk_rules`** — flat list of rules parsed from `juju_*.rules` files at page load. Read-only. This is the rules Prometheus is currently evaluating.
2. **`current_diff`** — the parsed contents of `diff.yaml` at page load. Authoritative model of operator intent.
3. **`working_diff`** — a mutable copy of `current_diff` that operator interactions mutate directly.

**Rendering:**

- Display each rule in `disk_rules`, with values from disk.
- If a rule's name appears in `working_diff.patch[*].match.alert`, show a "patched" badge and pre-populate inputs with the *patched* values (which is what disk shows anyway, since the previous reconcile already applied that patch).
- If a rule's name appears in `working_diff.remove[*].match.alert`, render it greyed out with a strikethrough — and an "undo remove" affordance.

**Operator interactions mutate `working_diff` directly:**

- Click "Remove" on rule X → add `{match: {alert: X}}` to `working_diff.remove`. If X has a `patch` entry in `working_diff`, drop the patch entry too.
- Edit any field on rule Y → upsert into `working_diff.patch` with the changed field under `set`. Patch entries are coalesced on `match.alert` to keep the diff minimal.
- Click "undo remove" on previously-removed rule Z → drop the corresponding entry from `working_diff.remove`.

**On save:** serialise `working_diff` to YAML and atomically write to `/etc/prometheus/rules/diff.yaml` (`diff.yaml.tmp` + rename).

**Important consequence**: the UI never needs to "compute the difference between two states." It only needs to translate UI events to diff operations. This is much simpler than trying to do structural diffing.

### D5. Validation in the UI

Run client-side validation before save:

- `for:` must parse as a Prometheus duration (`\d+[smhdwy]` repeated).
- `expr:` is **not** validated — we don't ship `promtool` in the UI container. Charm-side merge catches invalid PromQL ([ADR-0005](0005-charm-merge-pipeline.md)).
- Label/annotation keys must match `[a-zA-Z_][a-zA-Z0-9_]*`.
- Each rule in `disk_rules` must appear exactly once (sanity check; if two producers ship the same alert name, that row is rendered with an "ambiguous" warning and editing/removal is disabled, per [ADR-0006](0006-diff-document-schema.md) D1).

Validation failure shows inline errors; do not write the file.

### D6. Bootstrap and reload behaviour

On page load:

1. List `/etc/prometheus/rules/juju_*.rules`, parse each, build `disk_rules`.
2. If `/etc/prometheus/rules/diff.yaml` exists, parse it into `current_diff`. If malformed, set `current_diff` to empty and show a banner: "Existing overlay could not be parsed; starting fresh."
3. `working_diff = deep_copy(current_diff)`.
4. Render the page.

The UI does not poll. Reload-on-demand only (refresh button or full page reload).

### D7. Auth / access

None in MVP. Operators reach the UI via `kubectl port-forward` or the pod IP during a hackathon demo.

## Consequences

- The UI workload is one Python file (`app.py`), one template (`index.html.j2`), one Dockerfile.
- Container image is small: `python:3.12-slim` + `fastapi` + `jinja2` + `pyyaml` + `uvicorn`; htmx is a single static JS file served by the app.
- The UI parses Prometheus YAML rule format; needs a small parser (just `yaml.safe_load` + dict walking — no `promtool` required).
- The UI must mount the shared `rules` storage at `/etc/prometheus/rules/` per [ADR-0002](0002-diff-storage.md). Without that mount, nothing works.
- The UI is the **only** writer of `diff.yaml`. The charm is the only reader. No locking needed because saves are atomic via temp-file rename, and the charm reads a complete file or no file.
- Two pieces of knowledge are shared between UI and charm: the diff schema ([ADR-0006](0006-diff-document-schema.md)) and the file paths. Cost of duplication is low; document the paths in both codebases as constants.

## Open questions

- Single repo for UI source vs. separate repo? Hackathon answer: a `ui/` subfolder in this repo. Image built via GitHub Action or by hand and pushed to ghcr.
- Do we add an "import existing diff.yaml" textarea so an operator can paste a hand-written diff? Out of MVP scope but ~30 min of work.
- If a rule disappears from `disk_rules` (the producer charm stopped shipping it) but is still referenced by `working_diff.remove` or `working_diff.patch`, what does the UI show? Suggest: a small "orphan overlay entries" section at the bottom with a "clear" affordance. Cheap to add, prevents stale entries from rotting silently.
- How does the UI detect "rule files have changed under me since page load" (e.g. a new producer integrated)? Simple v1: don't try — operator refreshes the page. Better v1.1: a periodic background fetch + soft prompt to reload.
