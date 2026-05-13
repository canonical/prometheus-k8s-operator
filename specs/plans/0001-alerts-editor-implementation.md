# Plan 0001 — Alerts Editor implementation (hackathon)

**Status:** In progress
**Date:** 2026-05-13
**Owner:** Csaba
**Related:** [spec/0001](../0001-alerts-editor.md), [ADR-0001](../adr/0001-packaging-sidecar-vs-separate-charm.md), [ADR-0004](../adr/0004-ui-workload-design.md), [ADR-0005](../adr/0005-charm-merge-pipeline.md), [ADR-0006](../adr/0006-diff-document-schema.md)

## Strategy

Ship in vertical slices, each one independently demoable. Stop at any milestone and we still have working code in the trunk. Each milestone ends with a `juju refresh` and a manual demo step we can show.

The UI lives in a **second container** in the Prometheus pod, per [ADR-0001](../adr/0001-packaging-sidecar-vs-separate-charm.md) — *not* as code added to the charm's own process (Option C was rejected).

## Milestone 1 — "Hello, alerts editor" (the container is alive)

**Goal:** new container in the pod, exposes port 8080, returns a stub page. No rule parsing, no diff. Just prove plumbing.

### Files touched

- [charmcraft.yaml](../../charmcraft.yaml) — add:
  - `containers.alerts-editor` with `resource: alerts-editor-image`.
  - `resources.alerts-editor-image` pointing at a placeholder (`python:3.12-slim` is fine until we publish our own).
  - `storage.rules` (filesystem) and mount it under `/etc/prometheus/rules/` in **both** the `prometheus` and `alerts-editor` containers. The existing Prometheus config already writes alert rule files to that path — we just need to make it a shared Juju storage.
