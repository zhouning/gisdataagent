# ADR-036: Reject branching kinematic-wave operator admission

- Status: Accepted
- Date: 2026-07-28
- Scope: Geospatial Kernel branching finite-volume kinematic-wave operator

## Context

ADR-032 established numerical consistency, conservation, positivity, and an
analytic shock benchmark for the project-owned finite-volume kinematic-wave
primitive. A real-network two-system holdout was then attempted with complete
incremental tributary DAGs, authoritative NWM RouteLink geometry, public NWM
initial state and `q_lateral`, and public USACE boundary actions.

The v1 holdout did not seal predictions because its one-ULP CFL reporting check
was narrower than the observed binary64 evaluation by one ULP. ADR-033 retained
that failure and preregistered a new v2 window with a two-ULP reporting limit.
The operator flux, state, timestep, forcing, geometry, metrics, baseline, and
accuracy gate were unchanged.

The v2 predictions were jointly sealed before USGS access. Outcome acquisition
and scoring later required the recovery decisions in ADR-034 and ADR-035:
missing observations were retained as missing without imputation, and finite
approved negative USGS discharge values were preserved unchanged. These
recoveries did not change predictions, target values, the common mask, metrics,
baseline, or gates, but they prevent a pristine frozen-code confirmatory claim.

## Registered result

Every registered numerical execution gate passed for both actual and
branch-silent trajectories:

- Center Hill maximum mass residual/tolerance ratio: approximately
  `8.79e-05`;
- J. Percy Priest maximum mass residual/tolerance ratio: approximately
  `2.04e-04`;
- all cell states finite and nonnegative;
- zero-state/zero-input identity passed;
- maximum reported Courant number equaled the frozen two-ULP limit
  `0.8000000000000003`;
- operator form remained unadmitted and diagnostic-only.

The predictive gates failed without cross-system compensation:

| System | Scored hours | Kinematic RMSE | Persistence RMSE | Gate |
| --- | ---: | ---: | ---: | --- |
| Center Hill | 671 | 30.6064 m3/s | 8.7561 m3/s | fail |
| J. Percy Priest | 621 | 37.6834 m3/s | 27.5319 m3/s | fail |

The complete network beat the branch-silent diagnostic by only `0.5237 m3/s`
RMSE at Center Hill and `0.1809 m3/s` at J. Percy Priest. Tributary topology has
a measurable effect, but it does not explain the main forecast error.

## Post-score diagnosis

The registered score is not changed by this diagnosis. Outcome-aware lag and
affine scans are explicitly inadmissible as predictions.

- Center Hill zero-lag correlation is `0.489`; moving predictions 12 hours
  earlier gives the best posthoc correlation `0.901` and RMSE `15.82 m3/s`.
- J. Percy Priest zero-lag correlation is `0.798`; moving predictions 2 hours
  earlier gives the best posthoc correlation `0.971` and RMSE `17.76 m3/s`.
- Prediction/observation standard-deviation ratios are `0.67` and `0.84`.
- In the highest observed discharge decile, biases are approximately
  `-61.25 m3/s` and `-24.56 m3/s`.
- Outcome-fitted affine corrections still do not beat persistence at Center
  Hill and are not admissible in either system.

The failure is therefore not a conservation, positivity, or graph-accounting
failure. It is a predictive closure failure dominated by phase error, event
attenuation, and negative bias. The current Manning kinematic approximation,
boundary-time interpretation, parameter support, and open-loop state/forcing
combination are insufficient for one-hour prediction in these controlled river
reaches.

## Decision

Do not admit `BranchingFiniteVolumeKinematicWaveOperator` as a predictive
Geospatial Kernel operator. Keep it as a diagnostic numerical primitive with
`operator_form_admitted=false`.

Do not tune a lag, affine correction, Manning multiplier, state scale, or
closure on this holdout. The sealed predictions and score are final negative
evidence.

The next development phase must use separate public development windows and
must proceed in this order:

1. certify CWMS action support and USGS observation support on a shared event
   timeline, including publication semantics and station-control distance;
2. build an outcome-visible development benchmark for phase and event-amplitude
   diagnostics, separated from the next holdout;
3. test whether the phase error comes from boundary semantics, RouteLink
   geometry/celerity, missing regulated storage, or the kinematic approximation;
4. implement a regime-aware transport candidate only after that attribution,
   with diffusive/local-inertial or controlled-storage terms where evidence
   supports them;
5. freeze a new multi-system holdout with missing-prior and finite-negative-
   observation behavior explicitly tested before outcome access.

## Claim boundary

- `finite_volume_conservation_validated=true`
- `branching_DAG_execution_validated=true`
- `two_system_execution_gates_passed=true`
- `two_system_predictive_gate_passed=false`
- `strict_end_to_end_protocol_conformance=false`
- `operator_form_admitted=false`
- `hydrodynamically_validated=false`
- `geospatial_kernel_validated=false`
