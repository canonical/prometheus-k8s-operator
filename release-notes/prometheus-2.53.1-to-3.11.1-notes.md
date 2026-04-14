# 2.53.3 / 2024-11-04

Tag: v2.53.3
URL: https://github.com/prometheus/prometheus/releases/tag/v2.53.3

* [BUGFIX] Scraping: allow multiple samples on same series, with explicit timestamps. #14685, #14740


================================================================================

# 2.53.4 / 2025-03-18

Tag: v2.53.4
URL: https://github.com/prometheus/prometheus/releases/tag/v2.53.4

* [BUGFIX] Runtime: fix GOGC is being set to 0 when installed with empty prometheus.yml file resulting high cpu usage. #16090
* [BUGFIX] Scrape: fix dropping valid metrics after previous scrape failed. #16220


================================================================================

# 2.53.5 / 2025-06-27

Tag: v2.53.5
URL: https://github.com/prometheus/prometheus/releases/tag/v2.53.5

[LTS patch release]

* [ENHANCEMENT] TSDB: Add backward compatibility with the upcoming TSDB block index v3 #16762
* [BUGFIX] Top-level: Update GOGC before loading TSDB #16521


================================================================================

# 2.54.0 / 2024-08-09

Tag: v2.54.0
URL: https://github.com/prometheus/prometheus/releases/tag/v2.54.0

