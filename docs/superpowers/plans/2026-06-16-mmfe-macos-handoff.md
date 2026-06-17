# MMFE macOS Handoff

Date: 2026-06-16

## Branch

- Repository: `https://github.com/zhouning/gisdataagent.git`
- Branch: `feat/v12-extensible-platform`
- Latest pushed MMFE commit before this handoff: `2b68e85 feat: expose MMFE publish plan tool`

On macOS:

```bash
git clone https://github.com/zhouning/gisdataagent.git
cd gisdataagent
git checkout feat/v12-extensible-platform
git pull origin feat/v12-extensible-platform
```

## Current MMFE State

MMFE is now defined and implemented as a universal multimodal semantic fusion
engine with geospatial-specialized adapters. Geospatial data is a critical
modality family, but not the boundary of MMFE.

Completed contract and orchestration layers:

- Semantic fusion product manifest with schema, product id, field contracts,
  semantic mappings, alignment scoring, review items, lineage, quality, and
  AI-ready chunks.
- Generic modality metadata on source profiles: `modality`, `media_type`, and
  `adapter_family`.
- Lightweight generic profiling for text/Markdown, GraphML, AI/model-output
  sidecars, documents/images/audio/video/unknown binaries as future adapter
  entry points.
- Raster semantic evidence: sidecar/STAC/ISO XML metadata, band scale/offset,
  nodata/unit, CRS/grid semantics, feature-chip summaries.
- Point-cloud semantic evidence: LAS/LAZ metadata, classification/intensity/RGB
  and return evidence, LAZ backend evidence, chunking plan.
- PDAL pipeline and runner contracts.
- External AI sidecar and runner contracts.
- Vector publish contracts for pgvector and LanceDB.
- Iceberg analytical lakehouse publish contract.
- Sedona-on-Iceberg runner contract.
- STAC discovery catalog publish contract.
- `publish_semantic_product()` orchestration across Iceberg, STAC, pgvector,
  and LanceDB contracts.
- `preflight_mmfe_lakehouse_infrastructure()` ADK FusionToolset tool for
  direct lakehouse infrastructure checks from agent workflows.
- `plan_semantic_product_publish()` ADK FusionToolset tool for dry-run publish
  preflight from an agent workflow.

Important boundary: most of the above is a stable dependency-free contract,
validation, orchestration, and test layer. It is not yet the production backend
adapter layer that imports and runs LanceDB, Spark/Iceberg/Sedona, PDAL, or
third-party AI model runtimes directly.

## Verification Already Run on Windows

```powershell
.\.venv\Scripts\python.exe -m pytest `
  data_agent\test_fusion_toolset_publish_plan.py `
  data_agent\test_fusion_engine.py `
  data_agent\test_fusion_semantic_alignment.py `
  data_agent\test_fusion_semantic_product.py `
  data_agent\test_fusion_semantic_publisher.py `
  data_agent\test_fusion_lakehouse_publisher.py `
  data_agent\test_fusion_v2_semantic.py `
  data_agent\test_fusion_v2_integration.py `
  data_agent\test_fusion_v2_explainability.py `
  data_agent\test_fusion_v2_conflict.py `
  data_agent\test_fusion_ai_semantics.py `
  data_agent\test_fusion_pdal_pipeline.py `
  data_agent\test_toolsets.py -q
```

Result:

```text
369 passed, 21 warnings
```

## macOS Continuation Update

2026-06-16 macOS continuation established that the previously prepared TWM
validation datasets are suitable as MMFE regression fixtures. They should be
treated as a complex validation scaffold, not authoritative production truth:

- `twm_bishan_demo` and `twm_bishan_multi_admin_eval` provide richer vector,
  real Sentinel-2 imagery, rule-evaluation, relation, standard-contract, and
  optimization context for MMFE publishing validation.
- Their `parcel_current.semantic.json` and `synthetic_annual_change.semantic.json`
  manifests are minimal semantic wrappers. They intentionally lack full
  semantic-product chunks and stable product ids.
- MMFE vector publishing now supports these wrappers by deriving a stable
  fallback product id and creating one retrieval record from
  `ai_metadata.retrieval_text`.
- The four current TWM semantic wrappers are included in the semantic publisher
  regression test as `twm_validation_scaffold` fixtures.

Backend-adapter progress:

- Added optional local LanceDB executor:
  `data_agent/fusion/lancedb_adapter.py`.
- Added optional pgvector executor:
  `data_agent/fusion/pgvector_adapter.py`.
- Both adapters are imported only through optional execution paths and should
  not make MMFE core imports depend on LanceDB, PyArrow, PostgreSQL, or a live
  database.
- Real LanceDB integration is skipped unless `lancedb` and `pyarrow` are
  installed.
- Real pgvector integration is skipped unless `MMFE_PGVECTOR_TEST_DSN` points
  to an isolated pgvector-enabled PostgreSQL test database. On this macOS
  machine, the Docker Compose database at `localhost:5433` was used to validate
  the TWM semantic wrapper write/read path against table
  `agent_mmfe_semantic_vectors_test`.

Verification run on macOS:

```bash
PROJ_DATA=/Users/zhouning/miniconda3/envs/farmland-mpc/share/proj \
  .venv/bin/python -m pytest \
  data_agent/test_fusion_toolset_publish_plan.py \
  data_agent/test_fusion_semantic_product.py \
  data_agent/test_fusion_semantic_alignment.py \
  data_agent/test_fusion_semantic_publisher.py \
  data_agent/test_fusion_lakehouse_publisher.py \
  data_agent/test_fusion_ai_semantics.py \
  data_agent/test_fusion_pdal_pipeline.py \
  data_agent/test_fusion_lancedb_adapter.py \
  data_agent/test_fusion_pgvector_adapter.py -q
