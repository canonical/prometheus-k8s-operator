# ADR 0005 — Charm-side merge and apply pipeline

**Status:** Proposed (charm-side concern)
**Date:** 2026-05-13
**Related:** [spec/0001](../0001-alerts-editor.md), [ADR-0002](0002-diff-storage.md), [ADR-0003](0003-ui-to-charm-transport.md), [ADR-0006](0006-diff-document-schema.md)

## Context

The existing alerts pipeline in [`_set_alerts`](../../src/charm.py#L805):

1. Pulls rule dicts from `self.metrics_consumer.alerts` and `self.remote_write_provider.alerts`.
2. Hashes the combined input.
3. If the hash changed, wipes `/etc/prometheus/rules/` and rewrites `juju_<topology>.rules` files via [`_push_alert_rules`](../../src/charm.py#L823).
4. Returns whether anything changed, so the caller knows whether to reload Prometheus.

We need to slot a merge step between (1) and (2) that reads the diff (per [ADR-0002](0002-diff-storage.md)) and applies it. Everything else stays the same — change-detection works automatically because the merged output flows through the existing hash.

This ADR covers only what the charm does. UI behaviour is in [ADR-0004](0004-ui-workload-design.md); the diff schema is in [ADR-0006](0006-diff-document-schema.md).

## Decisions

### D1. Merge location & selective wipe

Modify `_set_alerts` to:

```
base_rules = { **metrics_consumer.alerts, **remote_write.alerts }   # dict[topology] -> rules_file
diff_yaml = self.container.pull("/etc/prometheus/rules/diff.yaml")  # may not exist
diff = load_diff(diff_yaml) if diff_yaml else None
merged = apply_overlay(base_rules, diff)                            # returns dict[topology] -> rules_file
alerts_hash = sha256(str(merged))
if alerts_hash != self._pull(ALERTS_HASH_PATH):
    selectively wipe juju_*.rules files only (NEVER diff.yaml)
    push per-topology files; update hash
```

For MVP (no `add:`), `merged` has the same key set as `base_rules`. Per-topology files keep their existing names. No new `juju_overlay_add.rules` file in MVP.

**Critical change to the existing wipe behaviour.** Today's code does:

```python
self.container.remove_path(RULES_DIR, recursive=True)   # charm.py:816
```

This would wipe `diff.yaml`, which lives in the same directory ([ADR-0002](0002-diff-storage.md)). Replace with a selective remove that only targets files matching `juju_*.rules`:

```python
for f in self.container.list_files(RULES_DIR, pattern="juju_*.rules"):
    self.container.remove_path(f.path)
```

No file outside `juju_*.rules` is ever touched by the wipe. `diff.yaml` is operator-owned and only ever written by the UI.

### D2. Where the merge code lives

A new module `src/alerts_overlay.py`:

- `load_diff(yaml_str) -> Diff` — parse + schema-validate (raises `OverlayError` on failure).
- `apply(base: dict, diff: Diff) -> dict` — returns merged rules dict; pure function, no I/O.
- `OverlayError` — single exception type the charm catches.

Pure-function design means unit tests don't need Pebble or any charm scaffolding.

### D3. Reading the diff

The diff lives on the shared `rules` storage, which is mounted in both the `prometheus` and `alerts-editor` containers. The charm reads it from the **Prometheus** container (the same one it already pebble-interacts with for rule files):

```python
def _read_diff(self):
    container = self.container  # the prometheus container
    if not container.can_connect():
        return None
    try:
        return container.pull("/etc/prometheus/rules/diff.yaml").read()
    except (PathError, ProtocolError):
        return None
```

A missing or unreadable file → `None` → no overlay applied. This is a valid state, not an error (no operator has saved anything yet).

### D4. Validation

Two layers:

1. **Schema validation** at `load_diff` (cheap, Python-side).
2. **`promtool check rules`** on the merged rules directory before declaring success. We already have [`_promtool_check_config`](../../src/charm.py); a sibling `_promtool_check_rules` is straightforward.

For MVP, run promtool **after** writing files (since promtool operates on files), inside a try/finally that restores the previous good state on failure. Acceptable because Prometheus only reloads on success.

### D5. Failure handling

- **Schema invalid** → log error, set `_stored.status["overlay"] = BlockedStatus("overlay schema invalid: ...")`, skip applying the diff (use base rules unchanged). Operator sees status; UI gets no signal (per [ADR-0003](0003-ui-to-charm-transport.md) limitations).
- **Match selectors hit nothing** → log warning, apply what can be applied. Operator sees status `ActiveStatus("overlay: 2 selectors matched nothing")`. Not blocking — likely an upstream rule rename.
- **promtool rejects merged output** → restore the previous rules files (we kept them in memory), set `BlockedStatus("overlay produces invalid rules: ...")`. Prometheus keeps loading the previous good ruleset.
- **UI container not connectable** → `_read_diff` returns `None`; behave as if no overlay. No status change.

### D6. Provenance in `.rules` files

Skip for MVP. Operators debugging will:

- Compare `juju_<topology>.rules` on disk to what their producer charm shipped (via `juju show-unit ... --format yaml | yq`).
- Or `cat /data/diff.yaml` in the UI container.

Post-hackathon: add a one-line comment at the top of each modified file naming which overlay operations touched it.

### D7. Status surface

Add `_stored.status["overlay"]: Tuple[str, str]` alongside the existing keys ([`charm.py`](../../src/charm.py#L121)). Surface via `_on_collect_unit_status`.

States the operator can see:

- `ActiveStatus()` — no overlay or overlay applied cleanly.
- `ActiveStatus("overlay: N selectors matched nothing")` — warning, not blocking.
- `BlockedStatus("overlay schema invalid: <message>")`.
- `BlockedStatus("overlay produces invalid rules: <promtool output>")`.

## Consequences

- New file `src/alerts_overlay.py` with pure-function merge logic, easily unit-tested.
- `_set_alerts` grows ~10 lines: read diff, call `apply`, set status on failure.
- **Existing rules-dir wipe is replaced with a selective `juju_*.rules`-only wipe** (D1). Single line of `_set_alerts` changes; tested behaviour: `diff.yaml` survives reconciles forever.
- New helper `_promtool_check_rules` mirroring the existing config check.
- New `_stored.status` key requires a one-line update to the `CompositeStatus` TypedDict and the `set_default` call in `__init__`.
- Hash logic unchanged because it hashes the merged output by construction.

## Open questions

- Where should `_read_diff` go? Inline in `_set_alerts` is fine for MVP; if it grows, lift to a method on the charm.
- For `promtool check rules` failure recovery, do we keep the previous-good files in memory (cheap, < 1 MB) or re-read them from disk before wipe? In-memory is simpler.
- Do we need to gate `apply_overlay` behind a config option (`enable_alerts_overlay`) for safety on existing deployments? For MVP no; post-hackathon yes (off by default for backwards compat).
- Selective wipe via `list_files(pattern=...)` — verify Pebble's `list_files` supports glob patterns; if not, fall back to listing all files and filtering in Python.
