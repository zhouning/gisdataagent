# TWM vs FLUS Fixed-Seed Stability Summary

Seeds: 20260623, 20260624, 20260625
Cases per seed: 100

| candidate | change FoM delta mean | change FoM delta range | OA delta mean | macro F1 delta mean |
|---|---:|---:|---:|---:|
| `twm_independent_transition_forecast_demand` | 0.021188 | 0.020833 to 0.021598 | -0.010806 | -0.033702 |
| `twm_hierarchical_transition_forecast_demand` | 0.021008 | 0.020654 to 0.021418 | -0.010809 | -0.034586 |
| `markov_transition_projection` | -0.005818 | -0.006173 to -0.005408 | -0.015393 | -0.043651 |
| `persistence` | -0.051387 | -0.051742 to -0.050977 | 0.006119 | 0.032195 |

Claim boundary: fixed-seed direct FLUS CA with adapter-supplied transition-prior suitability; not yet full FLUS ANN suitability training.
