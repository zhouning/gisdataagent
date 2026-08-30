# ADR-060: Source-split multi-cell patch-reach coupling

- Status: implemented as a native candidate; patch friction and public
  validation pending
- Date: 2026-07-29
- Depends on: ADR-059

## Context

ADR-059 synchronously coupled the multi-cell 2D confluence patch to its 1D
reaches and replaced the passive transverse-momentum reservoir with an explicit
instantaneous transition-wall reaction. That conservative core intentionally
excluded reach friction and lateral inflow.

Real reaches exchange water with rainfall, runoff, tributaries, drainage, and
managed inputs. Their longitudinal momentum is also dissipated by bed and bank
roughness. These effects are source terms rather than opening fluxes and must be
integrated without changing the Stage 18 interface law or hiding their separate
mass and momentum contributions.

## Decision

Implement `coupled_junction_patch_reach_sources.py` as a Strang-split wrapper
around the frozen Stage 18 conservative core. Freeze all five Stage 18 artifacts
by hash.

For every 1D reach, execute:

```text
lateral_half
manning_friction_half
stage18_patch_reach_conservative_core_full
manning_friction_half
lateral_half
```

The 2D patch state is passed unchanged through the source half-steps. It evolves
only inside the Stage 18 finite-area flux step. Stage 19 therefore does not
claim a patch-bed friction law.

## Lateral source semantics

Each reach cell declares nonnegative lateral inflow `q_l` in `m2/s`, interpreted
as volume per unit reach length per unit time. A source substep updates area by:

```text
A_next = A + dt q_l
```

The caller must select one of two typed longitudinal momentum conventions:

- `zero_longitudinal_momentum`: added water carries no longitudinal momentum;
- `matched_local_velocity`: added water enters at the cell's current velocity,
  so `Q_next = Q + (Q/A) dt q_l` for wet cells.

There is no implicit default and negative lateral flow is not supported. The
selected convention is included in every trace and global ledger.

## Manning friction semantics

For each 1D cell, the existing variable-section Manning source keeps area fixed
and applies the semi-implicit discharge update:

```text
Q_next = Q / (1 + dt C_drag |Q|)

C_drag = g n^2 / (A R_h^(4/3))
```

where `n` is the declared Manning roughness and `R_h` is hydraulic radius from
the cell section. The update preserves flow direction and avoids an explicit
friction timestep instability. Its exact change in longitudinal discharge
integral is recorded as a geographic vector using the branch tangent.

## Source-adjusted stability

The Stage 18 CFL bound depends on the state presented to its conservative step.
Stage 19 therefore iterates the following calculation:

1. estimate a common Stage 18 timestep from the unsplit state;
2. apply the first lateral and friction half-steps at half that timestep;
3. recompute the Stage 18 bound from the resulting source-adjusted state; and
4. reduce and repeat when the candidate exceeds the new bound.

At most 12 reductions are allowed. Nonconvergence fails closed. The full step
also rejects any timestep above the converged common bound.

## Whole-system ledgers

The Stage 19 volume ledger is:

```text
V_after - V_before
  = lateral_volume_change + external_boundary_volume_change
```

The geographic momentum ledger is:

```text
P_after - P_before
  = lateral_momentum_change
  + Manning_friction_change
  + external_boundary_impulse
  + patch_solid_wall_impulse
  + transition_wall_impulse
```

Patch internal faces and patch/reach opening exchanges remain internal. The
Stage 18 per-opening mass cancellation and vector closure gates are rerun inside
the source-split transition. No transverse terminal state is introduced.

## Manufactured evidence

The Stage 19 compiler freezes the five Stage 18 artifacts and evaluates 23
gates. All pass.

For the zero-longitudinal-momentum baseline (`dt = 0.1081463 s`):

- lateral volume added is `1.51405 m3`;
- whole-system mass error is `3.28e-12 m3`;
- geographic momentum error is `7.15e-13 m4/s`;
- lateral momentum change is zero at stored precision;
- geographic Manning-friction change is approximately
  `[-2.72657, -0.79056] m4/s`; and
