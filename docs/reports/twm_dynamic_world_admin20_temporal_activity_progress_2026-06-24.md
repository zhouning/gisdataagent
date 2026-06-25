# TWM Temporal Activity Progress

Date: 2026-06-24

## Scope

This report records the next TWM-vs-FLUS experiment after allocator v4. The goal was to improve allocation quality without using holdout labels or moving TWM toward a FLUS clone.

Inputs:

- Case set: 20 Dynamic World admin regions, 5 rolling cases per region, 100 cases total.
- FLUS baseline: reused fixed-seed FLUS ANN metrics from `docs/reports/twm_dynamic_world_admin20_flus_ann_twm_allocator_v4_all20_reused_flus_seed20260623_2026-06-24.json`.
- New all20 JSON: `docs/reports/twm_dynamic_world_admin20_flus_ann_twm_temporal_activity_reliability_all20_reused_flus_seed20260623_2026-06-24.json`.
- FLUS transition-diagnostics JSON: `docs/reports/twm_dynamic_world_admin20_flus_ann_twm_temporal_activity_reliability_flus_transition_diag_seed20260623_2026-06-24.json`.
- Replay-precision JSON: `docs/reports/twm_dynamic_world_admin20_flus_ann_twm_replay_precision_all20_reused_flus_seed20260623_2026-06-24.json`.
- Temporal-neighborhood JSON: `docs/reports/twm_dynamic_world_admin20_flus_ann_twm_temporal_neighborhood_all20_reused_flus_seed20260623_2026-06-24.json`.
- Temporal-neighborhood replay-precision JSON: `docs/reports/twm_dynamic_world_admin20_flus_ann_twm_temporal_neighborhood_replay_precision_all20_reused_flus_seed20260623_2026-06-24.json`.
- Target-transition-neighborhood replay-precision JSON: `docs/reports/twm_dynamic_world_admin20_flus_ann_twm_target_neighborhood_all20_reused_flus_seed20260623_2026-06-24.json`.
- Target-transition-neighborhood replay-precision reliability JSON: `docs/reports/twm_dynamic_world_admin20_flus_ann_twm_target_neighborhood_reliability_all20_reused_flus_seed20260623_2026-06-24.json`.
- Strict replay-precision JSON: `docs/reports/twm_dynamic_world_admin20_flus_ann_twm_strict_replay_precision_all20_reused_flus_seed20260623_2026-06-24.json`.
- Overprediction-control JSON: `docs/reports/twm_dynamic_world_admin20_flus_ann_twm_overprediction_control_all20_reused_flus_seed20260623_2026-06-24.json`.
- Product-modes JSON: `docs/reports/twm_dynamic_world_admin20_flus_ann_twm_product_modes_all20_reused_flus_seed20260623_2026-06-24.json`.
- Balanced-modes JSON: `docs/reports/twm_dynamic_world_admin20_flus_ann_twm_balanced_modes_all20_reused_flus_seed20260623_2026-06-24.json`.
- Balanced-frontier JSON: `docs/reports/twm_dynamic_world_admin20_flus_ann_twm_balanced_frontier_all20_reused_flus_seed20260623_2026-06-24.json`.
- Markov-demand JSON: `docs/reports/twm_dynamic_world_admin20_flus_ann_twm_markov_demand_all20_reused_flus_seed20260623_2026-06-24.json`.
- Persistence-demand JSON: `docs/reports/twm_dynamic_world_admin20_flus_ann_twm_persistence_demand_all20_reused_flus_seed20260623_2026-06-24.json`.
- Persistence-frontier JSON: `docs/reports/twm_dynamic_world_admin20_flus_ann_twm_persistence_frontier_all20_reused_flus_seed20260623_2026-06-24.json`.
- Demand projection diagnostics are embedded in the refreshed persistence-frontier JSON under `formal_forecast_comparison.demand_projection_diagnostics`.
- Region false-alarm guard JSON: `docs/reports/twm_dynamic_world_admin20_flus_ann_twm_region_false_alarm_guard_all20_reused_flus_seed20260623_2026-06-24.json`.
- Pair false-alarm guard JSON: `docs/reports/twm_dynamic_world_admin20_flus_ann_twm_pair_false_alarm_guard_all20_reused_flus_seed20260623_2026-06-24.json`.
- Verification command: `/Users/zhouning/gisdataagent/.venv/bin/python -m pytest data_agent/test_twm_dynamic_world_flus_comparison.py data_agent/test_twm_dynamic_world_flus_seed_summary.py -q`.

## Implemented Candidates

New train-only candidates:

1. `twm_transition_reliability_change_budget_forecast_demand`
   - Penalizes low-reliability source-target transitions estimated from `train_start -> train_end`.
2. `twm_transition_reliability_swap_change_budget_forecast_demand`
   - Keeps allocator v4 base allocation and applies transition reliability only to count-neutral swaps.
3. `twm_temporal_activity_change_budget_forecast_demand`
   - Boosts non-persistence scores for cells that changed during `train_start -> train_end`.
4. `twm_temporal_activity_reliability_change_budget_forecast_demand`
   - Applies temporal activity boost and transition reliability penalty together.
5. `twm_temporal_activity_replay_precision_change_budget_forecast_demand`
   - Uses train-period replay transition precision to penalize low-precision source-target transitions, then applies the same forecast-demand change-budget allocator.
6. `twm_temporal_activity_neighborhood_change_budget_forecast_demand`
   - Adds a neighborhood recent-change activity field so cells near recent training changes receive non-persistence score support.
7. `twm_temporal_activity_neighborhood_replay_precision_change_budget_forecast_demand`
   - Combines neighborhood recent-change activity with train-replay transition precision guarding.
8. `twm_temporal_activity_target_neighborhood_replay_precision_change_budget_forecast_demand`
   - Adds target-specific train transition neighborhood density, then applies the same train-replay transition precision guard.
