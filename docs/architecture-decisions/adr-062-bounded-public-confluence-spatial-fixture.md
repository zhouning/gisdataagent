# ADR-062: Bounded public-confluence spatial fixture

- Status: implemented as a public spatial fixture; runtime hydraulic admission
  remains closed
- Date: 2026-07-29
- Depends on: ADR-061

## Context

ADR-061 completed a spatially bound two-dimensional Manning-friction law, but
its four cells, geometry, state, and roughness values were manufactured. Adding
more manufactured source laws would not answer whether the kernel can bind its
geographic contracts to real, reproducible evidence when the project owner has
no additional private data to provide.

The next increment therefore needs to use data that the project can acquire
itself. It must distinguish three different claims:

1. a real public spatial fixture has been compiled;
2. the fixture contains enough hydraulic geometry to execute a physical
   rollout; and
3. public observations validate two-dimensional momentum at a confluence.

Only the first claim is supportable with the current evidence.

## Decision

Compile a real Center Hill confluence at NHDPlus feature `18421703` and connect
it to the existing `USGS 03424860` evidence chain. The topology is:

```text
18421705 ---\
              >--- 18421703 ---> USGS 03424860
18421707 ---/
```

The common NLDI endpoint is `(-85.909170702, 36.178724498)`. A two-kilometer
upstream NLDI request is the smallest tested navigation window that returns all
three target flowlines. It avoids reusing the much larger 30-kilometer topology
response as the only source artifact.

Stage 21 adds:

- `public_confluence_fixture.py`, which compiles and validates the typed
  fixture;
- a bounded acquisition script with host allowlists, object-size limits,
  retries, source identity checks, hashes, and an explicit no-workspace-upload
  contract;
- a six-cell finite-area horizontal support compatible with the Stage 17
  geometry type;
- a per-cell uncalibrated roughness-prior field compatible with the Stage 20
  type;
- tests and a 19-gate report; and
- raw and derived public artifacts under
  `data/geotransport_v0_1/stage21_center_hill_public_confluence`.

All five Stage 20 artifacts are frozen by hash.

## Public inputs

The acquisition downloaded `87,468` bytes across six public artifacts:

- USGS NLDI/NHDPlus flowlines in a two-kilometer navigation window;
- expanded NWIS metadata for `03424860`;
- a USGS 3DEP service metadata snapshot;
- a `64 x 64` 3DEP elevation export over the local fixture window;
- the USDA NASS CropScape CDL 2024 bounded-clip response; and
- the resulting `5 x 5`, 30-meter CDL GeoTIFF.

GDAL derives WGS84 point samples from both rasters. The manifest retains every
source URL, response URL, retrieval time, byte count, SHA256 identity, license
or source statement, and transformation tool identity. It also hash-verifies
the already public 53-value NWIS discharge response used elsewhere in the
Center Hill benchmark. That artifact is reused locally and is not sent back to
any service.

USGS artifacts are treated as public-domain government data. CDL is identified
as USDA NASS public data. No user, workspace, or private value is part of a
request.

## Horizontal support construction

The NLDI centerlines provide 30-meter direction supports. The resulting flow
azimuths are:

- `18421705`: `43.4229 degrees` into the junction;
- `18421707`: `320.6896 degrees` into the junction; and
- `18421703`: `354.6974 degrees` out of the junction.

The adapter reverses upstream flow directions to obtain outward patch-opening
normals. Three half-planes with a 15-meter apothem define a triangle. Its
corners are trimmed by `0.22`, leaving three centerline-normal opening edges and
three solid-wall edges. A fan from the junction creates six conforming
triangular cells.

The compiled support has:

- total plan area `1223.0165 m2`;
- maximum vertex radius `38.4043 m`;
- three branch openings and three wall faces;
- six internal radial faces; and
- zero opening-normal alignment error at stored precision.

This polygon is a deterministic computational support. It is not a mapped bank
polygon, a surveyed channel footprint, or evidence of actual opening width.
The geometry uses a local zero vertical placeholder solely to exercise the
horizontal Stage 17 type. That zero is neither 3DEP terrain nor channel-bed
elevation.

## Terrain and roughness semantics

Every patch cell contains native 3DEP samples. Cell terrain values span
`143.5154 m` to `143.5848 m`. They describe public bare-earth surface context,
not bathymetry. The adapter must not subtract these values from a water surface
to infer depth.

