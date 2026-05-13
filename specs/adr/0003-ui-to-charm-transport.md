# ADR 0003 — UI ↔ charm transport and reconcile signaling

**Status:** Accepted (revised 2026-05-13) — T2: Pebble custom notice from UI to alerts-editor container
**Supersedes:** prior decision T1 (file write + `update-status` polling)
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

## Decision (revised)

**T2 — Pebble custom notice from the UI to the alerts-editor container.**

Concretely:

- The UI atomically writes `/etc/prometheus/rules/diff.yaml` (tmp + rename).
- On a successful rename, the UI fires `pebble notify canonical.com/alerts-overlay/changed` on its own container's Pebble socket (the `pebble` binary is on PATH in any Pebble-managed container; `PEBBLE_SOCKET` is inherited from the Pebble parent process).
- The charm observes `self.on[ALERTS_EDITOR_CONTAINER].pebble_custom_notice` and, on the matching notice key, calls `_configure` — which already calls `_set_alerts`, which already reads `diff.yaml`.

Rationale for the flip from T1: the polling latency (up to 5 min) is unacceptable for the demo UX, and once we sketched the change it turned out to be ~10 lines split across the UI (one `subprocess.run`) and the charm (one observer + handler) — much smaller than the original ADR feared. The "polling is zero plumbing" advantage evaporates against "notices are also nearly zero plumbing, and an order of magnitude faster".

The pre-overlay behaviour of `_update_status` (only reconcile when the unit isn't `Active`, to recover from stuck WAL replays / ingress-not-yet-ready) is restored. `_update_status` no longer participates in overlay propagation at all.

## Consequences

- `_set_alerts` remains the only consumer of the diff file; it pulls `/etc/prometheus/rules/diff.yaml` from the Prometheus container via Pebble. The change is the *trigger*, not the consumer.
- A new observer is added to the charm — `self.on[ALERTS_EDITOR_CONTAINER].pebble_custom_notice` → `_on_alerts_overlay_changed`. The handler is a key-check + delegation to `_configure`.
- The notice key `canonical.com/alerts-overlay/changed` becomes part of the implicit contract between the UI workload and the charm. Document it as a constant in both codebases (`ALERTS_OVERLAY_NOTICE_KEY` in `charm.py`; a matching constant in `src/ui/app.py`).
- `_update_status` reverts to the original `if self.unit.status != ActiveStatus(): self._configure(event)` — no longer the overlay-propagation hook.
- If a notice fires while a reconcile is in flight, Juju's hook serialisation queues the next one — no concurrency concerns.
- Pebble notices persist until acked by the framework, so a notice fired during a brief charm outage is not lost.
- No demo "force a reconcile" step is needed any more; saves take effect sub-second.

## Defer for post-hackathon

- **Status feedback in the UI** ("last applied at HH:MM:SS"). Requires the charm to write a small ack file the UI can read; meaningful now that saves trigger immediate reconciles and operators can see effect promptly.
- **Save rate-limit / debounce.** With T1 each save was a cheap file overwrite; with T2 each save also schedules a charm reconcile. Hammering save can therefore queue reconciles. Add a small debounce in the UI (e.g. 200 ms) if this turns out to matter in practice.

## Open questions

- If the `pebble` binary is absent or `PEBBLE_SOCKET` is unset for any reason, the UI's `_notify_charm` becomes a silent no-op. Do we want a one-line health check at UI startup that logs a warning if `pebble notify` fails a dry-run? Cheap to add, prevents silent regressions.
- If the diff file is malformed when the charm reads it, what's the UI-visible feedback path? Still no return channel under T2 — operator only sees the bad state by checking `juju status`. Tracked as a post-hackathon item alongside the "last applied at" status feedback.
