# Specs

High-level specifications and architecture decision records (ADRs) for in-flight work on the Prometheus K8s charm.

## Scope context

These docs cover an **8-hour hackathon** scoped to a single Prometheus unit. We've deliberately punted on multi-unit coordination, HA, and several nice-to-haves; flagged inline where relevant. Post-hackathon ADRs should supersede the accepted ones rather than edit them.

## Layout

```
specs/
├── README.md                                ← you are here
├── 0001-alerts-editor.md                    ← feature spec
└── adr/
    ├── 0001-packaging-sidecar-vs-separate-charm.md   ← shared
    ├── 0002-diff-storage.md                 ← shared (charm-leaning)
    ├── 0003-ui-to-charm-transport.md        ← UI ↔ charm contract
    ├── 0004-ui-workload-design.md           ← UI-only
    ├── 0005-charm-merge-pipeline.md         ← charm-only
    └── 0006-diff-document-schema.md         ← shared contract
```

ADRs 0004 and 0005 are intentionally split so the two of you working on the UI workload and the one working on the charm-side merge can iterate without stepping on each other; ADR-0006 is the contract between them.

## Status legend

- **Proposed** — drafted, awaiting team review.
- **Accepted** — agreed, in or about to be implemented.
- **Superseded by NNNN** — replaced; see the linked ADR for the current decision.
- **Rejected** — considered and declined; kept for posterity.

## Conventions

- One decision per ADR. If two decisions are tightly coupled, split them and cross-link in **Consequences**.
- The "Options considered" section is the part to grill. Anything that lands in **Decision** without being weighed against at least one alternative is suspect.
- Each ADR ends with **Open questions** — these are the explicit hand-offs to the next round of design.
- Update — don't rewrite — accepted ADRs. If the decision changes, add a new ADR that supersedes the old one.