9. `twm_temporal_activity_target_neighborhood_replay_precision_reliability_change_budget_forecast_demand`
   - Applies train source-target transition reliability after target-specific neighborhood and replay-precision scoring.
10. `twm_temporal_activity_target_neighborhood_strict_replay_precision_change_budget_forecast_demand`
   - Uses a stricter train-replay transition precision guard to suppress low-precision source-target transitions.
11. `twm_temporal_activity_target_neighborhood_strict_replay_precision_overprediction_change_budget_forecast_demand`
   - Adds a train-replay overprediction guard for source-target pairs with high predicted/actual transition ratios and low replay precision.
12. `twm_conservative_map_mode_forecast_demand`
   - Exposes the independent transition forecast as a product-level conservative map mode for OA/macro-F1-oriented use.
13. `twm_balanced_strict_overprediction_churn75_forecast_demand`
   - Uses the strict replay-precision + overprediction score with train-only adaptive churn75 change-budget scaling.
   - This is a product-level balanced map mode, not a replacement for the change-discovery optimum.
14. `twm_balanced_strict_overprediction_churn50_forecast_demand` and `twm_balanced_strict_overprediction_churn90_forecast_demand`
   - Bound the train-only churn frontier around the default balanced mode.
   - Churn50 is a stability-leaning diagnostic; churn90 is a change-leaning diagnostic.
15. `twm_balanced_strict_overprediction_churn75_markov_forecast_demand`
   - Keeps the balanced churn75 spatial allocation but replaces linear class-total demand projection with train-only Markov demand.
   - This tests whether demand projection error is part of the OA/macro-F1 gap.
16. `twm_balanced_strict_overprediction_churn75_persistence_forecast_demand`
   - Keeps the balanced churn75 spatial allocation but uses train_end class totals as a no-net-demand scenario.
   - This tests whether a conservative demand scenario can retain TWM change-discovery power while improving map-level metrics.
17. `twm_balanced_strict_overprediction_churn50_persistence_forecast_demand` and `twm_balanced_strict_overprediction_churn90_persistence_forecast_demand`
   - Bound the persistence-demand churn frontier.
   - Churn50 is the most map-aware nonzero-change mode so far; churn90 is now the strongest change-discovery mode.
18. `twm_region_false_alarm_guarded_persistence_forecast_demand`
   - Uses train-replay change precision to lower the persistence-demand churn fraction from 0.9 toward 0.5 in regions where the train replay has high false-alarm pressure.
   - This is a train-only diagnostic for the 2023 per-region false-alarm issue; it does not use holdout labels.
19. `twm_pair_false_alarm_guarded_persistence_forecast_demand`
   - Adds a train-replay source-target false-alarm pressure guard after strict replay precision and overprediction control.
   - It penalizes transition pairs with low train-replay precision and high false-alarm rate, then uses persistence demand with churn90.
   - This targets spatial allocation quality for false-alarm-prone transition pairs rather than lowering total change budget.

All candidates preserve forecast demand exactly and use no holdout labels for training.

## Why Temporal Activity Was Added

The intermediate diagnostic rejected a simple stability-guard hypothesis. Cells that changed in the training period were not mostly noise; they were strongly predictive of future activity:

- Recent-change cells: 253,383 / 3,182,460 valid cells, about 8.0%.
- Actual holdout changes on recent-change cells: 113,267 / 248,107, about 45.7%.
- Allocator v4 predicted changes on recent-change cells: 61,706 / 253,423, about 24.4%.

Therefore the correct train-only direction was to boost recent temporal activity, not suppress it.

## Main Metrics

| Candidate | Mean change FoM | Mean OA | Mean macro-F1 | Mean change F1 | Target demand abs error |
|---|---:|---:|---:|---:|---:|
| FLUS ANN console | 0.150955 | 0.918396 | 0.505526 | 0.254339 | 186972 |
| TWM v4 full change budget | 0.154022 | 0.883117 | 0.429707 | 0.264095 | 0 |
| TWM temporal activity | 0.172645 | 0.885775 | 0.431404 | 0.291668 | 0 |
| TWM temporal activity + reliability | 0.171835 | 0.886015 | 0.438180 | 0.290496 | 0 |
| TWM temporal activity + replay precision | 0.174051 | 0.886081 | 0.432671 | 0.293715 | 0 |
| TWM temporal activity + neighborhood | 0.175059 | 0.886150 | 0.431105 | 0.295118 | 0 |
| TWM temporal activity + neighborhood + replay precision | 0.176506 | 0.886463 | 0.432618 | 0.297229 | 0 |
| TWM temporal activity + target neighborhood + replay precision | 0.176721 | 0.886554 | 0.432381 | 0.297521 | 0 |
| TWM temporal activity + target neighborhood + replay precision + reliability | 0.175884 | 0.886756 | 0.439970 | 0.296340 | 0 |
| TWM temporal activity + target neighborhood + strict replay precision | 0.181125 | 0.887294 | 0.431895 | 0.304059 | 0 |
| TWM temporal activity + target neighborhood + strict replay precision + overprediction control | 0.183793 | 0.887832 | 0.433352 | 0.307912 | 0 |
| TWM balanced strict overprediction churn50 | 0.152786 | 0.899289 | 0.459888 | 0.262700 | 0 |
| TWM balanced strict overprediction churn75 | 0.170797 | 0.893761 | 0.446161 | 0.289327 | 0 |
| TWM balanced strict overprediction churn90 | 0.179065 | 0.890257 | 0.438353 | 0.301217 | 0 |
| TWM balanced strict overprediction churn75 + Markov demand | 0.172665 | 0.895121 | 0.469955 | 0.292507 | 0 |
| TWM balanced strict overprediction churn50 + persistence demand | 0.166980 | 0.904069 | 0.492396 | 0.284016 | 0 |
| TWM balanced strict overprediction churn75 + persistence demand | 0.182869 | 0.898241 | 0.476059 | 0.306740 | 0 |
| TWM balanced strict overprediction churn90 + persistence demand | 0.190345 | 0.894604 | 0.466998 | 0.317124 | 0 |
| TWM reliability swap-only | 0.153042 | 0.883263 | 0.435483 | 0.262687 | 0 |
| TWM adaptive churn75 | 0.141681 | 0.889435 | 0.440850 | 0.245502 | 0 |
| TWM conservative map mode | 0.072575 | 0.908293 | 0.488534 | 0.133096 | 0 |
| TWM independent transition | 0.072575 | 0.908293 | 0.488534 | 0.133096 | 0 |

