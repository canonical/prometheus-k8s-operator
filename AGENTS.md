# AGENTS.md

Guidance for coding agents working in this repository.

## What this repo is
- Upstream workload source: https://github.com/prometheus/prometheus
- Charm repo: https://github.com/canonical/prometheus-k8s-operator

## Branches, tracks, and channels

- `main` ships Prometheus 3.14 (`prometheus-image` tag `3.14-26.04` in `charmcraft.yaml`). Pushes to `main` release to the `dev` track (`latest/edge`).
- `track/3.11` ships Prometheus 3.11 (`prometheus-image` tag `3.11-26.04`). Pushes to `track/3.11` release to the `3.11` track.
- Any `track/X` branch releases to track `X`.
- To find the workload version on a branch, read the `prometheus-image` entry in `charmcraft.yaml`, specifically the `# renovate: oci-image tag:` comment.
- Branches differ in `pyproject.toml`, `uv.lock`, and `charmcraft.yaml`. Do not copy dependency or build changes between branches without checking both.

## Workload questions

When a question depends on Prometheus behavior (flags, config fields, rule semantics, TSDB, remote write, HTTP API, defaults), and the answer is not clear from this repo, check the upstream source at https://github.com/prometheus/prometheus at the release tag matching the branch's version (`v3.14.x` for `main`, `v3.11.x` for `track/3.11`). Do this only when necessary; do not guess from memory.

## Required checks

- After any change that adds, changes, or fixes logic (under `src/`, `lib/charms/`, `tests/`, or to `charmcraft.yaml`, `tox.ini`, `pyproject.toml`, `uv.lock`), run `tox` from the repo root and confirm it succeeds before reporting the work as done.
- `tox -e fmt` auto-fixes ruff issues. Run it if `lint` fails on fixable rules, then rerun `tox`.
- Docs-only changes (`*.md`) do not need `tox`.
- If you change any file under `lib/charms/prometheus_k8s/`, bump its `LIBPATCH` (or `LIBAPI` for breaking changes). `tox -e static` fails otherwise. Never directly change a library when on a branch other than main.
- `tox -e unit` downloads `cos-tool-amd64` on first run, so it needs network access.
- Do not run `tox -e integration` or `tox -e interface` unless asked. They are not part of default `tox`.

## Code conventions

- Python 3.14 (`requires-python = "~=3.14.0"`). Pyright checks `src/` as Python 3.10 and `lib/charms/prometheus_k8s/` as Python 3.8, so library code must stay 3.8-compatible. Match the existing typing style in each lib file.
- Ruff: line length 99, Google docstring convention, `D` rules enabled. Tests are exempt from some `D` rules (see `pyproject.toml`).
- Dependencies are locked in `uv.lock` and installed through `tox` with `--frozen`. Do not run `uv lock` or `tox -e lock` unless asked.
- Unit tests use the ops/scenario harness. `tests/unit/conftest.py` patches the lightkube client, the Prometheus reload call, and `promtool` checks, so unit tests need no cluster.
- Follow existing patterns in the codebase. Do not introduce a second pattern for the same thing.
- Read `CONTRIBUTING.md` and `RELEASE.md` before changing contribution or release process.
