# ADR-042: Implement the homogeneous dynamic-wave HLL core

- Status: Accepted
- Date: 2026-07-28
- Scope: Stage 1 of the ADR-041 dynamic-wave candidate

## Context

ADR-041 selected a two-state dynamic-wave finite-volume candidate because the
public gravity-wave scale is materially faster than the failed kinematic
closure, while short supercritical reaches rule out deleting convective
momentum on the full path.

The first implementation stage is deliberately restricted to a prismatic
trapezoidal channel with no bed, friction, lateral-flow, geometry-transition,
or network-junction source. The conservative state and homogeneous flux are:

- `U = (A, Q)`;
- `F_A = Q`;
- `F_Q = Q^2/A + g I1(A)`;
- `I1 = b h^2/2 + z h^3/3`;
- characteristic speeds `u-c_g` and `u+c_g`, where `c_g=sqrt(gA/T)`.

An HLL Riemann flux uses the characteristic bounds and supports dry, reverse,
subcritical, transcritical, and supercritical interface states without an
equation-family switch.

## Evidence

All 13 outcome-independent homogeneous gates pass:

- the numerical derivative of hydrostatic pressure flux matches `gA/T` with
  relative error `7.47e-11`;
- dynamic momentum flux decomposes exactly into the local-inertial pressure
  flux plus `Q^2/A`;
- the subcritical case has characteristic speeds `-3.238/3.738 m/s`;
- the supercritical case has speeds `5.964/10.036 m/s` and uses the upstream
  physical flux;
- a uniform periodic state is an exact one-step identity;
- periodic homogeneous volume and momentum integrals close exactly in the
  uniform case;
- a 64-cell wet/dry pressure wave remains nonnegative for 100 adaptive-CFL
  steps.

The 100-step wet/dry run advances 739.95 seconds at maximum reported Courant
number `0.5000000000000001`. Its volume error is `-2.91e-11 m3` and its
homogeneous discharge-integral error is `-8.53e-12 m4/s`.

These tests use no public data, user data, actions, observations, or saved
predictions.

## Decision

Retain the trapezoidal hydrostatic flux, explicit convective momentum, HLL
interface solver, dry-state contract, adaptive CFL calculation, and
homogeneous mass/momentum ledger as the Stage 1 dynamic-wave primitive.

Do not connect this primitive to RouteLink or a development hydrograph yet.
A homogeneous solver on a sloping river would accelerate water indefinitely
without the missing source balance.

Stage 2 must implement and separately gate:

1. hydrostatic reconstruction and bed-slope balance for a lake-at-rest state;
2. Manning friction with a uniform-flow `S0=Sf` equilibrium test;
3. semi-implicit or otherwise positivity-safe friction handling;
4. lateral volume input with an explicit momentum convention;
5. source-inclusive mass ledger and CFL reporting.

Variable geometry and network junction coupling remain later stages. Momentum
is conserved only for the periodic homogeneous equation; bed and friction
sources will have an explicit momentum ledger rather than a false conservation
claim.

## Artifact

- Homogeneous dynamic-wave gate report SHA256:
  `15996dc5b6ee89348c4df128f9f8cc866f809011316c0a981f1421738f9bd25e`

## Claim boundary

- `homogeneous_prismatic_flux_implemented=true`
- `subcritical_and_supercritical_riemann_gates_passed=true`
- `well_balanced_source_operator_implemented=false`
- `variable_geometry_operator_implemented=false`
- `network_operator_implemented=false`
- `candidate_operator_admitted=false`
- `predictive_validation_complete=false`
- `geospatial_kernel_validated=false`
