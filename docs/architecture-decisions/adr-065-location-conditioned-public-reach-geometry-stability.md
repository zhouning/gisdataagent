# ADR-065: Location-conditioned public reach geometry stability

- Status: implemented as a location-conditioned diagnostic candidate; reach-wide
  and runtime geometry admission remain closed
- Date: 2026-07-29
- Depends on: ADR-064

## Context

ADR-064 compiled 110 real USGS field measurements at `USGS-03424860` into
state-conditioned hydraulic observations. It did not assume that one observed
width and area described a permanent cross section. Stage 24 asks the next
stronger question: do repeated measurements support a stable geometry law that
can replace the per-observation equivalent rectangles?

The answer must account for spatial support. Bridge-downstream measurements are
generally within 30 meters of the gauge, while wading measurements are generally
91 to 244 meters downstream. Treating both sets as interchangeable would test a
reach-wide homogeneous-section assumption rather than stability at one section.

The source also contains two records measured at the same instant and field
visit for the right one-third and left two-thirds channel. Those are component
areas and widths, not two complete cross sections. One recent bridge observation
has provisional rather than approved gage height. Both evidence types must be
retained in the ledger but excluded from geometry fitting.

## Decision

Add `public_reach_geometry_stability.py` as a deterministic Stage 24 audit over
the frozen Stage 23 observations. No network request or new private data is
required.

The 110 observations are partitioned exactly once:

```text
development bridge/ADCP, before 2023                 55
temporal bridge/ADCP holdout, 2023 onward             20
method/spatial wading/point-velocity holdout           25
provisional primary-location observation                1
simultaneous component-channel observations             2
other retained observations                              7
total                                                   110
```

The primary cohort requires:

- `BridgeDownstreamSide` field method;
- ADCP channel measurement;
- downstream direction;
- reported distance no greater than `30 m`;
- approved gage height; and
- no simultaneous component-channel identity.

The cutoff `2023-01-01T00:00:00Z` is fixed before fitting. The 20 temporal
holdout observations have no measurement-identity overlap with development.

The method/spatial holdout requires wading, point velocity, downstream direction,
approved height, and distance greater than `30 m`. Only 17 of its 25 observations
fall inside the development gage-height range and are scored. The other eight are
retained as outside-support evidence. This prevents spatial-transfer failure
from being attributed to stage extrapolation.

## Geometry law

Stage 24 fits one gage-datum-referenced trapezoidal candidate. Let
`x = H - H_ref`, where `H` is gage height and is still not interpreted as water
depth. The joint model is:

```text
A(H) = A_ref + W_ref*x + z*x^2
W(H) = W_ref + 2*z*x
dA/dH = W(H)
```

This is the exact area and top-width law of a trapezoidal section. Area residuals
are scaled by `100 m2`, width residuals by `50 m`, and ordinary least squares is
used without robust or post-hoc outlier removal. The fitted parameters are:

```text
reference gage height                 4.041648 m
area at reference                   255.803892 m2
top width at reference               71.288499 m
side slope                            2.950214 horizontal/vertical
inferred zero-area gage height       -0.341837 m
inferred bottom width                45.424056 m
development gage-height support       1.938528 to 8.936736 m
```

The positive physical root converts the polynomial into the kernel's existing
`TrapezoidalChannelSection`. For a stage `H`, candidate depth is
`H - H_zero`; stages below `H_zero` fail closed. The section then reproduces the
joint polynomial area and width, and `dA/dH = W` holds to floating-point
precision.

`H_zero` is an inferred model offset relative to the gauge datum. It is not a
surveyed bed elevation. The model never relabels raw gage height as water depth.

## Independent derivative test

The structural identity in the joint candidate is enforced by construction, so
it cannot by itself validate the geometry. Stage 24 separately fits an area-only
quadratic using the 55 development areas and no width observations:

```text
A_area_only(H) = 253.903855 + 70.165537*x + 3.739477*x^2
```

Its derivative is compared with observed width in all scored cohorts. This
provides an empirical `dA/dH approximately equals W` test that is independent of
the width part of the joint fit.

## Holdout results

The predeclared accuracy gates require median absolute percentage error no
greater than 10% and 90th-percentile absolute percentage error no greater than
15% for joint-model area, joint-model width, and the independent area derivative
against width.

