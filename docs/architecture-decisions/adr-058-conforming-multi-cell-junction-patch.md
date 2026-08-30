# ADR-058: Conforming multi-cell shallow-water junction patch

- Status: implemented as a native candidate; synchronous reach coupling and
  public validation pending
- Date: 2026-07-28
- Depends on: ADR-057

## Context

ADR-055 introduced a finite-area junction state, but represented the whole
confluence as one spatially uniform cell. ADR-056 and ADR-057 coupled that cell
to 1D reaches and source terms while retaining transverse opening momentum in
a passive terminal reservoir.

The passive reservoir made loss of momentum explicit, but it could not express
where that momentum travels inside the junction. A uniform cell has no
internal faces, travel path, recirculation region, or local water-surface
gradient. It therefore cannot distinguish momentum passing toward another
opening from momentum reaching a wall.

## Decision

Implement a conforming multi-cell finite-area patch in
`shallow_water_junction_patch.py`. Preserve all five Stage 16 artifacts by
hash. Stage 17 is a new two-dimensional patch core and does not modify the
frozen Stage 15 or Stage 16 reach couplers.

Each patch cell stores:

```text
U_cell = [V, M_east, M_north]
```

For cell plan area `S`:

```text
h       = V / S
u_east  = M_east / V
u_north = M_north / V
```

The patch may contain any connected set of admitted polygon cells. Stage 17
uses a four-cell manufactured grid, but the implementation is not hard-coded
to four cells.

## Geographic mesh contract

Vertices carry explicit east/north metric coordinates. Every cell declares a
counterclockwise vertex ring. Every directed polygon edge must be covered
exactly once by either:

- an internal face;
- a branch opening; or
- a solid wall.

An internal face is stored once, oriented as an edge of its left cell. The
right cell must contain the same vertex pair in reverse order. The
implementation verifies:

- positive counterclockwise polygon area;
- a simple, non-self-intersecting ring for every cell;
- exact reversed internal-edge pairing;
- complete edge coverage;
- connectivity of the internal cell graph; and
- closure of the external oriented length-normal measure.

This is stronger than Stage 14's length-normal boundary contract because the
vertices and cell adjacency are now explicit. It does not yet independently
prove that arbitrary nonadjacent cell polygons never overlap. That limitation
is retained in the claim boundary.

## Internal HLL exchange

For each internal face, rotate the left and right cell states into outward
normal and tangential components:

```text
U = [h, h u_n, h u_t]

F_n(U) = [
  h u_n,
  h u_n^2 + g h^2 / 2,
  h u_n u_t
]
```

The face uses the same two-dimensional HLL signal bounds as Stage 14. The
flux is evaluated once. The left cell receives its negative impulse and the
right cell receives the equal positive impulse:

```text
U_left,next  = U_left  - dt F_face
U_right,next = U_right + dt F_face
```

This single-evaluation rule prevents two independently rounded Riemann solves
from creating an internal conservation residual.

## External faces and walls

Branch openings retain the Stage 13 subcritical boundary reconstruction and
the Stage 14 rotated HLL opening law. Rectangular opening width must equal face
length, bed elevation must match the flat patch bed, and the face normal must
match the declared geographic branch direction.

Solid walls use the hydrostatic reflective-slip pressure flux:

```text
F_wall = L g h^2 / 2 n
```

The whole-patch mass ledger contains only branch-opening mass flux. The
whole-patch momentum ledger contains branch-opening vector flux and wall
pressure. Internal faces cancel exactly and do not appear as external terms.

## Cellwise CFL and drain bounds

For every cell, the spectral timestep is computed from all incident internal
and external faces:

```text
dt_wave = CFL * cell_area / sum(L_face * max_abs_signal_speed_face)
```

If the signed net face flow drains the cell, an additional bound is applied:

```text
dt_drain = CFL * cell_volume / net_outward_discharge
```

The patch uses the minimum bound over all cells. Nonpositive post-step cell
volume and excessive timesteps fail closed.

## Manufactured evidence

The Stage 17 compiler freezes the five Stage 16 artifacts and evaluates 21
gates. All pass.

The manufactured geometry contains four `100 m2` cells, four internal faces,
three branch openings, and five solid-wall faces. Its external oriented
boundary closes exactly at stored precision.

For the asymmetric baseline (`dt = 0.10832 s`):

- whole-patch mass error is `3.66e-15 m3`;
- whole-patch vector momentum error is `4.44e-16 m4/s`;
- internal mass and vector impulse cancellation errors are zero;
- maximum cell momentum ledger error is `4.44e-16 m4/s`; and
- all cell volumes remain positive.

A uniform lake at rest preserves every cell exactly at stored precision. Both
global ledger errors are zero.

A rigid 37-degree rotation preserves every cell volume. Maximum cell momentum
rotation error is `4.57e-15 m4/s`; the stable-timestep difference is
`8.33e-17 s`.

Across 25 steps, the minimum cell volume remains `190 m3`. Maximum stepwise
mass error is `2.29e-13 m3` and maximum momentum error is
`1.65e-14 m4/s`. The selected internal mass flux changes from
`2.21435 m3/s` to `0.50828 m3/s`, demonstrating internal state propagation.

## Relation to traditional GIS operators

Traditional GIS and mesh tooling can construct polygons, snap shared edges,
calculate area, validate rings, detect overlaps, orient boundaries, and attach
river centerlines. Those capabilities should ultimately produce the Stage 17
mesh contract from public terrain and hydrography.

The kernel consumes that topology as part of the physical law. Shared edges
become conservative exchange surfaces; polygon area converts volume into
depth; geographic normals rotate vector momentum; cell adjacency determines
propagation paths; and invalid topology stops the transition. GIS supplies
the spatial discretization, while the kernel evolves the conserved state and
audits dimensional invariants.

## Claim boundary

Stage 17 supports:

- a connected conforming polygon patch;
- flat bed shared by all cells and openings;
- wet cell and boundary states;
- rectangular branch openings;
- two-dimensional HLL internal and opening fluxes; and
- hydrostatic reflective-slip walls.

It does not yet support:

- synchronous updates of attached 1D reaches;
- Stage 16 reach friction and lateral sources inside the patch transition;
- variable bed elevation or hydrostatic reconstruction between patch cells;
- dry fronts or wetting and drying;
- patch bed friction, wall drag, turbulence, or sediment;
- independent pairwise polygon-overlap proof; or
- empirical public-data validation.

The Stage 16 passive reservoir is therefore not yet removed from the coupled
network operator. Stage 17 establishes the multidimensional state space that
can replace it, but the 2D-to-1D transition law remains the next task.

## Consequences and next work

The Geospatial Kernel can now represent a confluence as an oriented finite-area
mesh rather than a scalar graph node or one lumped cell. This is a substantive
step toward the requested geographic kernel: topology and direction directly
control the model's internal state transition.

Stage 18 should synchronously couple branch terminal cells to the external
faces of this patch. It must specify what happens to tangential momentum at a
2D-to-1D transition without reintroducing a passive accumulator. Acceptable
options include an explicit transition-wall reaction or a resolved channel
extension inside the 2D patch; silently discarding the tangential component is
not acceptable.

The candidate remains diagnostic-only and unadmitted.

## Artifacts

- Implementation:
  `data_agent/uwm/geospatial_kernel_v2/shallow_water_junction_patch.py`
- Tests:
  `data_agent/test_geospatial_kernel_shallow_water_junction_patch.py`
- Gate compiler:
  `scripts/compile_geotransport_stage17_junction_patch_gates.py`
- Gate report:
  `benchmarks/geotransport_v0_1/stage17_shallow_water_junction_patch_gates.json`
