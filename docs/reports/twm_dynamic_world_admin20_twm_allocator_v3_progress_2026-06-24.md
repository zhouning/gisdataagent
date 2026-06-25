# TWM Count-Neutral Allocator v3 Progress

Date: 2026-06-24

## Scope

This report records the TWM-vs-FLUS comparison after replacing the high-budget count-neutral swap allocator with a feasibility-aware pair selector.

- New report JSON: `docs/reports/twm_dynamic_world_admin20_flus_ann_twm_allocator_v3_all20_reused_flus_seed20260623_2026-06-24.json`
- Prior adaptive report JSON: `docs/reports/twm_dynamic_world_admin20_flus_ann_twm_adaptive_churn75_all20_reused_flus_seed20260623_2026-06-23.json`
- Case set: 20 regions, 5 rolling cases per region, 100 total cases
- FLUS metrics: reused from the fixed-seed FLUS ANN report
- TWM metrics: recomputed from current code

## Allocator Change

The previous batched allocator could over-consume one source-target class pair, leaving later count-neutral swaps unreachable even when the overall class supply could still satisfy more change budget.

The v3 allocator now:

1. Selects one currently feasible unordered class pair at a time.
2. Uses a remaining-supply feasibility check before accepting a swap.
3. Keeps larger candidate pools for common classes, so a large class can support multiple smaller class pairs.
4. Preserves forecast demand counts because each accepted operation is a paired class exchange.

Two regression tests cover these failure modes:

- `test_count_neutral_swaps_do_not_exhaust_one_class_pair_when_more_budget_is_reachable`
- `test_count_neutral_swaps_keep_extra_common_class_candidates_across_pairs`

## Main Metrics

| Candidate | Mean change FoM | Mean OA | Mean macro-F1 | Mean change F1 | Target demand abs error |
|---|---:|---:|---:|---:|---:|
| FLUS ANN console | 0.150955 | 0.918396 | 0.505526 | 0.254339 | 186972 |
| TWM full change budget v3 | 0.154071 | 0.883169 | 0.429713 | 0.264157 | 0 |
| TWM adaptive churn75 v3 | 0.141693 | 0.889441 | 0.440851 | 0.245516 | 0 |
| TWM fixed scale 0.75 v3 | 0.133712 | 0.893594 | 0.451102 | 0.233152 | 0 |
| TWM fixed scale 0.50 v3 | 0.105882 | 0.902705 | 0.468521 | 0.188993 | 0 |
| TWM fixed scale 0.25 v3 | 0.078352 | 0.907840 | 0.485789 | 0.143290 | 0 |
| TWM independent transition | 0.072575 | 0.908293 | 0.488534 | 0.133096 | 0 |

## Comparison Against Prior Allocator

Against the prior adaptive report:

- Full change-budget FoM: `0.157738 -> 0.154071`
- Full change-budget OA: `0.860924 -> 0.883169`
- Full change-budget macro-F1: `0.401175 -> 0.429713`
- Adaptive churn75 FoM: `0.147016 -> 0.141693`
- Adaptive churn75 OA: `0.870529 -> 0.889441`
- Adaptive churn75 macro-F1: `0.419270 -> 0.440851`

Interpretation: v3 gives up a small amount of change FoM to recover a meaningful amount of overall categorical quality. This is a better scientific trade-off for TWM than the previous aggressive batched allocator.

## Paired Comparison Against FLUS

`twm_change_budget_calibrated_forecast_demand` versus `flus_console_direct`:

- mean change FoM delta: +0.003116
- median change FoM delta: +0.018132
- wins/losses by change FoM: 54/46
- sign-test p-value for change FoM: 0.484118
- mean OA delta: -0.035227
- mean macro-F1 delta: -0.075813

`twm_change_budget_adaptive_churn75_forecast_demand` versus `flus_console_direct`:

- mean change FoM delta: -0.009263
- median change FoM delta: +0.005572
- wins/losses by change FoM: 51/49
- sign-test p-value for change FoM: 0.920411
- mean OA delta: -0.028955
- mean macro-F1 delta: -0.064675

## Budget Reachability

Most budget targets are met:

- fixed scale 0.25: 0 misses
- fixed scale 0.50: 0 misses
- fixed scale 0.75: 0 misses
- full change-budget: 1 miss
- adaptive churn75: 1 miss

The remaining miss is the same case: `西安市_周至县_陈河镇_2018_2019_2020`.

For that case, after the base demand allocation, the maximum reachable count-neutral pair-swap change count is 4288. The full target is 4590 and the adaptive target is 4316, so the remaining miss is a reachability limit of two-class swaps rather than the previous candidate-pool bug.

## Current Scientific Conclusion

The current evidence still does not justify saying TWM comprehensively beats GeoSOS-FLUS/FLUS.

The stronger and now more defensible conclusion is:

1. TWM full change-budget v3 slightly exceeds FLUS in mean change FoM, but not significantly.
2. v3 materially reduces the OA and macro-F1 damage compared with the previous aggressive allocator.
3. FLUS remains clearly stronger on OA and macro-F1.
4. TWM is now competitive on change-focused metrics while preserving exact forecast demand, but spatial/class allocation quality is still the main blocker.

## Next Step

The next experiment should move beyond two-class pair swaps for the rare unreachable high-budget cases. A conservative option is to add train-only, class-count-preserving multi-class cycles only when pair swaps cannot reach the requested budget. That would preserve the TWM demand constraint while allowing additional gross change without violating class totals.