## Paired Comparison

Temporal activity versus FLUS:

- Mean change FoM delta: +0.021690.
- Median change FoM delta: +0.028742.
- Wins/losses by change FoM: 65/35.
- Sign-test p-value for change FoM: 0.003518.
- Mean change F1 delta: +0.037330.
- Mean OA delta: -0.032622.
- Mean macro-F1 delta: -0.074123.

Temporal activity versus allocator v4:

- Mean change FoM delta: +0.018623.
- Median change FoM delta: +0.018290.
- Wins/losses by change FoM: 100/0.
- Mean OA delta: +0.002658.
- Mean macro-F1 delta: +0.001696.
- Mean change F1 delta: +0.027573.

Temporal activity + replay precision versus temporal activity:

- Mean change FoM delta: +0.001406.
- Median change FoM delta: +0.001039.
- Wins/losses/ties by change FoM: 68/13/19.
- Mean OA delta: +0.000306.
- Mean macro-F1 delta: +0.001267.
- Mean change F1 delta: +0.002047.

Temporal activity + replay precision versus FLUS:

- Mean change FoM delta: +0.023096.
- Median change FoM delta: +0.030112.
- Wins/losses by change FoM: 65/35.
- Sign-test p-value for change FoM: 0.003518.
- Mean change F1 delta: +0.039376.
- Mean OA delta: -0.032316.
- Mean macro-F1 delta: -0.072855.

Temporal activity + neighborhood versus FLUS:

- Mean change FoM delta: +0.024104.
- Median change FoM delta: +0.030290.
- Wins/losses by change FoM: 66/34.
- Sign-test p-value for change FoM: 0.001790.
- Mean change F1 delta: +0.040779.
- Mean OA delta: -0.032246.
- Mean macro-F1 delta: -0.074422.

Temporal activity + neighborhood versus replay precision:

- Mean change FoM delta: +0.001008.
- Median change FoM delta: +0.000906.
- Wins/losses/ties by change FoM: 60/33/7.
- Mean OA delta: +0.000070.
- Mean macro-F1 delta: -0.001566.
- Mean change F1 delta: +0.001403.

Temporal activity + neighborhood + replay precision versus FLUS:

- Mean change FoM delta: +0.025551.
- Median change FoM delta: +0.031310.
- Wins/losses by change FoM: 66/34.
- Sign-test p-value for change FoM: 0.001790.
- Mean change F1 delta: +0.042890.
- Mean OA delta: -0.031934.
- Mean macro-F1 delta: -0.072908.

Temporal activity + neighborhood + replay precision versus neighborhood-only:

- Mean change FoM delta: +0.001447.
- Median change FoM delta: +0.000903.
- Wins/losses/ties by change FoM: 63/22/15.
- Mean OA delta: +0.000312.
- Mean macro-F1 delta: +0.001513.
- Mean change F1 delta: +0.002111.

Temporal activity + target neighborhood + replay precision versus FLUS:

- Mean change FoM delta: +0.025766.
- Median change FoM delta: +0.030091.
- Wins/losses by change FoM: 68/32.
- Sign-test p-value for change FoM: 0.000409.
- Mean change F1 delta: +0.043182.
- Mean OA delta: -0.031843.
- Mean macro-F1 delta: -0.073145.

Temporal activity + target neighborhood + replay precision versus neighborhood + replay precision:

- Mean change FoM delta: +0.000216.
- Median change FoM delta: +0.000000.
- Wins/losses/ties by change FoM: 49/37/14.
- Sign-test p-value for change FoM: 0.235380.
- Mean OA delta: +0.000091.
- Mean macro-F1 delta: -0.000237.
- Mean change F1 delta: +0.000292.

Temporal activity + target neighborhood + replay precision + reliability versus FLUS:

- Mean change FoM delta: +0.024928.
- Median change FoM delta: +0.029299.
- Wins/losses by change FoM: 66/34.
- Sign-test p-value for change FoM: 0.001790.
- Mean change F1 delta: +0.042001.
- Mean OA delta: -0.031640.
- Mean macro-F1 delta: -0.065556.

Temporal activity + target neighborhood + replay precision + reliability versus target neighborhood + replay precision:

- Mean change FoM delta: -0.000838.
- Median change FoM delta: -0.000562.
- Wins/losses/ties by change FoM: 40/56/4.
- Sign-test p-value for change FoM: 0.125346.
- Mean OA delta: +0.000202.
- Mean macro-F1 delta: +0.007589.
- Mean change F1 delta: -0.001181.
- Mean exact transition FoM delta: +0.002652.
- Wins/losses/ties by exact transition FoM: 78/19/3.
- Sign-test p-value for exact transition FoM: 1.15e-09.

Temporal activity + target neighborhood + strict replay precision versus FLUS:

- Mean change FoM delta: +0.030169.
- Median change FoM delta: +0.035800.
- Wins/losses by change FoM: 71/29.
- Sign-test p-value for change FoM: 3.22e-05.
- Mean change F1 delta: +0.049720.
- Mean OA delta: -0.031103.
- Mean macro-F1 delta: -0.073632.

Temporal activity + target neighborhood + strict replay precision versus target neighborhood + replay precision:

- Mean change FoM delta: +0.004403.
- Median change FoM delta: +0.003723.
- Wins/losses/ties by change FoM: 80/13/7.
- Sign-test p-value for change FoM: 6.22e-13.
- Mean OA delta: +0.000740.
- Mean macro-F1 delta: -0.000486.
- Mean change F1 delta: +0.006538.
- Mean exact transition FoM delta: +0.002892.
- Wins/losses/ties by exact transition FoM: 82/12/6.
- Sign-test p-value for exact transition FoM: 5.62e-14.

