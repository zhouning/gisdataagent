# TWM Transition Diagnostics

Date: 2026-06-24

## Scope

This report adds transition-pair diagnostics to the TWM Dynamic World vs FLUS benchmark. It is based on:

- JSON: `docs/reports/twm_dynamic_world_admin20_flus_ann_twm_transition_diag_all20_reused_flus_seed20260623_2026-06-24.json`
- Case set: 20 regions, 5 rolling cases per region, 100 total cases
- Candidate analyzed here: `twm_change_budget_calibrated_forecast_demand`
- FLUS metrics are reused from the prior fixed-seed report, so FLUS transition-pair diagnostics are not available in this JSON.

The aggregate benchmark metrics are unchanged from allocator v4:

- TWM full change-budget mean change FoM: 0.154022
- TWM full change-budget mean OA: 0.883117
- TWM full change-budget mean macro-F1: 0.429707
- FLUS ANN mean change FoM: 0.150955
- FLUS ANN mean OA: 0.918396
- FLUS ANN mean macro-F1: 0.505526

## Diagnostic Added

Each pixel metric now includes `transition_pair_metrics` rows keyed by:

- source class: `initial`
- target class: `actual` or `prediction`

For each source-target transition, the metric records:

- actual transition count
- predicted transition count
- hit count
- false alarm count
- miss count
- precision, recall, F1

## Top False-Alarm Transitions

| Source -> target | Actual | Predicted | Hit | False alarm | Miss | Precision | Recall | F1 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| trees -> shrub_and_scrub | 25149 | 19927 | 1375 | 18552 | 23774 | 0.069002 | 0.054674 | 0.061008 |
| trees -> built | 9813 | 15658 | 2060 | 13598 | 7753 | 0.131562 | 0.209926 | 0.161753 |
| crops -> built | 15863 | 16789 | 3623 | 13166 | 12240 | 0.215796 | 0.228393 | 0.221916 |
| trees -> water | 7876 | 13252 | 1254 | 11998 | 6622 | 0.094627 | 0.159218 | 0.118705 |
| built -> trees | 9676 | 14144 | 2306 | 11838 | 7370 | 0.163037 | 0.238322 | 0.193619 |
| water -> trees | 8035 | 14140 | 2333 | 11807 | 5702 | 0.164993 | 0.290355 | 0.210417 |
| built -> crops | 12325 | 14116 | 2312 | 11804 | 10013 | 0.163786 | 0.187586 | 0.174880 |
| shrub_and_scrub -> trees | 25461 | 17572 | 6421 | 11151 | 19040 | 0.365411 | 0.252190 | 0.298422 |
| trees -> crops | 17697 | 13553 | 2601 | 10952 | 15096 | 0.191913 | 0.146974 | 0.166464 |
| crops -> trees | 20670 | 12744 | 3162 | 9582 | 17508 | 0.248117 | 0.152975 | 0.189262 |

## Top Missed Transitions

| Source -> target | Actual | Predicted | Hit | False alarm | Miss | Precision | Recall | F1 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| trees -> shrub_and_scrub | 25149 | 19927 | 1375 | 18552 | 23774 | 0.069002 | 0.054674 | 0.061008 |
| shrub_and_scrub -> trees | 25461 | 17572 | 6421 | 11151 | 19040 | 0.365411 | 0.252190 | 0.298422 |
| crops -> trees | 20670 | 12744 | 3162 | 9582 | 17508 | 0.248117 | 0.152975 | 0.189262 |
| trees -> crops | 17697 | 13553 | 2601 | 10952 | 15096 | 0.191913 | 0.146974 | 0.166464 |
| crops -> built | 15863 | 16789 | 3623 | 13166 | 12240 | 0.215796 | 0.228393 | 0.221916 |
| built -> crops | 12325 | 14116 | 2312 | 11804 | 10013 | 0.163786 | 0.187586 | 0.174880 |
| water -> crops | 10697 | 11255 | 1930 | 9325 | 8767 | 0.171479 | 0.180424 | 0.175838 |
| trees -> built | 9813 | 15658 | 2060 | 13598 | 7753 | 0.131562 | 0.209926 | 0.161753 |
| water -> bare | 8704 | 4783 | 1191 | 3592 | 7513 | 0.249007 | 0.136834 | 0.176615 |
| built -> trees | 9676 | 14144 | 2306 | 11838 | 7370 | 0.163037 | 0.238322 | 0.193619 |

## Interpretation

The main loss is not a uniform failure across all land-cover transitions. It is concentrated in a small set of high-volume, low-F1 transitions:

1. vegetation-class swaps: `trees <-> shrub_and_scrub`, `trees <-> crops`, `crops <-> trees`
2. urban-related swaps: `trees -> built`, `crops -> built`, `built -> trees`, `built -> crops`
3. water/bare edge cases: `trees -> water`, `water -> trees`, `water -> crops`, `water -> bare`

This explains why change FoM can be competitive while macro-F1 remains weak. The model is creating enough gross change and some real change hits, but it is often assigning the wrong target class for the changed cells.

## Next Experiment

The next scorer should remain train-only and preserve forecast demand, but add transition-specific quality control:

1. Estimate train-period transition reliability for each source-target pair.
2. Penalize candidate swaps and label exchanges for source-target pairs with low train reliability or very low transition F1 in replay diagnostics.
3. Add neighborhood compatibility to reduce implausible isolated class jumps.
4. Keep the v4 allocator as the allocation engine; change only the score used by pair swaps and label exchanges.

Success criteria for the next experiment:

- keep full change-budget mean change FoM near or above FLUS
- improve TWM macro-F1 and OA relative to allocator v4
- avoid holdout-tuned transition penalties