- [src/charm.py](../../src/charm.py) —
  - new property `_alerts_editor_layer` mirroring [_prometheus_layer](../../src/charm.py#L511): a single Pebble service `alerts-editor` running `uvicorn app:app --host 0.0.0.0 --port 8080`.
  - call `container.add_layer(...)` + `container.replan()` from `_configure`, gated on `container.can_connect()`. Use the existing `pebble-ready` hook wiring for the new container name.
  - open port 8080 via `self.unit.set_ports(...)` (alongside Prometheus's 9090).
- new folder `src/ui/` (under `src/` so `charmcraft pack` reliably bundles it — the charm pushes `app.py` into the container at reconcile time so we don't need to build a custom image yet) —
  - `src/ui/app.py` — minimal FastAPI app with `GET /` returning HTML "Alerts editor — stub page".
  - `src/ui/Dockerfile` — `FROM python:3.12-slim`, `pip install fastapi uvicorn jinja2 pyyaml`, `COPY app.py /app/`, `CMD uvicorn app:app --host 0.0.0.0 --port 8080`.
  - `src/ui/README.md` — one-paragraph "build with `docker build -t ghcr.io/<you>/alerts-editor:dev .`, push, then update `resources.alerts-editor-image` in `charmcraft.yaml`".

### Demo step

```
charmcraft pack
juju refresh prometheus-k8s --path ./prometheus-k8s_*.charm --resource alerts-editor-image=<image>
kubectl port-forward -n <model> pod/prometheus-k8s-0 8080:8080 -c alerts-editor
curl localhost:8080  # → "Alerts editor — stub page"
```

### Exit criteria

- `juju status` clean.
- The new container shows up in `kubectl describe pod`.
- The stub page is reachable.

## Milestone 2 — Read-only rule list

**Goal:** the page shows every rule Prometheus is currently loading. No editing yet. Implements [ADR-0004 D1 + D3](../adr/0004-ui-workload-design.md) for the read-side only.

### Files touched

- `src/ui/app.py` —
  - `_load_disk_rules()` — `glob('/etc/prometheus/rules/juju_*.rules')`, `yaml.safe_load` each, walk `groups[*].rules[*]`, return a flat list of dicts with `{source_file, group, alert, expr, for, labels, annotations}`.
  - `GET /` renders `index.html.j2` with the rule list (read-only — no inputs yet).
- `src/ui/templates/index.html.j2` — table or `<details>` per rule, matching the card sketch in [ADR-0004 D3](../adr/0004-ui-workload-design.md). Static HTML; htmx not required yet.
- `src/ui/static/` — placeholder; nothing here until M3.

### Demo step

Deploy a charm that ships rules (e.g. `kube-state-metrics-k8s`), relate it, refresh the page, see the rules listed with source-file annotation.

### Exit criteria

- All `juju_*.rules` are parsed without crashes.
- Rule count in the UI matches `wc -l` heuristic on the rules files.
- Empty state (no rules yet) renders a "no rules loaded" message rather than 500ing.

## Milestone 3 — Edit + remove + save (writes `diff.yaml`)

**Goal:** the full UI write path. Operators can edit `for`/`expr`/`labels`/`annotations`, click Remove, hit Save, and `/etc/prometheus/rules/diff.yaml` appears on the shared volume. The charm-side merge is **not** wired up yet — we verify by `kubectl exec ... cat /etc/prometheus/rules/diff.yaml`.

Implements [ADR-0004 D4 + D5 + D6](../adr/0004-ui-workload-design.md) and the file format from [ADR-0006](../adr/0006-diff-document-schema.md).

### Files touched

- `src/ui/app.py` —
  - bootstrap: on first request (or `GET /`), load `disk_rules` + parse existing `diff.yaml` into `current_diff`; `working_diff = deep_copy(current_diff)`. State held in a module-level dict — single-process, single-worker uvicorn is fine for MVP.
  - `POST /rules/{alert_name}/remove` → mutate `working_diff.remove`.
  - `POST /rules/{alert_name}/undo-remove` → drop from `working_diff.remove`.
  - `POST /rules/{alert_name}/patch` (form body) → upsert into `working_diff.patch` with changed fields under `set`. Coalesce on `match.alert`.
  - `POST /save` → validate (see below), serialise `working_diff` to YAML, atomic write to `/etc/prometheus/rules/diff.yaml` via temp-file + rename.
  - validation: `for:` must parse Prometheus duration; label/annotation keys must match `[a-zA-Z_][a-zA-Z0-9_]*`; reject save on failure with inline errors.
- `src/ui/templates/index.html.j2` — htmx-powered inputs and buttons; "patched"/"removed" badges; Save button at the top.
- `src/ui/static/htmx.min.js` — vendored; the app serves it.

### Demo step

Edit one rule, remove another, click Save, then:

```
kubectl exec -n <model> prometheus-k8s-0 -c prometheus -- cat /etc/prometheus/rules/diff.yaml
```

Confirm the file matches the [ADR-0006](../adr/0006-diff-document-schema.md) schema.

### Exit criteria

- Round-trip works: edit → save → refresh page → badges persist, inputs pre-populated from `working_diff`.
- Atomic write: kill the UI mid-save; on restart, either the new file is fully there or the old one is untouched (no half-written file).
- Validation failure does not write `diff.yaml`.

## Milestone 4 — Charm picks up the diff (end-to-end)

**Goal:** the merge pipeline in [ADR-0005](../adr/0005-charm-merge-pipeline.md). This is a different person's lane on the team — included here so we know where M3 hands off.

### Files touched (sketch — owned by the charm-merge person)

- [src/charm.py](../../src/charm.py) `_set_alerts` — after writing relation-supplied rule files, read `diff.yaml` (Pebble pull from the prometheus container per [ADR-0003](../adr/0003-ui-to-charm-transport.md)), apply patches/removes, write the merged result.
- Trigger reconcile on `update-status` or via a manual `juju run prometheus-k8s/0`.

### Exit criteria (full demo path)

- Operator removes `AlwaysFiringDueToAbsentMetric` in the UI → saves → triggers reconcile → Prometheus's own `/alerts` page no longer lists it.
- Operator changes `HostDown.for` from `10m` to `40m` → reconcile → Prometheus's `/alerts` reflects the new `for`.

## Out of scope for this plan

- Auth on the UI ([ADR-0004 D7](../adr/0004-ui-workload-design.md)).
- Live reload / polling when rule files change under us.
- "Add custom alert group" (`add:` in the diff) — schema reserves the shape but no UI affordance.
- Image build pipeline. We push by hand; renovate config is post-hackathon.
- Multi-unit; we assume 1 Prometheus unit throughout.

## Open risks

- `juju refresh` semantics with a new container + new storage on an already-deployed unit. Worst case: we redeploy from scratch. Cheap to test in M1.
- Pebble `replan` ordering vs. the shared volume mount being ready. Mitigation: gate the layer add on `container.can_connect()`.
- The `src/ui/` Python deps need to match what's in the image. Mitigation: keep deps in a single `src/ui/requirements.txt` and have the Dockerfile install from it.
