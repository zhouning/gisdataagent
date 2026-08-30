# ADR-043: Gate dynamic-wave bed, friction, and lateral source primitives

- Status: Accepted
- Date: 2026-07-28
- Scope: Stage 2 source primitives after ADR-042

## Context

ADR-042 implemented the homogeneous prismatic dynamic-wave HLL core. Real
rivers require bed, friction, and lateral source terms, but coupling them
before each term has an independent equilibrium gate would make numerical
errors difficult to attribute.

Three typed source primitives are now implemented separately:

1. hydrostatic reconstruction at a bed step, using the maximum interface bed
   elevation, reconstructed wet areas, and side-specific pressure corrections;
2. an analytic fixed-area Manning source solution for
   `dQ/dt = gA(S0-Sf)` with nonnegative discharge;
3. nonnegative lateral volume input with an explicit longitudinal-momentum
   convention.

The lateral conventions are either `zero_longitudinal_momentum`, which leaves
`Q` unchanged, or `matched_local_velocity`, which adds `u dA` and preserves
local velocity. An unspecified convention is rejected.

## Evidence

All 14 source gates pass without reading public data or outcomes.

A six-cell non-flat lake-at-rest case remains balanced for 100 periodic steps
and 1280.17 seconds. The free surface does not change, step volume error is
zero, and maximum spurious discharge is `7.28e-15 m3/s`, below the predeclared
`1e-12 m3/s` gate.

For a 20 m2 section, bed slope `0.002`, and Manning `n=0.035`, the derived
uniform discharge is `28.6511 m3/s`. Its computed friction slope is exactly
`0.002`, and a 300-second source step is an exact identity. On a flat bed, a
3600-second friction step reduces positive discharge without changing area or
reversing flow.

Both lateral momentum conventions add the prescribed 300 m3. Their floating
volume residual is `-5.68e-14 m3`. Negative lateral input remains unsupported
in this primitive rather than being silently clipped or reinterpreted.

## Decision

Retain the hydrostatic bed reconstruction, fixed-area analytic Manning source,
and typed lateral momentum conventions as Stage 2 primitives.

Do not yet claim a coupled river operator. The hydrostatic reconstruction
already represents bed acceleration, while the standalone Manning equilibrium
primitive contains `S0-Sf`; combining both naively would count bed slope twice.

Stage 3 must define one source-splitting contract in which:

1. bed acceleration is supplied only by hydrostatic reconstruction;
2. the coupled friction substep applies only `-gA Sf`;
3. lateral volume and its selected momentum convention enter the mass ledger;
4. open boundary states replace the periodic diagnostic boundary;
5. lake-at-rest, flat-bed friction decay, source-inclusive mass balance, and
   grid-refined moving-water equilibrium drift are all reported separately.

Variable geometry and network junctions remain out of scope until the coupled
single-reach source step passes.

## Artifact

- Dynamic-wave source gate report SHA256:
  `ccdca32158318a1fe6fcac65a2d80318fef7edc878794c322701e99e1e5e4d4e`

## Claim boundary

- `hydrostatic_bed_primitive_implemented=true`
- `manning_slope_friction_primitive_implemented=true`
- `lateral_volume_source_implemented=true`
- `source_primitives_coupled_with_homogeneous_flux=false`
- `variable_geometry_operator_implemented=false`
- `network_operator_implemented=false`
- `candidate_operator_admitted=false`
- `geospatial_kernel_validated=false`
