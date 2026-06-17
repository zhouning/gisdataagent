# MMFE Local Lakehouse Docker Plan

Date: 2026-06-16

## Purpose

The local Docker environment now includes a MinIO S3-compatible object store.
For TWM/MMFE work, this is the local data-lake storage substrate used to
validate S3 URI conventions, bucket creation, warehouse prefixes, STAC catalog
prefixes, and credential propagation.

Docker Compose itself provides the object-store baseline, not a production
Spark cluster. Spark, Sedona, and Iceberg are currently validated through the
external PySpark runtime container
`192.168.106.71/datacenter/runtime-notebook-pyspark:v3.0.0-arrch64` against the
same MinIO network and bucket. A thin local derived image
`gisdataagent/mmfe-spark-runtime:local` now bakes the validated S3A, Iceberg,
and Sedona jars into Spark so the hard-path smoke tests can run without Maven
or Ivy package resolution at runtime.

## Docker Services

`docker-compose.yml` provides:

- `minio`: S3-compatible object store on API port `9000` and console port
  `9001`.
- `minio-bucket-init`: one-shot bucket initializer for:
  - `gis-agent-uploads`
  - `gis-agent-lakehouse`
- `app`: receives the same AWS-compatible environment variables used by the
  existing `AWSS3Adapter`.

Default local endpoints:

```text
AWS_ENDPOINT_URL=http://minio:9000
AWS_ACCESS_KEY_ID=minio_admin
AWS_SECRET_ACCESS_KEY=local_dev_minio_secret
AWS_S3_BUCKET=gis-agent-uploads
MMFE_LAKEHOUSE_BUCKET=gis-agent-lakehouse
MMFE_LAKEHOUSE_WAREHOUSE_URI=s3://gis-agent-lakehouse/warehouse
MMFE_STAC_CATALOG_URI=s3://gis-agent-lakehouse/catalog/stac
MMFE_ICEBERG_CATALOG=local
MMFE_ICEBERG_NAMESPACE=gis.fusion
MMFE_ICEBERG_TABLE=semantic_products
```

From the host, the MinIO console is available at:

```text
http://localhost:9001
```

Smoke test:

```bash
./scripts/smoke_mmfe_minio_lakehouse.sh
./scripts/smoke_mmfe_minio_stac.sh
PROJ_DATA=/Users/zhouning/miniconda3/envs/farmland-mpc/share/proj \
  .venv/bin/python scripts/smoke_mmfe_minio_materialize.py \
  --endpoint-url http://localhost:9000
PROJ_DATA=/Users/zhouning/miniconda3/envs/farmland-mpc/share/proj \
  .venv/bin/python scripts/smoke_mmfe_minio_stac_python.py \
  --endpoint-url http://localhost:9000 \
  --expect-product-id sfp-twm-dc2a707aabda0c01 \
  --asset-href s3://gis-agent-lakehouse/curated/mmfe/sfp-twm-dc2a707aabda0c01/twm_mmfe_business_view.csv
docker run --rm --network gisdataagent_agent-net \
  -e JAVA_HOME=/usr/lib/jvm/java-17-openjdk-arm64 \
  -v /Users/zhouning/gisdataagent:/workspace \
  -v /Users/zhouning/gisdataagent/.tmp/ivy2:/home/jovyan/.ivy2 \
  -w /workspace \
  192.168.106.71/datacenter/runtime-notebook-pyspark:v3.0.0-arrch64 \
  python scripts/smoke_mmfe_spark_minio.py
docker run --rm \
  -e JAVA_HOME=/usr/lib/jvm/java-17-openjdk-arm64 \
  -v /Users/zhouning/gisdataagent:/workspace \
  -v /Users/zhouning/gisdataagent/.tmp/ivy2:/home/jovyan/.ivy2 \
  -w /workspace \
  192.168.106.71/datacenter/runtime-notebook-pyspark:v3.0.0-arrch64 \
  python scripts/smoke_mmfe_sedona_sql.py
docker run --rm --network gisdataagent_agent-net \
  -e JAVA_HOME=/usr/lib/jvm/java-17-openjdk-arm64 \
  -v /Users/zhouning/gisdataagent:/workspace \
  -v /Users/zhouning/gisdataagent/.tmp/ivy2:/home/jovyan/.ivy2 \
  -w /workspace \
  192.168.106.71/datacenter/runtime-notebook-pyspark:v3.0.0-arrch64 \
  python scripts/smoke_mmfe_iceberg_minio.py
docker run --rm --network gisdataagent_agent-net \
  -e JAVA_HOME=/usr/lib/jvm/java-17-openjdk-arm64 \
  -v /Users/zhouning/gisdataagent:/workspace \
  -v /Users/zhouning/gisdataagent/.tmp/ivy2:/home/jovyan/.ivy2 \
  -w /workspace \
  192.168.106.71/datacenter/runtime-notebook-pyspark:v3.0.0-arrch64 \
  python scripts/smoke_mmfe_sedona_twm_geojson.py
docker build -f docker/mmfe-spark-runtime/Dockerfile \
  -t gisdataagent/mmfe-spark-runtime:local .
bash scripts/smoke_mmfe_baked_spark_runtime.sh
```