Temporal activity + target neighborhood + strict replay precision + overprediction control versus FLUS:

- Mean change FoM delta: +0.032838.
- Median change FoM delta: +0.037878.
- Wins/losses by change FoM: 71/29.
- Sign-test p-value for change FoM: 3.22e-05.
- Mean change F1 delta: +0.053573.
- Mean OA delta: -0.030564.
- Mean macro-F1 delta: -0.072174.

Temporal activity + target neighborhood + strict replay precision + overprediction control versus strict replay precision:

- Mean change FoM delta: +0.002669.
- Median change FoM delta: +0.001495.
- Wins/losses/ties by change FoM: 73/20/7.
- Sign-test p-value for change FoM: 2.92e-08.
- Mean OA delta: +0.000539.
- Mean macro-F1 delta: +0.001458.
- Mean change F1 delta: +0.003853.
- Mean exact transition FoM delta: +0.002214.
- Wins/losses/ties by exact transition FoM: 83/12/5.
- Sign-test p-value for exact transition FoM: 3.21e-14.

Temporal activity + reliability versus temporal activity:

- Mean change FoM delta: -0.000810.
- Wins/losses by change FoM: 40/52, 8 ties.
- Mean OA delta: +0.000240.
- Mean macro-F1 delta: +0.006776.
- Mean change F1 delta: -0.001173.

## Change Counts

| Candidate | Predicted change | Actual change | Change hit | False alarm | Miss | Correct cells |
|---|---:|---:|---:|---:|---:|---:|
| FLUS ANN console | 86788 | 248107 | 40342 | 46446 | 207765 | 2913066 |
| TWM v4 full change budget | 253423 | 248107 | 70418 | 183005 | 177689 | 2794070 |
| TWM temporal activity | 253423 | 248107 | 76303 | 177120 | 171804 | 2802706 |
| TWM temporal activity + reliability | 253423 | 248107 | 76067 | 177356 | 172040 | 2803600 |
| TWM temporal activity + replay precision | 253423 | 248107 | 76831 | 176592 | 171276 | 2803722 |
| TWM temporal activity + neighborhood | 253423 | 248107 | 77242 | 176181 | 170865 | 2803921 |
| TWM temporal activity + neighborhood + replay precision | 253423 | 248107 | 77755 | 175668 | 170352 | 2804959 |
| TWM temporal activity + target neighborhood + replay precision | 253423 | 248107 | 77875 | 175548 | 170232 | 2805245 |
| TWM temporal activity + target neighborhood + replay precision + reliability | 253423 | 248107 | 77589 | 175834 | 170518 | 2806007 |
| TWM temporal activity + target neighborhood + strict replay precision | 253423 | 248107 | 79169 | 174254 | 168938 | 2807692 |
| TWM temporal activity + target neighborhood + strict replay precision + overprediction control | 253423 | 248107 | 80031 | 173392 | 168076 | 2809482 |

Temporal activity improves allocator v4 by adding 5,885 change hits and removing 5,885 false alarms while keeping the same predicted-change budget.
Replay precision improves temporal activity by adding another 528 change hits and removing another 528 false alarms while preserving the same predicted-change budget.
Neighborhood activity improves replay precision by adding another 411 change hits and removing another 411 false alarms while preserving the same predicted-change budget.
Adding replay precision to neighborhood activity adds another 513 change hits and removes another 513 false alarms while preserving the same predicted-change budget.
Target-specific transition neighborhood activity adds another 120 change hits and removes another 120 false alarms while preserving the same predicted-change budget. The gain is positive but small and not significant against the previous best candidate by paired sign test.
Adding transition reliability after the target-neighborhood replay-precision score gives back 286 change hits, but improves total correct cells by 762 and raises macro-F1 by 0.007589. This creates a separate transition/macro-F1 front rather than a new change-FoM front.
Strict train-replay precision adds 1,294 change hits and removes 1,294 false alarms relative to target-neighborhood replay precision while preserving the same predicted-change budget.
Overprediction control adds another 862 change hits and removes another 862 false alarms relative to strict train-replay precision while preserving the same predicted-change budget.

## Temporal Stratification

Temporal activity is robust against allocator v4 in every holdout year, but not uniformly superior to FLUS in every year.

| Holdout year | Cases | Activity mean FoM | v4 mean FoM | FLUS mean FoM | Activity - v4 | Activity - FLUS | Wins/losses vs FLUS |
|---|---:|---:|---:|---:|---:|---:|---:|
| 2019 | 20 | 0.181216 | 0.164463 | 0.125923 | +0.016753 | +0.055293 | 18/2 |
| 2020 | 20 | 0.166182 | 0.146599 | 0.156842 | +0.019584 | +0.009341 | 10/10 |
| 2021 | 20 | 0.161952 | 0.146611 | 0.133523 | +0.015342 | +0.028429 | 16/4 |
| 2022 | 20 | 0.179626 | 0.162149 | 0.150058 | +0.017478 | +0.029568 | 12/8 |
| 2023 | 20 | 0.174247 | 0.150291 | 0.188430 | +0.023957 | -0.014183 | 9/11 |

The 2023 stratum prevents a broad claim that TWM now wins every temporal setting. In 2023, FLUS keeps higher precision by predicting far fewer changes while still hitting many true changes.

With replay precision, the same temporal pattern remains:

- 2019: mean change FoM 0.182982, delta vs FLUS +0.057058, wins/losses 18/2.
- 2020: mean change FoM 0.167680, delta vs FLUS +0.010838, wins/losses 10/10.
- 2021: mean change FoM 0.163696, delta vs FLUS +0.030172, wins/losses 16/4.
- 2022: mean change FoM 0.180815, delta vs FLUS +0.030757, wins/losses 12/8.
- 2023: mean change FoM 0.175082, delta vs FLUS -0.013348, wins/losses 9/11.

