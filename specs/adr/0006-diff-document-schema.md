# ADR 0006 — Diff document schema (MVP)

**Status:** Proposed (shared contract between UI and charm)
**Date:** 2026-05-13
**Related:** [spec/0001](../0001-alerts-editor.md), [ADR-0004](0004-ui-workload-design.md), [ADR-0005](0005-charm-merge-pipeline.md)

## Context

The diff document is the contract between the UI workload ([ADR-0004](0004-ui-workload-design.md)) and the charm-side merge code ([ADR-0005](0005-charm-merge-pipeline.md)). Whatever we pin here becomes load-bearing for both teams immediately, and harder to change once code starts referring to it.

Starting point — the sketch from the feature brief:

```yaml
remove:
  - match:
      alert: AlwaysFiringDueToAbsentMetric

patch:
  - match:
      alert: HostDown
    set:
      for: 40m
      labels:
        severity: critical
      annotations:
        summary: Testingggggggg
        bruh: bruhhhhh

add:
  groups:
    - name: custom
      rules:
        - alert: MyNewRule
          ...
```

MVP excludes `add:` ([spec/0001](../0001-alerts-editor.md) non-goals). The schema *reserves* the shape so a future v1.x can ship it without a bump.

## Domain primer

A Prometheus rule file is a list of rule groups; each group has a `name` and a list of `rules`; each rule has either `alert:` (alerting rule) or `record:` (recording rule). Identity of an alerting rule is **not** uniquely defined by Prometheus itself — the same `alert:` name can appear in multiple groups with different label sets.

This means `match:` is doing two jobs: **identifying** which rules to act on, and (potentially) **scoping** the action to one producer's rules.

## Decisions (MVP)

### D1. Match semantics

For MVP, `match:` accepts a single key: `alert:` (the alert name). No label selectors, no group scoping, no topology scoping.

- ✅ Simplest possible. Covers the demo use cases.
- ❌ Ambiguous when two producers ship rules with the same name. **Handling**: UI displays a warning on such rows and disables editing/removal; charm-side `apply_overlay` treats `match` resolving to >1 rule as a hard error (`OverlayError("ambiguous match: N rules named X")`).

Post-MVP: add `labels:` (subset match) and `producer:` (Juju topology) keys.

### D2. `set:` merge semantics

- Top-level scalars (`for`, `expr`) are **replaced**.
- `labels` and `annotations` are **deep-merged** by key (existing keys not mentioned in `set` survive).

No `unset:` field in MVP — operators who want to drop a label can patch it to an empty string or wait for v1.x.

### D3. When `match` selects nothing

Apply nothing for that operation, log a warning, surface in status (`ActiveStatus("overlay: N selectors matched nothing")`). Not an error — likely an upstream rename.

### D4. When `match` is ambiguous (matches multiple rules)

Hard error from the charm-side merge; status goes to `BlockedStatus`. UI prevents this case at edit time (D1).

### D5. Order of operations

`remove` is applied before `patch`. A patched-then-removed rule is removed; a removed rule cannot be patched (patch becomes a no-op-warning per D3).

### D6. Conflict between two `patch` entries

Two patches whose `match` resolves to the same rule → schema validation error at the UI (the UI consolidates inline), and a hard error at the charm side as a defence-in-depth check.

### D7. Schema versioning

Top-level `schemaVersion: 1`. Charm refuses to apply mismatched versions with a clear error.

### D8. `add:` block

Reserved in the schema, not implemented in MVP. The charm-side validator rejects non-empty `add:` with `OverlayError("'add' is not yet implemented")`. This way a user pasting a hand-written diff with `add:` gets a clean error, not a silent drop.

## Canonical schema (v1, MVP)

```yaml
schemaVersion: 1

remove:
  - match:
      alert: <alert-name>            # required, only key supported in MVP

patch:
  - match:
      alert: <alert-name>            # required
    set:                             # at least one of: for / expr / labels / annotations
      for: <duration>
      expr: <promql>
      labels:                        # deep-merged into existing labels
        <key>: <value>
      annotations:                   # deep-merged into existing annotations
        <key>: <value>

add:                                 # RESERVED; non-empty value rejected in MVP
  groups: []
```

Both `remove:` and `patch:` are optional; omitting them is equivalent to `[]`.

## Consequences

- A Python dataclass (or pydantic model) implementing this schema lives in `src/alerts_overlay.py` and is shared with the UI workload code path (either copy-paste or shared module — for MVP, copy-paste with a comment is fine).
- The UI must enforce D1 (single key in `match`), D4 (no ambiguous edits), and D6 (no conflicting patches) at edit time so the saved file is always charm-valid.
- The charm enforces the same checks as a backstop — UI is not trusted to be a perfect validator.
- Round-trip: load `diff.yaml`, mutate via UI, save — must produce a byte-for-byte equivalent document if the operator made no changes. Snapshot tests recommended.

## Open questions

- Reserve a `metadata:` block now (author/timestamp/reason per operation) so we don't have to add it via a schema bump? Cheap to reserve, useful for support.
- Should `unset:` make it into v1 or wait for v1.x? If two of the three hackathon hours have a "demo wants to drop a label" moment, it's worth a tiny extra hour to add.
- For `add:` post-MVP: must group `name:` be globally unique, or can operators add rules to an existing producer's group? Unique is simpler and avoids ownership conflicts; recommend pinning that now.
- Do we forbid the diff from mutating Juju-injected labels (`juju_application`, `juju_unit`, etc.)? Probably yes; small denylist in the validator. Cheap to add at MVP time.
