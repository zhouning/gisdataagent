# ADR-066: Public observed-state geometry response

- Status: implemented as an observed-state physical-flux diagnostic; runtime
  geometry and time-advance admission remain closed
- Date: 2026-07-29
- Depends on: ADR-065

## Context

ADR-065 found that a near-gauge bridge-section candidate is stable on a
post-2023 temporal holdout but does not transfer to the distant wading support.
That establishes spatial locality, but it does not yet quantify whether choosing
the Stage 24 trapezoid instead of the Stage 23 state-conditioned rectangle makes
a material difference to dynamic-wave physics.

Stage 25 answers this while preserving the observed state. For each of the 20
approved bridge/ADCP temporal-holdout measurements, both geometry hypotheses
receive the exact same flow area `A` and discharge `Q`. This isolates geometry
from state-estimation differences.

The observations are months apart and come from one monitoring location. They
are not simultaneous states in neighboring finite-volume cells. Treating
successive observations as left and right HLL states would invent a spatial
gradient that the public evidence does not contain.

## Decision

Add `public_reach_geometry_response.py` as a Stage 25 diagnostic over the frozen
Stage 24 audit and the existing dynamic-wave primitives.

For every temporal-holdout state, compare:

```text
geometry 1: Stage 23 state-conditioned observed rectangular section
geometry 2: Stage 24 near-gauge bridge trapezoidal candidate

shared state: U = (A_observed, Q_observed)
```

The comparison evaluates:

- depth corresponding to observed area;
- top width at observed area;
- gravity-wave celerity;
- Froude number;
- hydrostatic pressure integral;
- physical mass and momentum flux;
- characteristic signal speeds; and
- identical-state HLL flux.

No observation is refit and no state is changed during this comparison.

## Physical decomposition

For a one-dimensional dynamic-wave state and section, the physical flux is:

```text
F(U; geometry) = (
  Q,
  Q^2/A + g*I1(A; geometry)
)
```

Holding `(A,Q)` fixed gives three exact consequences:

1. mass flux `Q` is geometry invariant;
2. mean velocity `Q/A` and convective momentum `Q^2/A` are geometry invariant;
3. only the hydrostatic term `g*I1` changes the physical momentum flux.

Stage 25 checks this decomposition directly rather than interpreting every flux
difference as a general model improvement.

Gravity-wave celerity remains geometry dependent:

```text
c = sqrt(g*A/T(A; geometry))
```

because the top width `T` differs between section hypotheses even when the state
area is identical.

## Identical-state HLL diagnostic

Stage 25 calls the existing HLL operator with the same observed state on both
sides of an interface, separately for each geometry:

```text
HLL(U, U; geometry) = F(U; geometry)
```

This is a numerical consistency and physical-flux diagnostic. It is not a
spatial transition or time advance. The maximum HLL mass-flux identity error is
`2.84e-14 m3/s`; the maximum HLL versus physical momentum-flux error is
`4.55e-13 m4/s2`. Both geometries retain a subcritical HLL wave regime for all
20 observed states.

## Response results

The values below are signed relative changes from the Stage 23 rectangle to the
Stage 24 bridge trapezoid at the same `(A,Q)`:

| Quantity | Minimum | Median | Maximum |
|---|---:|---:|---:|
| Depth | +15.02% | +20.42% | +26.25% |
| Top width | -9.33% | -3.39% | +4.65% |
| Gravity-wave celerity | -2.25% | +1.74% | +5.02% |
| Froude number | -4.78% | -1.71% | +2.30% |
| Hydrostatic pressure integral | +8.27% | +13.40% | +20.16% |
| Physical momentum flux | +8.14% | +13.22% | +20.09% |

The bridge candidate is deeper for every temporal-holdout state. Hydrostatic
pressure and total momentum response exceed the predeclared five-percent
materiality threshold for every state. The mass flux and convective momentum
terms remain unchanged.

The candidate-section inverse mapping from observed area back to gauge stage has
a median error of `-0.0108 m` and a maximum absolute error of `0.1712 m`. This is
consistent with the Stage 24 temporal holdout but remains an inferred model
relationship, not surveyed bed geometry.

## Meaning for the Geospatial Kernel

Traditional GIS can display both cross sections, calculate areas and widths, or
join the resulting attributes back to points. Those operations do not determine
how geometry changes a conservation-law flux.

Stage 25 adds the kernel-specific layer:

- bind alternative geometries to an identical typed physical state;
- decompose invariant mass and convective terms from geometry-dependent pressure;
- propagate top-width changes into wave speeds and flow regime;
- exercise the real HLL implementation while checking its consistency identity;
- refuse to turn temporal samples into invented spatial neighbors; and
- preserve the location and admission boundary established by Stage 24.

The section area, width, and pressure formulas could be implemented by a GIS,
hydraulics package, or the current kernel code. The defining kernel behavior is
that geographic support and geometry semantics constrain the physical operator
and its admissible claims.

## Claim boundary

Stage 25 supports:

- hydrodynamic comparison of two geometry hypotheses on 20 real observed states;
- exact fixed-state mass and convective-momentum invariance;
- geometry-dependent depth, width, pressure, celerity, Froude, and momentum flux;
- identical-state HLL consistency checks; and
- a quantitative materiality result for geometry choice.

It does not support:

- observed left/right spatial neighbor states;
- a dynamic time advance or reach rollout;
- runtime use of the Stage 24 bridge geometry;
- transfer to the distant wading section;
- transfer to the junction patch;
- confluence bathymetry; or
- operator admission.

## Evidence

All 20 Stage 25 gates pass:

- all seven frozen Stage 24 artifact hashes match;
- exactly the 20 temporal-holdout identities are compared;
- both geometry paths use the same observed state;
- all values are positive and finite;
- HLL mass and momentum identities close;
- mass and convective momentum remain geometry invariant;
- pressure and total momentum responses are material;
- celerity and Froude changes remain finite without regime changes; and
- runtime, reach-wide, confluence, and operator claims fail closed.

## Consequences and next work

Geometry is now demonstrated to be part of the physical kernel rather than only
a GIS preprocessing choice. The same observed state produces a median 13%
momentum-flux difference solely through its section contract.

Stage 26 should test controlled local transitions around these observed states.
Because public spatial-neighbor observations are absent, it should use explicitly
manufactured, symmetric area/discharge perturbations around each real state,
apply both geometry hypotheses, and check conservation, perturbation reversal,
CFL response, and geometry sensitivity. Such a tangent/Riemann diagnostic must
remain labeled synthetic around an observed anchor and cannot be reported as an
observed reach rollout.

In parallel, the public-data search should continue for simultaneous upstream and
downstream hydraulic observations or surveyed sections on this reach. Those data,
not temporal relabeling, are required to advance runtime admission.

## Artifacts

- Implementation:
  `data_agent/uwm/geospatial_kernel_v2/public_reach_geometry_response.py`
- Tests:
  `data_agent/test_geospatial_kernel_public_reach_geometry_response.py`
- Gate compiler:
  `scripts/compile_geotransport_stage25_public_geometry_response_gates.py`
- Response artifact:
  `data/geotransport_v0_1/stage25_center_hill_geometry_response/geometry_hydrodynamic_response.json`
- Gate report:
  `benchmarks/geotransport_v0_1/stage25_public_geometry_response_gates.json`