The 30-meter CDL raster identifies open water (`111`) and deciduous forest
(`141`) over the six-cell support. Five cells require an explicitly recorded
nearest-valid-pixel fallback because their small polygons contain no CDL pixel
center; one cell contains a pixel center. Stage 21 maps the classes to broad
engineering priors:

```text
111 open water:        n = 0.030, interval [0.025, 0.040]
141 deciduous forest:  n = 0.100, interval [0.070, 0.160]
```

The scalar value and interval are modeling priors, not measurements supplied by
CDL and not calibration results. Unknown positive CDL classes fail closed until
an explicit mapping is added. Each assigned prior is bound to the exact kernel
cell area and records its raster and mapping provenance.

## Gauge role

`USGS 03424860` is approximately `925.46 m` downstream. The frozen public
response contains 53 scalar discharge observations for parameter `00060`.
Those values can support boundary or outcome discharge and transport-timing
checks. They do not observe an east/north velocity vector, two-component
momentum, or the transition-wall reaction inside the confluence.

The gauge is therefore present in the fixture but cannot satisfy the missing
public vector-momentum validation gate.

## Fail-closed runtime boundary

The fixture deliberately exposes two successful type bindings:

- Stage 17 horizontal geometry contract compiles; and
- Stage 20 spatial roughness-prior contract compiles.

It refuses `require_runtime_hydraulic_geometry()` with
`public_confluence_bathymetry_and_cross_sections_missing`. A physical Stage 20
rollout remains inadmissible until at least the following are resolved:

- channel bathymetry or defensible cross sections;
- actual 1D/2D transition widths and vertical datum;
- roughness calibration or uncertainty propagation appropriate to the task;
  and
- observations capable of testing the claimed two-dimensional state, if that
  validation claim is pursued.

This refusal is not a failure of the geospatial kernel mission. It is the
kernel enforcing the difference between geographic context and hydraulic state.

## Relation to traditional GIS operators

Traditional GIS can download the rasters, reproject them, clip them, intersect
cell polygons, summarize classes, and calculate areas. Stage 21 uses those
operations as evidence preparation.

The kernel-specific work begins where the results become typed model
constraints:

- river-centerline direction becomes an opening-normal contract;
- a topology identity becomes a single-outlet transition contract;
- land-cover samples become uncertain, provenance-bound parameter priors;
- terrain is assigned an allowed semantic role and barred from an unsupported
  bathymetric role;
- gauge discharge is assigned scalar boundary/outcome roles and barred from a
  vector-momentum role; and
- missing hydraulic geometry causes a typed runtime refusal rather than an
  implicit default.

GIS answers where source evidence lies and how it overlaps. The geospatial
kernel additionally decides which state transition that evidence may constrain,
which invariants must hold, and which claims remain forbidden.

## Evidence

All 19 Stage 21 gates pass. In particular:

- the Stage 20 hashes remain frozen;
- all nine downloaded, derived, or reused artifacts match their manifests;
- the three real flowline terminals snap to one junction;
- the six-cell patch is conforming and branch-normal aligned;
- every cell has terrain and mapped land-cover support;
- every roughness value has exact cell-area and source provenance;
- the NWIS observation remains scalar;
- missing hydraulic geometry fails closed; and
- calibration, public vector validation, and operator admission remain false.

## Consequences and next work

The project now has its first real public-data confluence fixture connected to
the native finite-area and roughness types. It is no longer correct to describe
the current kernel as entirely supported by manufactured geography.

The next stage should address uncertainty rather than silently turning these
priors into truth. A useful Stage 22 increment is a roughness-prior ensemble and
spatial-resolution sensitivity contract that propagates CDL class uncertainty
and nearest-pixel fallback through the friction operator while preserving the
existing mass, momentum, rotation, and dissipation gates. Runtime hydraulic
admission should remain separate until open bathymetry or cross-section evidence
is found.

## Artifacts

- Acquisition:
  `scripts/acquire_geotransport_stage21_public_confluence_fixture.py`
- Compiler:
  `data_agent/uwm/geospatial_kernel_v2/public_confluence_fixture.py`
- Tests:
  `data_agent/test_acquire_geotransport_stage21_public_confluence_fixture.py`
  and `data_agent/test_geospatial_kernel_public_confluence_fixture.py`
- Gate compiler:
  `scripts/compile_geotransport_stage21_public_confluence_fixture_gates.py`
- Gate report:
  `benchmarks/geotransport_v0_1/stage21_public_confluence_fixture_gates.json`
- Fixture:
  `data/geotransport_v0_1/stage21_center_hill_public_confluence/public_confluence_fixture.json`