With neighborhood activity, the 2023 gap narrows but does not close:

- 2019: mean change FoM 0.183722, delta vs FLUS +0.057799, wins/losses 18/2.
- 2020: mean change FoM 0.168441, delta vs FLUS +0.011600, wins/losses 10/10.
- 2021: mean change FoM 0.165492, delta vs FLUS +0.031968, wins/losses 16/4.
- 2022: mean change FoM 0.181863, delta vs FLUS +0.031805, wins/losses 13/7.
- 2023: mean change FoM 0.175777, delta vs FLUS -0.012653, wins/losses 9/11.

With neighborhood + replay precision, the 2023 gap narrows again but still does not close:

- 2019: mean change FoM 0.185480, delta vs FLUS +0.059557, wins/losses 18/2.
- 2020: mean change FoM 0.170116, delta vs FLUS +0.013275, wins/losses 10/10.
- 2021: mean change FoM 0.167254, delta vs FLUS +0.033730, wins/losses 16/4.
- 2022: mean change FoM 0.183608, delta vs FLUS +0.033550, wins/losses 13/7.
- 2023: mean change FoM 0.176071, delta vs FLUS -0.012359, wins/losses 9/11.

With target-specific transition neighborhood + replay precision, the overall win count improves, but 2023 still remains below FLUS:

- 2019: mean change FoM 0.185781, delta vs FLUS +0.059858, wins/losses 18/2.
- 2020: mean change FoM 0.170096, delta vs FLUS +0.013255, wins/losses 10/10.
- 2021: mean change FoM 0.167479, delta vs FLUS +0.033955, wins/losses 17/3.
- 2022: mean change FoM 0.183946, delta vs FLUS +0.033888, wins/losses 14/6.
- 2023: mean change FoM 0.176305, delta vs FLUS -0.012125, wins/losses 9/11.

With target-specific transition neighborhood + replay precision + reliability, change FoM drops slightly and 2023 still remains below FLUS:

- 2019: mean change FoM 0.185271, delta vs FLUS +0.059347, wins/losses 18/2.
- 2020: mean change FoM 0.167518, delta vs FLUS +0.010676, wins/losses 10/10.
- 2021: mean change FoM 0.168623, delta vs FLUS +0.035100, wins/losses 16/4.
- 2022: mean change FoM 0.182438, delta vs FLUS +0.032380, wins/losses 13/7.
- 2023: mean change FoM 0.175569, delta vs FLUS -0.012861, wins/losses 9/11.

With strict train-replay precision, change FoM improves in every holdout year, but 2023 still remains below FLUS on mean FoM:

- 2019: mean change FoM 0.191212, delta vs FLUS +0.065288, wins/losses 18/2.
- 2020: mean change FoM 0.174741, delta vs FLUS +0.017900, wins/losses 10/10.
- 2021: mean change FoM 0.172132, delta vs FLUS +0.038608, wins/losses 19/1.
- 2022: mean change FoM 0.188315, delta vs FLUS +0.038257, wins/losses 14/6.
- 2023: mean change FoM 0.179223, delta vs FLUS -0.009207, wins/losses 10/10.

With strict train-replay precision + overprediction control, change FoM improves again in every holdout year, but 2023 still remains below FLUS on mean FoM:

- 2019: mean change FoM 0.195472, delta vs FLUS +0.069549, wins/losses 18/2.
- 2020: mean change FoM 0.177768, delta vs FLUS +0.020927, wins/losses 10/10.
- 2021: mean change FoM 0.175278, delta vs FLUS +0.041755, wins/losses 19/1.
- 2022: mean change FoM 0.190349, delta vs FLUS +0.040291, wins/losses 14/6.
- 2023: mean change FoM 0.180099, delta vs FLUS -0.008331, wins/losses 10/10.

With balanced strict-overprediction churn75, OA and macro-F1 improve versus the change-discovery candidate in every case, but change FoM drops and 2023 still remains below FLUS:

- 2019: mean change FoM 0.182758, delta vs FLUS +0.056835, wins/losses 18/2.
- 2020: mean change FoM 0.165199, delta vs FLUS +0.008358, wins/losses 10/10.
- 2021: mean change FoM 0.163177, delta vs FLUS +0.029654, wins/losses 15/5.
- 2022: mean change FoM 0.173081, delta vs FLUS +0.023023, wins/losses 12/8.
- 2023: mean change FoM 0.169768, delta vs FLUS -0.018662, wins/losses 10/10.

Balanced churn75 versus the change-discovery candidate:

- Change FoM: mean delta -0.012997, wins/losses 5/95.
- OA: mean delta +0.005929, wins/losses 100/0.
- Macro-F1: mean delta +0.012809, wins/losses 100/0.
- Versus FLUS on change FoM: mean delta +0.019841, wins/losses 65/35, sign-test p-value 0.003518.

The strict-overprediction churn frontier shows a clear tradeoff:

| Candidate | Mean change FoM | Mean OA | Mean macro-F1 | Change FoM delta vs FLUS | Wins/losses vs FLUS | Sign-test p |
|---|---:|---:|---:|---:|---:|---:|
| Churn50 | 0.152786 | 0.899289 | 0.459888 | +0.001831 | 57/43 | 0.193348 |
| Churn75 | 0.170797 | 0.893761 | 0.446161 | +0.019841 | 65/35 | 0.003518 |
| Churn90 | 0.179065 | 0.890257 | 0.438353 | +0.028110 | 69/31 | 0.000183 |

Interpretation:

1. Churn50 is not strong enough for a formal "beats FLUS on change FoM" claim because the sign-test p-value is not significant and 2020, 2022 and 2023 mean deltas are not positive.
2. Among linear-demand frontier candidates, churn75 is the best balanced setting because it preserves a significant change-FoM advantage while improving map-level metrics versus the change-discovery optimum.
3. Churn90 is useful as a change-leaning balanced diagnostic, but it gives up much of the OA/macro-F1 recovery relative to churn75.