```

Result:

```text
87 passed, 2 skipped, 4 warnings
```

Additional OKF validation run on macOS:

```bash
PROJ_DATA=/Users/zhouning/miniconda3/envs/farmland-mpc/share/proj \
  .venv/bin/python -m pytest \
  data_agent/test_fusion_okf_exporter.py \
  data_agent/test_twm_mmfe_okf_export.py \
  data_agent/test_twm_mmfe_semantic_bundle.py \
  data_agent/test_fusion_toolset_publish_plan.py \
  data_agent/test_fusion_semantic_product.py \
  data_agent/test_fusion_semantic_publisher.py \
  data_agent/test_fusion_lakehouse_config.py \
  data_agent/test_fusion_s3_stac_adapter.py \
  data_agent/test_fusion_lancedb_adapter.py \
  data_agent/test_fusion_pgvector_adapter.py -q
```

Result:

```text
52 passed, 2 skipped, 4 warnings
```

Additional semantic vector retrieval validation run on macOS:

```bash
PROJ_DATA=/Users/zhouning/miniconda3/envs/farmland-mpc/share/proj \
  .venv/bin/python -m pytest \
  data_agent/test_fusion_semantic_publisher.py \
  data_agent/test_fusion_lakehouse_publisher.py \
  data_agent/test_fusion_lakehouse_config.py \
  data_agent/test_fusion_s3_stac_adapter.py \
  data_agent/test_fusion_lancedb_adapter.py \
  data_agent/test_fusion_pgvector_adapter.py \
  data_agent/test_fusion_okf_exporter.py \
  data_agent/test_twm_mmfe_okf_export.py \
  data_agent/test_twm_mmfe_semantic_bundle.py \
  data_agent/test_fusion_toolset_publish_plan.py \
  data_agent/test_fusion_semantic_product.py -q
```

Result:

```text
79 passed, 2 skipped, 4 warnings
```

The two skips are expected in the default macOS environment: one for optional
LanceDB dependencies and one for an explicit pgvector test DSN.

Real pgvector smoke test run on macOS with Docker database:

```bash
PROJ_DATA=/Users/zhouning/miniconda3/envs/farmland-mpc/share/proj \
MMFE_PGVECTOR_TEST_DSN=postgresql://postgres:postgres@localhost:5433/gis_agent \
  .venv/bin/python -m pytest data_agent/test_fusion_pgvector_adapter.py -q
```

Result:

```text
4 passed
```

Real TWM semantic product publish -> vector store -> query smoke was also
validated against the same Docker pgvector database:

```bash
PROJ_DATA=/Users/zhouning/miniconda3/envs/farmland-mpc/share/proj \
  .venv/bin/python scripts/smoke_mmfe_semantic_vector_retrieval.py \
  --target pgvector \
  --pgvector-dsn postgresql://postgres:postgres@localhost:5433/gis_agent \
  --embedding-backend deterministic \
  --collection twm_mmfe_smoke \
  --query "永久基本农田占用审查" \
  --expect-text "永久基本农田"
```

Result:

```text
status=ok
published_count=13
match_count=3
expectation_ok=true
product_id=sfp-twm-dc2a707aabda0c01
table=agent_mmfe_semantic_vectors_smoke
embedding_backend=deterministic
embedding_dimension=16
```

This validates the hard integration path for the current TWM fixture:
semantic product chunks -> embeddings -> pgvector writes -> vector query
retrieval. It does not validate production semantic quality, because the
embedding backend in this run is the deterministic offline smoke embedder, not
a real embedding model.

Real local LanceDB publish -> vector store -> query smoke was then validated
after installing `lancedb` and `pyarrow==20.0.0` into `.venv`:

```bash
PROJ_DATA=/Users/zhouning/miniconda3/envs/farmland-mpc/share/proj \
  .venv/bin/python scripts/smoke_mmfe_semantic_vector_retrieval.py \
  --target lancedb \
  --embedding-backend deterministic \
  --collection twm_mmfe_smoke \
  --query "永久基本农田占用审查" \
  --expect-text "永久基本农田"
