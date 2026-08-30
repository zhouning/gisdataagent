# ADR-028: Causal Boundary Transition and Geographic Transfer Support

**Date**: 2026-07-27  
**Status**: Boundary-only transition retained as a candidate; downstream combination rejected

## Context

ADR-027 rejected persistence of one Smith Fork observation through a 24-hour branch. That failure left two distinct
questions: whether a causal boundary hydrograph can be forecast from public history, and whether a more accurate boundary
forecast improves the Center Hill outlet after geographic transfer. Combining those questions would make another negative
result ambiguous.

The user supplies no additional data. The project therefore acquired USGS `03424730` history from the public NWIS archive
for `2021-01-01T00Z/2021-12-09T01Z`. All `16,236` retained native samples have `A` quality at 30-minute cadence. Complete
hourly means provide 5,719 fit hours and 2,338 boundary-only temporal-holdout hours; 152 incomplete hours remain missing.
No Center Hill outlet target or current downstream development value was requested by this acquisition.

## Decision

Represent the boundary hydrograph as one stationary AR(2) transition on `log1p(discharge)`. Fit exactly three shared
coefficients by unweighted OLS using consecutive pre-`2021-09-01T00Z` triples. There is no lag search, regularization search,
horizon-specific parameter, imputation, or outlet calibration. A fixed `10,000m3/s` numerical bound is not fitted.

At issue time, the model accepts only observations whose archive availability time is no later than the issue time under the
registered one-hour lag. Two consecutive observations are required. It recursively fills every hourly support through the
target, so all `1/3/6/12/24h` values come from one state transition. Training must precede issue time and the AR roots must
lie inside the unit circle.

Only after a frozen boundary-only holdout passes all five horizons may the parameters enter the unchanged
`ObservedInternalBoundaryReplacement`. The downstream development gate then requires dynamic-boundary RMSE to be below
held boundary, modeled cut, zero boundary, parent local, and causal persistence at every `3/6/12/24h` horizon, plus mass
conservation.

## Boundary-Only Evidence

The fitted equation is:

```text
log1p(Q[t]) = 0.0049389267
              + 1.5941528104 * log1p(Q[t-1])
              - 0.5967174696 * log1p(Q[t-2])
```

Characteristic-root magnitudes are `0.993579` and `0.600574`. On the frozen `2021-09-01/2021-12-09` upstream holdout:

| Horizon | Log-AR(2) RMSE | Causal persistence RMSE |
|---:|---:|---:|
| 1h | 6.409 | 7.941 |
| 3h | 13.385 | 14.427 |
| 6h | 20.563 | 21.518 |
| 12h | 27.341 | 27.728 |
| 24h | 26.535 | 30.340 |

The non-compensatory boundary-only gate passes. This is a current revised archive replay, not proof of historical
operational availability.

## Downstream Evidence

The same frozen parameters were then applied without refitting to the exposed Center Hill development interval. The
downstream common-mask RMSE is:

| Horizon | Dynamic boundary | Held boundary | Modeled cut | Parent local | Causal persistence |
|---:|---:|---:|---:|---:|---:|
| 1h | 48.655 | 48.453 | 48.104 | 48.076 | 34.609 |
| 3h | 82.215 | 81.807 | 81.484 | 81.385 | 62.730 |
| 6h | 84.582 | 84.149 | 84.013 | 83.901 | 90.702 |
| 12h | 85.720 | 84.715 | 83.381 | 83.334 | 114.442 |
| 24h | 87.861 | 88.717 | 82.317 | 82.307 | 86.588 |

Dynamic boundary improves over held boundary only at 24h, by `0.855m3/s`. It remains worse than modeled cut and parent
local at every horizon, and worse than causal persistence at 1h, 3h, and 24h. The complete development gate fails. Mass
conservation passes with maximum residual-to-tolerance ratio below `4.70e-4`; no future observation update occurs.

A post-outcome attribution check scores the boundary itself inside the same current window. Log-AR(2) still beats boundary
persistence at all horizons: its RMSE is `12.535/24.752/35.374/50.321/51.174m3/s`, versus
`15.990/27.826/40.585/53.458/58.125m3/s`. Thus the failure is isolated to spatial support or downstream dynamic transfer,
not to complete loss of upstream boundary skill. This attribution is diagnostic and cannot validate the transition.

