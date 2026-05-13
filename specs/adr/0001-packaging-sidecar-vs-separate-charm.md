# ADR 0001 — Packaging: sidecar container vs. separate charm

**Status:** Accepted (hackathon) — Option A: sidecar container in the Prometheus pod
**Date:** 2026-05-13
**Related:** [spec/0001](../0001-alerts-editor.md), [ADR-0002](0002-diff-storage.md), [ADR-0003](0003-ui-to-charm-transport.md)

## Hackathon decision summary

For the 8-hour hackathon we ship the UI as a **second container in the Prometheus pod** of *this* charm — `charmcraft.yaml` gains a `containers.alerts-editor` entry and a corresponding `resources.alerts-editor-image`. The pod becomes:

```
prometheus pod
  ├── prometheus container       (existing)
  ├── alerts-editor container    (new)
  └── ops/charm container        (Juju-managed)
```

The full options analysis below is preserved for the post-hackathon review.

---

## Context

The Alerts Editor needs (a) a long-running UI workload and (b) read/write access to the operator's diff document, which the Prometheus charm consumes to mutate alert rules before writing them to disk.

There are three plausible homes for the UI:

1. **Second container in the Prometheus pod** of *this* charm (adds a `containers:` entry alongside `prometheus` in [`charmcraft.yaml`](../../charmcraft.yaml#L62)).
2. **Separate charm** in its own pod, related to Prometheus over a new Juju relation.
3. **In-process inside the charm** (the charm itself serves the UI). Listed for completeness; mentioned and dismissed below.

This decision is load-bearing for everything else — it determines the storage model for the diff, the transport between the UI and the charm, the deployment story, and the upgrade story.

## Options considered

### Option A — Second container in the same pod

The UI runs as a Pebble-managed workload in this charm's pod. The diff document lives on a shared volume (or is mediated through the charm via files / Pebble exec / Unix socket).

**Pros**

- Single deployment artifact. Operators get the editor by upgrading; no extra `juju deploy`, no extra relation.
- Co-located filesystem — the UI can read `/etc/prometheus/rules/` directly to render the current state, and the diff lives on the same pod as the consumer of the diff.
- No new relation interface to design, version, and stabilise.
- Matches how Grafana ships its bundled dashboards: one charm, one user-facing thing.

**Cons**

- Couples the UI's release cadence to the Prometheus charm's. A UI-only bug fix means cutting a Prometheus charm revision.
- The pod gets fatter — bigger image pull, more memory baseline, more attack surface even for operators who don't use the editor.
- No native way to disable the UI per-deployment without a config option that gates the Pebble service (extra code, extra states).
- Pod-level resource limits ([`config: cpu/memory`](../../charmcraft.yaml#L233)) now have to be split across two workloads — surprising UX.
- Multi-unit: every Prometheus unit ships a UI. Which one do operators talk to? (Picked up in ADR-0002.)

### Option B — Separate charm

A new `prometheus-alerts-editor-k8s` charm. It relates to `prometheus-k8s` over a new interface (e.g. `prometheus_alerts_overlay`). The diff travels over relation data, or both charms read/write it via a shared backend.

**Pros**

- Independent release cadence and lifecycle. The editor can ship 4.6 while Prometheus is on 4.5.
- Operators who don't want it never deploy it; zero footprint on the base charm.
- Forces a clean API boundary (the relation interface), which is healthier long-term than a shared filesystem.
- Matches existing COS patterns (`scrape-config-k8s`, `scrape-target-k8s`, `catalogue-k8s`).

**Cons**

- Two charms to deploy, relate, document, test, and renovate.
- Diff transport over relation data has size limits and event-storm risks (every UI save is a relation-changed event on Prometheus).
- The UI cannot directly observe Prometheus's filesystem; everything must come over an API or relation data.
- HA story: do you scale the editor charm? Single-unit by design? Either way it's a new constraint to communicate.
- More moving parts during incidents (which charm is the source of truth for the diff?).

### Option C — Serve UI from the charm process (rejected)

The charm code itself opens a port and serves the UI from within the Operator pod. Rejected because:

- Charms are event-driven; running a long-lived HTTP server from inside `ops` is anti-pattern and fragile across charm restarts.
- The charm container has no business serving operator-facing traffic.
- Loses K8s-native lifecycle (no Pebble layer, no liveness/readiness, no resource limits).

## Decision (hackathon)

**Option A.** Rationale:

- One deployment artifact. The hackathon team can iterate locally with `charmcraft pack && juju refresh` — no second charm, no new relation interface to design.
- The UI container has trivial access to the charm via Pebble (the charm-side code already uses Pebble for the Prometheus container).
- For 1 unit, the "which unit's UI is authoritative" problem (the main Option B selling point) doesn't exist.
- The cons of Option A (release coupling, fatter pod) are real but acceptable for 8 hours.

## Consequences

- [`charmcraft.yaml`](../../charmcraft.yaml#L62) gains:
  - `containers.alerts-editor` mounting the new shared `rules` storage at `/etc/prometheus/rules/` ([ADR-0002](0002-diff-storage.md)).
  - `resources.alerts-editor-image` with an `upstream-source` once we have a published image.
  - A new `storage.rules` entry, also mounted in the existing `prometheus` container at `/etc/prometheus/rules/`.
- The charm gains a new Pebble layer for the `alerts-editor` service and pulls `/etc/prometheus/rules/diff.yaml` from the Prometheus container at reconcile time ([ADR-0003](0003-ui-to-charm-transport.md)).
- Existing CPU/memory config options ([`charmcraft.yaml`](../../charmcraft.yaml#L233)) still apply only to the Prometheus container; UI container limits are hard-coded or omitted for MVP.
- We do **not** add a `enable_alerts_editor` config option in MVP; the UI is always on. Toggle is post-hackathon.

## Deferred to post-hackathon

- Should this be a separate charm long-term? The Option B analysis below still applies — revisit once the MVP proves the UX is worth investing in.
- Off-by-default config toggle for the UI service.
- Ingress sub-path routing for the UI so it sits behind the same external URL as Prometheus.
- Renovate config for the second image.

## Open questions

- Image source: build a slim Python image in-tree (Dockerfile + GitHub Action) or piggyback on an existing public base at runtime? Affects ADR-0004.
- Container ordering / readiness: does the charm need to wait for `alerts-editor` pebble-ready before its first reconcile? Probably not — the merge logic must already handle a missing/empty diff file.
