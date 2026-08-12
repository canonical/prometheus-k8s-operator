# Changelog

Changes on `track/3.11` since the common ancestor with `track/2` (`5e4f569`).

## Breaking Changes

- feat!: bump to `prometheus` workload version 3.11.1 ([#785](https://github.com/canonical/prometheus-k8s-operator/pull/785))
- feat(charm lib)!: duplicate host metrics missing alert for collectors thru RemoteWriteConsumer ([#748](https://github.com/canonical/prometheus-k8s-operator/pull/748))

## Features

- feat(tf): base input variable ([#842](https://github.com/canonical/prometheus-k8s-operator/pull/842)) (#843)
- feat: add charms blueprint ([#836](https://github.com/canonical/prometheus-k8s-operator/pull/836))
- feat: set blocked status if invalid rules in relation data and filter out invalid rules ([#817](https://github.com/canonical/prometheus-k8s-operator/pull/817))
- feat: bump to 26.04 ([#814](https://github.com/canonical/prometheus-k8s-operator/pull/814))
- feat: document the OR behavior of our retention config knobs ([#810](https://github.com/canonical/prometheus-k8s-operator/pull/810))
- feat(terraform): Support for Juju provider v2 ([#807](https://github.com/canonical/prometheus-k8s-operator/pull/807))
- feat: TF resources variable ([#805](https://github.com/canonical/prometheus-k8s-operator/pull/805))
- feat: add send-logs integration via LogForwarder ([#798](https://github.com/canonical/prometheus-k8s-operator/pull/798))
- feat: migrate charm-tracing to ops[tracing] ([#799](https://github.com/canonical/prometheus-k8s-operator/pull/799))
- feat(terraform): add channel validation ([#791](https://github.com/canonical/prometheus-k8s-operator/pull/791))
- feat: Manually trigger release CI ([#777](https://github.com/canonical/prometheus-k8s-operator/pull/777))
- feat: add sloth integration ([#772](https://github.com/canonical/prometheus-k8s-operator/pull/772))
- feat: receive-ca-cert relation endpoint ([#750](https://github.com/canonical/prometheus-k8s-operator/pull/750))
- feat: change default track to 'dev' in release workflow ([9f28723](https://github.com/canonical/prometheus-k8s-operator/commit/9f28723b2596337a11071d4746ea4fdfe169db43))

## Fixes

- fix: validate for correct track name ([#844](https://github.com/canonical/prometheus-k8s-operator/pull/844))
- fix: Integration test_logging ([#841](https://github.com/canonical/prometheus-k8s-operator/pull/841))
- fix(prometheus_remote_write): sort peer names for alerts duplication ([#834](https://github.com/canonical/prometheus-k8s-operator/pull/834))
- fix: alert rule errors message ([#830](https://github.com/canonical/prometheus-k8s-operator/pull/830))
- fix: PrometheusRulesProvider should update relation data when config changes ([#826](https://github.com/canonical/prometheus-k8s-operator/pull/826))
- fix: refresh metrics-endpoint unit address on `update_status` and `relation_changed` ([#815](https://github.com/canonical/prometheus-k8s-operator/pull/815))
- fix: update docs link ([#811](https://github.com/canonical/prometheus-k8s-operator/pull/811))
- fix: Split TF endpoints output to requires/provides ([#776](https://github.com/canonical/prometheus-k8s-operator/pull/776))
- fix: use blocked status on invalid log_level ([#662](https://github.com/canonical/prometheus-k8s-operator/pull/662))
- fix: add `juju_unit` label to non-wildcard scrape targets when unit can be identified ([#782](https://github.com/canonical/prometheus-k8s-operator/pull/782))
- fix: deepcopy generic alert rules ([#769](https://github.com/canonical/prometheus-k8s-operator/pull/769))
- fix: Prometheus should accept CA certs from root store when scraping ([78f1318](https://github.com/canonical/prometheus-k8s-operator/commit/78f131863dca08ebe807de98e4743664cfea736e))
- fix: inclusive naming check ([#744](https://github.com/canonical/prometheus-k8s-operator/pull/744))

## Others

- chore: update terraform-docs ([68d69b0](https://github.com/canonical/prometheus-k8s-operator/commit/68d69b02180bcd513e5fd910fef63e17770b9d5b))
- chore(blueprints): refresh charms.just ([860f2b1](https://github.com/canonical/prometheus-k8s-operator/commit/860f2b12a71fd541b8106a92937b056e9c95e6ce))
- chore: refresh charms.just from canonical/observability ([264d494](https://github.com/canonical/prometheus-k8s-operator/commit/264d4949fe322dc6e388e0087298202825a377f4))
- chore(track 3.11): fetch lib ([#847](https://github.com/canonical/prometheus-k8s-operator/pull/847))
- chore: upgrade grafana_source library to v1 for stable datasource UIDs ([#838](https://github.com/canonical/prometheus-k8s-operator/pull/838))
- chore: update charm libraries ([#833](https://github.com/canonical/prometheus-k8s-operator/pull/833))
- chore: update charm libraries ([#823](https://github.com/canonical/prometheus-k8s-operator/pull/823))
- chore: update charm libraries ([#821](https://github.com/canonical/prometheus-k8s-operator/pull/821))
- chore: update charm libraries ([#820](https://github.com/canonical/prometheus-k8s-operator/pull/820))
- chore: update charm libraries ([#813](https://github.com/canonical/prometheus-k8s-operator/pull/813))
- chore: update charm libraries ([#812](https://github.com/canonical/prometheus-k8s-operator/pull/812))
- chore: update charm libraries ([#809](https://github.com/canonical/prometheus-k8s-operator/pull/809))
- ci: fix token permissions for release workflow ([#806](https://github.com/canonical/prometheus-k8s-operator/pull/806))
- ci: add explicit workflow permissions for CodeQL ([#804](https://github.com/canonical/prometheus-k8s-operator/pull/804))
- chore: update charm libraries ([#801](https://github.com/canonical/prometheus-k8s-operator/pull/801))
- chore(ci): bump reusable workflows to v2 ([#797](https://github.com/canonical/prometheus-k8s-operator/pull/797))
- docs: improve charmcraft.yaml description field ([#787](https://github.com/canonical/prometheus-k8s-operator/pull/787))
- chore(deps): update ubuntu/prometheus docker tag to v2.55 ([#773](https://github.com/canonical/prometheus-k8s-operator/pull/773))
- chore: update charm libraries ([#774](https://github.com/canonical/prometheus-k8s-operator/pull/774))
- revert: Revert "feat: add sloth integration ([#772](https://github.com/canonical/prometheus-k8s-operator/pull/772))"
- chore: update charm libraries ([#770](https://github.com/canonical/prometheus-k8s-operator/pull/770))
- chore: bump python to 3.10 ([#771](https://github.com/canonical/prometheus-k8s-operator/pull/771))
- fix unit tests ([#761](https://github.com/canonical/prometheus-k8s-operator/pull/761))
- chore: update charm libraries ([#749](https://github.com/canonical/prometheus-k8s-operator/pull/749))
- chore: update charm libraries ([#745](https://github.com/canonical/prometheus-k8s-operator/pull/745))

