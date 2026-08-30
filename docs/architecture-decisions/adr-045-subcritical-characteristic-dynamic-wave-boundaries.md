# ADR-045: Gate subcritical characteristic dynamic-wave boundaries

- Status: Accepted
- Date: 2026-07-28
- Scope: Stage 4 boundary closure after ADR-044

## Context

ADR-044 coupled the dynamic-wave flux and sources with fixed ghost states. A
fixed ghost specifies both wetted area and discharge. That is useful for
diagnostics, but it over-specifies a subcritical open boundary, where exactly
one characteristic enters the reach and one leaves it.

A usable public-data boundary normally supplies one quantity: upstream flow,
downstream stage, or occasionally cross-sectional area. The missing boundary
state must come from the simulated reach rather than from another unavailable
observation.

For state `(A,Q)`, velocity `u=Q/A`, and gravity celerity
`c=sqrt(gA/T)`, the outgoing invariants used here are:

- left boundary: `u - integral_0^A c(a)/a da`, carried by `u-c`;
- right boundary: `u + integral_0^A c(a)/a da`, carried by `u+c`.

This is the general prismatic-section form. The rectangular special case
reduces to `u +/- 2c`; applying that shortcut directly to a trapezoidal
section would be incorrect.

## Implementation

The boundary contract requires a side, bed elevation, one prescribed quantity,
and one value. Supported quantities are wetted area, discharge, and free
surface elevation.

For area or free surface, discharge follows directly from the outgoing
invariant. For prescribed discharge, area is solved from that invariant. The
solver first attempts a local Newton solve from the adjacent internal area,
then uses a logarithmic bracket scan and bisection. It retains only subcritical
roots and selects the root nearest the adjacent internal area.

The trapezoidal characteristic potential is integrated after substituting
`h=s^2`, removing the integrable dry-end singularity. A fixed 24-point
Gauss-Legendre rule then evaluates the regularized integral deterministically.

The CFL estimator resolves characteristic ghosts from the current boundary
cells. The coupled source step resolves them again after the first lateral and
friction half-steps, so the hydrostatic flux does not use a stale ghost state.
Every resolved boundary records the prescribed quantity, incoming and outgoing
characteristics, both characteristic speeds, and its invariant residual.

## Evidence

All 16 outcome-free Stage 4 gates pass. No public data, action values,
observations, or saved predictions are read.

For a rectangular section, the computed potential equals `2c` exactly at
reported precision. For the trapezoidal test section, the relative error
between the numerical potential derivative and `c/A` is `2.33e-11`.
Uniform subcritical states are exactly recovered from an upstream discharge
condition and a downstream free-surface condition.

A flat six-cell lake remains an exact identity for 100 coupled steps. Area,
discharge, mass ledger, momentum ledger, and outgoing-invariant residual all
remain zero at reported precision.

The moving-water diagnostic uses the same 2400 m reach, 1800 s duration,
20 m2 area, 0.002 bed slope, Manning `n=0.035`, and `28.6511 m3/s`
equilibrium discharge as ADR-044. Stage 4 supplies only upstream discharge and
downstream free surface:

| Cells | Max area drift | Max discharge drift | Area ratio | Flow ratio |
|---:|---:|---:|---:|---:|
| 24 | 6.9141% | 5.7390% | - | - |
| 48 | 3.5056% | 2.9955% | 0.5070 | 0.5220 |
| 96 | 1.7650% | 1.5308% | 0.5035 | 0.5110 |

Both errors decrease by more than the required factor at both refinements and
the 96-cell errors are below the fixed 2% limits. Across all moving-flow steps,
the maximum outgoing-invariant residual is below `1e-12 m/s`. The 96-cell
cumulative mass and momentum ledger residuals are `-1.00e-11 m3` and
`-4.66e-10 m4/s`.

## Decision

Retain the subcritical characteristic boundary implementation and its
integration with the coupled single-reach dynamic-wave diagnostic.

Do not generalize the claim beyond one incoming characteristic per boundary.
Dry, transcritical, and supercritical interiors fail closed because they need
different information counts and boundary policies. A prescribed-discharge
root that is not subcritical is rejected rather than silently selecting a
hydraulically different branch.

The next stages are:

1. add variable section geometry and explicit interface geometry semantics;
2. add time-series adapters that create one boundary specification per step;
3. add conservative network junction coupling;
4. bind public geometry and boundary series only after these numerical gates,
   without reading development outcomes during implementation.

## Artifact

- Characteristic-boundary gate report SHA256:
  `d331a66b2e1c4abbd228908790afdfea8870e8f41d5d4eac6e52d02452a5ef4f`

## Claim boundary

- `subcritical_characteristic_boundaries_implemented=true`
- `upstream_discharge_boundary_implemented=true`
- `downstream_stage_boundary_implemented=true`
- `supercritical_characteristic_boundaries_implemented=false`
- `dry_characteristic_boundaries_implemented=false`
- `time_series_boundary_adapter_implemented=false`
- `variable_geometry_operator_implemented=false`
- `network_operator_implemented=false`
- `candidate_operator_admitted=false`
- `predictive_validation_complete=false`
- `geospatial_kernel_validated=false`