With Markov demand, the balanced mode improves again:

- Mean change FoM: 0.172665 versus FLUS 0.150955, delta +0.021710.
- Wins/losses by change FoM versus FLUS: 67/33, sign-test p-value 0.000874.
- Mean OA: 0.895121 versus 0.893761 for linear-demand churn75.
- Mean macro-F1: 0.469955 versus 0.446161 for linear-demand churn75.
- Oracle demand abs error: 280958 versus 325410 for linear-demand TWM candidates and 226042 for FLUS.

Interpretation:

1. Demand projection is a real contributor to the OA/macro-F1 gap.
2. Markov demand is train-only and improves the balanced candidate without using holdout class totals.
3. It still does not close the gap to FLUS: FLUS remains higher on OA, macro-F1 and oracle demand error.

With persistence demand, the balanced mode improves more strongly:

- Mean change FoM: 0.182869 versus FLUS 0.150955, delta +0.031914.
- Wins/losses by change FoM versus FLUS: 66/34, sign-test p-value 0.001790.
- Mean OA: 0.898241 versus 0.895121 for Markov-demand balanced and 0.893761 for linear-demand balanced.
- Mean macro-F1: 0.476059 versus 0.469955 for Markov-demand balanced and 0.446161 for linear-demand balanced.
- Oracle demand abs error: 198886 versus FLUS 226042, Markov-demand TWM 280958 and linear-demand TWM 325410.
- 2023 remains unresolved: mean change FoM delta versus FLUS is -0.007863, wins/losses 10/10.

Interpretation:

1. The current Dynamic World rolling benchmark is better served by a no-net-demand scenario than by the simple linear trend demand projection.
2. Persistence demand is not a no-change model here: TWM still performs spatial count-neutral changes through the churn budget.
3. This is the strongest product-layer TWM mode so far, but FLUS still leads on OA and macro-F1.

The persistence-demand churn frontier changes the current best:

| Candidate | Mean change FoM | Mean OA | Mean macro-F1 | Change FoM delta vs FLUS | Wins/losses vs FLUS | Sign-test p | Oracle demand error |
|---|---:|---:|---:|---:|---:|---:|---:|
| Persistence churn50 | 0.166980 | 0.904069 | 0.492396 | +0.016025 | 62/38 | 0.020979 | 198886 |
| Persistence churn75 | 0.182869 | 0.898241 | 0.476059 | +0.031914 | 66/34 | 0.001790 | 198886 |
| Persistence churn90 | 0.190345 | 0.894604 | 0.466998 | +0.039389 | 68/32 | 0.000409 | 198886 |

Interpretation:

1. Persistence churn90 is now the strongest change-discovery candidate by mean change FoM.
2. Persistence churn50 is the closest current nonzero-change TWM mode to FLUS on map metrics while still significantly beating FLUS on change FoM.
3. The 2023 stratum is nearly closed but not yet won: persistence churn90 has mean change FoM delta -0.000843 versus FLUS and 10/10 wins/losses.
4. All persistence-demand frontier modes beat FLUS on oracle demand error: 198886 versus FLUS 226042.

## Demand Projection Diagnostics

The refreshed formal report now separates two quantities that were easy to conflate:

1. Demand target error: L1 absolute error between a candidate's supplied `target_counts` and the holdout oracle class counts.
2. Realized output demand error: L1 absolute error between the final simulated map counts and the holdout oracle class counts.

FLUS is supplied with the adapter's linear forecast demand target. That target has a total demand target error of 325410 across the 100 cases, but the realized FLUS output has oracle demand error 226042 because FLUS does not exactly preserve the supplied demand in all cases. TWM frontier modes preserve their selected demand targets exactly, so their realized output demand error equals their selected demand target error.

Demand target error ranking:

| Demand target | Total target-vs-oracle error | Delta vs FLUS supplied target | Wins/losses vs FLUS supplied target |
|---|---:|---:|---:|
| Persistence demand | 198886 | -126524 | 85/14 |
| Markov demand | 280958 | -44452 | 93/6 |
| Linear/FLUS-supplied demand | 325410 | 0 | 0/0 |

Year-stratified target-vs-oracle error:

| Holdout year | Persistence demand | Markov demand | Linear/FLUS-supplied demand |
|---|---:|---:|---:|
| 2019 | 42010 | 60208 | 65996 |
| 2020 | 50052 | 67670 | 77834 |
| 2021 | 32572 | 52426 | 63626 |
| 2022 | 42142 | 53478 | 59712 |
| 2023 | 32110 | 47176 | 58242 |

Interpretation:

1. Persistence demand is the best demand target on every holdout year in this 20-region benchmark.
2. Markov demand also beats the linear/FLUS-supplied target on target-vs-oracle error, but it remains worse than persistence demand.
3. This explains why persistence improves TWM's map-aware modes without violating the no-holdout-training rule.
4. It does not by itself prove that persistence demand is universally better; the next robustness check should test whether this no-net-demand behavior holds on additional regions or alternative temporal splits.

## 2023 Temporal Stratum Diagnostics

The refreshed formal report also adds `temporal_strata_vs_flus`, which aggregates each TWM candidate against FLUS by holdout year. This separates per-case mean change FoM from pixel-weighted micro change FoM and tracks hit, false alarm and miss deltas.

For the current change-discovery candidate, `twm_balanced_strict_overprediction_churn90_persistence_forecast_demand`:

| Holdout year | Mean change FoM delta | Micro change FoM delta | Wins/losses | Hit delta | False alarm delta | Miss delta | Pattern |
|---|---:|---:|---:|---:|---:|---:|---|
| 2019 | +0.074050 | +0.111224 | 18/2 | +11602 | +21905 | -11602 | both positive |
| 2020 | +0.035014 | +0.062668 | 11/9 | +8327 | +22731 | -8327 | both positive |
| 2021 | +0.046843 | +0.071783 | 17/3 | +8414 | +21721 | -8414 | both positive |
| 2022 | +0.041884 | +0.074518 | 12/8 | +8700 | +20506 | -8700 | both positive |
| 2023 | -0.000843 | +0.019780 | 10/10 | +5564 | +22426 | -5564 | micro positive, mean negative |

