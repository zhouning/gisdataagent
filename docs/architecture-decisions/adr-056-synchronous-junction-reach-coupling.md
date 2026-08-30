# ADR-056: Synchronous 2D junction and 1D reach coupling

- Status: implemented as a native candidate; source coupling and public
  validation pending
- Date: 2026-07-28
- Depends on: ADR-055

## Context

ADR-055 gave a confluence its own finite-area two-dimensional shallow-water
state and explicit wall-pressure flux. Its HLL opening flux updated the
junction cell, but the adjacent one-dimensional reaches did not receive the
equal-and-opposite exchange in the same timestep. The cell was therefore a
valid local control-volume candidate but not yet a globally conservative
network transition.

The coupling has a dimensional mismatch that cannot be hidden. A geographic
opening flux contains east and north momentum, while a one-dimensional reach
stores only longitudinal momentum. Projecting the opening flux onto the reach
axis and discarding the remainder would make the scalar reach update appear
reasonable while violating the geographic momentum law.

## Decision

Implement synchronous coupling in `coupled_junction_reach.py`. Preserve the
five Stage 14 artifacts by hash and leave the frozen Stage 13 and 14
implementations unchanged.

At the start of each step, construct terminal states from the current reach
cells and resolve the existing subcritical common-stage boundary contract.
Use those boundary states and the current junction-cell state in the Stage 14
rotated two-dimensional HLL problem. The same opening mass and vector momentum
flux is then applied simultaneously to the cell and its attached reach.

For branch flow tangent `t` and the outward-from-junction opening flux
`(q, J)`, split the momentum flux as:

```text
J_longitudinal = (J dot t) t
J_transverse   = J - (J dot t) t
```

The branch-side and junction-side impulses are:

```text
branch volume impulse   = +dt q
junction volume impulse = -dt q

branch longitudinal impulse = +dt J_longitudinal
branch transverse impulse   = +dt J_transverse
junction opening impulse    = -dt J
```

Each opening therefore cancels independently in mass and both geographic
momentum components.

## One-dimensional boundary signs

Reach coordinates always point along the declared flow tangent. Upstream
reaches attach to the junction at their right boundary; the downstream reach
attaches at its left boundary. The finite-volume flux overrides are:

```text
upstream right boundary:
  area flux     = -q
  momentum flux = -(J dot t)

downstream left boundary:
  area flux     = +q
  momentum flux = +(J dot t)
```

These signs make the integrated terminal reach cell receive `+dt q` and
`+dt (J dot t)` for either branch role. Internal reach interfaces retain the
existing hydrostatic HLL implementation.

## Transverse momentum reservoir

The transverse impulse is stored in an explicit terminal reservoir for every
branch. The reservoir is a geographic east/north vector constrained to remain
orthogonal to the branch tangent. It is part of the global momentum state and
is never discarded or reassigned to another branch.

This reservoir is an interface-scale accounting state, not a claim that a 1D
reach has acquired transverse hydrodynamics. It does not yet feed back into
subsequent opening fluxes. A passive reservoir can accumulate momentum over a
long rollout, so closure of this Stage 15 ledger is necessary but not enough
for physical admission. Replacing it with a resolved near-junction 2D mesh or
a validated subgrid relaxation law is future work.

## Global ledgers

The total stored water is the sum of all reach-cell volumes and the junction
volume. Node exchange cancels internally, leaving only the upstream external
inflow and downstream external outflow in the global mass ledger.

The geographic momentum state is:

```text
P_total = P_junction
        + sum(P_reach_longitudinal t)
        + sum(P_terminal_transverse)
```

The expected external impulse includes the physical flux at each open reach
boundary and the negative of the junction wall-pressure outflux. The complete
east/north ledger is therefore:

```text
P_after - P_before
  = dt F_external_reaches - dt F_junction_walls
```

Opening HLL fluxes do not appear on the right-hand side because the branch and
junction contributions cancel pairwise.

## Supported scope and refusals

Stage 15 deliberately admits only the clean homogeneous coupling baseline:

