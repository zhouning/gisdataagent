# ADR-044: Gate the coupled single-reach dynamic-wave diagnostic

- Status: Accepted
- Date: 2026-07-28
- Scope: Stage 3 coupling after ADR-043

## Context

ADR-043 retained separate hydrostatic bed, Manning friction, and lateral
inflow primitives. It prohibited naive coupling because hydrostatic
reconstruction already supplies bed acceleration. Adding a second explicit
bed-slope source would count the same acceleration twice.

The Stage 3 diagnostic now couples the two-state dynamic-wave flux and sources
on one prismatic reach. Its symmetric step order is:

1. lateral inflow for half a timestep;
2. friction-only Manning decay for half a timestep;
3. one full hydrostatic-reconstruction flux step;
4. friction-only Manning decay for half a timestep;
5. lateral inflow for half a timestep.

The friction substep contains only `-g A Sf`. Bed acceleration remains solely
inside hydrostatic reconstruction. Lateral inflow requires either zero
longitudinal momentum or matched local velocity; there is no implicit default.

Open boundaries use typed, fixed ghost states with explicit ghost-bed
elevations. These are diagnostic boundary conditions, not characteristic or
rating-curve boundary conditions.

## Conservation contract

Every coupled step reports a mass ledger with initial volume, prescribed
lateral volume, net open-boundary volume, final volume, and closure residual.
It also reports a momentum ledger that separates lateral, friction, and
combined boundary-and-bed contributions. The latter two effects cannot be
separated from cell-integrated state changes without adding an interface
momentum-flux ledger, so the report does not claim such a separation.

Bed acceleration is not included in a second source term. This is the key
difference from the standalone Stage 2 `S0-Sf` equilibrium diagnostic.

## Evidence

All 14 outcome-free Stage 3 gates pass. No public data, action values,
observations, or saved predictions are read.

An open four-cell lake over non-flat bed remains at rest for 100 steps and
1152.15 seconds. Area drift is zero, maximum spurious discharge is
`6.55e-15 m3/s`, and the largest step mass-ledger residual is
`2.27e-30 m3`.

The source-inclusive probe adds the prescribed `6.0 m3` of lateral water. Its
friction momentum contribution is negative (`-7.151 m4/s`), its mass residual
is `-2.65e-12 m3`, and its momentum ledger closes exactly at reported
precision.

Moving-water behavior is tested on a fixed 2400 m reach for 1800 seconds. The
channel has constant 20 m2 area, bed slope 0.002, Manning `n=0.035`, and
derived equilibrium discharge `28.6511 m3/s`. Ghost cells extend the same bed
slope and center spacing. The result is not required to be an exact discrete
moving-water balance; it must converge under grid refinement and pass fixed
fine-grid drift limits.

| Cells | Cell length | Max area drift | Max discharge drift |
|---:|---:|---:|---:|
| 24 | 100 m | 3.3071% | 0.7127% |
| 48 | 50 m | 1.7299% | 0.5171% |
| 96 | 25 m | 0.8809% | 0.2513% |

Both errors decrease at both refinements. The 96-cell result passes the
predeclared 1% area and 0.5% discharge limits. Its cumulative mass and
momentum ledger residuals are `-1.56e-11 m3` and `9.31e-10 m4/s`.

## Decision

Retain the coupled source-split single-reach operator as a Stage 3 diagnostic.
The implementation has earned the claims that the source primitives are
coupled with the homogeneous flux, fixed-ghost open boundaries exist, and
source-inclusive mass and momentum ledgers close.

Do not admit the operator for predictive evaluation yet. The next numerical
stages are:

1. replace or supplement fixed ghosts with characteristic boundary contracts;
2. add spatially variable section geometry with interface geometry semantics;
3. add conservative junction coupling and junction-local mass ledgers;
4. only then bind public river geometry and boundary time series without
   reading development outcomes during equation implementation.

## Artifact

- Coupled dynamic-wave gate report SHA256:
  `36024933a56058bbe7cf5fcdc6dfa45cfef9790aef719b9e671586f58db06060`

## Claim boundary

- `source_primitives_coupled_with_homogeneous_flux=true`
- `fixed_ghost_open_boundaries=true`
- `source_inclusive_mass_and_momentum_ledgers=true`
- `moving_uniform_flow_convergence_gate_passed=true`
- `characteristic_boundary_conditions_implemented=false`
- `variable_geometry_operator_implemented=false`
- `network_operator_implemented=false`
- `candidate_operator_admitted=false`
- `predictive_validation_complete=false`
- `geospatial_kernel_validated=false`
