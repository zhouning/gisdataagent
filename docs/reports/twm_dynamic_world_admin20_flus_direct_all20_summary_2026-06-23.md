# TWM vs FLUS Dynamic World Admin20 Direct Comparison

Date: 2026-06-23

## Protocol

- Dataset: previously downloaded GEE Dynamic World admin20 rasters, 20 regions, years 2017-2023.
- Rolling cases: 100 total cases. Each case trains from `t0 -> t1` and evaluates a forecast for `t2`.
- Class space: Dynamic World classes `0..8`; FLUS receives encoded classes `1..9`; invalid/nodata pixels are excluded by the shared valid mask.
- Formal comparison set: only candidates with `candidate_metadata.demand_mode == forecast_demand`.
- Excluded from formal ranking: oracle-demand upper bound and no-demand diagnostic projection.
- FLUS backend: local `/Users/zhouning/FLUS_console_crossplatform/build/flus_console`, max iterations 30.
- FLUS suitability/probability input: adapter-generated observed train transition-prior probability cube. This is a direct FLUS CA comparison, not yet a full FLUS ANN suitability-training reproduction.
- Randomness boundary: FLUS CA source seeds with `srand(time(NULL))`; this all20 report is one stochastic realization.

Evidence files:

- `docs/reports/twm_dynamic_world_admin20_flus_direct_all20_2026-06-23.json`
- `docs/reports/twm_dynamic_world_admin20_flus_direct_pilot3x2_2026-06-23.json`
- `scripts/run_twm_dynamic_world_flus_comparison.py`

## Execution Status

All 100 cases completed:

- packaged cases: 100
- direct FLUS evaluated cases: 100
- failed FLUS executions: 0

## Formal Ranking By Mean Change FoM

| candidate | cases | mean change FoM | mean OA | mean macro F1 | target demand abs error |
|---|---:|---:|---:|---:|---:|
| `twm_ablation_no_transition_prior_forecast_demand` | 100 | 0.072606 | 0.908290 | 0.488366 | 0 |
| `twm_independent_transition_forecast_demand` | 100 | 0.072575 | 0.908293 | 0.488534 | 0 |
| `twm_cross_region_smoothed_transition_forecast_demand` | 100 | 0.072575 | 0.908293 | 0.488534 | 0 |
| `twm_ablation_no_drivers_forecast_demand` | 100 | 0.072575 | 0.908293 | 0.488534 | 0 |
| `twm_calibrated_hierarchical_transition_forecast_demand` | 100 | 0.072549 | 0.908290 | 0.488194 | 0 |
| `twm_hierarchical_transition_forecast_demand` | 100 | 0.072395 | 0.908291 | 0.487650 | 0 |
| `twm_ablation_no_neighborhood_forecast_demand` | 100 | 0.053789 | 0.905147 | 0.480950 | 0 |
| `flus_console_direct` | 100 | 0.051244 | 0.919195 | 0.522019 | 118562 |
| `markov_transition_projection` | 100 | 0.045569 | 0.903706 | 0.478585 | 0 |
| `persistence` | 100 | 0.000000 | 0.925218 | 0.554431 | 189862 |

## Paired TWM vs FLUS Results

For the main TWM independent forecast candidate compared against `flus_console_direct` on the same 100 cases:

- change FoM delta: mean +0.021331, median +0.016721; wins/losses 81/19; exact sign-test p = 2.70e-10.
- overall accuracy delta: mean -0.010902, median -0.006412; wins/losses 1/98 with 1 tie; exact sign-test p = 3.16e-28.
- macro F1 delta: mean -0.033485; exact sign-test p = 1.25e-22.
- target demand abs error delta: -118562, because the TWM demand-projected candidates exactly satisfy forecast target counts, while FLUS retains residual demand mismatch after 30 iterations.

For the hierarchical TWM forecast candidate:

- change FoM delta: mean +0.021152, median +0.016641; wins/losses 79/21; exact sign-test p = 4.34e-09.
- overall accuracy delta: mean -0.010905, median -0.006398; wins/losses 1/99; exact sign-test p = 1.59e-28.

Region-level robustness:

- TWM independent mean change FoM delta is positive in 20/20 regions.
- TWM independent mean OA delta is negative in 20/20 regions.

## Component Interpretation

- The TWM transition surface improves clearly over the Markov projection on change FoM: +0.027006 mean change FoM.
- Neighborhood context contributes strongly: full TWM is +0.018786 mean change FoM over the no-neighborhood ablation.
- Current external driver and cross-region smoothing paths are effectively neutral on this dataset.
- Current transition-prior flag is not supported as a positive component in this all20 run: the no-transition-prior ablation is only +0.000031 mean change FoM over the independent candidate, with 12 wins, 13 losses, and 75 ties. This should be treated as no meaningful effect, not as a real ablation win.
- The no-demand projection diagnostic can raise change detection but violates demand totals; it remains excluded from formal forecast claims.

## Conclusion

Under the locked forecast-demand protocol, TWM is stronger than the current direct FLUS CA adapter for change-location accuracy, as measured by change FoM and paired sign tests across all 100 rolling cases.

TWM is not stronger than FLUS on overall accuracy or macro F1 in this run. The high persistence/FLUS OA reflects the dominance of unchanged pixels, so OA should not be used alone to judge land-use change simulation quality.

The scientifically defensible conclusion is therefore metric-specific:

- Supported: TWM improves change FoM over direct FLUS CA with adapter-supplied transition-prior suitability.
- Supported: TWM demand-projected candidates exactly satisfy forecast demand totals; FLUS retains residual target-demand mismatch at 30 iterations.
- Not supported: a blanket claim that TWM beats FLUS on all accuracy metrics.
- Not yet supported: a claim against a full FLUS ANN-trained suitability workflow or against repeated seeded FLUS stochastic realizations.

## Next Required Rigor Steps

1. Add deterministic seed control to the FLUS console or run repeated FLUS realizations with controlled spacing/seeds.
2. Wire the FLUS ANN suitability-training workflow, then rerun the same 100 rolling cases.
3. Report primary metrics separately: change FoM for change allocation, OA/macro F1 for class agreement, and target-demand error for demand feasibility.