```

Result:

```text
status=ok
published_count=13
match_count=3
expectation_ok=true
product_id=sfp-twm-dc2a707aabda0c01
dataset_uri=.tmp/mmfe-lancedb-smoke
table=semantic_products
embedding_backend=deterministic
embedding_dimension=16
```

Real embedding gateway retrieval was then validated with the local Ollama model
`nomic-embed-text-v2-moe:latest`. LanceDB path:

```bash
PROJ_DATA=/Users/zhouning/miniconda3/envs/farmland-mpc/share/proj \
  .venv/bin/python scripts/smoke_mmfe_semantic_vector_retrieval.py \
  --target lancedb \
  --embedding-backend gateway \
  --embedding-model nomic-embed-text-v2-moe \
  --collection twm_mmfe_gateway_smoke \
  --query "永久基本农田占用审查" \
  --expect-text "永久基本农田" \
  --lancedb-uri .tmp/mmfe-lancedb-gateway-smoke
```

Result:

```text
status=ok
published_count=13
match_count=3
expectation_ok=true
embedding_model=nomic-embed-text-v2-moe
embedding_dimension=768
top_match=fusion:layer:synthetic_pbf
```

pgvector path using a separate 768-dimensional smoke table:

```bash
PROJ_DATA=/Users/zhouning/miniconda3/envs/farmland-mpc/share/proj \
  .venv/bin/python scripts/smoke_mmfe_semantic_vector_retrieval.py \
  --target pgvector \
  --pgvector-dsn postgresql://postgres:postgres@localhost:5433/gis_agent \
  --pgvector-table agent_mmfe_semantic_vectors_smoke_768 \
  --embedding-backend gateway \
  --embedding-model nomic-embed-text-v2-moe \
  --collection twm_mmfe_gateway_smoke \
  --query "永久基本农田占用审查" \
  --expect-text "永久基本农田"
```

Result:

```text
status=ok
published_count=13
match_count=3
expectation_ok=true
embedding_model=nomic-embed-text-v2-moe
embedding_dimension=768
top_match=fusion:layer:synthetic_pbf
table=agent_mmfe_semantic_vectors_smoke_768
```

Important pgvector production note: pgvector stores dimension at column type
level, for example `vector(16)` or `vector(768)`. The deterministic smoke
embedder and real embedding models must not share the same pgvector table
unless their embedding dimensions match. The adapter now checks an existing
table's `embedding` column dimension before insert and returns a clear error
if the payload dimension differs.

The next hard validations remain:

- Production publication and deployment wiring for the local baked Spark
  runtime image that already contains pinned S3A/Iceberg/Sedona jars.
- Deeper Sedona raster operations beyond the validated zonal statistics,
  project-level clipped GeoTIFF write/read-back path, minimal derived raster
  STAC registration, host-side COG materialization, and static STAC
  catalog/collection index publishing: reprojection products and production
  STAC API/catalog governance in MinIO.
- Rasterio/GDAL packaging for production. The macOS host `.venv` can run the
  COG optimization smoke, but the baked Spark runtime image intentionally does
  not yet include rasterio, GDAL CLI tools, or rio-cogeo.
- PDAL execution against externally sourced real LAS/LAZ/COPC inputs, beyond
  the generated faux LAS smoke.

Local lakehouse update:

- Docker Compose now includes MinIO and a bucket initializer for
  `gis-agent-uploads` and `gis-agent-lakehouse`.
- The app container receives AWS-compatible MinIO variables plus MMFE lakehouse
  defaults such as `MMFE_LAKEHOUSE_WAREHOUSE_URI` and `MMFE_STAC_CATALOG_URI`.
- `data_agent/fusion/lakehouse_config.py` converts these variables into
  Iceberg/STAC publish defaults and Spark/Sedona S3A settings.
- `plan_semantic_product_publish()` can fill missing Iceberg/STAC settings from
  those environment defaults.
- Added optional S3/MinIO STAC publisher and object materialization adapters.
  The Python `.venv` now includes boto3/botocore, and the Python path has been
  validated against Docker MinIO:
  - TWM semantic product JSON and business CSV materialized to
    `s3://gis-agent-lakehouse/curated/mmfe/sfp-twm-dc2a707aabda0c01/...`
    with read-back SHA-256 verification.
  - The same materialization smoke can generate a tiny GeoParquet validation
    artifact with `--include-geoparquet`, upload it under the same curated
    prefix, set `application/vnd.apache.parquet`, and verify read-back
    SHA-256 against MinIO.
  - STAC item published to
    `s3://gis-agent-lakehouse/catalog/stac/mmfe-fusion-products/sfp-twm-dc2a707aabda0c01.json`
    and read back through boto3.
  - The STAC data asset now points to the materialized S3 CSV rather than a
    local filesystem path.