## Outcome-Free Geographic Transfer Audit

An outcome-free unit impulse makes the implicit transfer law visible. The compiled Smith Fork-to-outlet path contains 12
reaches over `21.720km`. Initial NWM velocity gives a `19.250h` path travel-time prior. A synthetic
`1m3/s` one-hour boundary pulse in the current conservative Manning kernel first exceeds `1e-6m3/s` at the outlet in hour
2, peaks in hour 14, and has a 240-hour response center of mass at `22.007h`. The outlet recovers `99.9242%` of the
`3,600m3` pulse by hour 240; only `2.729m3` remains in storage and the differenced mass residual is `4.21e-8m3`.

This delay support explains why a better dynamic boundary helps held-boundary prediction only at 24h. It also rejects the
earlier idea that an interior innovation should propagate contemporaneously across all upstream/downstream state.

## Relationship to Traditional GIS

A GIS downstream trace returns the 12 reaches and their `21.720km` length. Linear referencing determines the partial first
reach. Those are indispensable static facts, but they do not provide the arrival-time distribution, attenuation, recursive
storage, pulse recovery, or a causal observation vintage.

The Geospatial Kernel turns the GIS path into a state-dependent conservative Green's function. Its support is locked by
topology and geometry; its weights arise from hydraulic state and constitutive laws; its integral is checked against the mass
ledger. A learned closure may adjust bounded travel/storage dynamics using independent data, but cannot place response mass
off the compiled path, create volume, or select a favorable horizon after scoring.

## Consequences

Retain the stable causal boundary-transition interface and its public data pipeline. Reject the present combination as a
downstream predictive closure. Do not tune AR coefficients on Center Hill outlet error.

The next kernel milestone is an explicit geographic transfer-support operator derived before target scoring. It should emit
path identity, state-conditioned first arrival, peak, center of mass, normalized impulse weights, and uncertainty. That
support should replace contemporaneous graph covariance in the graph observer. Before another downstream gate, the project
must also resolve the unadmitted 52m gauge attachment and replace length-proportional partial `q_lateral` with catchment-
based support. These are public-data acquisition tasks; they do not require user-supplied data.

## Artifact Identity

- boundary history report: `cb11057963e68b1f78390e84e98cb77a6350b7c12ef4ea9c3b1e582f4b2c1709`;
- boundary-transition protocol: `599191c671d006620df8ba1fbd864c8d2b8b9fe145f2ccc4708d877a8e2934ce`;
- boundary-transition parameters: `1f2e5dfefa5f21bca60e5f36f5fed59d18dd5519d02baa0236628ec1a51eeed9`;
- boundary-transition report: `599ff46086e1f49cc02cd0f85dcde52391a54c6a60a68d7fd83220a9b70db5db`;
- downstream protocol: `c2eade8b3d0e0d63d2909765a8bc44e46a4fcce88658066842fe32794175c6f4`;
- downstream predictions: `02123360d27163c5a62512ad267cfd6cf4b5ff3e5f6ab5593fe353bce190b119`;
- downstream report: `596c6895d4bc73ca6afe4ee11cef8d10cce9f8616fa42bc1faf883cd93ee9fea`;
- skill-transfer diagnostic: `64b9a1da539b2a017d7920e2cd4b9d5ed78e8bc3526754e1d023e996a6e77a6f`;
- outcome-free impulse report: `e9c4d2016562d1f86b7d9e85323722650c144be911565bb20fd21075966265ff`.

## Claim Boundary

- `public_boundary_history_acquired=true`
- `boundary_transition_upstream_holdout_passed=true`
- `dynamic_internal_boundary_development_gate_passed=false`
- `boundary_skill_transfer_gate_passed=false`
- `outcome_free_transfer_diagnostic_executed=true`
- `internal_boundary_reference_admitted=false`
- `partial_forcing_support_admitted=false`
- `operational_forecast_evaluated=false`
- `forecast_closure_validated=false`
- `geospatial_kernel_validated=false`
