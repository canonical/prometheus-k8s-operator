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

