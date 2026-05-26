# ADR 0002 — Diff document storage location

**Status:** Accepted (hackathon) — shared Juju storage mounted in both containers; diff at `/etc/prometheus/rules/diff.yaml`
**Date:** 2026-05-13
**Supersedes:** prior draft proposing UI-container-local storage
**Related:** [ADR-0001](0001-packaging-sidecar-vs-separate-charm.md), [ADR-0003](0003-ui-to-charm-transport.md), [ADR-0005](0005-charm-merge-pipeline.md)

## Context

The diff document is the only piece of operator-authored state in the feature. We need a single location for it that:

- the UI workload can write to,
- the charm can read at reconcile time,
- **and is the same place the UI reads base rules from**, since per the team's design the UI must NOT depend on Prometheus's HTTP API.

The base rules already exist at `/etc/prometheus/rules/juju_<topology>.rules` inside the Prometheus container (written by [`_push_alert_rules`](../../src/charm.py#L823)). Putting the diff at `/etc/prometheus/rules/diff.yaml` and making the whole directory a shared mount gives both containers a single rendezvous point.

## Decision

**Add a new Juju `storage:` entry, mount it in both the `prometheus` and `alerts-editor` containers at `/etc/prometheus/rules/`.**

```yaml
# charmcraft.yaml (sketch)
storage:
  rules:
    type: filesystem
    location: /etc/prometheus/rules
containers:
  prometheus:
    resource: prometheus-image
    mounts:
      - storage: database
        location: /var/lib/prometheus
      - storage: rules
        location: /etc/prometheus/rules
  alerts-editor:
    resource: alerts-editor-image
    mounts:
      - storage: rules
        location: /etc/prometheus/rules
```

Contents of the shared mount:

```
/etc/prometheus/rules/
├── juju_<topology-1>.rules     ← written by charm from relation data
├── juju_<topology-2>.rules     ← written by charm from relation data
├── ...
└── diff.yaml                    ← written by UI; read by charm
```

- **UI workload** reads `juju_*.rules` to discover the rules currently loaded by Prometheus, and writes `diff.yaml` on save.
- **Charm** reads `diff.yaml` at reconcile time (via Pebble pull on the Prometheus container, since the charm-ops container does not mount the storage).
- **Prometheus** continues to read `juju_*.rules` for evaluation. Prometheus ignores `diff.yaml` because [`prometheus.yml`](../../src/charm.py#L1086) globs only `juju_*.rules`.

## Options considered

### S1. Shared Juju storage at `/etc/prometheus/rules/` *(chosen)*

- ✅ Single source of truth that both containers can read directly via the filesystem — UI doesn't need the Prometheus HTTP API.
- ✅ Survives pod restart (PV-backed).
- ✅ Diff sits next to the rule files it describes — co-located, easy to debug from `kubectl exec`.
- ❌ The existing rules-dir wipe in `_set_alerts` must be made selective (wipe only `juju_*.rules`, preserve `diff.yaml`). See [ADR-0005](0005-charm-merge-pipeline.md).
- ❌ Slightly more `charmcraft.yaml` plumbing than a container-local file.

### S2. UI-container-local file (`/data/diff.yaml`)

- ✅ Zero `charmcraft.yaml` changes for storage.
- ❌ UI cannot read base rules from disk (different container's filesystem), forcing it to call Prometheus's HTTP API — which the team explicitly does not want.
- ❌ Diff lost on pod recreation.

### S3. Sub-path of existing `database` storage

- ✅ Survives pod recreation; no new storage entry needed.
- ❌ Mixes overlay state with Prometheus's TSDB on the same volume; couples concerns that should stay separate.
- ❌ Still requires mounting in the UI container, so no plumbing win over S1.

### S4. Peer relation app data

- ✅ Survives everything; controller-state backed.
- ❌ UI cannot read/write peer data directly; needs charm-mediated transport — re-introduces the coupling we want to avoid.
- ❌ Doesn't solve the UI's "where do I read base rules from?" question at all.

## Consequences

- `charmcraft.yaml` gains a new `storage.rules` entry of type `filesystem`, mounted in both `prometheus` and `alerts-editor`.
- The Prometheus container's rules dir is now on a PV. This is a behavioural shift from today (where it's ephemeral), but harmless: the charm regenerates `juju_*.rules` on every reconcile from relation data, so PV-backing them changes nothing operational.
- The charm's `_set_alerts` must do a **selective wipe** — `juju_*.rules` only, never `diff.yaml`. Tracked in [ADR-0005](0005-charm-merge-pipeline.md) D1.
- The charm reads `diff.yaml` via `self.container.pull("/etc/prometheus/rules/diff.yaml")` on the Prometheus container (existing Pebble pattern in the codebase).
- The UI reads `/etc/prometheus/rules/juju_*.rules` from its own filesystem (same shared mount) and writes `diff.yaml` to the same location.
- Atomic writes from the UI: write to `diff.yaml.tmp` and rename, so the charm never reads a half-written file.

## Open questions

- Does the new `storage.rules` entry need any explicit size budget? Juju storage defaults are usually fine for a directory of YAML files (KB-scale), but worth a `minimum-size: 1M` or similar to make intent explicit.
- The Prometheus container creates `/etc/prometheus/rules/` today as part of its image; mounting a storage there should override that. Verify with a `juju deploy` smoke test early — Juju storage mounts have occasional sharp edges around pre-existing directories.
- Multi-unit (post-hackathon): per-unit PV → diffs would diverge. The shared-storage model breaks once we scale; needs a peer-relation sync or single-leader-write model. Tracked for post-hackathon.