- at least two upstream reaches and exactly one downstream reach;
- wet, subcritical states supported by the predecessor junction solver;
- a flat bed shared by the junction, every reach cell, and external boundary;
- uniform rectangular reach sections whose width equals the attached opening;
- zero lateral inflow; and
- one explicit transverse reservoir per branch in exact contract order.

Branch identifier or order mismatch, nonrectangular or variable-width
sections, bed steps, lateral sources, a nontransverse reservoir, and a timestep
above the common reach-cell CFL limit fail closed. Manning values remain part
of the reach container but friction is not applied in this Stage 15 step.

Friction and lateral-flow Strang splitting, nonuniform hydrostatic source
terms, dry fronts, irregular openings, multiple 2D junction cells, sediment,
and reservoir feedback are outside the claim boundary. They are not silently
approximated.

## Manufactured evidence

The Stage 15 compiler freezes all five Stage 14 artifacts and evaluates 18
gates. All pass.

For the asymmetric single step (`dt = 0.06713 s`), the whole-system mass
ledger closes to stored precision and the geographic momentum error is
`4.71e-13 m4/s`. The maximum per-opening vector cancellation error is
`2.51e-15 m4/s`.

A lake at rest preserves all reach states exactly at stored precision. The
junction-state residual is `4.00e-15` in the combined manufactured norm and
the maximum transverse reservoir magnitude is `5.66e-15 m4/s`.

A rigid 37-degree rotation leaves every scalar reach state unchanged and
rotates the junction and reservoir vectors. The junction momentum rotation
error is `1.53e-14 m4/s`; the maximum reservoir rotation error is
`6.39e-15 m4/s`.

Across 25 synchronous steps, the minimum reach area is `19.8994 m2` and the
minimum junction volume is `190 m3`. Maximum stepwise ledger errors are
`4.95e-12 m3` for mass and `3.00e-12 m4/s` for geographic momentum. The
largest terminal transverse reservoir reaches `7.98 m4/s`, proving that the
component unavailable to the 1D state remains explicit during asymmetric
evolution.

## Relation to traditional GIS operators

Traditional GIS supplies the spatial facts required by this law: reach
centerline direction, branch role, junction polygon, opening length, plan
area, and bed or section attributes. It can validate identifiers, topology,
orientation, and measurements, but it normally does not evolve a conservative
hydrodynamic state.

This kernel uses those geographic facts inside the state-transition law. A
rigid map rotation must rotate vector state without changing scalar hydraulics;
an opening must exchange equal-and-opposite mass and momentum; and unsupported
geometry must stop execution. GIS preprocessing remains essential, while the
kernel adds temporal dynamics, physical units, invariants, CFL bounds,
provenance, and typed refusal.

## Consequences and next work

Stage 15 closes the immediate conservation gap identified by ADR-055. The 2D
junction cell and all adjacent 1D terminal cells now advance from the same
opening flux in one timestep, without deleting the transverse component.

The result remains diagnostic-only and unadmitted. Its current success is a
manufactured-law result, not empirical validation. No open machine-readable
confluence dataset with the required geometry and hydraulic state variables
was identified in the bounded Stage 13 search.

The next scientific increments should be ordered as follows:

1. add well-balanced friction and lateral-source splitting while preserving
   the Stage 15 opening exchange;
2. define a nonpassive transverse closure, preferably through a small 2D
   near-junction mesh rather than an unconstrained fitted decay coefficient;
3. replace manufactured face measures with polygon-derived oriented geometry
   and verify vertex topology; and
4. validate against an independently sourced public laboratory or field
   dataset when its numeric observations can be legally acquired.

## Artifacts

- Implementation:
  `data_agent/uwm/geospatial_kernel_v2/coupled_junction_reach.py`
- Tests:
  `data_agent/test_geospatial_kernel_coupled_junction_reach.py`
- Gate compiler:
  `scripts/compile_geotransport_stage15_coupled_junction_gates.py`
- Gate report:
  `benchmarks/geotransport_v0_1/stage15_coupled_junction_reach_gates.json`
