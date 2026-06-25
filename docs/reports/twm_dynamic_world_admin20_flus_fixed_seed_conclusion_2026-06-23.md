# TWM vs FLUS Fixed-Seed Scientific Conclusion

Date: 2026-06-23

## What Was Tested

The comparison now includes fixed-seed FLUS runs, so the previous stochastic-reproducibility weakness has been addressed for the direct CA experiment.

Protocol:

- 20 Dynamic World admin20 regions.
- 100 rolling forecast cases: train `t0 -> t1`, evaluate `t2`.
- Formal candidates: only `forecast_demand` candidates.
- Excluded from formal claims: oracle-demand and no-demand diagnostics.
- FLUS executable: `/Users/zhouning/FLUS_console_crossplatform/build/flus_console`.
- FLUS random seeds: `20260623`, `20260624`, `20260625`.
- FLUS max iterations: 30.
- FLUS suitability input: adapter-supplied observed transition-prior probability cube.

Evidence:

- `docs/reports/twm_dynamic_world_admin20_flus_direct_all20_seed20260623_2026-06-23.json`
- `docs/reports/twm_dynamic_world_admin20_flus_direct_all20_seed20260624_2026-06-23.json`
- `docs/reports/twm_dynamic_world_admin20_flus_direct_all20_seed20260625_2026-06-23.json`
- `docs/reports/twm_dynamic_world_admin20_flus_seed_stability_2026-06-23.json`
- `docs/reports/twm_dynamic_world_admin20_flus_seed_stability_2026-06-23.md`

## Reproducibility Fix

The local FLUS console was patched to accept `FLUS_RANDOM_SEED`.

Validation:

- same seed `20260623` on the same packaged case produced identical `simresult.tif` MD5: `3b30fac7fb14dde8aaf4d5dcc8808a82`.
- different seed `20260624` produced a different MD5: `12855418402e9c6f00f5f88dbde38b61`.

This confirms that the direct FLUS CA random path is now controllable and reproducible.

## Cross-Seed Main Result

For `twm_independent_transition_forecast_demand` versus `flus_console_direct`:

| metric | cross-seed result |
|---|---:|
| mean change FoM delta | +0.021188 |
| change FoM delta range | +0.020833 to +0.021598 |
| change FoM positive seeds | 3/3 |
| paired case wins by change FoM | 82-86 wins out of 100, depending on seed |
| mean OA delta | -0.010806 |
| OA delta range | -0.010842 to -0.010753 |
| mean macro F1 delta | -0.033702 |
| target-demand abs-error delta | about -117753 |

Region-level stability:

- In every seed, TWM independent has positive mean change FoM delta in 20/20 regions.
- In every seed, TWM independent has negative mean OA delta in 20/20 regions.

## Scientific Interpretation

The result is stable across fixed FLUS random seeds.

Supported conclusions:

1. TWM is consistently better than the current direct FLUS CA adapter at allocating changed pixels, as measured by change FoM.
2. This change-FoM advantage is not driven by one random FLUS realization: it holds for all 3 fixed seeds, all 100 cases per seed, and all 20 regions at the region-mean level.
3. TWM demand-projected candidates exactly satisfy forecast demand totals by construction; FLUS retains residual target-demand mismatch after 30 iterations.
4. FLUS remains better than TWM on overall accuracy and macro F1 in these runs.

Unsupported conclusions:

1. It is not valid to claim that TWM is globally better than FLUS on all metrics.
2. It is not yet valid to claim superiority over full GeoSOS-FLUS, because the FLUS suitability layer here is adapter-supplied transition-prior suitability, not the full FLUS ANN suitability-training workflow.
3. It is not valid to use OA alone as the primary metric for this task, because persistence has high OA while zero change FoM.

## Final Current Conclusion

For the current Dynamic World admin20 one-year rolling land-change simulation scenario, TWM and direct FLUS CA are not equivalent. Their strengths differ:

- TWM is more reliable for change allocation.
- FLUS is more reliable for overall land-cover agreement under the current direct CA setup.
- Both models still have low absolute change FoM, so neither should be described as high-accuracy land-change simulation yet.

The strongest defensible statement is:

> Under a fixed-seed, forecast-demand-only protocol on 20 Dynamic World admin20 regions and 100 rolling cases, TWM shows a statistically and operationally stable advantage over direct FLUS CA for changed-pixel allocation, while FLUS retains an advantage on overall pixel agreement and macro F1. The conclusion is metric-specific and does not yet cover the full GeoSOS-FLUS ANN-trained suitability workflow.

## Remaining Work Before Final Paper-Level Claim

1. Reproduce a full FLUS ANN suitability-training workflow for the same 100 cases.
2. Increase FLUS seed count if publishing confidence intervals around FLUS stochastic variation is required.
3. Separate conclusions by intended use:
   - change allocation: use change FoM and change F1;
   - map agreement: use OA, kappa, macro F1;
   - demand feasibility: use target-demand residual;
   - scientific validity: report all of the above, not only one metric.
