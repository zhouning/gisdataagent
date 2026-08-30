# ADR-063: Public roughness support-uncertainty ensemble

- Status: implemented as a diagnostic uncertainty contract; hydraulic runtime
  admission remains closed
- Date: 2026-07-29
- Depends on: ADR-062

## Context

ADR-062 compiled the first real public-data confluence fixture. It assigned one
USDA NASS CDL 2024 class and one Manning prior to each of six finite-area cells.
Five cells contained no land-cover pixel center and therefore used the nearest
valid pixel. The native CDL resolution is 30 meters, while Stage 21 patch cells
range from approximately `110 m2` to `345 m2`. A single CDL pixel has nearly
`900 m2` of native support.

This scale mismatch makes the Stage 21 point assignment reproducible but not
unique. Treating it as exact would hide two distinct uncertainties:

1. a land-cover class maps to a range of plausible Manning values rather than
   one measured coefficient; and
2. a raster can be assigned by pixel center/nearest neighbor or by the actual
   overlap between pixel footprints and model cells.

The kernel needs to retain and propagate both sources without claiming that it
has addressed missing bathymetry, cross sections, depth, initial velocity, or
turbulence closure.

## Decision

Add `public_confluence_roughness_ensemble.py` as a typed Stage 22 wrapper around
the frozen Stage 20 friction primitive and the frozen Stage 21 public fixture.
No Stage 20 or Stage 21 implementation is modified. Nine Stage 21 artifacts are
frozen by hash.

For each patch cell, compile two spatial support rules:

```text
point rule:
  use contained pixel centers; if none, use the nearest valid pixel center

footprint rule:
  infer raster pixel rectangles from adjacent WGS84 sample centers,
  clip every rectangle against the exact patch-cell polygon,
  and area-weight class contributions over the cell
```

The resampled WGS84 grid has local pixel dimensions of approximately
`26.6771 m x 33.0498 m`, or `881.6724 m2`. The unequal local dimensions reflect
the geographic reprojection of the native 30-meter equal-area grid. They are
not interpreted as a new native sensor resolution.

Positive class footprints must cover every patch cell within `1e-6 m2`. A
positive unmapped class or a no-data footprint intersecting the patch fails
closed.

## Class and support intervals

For each support rule, area fractions weight the lower, central, and upper
Manning lookup values declared in ADR-062. The joint cell interval is the
envelope over both rules:

```text
joint_lower = min(point_lower, footprint_lower)
joint_upper = max(point_upper, footprint_upper)
```

Stage 22 discovers that footprint aggregation changes the central roughness in
three cells:

- `cell-00`: mostly open water with a deciduous-forest contribution;
- `cell-04`: open water mixed with deciduous and mixed forest; and
- `cell-05`: open water, deciduous forest, and mixed forest rather than the
  point rule's pure deciduous-forest assignment.

The six joint intervals are:

```text
cell-00  [0.025000, 0.048948]
cell-01  [0.025000, 0.040000]
cell-02  [0.025000, 0.040000]
cell-03  [0.025000, 0.040000]
cell-04  [0.025000, 0.078139]
cell-05  [0.054364, 0.160000]
```

The maximum absolute difference between the two central support-rule estimates
is `0.023820`. Raster aggregation is therefore material relative to the Manning
values themselves and must remain visible in the model contract.

## Ensemble members

Compile eight ordered fields, each with the exact Stage 20 geometry provenance
and cell area binding:

```text
joint_lower
point_lower
footprint_lower
point_center
footprint_center
point_upper
footprint_upper
joint_upper
```

This is a deterministic bounding ensemble, not a calibrated probability
distribution. Member order is part of the contract. No probability, likelihood,
or confidence level is assigned to an endpoint.

## Friction propagation diagnostic

Every member is propagated through the frozen Stage 20 semi-implicit vector
Manning primitive for one second. Because the public fixture still lacks
bathymetry and cross sections, the input state is deliberately manufactured:
each cell has `1.25 m` depth and a nonzero radial velocity varying by cell. The
state exists only to test parameter propagation and invariants. It is not an
observation, reconstruction, initial condition, or hydraulic simulation of the
real confluence.

The energy-dissipation results are:

```text
joint_lower       1.224835 m5/s2
point_lower       1.700021 m5/s2
footprint_lower   1.522578 m5/s2
point_center      3.106787 m5/s2
footprint_center  2.759144 m5/s2
point_upper       6.895465 m5/s2
footprint_upper   6.024900 m5/s2
joint_upper       8.364667 m5/s2
```

The joint endpoints bracket every member's total dissipation. In every cell,
the joint upper field has no larger damping factor and no smaller energy
dissipation than the joint lower field. All eight members preserve volume
exactly. The maximum vector-momentum ledger error is
`3.66e-14 m4/s`.

A rigid 37-degree rotation is applied to the geometry, input momentum, and
output comparison. Across all members and cells, the maximum rotated momentum
error is `3.18e-14 m4/s`; the maximum energy error is `5.68e-14 m5/s2`.

## Relation to traditional GIS operators

Traditional GIS supplies the essential spatial operations used here:

- interpret raster georeferencing;
- construct pixel footprints;
- clip polygons;
- calculate intersection areas; and
- summarize categorical fractions.

Those operations reveal which classes may support each model cell. They do not
by themselves decide how alternative support rules affect a temporal physical
state.

The geospatial kernel adds four responsibilities beyond the GIS overlay:

- preserve the alternative aggregation rule as model provenance rather than
  erasing it after preprocessing;
- turn class fractions into an explicitly uncertain parameter field while
  refusing probability claims that have not been estimated;
- propagate every field through the physical state transition and test mass,
  two-component momentum, direction, rotation, and energy consequences; and
- keep absent hydraulic evidence outside the claimed uncertainty closure.

Thus traditional GIS computes spatial support. The kernel makes support choice
part of the world-model state contract and audits how that choice changes future
state transitions.

## Claim boundary

Stage 22 supports:

- public land-cover spatial-support uncertainty;
- land-cover-to-Manning lookup intervals;
- deterministic joint bounds across two support rules;
- exact Stage 20 cell and geometry binding for every member;
- friction-response propagation with conservative ledgers; and
- rotation-covariant ensemble behavior.

It does not support:

- calibrated Manning coefficients or a posterior distribution;
- bathymetry or cross-section uncertainty;
- observed water depth or two-dimensional velocity state;
- an admitted real-confluence hydraulic rollout;
- public vector-momentum validation; or
- operator admission.

The Stage 21 typed refusal for missing bathymetry and cross sections remains in
force. Stage 22 narrows one real uncertainty source; it does not convert a
horizontal fixture into a validated hydraulic model.

## Evidence

All 20 gates pass:

- all frozen Stage 21 hashes match;
- pixel footprints cover every patch cell;
- nearest-pixel dependencies and support-sensitive cells are explicit;
- every joint interval envelopes both support rules;
- all eight fields preserve exact Stage 20 spatial binding;
- all mass and vector-momentum ledgers close;
- joint endpoints bracket total and cellwise energy dissipation;
- the support-rule difference changes the friction response;
- the complete ensemble is rotation covariant; and
- unknown classes, state ordering errors, and invalid timesteps fail closed.

## Consequences and next work

The kernel now represents a real data-resolution ambiguity as part of its state
transition evidence rather than collapsing it during GIS preprocessing. This is
a concrete example of the geospatial world-model kernel: geographic support,
parameter meaning, physical transition, uncertainty, and claim boundaries are
one auditable contract.

Stage 23 should pursue public hydraulic geometry independently of this ensemble.
The highest-value bounded search is for USGS field-measurement cross sections,
rating measurement metadata, 3DEP lidar point clouds with water/bank context,
and openly licensed bathymetric or surveyed bridge/river-section records near
the Center Hill network. Any terrain-derived approximation must remain a
separate candidate and must not weaken the existing fail-closed boundary.

## Artifacts

- Implementation:
  `data_agent/uwm/geospatial_kernel_v2/public_confluence_roughness_ensemble.py`
- Tests:
  `data_agent/test_geospatial_kernel_public_confluence_roughness_ensemble.py`
- Gate compiler:
  `scripts/compile_geotransport_stage22_public_roughness_ensemble_gates.py`
- Ensemble:
  `data/geotransport_v0_1/stage22_center_hill_roughness_ensemble/roughness_ensemble.json`
- Propagation report:
  `data/geotransport_v0_1/stage22_center_hill_roughness_ensemble/friction_propagation.json`
- Gate report:
  `benchmarks/geotransport_v0_1/stage22_public_roughness_ensemble_gates.json`

