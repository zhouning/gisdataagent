# ADR-061: Spatially supported patch Manning friction

- Status: implemented as a native candidate; roughness calibration and public
  validation pending
- Date: 2026-07-29
- Depends on: ADR-060

## Context

ADR-060 integrated cellwise lateral inflow and Manning friction on the 1D
reaches surrounding a multi-cell 2D junction patch. It intentionally left patch
friction undefined because a scalar roughness value without polygon support or
provenance would weaken the geographic contract.

The patch nevertheless needs a dissipative bed-friction mechanism before it can
represent sustained two-dimensional circulation. That mechanism must preserve
mass, act on the complete east/north momentum vector, be rotation invariant,
and bind every roughness value to the exact cell geometry it describes.

## Decision

Implement the primitive and coupled wrapper in
`coupled_junction_patch_reach_patch_friction.py`. Freeze all five Stage 19
artifacts by hash.

Every patch roughness field declares:

- junction identity;
- geometry provenance identity;
- one positive finite Manning value per patch cell;
- the polygon support area for each value;
- per-cell parameter provenance; and
- field-level provenance.

Cell order must exactly match the patch geometry and evolving state. Declared
support areas must match polygon areas within a metric tolerance. Geometry
vintage, missing cells, reordered cells, nonpositive roughness, and area
mismatch fail closed.

## Two-dimensional Manning law

For one wet finite-area cell, let:

```text
V = water volume
S = polygon plan area
h = V / S
M = [M_east, M_north]
u = M / V
```

Stage 20 uses local depth as the wide-cell hydraulic-radius approximation and
applies the semi-implicit vector update:

```text
lambda = g n^2 |u| / h^(4/3)
M_next = M / (1 + dt lambda)
V_next = V
```

The same scalar damping factor multiplies both geographic momentum components.
Consequently, the operator preserves vector direction, cannot reverse flow,
and is invariant under a rigid coordinate rotation.

The horizontally integrated kinetic-energy quantity is:

```text
K = |M|^2 / (2 V)    [m5/s2]
```

For positive timestep and roughness, `0 < damping_factor <= 1`, so every cell
has nonnegative `K_before - K_after`. The exact momentum difference is recorded
as the patch-friction impulse.

The local-depth hydraulic-radius rule is a modeling approximation, not a claim
that an arbitrary polygon is a surveyed wide rectangular channel.

## Coupled source order

Patch friction is wrapped around the frozen Stage 19 source-split transition:

```text
patch_friction_half
(lateral_half + reach_friction_half)
stage18_patch_reach_conservative_core_full
(reach_friction_half + lateral_half)
patch_friction_half
```

Patch friction and reach source terms act on disjoint state partitions before
and after the conservative core, so their relative ordering within each source
half-step is commutative. The Stage 19 implementation and Stage 18 opening law
remain unchanged.

The common timestep is evaluated again after the first patch-friction half-step.
Although friction normally lowers signal speed, the iterative contract does not
assume that outcome; it reduces the candidate and repeats if the source-adjusted
Stage 19 bound is smaller.

## Whole-system ledgers

Patch friction has no mass source. The global volume ledger remains:

```text
V_after - V_before
  = lateral_volume_change + external_boundary_volume_change
```

The geographic momentum ledger becomes:

```text
P_after - P_before
  = lateral_momentum_change
  + reach_Manning_friction_change
  + patch_Manning_friction_change
  + external_boundary_impulse
  + patch_solid_wall_impulse
  + transition_wall_impulse
```

The two patch-friction impulses are reported separately and as a combined
change. Stage 18 per-opening vector closure and transition-wall reaction remain
part of the nested evidence.

## Manufactured evidence

The Stage 20 compiler freezes all five Stage 19 artifacts and evaluates 25
gates. All pass.

The manufactured roughness field assigns `n = 0.030, 0.035, 0.040, 0.045` to
the four `100 m2` patch cells with explicit cell provenance. These values test
spatial variation; they are not calibrated estimates.

