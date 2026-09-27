# Abu Dhabi GIS preprocessing image

This image is the source-data compilation layer between customer GIS delivery
and the hydrodynamics runtime. It accepts a FileGDB directory or a ZIP archive,
validates the archive boundary, records a layer inventory and compiles the
stormwater network into private GeoParquet/Parquet artifacts and auditable
manifests.

It is deliberately separate from the SWMM/ANUGA image. The source compiler
does not claim that a pipe GDB contains terrain, rainfall, tide boundaries,
pump control curves or land-use/catchment parameters. Those are separate
source contracts handled by the same image through independent adapters. Every
adapter writes a private normalized artifact plus a hash-bound manifest; a
missing unit, datum, geometry or control field leaves the result diagnostic-only
instead of guessing.

## Build

```bash
docker build \
  -f deploy/abu-dhabi-gis-preprocess/Dockerfile \
  -t abu-dhabi-gis-preprocess:v1 .
```

The Dockerfile is multi-architecture compatible. Build one native image per
target (`linux/arm64` and `linux/amd64`) or publish a manifest list with
`docker buildx build --platform linux/arm64,linux/amd64`.

The included helper builds both local architecture tags:

```bash
deploy/abu-dhabi-gis-preprocess/build-multiarch.sh local \
  abu-dhabi-gis-preprocess:v1
```

This produces `abu-dhabi-gis-preprocess:v1-arm64` and
`abu-dhabi-gis-preprocess:v1-amd64`. To publish one multi-architecture tag to
an authenticated registry:

```bash
deploy/abu-dhabi-gis-preprocess/build-multiarch.sh publish \
  ghcr.io/your-org/abu-dhabi-gis-preprocess:v1
```

## Inventory a GDB ZIP

```bash
docker run --rm --read-only \
  --tmpfs /tmp:size=2g,mode=1777 \
  -v /path/to/customer:/input:ro \
  -v /path/to/inventory:/output \
  abu-dhabi-gis-preprocess:v1 \
  inventory --source /input/DMT_StormWater_AbuDhabi_Processed.gdb.zip \
  --output /output
```

## Compile the stormwater GDB

```bash
docker run --rm --read-only \
  --tmpfs /tmp:size=2g,mode=1777 \
  -v /path/to/customer:/input:ro \
  -v /path/to/compiled:/output \
  abu-dhabi-gis-preprocess:v1 \
  compile-abudhabi-stormwater-gdb \
  --gdb /input/DMT_StormWater_AbuDhabi_Processed.gdb.zip \
  --output-root /output
```

The output is private customer-derived data and must not be committed to the
public repository. It includes the normalized network, aggregate audit,
static-graph contract, source inventory and `gis_preprocess_run_manifest.json`.
The current GDB compilation stage is diagnostic-only: citywide SWMM input,
surface grid and coupling bindings remain false until their authoritative
source contracts are supplied.

## Pump stations

The customer stormwater GDB already contains a `PS_PUMP` layer. Normalize it
with the same image (the output is private and remains diagnostic-only unless
the physical units are explicitly declared):

```bash
docker run --rm --read-only \
  --tmpfs /tmp:size=2g,mode=1777 \
  -v /path/to/customer:/input:ro \
  -v /path/to/pumps:/output \
  abu-dhabi-gis-preprocess:v1 \
  compile-pump-stations \
  --source /input/DMT_StormWater_AbuDhabi_Processed.gdb.zip \
  --output-root /output \
  --layer PS_PUMP
```

This creates `pump_stations.private.geoparquet` and
`pump_stations_compile_manifest.json`. Pump curves, gate logic, telemetry and
runtime state are intentionally separate inputs and are not inferred from
asset attributes. Add `--flow-unit` and `--capacity-unit` only after those
units have been confirmed from the customer's data dictionary; supplying
plausible-looking units merely to pass admission is not acceptable.

## Tide or boundary series

CSV and Parquet series are normalized to UTC and checked for duplicate and
non-monotonic timestamps. A value unit and vertical datum are required before
the source contract is marked admitted:

```bash
docker run --rm --read-only \
  --tmpfs /tmp:size=2g,mode=1777 \
  -v /path/to/customer:/input:ro \
  -v /path/to/tide:/output \
  abu-dhabi-gis-preprocess:v1 \
  compile-tide-boundaries --source /input/tide.csv --output-root /output \
  --timestamp-field observed_at --value-field level_m \
  --boundary-field station_id --value-kind stage \
  --value-unit m --timezone Asia/Dubai --vertical-datum CD
```

## Land use

Land-use polygons can be supplied as a layer in a FileGDB or as another GDAL
vector source. The adapter reprojects to the target CRS, computes private
area metrics and validates an explicitly supplied imperviousness fraction:

```bash
docker run --rm --read-only \
  --tmpfs /tmp:size=2g,mode=1777 \
  -v /path/to/customer:/input:ro \
  -v /path/to/land-use:/output \
  abu-dhabi-gis-preprocess:v1 \
  compile-land-use --source /input/landuse.gpkg --output-root /output \
  --class-field land_use_class --code-field land_use_code \
  --imperviousness-field imperviousness
```

## Extension boundary

Additional adapters use the same pattern and manifest schema:

* `compile-terrain`: raster CRS, vertical datum, nodata and mesh/grid policy;
* pump control curves and telemetry: separate from static pump geometry;
* catchment joins and land-use crosswalks: separate from polygon normalization;
* boundary datum conversion and coastal coupling: separate from time-series
  normalization.

Each adapter must write a deterministic artifact manifest and must fail closed
when units, CRS, vertical datum or required fields are absent.
