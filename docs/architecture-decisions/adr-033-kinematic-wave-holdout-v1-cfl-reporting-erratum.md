# ADR-033: Kinematic-wave holdout v1 CFL reporting erratum

- Status: Accepted
- Date: 2026-07-28
- Scope: Geospatial Kernel branching finite-volume kinematic-wave validation

## Context

The v1 two-system holdout protocol was frozen before dynamic input and outcome
access. Public NWM and CWMS inputs were then acquired, but the outcome-free
Center Hill execution stopped before writing either prediction artifact.
No USGS outcome URL, path, column, or value was requested or loaded.

The frozen execution report recorded:

- actual maximum mass residual/tolerance ratio: `8.830287085533862e-05`;
- branch-silent maximum mass residual/tolerance ratio: `9.211539911552441e-05`;
- all cell states finite and nonnegative;
- zero-state/zero-input identity passed;
- operator form remained unadmitted and diagnostic-only;
- configured CFL number: `0.8`;
- observed binary64 maximum Courant number: `0.8000000000000003`;
- frozen one-ULP comparison limit: `0.8000000000000002`.

The only failed execution checks were the actual and branch-silent CFL
comparisons. The adaptive step construction is mathematically bounded by the
configured CFL number. The two-ULP excess is produced by the binary64 sequence
used to construct and then report `celerity * dt / cell_length`; it does not
change a timestep, flux, state, or prediction.

## Decision

The v1 protocol remains failed. Its gate, code hashes, and report will not be
changed, and v1 predictions will not be reconstructed or sealed.

A v2 holdout will use a new outcome-inaccessible NWM time chunk and will freeze
the CFL reporting comparison as the configured value plus two binary64 ULPs.
It will reuse the exact v1 operator and numerical trajectory implementation.
No fitting, state scaling, lag, closure, action change, forcing change, metric
change, baseline change, or accuracy-gate change is permitted.

The v2 candidate window is:

- initial state: `2022-11-10T00:00:00Z`, NWM time chunk `570`;
- rollout: `[2022-11-10T01:00:00Z, 2022-12-08T01:00:00Z)`, NWM time chunk
  `571`;
- systems: Center Hill and J. Percy Priest;
- duration: 672 one-hour steps.

Neither v2 dynamic inputs nor v2 outcome values had been requested when this
decision was recorded.

## Consequences

The v1 result is evidence that execution-gate representation must be frozen as
carefully as the physical operator. It is not evidence against conservation or
the kinematic-wave equation.

Passing v2 will not automatically admit the operator form. Admission still
requires a separate post-score architecture decision that considers predictive
accuracy, negative controls, independence limits, and generalization scope.
