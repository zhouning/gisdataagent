# TWM Count-Neutral Allocator v4 Progress

Date: 2026-06-24

## Scope

This report records the TWM-vs-FLUS comparison after adding a conservative count-neutral label-exchange fallback to the v3 pair-swap allocator.

- New report JSON: `docs/reports/twm_dynamic_world_admin20_flus_ann_twm_allocator_v4_all20_reused_flus_seed20260623_2026-06-24.json`
- Prior allocator v3 JSON: `docs/reports/twm_dynamic_world_admin20_flus_ann_twm_allocator_v3_all20_reused_flus_seed20260623_2026-06-24.json`
- Case set: 20 regions, 5 rolling cases per region, 100 total cases
- FLUS metrics: reused from the fixed-seed FLUS ANN report
- TWM metrics: recomputed from current code

## Allocator Change

v3 still had one high-budget miss because two-class swaps could not consume enough unchanged cells while preserving forecast demand counts. v4 keeps the v3 pair-swap allocator and adds a fallback:

1. First, run feasibility-aware count-neutral pair swaps among unchanged cells.
2. If the requested change budget is still not met, exchange predicted labels between one unchanged cell and one already changed cell.
3. Accept the exchange only when the already changed cell remains changed after receiving the unchanged cell's label.
4. This preserves class totals exactly while increasing gross change by one cell per accepted exchange.

The new regression test is:

- `test_count_neutral_swaps_use_changed_label_exchanges_after_unchanged_pairs_are_exhausted`

## Main Metrics

| Candidate | Mean change FoM | Mean OA | Mean macro-F1 | Mean change F1 | Target demand abs error |
|---|---:|---:|---:|---:|---:|
| FLUS ANN console | 0.150955 | 0.918396 | 0.505526 | 0.254339 | 186972 |
| TWM full change budget v4 | 0.154022 | 0.883117 | 0.429707 | 0.264095 | 0 |
| TWM adaptive churn75 v4 | 0.141681 | 0.889435 | 0.440850 | 0.245502 | 0 |
| TWM fixed scale 0.75 v4 | 0.133712 | 0.893594 | 0.451102 | 0.233152 | 0 |
| TWM fixed scale 0.50 v4 | 0.105882 | 0.902705 | 0.468521 | 0.188993 | 0 |
| TWM fixed scale 0.25 v4 | 0.078352 | 0.907840 | 0.485789 | 0.143290 | 0 |
| TWM independent transition | 0.072575 | 0.908293 | 0.488534 | 0.133096 | 0 |

## Comparison Against Allocator v3

The v4 fallback changes aggregate metrics only minimally:

- Full change-budget FoM: `0.154071 -> 0.154022`
- Full change-budget OA: `0.883169 -> 0.883117`
- Adaptive churn75 FoM: `0.141693 -> 0.141681`
- Adaptive churn75 OA: `0.889441 -> 0.889435`

The important change is budget reachability:

- v3 full change-budget misses: 1/100
- v4 full change-budget misses: 0/100
- v3 adaptive churn75 misses: 1/100
- v4 adaptive churn75 misses: 0/100

## Paired Comparison Against FLUS

`twm_change_budget_calibrated_forecast_demand` versus `flus_console_direct`:

- mean change FoM delta: +0.003067
- median change FoM delta: +0.018132
- wins/losses by change FoM: 54/46
- sign-test p-value for change FoM: 0.484118
- mean OA delta: -0.035279
- mean macro-F1 delta: -0.075819

`twm_change_budget_adaptive_churn75_forecast_demand` versus `flus_console_direct`:

- mean change FoM delta: -0.009274
- median change FoM delta: +0.005572
- wins/losses by change FoM: 51/49
- sign-test p-value for change FoM: 0.920411
- mean OA delta: -0.028961
- mean macro-F1 delta: -0.064676

## Current Scientific Conclusion

v4 resolves the remaining engineering reachability issue without materially changing the benchmark conclusion.

The scientific conclusion remains:

1. TWM full change-budget is competitive with FLUS on change FoM and slightly higher in mean value.
2. The change-FoM advantage is not statistically significant under the paired sign test.
3. FLUS remains substantially stronger on OA and macro-F1.
4. TWM now preserves exact forecast demand and reaches requested change budgets across all 100 cases.
5. The remaining gap is no longer budget reachability; it is spatial/class allocation quality.

## Next Step

The next experiment should target allocation quality directly. Recommended direction: add transition-level diagnostics and optimize the label-exchange/pair-swap scorer with neighborhood compatibility and per-transition penalties, while keeping forecast demand and train-only calibration fixed.
