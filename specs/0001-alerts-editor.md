# Spec 0001 — Alerts Editor (Hackathon MVP)

**Status:** Accepted (MVP scope)
**Scope:** 8-hour hackathon, single Prometheus unit
**Related ADRs:** [0001](adr/0001-packaging.md), [0002](adr/0002-diff-storage.md), [0003](adr/0003-ui-to-charm-transport.md), [0004](adr/0004-ui-workload-design.md), [0005](adr/0005-charm-merge-pipeline.md), [0006](adr/0006-diff-document-schema.md)

## Problem

Alert rules reach this charm exclusively through relations (`metrics-endpoint`, `receive-remote-write`) and the charm writes them verbatim under `/etc/prometheus/rules/juju_<topology>.rules` ([`_set_alerts`](../src/charm.py#L805)). Operators have **no supported way** to silence a noisy upstream alert, or to tighten thresholds/severity/annotations on a per-deployment basis, without forking the producing charm.

## Goals (MVP)

- Add a UI workload to the Prometheus pod that displays the rules currently loaded by Prometheus in a layout reminiscent of Prometheus's own Alerts page.
- Let the operator **remove** an existing alert rule.
- Let the operator **patch** an existing alert rule's mutable fields (`for`, `expr`, `labels`, `annotations`).
- Persist these edits as a YAML diff document.
- Have the charm pick up the diff on its next reconcile and produce a merged rule set that Prometheus loads.

## Non-goals (deferred)

| Item                                                                  | Why deferred                                              |
|-----------------------------------------------------------------------|-----------------------------------------------------------|
| Adding custom alert rule groups (`add:` in the diff)                  | Not in MVP. Schema reserves the shape.                    |
| Per-rule reset / undo button in the UI                                | Operator manages the diff via incremental edits for MVP.  |
| Multi-unit Prometheus support                                         | Hackathon constraint: 1 unit only.                        |
| Survival of edits across pod restart                                  | Now in scope by default — diff lives on shared PV per [ADR-0002](adr/0002-diff-storage.md). |
| Per-rule provenance comments in `.rules` files                        | Skip for MVP; revisit if debugging hurts.                 |
| Authentication on the UI                                              | Inherits Prometheus exposure for MVP.                     |
| Editing scrape configs, Alertmanager routes, recording rules          | Out of scope, separate features.                          |

## User stories (MVP)

1. **Silence a noisy upstream alert.** Operator opens the UI, finds `AlwaysFiringDueToAbsentMetric`, clicks "remove", saves. Within one reconcile cycle (≤5 min, or sooner if a charm event fires), the rule stops being evaluated.
2. **Tighten an alert for my environment.** Operator edits `HostDown`'s `for:` from `10m` to `40m` and bumps `severity:` to `critical`. Change persists for the life of the pod.

## What "ready for demo" means

- [ ] A second container (`alerts-editor`) is part of the Prometheus pod and serves a UI on a known port.
- [ ] The UI lists every alert currently loaded by Prometheus, with editable fields for `for`/`expr`/`labels`/`annotations` and a "remove" button per row.
- [ ] Save generates a YAML diff conforming to [ADR-0006](adr/0006-diff-document-schema.md) and writes it to `/etc/prometheus/rules/diff.yaml` on the shared rules storage.
- [ ] The charm reads the diff (pulled via Pebble from the Prometheus container), applies it to relation-supplied rules in `_set_alerts`, and writes the merged result.
- [ ] Demo path: remove one alert in the UI, patch another, trigger reconcile (`juju run prometheus-k8s/0` of anything that fires `config-changed`, or wait for `update-status`), confirm via Prometheus's own Alerts page that the changes took effect.

## Architecture sketch (MVP)

```
+--------------------------- Prometheus pod (1 unit) ---------------------------+
|                                                                               |
|         +============== shared Juju storage: rules ==============+            |
|         | /etc/prometheus/rules/                                  |            |
|         |   juju_<topo-1>.rules     (written by charm)            |            |
|         |   juju_<topo-2>.rules     (written by charm)            |            |
|         |   diff.yaml               (written by UI, read by charm)|            |
|         +=========================================================+            |
|              ^               ^               ^                                 |
|              | mounted       | pebble-pull   | mounted                         |
|              | r/w           | (charm-ops)   | r/o                             |
|              |               |               |                                 |
|   +----------+----+   +------+--------+   +--+-----------------+               |
|   | alerts-editor |   | charm/ops     |   | prometheus         |               |
|   | container     |   | container     |   | container          |               |
|   |               |   |               |   |                    |               |
|   | reads:        |   | _set_alerts:  |   | loads rules from   |               |
|   |  juju_*.rules |   |  - read base  |   | juju_*.rules; on   |               |
|   |  diff.yaml    |   |    from       |   | reload, re-parses  |               |
|   |               |   |    relations  |   | the directory      |               |
|   | writes:       |   |  - read diff  |   |                    |               |
|   |  diff.yaml    |   |    via pebble |   |                    |               |
|   |               |   |  - merge +    |   |                    |               |
|   |               |   |    promtool   |   |                    |               |
|   |               |   |  - push files |--->|  (pebble-push)    |               |
|   +-------+-------+   +---------------+   +--------------------+               |
|           ^                                                                    |
|           | HTTP from operator's browser                                       |
+-----------|--------------------------------------------------------------------+
            |
         browser
```

Trigger for the charm reconcile is whichever Juju event fires next — `update-status` (every ~5 min), or any other (relation change, config change, action). For the demo, force a reconcile manually if needed.

Note: per [ADR-0005](adr/0005-charm-merge-pipeline.md), `_set_alerts` wipes `juju_*.rules` selectively (never `diff.yaml`) at the start of each reconcile, then writes new merged files.

## Cross-cutting open questions

- **Image source for the UI container.** Build a Dockerfile in this repo and push to ghcr? Use a public Python base and ship the app in the charm? Decision affects [ADR-0004](adr/0004-ui-workload-design.md).
- **What's the "reset" story** if the diff itself becomes corrupted? Hackathon answer: `kubectl exec` and delete the file. Post-hackathon answer needs a `juju run` action.
- **Non-goal becomes a goal**: edits now survive pod restart for free because the diff is on a PV ([ADR-0002](adr/0002-diff-storage.md)). The non-goals table mentions this as deferred — strike that row post-MVP review.