- Containerized Spark/Sedona runtime validation has started using
  `192.168.106.71/datacenter/runtime-notebook-pyspark:v3.0.0-arrch64` with
  corrected `JAVA_HOME=/usr/lib/jvm/java-17-openjdk-arm64`:
  - Spark 3.5 read the materialized CSV from MinIO through S3A, wrote a summary
    back under `curated/mmfe/.../spark_smoke/business_summary`, and read it
    back successfully.
  - Sedona 1.9 vector SQL smoke returned `ST_Distance(...)=5.0` and
    `ST_Contains(...)=true`.
  - Iceberg wrote and read table
    `mmfe.gis_fusion.semantic_products_smoke` against the MinIO warehouse, with
    one data row and two history entries.
  - Sedona parsed real TWM GeoJSON layers
    `synthetic_projects.geojson` and `synthetic_pbf.geojson`, computed 39
    project/PBF spatial intersections with projected overlap areas in
    EPSG:32648, matched the reference relation row count, wrote the output to
    `curated/mmfe/.../spark_smoke/sedona_project_pbf_intersections`, and read it
    back through S3A.
  - Added `docker/mmfe-spark-runtime/Dockerfile`, deriving from the local
    PySpark image and baking in `hadoop-aws`, AWS SDK, Iceberg runtime, Sedona
    shaded, WildFly OpenSSL, and `org.datasyslab:geotools-wrapper:1.9.0-33.5`
    jars.
  - Added `scripts/smoke_mmfe_baked_spark_runtime.sh`. It checks the baked jars
    and reruns Spark S3A, Iceberg, Sedona SQL, Sedona TWM GeoJSON, and Sedona
    raster smokes with `--packages ""`; all passed, so this path no longer
    depends on Maven/Ivy runtime resolution.
  - Added `scripts/smoke_mmfe_sedona_raster.py`. It validates
    `RS_MakeEmptyRaster`, `RS_Count`, `RS_SummaryStatsAll`, `RS_AsMatrix`, and
    `RS_FromGeoTiff` over both `rasters/synthetic_ndvi_2026.tif` and
    `real_imagery/sentinel2_l2a_ndvi.tif`.
  - Added `scripts/smoke_mmfe_sedona_raster_zonal.py`. It transforms TWM
    project polygons into EPSG:32648, computes `RS_ZonalStatsAll` against the
    real Sentinel-2 NDVI GeoTIFF, writes the project-level NDVI semantic
    relation table to
    `curated/mmfe/.../spark_smoke/sedona_project_ndvi_zonal_stats`, and reads it
    back through S3A. The local run produced 60 project/raster rows, including
    20 projects with valid observed NDVI pixels.
  - Added `scripts/smoke_mmfe_sedona_raster_clip.py`. It uses
    `RS_Clip(raster, 1, project_geom)` and `RS_AsGeoTiff` to create
    project-level NDVI GeoTIFF clips, writes three `.tif` artifacts and a
    manifest to
    `curated/mmfe/.../spark_smoke/sedona_project_ndvi_clips`, then reads each
    GeoTIFF back through S3A with `RS_FromGeoTiff`. The local run preserved
    EPSG:32648 and matching NDVI statistics for all three read-back rasters.
  - Added `scripts/smoke_mmfe_sedona_raster_clip_stac.py`. It registers the
    three Sedona-derived NDVI GeoTIFF clips as STAC items in
    `catalog/stac/mmfe-derived-raster-assets`, using Hadoop S3A instead of
    boto3 so it runs inside the baked Spark runtime. The smoke reads the STAC
    items back and verifies each `data` asset href and `proj:epsg=32648`.
  - Added `scripts/smoke_mmfe_rasterio_cog_materialize.py`. It runs from the
    macOS host `.venv`, rewrites those three Sedona-derived NDVI clips as COGs,
    validates `LAYOUT=COG`, tiling, CRS, and shape/type preservation, uploads
    the `.cog.tif` files to
    `curated/mmfe/.../spark_smoke/sedona_project_ndvi_clips/cog`, verifies
    MinIO read-back SHA-256 checksums, and registers three STAC items under
    `catalog/stac/mmfe-derived-raster-cog-assets` with the `cog` asset role.
    The same smoke now publishes and reads back static STAC indexes:
    `catalog/stac/catalog.json` and
    `catalog/stac/mmfe-derived-raster-cog-assets/collection.json`, where the
    collection index contains three `rel=item` links to the COG STAC items.
- Current `.venv` now includes `lancedb`, `pyarrow==20.0.0`, `boto3`, and
  rasterio, and the real local LanceDB publish/query smoke plus host-side COG
  publish smoke have been validated. These dependencies are declared in the
  `.[mmfe]` optional dependency group rather than core lite mode.
- Added optional PDAL Docker executor helpers in
  `data_agent/fusion/pdal_pipeline.py`:
  `build_docker_pdal_executor()` and `build_docker_pdal_runner_spec()`.
  `scripts/smoke_mmfe_pdal_docker.py` ran `pdal/pdal:latest` 2.10.2 through the
  MMFE runner contract, executed a real `readers.faux -> writers.las` pipeline,
  created `.tmp/mmfe-pdal-smoke/faux_points.las`, and verified 25 output points
  with `pdal info --summary`.
