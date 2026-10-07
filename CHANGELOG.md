# Changelog

Changes on `track/3.14` since the common ancestor with `track/3.11` (`572dddb`).

## Breaking Changes

- fix!: WAL compression config ([#862](https://github.com/canonical/prometheus-k8s-operator/pull/862))
- refactor!: Remove self-mon scrape job ([#868](https://github.com/canonical/prometheus-k8s-operator/pull/868))

## Features

- feat: rewrite feature files using Pytest BDD 8 ([#878](https://github.com/canonical/prometheus-k8s-operator/pull/878))
- feat: Alert Knob ([#857](https://github.com/canonical/prometheus-k8s-operator/pull/857))
- feat: enable out-of-order samples ([#865](https://github.com/canonical/prometheus-k8s-operator/pull/865))
- feat(lib): Remote write rule compression ([#864](https://github.com/canonical/prometheus-k8s-operator/pull/864))
- feat: ensure the Prom Scrape lib observes leader_elected ([#860](https://github.com/canonical/prometheus-k8s-operator/pull/860))
- feat: move invalid alert rules/scrape job helpers to Prom libs ([#851](https://github.com/canonical/prometheus-k8s-operator/pull/851))
- feat: blocked on invalid scrape jobs ([#849](https://github.com/canonical/prometheus-k8s-operator/pull/849))
- feat: source `cosTool` from cosl ([#846](https://github.com/canonical/prometheus-k8s-operator/pull/846))
- feat(tf): base input variable ([#842](https://github.com/canonical/prometheus-k8s-operator/pull/842))

## Fixes

- fix: Do not forward CA file over prometheus_scrape ([#876](https://github.com/canonical/prometheus-k8s-operator/pull/876))
- fix: Scrape jobs behind ingress ([#871](https://github.com/canonical/prometheus-k8s-operator/pull/871))
- fix: leader guard for _has_relation_error ([#852](https://github.com/canonical/prometheus-k8s-operator/pull/852))
- fix: Integration test_logging ([#840](https://github.com/canonical/prometheus-k8s-operator/pull/840))

## Others

- chore(deps): lock file maintenance ([#788](https://github.com/canonical/prometheus-k8s-operator/pull/788))
- chore: properly xfail test_workload_tracing ([1b4c3a6](https://github.com/canonical/prometheus-k8s-operator/commit/1b4c3a6b9189375da645f08ae8e8ad96ed18aae5))
- chore: bump ops version ([#872](https://github.com/canonical/prometheus-k8s-operator/pull/872))
- chore: bump prometheus workload to 3.14-26.04 ([#863](https://github.com/canonical/prometheus-k8s-operator/pull/863))
- chore: update charm libraries ([#858](https://github.com/canonical/prometheus-k8s-operator/pull/858))
- chore: update charm libraries ([#854](https://github.com/canonical/prometheus-k8s-operator/pull/854))
- chore: update charm libraries ([#853](https://github.com/canonical/prometheus-k8s-operator/pull/853))
- chore: update terraform-docs ([a40f359](https://github.com/canonical/prometheus-k8s-operator/commit/a40f35980fb62ca9fa3012e596675e7d1a5cc233))
- chore(blueprints): refresh charms.just ([0c525cf](https://github.com/canonical/prometheus-k8s-operator/commit/0c525cfc2c5634ff9fa856114694357da6ef6282))
- chore: update charm libraries ([#850](https://github.com/canonical/prometheus-k8s-operator/pull/850))
- chore: update charm libraries ([#835](https://github.com/canonical/prometheus-k8s-operator/pull/835))
- chore: refresh charms.just from canonical/observability ([#848](https://github.com/canonical/prometheus-k8s-operator/pull/848))

