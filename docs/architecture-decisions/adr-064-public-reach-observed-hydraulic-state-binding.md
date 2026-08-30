# ADR-064: Public reach observed hydraulic-state binding

- Status: implemented for observed downstream-reach states; fixed geometry and
  hydraulic operator admission remain closed
- Date: 2026-07-29
- Depends on: ADR-063

## Context

ADR-062 and ADR-063 established real horizontal support and roughness uncertainty
for the Center Hill confluence, but deliberately refused to manufacture
bathymetry, cross sections, water depth, or observed momentum from 3DEP terrain,
CDL land cover, and instantaneous NWIS discharge.

The USGS Water Data OGC API exposes a different public evidence class at
monitoring location `USGS-03424860`: individual field channel measurements with
flow, water-surface width, flow area, and reported mean velocity. The gauge is on
NHDPlus reach `18421703`, approximately `925.456 m` downstream of the Stage 21
junction. These observations can constrain real hydraulic states on that reach,
but their location and semantics do not complete the upstream junction patch.

## Decision

Add a bounded Stage 23 acquisition and compiler for the following public USGS
objects:

```text
channel-measurements queryables                   7,372 bytes
USGS-03424860 channel measurements              187,936 bytes
USGS-03424860 field measurements                541,077 bytes
total                                            736,385 bytes
```

All requests are site-filtered, capped at 1.5 MB in total, and restricted to
`api.waterdata.usgs.gov`. No workspace or private data is sent. The three raw
objects are retained with SHA-256 identity, source URL, role, license, size, and
retrieval metadata.

The channel collection contains 110 records from `2011-01-25` through
`2026-05-20`; the field collection contains 401 records. For each channel record,
the compiler joins a `MeanGageHeight` observation from the same `field_visit_id`.
If a visit contains more than one such observation, it selects the value nearest
in time to the channel measurement. The channel measurement UUID is the primary
identity. One valid record has no legacy `measurement_number`; it remains in the
compiled set and is identified by UUID rather than discarded.

Source customary units are normalized using exact declared conversions:

```text
ft       -> m     x 0.3048
ft2      -> m2    x 0.09290304
ft3/s    -> m3/s  x 0.028316846592
```

An unknown or changed source unit fails closed.

## Kernel state binding

Each measurement compiles to a real one-dimensional dynamic-wave state:

```text
U = (A, Q)

A = observed flow area
Q = observed channel flow
u_kernel = Q / A
```

The independent reported mean velocity is retained to check the rounded source
identity `Q approximately equals A * u_reported`. The maximum relative closure
error across all 110 observations is `0.012613`, below the declared two-percent
tolerance.

For each individual observation only, Stage 23 creates an equivalent rectangular
section:

```text
b = observed water-surface width W
side slope = 0
h_equivalent = A / W
```

This section exactly recovers the observed area and top width at that state. The
largest floating-point recovery error is `5.68e-14`. It is a state-conditioned
representation, not a survey of the bed and not a permanent reach geometry.
Width ranges from `24.0792 m` to `111.8616 m`, while area ranges from
`10.3122 m2` to `688.4115 m2`; freezing one measurement as the reach geometry
would erase observed hydraulic variation.

The equivalent depth supports local state diagnostics:

```text
Fr = (Q / A) / sqrt(g * A / W)
lambda_minus, lambda_plus = Q / A +/- sqrt(g * A / W)
```

All 110 observed equivalent states are subcritical. The maximum Froude number is
`0.620873`, and every characteristic-speed pair straddles zero. This validates
the state binding and local regime calculation under the equivalent-section
contract; it does not validate a reach-scale rollout.

## Gage-height boundary

USGS parameter `00065` is gage height relative to a station datum. It is not the
water-column depth above the channel bed. Stage 23 retains the joined gage height
and approval status as observational context but never uses it as `h` in the
dynamic-wave equations. The equivalent depth is computed only from observed
flow area and width.

There are 109 approved joined heights and one provisional height. Approval status
is preserved so later inference can stratify or exclude records without silently
changing the source population.

## Relationship to traditional GIS operators

Stage 23 does not replace GIS. It uses the same computational foundations where
the task is genuinely geospatial:

| Concern | Traditional GIS implementation | Geospatial Kernel implementation |
|---|---|---|
| OGC feature access | Read point features and attributes | Reuse the feature representation, then verify source identity and bounded provenance |
| Location and topology | Locate a gauge and spatially join it to a river reach | Retain the reach binding and its distance from the junction as part of the model claim domain |
| Units and schemas | Convert fields and validate columns | Convert fields before constructing a typed physical state; changed units fail closed |
| Cross-section handling | Store or derive geometry and calculate areas | Bind geometry to one observed state and explicitly refuse reuse as permanent geometry |
| Temporal records | Join or summarize rows by timestamp and key | Compile each row as a time-indexed state and preserve the field-visit join rule |
| Hydraulic reasoning | Usually delegated to a separate model or plugin | Check `Q=A*u`, Froude regime, characteristic speeds, and state admissibility in the kernel contract |
| Missing evidence | Often represented as null attributes or filled during preprocessing | Expose a typed refusal that blocks unsupported fixed geometry and confluence bathymetry |

For coordinate transforms, intersections, network matching, raster sampling, and
geometry validity, a kernel operator may use the same GEOS, PROJ, GDAL, or native
GIS algorithms as desktop and server GIS. Reimplementing those algorithms is not
the kernel's purpose. The difference is the surrounding contract:

1. inputs have physical roles, units, temporal support, and provenance;
2. spatial support is bound to the exact state or transition it conditions;
3. outputs must satisfy physical identities, invariants, covariance, or declared
   approximation tolerances;
4. uncertainty and missing evidence propagate instead of disappearing during
   preprocessing; and
5. an operator is admitted only for a stated location, scale, regime, and task.

Thus some Geospatial Kernel operators share their numerical core with GIS
operators, while others, such as conservative fluxes and characteristic-wave
calculations, are physical transition operators not normally provided by GIS.
The kernel is defined by composition of spatial support, typed state, physical
law, temporal transition, uncertainty, and executable claim boundaries, not by
inventing a second geometry engine.

## Claim boundary

Stage 23 supports:

- 110 public, source-identified downstream-reach hydraulic observations;
- SI-normalized flow, area, width, reported velocity, and gage-height context;
- one typed `DynamicWaveCellState(A, Q)` per observation;
- one state-conditioned equivalent rectangular section per observation;
- source-rounded `Q=A*u` closure checks;
- local Froude and characteristic-speed diagnostics; and
- executable refusal of fixed geometry and junction bathymetry claims.

It does not support:

- a surveyed or time-invariant reach cross section;
- bed elevation or depth derived from gage height;
- transfer of gauge geometry 925 m upstream to the confluence patch;
- a two-dimensional observed momentum field;
- calibrated roughness or bathymetry uncertainty;
- a validated downstream-reach or junction rollout; or
- operator admission.

The Stage 21 bathymetry refusal and Stage 22 roughness-calibration boundary remain
in force.

## Evidence

All 18 Stage 23 gates pass. In particular:

- all seven frozen Stage 22 artifact hashes match;
- all three public USGS raw-object hashes match;
- all 110 UUID-identified observations compile and join gage-height context;
- every dynamic-wave state is positive and finite;
- all source flow identities close within two percent;
- all equivalent sections recover observed area and width;
- all observations are subcritical and their wave speeds straddle zero;
- ADCP and point-velocity methods plus bridge, wading, and boat field methods are
  retained; and
- fixed geometry, junction bathymetry, and operator admission remain closed.

## Consequences and next work

The kernel now has real hydraulic state evidence, not only horizontal geometry
and land-cover priors. This is a meaningful advance, but it does not turn the
Center Hill fixture into a validated hydraulic world model.

The next bounded increment should test whether repeated observations support a
stable reach-geometry candidate rather than assuming one. A Stage 24 candidate
can stratify by channel, method, approval status, and time; estimate monotone
area-stage and width-stage relationships; and test the geometric identity
`dA/dH approximately equals W` where the station datum is consistent. Temporal
holdout and method holdout are required. A failed stability or derivative test
must preserve the state-conditioned Stage 23 representation rather than forcing
a fixed cross section.

Separately, junction-patch bathymetry still requires spatially local surveyed,
lidar-waterline, sonar, bridge-section, or equivalent evidence. The downstream
rating evidence cannot satisfy that requirement.

## Artifacts

- Acquisition:
  `scripts/acquire_geotransport_stage23_usgs_channel_measurements.py`
- State compiler:
  `data_agent/uwm/geospatial_kernel_v2/public_reach_hydraulic_measurements.py`
- Tests:
  `data_agent/test_acquire_geotransport_stage23_usgs_channel_measurements.py`
  and
  `data_agent/test_geospatial_kernel_public_reach_hydraulic_measurements.py`
- Gate compiler:
  `scripts/compile_geotransport_stage23_public_reach_hydraulic_gates.py`
- Acquisition manifest and compiled measurements:
  `data/geotransport_v0_1/stage23_usgs_channel_measurements_03424860/`
- Gate report:
  `benchmarks/geotransport_v0_1/stage23_public_reach_hydraulic_gates.json`
