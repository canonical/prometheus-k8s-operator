# ADR 0003 — UI ↔ charm transport and reconcile signaling

**Status:** Accepted (hackathon) — file write + `update-status` polling
**Date:** 2026-05-13
**Related:** [ADR-0001](0001-packaging-sidecar-vs-separate-charm.md), [ADR-0002](0002-diff-storage.md), [ADR-0005](0005-charm-merge-pipeline.md)

## Context

When the operator clicks "save" in the UI, two things must happen:

1. **The new diff bytes must be visible to the charm** (covered by [ADR-0002](0002-diff-storage.md): file at `/etc/prometheus/rules/diff.yaml` on the shared rules storage).
2. **The charm must run `_set_alerts` again so the change reaches Prometheus.** That's the subject of this ADR — what tells the charm "go reconcile"?

Juju charms react to events, not file watches. Without a signal, a saved diff sits unread until some other event fires.

Because the diff lives on the shared `rules` storage ([ADR-0002](0002-diff-storage.md)), the charm reads it via Pebble pull on the **Prometheus** container (which already mounts the storage), not the UI container.

## Options considered

### T1. UI writes file; charm reads it on the next reconcile triggered by `update-status`

`update-status` fires every ~5 min by default. No new plumbing required.

- ✅ Zero new code for the signal path — every charm already observes `update-status`.
- ✅ No coupling between the UI and the charm beyond the shared file location.
- ❌ Up to ~5 min latency between save and effect. Demo cadence requires a manual reconcile prod (`juju run prometheus-k8s/0 validate-configuration` or a config-changed) to feel snappy.

### T2. UI fires a Pebble custom notice; charm observes `pebble-custom-notice`

Charm gets the event immediately; calls `_set_alerts`. Low-latency, idiomatic ops mechanism.

- ✅ Sub-second latency. Looks like magic in a demo.
- ✅ Pebble notices are persistent across Juju event delivery, so saves don't get dropped.
- ❌ The UI container needs to talk to Pebble. The Pebble socket on each container is per-container; firing a notice on its own container's Pebble emits a workload-level event the charm sees. Workable but not zero-effort.
- ❌ Adds an extra observer + handler in `charm.py`.

### T3. UI calls a Juju action

UI shells out to `juju run prometheus-k8s/0 apply-overlay` (or has the operator click "save" in the UI then run the action manually).

- ✅ Explicit, auditable.
- ❌ Coupling the UI to the `juju` CLI is awkward — the UI workload doesn't have a Juju agent or credentials. Operator-runs-the-action is bad UX.

### T4. UI calls Prometheus `/-/reload` directly after writing rule files itself

Bypasses the charm entirely on the hot path.

- ✅ Lowest possible latency.
- ❌ Requires the merge logic in the UI workload as well as the charm. Two places of truth.
- ❌ The charm's next reconcile will overwrite whatever the UI wrote, since it regenerates rule files from scratch.
- ❌ Wrong layering: workloads shouldn't reach across into other workloads' state.

## Decision (hackathon)

**T1 — file write + `update-status` polling.** Accepted with full awareness that demo latency requires a manual nudge.

Rationale: the user explicitly picked the lowest-plumbing option for the hackathon. The ~5 min worst-case latency is irrelevant for a demo where we can force a reconcile by running any action, refreshing config, or restarting the unit. T2 is the natural post-hackathon upgrade.

## Consequences

- `_set_alerts` is the only consumer of the diff file. It pulls `/etc/prometheus/rules/diff.yaml` from the Prometheus container via Pebble, applies, returns whether anything changed. No new event observers added.
- The demo script needs a "force a reconcile now" step. Suggested approaches, in order of cheapness:
  1. Bump a config option (e.g. flip `log_level` and flip back).
  2. Run the existing `validate-configuration` action — it doesn't trigger reconcile by itself, so this doesn't actually work. Strike.
  3. `juju refresh` the charm to its own revision (overkill but reliable).
  4. Just wait up to 5 min.
- The UI must communicate save success purely from its own perspective ("diff written to /etc/prometheus/rules/diff.yaml"). It cannot wait for the charm to ack — there is no return channel.

## Defer for post-hackathon

- **Upgrade to T2 (Pebble notice).** Same file storage, add `pebble-custom-notice` observer in the charm and a one-liner in the UI. Closes the latency gap without changing the data model.
- **Status feedback in the UI** ("last applied at HH:MM:SS"). Requires the charm to write a small ack file the UI can read.
- **Save rate-limit.** If an operator hammers save, T1 doesn't care (each save is just a file overwrite). T2 would care — needs debouncing.

## Open questions

- For the demo, do we want a hard-coded shorter `update-status` interval (`juju model-config update-status-hook-interval=30s`)? Trades demo snappiness for log noise. Probably yes for the demo window.
- If the diff file is malformed when the charm reads it, what's the UI-visible feedback path? In T1 there is none — operator only sees the bad state by checking `juju status`. Post-hackathon item.