Interpretation:

1. The remaining 2023 issue is not a demand-projection failure: persistence demand is also best in 2023 by target-vs-oracle error.
2. It is not a pixel-weighted total failure either: in 2023, TWM's micro change FoM is higher than FLUS by +0.019780.
3. The unresolved gap is case-weighted fairness across regions. TWM captures more changed pixels in aggregate, but its extra false alarms hurt enough small and medium regions that the per-case mean delta remains slightly negative.
4. The next optimization should therefore be a train-only, region-sensitive false-alarm control or product-mode gate, not another demand-projection change.

## Region False-Alarm Guard

The first train-only region-sensitive guard was tested after the 2023 diagnostic. It lowers the persistence-demand churn fraction when train-replay change precision is below a target threshold. This is deliberately conservative and uses only `train_start -> train_end` replay metrics.

All20 comparison:

| Candidate | Mean change FoM | Mean OA | Mean macro-F1 | Change FoM delta vs FLUS | Wins/losses vs FLUS | Sign-test p |
|---|---:|---:|---:|---:|---:|---:|
| Persistence churn90 | 0.190345 | 0.894604 | 0.466998 | +0.039389 | 68/32 | 0.000409 |
| Region false-alarm guard | 0.188719 | 0.895320 | 0.468870 | +0.037764 | 68/32 | 0.000409 |
| Persistence churn50 | 0.166980 | 0.904069 | 0.492396 | +0.016025 | 62/38 | 0.020979 |

2023 comparison:

| Candidate | Mean change FoM delta | Micro change FoM delta | Wins/losses | Hit delta | False alarm delta | Miss delta | Pattern |
|---|---:|---:|---:|---:|---:|---:|---|
| Persistence churn90 | -0.000843 | +0.019780 | 10/10 | +5564 | +22426 | -5564 | micro positive, mean negative |
| Region false-alarm guard | -0.001598 | +0.019473 | 10/10 | +5448 | +21962 | -5448 | micro positive, mean negative |
| Persistence churn50 | -0.022011 | -0.001802 | 9/11 | +2312 | +13716 | -2312 | both negative |

Interpretation:

1. The guard remains significantly better than FLUS overall, but it does not beat persistence churn90.
2. It reduces 2023 false alarms relative to churn90 by 464 cells, but also loses 116 true hits, so the per-case 2023 mean does not improve.
3. The 2023 gap is therefore not solved by lowering regional churn alone. The next candidate should target transition-specific spatial allocation quality, especially false-alarm-prone source-target pairs, rather than only reducing the amount of change.
4. Persistence churn90 remains the change-discovery recommendation; persistence churn50 remains the map-aware simulation recommendation.

## Pair False-Alarm Guard

The next candidate targeted the failure mode identified above: false-alarm-prone source-target transition pairs. Unlike the region guard, it does not reduce total churn. It keeps persistence demand and churn90, but applies an additional train-replay penalty to transition pairs with high false-alarm rate and low precision.

All20 comparison:

| Candidate | Mean change FoM | Mean OA | Mean macro-F1 | Mean change F1 | Change FoM delta vs FLUS | Wins/losses vs FLUS | Sign-test p |
|---|---:|---:|---:|---:|---:|---:|---:|
| FLUS ANN console | 0.150955 | 0.918396 | 0.505526 | 0.254339 | 0 | - | - |
| Persistence churn90 | 0.190345 | 0.894604 | 0.466998 | 0.317124 | +0.039389 | 68/32 | 0.000409 |
| Pair false-alarm guard | 0.193984 | 0.895258 | 0.467125 | 0.322401 | +0.043028 | 69/31 | 0.000183 |
| Persistence churn50 | 0.166980 | 0.904069 | 0.492396 | 0.284016 | +0.016025 | 62/38 | 0.020979 |

Temporal-stratum comparison for the pair guard:

| Holdout year | Mean change FoM delta | Micro change FoM delta | Wins/losses | Hit delta | False alarm delta | Miss delta | Pattern |
|---|---:|---:|---:|---:|---:|---:|---|
| 2019 | +0.079905 | +0.115764 | 18/2 | +11907 | +21600 | -11907 | both positive |
| 2020 | +0.038670 | +0.065569 | 11/9 | +8524 | +22534 | -8524 | both positive |
| 2021 | +0.050817 | +0.074900 | 18/2 | +8624 | +21511 | -8624 | both positive |
| 2022 | +0.044697 | +0.076965 | 12/8 | +8860 | +20346 | -8860 | both positive |
| 2023 | +0.001053 | +0.020563 | 10/10 | +5616 | +22374 | -5616 | both positive |

Interpretation:

1. Pair-level false-alarm control is the first candidate to close the 2023 mean change-FoM gap while also improving the all20 mean change FoM.
2. The improvement is modest but directionally important: compared with persistence churn90, it adds +0.003639 mean change FoM and improves the 2023 mean delta from -0.000843 to +0.001053.
3. It does not solve the final-map gap: FLUS remains higher on OA and macro-F1.
4. The new default change-discovery recommendation is `twm_pair_false_alarm_guarded_persistence_forecast_demand`; the map-aware and conservative recommendations remain unchanged.

## FLUS Transition Diagnostics

The FLUS outputs were re-evaluated from existing `simresult.tif` files with the current `pixel_metrics` schema, adding `transition_pair_metrics` to the FLUS side for all 100 cases.