For a one-second primitive friction step:

- patch volume error is zero;
- vector-momentum ledger error is `1.78e-15 m4/s`;
- integrated kinetic-energy dissipation is `2.62e-4 m5/s2`; and
- every cell preserves its original momentum direction.

For the complete source-split baseline (`dt = 0.1081461 s`):

- whole-system mass error is `-2.18e-12 m3`;
- geographic momentum error is `5.03e-13 m4/s`;
- patch-friction momentum change is approximately
  `[-4.09e-4, -2.37e-4] m4/s`; and
- the two patch half-steps dissipate `3.41e-5 m5/s2`.

A zero-flow lake at rest preserves every patch and reach state exactly. A rigid
37-degree rotation preserves scalar reach states, covaries every patch-cell
momentum, and covaries the combined patch-friction impulse. The maximum coupled
patch rotation error is `8.19e-15 m4/s`.

Across 20 complete steps:

- minimum patch-cell volume remains `190 m3`;
- minimum reach area is `19.8907 m2`;
- maximum mass-ledger error is `6.02e-12 m3`;
- maximum momentum-ledger error is `1.45e-12 m4/s`; and
- accumulated patch-friction dissipation is `0.00610 m5/s2`.

## Relation to traditional GIS operators

Traditional GIS software can classify land cover, sample roughness rasters,
intersect parameter polygons with mesh cells, calculate area-weighted summaries,
and preserve source metadata. Those operations create a spatial roughness field;
they do not define how water momentum changes through time.

Stage 20 turns the field into a typed state transition. Polygon area determines
depth, geometry identity prevents applying parameters to the wrong mesh vintage,
the geographic momentum vector makes rotation covariance testable, and energy
dissipation becomes a gate. GIS establishes where a parameter applies and where
it came from; the kernel applies the physical law and audits its consequences.

## Data basis and claim boundary

No private user data is assumed. Public land-cover, terrain, hydrography, and
hydraulic-reference products may supply roughness priors and polygon support.
However, land-cover lookup values are uncertain priors, not site-calibrated
Manning coefficients. A public-data compiler must retain source vintage,
classification mapping, aggregation method, missingness, and uncertainty.

Stage 20 supports:

- exact per-cell polygon support for patch roughness;
- geometry and parameter provenance binding;
- wet flat-bed 2D semi-implicit vector Manning drag;
- mass preservation and exact vector-impulse accounting;
- nonnegative patch kinetic-energy dissipation;
- source-adjusted coupling with all Stage 19 reach terms; and
- preservation of the Stage 18 transition reaction.

It does not support:

- calibrated or observed patch roughness;
- uncertainty ensembles or roughness inference;
- wall shear distinct from bed friction;
- nonlocal turbulence or subgrid recirculation closure;
- variable patch bed, irregular openings, or wetting and drying; or
- completed public empirical validation.

The candidate remains diagnostic-only and unadmitted.

## Consequences and next work

The multi-cell patch now has a geographically bound dissipative source law
instead of frictionless internal circulation. This completes the basic source
inventory for the current wet, flat-bed network transition without modifying
the frozen conservative core.

The next stage should shift from additional manufactured physics to a bounded
public-data compiler: derive one reproducible confluence geometry, cell support,
reach directions, terrain attributes, and roughness-prior field from open data.
Hydraulic observations should be treated according to what they actually
measure; gauge stage and discharge can test boundary and mass behavior but do
not directly validate unobserved two-dimensional momentum.

## Artifacts

- Implementation:
  `data_agent/uwm/geospatial_kernel_v2/coupled_junction_patch_reach_patch_friction.py`
- Tests:
  `data_agent/test_geospatial_kernel_coupled_junction_patch_reach_patch_friction.py`
- Gate compiler:
  `scripts/compile_geotransport_stage20_patch_friction_source_split_gates.py`
- Gate report:
  `benchmarks/geotransport_v0_1/stage20_patch_friction_source_split_gates.json`