- Detailed boundary and next steps are recorded in
  `docs/superpowers/plans/2026-06-16-mmfe-local-lakehouse-docker.md`.

OKF sidecar update:

- Added `data_agent/fusion/okf_exporter.py` as a generic MMFE semantic product
  to OKF Markdown bundle exporter.
- Added `export_semantic_product_okf()` to `FusionToolset` so an agent workflow
  can export a semantic product manifest to a human- and agent-readable review
  bundle.
- OKF is explicitly a sidecar layer. The authoritative machine contracts remain
  the semantic product JSON, field semantic CSV/JSON content, STAC/Iceberg
  publish specs, and pgvector/LanceDB vector publish specs.
- The TWM validation semantic product can now be exported through the generic
  exporter while automatically loading the conventional TWM sidecars:
  `twm_mmfe_field_semantics.csv`, `twm_state_input_contract.json`, and
  `twm_mmfe_semantic_graph.json`.
- The regenerated TWM OKF fixture at
  `data_agent/test_data/twm_bishan_demo/mmfe_semantic_fusion/okf_bundle`
  contains 193 Markdown files and uses `datasets/semantic_product.md` as the
  generic dataset entrypoint.

Semantic vector retrieval update:

- Added a generic semantic vector query contract in
  `data_agent/fusion/semantic_publisher.py`:
  `build_semantic_vector_query_spec()`, `embed_semantic_vector_query()`, and
  `run_semantic_vector_query()`.
- Added injected query adapters:
  `build_lancedb_querier()` and `build_pgvector_querier()`.
- Added optional backend query executors:
  `build_local_lancedb_query_executor()` /
  `query_lancedb_semantic_vectors()` and
  `build_pgvector_query_executor()` /
  `query_pgvector_semantic_vectors()`.
- Added `query_semantic_vectors()` to `FusionToolset`. It can return a validated
  query plan without executing an embedding call, or execute a backend query
  when the caller provides `query_embedding_json` generated by the same
  embedding model used at publish time.
- The MMFE vector path now covers publish -> store -> query contracts for both
  LanceDB and pgvector, while keeping optional runtime dependencies out of core
  imports.

## Recommended macOS Next Slice

Stop extending pure contracts for now. The pgvector and local LanceDB hard
retrieval paths are validated with the deterministic offline smoke embedder.
Use the macOS environment to validate the remaining production-like paths in
this order:

1. Real embedding gateway retrieval smoke
   - Configure one production embedding backend: Gemini/Vertex,
     local sentence-transformers, or Ollama.
   - Re-run `scripts/smoke_mmfe_semantic_vector_retrieval.py` for both
     pgvector and LanceDB with `--embedding-backend gateway`.
   - Confirm the publish and query vectors come from the same active model and
     have the expected dimension.

2. Spark/Iceberg/Sedona production adapter examples
   - Keep Spark/Iceberg/Sedona optional.
   - Promote the executable local smoke scripts into documented adapter
     examples and config templates.
   - Add docs for catalog, warehouse URI, Spark config, Sedona SQL, expected
     manifest patch behavior, and registry/deployment wiring for the baked
     Spark runtime image.

3. PDAL/LAZ real execution path
   - Keep PDAL optional.
   - Move beyond the generated `readers.faux` smoke to externally sourced real
     LAS/LAZ/COPC input.
   - Use the existing runner spec and chunk artifact manifest contracts for
     chunk materialization and optional lakehouse upload.

## Files Most Relevant for Continuation

- `data_agent/fusion/semantic_product.py`
- `data_agent/fusion/semantic_publisher.py`
- `data_agent/fusion/lakehouse_publisher.py`
- `data_agent/fusion/okf_exporter.py`
- `data_agent/fusion/pdal_pipeline.py`
- `data_agent/fusion/ai_semantics.py`
- `data_agent/toolsets/fusion_tools.py`
- `data_agent/test_fusion_okf_exporter.py`
- `data_agent/test_twm_mmfe_okf_export.py`
- `data_agent/test_fusion_semantic_publisher.py`
- `data_agent/test_fusion_lakehouse_publisher.py`
- `data_agent/test_fusion_toolset_publish_plan.py`
- `docs/superpowers/specs/2026-06-15-mmfe-semantic-fusion-product-design.md`
- `docs/superpowers/plans/2026-06-15-mmfe-semantic-fusion-product.md`

## Windows Workspace Note

The Windows workspace still has unrelated local dirty changes in NL2SQL,
temporary output, and benchmark files. They were intentionally not staged or
committed with MMFE. A fresh macOS clone of `feat/v12-extensible-platform` will
not include those local dirty files.

## 2026-06-17 Production-System Continuation Update

User clarified that MMFE should continue according to real production-system
requirements, not as a demo. The current TWM dataset remains a validation
fixture, but MMFE capabilities should be designed as production controls,
contracts, gates, and auditable artifacts.

Latest completed MMFE production-system slices:

