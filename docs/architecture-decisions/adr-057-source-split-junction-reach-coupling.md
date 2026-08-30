# ADR-057: Source-split junction and reach coupling

- Status: implemented as a native candidate; junction-cell closure and public
  validation pending
- Date: 2026-07-28
- Depends on: ADR-056

## Context

ADR-056 synchronously coupled the finite-area 2D junction cell to its adjacent
1D reaches. It conserved water and geographic momentum across each opening,
but deliberately rejected nonzero lateral inflow and did not apply the Manning
roughness already present in the reach contracts.

That homogeneous baseline was necessary for isolating the opening law. A
useful geographic world-model kernel must also distinguish water entering
along a reach from distributed water added inside it, and must represent the
loss of longitudinal momentum to bed and bank drag. Adding those effects
without an explicit source ledger would make it impossible to tell physical
dissipation from a broken junction exchange.

## Decision

Implement `coupled_junction_reach_sources.py` as a source-split wrapper around
the frozen Stage 15 core. Preserve all five Stage 15 artifacts by hash and do
not modify their opening-flux implementation.

For timestep `dt`, use the symmetric order:

```text
lateral inflow:       dt / 2
Manning friction:     dt / 2
Stage 15 HLL core:    dt
Manning friction:     dt / 2
lateral inflow:       dt / 2
```

This is a Strang-style composition. The source-adjusted CFL is not evaluated
only on the initial state. A candidate timestep is used to apply the first two
half steps, the Stage 15 common CFL is recomputed on that prepared state, and
the candidate is reduced until it is admissible.

## Lateral water and momentum semantics

The distributed lateral input has units `m2/s` per reach cell. Over cell
length `dx`, its prescribed water-volume change is:

```text
dV_lateral = q_lateral * dx * dt
```

Negative lateral input is not supported by the inherited primitive. It is not
silently reinterpreted as infiltration, abstraction, or evaporation.

Two explicit longitudinal-momentum conventions are supported:

```text
zero_longitudinal_momentum
  added water changes area but injects no reach-axis momentum

matched_local_velocity
  added water carries the current local reach-axis velocity
```

The second convention is not a model of cross-channel inflow direction. It
only states the longitudinal momentum assigned at the 1D resolution. A future
2D rainfall, hillslope, or tributary interface needs geographic source
direction rather than this scalar convention.

## Manning friction

Every reach cell uses its declared trapezoidal section and Manning `n`. On the
currently admitted flat-bed geometry, the implicit friction-only update is:

```text
Q_next = Q / (1 + dt * D(A, section, n) * abs(Q))
```

where `D` is the dimensional drag factor computed from area and hydraulic
radius. Area is unchanged, flow direction is preserved, and positive flow
loses longitudinal momentum. The junction cell itself has no friction or
turbulence source in Stage 16.

## Global conservation ledger

The Stage 16 mass balance is:

```text
V_after - V_before
  = dV_lateral + dV_external_reach_boundaries
```

Friction contributes no water. Opening exchange remains internal and cancels
between the Stage 15 junction and branch states.

For each reach, the two lateral and two friction substeps are measured from
their actual before and after longitudinal momentum integrals. Those scalar
changes are rotated into east/north coordinates using the frozen branch flow
tangent. The whole-system geographic momentum balance is:

```text
P_after - P_before
  = dP_lateral
  + dP_friction
  + dP_external_reach_boundaries
  + dP_junction_wall_pressure
```

The complete Stage 15 opening impulse and terminal transverse reservoir remain
inside the state transition and cancel from the external ledger.

## Supported scope and refusals

Stage 16 inherits the Stage 15 restrictions:

- one uniform 2D junction cell;
- flat bed and uniform rectangular attached reaches;
- wet subcritical terminal states;
- at least two upstream branches and exactly one downstream branch; and
- a passive transverse terminal-momentum reservoir.

It adds nonnegative distributed lateral inflow and cellwise positive Manning
roughness. An unspecified lateral-momentum convention, excessive timestep,
branch mismatch, negative lateral input, or any inherited unsupported geometry
fails closed.

The following remain outside the claim boundary:

- junction-cell wall or bed friction and turbulence;
- transverse reservoir feedback;
- geographic direction of lateral source momentum;
- negative source/sink fluxes;
- irregular openings, bed steps, dry fronts, and 2D junction meshes; and
- empirical public-data validation.

## Manufactured evidence

The Stage 16 compiler freezes the five Stage 15 artifacts and evaluates 19
gates. All pass.

For the zero-longitudinal-momentum case, a `0.06713 s` step adds
`0.93975 m3` of lateral water. The lateral momentum change is exactly zero at
stored precision. Whole-system mass error is `5.14e-13 m3` in magnitude and
geographic momentum error is `1.51e-12 m4/s`.

With matched local velocity, the lateral source contributes the explicit
geographic impulse `[-0.08541, 0.26083] m4/s`; the total momentum ledger error
is `4.68e-13 m4/s`.

A lake at rest with zero lateral input preserves every reach state exactly at
stored precision. The junction residual is `4.00e-15` in the manufactured
combined norm and the geographic momentum ledger error is `7.57e-15 m4/s`.

Under a rigid 37-degree rotation, every scalar reach result is unchanged. The
friction-vector rotation error is zero and the lateral-vector rotation error
is `1.39e-17 m4/s`.

Across 20 matched-velocity steps, the minimum reach area is `19.9205 m2` and
the minimum junction volume is `190 m3`. Maximum stepwise errors are
`5.15e-12 m3` for mass and `1.42e-12 m4/s` for geographic momentum.

## Relation to traditional GIS operators

A traditional GIS can intersect rainfall or runoff fields with reach
supports, measure contributing length, attach roughness attributes, and
calculate reach direction. Those operations establish the spatial support and
parameters of the source terms.

Stage 16 uses those facts inside a time transition. It distinguishes extensive
water addition from momentum semantics, rotates scalar reach impulses into a
geographic vector ledger, composes sources symmetrically around a conservative
opening operator, recomputes CFL after source preparation, and refuses missing
semantics. GIS remains the geometry and attribution layer; the kernel supplies
the dimensional evolution law and invariant audit.

## Consequences and next work

Stage 16 removes the immediate Stage 15 restriction on lateral water and reach
friction without altering the junction exchange. It does not solve the more
fundamental passive-reservoir limitation.

The next increment should replace or close that passive state. The preferred
path is a small near-junction 2D finite-area patch with multiple cells and
internal face fluxes. That would let transverse momentum recirculate, leave
through another opening, or dissipate through an explicit wall/bed law rather
than accumulate indefinitely. Polygon-derived face topology should enter that
stage so the geographic structure is no longer manufactured only.

The candidate remains diagnostic-only and unadmitted. Manufactured invariants
show that the specified law is internally consistent; they do not establish
accuracy against a real confluence.

## Artifacts

- Implementation:
  `data_agent/uwm/geospatial_kernel_v2/coupled_junction_reach_sources.py`
- Tests:
  `data_agent/test_geospatial_kernel_coupled_junction_reach_sources.py`
- Gate compiler:
  `scripts/compile_geotransport_stage16_source_split_junction_gates.py`
- Gate report:
  `benchmarks/geotransport_v0_1/stage16_source_split_junction_reach_gates.json`
