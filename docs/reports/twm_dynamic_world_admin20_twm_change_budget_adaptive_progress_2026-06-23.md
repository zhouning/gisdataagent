# TWM Change-Budget Adaptive Progress

Date: 2026-06-23

## Scope

This report records the current TWM-vs-FLUS comparison after adding a train-only adaptive change-budget scale candidate. The FLUS metrics are reused from the existing full ANN all20 report; only TWM candidates were recomputed from current code.

- New report JSON: `docs/reports/twm_dynamic_world_admin20_flus_ann_twm_adaptive_churn75_all20_reused_flus_seed20260623_2026-06-23.json`
- Previous scale-matrix JSON: `docs/reports/twm_dynamic_world_admin20_flus_ann_twm_scale_matrix_all20_reused_flus_seed20260623_2026-06-23.json`
- Case set: 20 regions, 5 rolling cases per region, 100 total cases
- FLUS protocol: local FLUS console with ANN probability training, fixed seed 20260623
- TWM protocol: forecast demand only; no holdout class totals and no holdout labels used for training

## Candidate Added

`twm_change_budget_adaptive_churn75_forecast_demand` adds a train-only adaptive scale for count-neutral swaps:

```text
adaptive_train_change = train_net_demand_change + 0.75 * train_count_neutral_churn
budget_scale = adaptive_train_change / observed_train_change
```

The rule uses only `train_start -> train_end` class counts. It does not select 0.75 from holdout performance. The metadata records:

- `scale_selection_rule = net_demand_change_plus_75pct_count_neutral_churn`
- `scale_selection_source = train_start_train_end_class_counts`
- `uses_holdout_labels_for_training = false`

Across 100 cases, adaptive scale statistics were:

- mean scale: 0.839541
- median scale: 0.834284
- range: 0.776824 to 0.983835
- budget not met: 1/100 cases

## Main Metrics

| Candidate | Mean change FoM | Mean OA | Mean macro-F1 | Mean change F1 | Target demand abs error |
|---|---:|---:|---:|---:|---:|
| FLUS ANN console | 0.150955 | 0.918396 | 0.505526 | 0.254339 | 186972 |
| TWM full change budget | 0.157738 | 0.860924 | 0.401175 | 0.267847 | 0 |
| TWM adaptive churn75 | 0.147016 | 0.870529 | 0.419270 | 0.252676 | 0 |
| TWM fixed scale 0.75 | 0.140957 | 0.877730 | 0.432468 | 0.243692 | 0 |
| TWM fixed scale 0.50 | 0.110318 | 0.895278 | 0.460437 | 0.195955 | 0 |
| TWM fixed scale 0.25 | 0.080145 | 0.907211 | 0.484757 | 0.146304 | 0 |
| TWM independent transition | 0.072575 | 0.908293 | 0.488534 | 0.133096 | 0 |
| TWM learned suitability | 0.077867 | 0.908390 | 0.487664 | 0.142081 | 0 |

## Paired Comparison Against FLUS

`twm_change_budget_adaptive_churn75_forecast_demand` versus `flus_console_direct`:

- mean change FoM delta: -0.003939
- median change FoM delta: +0.006320
- wins/losses by change FoM: 55/45
- sign-test p-value for change FoM: 0.368202
- mean OA delta: -0.047867
- wins/losses by OA: 0/100
- mean macro-F1 delta: -0.086256

Interpretation: adaptive churn75 is statistically indistinguishable from FLUS on change FoM in this 100-case benchmark, but it is clearly worse on OA and macro-F1.

## Trade-Off Curve

The change-budget scale matrix now shows a consistent trade-off:

- Raising budget strength improves change FoM and change F1.
- Raising budget strength reduces OA and macro-F1.
- Adaptive churn75 sits between fixed 0.75 and full budget:
  - vs fixed 0.75: +0.006059 change FoM, -0.007201 OA, -0.013198 macro-F1
  - vs full budget: -0.010722 change FoM, +0.009605 OA, +0.018095 macro-F1

This is useful because adaptive churn75 is not a post-hoc holdout-tuned point. It is a train-only, reproducible compromise.

## Current Scientific Conclusion

The current evidence does not support the claim that TWM comprehensively outperforms GeoSOS-FLUS/FLUS for this land simulation benchmark.

The defensible conclusions are narrower:

1. TWM's original independent transition candidate is far below FLUS on change FoM.
2. Training change-budget calibration closes most of the change-detection gap and can slightly exceed FLUS in mean change FoM.
3. That gain is not statistically significant under the current paired sign test.
4. All higher-change TWM variants are materially worse than FLUS on OA and macro-F1.
5. Adaptive churn75 gives a train-only compromise close to FLUS change FoM, but it still loses on overall categorical quality.

## Next Research Direction

The next optimization should not simply increase the change budget. The bottleneck is now spatial/class allocation quality under a higher gross-change budget.

Recommended next step:

1. Keep forecast demand and train-only calibration fixed.
2. Improve the count-neutral swap allocator so swaps are selected by pair-level opportunity cost and local neighborhood compatibility, not only by broad source-target batches.
3. Add per-class and per-transition diagnostics to identify which transitions cause macro-F1 loss.
4. Treat FLUS as a benchmark, not as the product target: TWM should preserve interpretable demand, transition, and policy components while improving allocation quality.