| Candidate | Transition predicted | Transition actual | Transition hit | Transition false alarm | Transition miss | Transition FoM |
|---|---:|---:|---:|---:|---:|---:|
| FLUS ANN console | 86788 | 248107 | 25159 | 61629 | 222948 | 0.081227 |
| TWM temporal activity | 253423 | 248107 | 45473 | 207950 | 202634 | 0.099709 |
| TWM temporal activity + reliability | 253423 | 248107 | 46603 | 206820 | 201504 | 0.102441 |
| TWM temporal activity + replay precision | 253423 | 248107 | 45961 | 207462 | 202146 | 0.100887 |
| TWM temporal activity + neighborhood | 253423 | 248107 | 45749 | 207674 | 202358 | 0.100375 |
| TWM temporal activity + neighborhood + replay precision | 253423 | 248107 | 46274 | 207149 | 201833 | 0.101644 |
| TWM temporal activity + target neighborhood + replay precision | 253423 | 248107 | 46440 | 206983 | 201667 | 0.102046 |
| TWM temporal activity + target neighborhood + replay precision + reliability | 253423 | 248107 | 47488 | 205935 | 200619 | 0.104589 |
| TWM temporal activity + target neighborhood + strict replay precision | 253423 | 248107 | 47593 | 205830 | 200514 | 0.104845 |
| TWM temporal activity + target neighborhood + strict replay precision + overprediction control | 253423 | 248107 | 48521 | 204902 | 199586 | 0.107108 |
| TWM pair false-alarm guard + persistence churn90 | 238684 | 248107 | 55181 | 183503 | 192926 | 0.127849 |

Transition-level interpretation:

1. TWM temporal activity is higher-recall than FLUS: it captures many more exact source-target changes.
2. FLUS is much more conservative and has far fewer transition false alarms.
3. Pair false-alarm guard is now the best change-FoM and transition-pair candidate so far, but still does not close the OA/macro-F1 gap.
4. Target-specific transition neighborhood improves exact transition FoM from 0.101644 to 0.102046 versus the previous change-FoM best; overprediction control raises exact transition FoM further to 0.107108.
5. Pair false-alarm guard raises exact transition FoM further to 0.127849 by improving hit count while reducing transition false alarms relative to the prior strict-overprediction frontier.
6. The largest TWM false-alarm excesses versus FLUS remain concentrated in transitions such as shrub_and_scrub -> trees, trees -> crops, water -> trees and trees -> built.

## Product Modes

The benchmark now exposes explicit TWM usage modes and keeps the previous change-discovery default as a reference point:

1. `twm_balanced_strict_overprediction_churn90_persistence_forecast_demand`
   - Previous default change-discovery and scenario-simulation mode.
   - It has change FoM 0.190345 versus FLUS 0.150955.
   - It also improves oracle demand error versus FLUS: 198886 versus 226042.
   - It is not yet a conservative final-map product, because OA and macro-F1 still trail FLUS.
2. `twm_pair_false_alarm_guarded_persistence_forecast_demand`
   - Recommended as the default change-discovery and scenario-simulation mode.
   - It has the strongest current change FoM: 0.193984 versus FLUS 0.150955.
   - It also closes the 2023 mean change-FoM gap while preserving the persistence-demand advantage.
   - It is still not a conservative final-map product, because OA and macro-F1 remain below FLUS.
3. `twm_balanced_strict_overprediction_churn50_persistence_forecast_demand`
   - Recommended when the user wants a more map-like simulation while preserving a statistically significant change-FoM advantage over FLUS.
   - It has OA 0.904069 and macro-F1 0.492396, much closer to FLUS than the change-discovery mode.
   - It keeps mean change FoM above FLUS: 0.166980 versus 0.150955, with 62/38 wins/losses.
   - It also improves oracle demand error relative to FLUS: 198886 versus 226042.
   - Persistence churn75 remains a middle frontier point; linear-demand and Markov-demand variants are retained as diagnostics.
4. `twm_conservative_map_mode_forecast_demand`
   - Recommended only when the user prefers a more stable final land-cover map over aggressive change discovery.
   - It has much higher OA and macro-F1 than change-discovery mode: OA 0.908293 and macro-F1 0.488534.
   - It is closer to FLUS on map-level metrics, but weak for change discovery: change FoM 0.072575 versus FLUS 0.150955.

This makes the current system usable with an explicit mode choice rather than a single ambiguous "best" model.

## Scientific Conclusion

The latest evidence supports a stronger, but still bounded, claim:

1. TWM temporal activity significantly outperforms the fixed-seed GeoSOS-FLUS ANN console baseline on change FoM for this 100-case Dynamic World admin20 benchmark.
2. The improvement is not just a mean artifact: the paired sign test is significant and the current best win/loss count is 69/31 versus FLUS.
3. TWM still does not comprehensively outperform FLUS, because FLUS remains substantially stronger on OA and macro-F1.
4. The strongest current TWM candidate for change detection is `twm_pair_false_alarm_guarded_persistence_forecast_demand`.
5. The strongest current TWM product candidate for map-aware simulation is `twm_balanced_strict_overprediction_churn50_persistence_forecast_demand`.
6. Persistence demand is the strongest demand setting so far: it reduces target-vs-oracle demand error below the FLUS-supplied linear target and gives TWM lower realized oracle demand error than FLUS while preserving a statistically significant change-FoM advantage.
7. The previous 2023 residual mean gap is now closed by pair-level false-alarm control, although the 2023 wins/losses remain balanced at 10/10.
8. A first train-only region false-alarm guard did not solve 2023, showing that churn reduction alone is insufficient.

## Next Work

The next scientifically rigorous step is not to tune on holdout scores. Recommended next steps:

1. Validate strict replay precision + overprediction control on a different region/time split or additional GEE regions before treating it as a general superiority result.
2. Add a train-only secondary objective for OA/macro-F1, because the current best still optimizes change detection more than conservative class accuracy.
3. Validate whether persistence demand still outperforms linear and Markov demand on additional regions or alternative temporal splits.
4. Validate the pair false-alarm guard on additional regions or alternative temporal splits before treating the 2023 closure as general.
5. Keep OA and macro-F1 as explicit secondary objectives, because change-FoM and demand gains still do not close the FLUS conservative-precision advantage.