- Semantic graph standard/value-domain integration is in place.
  - `twm_mmfe_semantic_graph.json` contains 1424 nodes and 3547 edges.
  - `field:parcel_current.DLBM` traces through
    `value_domain:gb_t_21010_2017_land_use_code` to
    `standard_source:gb-t-21010-2017`.
- Semantic trace cards are generated and exposed.
  - Module: `data_agent/fusion/semantic_graph_trace.py`
  - Tool: `trace_mmfe_semantics()` in
    `data_agent/toolsets/fusion_tools.py`
  - TWM trace card count: 14.
- Semantic product readiness diagnostics are now a first-class contract.
  - Module: `data_agent/fusion/semantic_product_diagnostics.py`
  - Schema: `mmfe.semantic_product_diagnostic.v1`
  - Tool: `diagnose_mmfe_semantic_product()`
  - The TWM-MMFE product diagnoses as:
    - `validation_ready=true`
    - `production_ready=false`
    - status: `validation_ready_with_production_gaps`
    - readiness score: `0.8984`
  - Production gaps are explicitly tracked:
    - authoritative natural-resource production data is still required;
    - six natural-resource One Map expert-material standards still need
      official public source/full-text evidence.
- The TWM MMFE bundle generation now materializes diagnostics.
  - Script: `scripts/build_twm_mmfe_semantic_bundle.py`
  - New output: `twm_mmfe_semantic_diagnostic.json`
  - The semantic product manifest now records:
    - `business_outputs.semantic_diagnostic`
    - `mmfe_bundle.semantic_diagnostic_summary`
    - `mmfe_bundle.semantic_diagnostic_top_gaps`
    - `mmfe_bundle.semantic_diagnostic_recommendations_zh`
  - STAC item now contains a `semantic_diagnostic` asset.
  - README now shows diagnostic status, validation readiness, and production
    readiness.
- OKF export now includes readiness diagnostics.
  - `data_agent/fusion/okf_exporter.py` loads
    `twm_mmfe_semantic_diagnostic.json` when present, or derives diagnostics
    from available sidecars.
  - New OKF document:
    `diagnostics/semantic_product_readiness.md`
  - Actual OKF export from a fresh generated bundle produced:
    - `file_count=939`
    - `concept_count=911`
- Production publish gate was added to the publish-plan layer.
  - Schema: `mmfe.production_publish_gate.v1`
  - Function: `build_production_publish_gate()`
  - `build_semantic_product_publish_plan()` now prepends a
    `production_gate` step.
  - `plan_semantic_product_publish()` now accepts:
    - `publish_environment=production|validation|development`
    - `require_production_ready=true|false|auto`
  - Production environment defaults to strict mode and requires
    `production_ready=true`.
  - Validation/development environments allow `validation_ready=true` products
    to flow, but retain production-gap warnings.
- The same production gate is now enforced by actual
  `publish_semantic_product()` execution, not only by dry-run planning.
  - Production publish of the current validation-only TWM product returns
    `valid=false` before any Iceberg/STAC/vector backend adapter is called.
  - Validation publish can execute configured backends, but the returned result
    includes `production_gate.warnings` so production gaps remain visible.
- Production-readiness source metadata is now a formal MMFE contract.
  - Schema: `mmfe.production_readiness.v1`
  - Module: `data_agent/fusion/production_readiness.py`
  - Required source metadata includes authority, authority level,
    license/access rights, update date, lineage, CRS, scale or resolution,
    official standard version, and security classification.
  - `diagnose_semantic_product_readiness()` now adds
    `production_metadata_contract`; `production_authority` can only pass when
    this source-level contract is present and ready.
  - The TWM bundle now emits `twm_mmfe_production_readiness.json`, adds it to
    `business_outputs`, publishes it as a STAC asset, and shows the readiness
    summary in README output. The current validation fixture has
    `production_metadata_ready=false` and 10 blocked sources.
- Standard-source acquisition is now represented as an auditable ingestion plan.
  - Schema: `mmfe.standard_source_ingestion_plan.v1`
  - Function: `build_standard_source_ingestion_plan()`
  - Each standard source becomes an acquisition/extraction task with official
    URL/search URL, retrieval status, required actions, checksum/archive state,
    extraction status, and blocking reasons.
  - The TWM bundle emits
    `twm_mmfe_standard_source_ingestion_plan.json`, adds it to
    `business_outputs`, publishes it as a STAC asset, and includes
    `standard_source_ingestion` in readiness diagnostics. The current fixture
    has `standard_source_ingestion_ready=false` and 7 blocked tasks.
- The first standard-source ingestion runner contract is implemented.
  - Schema: `mmfe.standard_source_ingestion_run.v1`
  - Function: `run_standard_source_ingestion_plan()`
  - The runner executes plan tasks through injected `fetcher`, `archiver`, and
    `extractor` adapters, recording archive URI, SHA-256 checksum, extraction
    status, and citation-anchor counts.
  - MMFE core still does not perform network download or PDF parsing directly;
    missing adapters produce structured per-task errors.
