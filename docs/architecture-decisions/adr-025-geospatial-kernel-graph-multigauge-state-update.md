# ADR-025: Graph-Constrained Multi-Gauge State Update

**Date**: 2026-07-27  
**Status**: Accepted as an operator contract; first contemporaneous-covariance candidate rejected by development gate

## Context

ADR-024 showed that causal outlet state update was the main useful part of the first `ForecastClosure`, while a shared
state-dependent roughness residual added only `0.591 m3/s` RMSE improvement and the complete candidate still lost to
persistence. The next proposed step was a low-dimensional, multi-gauge state estimator. The user does not supply data,
so the project must establish this step entirely from public sources.

The frozen Center Hill D5 domain contains 435 reaches. A 1000 km NLDI upstream-site query returned 160 catalog sites;
intersection with the frozen feature axis left 28 sites on 26 reaches. A single bounded NWIS `00060` request over the
pre-D3 window returned only two usable series:

| Site | Feature | Role | Complete hours | Native cadence |
|---|---:|---|---:|---:|
| USGS `03424730` Smith Fork at Temperance Hall | `18421273` | interior branch state | 639 / 672 | 1800 s |
| USGS `03424860` Caney Fork at Stonewall | `18421703` | outlet state and target | 668 / 672 | 1800 s |

Both contain only `A` samples in retained complete hours. Missing hours are not imputed. These are currently retrieved,
revised archive values; their operational availability vintage is not verified. The input report SHA-256 is
`f96d059434668bd564932d5ae5bf03cb9ecdf0d4826f34013b7fafad3621cc2b`.

## Decision

Add an optional `GraphStateUpdateParameters` contract to the forecast closure. It is constrained as follows:

- the feature axis must exactly equal the frozen `DirectedReachNetwork` axis;
- every update row is keyed by an observed feature and may be nonzero only on strict upstream ancestors of that feature;
- gauge columns are zero because local discharge-to-storage inversion remains a separately recorded update;
- gains are finite and bounded in `[0,1]`;
- supports for different gauges are disjoint, preventing overlapping hidden-state corrections;
- graph increments are converted in normalized log-storage space, remain nonnegative in state, and are separately exposed
  in `graph_analysis_increment_m3`;
- topology fingerprint and complete forecast-cycle mass accounting remain mandatory;
- parameter training time, evidence, modeled-state status, possible nudging, and outcome-calibration status are explicit.

The first candidate is rank one. Its direction is estimated from the first 168 hours of public NWM retrospective
`streamflow / velocity x effective length` states. For each strict upstream ancestor of Smith Fork, the regression on the
gauge's normalized log storage is clipped to `[0,1]`. No USGS value, D3 outcome, or later blind outcome is used to fit the
gain. The basis has 267 upstream ancestors, 259 positive applied gains, zero outcome-fitted free parameters, and is marked
`candidate`, `admitted=false`, `modeled_state_based=true`, `possible_nudging=true`.

## Public Development Evidence

All scenarios start from the same outlet-updated activation state at `2021-12-16T02Z`. The following 503 issue times use
the same action, forcing, geometry, observation lag assumption, and missing-data rule:

| Scenario | RMSE (m3/s) | NSE | Interpretation |
|---|---:|---:|---|
| graph multi-gauge | 47.400 | 0.8087 | local two-gauge update plus rank-one spatial propagation |
| local multi-gauge | 47.115 | 0.8110 | both gauges, no spatial propagation |
| outlet only | 47.162 | 0.8106 | ADR-024 state-update control |
| interior only | 82.631 | 0.4185 | Smith Fork update without outlet correction |
| no update | 82.770 | 0.4166 | shared-state open-loop control |
| latency-matched persistence | 33.803 | 0.9030 | graph candidate did not beat |
| one-hour persistence | 17.415 | 0.9742 | graph candidate did not beat |

The local second gauge improves outlet-only RMSE by only `0.046 m3/s`. The graph propagation then loses `0.285 m3/s`
relative to local multi-gauge and `0.238 m3/s` relative to outlet-only. All five Kernel scenarios pass the complete mass
ledger; the maximum residual/tolerance ratio is below `4.8e-4`. The graph candidate therefore fails for predictive
reasons, not conservation or topology reasons.

Artifacts:

- graph parameters SHA-256: `7128a100867af237b00f3d83bca67288b4df12f4f15f1386f344e0ddfd40f633`;
- predictions SHA-256: `99e29085f22c9b9ad1fad4747d4a61707a942425b74aa472c35d1b66aa5fe8a4`;
- report SHA-256: `fdd1b0996eb2ead2b03be75606f320d054b6983e5337c434e53b2a5e5e850492`.

## Consequences

The operator boundary is retained because it supplies a falsifiable place for geographically constrained hidden-state
updates without allowing topology mutation or unaccounted mass. The contemporaneous NWM covariance instance is rejected.
It must not be tuned on this diagnostic window.

The result also exposes a task-design issue. Smith Fork is an interior branch and its state should influence the outlet
after a travel delay, not necessarily in the next one-hour target. A contemporaneous covariance basis ignores this lag,
while one-hour persistence is exceptionally strong. The next development protocol must therefore predeclare lead times
`1/3/6/12/24h`, distinguish oracle-forcing diagnostics from operationally available forcing/action forecasts, and compare
lead-matched persistence at every horizon. A lagged graph kernel may be implemented only after that protocol is frozen.

No new untouched multi-system window is consumed. Operational publication vintage remains unresolved, and NWM
retrospective states may contain nudging. Neither this data acquisition nor this development run can validate a forecast
closure or the Geospatial Kernel.

## Claim Boundary

- `public_multigauge_development_data_available=true`
- `graph_state_update_contract_implemented=true`
- `graph_state_update_dag_support_enforced=true`
- `graph_state_update_outcome_calibrated=false`
- `graph_state_update_possible_nudging=true`
- `graph_state_update_conservation_passed=true`
- `local_multigauge_beats_outlet_only_development_rmse=true`
- `graph_multigauge_beats_local_multigauge_development_rmse=false`
- `graph_multigauge_beats_persistence=false`
- `graph_multigauge_development_gate_passed=false`
- `operational_observation_vintage_verified=false`
- `graph_state_estimation_validated=false`
- `forecast_closure_validated=false`
- `geospatial_kernel_validated=false`