Default upload target:

```text
s3://gis-agent-lakehouse/raw/twm/parcel_current.semantic.json
s3://gis-agent-lakehouse/catalog/stac/mmfe-fusion-products/twm-parcel-current.json
```

2026-06-16 local result:

```text
[minio-smoke] uploaded s3://gis-agent-lakehouse/raw/twm/parcel_current.semantic.json
[minio-stac-smoke] uploaded s3://gis-agent-lakehouse/catalog/stac/mmfe-fusion-products/twm-parcel-current.json
```

2026-06-17 Python adapter result:

```text
materialized s3://gis-agent-lakehouse/curated/mmfe/sfp-twm-dc2a707aabda0c01/twm_mmfe_semantic_product.json
materialized s3://gis-agent-lakehouse/curated/mmfe/sfp-twm-dc2a707aabda0c01/twm_mmfe_business_view.csv
materialized s3://gis-agent-lakehouse/curated/mmfe/sfp-twm-dc2a707aabda0c01/sfp-twm-dc2a707aabda0c01_lakehouse_validation.geoparquet content_type=application/vnd.apache.parquet
published s3://gis-agent-lakehouse/catalog/stac/mmfe-fusion-products/sfp-twm-dc2a707aabda0c01.json
STAC data asset href=s3://gis-agent-lakehouse/curated/mmfe/sfp-twm-dc2a707aabda0c01/twm_mmfe_business_view.csv
spark read/write s3a://gis-agent-lakehouse/curated/mmfe/.../twm_mmfe_business_view.csv -> spark_smoke/business_summary
sedona SQL distance=5.0 contains_point=true
iceberg table mmfe.gis_fusion.semantic_products_smoke row_count=1 history_count=2
sedona TWM GeoJSON project/PBF intersections=39 reference_relation_rows=39 metric_mode=projected_m2
sedona TWM output=s3a://gis-agent-lakehouse/curated/mmfe/sfp-twm-dc2a707aabda0c01/spark_smoke/sedona_project_pbf_intersections
baked runtime jars present; Spark S3A, Iceberg, Sedona SQL, Sedona TWM GeoJSON, Sedona raster, Sedona raster zonal, Sedona raster clip, and Sedona raster clip STAC smokes all passed with packages=""
pdal docker smoke image=pdal/pdal:latest version=2.10.2 point_count=25 output=.tmp/mmfe-pdal-smoke/faux_points.las
COG materialized s3://gis-agent-lakehouse/curated/mmfe/sfp-twm-dc2a707aabda0c01/spark_smoke/sedona_project_ndvi_clips/cog/*.cog.tif
COG STAC collection=s3://gis-agent-lakehouse/catalog/stac/mmfe-derived-raster-cog-assets published_count=3
static STAC catalog=s3://gis-agent-lakehouse/catalog/stac/catalog.json collection_index=s3://gis-agent-lakehouse/catalog/stac/mmfe-derived-raster-cog-assets/collection.json item_count=3
```

## Baked Spark Runtime

`docker/mmfe-spark-runtime/Dockerfile` derives from the existing local PySpark
runtime and copies these already validated jars into `/usr/local/spark/jars`:

- `hadoop-aws-3.3.4.jar`
- `aws-java-sdk-bundle-1.12.262.jar`
- `wildfly-openssl-1.0.7.Final.jar`
- `iceberg-spark-runtime-3.5_2.12-1.6.1.jar`
- `sedona-spark-shaded-3.5_2.12-1.9.0.jar`
- `geotools-wrapper-1.9.0-33.5.jar`

`scripts/smoke_mmfe_baked_spark_runtime.sh` checks that those jars exist in the
image and then runs:

- `scripts/smoke_mmfe_spark_minio.py --packages ""`
- `scripts/smoke_mmfe_iceberg_minio.py --packages ""`
- `scripts/smoke_mmfe_sedona_sql.py --packages ""`
- `scripts/smoke_mmfe_sedona_twm_geojson.py --packages ""`
- `scripts/smoke_mmfe_sedona_raster.py --packages ""`
- `scripts/smoke_mmfe_sedona_raster_zonal.py --packages ""`
- `scripts/smoke_mmfe_sedona_raster_clip.py --packages ""`
- `scripts/smoke_mmfe_sedona_raster_clip_stac.py --packages ""`

The important validation point is `packages=""` in every smoke result. That
means Spark did not use `spark.jars.packages`, Maven, or the mounted Ivy cache
to resolve S3A, Iceberg, or Sedona at runtime.

The raster smoke uses `org.datasyslab:geotools-wrapper:1.9.0-33.5`. Before this
jar was added, even `RS_MakeEmptyRaster` failed with a missing
`org.geotools.coverage.grid.GridCoverage2D` class. After adding the wrapper,
Sedona raster SQL can construct rasters and read both the synthetic NDVI
fixture and the real Sentinel-2 NDVI GeoTIFF.

## MMFE Config Helpers

`data_agent/fusion/lakehouse_config.py` converts the environment into:

- object-store defaults
- Iceberg publish defaults
- STAC publish defaults
- Spark/Sedona S3A config

The FusionToolset publish-plan tool now uses these defaults when explicit
Iceberg/STAC settings are omitted. This lets a TWM `.semantic.json` produce a
valid local lakehouse publish plan without hard-coding the Docker bucket names
inside the tool call.

## Validation Boundary

Validated now:

- MinIO-compatible environment contract
- Docker MinIO bucket initialization for `gis-agent-uploads` and
  `gis-agent-lakehouse`
- object upload/list smoke test using a TWM semantic manifest
- STAC item upload/list smoke test under `catalog/stac/...`
- Python boto3-backed object materialization into `curated/mmfe/...` with
  read-back SHA-256 verification
- Python boto3-backed STAC publishing into MinIO with read-back item validation
- STAC item data asset pointing to the already materialized S3 lakehouse object
- containerized Spark 3.5 S3A read/compute/write/read-back against MinIO using
  the materialized TWM business CSV
- containerized Apache Sedona 1.9 vector SQL smoke on Spark 3.5
- containerized Spark Iceberg table creation/read-back/history read against the
  MinIO warehouse using Hadoop catalog
- containerized Apache Sedona 1.9 spatial join over real TWM GeoJSON layers:
  `synthetic_projects.geojson` and `synthetic_pbf.geojson` produced 39
  project/PBF intersections, matched the reference relation row count, computed
  projected overlap area in EPSG:32648, wrote CSV output to MinIO, and read it
  back through S3A
- local derived MMFE Spark runtime image with S3A, AWS SDK, Iceberg, and Sedona
  jars baked into Spark classpath; Spark S3A, Iceberg, Sedona SQL, and real TWM
  GeoJSON smoke tests passed with `--packages ""`
- Sedona raster SQL with GeoTools wrapper baked into the runtime:
  `RS_MakeEmptyRaster`, `RS_Count`, `RS_SummaryStatsAll`, `RS_AsMatrix`, and
  `RS_FromGeoTiff` passed against
  `rasters/synthetic_ndvi_2026.tif` and
  `real_imagery/sentinel2_l2a_ndvi.tif`
- Sedona raster/vector semantic fusion over the TWM validation dataset:
  `synthetic_projects.geojson` project polygons were transformed from
  EPSG:4326 to EPSG:32648, summarized against
  `real_imagery/sentinel2_l2a_ndvi.tif` with `RS_ZonalStatsAll`, written to
  `s3a://gis-agent-lakehouse/curated/mmfe/sfp-twm-dc2a707aabda0c01/spark_smoke/sedona_project_ndvi_zonal_stats`,
  and read back through S3A. The smoke produced 60 project/raster relation
  rows, including 20 projects with Sentinel-2 NDVI valid pixels.
- Sedona raster product materialization over the same TWM validation dataset:
  `RS_Clip(raster, 1, project_geom)` and `RS_AsGeoTiff` produced project-level
  NDVI GeoTIFF clips for three projects, wrote those `.tif` assets to
  `s3a://gis-agent-lakehouse/curated/mmfe/sfp-twm-dc2a707aabda0c01/spark_smoke/sedona_project_ndvi_clips/geotiff/`,
  wrote a manifest under `.../sedona_project_ndvi_clips/manifest`, and read
  each GeoTIFF back through S3A with `RS_FromGeoTiff`. The read-back preserved
  EPSG:32648 and matching NDVI summary statistics.
