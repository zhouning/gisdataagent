# ADR-059: Synchronous patch-reach coupling with transition reaction

- Status: implemented as a native candidate; source splitting and public
  validation pending
- Date: 2026-07-28
- Depends on: ADR-058

## Context

ADR-058 replaced a spatially uniform junction cell with a conforming
multi-cell shallow-water patch. It gave transverse momentum somewhere physical
to propagate inside the confluence, but did not update the attached 1D reaches.
ADR-056 had already coupled a single 2D cell to those reaches by storing every
opening's unrepresentable transverse impulse in a passive terminal reservoir.
That reservoir made the dimensional mismatch visible, but had no transport or
release law and could grow without bound.

Stage 18 must update the 2D patch and all 1D branch terminal cells with the same
opening flux. It must also close the transverse component without silently
deleting it or restoring the passive reservoir.

## Decision

Implement the synchronous operator in
`coupled_junction_patch_reach.py`. Preserve all five Stage 17 artifacts by
hash. Do not modify or reinterpret the frozen Stage 15 reservoir operator.

The coupled state consists only of:

```text
2D patch cell: [V, M_east, M_north]
1D reach cell: [A, Q_longitudinal]
```

There is no terminal transverse-momentum state in the Stage 18 transition.

## One shared opening flux

The 2D patch evaluates one rotated HLL flux at each branch opening:

```text
F_open = [F_V, F_east, F_north]
```

The same mass flux is applied with opposite signs to the patch cell and branch
terminal cell. Upstream openings override the right boundary of their reaches;
the downstream opening overrides the left boundary of its reach. The opening
flux is not independently recomputed by the 1D solver.

For the unit geographic branch tangent `t`, split vector momentum flux into:

```text
F_parallel = (F_momentum dot t) t
F_perp     = F_momentum - F_parallel
```

The patch receives the full vector impulse and the reach receives the
longitudinal component:

```text
delta_P_patch = -dt F_momentum
delta_P_reach =  dt F_parallel
```

## Transition-wall closure

A 1D channel state has no transverse degree of freedom. Stage 18 interprets
that dimensional constraint as an unresolved transition wall exerting the
instantaneous impulse

```text
I_transition_on_fluid = -dt F_perp
```

Therefore:

```text
delta_P_patch + delta_P_reach = I_transition_on_fluid
```

The reported structural reaction is exactly the opposite:

```text
I_structure = -I_transition_on_fluid
```

This is the reaction force associated with projecting a 2D state space onto a
1D channel state space. It is analogous to a constraint reaction or Lagrange
multiplier: it is an external impulse on the represented fluid, not conserved
fluid momentum hidden in an untransported state. It is calculated and audited
at every opening and every step, but is not accumulated.

This is a deliberate closure hypothesis. Stage 18 does not claim that the
transition reaction predicts a measured wall load, nor does the reaction feed
back into the HLL flux. A resolved 2D channel extension would be a stronger
future representation when mesh and bathymetry support it.

## Whole-system ledgers

The total volume is the sum of every patch-cell volume and every reach-cell
volume. Internal patch faces and patch/reach openings cancel. Only upstream
external inflow and downstream external outflow remain in the global volume
ledger.

The geographic momentum is the sum of all 2D cell vectors and all 1D discharge
integrals rotated by their branch tangents. Its external impulse ledger contains:

- external reach-boundary momentum flux;
- hydrostatic pressure on explicit patch solid walls; and
- the 2D-to-1D transition-wall impulse.

No passive reservoir is included in either the state or the ledger.

## Stability contract

One step uses the minimum of:

- the Stage 17 cellwise patch spectral and drain bounds;
- the standard 1D reach HLL bounds; and
- an opening-specific reach bound using the adjacent patch-cell normal speed,
  boundary-state speed, and gravity-wave celerity.

Nonpositive patch volumes, negative reach areas, mismatched branch identities,
misoriented openings, nonrectangular widths, nonflat beds, nonzero lateral
inflow, unsupported external beds, and excessive timesteps fail closed.

## Manufactured evidence

The Stage 18 compiler freezes the five Stage 17 artifacts and evaluates 21
gates. All pass.

For the asymmetric four-cell baseline (`dt = 0.1081466 s`):