| Cohort | Area median / p90 | Width median / p90 | Independent derivative median / p90 | Decision |
|---|---:|---:|---:|---|
| Development, 55 | 3.07% / 6.16% | 3.53% / 7.89% | 6.41% / 12.35% | pass |
| Temporal holdout, 20 | 1.70% / 3.20% | 4.04% / 6.03% | 8.35% / 12.95% | pass |
| Method/spatial holdout, 17 in support | 234.58% / 572.76% | 15.91% / 57.27% | 21.25% / 45.47% | fail |

The temporal result supports stability of a bridge-location diagnostic candidate
through March 2026. It does not support transfer to the distant wading section.
The transfer rejection is material in area, width, and the independent derivative
test, even after limiting evaluation to the development stage range.

## Meaning for the Geospatial Kernel

This result is not a failure of the Geospatial World Model premise. It identifies
one of the geographic laws the kernel must enforce: a physical relationship can
be stable in time while remaining local in space. A reach identifier is not, by
itself, sufficient support for a homogeneous cross section.

Traditional GIS can perform the attribute filtering, distance grouping, temporal
selection, and regression-table output. Stage 24 adds kernel responsibilities:

- bind the learned curve to the geometric identity `dA/dH=W`;
- construct an actual physical section type with a positive domain;
- separate temporal generalization from spatial/method transfer;
- retain every excluded record in an exhaustive evidence partition;
- prevent inferred datum offsets from becoming surveyed bed claims; and
- make failed transfer an executable refusal of reach-wide geometry.

The underlying regression could be implemented in a GIS statistics tool and the
same result reused. What makes it a kernel operator is the composition of spatial
support, physical geometry, state semantics, holdout protocol, and claim
admission. The kernel does not need a proprietary replacement for GIS algebra;
it needs laws and boundaries that ordinary geoprocessing does not enforce.

## Claim boundary

Stage 24 supports:

- an exhaustive, disjoint evidence partition;
- a physical trapezoidal stage-geometry candidate for the near-gauge bridge
  cohort;
- an independent area-derivative width audit;
- successful post-2023 temporal holdout at the bridge-location support;
- empirical rejection of transfer to the distant wading support; and
- typed refusal of reach-wide, runtime, and confluence geometry claims.

It does not support:

- a surveyed bridge or river cross section;
- interpretation of inferred zero-area stage as bed elevation;
- a homogeneous geometry for all of NHDPlus reach `18421703`;
- transfer of this section to the junction 925 meters upstream;
- runtime dynamic-wave geometry admission;
- confluence bathymetry; or
- operator admission.

## Evidence

All 20 Stage 24 gates pass, including gates whose correct result is rejection of
an unsupported claim:

- all ten frozen Stage 23 hashes match;
- all 110 observations are partitioned once without leakage;
- component channels and provisional height are retained but excluded from fit;
- the candidate has positive trapezoidal parameters and physical stage domain;
- development and temporal accuracy gates pass;
- method/spatial transfer fails materially inside common stage support; and
- reach-wide geometry, runtime geometry, confluence bathymetry, and operator
  admission fail closed.

## Consequences and next work

Stage 24 replaces an undifferentiated fixed-section question with a spatially
conditioned result. The bridge candidate is useful for diagnostics, but the
kernel must not attach it indiscriminately to every state on the reach.

Stage 25 should propagate this geometry distinction through existing dynamic-wave
diagnostics without opening runtime admission. For each Stage 23 temporal-holdout
state, compare the state-conditioned rectangular section with the Stage 24
bridge candidate for depth, top width, gravity-wave celerity, hydrostatic pressure
and HLL flux. This will quantify how much the geometry contract changes physical
transition terms. A geometry ensemble should remain location-conditioned, and
the distant wading support should be a negative transfer control rather than an
alternative truth for the bridge location.

Junction bathymetry remains a separate public-data search and cannot be inferred
from either geometry family.

## Artifacts

- Implementation:
  `data_agent/uwm/geospatial_kernel_v2/public_reach_geometry_stability.py`
- Tests:
  `data_agent/test_geospatial_kernel_public_reach_geometry_stability.py`
- Gate compiler:
  `scripts/compile_geotransport_stage24_public_reach_geometry_gates.py`
- Geometry audit:
  `data/geotransport_v0_1/stage24_center_hill_reach_geometry_stability/reach_geometry_stability_audit.json`
- Gate report:
  `benchmarks/geotransport_v0_1/stage24_public_reach_geometry_stability_gates.json`