- The first concrete local standard-source adapter path is implemented.
  - Sidecar schema: `mmfe.standard_source_citation_anchors.v1`
  - Functions: `build_local_standard_source_fetcher()`,
    `build_local_standard_source_archiver()`,
    `build_local_standard_source_extractor()`,
    `build_http_standard_source_fetcher()`,
    `build_s3_standard_source_archiver()`,
    `archive_standard_source_bytes_to_s3()`,
    `apply_standard_source_ingestion_run()`
  - The local fetcher reads task-local or identifier-mapped files, the archiver
    writes bytes/checksums with stable archive URIs, and the extractor writes
    citation-anchor JSON sidecars for UTF-8-readable text/CSV/JSON standards
    plus dependency-free `.docx` files parsed from OOXML `word/document.xml`.
  - The HTTP fetcher is an explicit injected adapter for authorized official
    URL retrieval. It supports official-domain allowlists, records HTTP status,
    source URL, content type, byte count, and SHA-256, and can be tested with a
    fake opener without real network calls.
  - The S3/MinIO archiver persists fetched standard-source bytes to a configured
    `s3://...` prefix with bucket/key, content type, byte count, endpoint, and
    SHA-256 metadata, while importing boto3 only on the optional adapter path.
  - Successful ingestion runs can be folded back into the registry, recording
    archive URI, checksum, bytes, extraction status, citation-anchor count, and
    sidecar path so the next ingestion plan marks completed sources as ready.
  - This supports offline development and production rehearsal without adding
    network, PDF, legacy-DOC, or object-store dependencies to MMFE core import
    time.
- Enriched standard-source registries now participate in production-readiness
  metadata.
  - Function: `standard_source_production_metadata_from_registry()`
  - Archived and extracted official standards map into
    `mmfe.production_readiness.v1` rows with archive URI, checksum, access
    rights, extraction status, citation-anchor counts, and
    `not_for_production` flags.
  - The TWM bundle appends those standard-source rows to
    `twm_mmfe_production_readiness.json`, so standard-source ingestion
    completion feeds the same production gate as authoritative source metadata.
- Authoritative data-source metadata can now enter the same production
  readiness contract without backend coupling.
  - Function: `source_production_metadata_from_records()`
  - Metadata rows from `metadata_vector.csv`-style tables or platform API
    responses normalize to authority, access rights, update date, lineage, CRS,
    scale/resolution, official standard version, security classification, and
    synthetic/not-for-production flags.
  - `production_readiness_from_manifest()` now derives source rows from
    `mmfe_bundle.source_production_metadata`, metadata records, and
    `mmfe_bundle.standard_source_registry`, deduplicating explicit standard rows
    and registry-derived rows.
- Lakehouse infrastructure preflight is now a formal MMFE contract.
  - Schema: `mmfe.infrastructure_preflight.v1`
  - Functions: `build_lakehouse_infrastructure_preflight()`,
    `validate_lakehouse_infrastructure_preflight()`
  - The preflight checks object-store endpoint/buckets/credentials, Iceberg
    warehouse/table identity, STAC catalog location, Spark S3A settings, and
    production-environment risks such as local MinIO endpoints or local default
    credentials.
  - It now also detects cross-component configuration drift between the
    object-store warehouse URI, Iceberg warehouse URI, lakehouse bucket, STAC
    catalog URI, and Spark S3A endpoint.
  - Spark S3A preflight now verifies SimpleAWSCredentialsProvider has access
    and secret keys, and checks Spark access key, path-style access, and SSL
    settings against the object-store config.
  - The preflight result now includes a stable SHA-256
    `config_fingerprint` over non-secret lakehouse config material for
    deployment audit/comparison without exposing access keys or secret keys.
  - `build_semantic_product_publish_plan()` now adds an
    `infrastructure_preflight` step immediately after the production gate, and
    the FusionToolset summary exposes `infrastructure_preflight_valid`.
  - `preflight_mmfe_lakehouse_infrastructure()` exposes the same contract
    directly to agent workflows from a full config JSON or environment-variable
    override JSON, without requiring a semantic product manifest or publish
    plan.
  - `plan_semantic_product_publish()` normalizes environment defaults when the
    caller explicitly overrides the Iceberg warehouse URI, so derived lakehouse
    bucket and default STAC catalog URI stay aligned with that warehouse.
  - `publish_semantic_product()` now enforces the same preflight before any
    Iceberg/STAC/vector backend adapter is called, returning structured
    `infrastructure_preflight` errors for production-local endpoints or local
    default MinIO credentials while allowing validation smoke runs with
    warnings.
  - Sanitized preflight config redacts access keys and secret keys before the
    plan or publish result is returned.

Important verified behavior:

- For current TWM-MMFE product with `publish_environment=production`:
  - plan is invalid;
  - `production_gate.valid=false`;
  - error: `semantic product is not production_ready`;
  - warnings list the authoritative-data and official-standard-source gaps.