- the Stage 18 transition-wall impulse remains active at approximately
  `[-0.17315, -0.09006] m4/s`.

With matched-local-velocity semantics, lateral momentum change is approximately
`[0.23784, 0.30268] m4/s`. Mass and momentum errors remain below the gates.

A zero-flow, zero-lateral-inflow lake at rest preserves every patch and reach
state exactly at stored precision. A rigid 37-degree rotation preserves all
scalar reach states and covaries the lateral, friction, and transition-reaction
vectors; their maximum reported rotation error is below `1e-15 m4/s`.

Across 20 source-split steps:

- minimum patch-cell volume remains `190 m3`;
- minimum reach area is `19.8907 m2`;
- maximum mass-ledger error is `4.32e-12 m3`;
- maximum momentum-ledger error is `2.45e-12 m4/s`;
- transverse opening flux remains active; and
- no persistent transverse terminal state appears.

## Relation to traditional GIS operators

Traditional GIS tools can intersect rainfall or runoff rasters with reach
segments, aggregate drainage contributions, attach roughness classifications,
measure reach lengths, and sample land-cover or channel-survey attributes. The
result is a spatial dataset whose provenance, support, units, and timestamp must
be checked.

Stage 19 consumes those quantities as typed terms in an evolving conservation
law. Reach length converts lateral input density into volume; branch direction
rotates scalar source changes into geographic momentum; source timing controls
which state enters the nonlinear flux; and the global ledger distinguishes
forcing, dissipation, boundary transport, solid-wall force, and dimensional
transition reaction. Traditional GIS constructs and audits the spatial support;
the kernel determines how those supported quantities change world state.

## Data basis and claim boundary

The current evidence is manufactured and tests invariants, not predictive skill.
No private user data is required to continue development. Public precipitation,
runoff, hydrography, terrain, land-cover, and gauge data can supply future source
and geometry candidates, but their spatial support and information vintage must
be admitted before use. A land-cover-derived Manning value is a prior, not a
calibrated hydraulic truth.

Stage 19 supports:

- a conforming wet multi-cell patch coupled to 1D reaches;
- nonnegative, cellwise lateral inflow on every reach;
- explicit zero-momentum or matched-local-velocity inflow semantics;
- cellwise semi-implicit Manning friction on 1D reaches;
- source-adjusted common CFL selection;
- preserved Stage 18 transition-wall closure; and
- separate whole-system mass and geographic momentum ledgers.

It does not support:

- patch-bed friction or wall drag;
- negative lateral extraction, pumps, gates, or control actions;
- lateral inflow with an independently specified velocity vector;
- variable patch bed, irregular openings, or wetting and drying;
- calibrated roughness or uncertainty propagation; or
- completed public empirical validation.

The candidate remains diagnostic-only and unadmitted.

## Consequences and next work

Stage 19 makes the multi-cell network transition usable with distributed reach
forcing and roughness while preserving its dimensional accounting. The model no
longer needs to choose between a physically richer 2D junction and explicit 1D
source terms.

Stage 20 should add a typed 2D patch-bed friction law only after specifying the
roughness support for each polygon cell and proving rotational covariance,
energy dissipation, lake-at-rest preservation, and compatibility with the
Stage 19 split. Public-data work should separately assemble a reproducible
geometry and forcing fixture; gauge-only evidence must not be presented as a
validation of unobserved 2D vector momentum.

## Artifacts

- Implementation:
  `data_agent/uwm/geospatial_kernel_v2/coupled_junction_patch_reach_sources.py`
- Tests:
  `data_agent/test_geospatial_kernel_coupled_junction_patch_reach_sources.py`
- Gate compiler:
  `scripts/compile_geotransport_stage19_source_split_patch_reach_gates.py`
- Gate report:
  `benchmarks/geotransport_v0_1/stage19_source_split_coupled_junction_patch_reach_gates.json`