- STAC registration for the derived raster assets:
  `scripts/smoke_mmfe_sedona_raster_clip_stac.py` publishes one STAC item per
  clipped NDVI GeoTIFF under
  `s3://gis-agent-lakehouse/catalog/stac/mmfe-derived-raster-assets/`, using a
  Hadoop S3A publisher so the baked Spark runtime does not need boto3. The smoke
  published and read back three STAC items and verified each `data` asset href
  points to the corresponding lakehouse GeoTIFF with `proj:epsg=32648`.
- Host-side COG optimization for the derived raster assets:
  `scripts/smoke_mmfe_rasterio_cog_materialize.py` rewrote the three
  Sedona-derived project-level NDVI GeoTIFF clips as Cloud-Optimized GeoTIFFs
  with rasterio's COG driver, validated `LAYOUT=COG`, tiling, EPSG:32648, and
  unchanged raster shape/type, uploaded the `.cog.tif` files to
  `s3://gis-agent-lakehouse/curated/mmfe/sfp-twm-dc2a707aabda0c01/spark_smoke/sedona_project_ndvi_clips/cog/`,
  verified read-back SHA-256 checksums through MinIO, registered one STAC item
  per COG under
  `s3://gis-agent-lakehouse/catalog/stac/mmfe-derived-raster-cog-assets/`, and
  read back each STAC item with `roles=["data","derived","raster","ndvi","cog"]`.
  The same smoke now writes and reads back a static STAC root catalog at
  `s3://gis-agent-lakehouse/catalog/stac/catalog.json` plus the collection
  index
  `s3://gis-agent-lakehouse/catalog/stac/mmfe-derived-raster-cog-assets/collection.json`,
  with three `rel=item` links to the published COG STAC items. This is
  intentionally a host-side optional raster publishing job; the baked Spark
  runtime image still does not include rasterio/GDAL tooling.
- default MMFE lakehouse config generation
- optional S3/MinIO STAC publisher adapter contract
- dry-run Iceberg/STAC/vector publish planning from environment defaults
- pgvector real write/read path for TWM semantic wrapper
- local LanceDB real write/read path for the TWM semantic product
- real Ollama embedding gateway retrieval smoke for both local LanceDB and
  Docker pgvector using `nomic-embed-text-v2-moe` 768-dimensional embeddings
- optional PDAL Docker executor path: `pdal/pdal:latest` ran a real
  `readers.faux -> writers.las` pipeline through the MMFE runner contract,
  created `.tmp/mmfe-pdal-smoke/faux_points.las`, and `pdal info --summary`
  read back 25 points with valid bounds and LAS metadata
- GeoParquet object materialization through the Python S3 adapter:
  `scripts/smoke_mmfe_minio_materialize.py --include-geoparquet` now generates
  a tiny GeoParquet validation artifact, uploads it to
  `s3://gis-agent-lakehouse/curated/mmfe/<product_id>/`, assigns
  `application/vnd.apache.parquet`, and verifies read-back SHA-256 against
  MinIO

Not yet validated:

- Sedona raster reprojection output products and production STAC API/catalog
  governance for derived raster assets. Raster construction, GeoTIFF read
  metadata, project-level NDVI zonal statistics, project-level clipped GeoTIFF
  write/read-back to MinIO, STAC item registration/read-back, host-side COG
  optimization/materialization, and static STAC catalog/collection index
  publication are validated.
- Rasterio/GDAL packaging inside the baked Spark runtime image. COG optimization
  is validated from the macOS host `.venv`; production deployment still needs
  either a separate raster-publishing job image or an expanded Spark runtime
  image with the required GDAL/rasterio stack.
- production publication of the baked Spark runtime image to a registry and
  deployment wiring; the local baked image is validated, but not released as a
  production image
- PDAL execution over externally sourced real LAS/LAZ/COPC point-cloud inputs;
  the current PDAL smoke uses `readers.faux` to generate a minimal LAS fixture

The next implementation slice should move beyond object-store plumbing:

1. Promote the local baked Spark runtime into a registry-published deployment
   image and wire it into docker-compose/k8s job execution.
2. Extend the Sedona raster path from project-level clipped GeoTIFFs and
   STAC/COG/static-catalog items to reprojection products and production STAC
   API/catalog governance in MinIO.
3. Extend PDAL validation from generated faux LAS to real LAS/LAZ/COPC input,
   chunk materialization, and optional lakehouse upload.
