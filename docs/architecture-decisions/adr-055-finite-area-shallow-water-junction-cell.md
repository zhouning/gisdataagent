# ADR-055: Finite-area shallow-water junction control cell

- Status: implemented as a native candidate; coupled reach update pending
- Date: 2026-07-28
- Depends on: ADR-054

## Context

ADR-054 introduced a geographic two-component momentum ledger for a
zero-storage one-dimensional confluence. It made the required junction
reaction explicit instead of discarding transverse momentum, but the reaction
was still inferred by setting it equal to the terminal generalized-flux
imbalance. The node itself had no water volume or momentum state.

That was a necessary accounting stage, not the final geographic kernel. A
world-model kernel should be able to represent a confluence as a place with
finite area, storage, orientation, boundary geometry, and evolving horizontal
momentum. Otherwise the node cannot retain memory or feed its state back into
later exchanges.

## Decision

Implement one finite-area, uniform shallow-water control cell in
`shallow_water_junction_cell.py`. Preserve all Stage 13 artifacts by hash and
do not modify the frozen Stage 10-13 operators.

The conserved cell state is:

```text
U_cell = [V, M_east, M_north]

V       = integral(h dA)
M_east  = integral(h u_east dA)
M_north = integral(h u_north dA)
```

For a uniform cell with plan area `S`:

```text
h = V / S
u_east  = M_east / V
u_north = M_north / V
```

This gives the junction independent water-surface and velocity state. Its
surface is not forced to remain equal to the Stage 13 common stage. A stage
difference is resolved by the opening Riemann problem and changes subsequent
exchange.

## Oriented boundary geometry

Each junction boundary face has a length and an outward normal azimuth,
measured clockwise from true north. Branch openings additionally carry an
exact branch identifier and upstream/downstream role. Solid-wall faces carry
no branch.

The oriented boundary measure must close:

```text
sum(L_face * n_face) = [0, 0]
```

This identity is required for lake-at-rest preservation: uniform hydrostatic
pressure integrated over a closed boundary must have zero resultant. The
current contract verifies the oriented length-normal measure, but not polygon
vertex topology or self-intersection. Plan area and face measures therefore
require explicit provenance and remain manufactured in Stage 14.

## Opening flux

For every branch opening, the coordinate system is rotated into outward
normal and tangential components. The cell is the left Riemann state and the
one-dimensional branch boundary is reconstructed as a two-dimensional right
state whose velocity follows its geographic flow azimuth.

The conserved state per unit width and normal physical flux are:

```text
U = [h, h u_n, h u_t]

F_n(U) = [
  h u_n,
  h u_n^2 + g h^2 / 2,
  h u_n u_t
]
```

The interface uses the standard HLL signal bounds:

```text
s_left  = min(u_n,left - sqrt(g h_left),
              u_n,right - sqrt(g h_right))
s_right = max(u_n,left + sqrt(g h_left),
              u_n,right + sqrt(g h_right))
```

The resulting normal and tangential momentum flux is rotated back into east
and north components and multiplied by opening length. No fitted coefficient
or HEC-RAS residual correction is used.

## Solid walls and update

Solid walls use a reflective slip boundary. Their mass flux is zero and their
uniform-cell hydrostatic pressure flux is:

```text
F_wall = L_wall * g h^2 / 2 * n_wall
```

The explicit finite-volume update is:

```text
V_next = V - dt * sum(Q_out,opening)

M_next = M - dt * (
  sum(F_momentum,opening) + sum(F_pressure,wall)
)
```

The Stage 13 inferred reaction is not an input to this update. Directional
imbalance changes cell momentum, while wall pressure is computed from the
declared boundary geometry.

The timestep is bounded by a face-spectral CFL limit based on plan area and by
a volume-draining limit when net flow is outward. Nonpositive or nonfinite
states and excessive timesteps fail closed.

## Supported scope

Stage 14 deliberately supports only:

- one uniform finite-area junction cell;
- a flat bed shared by the cell and all openings;
- rectangular branch openings whose face length equals channel width;
- at least two upstream openings and exactly one downstream opening;
- wet states; and
- subcritical boundary states inherited from the Stage 13 coupling.

Trapezoidal or irregular openings, bed steps, dry-state fronts, polygon meshes,
friction, turbulence closure, and sediment are not silently approximated.
They have typed rejection or remain outside the claim boundary.

## Manufactured evidence

The Stage 14 compiler freezes ten Stage 13 artifacts and evaluates 16 gates.
All pass.

In the dynamic manufactured case, a `0.06755 s` step changes the cell from:

```text
V = 200.00000 m3
M = [0, 0] m4/s
```

to:

```text
V = 200.03934 m3
M = [-0.25524, 3.08448] m4/s
```

The mass ledger error is `8.31e-15 m3` in magnitude and the two-component
momentum ledger error is zero at stored precision.

A lake at rest retains `V=200 m3`; its residual north momentum is
`4.00e-15 m4/s`. A rigid 37-degree rotation preserves scalar mass exchange to
`8.88e-16 m3/s` and rotates the momentum update with vector error
`1.90e-14 m4/s`.

Starting from depth `1.9 m`, 25 successive HLL updates remain positive. The
opening mass exchange changes from `-7.57155` to `-2.81087 m3/s`, demonstrating
that the evolving cell state feeds back into later Riemann solves. Maximum
multistep ledger errors are `1.33e-14 m3` for mass and `3.11e-15 m4/s` for
momentum.

## Relation to GIS operators

Traditional GIS can construct the junction polygon, measure area, orient
boundary segments, and attach river centerlines. Those are required inputs,
but the Stage 14 operator goes further: it evolves water volume and geographic
momentum, resolves directional Riemann fluxes, enforces conservation and CFL
conditions, and returns dimensional ledgers and typed refusals.

The distinction is not that GIS geometry is replaced. GIS geometry becomes a
first-class physical boundary contract inside the model rather than a
preprocessing artifact.

## Claim boundary and next work

Stage 14 establishes an explicit multidimensional node state, but it is not
yet a fully coupled network solver. The HLL opening flux changes the cell while
the adjacent one-dimensional reach terminal cells are not updated with the
equal-and-opposite exchange in the same timestep. Treating the current result
as globally conservative network evolution would therefore be an overclaim.

Stage 15 should implement synchronous branch-cell coupling:

1. replace the existing common-stage node boundary override with the Stage 14
   opening HLL flux;
2. apply each opening flux with opposite sign to its adjacent reach terminal
   cell and the junction cell;
3. use a common CFL timestep across all reaches and junction cells;
4. verify whole-network mass plus east/north momentum ledgers;
5. preserve lake at rest across reach-cell interfaces; and
6. retain the existing public-validation refusal until independent numeric
   observations become available.

The candidate remains diagnostic-only and is not admitted.

## Artifacts

- Implementation:
  `data_agent/uwm/geospatial_kernel_v2/shallow_water_junction_cell.py`
- Tests:
  `data_agent/test_geospatial_kernel_shallow_water_junction_cell.py`
- Compiler:
  `scripts/compile_geotransport_stage14_junction_cell_gates.py`
- Gate report:
  `benchmarks/geotransport_v0_1/stage14_shallow_water_junction_cell_gates.json`