Release 2.54 brings a release candidate of a major new version of [Remote Write: 2.0](https://prometheus.io/docs/specs/remote_write_spec_2_0/).
This is experimental at this time and may still change.
Remote-write v2 is enabled by default, but can be disabled via feature-flag `web.remote-write-receiver.accepted-protobuf-messages`.

* [CHANGE] Remote-Write: `highest_timestamp_in_seconds` and `queue_highest_sent_timestamp_seconds` metrics now initialized to 0. #14437
* [CHANGE] API: Split warnings from info annotations in API response. #14327
* [FEATURE] Remote-Write: Version 2.0 experimental, plus metadata in WAL via feature flag `metadata-wal-records` (defaults on). #14395,#14427,#14444
* [FEATURE] PromQL: add limitk() and limit_ratio() aggregation operators. #12503
* [ENHANCEMENT] PromQL: Accept underscores in literal numbers, e.g. 1_000_000 for 1 million. #12821
* [ENHANCEMENT] PromQL: float literal numbers and durations are now interchangeable (experimental). Example: `time() - my_timestamp > 10m`. #9138
* [ENHANCEMENT] PromQL: use Kahan summation for sum(). #14074,#14362
* [ENHANCEMENT] PromQL (experimental native histograms): Optimize `histogram_count` and `histogram_sum` functions. #14097
* [ENHANCEMENT] TSDB: Better support for out-of-order experimental native histogram samples. #14438
* [ENHANCEMENT] TSDB: Optimise seek within index. #14393
* [ENHANCEMENT] TSDB: Optimise deletion of stale series. #14307
* [ENHANCEMENT] TSDB: Reduce locking to optimise adding and removing series. #13286,#14286
* [ENHANCEMENT] TSDB: Small optimisation: streamline special handling for out-of-order data. #14396,#14584
* [ENHANCEMENT] Regexps: Optimize patterns with multiple prefixes. #13843,#14368
* [ENHANCEMENT] Regexps: Optimize patterns containing multiple literal strings. #14173
* [ENHANCEMENT] AWS SD: expose Primary IPv6 addresses as __meta_ec2_primary_ipv6_addresses. #14156
* [ENHANCEMENT] Docker SD: add MatchFirstNetwork for containers with multiple networks. #10490
* [ENHANCEMENT] OpenStack SD: Use `flavor.original_name` if available. #14312
* [ENHANCEMENT] UI (experimental native histograms): more accurate representation. #13680,#14430
* [ENHANCEMENT] Agent: `out_of_order_time_window` config option now applies to agent. #14094
* [ENHANCEMENT] Notifier: Send any outstanding Alertmanager notifications when shutting down. #14290
* [ENHANCEMENT] Rules: Add label-matcher support to Rules API. #10194
* [ENHANCEMENT] HTTP API: Add url to message logged on error while sending response. #14209
* [BUGFIX] CLI: escape `|` characters when generating docs. #14420
* [BUGFIX] PromQL (experimental native histograms): Fix some binary operators between native histogram values. #14454
* [BUGFIX] TSDB: LabelNames API could fail during compaction. #14279
* [BUGFIX] TSDB: Fix rare issue where pending OOO read can be left dangling if creating querier fails. #14341
* [BUGFIX] TSDB: fix check for context cancellation in LabelNamesFor. #14302
* [BUGFIX] Rules: Fix rare panic on reload. #14366
* [BUGFIX] Config: In YAML marshalling, do not output a regexp field if it was never set. #14004
* [BUGFIX] Remote-Write: reject samples with future timestamps. #14304
* [BUGFIX] Remote-Write: Fix data corruption in remote write if max_sample_age is applied. #14078
* [BUGFIX] Notifier: Fix Alertmanager discovery not updating under heavy load. #14174
* [BUGFIX] Regexes: some Unicode characters were not matched by case-insensitive comparison. #14170,#14299
* [BUGFIX] Remote-Read: Resolve occasional segmentation fault on query. #14515

Many thanks to the Prometheus Team and contributors:
@zenador 
@jjo 
@rexagod 
@darshanime 
@charleskorn 
@fpetkovski 
@carrieedwards 
@colega  
@pracucci 
@akunszt 
@DrAuYueng 
@paulojmdias 
@Maniktherana 
@rabenhorst  
@saswatamcode 
@B1F030 
@yeya24 
@rapphil 
@liam-howe-maersk 
@jkroepke 
@FUSAKLA 
@Ranveer777


================================================================================

# 2.54.1 / 2024-08-27

Tag: v2.54.1
URL: https://github.com/prometheus/prometheus/releases/tag/v2.54.1

* [BUGFIX] Scraping: allow multiple samples on same series, with explicit timestamps. #14685
* [BUGFIX] Docker SD: fix crash in `match_first_network` mode when container is reconnected to a new network. #14654
* [BUGFIX] PromQL: fix experimental native histogram counter reset detection on stale samples. #14514
* [BUGFIX] PromQL: fix experimental native histograms getting corrupted due to vector selector bug in range queries. #14538
* [BUGFIX] PromQL: fix experimental native histogram memory corruption when using histogram_count or histogram_sum. #14605

**Full Changelog**: https://github.com/prometheus/prometheus/compare/v2.54.0...v2.54.1


================================================================================

# 2.55.0 / 2024-10-22

Tag: v2.55.0
URL: https://github.com/prometheus/prometheus/releases/tag/v2.55.0

## What's Changed
* [FEATURE] PromQL: Add experimental `info` function. #14495
* [FEATURE] Support UTF-8 characters in label names - feature flag `utf8-names`. #14482, #14880, #14736, #14727
* [FEATURE] Scraping: Add the ability to set custom `http_headers` in config. #14817
* [FEATURE] Scraping: Support feature flag `created-timestamp-zero-ingestion` in OpenMetrics. #14356, #14815
* [FEATURE] Scraping: `scrape_failure_log_file` option to log failures to a file. #14734
* [FEATURE] OTLP receiver: Optional promotion of resource attributes to series labels. #14200
* [FEATURE] Remote-Write: Support Google Cloud Monitoring authorization. #14346
* [FEATURE] Promtool: `tsdb create-blocks` new option to add labels. #14403
* [FEATURE] Promtool: `promtool test` adds `--junit` flag to format results. #14506
* [FEATURE] TSDB: Add `delayed-compaction` feature flag, for people running many Prometheus to randomize timing. #12532
* [ENHANCEMENT] OTLP receiver: Warn on exponential histograms with zero count and non-zero sum. #14706
* [ENHANCEMENT] OTLP receiver: Interrupt translation on context cancellation/timeout. #14612
* [ENHANCEMENT] Remote Read client: Enable streaming remote read if the server supports it. #11379
* [ENHANCEMENT] Remote-Write: Don't reshard if we haven't successfully sent a sample since last update. #14450
* [ENHANCEMENT] PromQL: Delay deletion of `__name__` label to the end of the query evaluation. This is **experimental** and enabled under the feature-flag `promql-delayed-name-removal`. #14477
* [ENHANCEMENT] PromQL: Experimental `sort_by_label` and `sort_by_label_desc` sort by all labels when label is equal. #14655, #14985
* [ENHANCEMENT] PromQL: Clarify error message logged when Go runtime panic occurs during query evaluation. #14621
* [ENHANCEMENT] PromQL: Use Kahan summation for better accuracy in `avg` and `avg_over_time`. #14413
* [ENHANCEMENT] Tracing: Improve PromQL tracing, including showing the operation performed for aggregates, operators, and calls. #14816
* [ENHANCEMENT] API: Support multiple listening addresses. #14665
* [ENHANCEMENT] TSDB: Backward compatibility with upcoming index v3. #14934
* [PERF] TSDB: Query in-order and out-of-order series together. #14354, #14693, #14714, #14831, #14874, #14948, #15120
* [PERF] TSDB: Streamline reading of overlapping out-of-order head chunks. #14729
* [BUGFIX] PromQL: make sort_by_label stable. #14985
* [BUGFIX] SD: Fix dropping targets (with feature flag `new-service-discovery-manager`). #13147
* [BUGFIX] SD: Stop storing stale targets (with feature flag `new-service-discovery-manager`). #13622
* [BUGFIX] Scraping: exemplars could be dropped in protobuf scraping. #14810
* [BUGFIX] Remote-Write: fix metadata sending for experimental Remote-Write V2. #14766
* [BUGFIX] Remote-Write: Return 4xx not 5xx when timeseries has duplicate label. #14716
* [BUGFIX] Experimental Native Histograms: many fixes for incorrect results, panics, warnings. #14513, #14575, #14598, #14609, #14611, #14771, #14821
* [BUGFIX] TSDB: Only count unknown record types in `record_decode_failures_total` metric. #14042

## New Contributors
* @maxamins made their first contribution in https://github.com/prometheus/prometheus/pull/14346
* @cuiweiyuan made their first contribution in https://github.com/prometheus/prometheus/pull/14626
* @harshitasao made their first contribution in https://github.com/prometheus/prometheus/pull/14690
* @patilsuraj767 made their first contribution in https://github.com/prometheus/prometheus/pull/14403
* @riskrole made their first contribution in https://github.com/prometheus/prometheus/pull/14751
* @jcreixell made their first contribution in https://github.com/prometheus/prometheus/pull/14477
* @kevinrawal made their first contribution in https://github.com/prometheus/prometheus/pull/14765
* @electron0zero made their first contribution in https://github.com/prometheus/prometheus/pull/14650
* @shandongzhejiang made their first contribution in https://github.com/prometheus/prometheus/pull/14700

**Full Changelog**: https://github.com/prometheus/prometheus/compare/v2.54.1...v2.55.0


================================================================================

# 2.55.1 / 2024-11-04

Tag: v2.55.1
URL: https://github.com/prometheus/prometheus/releases/tag/v2.55.1

* [BUGFIX] `round()` function did not remove `__name__` label. #15250


================================================================================

# 3.0.0 / 2024-11-14

Tag: v3.0.0
URL: https://github.com/prometheus/prometheus/releases/tag/v3.0.0

This release includes new features such as a brand new UI and UTF-8 support enabled by default. As this marks the first new major version in seven years, several breaking changes are introduced. The breaking changes are mainly around the removal of deprecated feature flags and CLI arguments, and the full list can be found below. For users that want to upgrade we recommend to read through our [migration guide](https://prometheus.io/docs/prometheus/3.0/migration/).

* [CHANGE] Set the `GOMAXPROCS` variable automatically to match the Linux CPU quota. Use `--no-auto-gomaxprocs` to disable it. The `auto-gomaxprocs` feature flag was removed. #15376
* [CHANGE] Set the `GOMEMLIMIT` variable automatically to match the Linux container memory limit. Use `--no-auto-gomemlimit` to disable it. The `auto-gomemlimit` feature flag was removed. #15373
* [CHANGE] Scraping: Remove implicit fallback to the Prometheus text format in case of invalid/missing Content-Type and fail the scrape instead. Add ability to specify a `fallback_scrape_protocol` in the scrape config. #15136
* [CHANGE] Remote-write: default enable_http2 to false. #15219
* [CHANGE] Scraping: normalize "le" and "quantile" label values upon ingestion. #15164
* [CHANGE] Scraping: config `scrape_classic_histograms` was renamed to `always_scrape_classic_histograms`. #15178
* [CHANGE] Config: remove expand-external-labels flag, expand external labels env vars by default. #14657
* [CHANGE] Disallow configuring AM with the v1 api. #13883
* [CHANGE] regexp `.` now matches all characters (performance improvement). #14505
* [CHANGE] `holt_winters` is now called `double_exponential_smoothing` and moves behind the [experimental-promql-functions feature flag](https://prometheus.io/docs/prometheus/latest/feature_flags/#experimental-promql-functions). #14930
* [CHANGE] API: The OTLP receiver endpoint can now be enabled using `--web.enable-otlp-receiver` instead of `--enable-feature=otlp-write-receiver`. #14894
* [CHANGE] Prometheus will not add or remove port numbers from the target address. `no-default-scrape-port` feature flag removed. #14160
* [CHANGE] Logging: the format of log lines has changed a little, along with the adoption of Go's Structured Logging package. #14906
* [CHANGE] Don't create extra `_created` timeseries if feature-flag `created-timestamp-zero-ingestion` is enabled. #14738
* [CHANGE] Float literals and time durations being the same is now a stable fetaure. #15111
* [CHANGE] UI: The old web UI has been replaced by a completely new one that is less cluttered and adds a few new features (PromLens-style tree view, better metrics explorer, "Explain" tab). However, it is still missing some features of the old UI (notably, exemplar display and heatmaps). To switch back to the old UI, you can use the feature flag `--enable-feature=old-ui` for the time being. #14872
* [CHANGE] PromQL: Range selectors and the lookback delta are now left-open, i.e. a sample coinciding with the lower time limit is excluded rather than included. #13904
* [CHANGE] Kubernetes SD: Remove support for `discovery.k8s.io/v1beta1` API version of EndpointSlice. This version is no longer served as of Kubernetes v1.25. #14365
* [CHANGE] Kubernetes SD: Remove support for `networking.k8s.io/v1beta1` API version of Ingress. This version is no longer served as of Kubernetes v1.22. #14365
* [CHANGE] UTF-8: Enable UTF-8 support by default. Prometheus now allows all UTF-8 characters in metric and label names. The corresponding `utf8-name` feature flag has been removed. #14705
* [CHANGE] Console: Remove example files for the console feature. Users can continue using the console feature by supplying their own JavaScript and templates. #14807
* [CHANGE] SD: Enable the new service discovery manager by default. This SD manager does not restart unchanged discoveries upon reloading. This makes reloads faster and reduces pressure on service discoveries' sources. The corresponding `new-service-discovery-manager` feature flag has been removed. #14770
* [CHANGE] Agent mode has been promoted to stable. The feature flag `agent` has been removed. To run Prometheus in Agent mode, use the new `--agent` cmdline arg instead. #14747
* [CHANGE] Remove deprecated `remote-write-receiver`,`promql-at-modifier`, and `promql-negative-offset` feature flags. #13456, #14526
* [CHANGE] Remove deprecated `storage.tsdb.allow-overlapping-blocks`, `alertmanager.timeout`, and `storage.tsdb.retention` flags. #14640, #14643
* [FEATURE] OTLP receiver: Ability to skip UTF-8 normalization using `otlp.translation_strategy = NoUTF8EscapingWithSuffixes` configuration option. #15384
* [FEATURE] Support config reload automatically - feature flag `auto-reload-config`. #14769
* [ENHANCEMENT] Scraping, rules: handle targets reappearing, or rules moving group, when out-of-order is enabled. #14710
* [ENHANCEMENT] Tools: add debug printouts to promtool rules unit testing #15196
* [ENHANCEMENT] Scraping: support Created-Timestamp feature on native histograms. #14694
* [ENHANCEMENT] UI: Many fixes and improvements. #14898, #14899, #14907, #14908, #14912, #14913, #14914, #14931, #14940, #14945, #14946, #14972, #14981, #14982, #14994, #15096
* [ENHANCEMENT] UI: Web UI now displays notifications, e.g. when starting up and shutting down. #15082
* [ENHANCEMENT] PromQL: Introduce exponential interpolation for native histograms. #14677
* [ENHANCEMENT] TSDB: Add support for ingestion of out-of-order native histogram samples. #14850, #14546
* [ENHANCEMENT] Alerts: remove metrics for removed Alertmanagers. #13909
* [ENHANCEMENT] Kubernetes SD: Support sidecar containers in endpoint discovery. #14929
* [ENHANCEMENT] Consul SD: Support catalog filters. #11224
* [ENHANCEMENT] Move AM discovery page from "Monitoring status" to "Server status". #14875
* [PERF] TSDB: Parallelize deletion of postings after head compaction. #14975
* [PERF] TSDB: Chunk encoding: shorten some write sequences. #14932
* [PERF] TSDB: Grow postings by doubling. #14721
* [PERF] Relabeling: Optimize adding a constant label pair. #12180
* [BUGFIX] UI: fix selector / series formatting for empty metric names. #15341
* [BUGFIX] PromQL: Fix stddev+stdvar aggregations to always ignore native histograms. #14941
* [BUGFIX] PromQL: Fix stddev+stdvar aggregations to treat Infinity consistently. #14941
* [BUGFIX] OTLP receiver: Preserve colons when generating metric names in suffix adding mode (this mode is always enabled, unless one uses Prometheus as a library). #15251
* [BUGFIX] Scraping: Unit was missing when using protobuf format. #15095
* [BUGFIX] PromQL: Only return "possible non-counter" annotation when `rate` returns points. #14910
* [BUGFIX] TSDB: Chunks could have one unnecessary zero byte at the end. #14854
* [BUGFIX] "superfluous response.WriteHeader call" messages in log. #14884
* [BUGFIX] PromQL: Unary negation of native histograms. #14821
* [BUGFIX] PromQL: Handle stale marker in native histogram series (e.g. if series goes away and comes back). #15025
* [BUGFIX] Autoreload: Reload invalid yaml files. #14947
* [BUGFIX] Scrape: Do not override target parameter labels with config params. #11029

**Full Changelog**: https://github.com/prometheus/prometheus/compare/v2.55.0...v3.0.0


================================================================================

# 3.0.1 / 2024-11-28

Tag: v3.0.1
URL: https://github.com/prometheus/prometheus/releases/tag/v3.0.1

The first bug fix release for Prometheus 3.

* [BUGFIX] Promql: Make subqueries left open. #15431
* [BUGFIX] Fix memory leak when query log is enabled. #15434
* [BUGFIX] Support utf8 names on /v1/label/:name/values endpoint. #15399


================================================================================

# 3.1.0 / 2025-01-02

Tag: v3.1.0
URL: https://github.com/prometheus/prometheus/releases/tag/v3.1.0

## What's Changed

 * [SECURITY] upgrade golang.org/x/crypto to address reported CVE-2024-45337. #15691
 * [CHANGE] Notifier: Increment prometheus_notifications_errors_total by the number of affected alerts rather than per batch. #15428
 * [CHANGE] API: list rules field "groupNextToken:omitempty" renamed to "groupNextToken". #15400
 * [ENHANCEMENT] OTLP translate: keep identifying attributes in target_info. #15448
 * [ENHANCEMENT] Paginate rule groups, add infinite scroll to rules within groups. #15677
 * [ENHANCEMENT] TSDB: Improve calculation of space used by labels. #13880
 * [ENHANCEMENT] Rules: new metric rule_group_last_rule_duration_sum_seconds. #15672
 * [ENHANCEMENT] Observability: Export 'go_sync_mutex_wait_total_seconds_total' metric. #15339
 * [ENHANCEMEN] Remote-Write: optionally use a DNS resolver that picks a random IP. #15329
 * [PERF] Optimize `l=~".+"` matcher. #15474, #15684
 * [PERF] TSDB: Cache all symbols for compaction . #15455
 * [PERF] TSDB: MemPostings: keep a map of label values slices. #15426
 * [PERF] Remote-Write: Remove interning hook. #15456
 * [PERF] Scrape: optimize string manipulation for experimental native histograms with custom buckets. #15453
 * [PERF] TSDB: reduce memory allocations. #15465, #15427
 * [PERF] Storage: Implement limit in mergeGenericQuerier. #14489
 * [PERF] TSDB: Optimize inverse matching. #14144
 * [PERF] Regex: use stack memory for lowercase copy of string. #15210
 * [PERF] TSDB: When deleting from postings index, pause to unlock and let readers read. #15242
 * [BUGFIX] Main: Avoid possible segfault at exit. (#15724)
 * [BUGFIX] Rules: Do not run rules concurrently if uncertain about dependencies. #15560
 * [BUGFIX] PromQL: Adds test for `absent`, `absent_over_time` and `deriv` func with histograms. #15667
 * [BUGFIX] PromQL: Fix various bugs related to quoting UTF-8 characters. #15531
 * [BUGFIX] Scrape: fix nil panic after scrape loop reload. #15563
 * [BUGFIX] Remote-write: fix panic on repeated log message. #15562
 * [BUGFIX] Scrape: reload would ignore always_scrape_classic_histograms and convert_classic_histograms_to_nhcb configs. #15489
 * [BUGFIX] TSDB: fix data corruption in experimental native histograms. #15482
 * [BUGFIX] PromQL: Ignore histograms in all time related functions. #15479
 * [BUGFIX] OTLP receiver: Convert metric metadata. #15416
 * [BUGFIX] PromQL: Fix `resets` function for histograms. #15527
 * [BUGFIX] PromQL: Fix behaviour of `changes()` for mix of histograms and floats. #15469
 * [BUGFIX] PromQL: Fix behaviour of some aggregations with histograms. #15432
 * [BUGFIX] allow quoted exemplar keys in openmetrics text format. #15260
 * [BUGFIX] TSDB: fixes for rare conditions when loading write-behind-log (WBL). #15380
 * [BUGFIX] `round()` function did not remove `__name__` label. #15250
 * [BUGFIX] Promtool: analyze block shows metric name with 0 cardinality. #15438
 * [BUGFIX] PromQL: Fix `count_values` for histograms. #15422
 * [BUGFIX] PromQL: fix issues with comparison binary operations with `bool` modifier and native histograms. #15413
 * [BUGFIX] PromQL: fix incorrect "native histogram ignored in aggregation" annotations. #15414
 * [BUGFIX] PromQL: Corrects the behaviour of some operator and aggregators with Native Histograms. #15245
 * [BUGFIX] TSDB: Always return unknown hint for first sample in non-gauge histogram chunk. #15343
 * [BUGFIX] PromQL: Clamp functions: Ignore any points with native histograms. #15169
 * [BUGFIX] TSDB: Fix race on stale values in headAppender. #15322
 * [BUGFIX] UI: Fix selector / series formatting for empty metric names. #15340
 * [BUGFIX] OTLP receiver: Allow colons in non-standard units. #15710


================================================================================

# 3.2.0 / 2025-02-17

Tag: v3.2.0
URL: https://github.com/prometheus/prometheus/releases/tag/v3.2.0

## Prometheus v3.2.0 Changelog

* [CHANGE] relabel: Replace actions can now use UTF-8 characters in `targetLabel` field. Note that `$<chars>` or `${<chars>}` will be expanded. This also apply to `replacement` field for `LabelMap` action. #15851
* [CHANGE] rulefmt: Rule names can use UTF-8 characters, except `{` and `}` characters (due to common mistake checks). #15851
* [FEATURE] remote/otlp: Add feature flag `otlp-deltatocumulative` to support conversion from delta to cumulative. #15165
* [ENHANCEMENT] openstack SD: Discover Octavia loadbalancers. #15539
* [ENHANCEMENT] scrape: Add metadata for automatic metrics to WAL for `metadata-wal-records` feature. #15837
* [ENHANCEMENT] promtool: Support linting of scrape interval, through lint option `too-long-scrape-interval`. #15719
* [ENHANCEMENT] promtool: Add --ignore-unknown-fields option. #15706
* [ENHANCEMENT] ui: Make "hide empty rules" and hide empty rules" persistent #15807
* [ENHANCEMENT] web/api: Add a limit parameter to `/query` and `/query_range`. #15552
* [ENHANCEMENT] api: Add fields Node and ServerTime to `/status`. #15784
* [PERF] Scraping: defer computing labels for dropped targets until they are needed by the UI.  #15261
* [BUGFIX] remotewrite2: Fix invalid metadata bug for metrics without metadata. #15829
* [BUGFIX] remotewrite2: Fix the unit field propagation. #15825
* [BUGFIX] scrape: Fix WAL metadata for histograms and summaries. #15832
* [BUGFIX] ui: Merge duplicate "Alerts page settings" sections. #15810
* [BUGFIX] PromQL: Fix `<aggr_over_time>` functions with histograms. #15711


================================================================================

# 3.2.1 / 2025-02-25

Tag: v3.2.1
URL: https://github.com/prometheus/prometheus/releases/tag/v3.2.1

* [BUGFIX] Don't send Accept header `escape=allow-utf-8` when `metric_name_validation_scheme: legacy` is configured. #16061


================================================================================

# 3.3.0 / 2025-04-15

Tag: v3.3.0
URL: https://github.com/prometheus/prometheus/releases/tag/v3.3.0

* [FEATURE] PromQL: Implement `idelta()` and `irate()` for native histograms. #15853
* [ENHANCEMENT] Scaleway SD: Add `__meta_scaleway_instance_public_ipv4_addresses` and `__meta_scaleway_instance_public_ipv6_addresses` labels. #14228
* [ENHANCEMENT] TSDB: Reduce locking while reloading blocks. #12920
* [ENHANCEMENT] PromQL: Allow UTF-8 labels in `label_replace()`. #15974
* [ENHANCEMENT] Promtool: `tsdb create-blocks-from openmetrics` can now read from a Pipe. #16011
* [ENHANCEMENT] Rules: Add support for anchors and aliases in rule files. #14957
* [ENHANCEMENT] Dockerfile: Make `/prometheus` writable. #16073
* [ENHANCEMENT] API: Include scrape pool name for dropped targets in `/api/v1/targets`. #16085
* [ENHANCEMENT] UI: Improve time formatting and copying of selectors. #15999 #16165
* [ENHANCEMENT] UI: Bring back vertical grid lines and graph legend series toggling instructions. #16163 #16164
* [ENHANCEMENT] Mixin: The `cluster` label can be customized using `clusterLabel`. #15826
* [PERF] TSDB: Optimize some operations on head chunks by taking shortcuts. #12659
* [PERF] TSDB & Agent: Reduce memory footprint during WL replay. #15778
* [PERF] Remote-Write: Reduce memory footprint during WAL replay. #16197
* [PERF] API: Reduce memory footprint during header parsing. #16001
* [PERF] Rules: Improve dependency evaluation, enabling better concurrency. #16039
* [PERF] Scraping: Improve scraping performance for native histograms. #15731
* [PERF] Scraping: Improve parsing of created timestamps. #16072
* [BUGFIX] Scraping: Bump cache iteration after error to avoid false duplicate detections. #16174
* [BUGFIX] Scraping: Skip native histograms series when ingestion is disabled. #16218
* [BUGFIX] PromQL: Fix counter reset detection for native histograms. #15902 #15987
* [BUGFIX] PromQL: Fix inconsistent behavior with an empty range. #15970
* [BUGFIX] PromQL: Fix inconsistent annotation in `quantile_over_time()`. #16018
* [BUGFIX] PromQL: Prevent `label_join()` from producing duplicates. #15975
* [BUGFIX] PromQL: Ignore native histograms in `scalar()`, `sort()` and `sort_desc()`. #15964
* [BUGFIX] PromQL: Fix annotations for binary operations between incompatible native histograms. #15895
* [BUGFIX] Alerting: Consider alert relabeling when deciding whether alerts are dropped. #15979
* [BUGFIX] Config: Set `GoGC` to the default value in case of an empty configuration. #16052
* [BUGFIX] TSDB: Fix unknown series errors and potential data loss during WAL replay when inactive series are removed from the head and reappear before the next WAL checkpoint. #16060
* [BUGFIX] Scaleway SD: The public IP will no longer be set to `__meta_meta_scaleway_instance_public_ipv4` if it is an IPv6 address. #14228
* [BUGFIX] UI: Display the correct value of Alerting rules' `keep_firing_for`. #16211


================================================================================

# 3.3.1 / 2025-05-02

Tag: v3.3.1
URL: https://github.com/prometheus/prometheus/releases/tag/v3.3.1

* [BUGFIX] Azure SD: Fix panic on malformed log message. #16434 #16210
* [BUGFIX] Config: Update GOGC before loading TSDB. #16491


================================================================================

# 3.4.0 / 2025-05-17

Tag: v3.4.0
URL: https://github.com/prometheus/prometheus/releases/tag/v3.4.0

* [CHANGE] Config: Make setting out-of-order native histograms feature (`--enable-feature=ooo-native-histograms`) a no-op. Out-of-order native histograms are now always enabled when `out_of_order_time_window` is greater than zero and `--enable-feature=native-histograms` is set. #16207
* [FEATURE] OTLP translate: Add feature flag for optionally translating OTel explicit bucket histograms into native histograms with custom buckets. #15850
* [FEATURE] OTLP translate: Add option to receive OTLP metrics without translating names or attributes. #16441
* [FEATURE] PromQL: allow arithmetic operations in durations in PromQL parser. #16249
* [FEATURE] OTLP receiver: Add primitive support for ingesting OTLP delta metrics as-is. #16360
* [ENHANCEMENT] PromQL: histogram_fraction for bucket histograms. #16095
* [ENHANCEMENT] TSDB: add `prometheus_tsdb_wal_replay_unknown_refs_total` and `prometheus_tsdb_wbl_replay_unknown_refs_total` metrics to track unknown series references during WAL/WBL replay. #16166
* [ENHANCEMENT] Scraping: Add config option for escaping scheme request. #16066
* [ENHANCEMENT] Config: Add global config option for convert_classic_histograms_to_nhcb. #16226
* [ENHANCEMENT] Alerting: make batch size configurable (`--alertmanager.notification-batch-size`). #16254
* [PERF] Kubernetes SD: make endpointSlice discovery more efficient. #16433
* [BUGFIX] Config: Fix auto-reload on changes to rule and scrape config files. #16340
* [BUGFIX] Scraping: Skip native histogram series if ingestion is disabled. #16218
* [BUGFIX] TSDB: Handle metadata/tombstones/exemplars for duplicate series during WAL replay. #16231
* [BUGFIX] TSDB: Avoid processing exemplars outside the valid time range during WAL replay. #16242
* [BUGFIX] Promtool: Add feature flags for PromQL features. #16443
* [BUGFIX] Rules: correct logging of alert name & template data. #15093
* [BUGFIX] PromQL: Use arithmetic mean for `histogram_stddev()` and `histogram_stdvar()` . #16444


================================================================================

# 3.4.1 / 2025-05-31

Tag: v3.4.1
URL: https://github.com/prometheus/prometheus/releases/tag/v3.4.1

* [BUGFIX] Parser: Add reproducer for a dangling-reference issue in parsers. #16633


================================================================================

# 3.4.2 / 2025-06-26

Tag: v3.4.2
URL: https://github.com/prometheus/prometheus/releases/tag/v3.4.2

* [BUGFIX] OTLP receiver: Fix default configuration not being respected if the `otlp:` block is unset in the config file. #16693


================================================================================

# 3.5.0 / 2025-07-14

Tag: v3.5.0
URL: https://github.com/prometheus/prometheus/releases/tag/v3.5.0

3.5 is a Long Term Support (LTS) release; see release https://prometheus.io/docs/introduction/release-cycle/
There are a number of new features, and no known breaking changes in this release:

* [FEATURE] PromQL: Add experimental type and unit metadata labels, behind feature flag `type-and-unit-labels`. #16228 #16632 #16718 #16743
* [FEATURE] PromQL: Add `ts_of_(min|max|last)_over_time`, behind feature flag `experimental-promql-functions`. #16722 #16733
* [FEATURE] Scraping: Add global option `always_scrape_classic_histograms` to scrape a classic histogram even if it is also exposed as native. #16452
* [FEATURE] OTLP: New config options `promote_all_resource_attributes` and `ignore_resource_attributes`. #16426
* [FEATURE] Discovery: New service discovery for STACKIT Cloud. #16401
* [ENHANCEMENT] Hetzner SD: Add `label_selector` to filter servers. #16512
* [ENHANCEMENT] PromQL: support non-constant parameter in aggregations like `quantile` and `topk`. #16404
* [ENHANCEMENT] UI: Better total target count display when using `keep_dropped_targets` option. #16604
* [ENHANCEMENT] UI: Add simple filtering on the `/rules` page. #16605
* [ENHANCEMENT] UI: Display query stats in hover tooltip over table query tab. #16723
* [ENHANCEMENT] UI: Clear search field on `/targets` page. #16567
* [ENHANCEMENT] Rules: Check that rules parse without error earlier at startup. #16601
* [ENHANCEMENT] Promtool: Optional fuzzy float64 comparison in rules unittests. #16395
* [PERF] PromQL: Reuse `histogramStatsIterator` where possible. #16686
* [PERF] PromQL: Reuse storage for custom bucket values for native histograms. #16565
* [PERF] UI: Optimize memoization and search debouncing on `/targets` page. #16589
* [PERF] UI: Fix full-page re-rendering when opening status nav menu. #16590
* [PERF] Kubernetes SD: use service cache.Indexer to achieve better performance. #16365
* [PERF] TSDB: Optionally use Direct IO for chunks writing. #15365
* [PERF] TSDB: When fetching label values, stop work earlier if the limit is reached. #16158
* [PERF] Labels: Simpler/faster stringlabels encoding. #16069
* [PERF] Scraping: Reload scrape pools concurrently. #16595 #16783
* [BUGFIX] Top-level: Update GOGC before loading TSDB. #16491
* [BUGFIX] Config: Respect GOGC environment variable if no "runtime" block exists. #16558
* [BUGFIX] PromQL: Fix native histogram `last_over_time`. #16744
* [BUGFIX] PromQL: Fix reported parser position range in errors for aggregations wrapped in ParenExpr #16041 #16754
* [BUGFIX] PromQL: Don't emit a value from `histogram_fraction` or `histogram_quantile` if classic and native histograms are present at the same timestamp. #16552
* [BUGFIX] PromQL: Incorrect rounding of `[1001ms]` to `[1s]` and similar. #16478
* [BUGFIX] PromQL: Fix inconsistent / sometimes negative `histogram_count` and `histogram_sum`. #16682
* [BUGFIX] PromQL: Improve handling of NaNs in native histograms. #16724
* [BUGFIX] PromQL: Fix unary operator precedence in duration expressions. #16713
* [BUGFIX] PromQL: Improve consistency of `avg` aggregation and `avg_over_time`. #16569 #16773
* [BUGFIX] UI: Add query warnings and info to graph view. #16753 #16759
* [BUGFIX] API: Add HTTP `Vary: Origin` header to responses to avoid cache poisoning. #16008
* [BUGFIX] Discovery: Avoid deadlocks by taking locks in consistent order. #16587
* [BUGFIX] Remote-write: For Azure AD auth, allow empty `client_id` to suppport system assigned managed identity. #16421
* [BUGFIX] Scraping: Fix rare memory corruption bug. #16623
* [BUGFIX] Scraping: continue handling custom-bucket histograms after an exponential histogram is encountered. #16720
* [BUGFIX] OTLP: Default config not respected when `otlp:` block is unset. #16693


================================================================================

# 3.5.1 / 2026-01-07

Tag: v3.5.1
URL: https://github.com/prometheus/prometheus/releases/tag/v3.5.1

This is the current "Long Term Support" release.
No code changes since 3.5.0, just some dependency updates:
* Docker library updated from 28.2.2 to 28.5.2. #17821
* Built with Go 1.24.11.


================================================================================

# 3.5.2 / 2026-04-13

Tag: v3.5.2
URL: https://github.com/prometheus/prometheus/releases/tag/v3.5.2

This release has a fix for a Stored XSS vulnerability that can be triggered via crafted metric names and label values in Prometheus web UI tooltips and metrics explorer. Thanks to Duc Anh Nguyen from TinyxLab for reporting it.

* [SECURITY] UI: Fix stored XSS via unescaped metric names and labels. CVE-2026-40179. #18507
* [PERF] Regex: Stop calling Simplify. #17908


================================================================================

# 3.6.0 / 2025-09-17

Tag: v3.6.0
URL: https://github.com/prometheus/prometheus/releases/tag/v3.6.0

* [FEATURE] PromQL: Add `step()`, and `min()` and `max()` on durations, behind feature flag `promql-duration-expr`. #16777
* [FEATURE] API: Add a `/v1/status/tsdb/blocks` endpoint exposing metadata about loaded blocks. #16695
* [FEATURE] Templates: Add `toDuration()` and `now()` functions. #16619
* [ENHANCEMENT] Discovery: Add support for attaching namespace metadata to targets. #16831
* [ENHANCEMENT] OTLP: Support new `UnderscoreEscapingWithoutSuffixes` strategy via `otlp.translation_strategy`. #16849
* [ENHANCEMENT] OTLP: Support including scope metadata as metric labels via `otlp.promote_scope_metadata`. #16878
* [ENHANCEMENT] OTLP: Add `__type__` and `__unit__` labels when feature flag `type-and-unit-labels` is enabled. #16630
* [ENHANCEMENT] Tracing: Send the traceparent HTTP header during scrapes. #16425
* [ENHANCEMENT] UI: Add option to disable info and warning query messages under `Query page settings`. #16901
* [ENHANCEMENT] UI: Improve metadata handling for `_count/_sum/_bucket` suffixes. #16910
* [ENHANCEMENT] TSDB: Track stale series in the Head block via the `prometheus_tsdb_head_stale_series` metric. #16925
* [PERF] PromQL: Improve performance due to internal optimizations. #16797
* [BUGFIX] Config: Fix "unknown global name escaping method" error messages produced during config validation. #16801
* [BUGFIX] Discovery: Fix race condition during shutdown. #16820
* [BUGFIX] OTLP: Generate `target_info` samples between the earliest and latest samples per resource. #16737
* [BUGFIX] PromQL: Fail when `NaN` is passed as parameter to `topk()`, `bottomk()`, `limitk()` and `limit_ratio()`. #16725
* [BUGFIX] PromQL: Fix extrapolation for native counter histograms. #16828
* [BUGFIX] PromQL: Reduce numerical errors by disabling some optimizations. #16895
* [BUGFIX] PromQL: Fix inconsistencies when using native histograms in subqueries. #16879
* [BUGFIX] PromQL: Fix inconsistent annotations for `rate()` and `increase()` on histograms when feature flag `type-and-unit-labels` is enabled. #16915
* [BUGFIX] Scraping: Fix memory corruption in `slicelabels` builds. #16946
* [BUGFIX] TSDB: Fix panic on append when feature flag `created-timestamp-zero-ingestion` is enabled. #16332
* [BUGFIX] TSDB: Fix panic on append for native histograms with empty buckets. #16893


================================================================================

# 3.7.0 / 2025-10-15

Tag: v3.7.0
URL: https://github.com/prometheus/prometheus/releases/tag/v3.7.0

## Warning

We discovered a  breaking change in the OTLP endpoint: OpenTelemetry attribute names starting with underscore, for example `_attrib`, are no longer automatically translated to `key_attrib`. Please use 3.7.1 instead for OTLP ingestion.

## Changelog

* [CHANGE] Remote-write: the following metrics are deprecated:
   - `prometheus_remote_storage_samples_in_total`, use `prometheus_wal_watcher_records_read_total{type="samples"}` and `prometheus_remote_storage_samples_dropped_total` instead,
   - `prometheus_remote_storage_histograms_in_total`, use `prometheus_wal_watcher_records_read_total{type=~".*histogram_samples"}` and `prometheus_remote_storage_histograms_dropped_total` instead,
   - `prometheus_remote_storage_exemplars_in_total`, use `prometheus_wal_watcher_records_read_total{type="exemplars"}` and `prometheus_remote_storage_exemplars_dropped_total` instead,
   - `prometheus_remote_storage_highest_timestamp_in_seconds`, use the more accurate `prometheus_remote_storage_queue_highest_timestamp_seconds` instead in dashboards and alerts to properly account for relabeling and for more accuracy. #17065
* [FEATURE] PromQL: Add support for experimental anchored and smoothed rate behind feature flag `promql-extended-range-selectors`. #16457
* [FEATURE] Federation: Add support for native histograms with custom buckets (NHCB). #17215
* [FEATURE] PromQL: Add `first_over_time(...)` and `ts_of_first_over_time(...)` behind feature flag `experimental-promql-functions`. #16963 #17021
* [FEATURE] Remote-write: Add support for Azure Workload Identity as an authentication method for the receiver. #16788
* [FEATURE] Remote-write: Add type and unit labels to outgoing time series in remote-write 2.0 when the `type-and-unit-labels` feature flag is enabled. #17033
* [FEATURE] OTLP: Write start time of metrics as created time zero samples into TSDB when `created-timestamp-zero-ingestion` feature flag is enabled. #16951
* [ENHANCEMENT] PromQL: Add warn-level annotations for counter reset conflicts in certain histogram operations. #17051 #17094
* [ENHANCEMENT] UI: Add scrape interval and scrape timeout to targets page. #17158
* [ENHANCEMENT] TSDB: Reduce the resolution of native histograms read from chunks or remote read if the schema is exponential. #17213
* [ENHANCEMENT] Remote write: Add logging for unexpected metadata in sample batches, when metadata entries are found in samples-only batches. #17034 #17082
* [ENHANCEMENT] Rules: Support concurrent evaluation for rules querying `ALERTS` and `ALERTS_FOR_STATE`. #17064
* [ENHANCEMENT] TSDB: Add logs to improve visibility into internal operations. #17074
* [PERF] OTLP: Write directly to TSDB instead of passing through a Remote-Write adapter when receiving OTLP metrics. #16951
* [PERF] OTLP: Reduce number of logs emitted from OTLP endpoint. No need to log duplicate sample errors. #17201
* [PERF] PromQL: Move more work to preprocessing step. #16896
* [PERF] PromQL: Reduce allocations when walking the syntax tree. #16593
* [PERF] TSDB: Optimize appender creation, slightly speeding up startup. #16922
* [PERF] TSDB: Improve speed of querying a series with multiple matchers. #13971
* [BUGFIX] Alerting: Mutating alerts relabeling (using `replace` actions, etc.) within a `alertmanager_config.alert_relabel_configs` block is now scoped correctly and no longer yields altered alerts to subsequent blocks. #17063
* [BUGFIX] Config: Infer valid escaping scheme when scrape config validation scheme is set. #16923
* [BUGFIX] TSDB: Correctly handle appending mixed-typed samples to the same series. #17071 #17241 #17290 #17295 #17296
* [BUGFIX] Remote-write: Prevent sending unsupported native histograms with custom buckets (NHCB) over Remote-write 1.0, log warning. #17146
* [BUGFIX] TSDB: Fix metadata entries handling on `metadata-wal-records` experimental feature for native histograms with custom buckets (NHCB) in protobuf scraping. #17156
* [BUGFIX] TSDB: Ignore Native Histograms with invalid schemas during WAL/WBL replay. #17214
* [BUGFIX] PromQL: Avoid empty metric names in annotations for `histogram_quantile()`. #16794
* [BUGFIX] PromQL: Correct inaccurate character positions in errors for some aggregate expressions. #16996 #17031
* [BUGFIX] PromQL: Fix `info()` function on churning series. #17135
* [BUGFIX] PromQL: Set native histogram to gauge type when subtracting or multiplying/dividing with negative factors. #17004
* [BUGFIX] TSDB: Reject unsupported native histogram schemas when attempting to append to TSDB. For scrape and remote-write implement reducing the resolution to fit the maximum if the schema is within the -9 to 52. #17189
* [BUGFIX] Remote-write: Fix HTTP handler to return after writing error response for invalid compression. #17050
* [BUGFIX] Remote-write: Return HTTP error `400` instead of `5xx` for wrongly formatted Native Histograms. #17210
* [BUGFIX] Scrape: Prevent staleness markers from generating unnecessary series. #16429
* [BUGFIX] TSDB: Avoid misleading `Failed to calculate size of \"wal\" dir` error logs during WAL clean-up. #17006
* [BUGFIX] TSDB: Prevent erroneously dropping series records during WAL checkpoints. #17029
* [BUGFIX] UI: Fix redirect to path of `-web.external-url` if `-web.route-prefix` is configured. #17240
* [BUGIFX] Remote-write: Do not panic on invalid symbol table in remote-write 2.0. #17160


================================================================================

# 3.7.1 / 2025-10-16

Tag: v3.7.1
URL: https://github.com/prometheus/prometheus/releases/tag/v3.7.1

* [BUGFIX] OTLP: Prefix `key_` to label name when translating an OTel attribute name starting with a single underscore, and keep multiple consecutive underscores in label name when translating an OTel attribute name. This reverts the breaking changes introduced in 3.7.0. #17344


================================================================================

# 3.7.2 / 2025-10-22

Tag: v3.7.2
URL: https://github.com/prometheus/prometheus/releases/tag/v3.7.2

* [BUGFIX] AWS SD: Fix AWS SDK v2 credentials handling for EC2 and Lightsail discovery. #17355
* [BUGFIX] AWS SD: Load AWS region from IMDS when not set. #17376
* [BUGFIX] Relabeling: Fix `labelmap` action validation with the legacy metric name validation scheme. #17372
* [BUGFIX] PromQL: Fix parsing failure when `anchored` and `smoothed` are used as metric names and label names. #17353
* [BUGFIX] PromQL: Fix formatting of range vector selectors with `smoothed`/`anchored` modifier. #17354


================================================================================

# 3.7.3 / 2025-10-29

Tag: v3.7.3
URL: https://github.com/prometheus/prometheus/releases/tag/v3.7.3

* [BUGFIX] UI: Revert changed (and breaking) redirect behavior for `-web.external-url` if `-web.route-prefix` is configured, which was introduced in #17240. #17389
* [BUGFIX] Fix federation of some native histograms. #17299 #17409
* [BUGFIX] promtool: `check config` would fail when `--lint=none` flag was set. #17399 #17414
* [BUGFIX] Remote-write: fix a deadlock in the queue resharding logic that can lead to suboptimal queue behavior. #17412


================================================================================

# 3.8.0 / 2025-11-28

Tag: v3.8.0
URL: https://github.com/prometheus/prometheus/releases/tag/v3.8.0

## Note for users of Native Histograms

This is the first release with Native Histograms as a stable feature. However, scraping Native Histograms has to be activated explicitly via the `scrape_native_histograms` config setting (newly introduced in this release). To ease the transition, the `--enable-feature=native-histograms` flag is not a complete no-op in this release, but changes the default value of `scrape_native_histograms` to `true`. In the next release (v3.9), the feature flag _will_ be a complete no-op, and the default value of `scrape_native_histograms` will always be `false`. If you have been using the feature flag so far, the recommended course of action is the following:
1. Upgrade to v3.8 and keep the feature flag. Everything should work as before.
2. At your own pace, set `scrape_native_histograms` to `true` in all relevant scrape configs. (There is a global and a per-scrape-config version of  `scrape_native_histograms`, allowing granular control if needed. It is a good idea to also set `scrape_native_histograms` explicitly to `false` where you do not want to scrape Native Histograms. In this way, you do not depend on the default value of the setting anymore.)
3. Remove the feature flag and make sure that everything still works as intended.
4. Now you are ready for an upgrade to the next release (v3.9).

## Changelog

* [CHANGE] Remote-write 2 (receiving): Update to [2.0-rc.4 spec](https://github.com/prometheus/docs/blob/60c24e450010df38cfcb4f65df874f6f9b26dbcb/docs/specs/prw/remote_write_spec_2_0.md). "created timestamp" (CT) is now called "start timestamp" (ST). #17411
* [CHANGE] TSDB: Native Histogram Custom Bounds with a NaN threshold are now rejected. #17287
* [FEATURE] OAuth2: support jwt-bearer grant-type (RFC7523 3.1). #17592
* [FEATURE] Dockerfile: Add OpenContainers spec labels to Dockerfile. #16483
* [FEATURE] SD: Add unified AWS service discovery for ec2, lightsail and ecs services. #17046
* [FEATURE] Native histograms are now a stable, but optional feature, use the `scrape_native_histograms` config setting. #17232 #17315
* [FEATURE] UI: Support anchored and smoothed keyword in promql editor. #17239
* [FEATURE] UI: Show detailed relabeling steps for each discovered target. #17337
* [FEATURE] Alerting: Add urlQueryEscape to template functions. #17403
* [FEATURE] Promtool: Add  Remote-Write 2.0 support to `promtool push metrics` via the `--protobuf_message` flag. #17417
* [ENHANCEMENT] Clarify the docs about handling negative native histograms.  #17249
* [ENHANCEMENT] Mixin: Add static UID to the remote-write dashboard. #17256
* [ENHANCEMENT] PromQL: Reconcile mismatched NHCB bounds in `Add` and `Sub`. #17278
* [ENHANCEMENT] Alerting: Add "unknown" state for alerting rules that haven't been evaluated yet. #17282
* [ENHANCEMENT] Scrape: Allow simultaneous use of classic histogram → NHCB conversion and zero-timestamp ingestion. #17305
* [ENHANCEMENT] UI: Add smoothed/anchored in explain. #17334
* [ENHANCEMENT] OTLP: De-duplicate any `target_info` samples with the same timestamp for the same series. #17400
* [ENHANCEMENT] Document `use_fips_sts_endpoint` in `sigv4` config sections. #17304
* [ENHANCEMENT] Document Prometheus Agent. #14519
* [PERF] PromQL: Speed up parsing of variadic functions. #17316
* [PERF] UI: Speed up alerts/rules/... pages by not rendering collapsed content. #17485
* [PERF] UI: Performance improvement when getting label name and values in promql editor. #17194
* [PERF] UI: Speed up /alerts for many firing alerts via virtual scrolling.  #17254
* [BUGFIX] PromQL: Fix slice indexing bug in info function on churning series. #17199
* [BUGFIX] API: Reduce lock contention on `/api/v1/targets`. #17306
* [BUGFIX] PromQL: Consistent handling of gauge vs. counter histograms in aggregations. #17312
* [BUGFIX] TSDB: Allow NHCB with -Inf as the first custom value. #17320
* [BUGFIX] UI: Fix duplicate loading of data from the API speed up rendering of some pages. #17357
* [BUGFIX] Old UI: Fix createExpressionLink to correctly build /graph URLs so links from Alerts/Rules work again. #17365
* [BUGFIX] PromQL: Avoid panic when parsing malformed `info` call. #17379
* [BUGFIX] PromQL: Include histograms when enforcing sample_limit. #17390
* [BUGFIX] Config: Fix panic if TLS CA file is absent. #17418
* [BUGFIX] PromQL: Fix `histogram_fraction` for classic histograms and NHCB if lower bound is in the first bucket. #17424


================================================================================

# 3.8.1 / 2025-12-16

Tag: v3.8.1
URL: https://github.com/prometheus/prometheus/releases/tag/v3.8.1

* [BUGFIX] remote: Fix Remote Write receiver, so it does not send wrong response headers for v1 flow and cause Prometheus senders to emit false partial error log and metrics. #17683


================================================================================

# 3.9.0 / 2026-01-06

Tag: v3.9.0
URL: https://github.com/prometheus/prometheus/releases/tag/v3.9.0

## Note for users of Native Histograms

In version 3.9, Native Histograms is no longer experimental, and the feature flag `native-histogram` has no effect.  You must now turn on 
the config setting `scrape_native_histograms` to collect Native Histogram samples from exporters.

## Changelog

- [CHANGE] Native Histograms are no longer experimental! Make the `native-histogram` feature flag a no-op. Use `scrape_native_histograms` config option instead. #17528
- [CHANGE] API: Add maximum limit of 10,000 sets of statistics to TSDB status endpoint. #17647
- [FEATURE] API: Add /api/v1/features for clients to understand which features are supported. #17427
- [FEATURE] Promtool: Add `start_timestamp` field for unit tests. #17636
- [FEATURE] Promtool: Add `--format seriesjson` option to `tsdb dump` to output just series labels in JSON format. #13409
- [FEATURE] Add `--storage.tsdb.delay-compact-file.path` flag for better interoperability with Thanos. #17435
- [FEATURE] UI: Add an option on the query drop-down menu to duplicate that query panel. #17714
- [ENHANCEMENT]: TSDB: add flag `--storage.tsdb.block-reload-interval` to configure TSDB Block Reload Interval. #16728
- [ENHANCEMENT] UI: Add graph option to start the chart's Y axis at zero. #17565
- [ENHANCEMENT] Scraping: Classic protobuf format no longer requires the unit in the metric name. #16834
- [ENHANCEMENT] PromQL, Rules, SD, Scraping: Add native histograms to complement existing summaries. #17374
- [ENHANCEMENT] Notifications: Add a histogram `prometheus_notifications_latency_histogram_seconds` to complement the existing summary. #16637
- [ENHANCEMENT] Remote-write: Add custom scope support for AzureAD authentication. #17483
- [ENHANCEMENT] SD: add a `config` label with job name for most `prometheus_sd_refresh` metrics. #17138
- [ENHANCEMENT] TSDB: New histogram `prometheus_tsdb_sample_ooo_delta`, the distribution of out-of-order samples in seconds. Collected for all samples, accepted or not. #17477
- [ENHANCEMENT] Remote-read: Validate histograms received via remote-read. #17561
- [PERF] TSDB: Small optimizations to postings index. #17439
- [PERF] Scraping: Speed up relabelling of series. #17530
- [PERF] PromQL: Small optimisations in binary operators. #17524, #17519.
- [BUGFIX] UI: PromQL autocomplete now shows the correct type and HELP text for OpenMetrics counters whose samples end in `_total`. #17682
- [BUGFIX] UI: Fixed codemirror-promql incorrectly showing label completion suggestions after the closing curly brace of a vector selector. #17602
- [BUGFIX] UI: Query editor no longer suggests a duration unit if one is already present after a number. #17605
- [BUGFIX] PromQL: Fix some "vector cannot contain metrics with the same labelset" errors when experimental delayed name removal is enabled. #17678
- [BUGFIX] PromQL: Fix possible corruption of PromQL text if the query had an empty `ignoring()` and non-empty grouping. #17643
- [BUGFIX] PromQL: Fix resets/changes to return empty results for anchored selectors when all samples are outside the range. #17479
- [BUGFIX] PromQL: Check more consistently for many-to-one matching in filter binary operators. #17668
- [BUGFIX] PromQL: Fix collision in unary negation with non-overlapping series. #17708
- [BUGFIX] PromQL: Fix collision in label_join and label_replace with non-overlapping series. #17703
- [BUGFIX] PromQL: Fix bug with inconsistent results for queries with OR expression when experimental delayed name removal is enabled. #17161
- [BUGFIX] PromQL: Ensure that `rate`/`increase`/`delta` of histograms results in a gauge histogram. #17608
- [BUGFIX] PromQL: Do not panic while iterating over invalid histograms. #17559
- [BUGFIX] TSDB: Reject chunk files whose encoded chunk length overflows int. #17533
- [BUGFIX] TSDB: Do not panic during resolution reduction of invalid histograms. #17561
- [BUGFIX] Remote-write Receive: Avoid duplicate labels when experimental type-and-unit-label feature is enabled. #17546
- [BUGFIX] OTLP Receiver: Only write metadata to disk when experimental metadata-wal-records feature is enabled. #17472


================================================================================

# 3.9.1 / 2026-01-07

Tag: v3.9.1
URL: https://github.com/prometheus/prometheus/releases/tag/v3.9.1

- [BUGFIX] Agent: fix crash shortly after startup from invalid type of object. #17802
 - [BUGFIX] Scraping: fix relabel keep/drop not working. #17807


================================================================================

# 3.10.0 / 2026-02-24

Tag: v3.10.0
URL: https://github.com/prometheus/prometheus/releases/tag/v3.10.0

Prometheus now offers a distroless Docker image variant alongside the default
busybox image. The distroless variant provides enhanced security with a minimal
base image, uses UID/GID 65532 (nonroot) instead of nobody, and removes the
VOLUME declaration. Both variants are available with `-busybox` and `-distroless`
tag suffixes (e.g., `prom/prometheus:latest-busybox`, `prom/prometheus:latest-distroless`).
The busybox image remains the default with no suffix for backwards compatibility
(e.g., `prom/prometheus:latest` points to the busybox variant).

For users migrating existing **named** volumes from the busybox image to the distroless variant, the ownership can be adjusted with:
```
docker run --rm -v prometheus-data:/prometheus alpine chown -R 65532:65532 /prometheus
```
Then, the container can be started with the old volume with:
```
docker run -v prometheus-data:/prometheus prom/prometheus:latest-distroless
```
User migrating from bind mounts might need to ajust permissions too, depending on their setup.

- [CHANGE] Alerting: Add `alertmanager` dimension to following metrics: `prometheus_notifications_dropped_total`, `prometheus_notifications_queue_capacity`, `prometheus_notifications_queue_length`. #16355
- [CHANGE] UI: Hide expanded alert annotations by default, enabling more information density on the `/alerts` page. #17611
- [FEATURE] AWS SD: Add MSK Role. #17600
- [FEATURE] PromQL: Add `fill()` / `fill_left()` / `fill_right()` binop modifiers for specifying default values for missing series. #17644
- [FEATURE] Web: Add OpenAPI 3.2 specification for the HTTP API at `/api/v1/openapi.yaml`. #17825
- [FEATURE] Dockerfile: Add distroless image variant using UID/GID 65532 and no VOLUME declaration. Busybox image remains default. #17876
- [FEATURE] Web: Add on-demand wall time profiling under `<URL>/debug/pprof/fgprof`. #18027
- [ENHANCEMENT] PromQL: Add more detail to histogram quantile monotonicity info annotations. #15578
- [ENHANCEMENT] Alerting: Independent alertmanager sendloops. #16355
- [ENHANCEMENT] TSDB: Experimental support for early compaction of stale series in the memory with configurable threshold `stale_series_compaction_threshold` in the config file. #16929
- [ENHANCEMENT] Service Discovery: Service discoveries are now removable from the Prometheus binary through the Go build tag `remove_all_sd` and individual service discoveries can be re-added with the build tags `enable_<sd name>_sd`. Users can build a custom Prometheus with only the necessary SDs for a smaller binary size. #17736
- [ENHANCEMENT] Promtool: Support promql syntax features `promql-duration-expr` and `promql-extended-range-selectors`. #17926
- [PERF] PromQL: Avoid unnecessary label extraction in PromQL functions. #17676
- [PERF] PromQL: Improve performance of regex matchers like `.*-.*-.*`. #17707
- [PERF] OTLP: Add label caching for OTLP-to-Prometheus conversion to reduce allocations and improve latency. #17860
- [PERF] API: Compute `/api/v1/targets/relabel_steps` in a single pass instead of re-running relabeling for each prefix. #17969
- [PERF] tsdb: Optimize LabelValues intersection performance for matchers. #18069
- [BUGFIX] PromQL: Prevent query strings containing only UTF-8 continuation bytes from crashing Prometheus. #17735
- [BUGFIX] Web: Fix missing `X-Prometheus-Stopping` header for `/-/ready` endpoint in `NotReady` state. #17795
- [BUGFIX] PromQL: Fix PromQL `info()` function returning empty results when filtering by a label that exists on both the input metric and `target_info`. #17817
- [BUGFIX] TSDB: Fix a bug during exemplar buffer grow/shrink that could cause exemplars to be incorrectly discarded. #17863
- [BUGFIX] UI: Fix broken graph display after page reload, due to broken Y axis min encoding/decoding. #17869
- [BUGFIX] TSDB: Fix memory leaks in buffer pools by clearing reference fields (Labels, Histogram pointers, metadata strings) before returning buffers to pools. #17879
- [BUGFIX] PromQL: info function: fix series without identifying labels not being returned. #17898
- [BUGFIX] OTLP: Filter `__name__` from OTLP attributes to prevent duplicate labels. #17917
- [BUGFIX] TSDB: Fix division by zero when computing stale series ratio with empty head. #17952
- [BUGFIX] OTLP: Fix potential silent data loss for sum metrics. #17954
- [BUGFIX] PromQL: Fix smoothed interpolation across counter resets. #17988
- [BUGFIX] PromQL: Fix panic with `@` modifier on empty ranges. #18020
- [BUGFIX] PromQL: Fix `avg_over_time` for a single native histogram. #18058


================================================================================

# 3.11.0 / 2026-04-02

Tag: v3.11.0
URL: https://github.com/prometheus/prometheus/releases/tag/v3.11.0

- [CHANGE] Hetzner SD: The `__meta_hetzner_datacenter` label is deprecated for the role `robot` but kept for backward compatibility, use the `__meta_hetzner_robot_datacenter` label instead. For the role `hcloud`, the label is deprecated and will stop working after the 1 July 2026. #17850
- [CHANGE] Hetzner SD: The `__meta_hetzner_hcloud_datacenter_location` and `__meta_hetzner_hcloud_datacenter_location_network_zone` labels are deprecated, use the `__meta_hetzner_hcloud_location` and `__meta_hetzner_hcloud_location_network_zone` labels instead. #17850
- [CHANGE] Promtool: Redirect debug output to stderr to avoid interfering with stdout-based tool output. #18346
- [FEATURE] AWS SD: Add Elasticache Role. #18099
- [FEATURE] AWS SD: Add RDS Role. #18206
- [FEATURE] Azure SD: Add support for Azure Workload Identity authentication method. #17207
- [FEATURE] Discovery: Introduce `prometheus_sd_last_update_timestamp_seconds` metric to track the last time a service discovery update was sent to consumers. #18194
- [FEATURE] Kubernetes SD: Add support for node role selectors for pod roles. #18006
- [FEATURE] Kubernetes SD: Introduce pod-based labels for deployment, cronjob, and job controller names: `__meta_kubernetes_pod_deployment_name`, `__meta_kubernetes_pod_cronjob_name` and `__meta_kubernetes_pod_job_name`, respectively. #17774
- [FEATURE] PromQL: Add `</` and `>/` operators for trimming observations from native histograms. #17904
- [FEATURE] PromQL: Add experimental `histogram_quantiles` variadic function for computing multiple quantiles at once. #17285
- [FEATURE] TSDB: Add `storage.tsdb.retention.percentage` configuration to configure the maximum percent of disk usable for TSDB storage. #18080
- [FEATURE] TSDB: Add an experimental `st-storage` feature flag. When enabled, Prometheus stores ingested start timestamps (ST, previously called Created Timestamp) from scrape or OTLP in the TSDB and Agent WAL, and exposes them via Remote Write 2. #18062
- [FEATURE] TSDB: Add an experimental `xor2-encoding` feature flag for the new TSDB block float sample chunk encoding that is optimized for scraped data and allows encoding start timestamps. #18062
- [ENHANCEMENT] HTTP client: Add AWS `external_id` support for sigv4. #17916
- [ENHANCEMENT] Kubernetes SD: Deduplicate deprecation warning logs from the Kubernetes API to reduce noise. #17829
- [ENHANCEMENT] TSDB: Remove old temporary checkpoints when creating a Checkpoint. #17598
- [ENHANCEMENT] UI: Add autocomplete support for experimental `first_over_time` and `ts_of_first_over_time` PromQL functions. #18318
- [ENHANCEMENT] Vultr SD: Upgrade govultr library from v2 to v3 for continued security patches and maintenance. #18347
- [PERF] PromQL: Improve performance and reduce heap allocations in joins (VectorBinop)/And/Or/Unless. #17159
- [PERF] PromQL: Partially address performance regression in native histogram aggregations due to using `KahanAdd`. #18252
- [PERF] Remote write: Optimize WAL watching used for RW sending to reuse internal buffers. #18250
- [PERF] TSDB: Optimize LabelValues intersection performance for matchers. #18069
- [PERF] UI: Skip restacking on hover in stacked series charts. #18230
- [BUGFIX] AWS SD: Fix EC2 SD ignoring the configured `endpoint` option, a regression from the AWS SDK v2 migration. #18133
- [BUGFIX] AWS SD: Fix panic in EC2 SD when DescribeAvailabilityZones returns nil ZoneName or ZoneId. #18133
- [BUGFIX] Agent: Fix memory leak caused by duplicate SeriesRefs being loaded as active series. #17538
- [BUGFIX] Alerting: Fix alert state incorrectly resetting to pending when the FOR period is increased in the config file. #18244
- [BUGFIX] Azure SD: Fix system-assigned managed identity not working when `client_id` is empty. #18323
- [BUGFIX] Consul SD: Fix filter parameter not being applied to health service endpoint, causing Node and Node.Meta filters to be ignored. #17349
- [BUGFIX] Kubernetes SD: Fix duplicate targets generated by `*DualStack` EndpointSlices policies. #18192
- [BUGFIX] OTLP: Fix ErrTooOldSample being returned as HTTP 500 instead of 400 in PRW v2 histogram write paths, preventing infinite client retry loops. #18084
- [BUGFIX] OTLP: Fix exemplars getting mixed between incorrect parts of a histogram. #18056
- [BUGFIX] PromQL: Do not skip histogram buckets in queries where histogram trimming is used. #18263
- [BUGFIX] Remote write: Fix `prometheus_remote_storage_sent_batch_duration_seconds` measuring before the request was sent. #18214
- [BUGFIX] Rules: Fix alert state restoration when rule labels contain Go template expressions. #18375
- [BUGFIX] Scrape: Fix panic when parsing bare label names without an equal sign in brace-only metric notation. #18229
- [BUGFIX] TSDB: Fail early when `use-uncached-io` feature flag is set on unsupported environments. #18219
- [BUGFIX] TSDB: Fall back to CLI flag values when retention is removed from config file. #18200
- [BUGFIX] TSDB: Fix memory leaks in buffer pools by clearing reference fields before returning buffers to pools. #17895
- [BUGFIX] TSDB: Fix missing mmap of histogram chunks during WAL replay. #18306
- [BUGFIX] TSDB: Fix storage.tsdb.retention.time unit mismatch in file causing retention to be 1e6 times longer than configured. #18200
- [BUGFIX] Tracing: Fix missing traceID in query log when tracing is enabled, previously only spanID was emitted. #18189
- [BUGFIX] UI: Fix tooltip Y-offset drift when using multiple graph panels. #18228
- [BUGFIX] UI: Update retention display in runtime info when config is reloaded. #18200


================================================================================

# 3.11.1 / 2026-04-07

Tag: v3.11.1
URL: https://github.com/prometheus/prometheus/releases/tag/v3.11.1

- [BUGFIX] Tracing: Fix startup failure for OTLP HTTP tracing with `insecure: true`. #18469