- whole-system mass error is `0 m3`;
- geographic vector-momentum error is `3.44e-13 m4/s`;
- maximum per-opening vector closure error is `2.78e-17 m4/s`;
- net transition-wall impulse on the fluid is approximately
  `[-0.17315, -0.09006] m4/s`; and
- both the patch and all attached reaches update in the same step.

A uniform lake at rest preserves every patch and reach state exactly at stored
precision. Its global ledgers close exactly; the largest computed transverse
flux is `1.20e-14 m4/s2`, consistent with roundoff.

A rigid 37-degree rotation preserves all scalar reach states exactly. Maximum
patch-cell momentum rotation error is `5.62e-15 m4/s`, and maximum transition
impulse rotation error is `6.41e-15 m4/s`.

Across 25 synchronous steps:

- minimum patch-cell volume remains `190 m3`;
- minimum reach area is `19.8527 m2`;
- maximum mass-ledger error is `5.41e-12 m3`;
- maximum momentum-ledger error is `1.68e-12 m4/s`;
- transverse opening flux is active; and
- no persistent transverse terminal state appears.

## Relation to traditional GIS operators

Traditional GIS software can build or validate the inputs to this operator:
river centerlines define branch tangents, polygon boundaries define opening
normals and lengths, topology identifies adjacent cells, and terrain or surveyed
cross sections supply widths and bed elevations. Buffer, intersect, snap,
polygonize, spatial join, raster sampling, and network tracing remain data
preparation operations. They normally return a new dataset and have no evolving
conserved state.

The Stage 18 kernel consumes those geographic measures inside a state-transition
law. The branch tangent is a momentum projector; the opening normal defines the
Riemann problem; polygon area converts stored volume to depth; adjacency routes
internal waves; and the mismatch between the 2D vector space and 1D tangent
space produces a typed reaction impulse. Rotation covariance and whole-system
ledgers are part of the operator contract. This is the relevant difference from
calling conventional GIS tools from an agent.

## Data basis and claim boundary

Stage 18 is supported by manufactured invariant tests, not empirical
calibration. The user is not required to provide private data, but that does not
waive the need for public-data validation. Public hydrography and elevation can
eventually provide geometry; public gauges can provide boundary hydrographs.
The unresolved difficulty is obtaining coincident, machine-readable confluence
geometry plus sufficiently complete hydraulic state observations for vector
validation.

Stage 18 supports:

- a connected conforming multi-cell patch;
- synchronous updates of two or more upstream reaches and one downstream reach;
- wet, flat-bed, rectangular openings and reaches;
- one shared opening mass and vector-momentum flux;
- explicit instantaneous transition-wall reaction; and
- global volume and two-component geographic momentum ledgers.

It does not support:

- friction or lateral-inflow source splitting inside the new coupled operator;
- feedback from transition reaction to the opening flux;
- a resolved 2D extension along each attached channel;
- variable bed elevation, irregular opening sections, or wetting and drying;
- turbulence, sediment, wall drag, or structure-load prediction; or
- completed public empirical validation.

The candidate remains diagnostic-only and unadmitted.

## Consequences and next work

Stage 18 completes the first synchronous network transition for the multi-cell
kernel and removes the passive transverse accumulator from that path. The model
now distinguishes momentum transported inside the 2D confluence from momentum
removed by the explicit dimensional constraint at a 1D interface.

Stage 19 should integrate the Stage 16 Strang-split Manning friction and lateral
inflow sources around this Stage 18 conservative core. In parallel, a public
data assembly path should derive a reproducible patch/reach geometry contract
from open hydrography and elevation, while treating gauge-only validation as a
partial mass-and-stage test rather than evidence for unobserved vector momentum.

## Artifacts

- Implementation:
  `data_agent/uwm/geospatial_kernel_v2/coupled_junction_patch_reach.py`
- Tests:
  `data_agent/test_geospatial_kernel_coupled_junction_patch_reach.py`
- Gate compiler:
  `scripts/compile_geotransport_stage18_coupled_patch_reach_gates.py`
- Gate report:
  `benchmarks/geotransport_v0_1/stage18_coupled_junction_patch_reach_gates.json`