- For the same product with `publish_environment=validation`:
  - plan is valid;
  - `production_gate.valid=true`;
  - warnings are preserved so the product cannot be mistaken for production
    ready.

Most recent verification commands:

```bash
PROJ_DATA=/Users/zhouning/miniconda3/envs/farmland-mpc/share/proj \
  .venv/bin/python -m pytest \
  data_agent/test_fusion_lakehouse_publisher.py \
  data_agent/test_fusion_toolset_publish_plan.py -q
```

Result:

```text
45 passed, 5 warnings
```

Runtime publish-gate focused verification:

```bash
.venv/bin/python -m pytest data_agent/test_fusion_lakehouse_publisher.py -q
```

Result:

```text
25 passed, 1 warning
```

Production-readiness and publish-gate focused verification:

```bash
.venv/bin/python -m pytest \
  data_agent/test_fusion_lakehouse_config.py \
  data_agent/test_fusion_standard_sources.py \
  data_agent/test_fusion_production_readiness.py \
  data_agent/test_fusion_semantic_product_diagnostics.py \
  data_agent/test_twm_mmfe_semantic_bundle.py \
  data_agent/test_fusion_lakehouse_publisher.py \
  data_agent/test_fusion_toolset_publish_plan.py -q
```

Result:

```text
82 passed, 5 warnings
```

```bash
PROJ_DATA=/Users/zhouning/miniconda3/envs/farmland-mpc/share/proj \
  .venv/bin/python -m pytest \
  data_agent/test_fusion_semantic_alignment.py \
  data_agent/test_fusion_semantic_product.py \
  data_agent/test_fusion_semantic_product_diagnostics.py \
  data_agent/test_fusion_lakehouse_publisher.py \
  data_agent/test_fusion_okf_exporter.py \
  data_agent/test_fusion_semantic_graph_trace.py \
  data_agent/test_twm_mmfe_semantic_bundle.py \
  data_agent/test_twm_mmfe_okf_export.py \
  data_agent/test_fusion_toolset_publish_plan.py \
  data_agent/test_twm_state_input.py \
  data_agent/test_fusion_standard_sources.py -q
```

Result:

```text
80 passed, 4 warnings
```

Actual generation/export smoke checks:

```bash
PROJ_DATA=/Users/zhouning/miniconda3/envs/farmland-mpc/share/proj \
  .venv/bin/python scripts/build_twm_mmfe_semantic_bundle.py \
  --data-dir data_agent/test_data/twm_bishan_demo \
  --out-dir /tmp/twm-mmfe-diagnostic-check
```

Output included:

```text
standard_source_ingestion_ready=false
standard_source_ingestion_blocked_task_count=7
production_readiness_ready=false
production_readiness_blocked_source_count=17
semantic_diagnostic_status=validation_ready_with_production_gaps
semantic_diagnostic_validation_ready=true
semantic_diagnostic_production_ready=false
```

```bash
PROJ_DATA=/Users/zhouning/miniconda3/envs/farmland-mpc/share/proj \
  .venv/bin/python scripts/export_twm_mmfe_okf_bundle.py \
  --mmfe-dir /tmp/twm-mmfe-diagnostic-check \
  --out-dir /tmp/twm-mmfe-diagnostic-check/okf_bundle
```

Result:

```text
valid=true
file_count=939
concept_count=911
```

Recommended next production-system slice:

1. Extend concrete standard-source ingestion adapters beyond the current
   HTTP/S3/local-text/DOCX path: production authorization/policy handling for
   official downloads and PDF/legacy-DOC full-text extraction into
   citation-anchor sidecars.
2. Add production-readiness ingestion for real authoritative datasets:
   read metadata tables or platform API responses, populate
   `mmfe.production_readiness.v1`, and fail production publish when required
   source-level fields are absent.
3. Continue lakehouse hardening only where needed for production behavior:
   S3/Iceberg/Sedona/STAC execution checks should honor production gates and
   persist readiness metadata with published objects.

Key files added or materially changed in the latest slice:

- `data_agent/fusion/semantic_product_diagnostics.py`
- `data_agent/fusion/production_readiness.py`
- `data_agent/fusion/standard_sources.py`
- `data_agent/fusion/semantic_graph_trace.py`
- `data_agent/fusion/lakehouse_publisher.py`
- `data_agent/fusion/okf_exporter.py`
- `data_agent/toolsets/fusion_tools.py`
- `scripts/build_twm_mmfe_semantic_bundle.py`
- `scripts/export_twm_mmfe_okf_bundle.py`
- `data_agent/test_fusion_semantic_product_diagnostics.py`
- `data_agent/test_fusion_production_readiness.py`
- `data_agent/test_fusion_standard_sources.py`
- `data_agent/test_fusion_semantic_graph_trace.py`
- `data_agent/test_twm_mmfe_semantic_bundle.py`
- `data_agent/test_twm_mmfe_okf_export.py`
- `data_agent/test_fusion_toolset_publish_plan.py`
- `data_agent/test_fusion_lakehouse_publisher.py`
