# ADR-067: Observed-anchor local perturbation transition

- Status: implemented as a controlled local transition diagnostic; real-reach
  grid and runtime operator admission remain closed
- Date: 2026-07-29
- Depends on: ADR-066

## Context

ADR-066 showed that two location-conditioned geometry hypotheses produce
materially different hydrostatic pressure and momentum flux at the same observed
state. Its identical-state HLL calls were intentionally static consistency tests;
they did not advance a nonuniform state.

Stage 26 asks whether the geometry difference survives an actual finite-volume
update while retaining conservation, stability, and symmetry. Public observations
provide 20 real anchor states, but they do not provide simultaneous neighboring
cell states or both reach boundaries. Any local spatial variation must therefore
be declared as manufactured.

The public centerline for NHDPlus `18421703` is approximately `1147 m` in the
Stage 21 fixture. Stage 24 rejected reach-wide geometry transfer, so Stage 26
does not divide that line into apparently real hydraulic cells. It uses a
separate numerical scale whose only purpose is operator diagnosis.

## Decision

Add `public_reach_local_perturbation.py` as a Stage 26 wrapper around the frozen
Stage 25 geometry response and existing periodic HLL update.

For each of the 20 temporal-holdout observations, define a four-cell state around
the observed anchor `(A,Q)`:

```text
area multipliers       [1.05, 1.00, 0.95, 1.00]
discharge multipliers  [1.00, 1.05, 1.00, 0.95]
```

Area and discharge perturbations are phase shifted so both conserved variables
have nonuniform interface fluxes. Their arithmetic means remain exactly at the
observed anchor. The perturbation magnitude is fixed at five percent; no
anchor-specific tuning is performed.

The numerical contract is:

```text
cell count                    4
periodic numerical ring       true
numerical cell length         100 m
target Courant number         0.4
time step                     min(stable rectangle, stable trapezoid)
```

The `100 m` length is not a discretization of the public reach, and the periodic
ring is not river topology. Both geometry hypotheses receive the same input and
the same shared time step.

## Perturbation reversal

Changing both perturbation signs is equivalent to rotating the four-cell pattern
by two cells:

```text
[+area, 0, -area, 0] -> [-area, 0, +area, 0]
[0, +flow, 0, -flow] -> [0, -flow, 0, +flow]
```

For a homogeneous periodic operator, the advanced reversed state must equal the
advanced original state rotated by two cells. Stage 26 calculates this separately
for the rectangle and trapezoid. Both area and discharge covariance errors are
exactly zero across all 40 geometry-anchor paths.

## Stability and conservation

The shared stable time step ranges from `5.0400 s` to `8.5782 s`, with a median
of `7.2617 s`. The maximum realized Courant number is
`0.4000000000000001`, within floating-point tolerance of the declared limit.

The Stage 24 trapezoid is the limiting geometry for 15 anchors; the Stage 23
rectangle is limiting for five. The candidate stable time step ranges from
`4.11%` smaller to `2.73%` larger than the rectangle value. Geometry therefore
changes the CFL constraint, but neither hypothesis is universally more
restrictive.

All one-step outputs remain finite and strictly wet. The minimum updated area is
`115.2334 m2`. Across all 40 forward paths:

```text
maximum absolute periodic volume error       2.91e-11 m3
maximum absolute discharge-integral error    1.46e-11 m4/s
maximum reversal area covariance error       0
maximum reversal discharge covariance error  0
```

## Geometry response after one step

Both geometry paths begin from the same nonuniform state and use the same time
step. Relative differences between their updated states are:

| Quantity | Minimum | Median | Maximum |
|---|---:|---:|---:|
| Area L2 response | 0.0063% | 0.0229% | 0.0613% |
| Discharge L2 response | 0.0125% | 0.5538% | 3.2775% |
| Maximum cell area response | 0.0072% | 0.0371% | 0.0907% |
| Maximum cell discharge response | 0.0209% | 0.7880% | 4.6402% |

The updated discharge response exceeds the declared one-percent materiality
threshold for at least one observed anchor. The smaller area response is still
strictly nonzero. This connects the Stage 25 hydrostatic flux difference to an
actual conservative state transition.

## Meaning for the Geospatial Kernel

Traditional GIS can generate a four-cell layer, attach perturbed attributes, and
compare output maps. It does not normally impose the finite-volume state law or
test the following as one contract:

- both geometry alternatives receive the identical conserved state;
- time step selection respects both geometry-dependent wave-speed limits;
- periodic mass and momentum ledgers close;
- sign-reversed perturbations transform covariantly;
- all updated areas remain physically admissible; and
- synthetic spatial structure cannot be relabeled as observation.

This is the Geospatial Kernel role: geographic geometry and support constrain a
physical transition operator, while conservation, covariance, numerical domain,
and evidence status remain executable properties.

## Claim boundary

Stage 26 supports:

- 20 observed hydraulic states used as local anchors;
- deterministic symmetric area and discharge perturbations;
- one real HLL finite-volume update under both geometry hypotheses;
- shared CFL-safe time stepping;
- periodic mass and momentum conservation;
- exact perturbation-reversal covariance; and
- measured geometry sensitivity of the updated state.

It does not support:

- observed perturbed states;
- observed neighboring spatial states;
- a real four-cell reach discretization;
- real upstream or downstream boundary conditions;
- a reach forecast or observed rollout;
- confluence geometry; or
- runtime operator admission.

## Evidence

All 20 Stage 26 gates pass:

- all seven Stage 25 artifacts are hash frozen;
- all 20 observed anchor identities are retained;
- perturbation patterns and evidence labels are exact;
- every shared time step is stable for both geometries;
- all forward states are finite, nonnegative, and conservative;
- perturbation reversal is exactly translation covariant;
- geometry affects area, discharge, and stability response; and
- observed-rollout, real-grid, and runtime claims fail closed.

## Consequences and next work

The kernel now has a data-anchored but honestly synthetic local transition test.
It demonstrates that the location-conditioned geometry choice affects not only
static pressure but a conservative HLL update.

Stage 27 should return to public-data acquisition. A bounded NLDI and USGS search
should identify gauges or field measurements upstream and downstream of
`18421703`, determine whether simultaneous discharge/stage windows exist, and
compile a spatial-boundary evidence ledger. If no second spatial observation is
available, the result must be a documented boundary-data refusal rather than a
temporal record being substituted for a spatial neighbor.

## Artifacts

- Implementation:
  `data_agent/uwm/geospatial_kernel_v2/public_reach_local_perturbation.py`
- Tests:
  `data_agent/test_geospatial_kernel_public_reach_local_perturbation.py`
- Gate compiler:
  `scripts/compile_geotransport_stage26_public_local_perturbation_gates.py`
- Perturbation artifact:
  `data/geotransport_v0_1/stage26_center_hill_local_perturbation/observed_anchor_local_perturbation.json`
- Gate report:
  `benchmarks/geotransport_v0_1/stage26_public_local_perturbation_gates.json`
