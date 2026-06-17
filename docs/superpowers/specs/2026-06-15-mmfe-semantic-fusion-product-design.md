# MMFE Semantic Fusion Product Design

## Goal

Upgrade the Multi-Modal Fusion Engine (MMFE) from a file-level fusion tool into a semantic fusion product generator. A fusion run should still produce normal GIS data that business users can open and query, but it should also produce a structured semantic package that AI applications can use for retrieval, grounding, reasoning, and follow-up automation.

The intent is not to replace PostGIS/GeoPandas or introduce a new storage stack in this iteration. The intent is to make the existing fusion pipeline produce deeper, explicit semantic artifacts instead of only a merged GeoJSON plus a quality score.

## Foundational Principle

MMFE is a universal multimodal semantic fusion engine with geospatial-specialized
adapters. It must support semantic fusion across arbitrary data types, including
structured tables, semi-structured documents, text, images, audio, video, time
series, event logs, graphs, model inference outputs, binary/domain-specific
artifacts, and geospatial data.

Geospatial data is a critical modality family, not the boundary of MMFE. Its
special status comes from CRS, geometry, topology, spatial scale, resolution,
projection, spatial indexing, and raster/vector/point-cloud/trajectory/network/
3D transformations. These spatial constraints should be implemented as
specialized profiling, alignment, validation, execution, and publishing adapters
on top of the common semantic fusion core.

Therefore, future roadmap and implementation work should avoid treating
`vector`, `raster`, `tabular`, `point_cloud`, or `stream` as the complete
universe of MMFE data types. Those are current adapter categories. The durable
contract is semantic evidence, entity/attribute/relation/event alignment,
lineage, confidence, conflict governance, and AI-ready product generation across
all modalities.

Implementation note: the first contract-level step is to carry universal source
metadata alongside existing adapter-specific fields. `FusionSource` now supports
`modality`, `media_type`, and `adapter_family` so current geospatial adapters
and future generic adapters can share one semantic product manifest contract.
Existing `data_type` values remain for backward compatibility and strategy
selection.

## Current State

The existing MMFE implementation is concentrated in:

- `data_agent/fusion/`: modular fusion engine with profiling, compatibility, matching, alignment, execution, validation, temporal, ontology, KG, conflict, and explainability modules.
- `data_agent/fusion_engine.py`: backward-compatible proxy.
- `data_agent/toolsets/fusion_tools.py`: ADK tool layer.
- `data_agent/api/fusion_v2_routes.py`: quality, lineage, conflict, operation, and temporal preview API endpoints.
- `data_agent/standards/gis_ontology.yaml`: ontology equivalences, derivations, and inference rules.
- `data_agent/test_fusion_engine.py` and `data_agent/test_fusion_v2_*.py`: existing regression coverage.

The code already has useful pieces:

- 10 fusion strategies and PostGIS push-down.
- Field matching through exact, equivalence, ontology, LLM schema alignment, embedding, unit-aware, and fuzzy tiers.
- Temporal alignment, conflict resolution, quality validation, KG enrichment, and explainability fields.
- Data catalog registration for fusion outputs.

The main gap is that these pieces do not yet converge into a durable semantic product. In practice, output remains mostly a physical fused dataset plus optional explainability columns. Ontology derivations and inference are not part of the normal `execute_fusion()` product path, `assess_compatibility()` does not expose ontology matching, and no structured AI-ready manifest is returned by `FusionResult`.

## Design Principles

1. Keep business output first-class.
   The fused GeoJSON/GeoDataFrame must remain easy to open in QGIS, ArcGIS, PostGIS workflows, and ordinary business reporting.

2. Add semantic depth without making LLM calls mandatory.
   Ontology, deterministic derivations, field contracts, and explainability are the default foundation. LLM and embedding paths remain optional and degrade cleanly.

3. Make AI consumption explicit.
   The pipeline should emit a JSON manifest with stable keys that agent memory, RAG, pgvector, LanceDB, Iceberg, or future STAC/GeoParquet publishers can consume.

4. Preserve compatibility.
   Existing imports and existing simple `execute_fusion()` calls should keep working.

5. Avoid storage-stack churn in this iteration.
   Lance/LanceDB is a strong fit for future vector and multimodal retrieval over semantic fusion products. It should not be introduced before the semantic product contract exists.

## Proposed Architecture

Add a semantic product layer after strategy execution and conflict resolution, before the final `FusionResult` is returned.

Pipeline:

```text
profile sources
  -> assess compatibility, including optional ontology matches
  -> align CRS/units/columns
  -> execute fusion strategy
  -> resolve conflicts
  -> apply semantic enrichment
  -> inject explainability fields
  -> validate quality
  -> write business dataset
  -> write semantic product manifest
  -> register catalog asset
```

The new semantic enrichment stage produces two outputs:

- Enhanced business dataset: extra deterministic semantic fields such as derived indicators and inferred classes.
- Semantic product manifest: structured JSON describing mappings, derivations, semantic summaries, lineage, quality, and AI-ready text chunks.

## New Module

Create `data_agent/fusion/semantic_product.py`.

Responsibilities:

- Apply ontology derivations and inference rules to the fused `GeoDataFrame`.
- Build a semantic field contract from compatibility matches, source profiles, ontology metadata, and output columns.
- Build per-feature semantic summaries for a capped sample of features.
- Build AI-ready document chunks for retrieval or vectorization.
- Write a manifest JSON beside the fused output.
- Return the enhanced `GeoDataFrame` and manifest metadata to `execute_fusion()`.

Key functions:

```python
def build_semantic_fusion_product(
    output_gdf: gpd.GeoDataFrame,
    sources: list[FusionSource],
    strategy: str,
    field_matches: list[dict] | None = None,
    quality: dict | None = None,
    alignment_log: list[str] | None = None,
    temporal_log: list[str] | None = None,
    conflict_summary: dict | None = None,
    config: dict | None = None,
) -> tuple[gpd.GeoDataFrame, dict]:
    """Apply deterministic semantic enrichment and build a product manifest."""
```

```python
def write_semantic_product_manifest(
    manifest: dict,
    output_path: str,
) -> str:
    """Write manifest JSON next to the fused dataset and return its path."""
```

The manifest should be plain JSON, not a database-only artifact, so it can travel with exported datasets.

## Manifest Contract

The manifest should use stable top-level keys:

```json
{
  "product_type": "semantic_fusion_product",
  "version": "1.0",
  "business_output": {
    "path": "...",
    "format": "GeoJSON",
    "row_count": 123,
    "column_count": 18,
    "crs": "EPSG:4326"
  },
  "sources": [
    {
      "path": "...",
      "data_type": "vector",
      "row_count": 100,
      "crs": "EPSG:4326",
      "semantic_domain": null,
      "semantic_hints": []
    }
  ],
  "semantic_mappings": [
    {
      "source_field": "DLBM",
      "target_field": "land_use_code",
      "confidence": 0.85,
      "match_type": "ontology"
    }
  ],
  "derived_fields": [
    {
      "field": "building_height",
      "method": "ontology_derivation",
      "description": "Derived from floors * 3.0"
    }
  ],
  "inferred_fields": [
    {
      "field": "slope_class",
      "method": "ontology_inference"
    }
  ],
  "feature_semantics": [
    {
      "row_index": 0,
      "summary": "Parcel 1: land_use_code=0101; area=1000.0; confidence=0.8",
      "source_refs": ["source_a.geojson", "source_b.csv"],
      "quality": "high"
    }
  ],
  "ai_metadata": {
    "retrieval_text": "...",
    "chunks": [
      {
        "chunk_id": "fusion:0",
        "text": "...",
        "metadata": {
          "strategy": "spatial_join",
          "row_count": 123
        }
      }
    ],
    "embedding_ready": true,
    "recommended_vector_targets": ["pgvector", "lancedb"]
  },
  "quality": {
    "score": 0.93,
    "warnings": []
  },
  "lineage": {
    "strategy": "spatial_join",
    "alignment_steps": [],
    "temporal_alignment": [],
    "conflict_resolution": {}
  }
}
```

The `recommended_vector_targets` field is informational. MMFE exposes optional
publisher adapter contracts for vector targets such as pgvector and LanceDB,
while keeping the actual storage clients outside the fusion core.

## FusionResult Changes

Extend `FusionResult` with:

- `semantic_product_path: str = ""`
- `semantic_summary: dict = field(default_factory=dict)`
- `derived_fields: list = field(default_factory=list)`
- `inferred_fields: list = field(default_factory=list)`

These fields are additive and preserve backward compatibility.

## Execute Fusion Integration

Modify `data_agent/fusion/execution.py`.

Add optional parameter:

```python
semantic_config: Optional[dict] = None
```

Behavior:

- If `semantic_config` is omitted, keep existing behavior.
- If `semantic_config` is provided, call `build_semantic_fusion_product()`.
- If `semantic_config.get("enabled", True)` is true, apply ontology derivations and inference by default.
- If semantic enrichment fails, preserve the fused output and record a warning in `semantic_summary`.

Recommended default when called from the tool layer:

```python
semantic_config = {
    "enabled": True,
    "use_ontology": True,
    "derive_fields": True,
    "infer_fields": True,
    "feature_sample_limit": 25,
    "ai_chunks": True
}
```

## Compatibility Assessment Changes

Modify `data_agent/fusion/compatibility.py`:

```python
def assess_compatibility(
    sources: list[FusionSource],
    use_embedding: bool = False,
    use_llm_schema: bool = False,
    use_ontology: bool = False,
) -> CompatibilityReport:
```

Pass `use_ontology` into `_find_field_matches()`.

This fixes the current disconnect where ontology matching exists in `matching.py` but is not accessible through the main compatibility API.

## Tool Layer Changes

Modify `data_agent/toolsets/fusion_tools.py`.

Add optional parameter to `fuse_datasets()`:

```python
semantic_product: str = "true"
```

When true, pass `semantic_config` into `execute_fusion()`.

Return text should include:

- fused output path
- semantic product manifest path
- derived field count
- inferred field count
- quality score

Do not expose LanceDB as a required fusion parameter. A future
`publish_semantic_product()` or `index_semantic_product()` tool can route
manifests to pgvector, LanceDB, STAC, or GeoParquet through optional adapters.

## Ontology YAML Fix

Repair `data_agent/standards/gis_ontology.yaml`.

The current file contains mojibake in Chinese labels. Replace the corrupted values with valid UTF-8 while preserving English aliases and existing group IDs where possible.

Minimum coverage for this iteration:

- area: `area`, `面积`, `mj`, `zmj`, `shape_area`, `tbmj`, `AREA`
- perimeter: `perimeter`, `周长`, `shape_length`, `PERIMETER`
- land_use_code: `dlbm`, `DLBM`, `地类编码`, `用地编码`, `land_use_code`
- land_use_name: `dlmc`, `DLMC`, `地类名称`, `用地名称`, `land_use_name`
- elevation: `elevation`, `高程`, `dem`, `height`, `altitude`
- slope: `slope`, `坡度`, `gradient`, `pd`
- population: `population`, `人口`, `pop`, `rk`, `pop_count`
- floors: `floors`, `层数`, `cs`, `floor_count`, `building_floors`
- building_height: `building_height`, `建筑高度`, `jzgd`, `height_m`
- parcel_id: `parcel_id`, `地块编号`, `dkbh`, `parcel_no`, `lot_id`
- name: `name`, `名称`, `mc`, `feature_name`
- district: `district`, `区县`, `county`, `行政区`
- ndvi: `ndvi`, `NDVI`, `植被指数`, `vegetation_index`

## Lance and LanceDB Positioning

Lance/LanceDB should be treated as an optional AI indexing target, not the MMFE fusion core.

Appropriate future use cases:

- Store feature-level semantic chunks and embeddings for natural language retrieval.
- Index multimodal artifacts such as geometry summaries, text descriptions, image chips, or raster-derived feature vectors.
- Support low-latency similarity search over semantic fusion products.

Not appropriate for this iteration:

- Replacing PostGIS spatial computation.
- Replacing GeoJSON/GeoParquet business exports.
- Becoming a mandatory runtime dependency for ordinary data fusion.

MMFE emits `ai_metadata.chunks` and marks the product as `embedding_ready`.
That gives a clean handoff point for pgvector or LanceDB publisher adapters
without adding those stores to the core fusion runtime.

## Testing Strategy

Use TDD. Add focused tests before implementation.

New tests:

- `data_agent/test_fusion_semantic_product.py`
  - manifest contains stable top-level keys
  - ontology derivation adds `building_height` from `floors`
  - ontology inference adds `slope_class` from `slope`
  - AI chunks include source, strategy, quality, and representative fields
  - manifest write path is generated beside output

Modified tests:

- `data_agent/test_fusion_v2_semantic.py`
  - `assess_compatibility(..., use_ontology=True)` returns ontology match

- `data_agent/test_fusion_v2_integration.py`
  - `execute_fusion(..., semantic_config={"enabled": True})` returns `semantic_product_path`
  - output dataset includes derived semantic fields when possible

- `data_agent/test_toolsets.py` or `data_agent/test_fusion_v2_integration.py`
  - `fuse_datasets` signature includes `semantic_product`

Verification commands:

```powershell
.\.venv\Scripts\python.exe -m pytest data_agent\test_fusion_semantic_product.py -q
.\.venv\Scripts\python.exe -m pytest data_agent\test_fusion_v2_semantic.py data_agent\test_fusion_v2_integration.py -q
```

If time allows, run:

```powershell
.\.venv\Scripts\python.exe -m pytest data_agent\test_fusion_engine.py data_agent\test_fusion_v2_semantic.py data_agent\test_fusion_v2_integration.py data_agent\test_fusion_v2_explainability.py data_agent\test_fusion_v2_conflict.py -q
```

## Acceptance Criteria

1. A fusion run can produce a normal business dataset and a semantic product manifest.
2. The manifest includes source profiles, field mappings, derived fields, inferred fields, feature summaries, quality, and lineage.
3. Ontology matching is reachable through `assess_compatibility()`.
4. Ontology derivation and inference can enrich fused outputs deterministically.
5. Existing MMFE tests remain compatible.
6. Lance/LanceDB is available through an optional publisher contract, not added as a required dependency.

## Non-Goals

- No LanceDB runtime client or database connection implementation in this iteration.
- No GeoParquet publisher in this iteration.
- No new frontend visualization tab in this iteration.
- No model training or MGIM-style self-supervised representation learning.
- No broad refactor of unrelated semantic layer or NL2SQL modules.

## Risks

- Ontology derivation formulas can be brittle if aliases are incomplete.
  Mitigation: deterministic tests for supported formulas and graceful skip when required fields are absent.

- Manifest can become too large on large fusion outputs.
  Mitigation: cap `feature_semantics` and AI chunks with `feature_sample_limit`.

- Existing tests may rely on old default behavior.
  Mitigation: semantic product generation is opt-in at `execute_fusion()` and enabled by the tool layer only through an explicit default parameter.

- Chinese ontology labels may need domain review.
  Mitigation: keep common aliases conservative and preserve English aliases.

## Implementation Notes

Implemented in:

- `data_agent/fusion/models.py`
- `data_agent/fusion/profiling.py`
- `data_agent/fusion/semantic_product.py`
- `data_agent/fusion/execution.py`
- `data_agent/fusion/compatibility.py`
- `data_agent/toolsets/fusion_tools.py`
- `data_agent/standards/gis_ontology.yaml`

The semantic fusion product is opt-in at the engine layer through
`semantic_config` and enabled by default at the FusionToolset layer through
`semantic_product="true"`. The generated business output is still a normal GIS
dataset, while the sidecar `.semantic.json` manifest carries semantic mappings,
derived fields, inferred fields, lineage, quality, feature summaries, and
embedding-ready AI chunks.

Manifest v1.1 adds an explicit schema contract through
`SEMANTIC_PRODUCT_SCHEMA` and `validate_semantic_product_manifest()`. Each
manifest now carries a stable `product_id` and `field_contracts` section. Field
contracts describe field role, dtype, null ratio, source mappings, lineage, and
value profiles. Numeric fields include min/max/mean; categorical fields include
unique counts and capped sample values. This gives both business users and AI
retrieval/indexing layers a stronger contract than raw column names.

Semantic mappings also carry deterministic alignment evidence. Each mapping can
include source/target field profiles, confidence bands, matcher evidence,
ontology group evidence, dtype compatibility, value-statistics availability, and
a compact explanation string. This keeps the first semantic-alignment
improvement local and testable while leaving a clear extension point for later
document-context and LLM schema-alignment evidence.

Semantic mappings now also carry an `alignment_score` decision record. The
current deterministic scorer combines matcher confidence, dtype compatibility,
value-profile support, and ontology support into a normalized score with
`accept` / `review` / `reject` decisions. AI metadata summarizes these decisions
so downstream RAG or vector-indexing jobs can prefer accepted mappings and route
review/reject mappings to human or LLM-assisted validation.

The alignment scorer has been extracted to
`data_agent/fusion/semantic_alignment.py` and re-exported from both
`data_agent.fusion` and `data_agent.fusion_engine`. This keeps
`semantic_product.py` focused on building the fusion product while making the
same scoring contract reusable by later document-context evidence, LLM schema
alignment evidence, and indexing quality gates.

Document-context evidence is now part of the semantic alignment path.
`fuse_datasets()` accepts a `document_context` JSON string, typically the output
from `inject_document_context()`, and forwards it through `semantic_config`.
`semantic_product.py` indexes `source_metadata[].field_definitions` from data
dictionaries or business documents and emits `document_context` evidence when a
definition links the source and target fields. The scoring module treats this as
an additive support signal, so ordinary fusion runs are not penalized when no
document context is available.

Non-accepted mappings now produce actionable semantic review items.
`build_alignment_review_items()` turns `review` and `reject` decisions into a
compact checklist with severity, reason codes, evidence summaries, and suggested
actions. The manifest exposes this through `ai_metadata.alignment_review`, and
`FusionResult.semantic_summary` includes the review item count and whether human
review is required. This turns semantic alignment quality from a passive score
into a business/AI governance workflow input.

Raster source profiling now emits evidence-backed `semantic_hints` and a
source-level `semantic_domain` for common raster products. The current
deterministic rule set covers NDVI/vegetation index, DEM/elevation, slope, and
land-cover classification signals. Evidence comes from filename tokens, band
descriptions, band tags, and conservative value-range checks where useful. The
hints are carried into `manifest.sources[].semantic_hints`, so downstream
business review, RAG chunking, or future vector indexing can see why a raster
band was treated as NDVI, elevation, slope, or land-cover class. These hints are
metadata evidence, not an irreversible classification step.

Point-cloud profiling now emits LAS dimension-level semantic evidence when
`laspy` can read the source. MMFE keeps the old optional-dependency fallback
when `laspy` is unavailable, but a readable LAS/LAZ profile can now expose
classification, intensity, return number/count, RGB color, scan angle, XYZ
statistics, ASPRS classification counts, source-level `semantic_domain="lidar"`,
and `semantic_hints` for classified, intensity-bearing, and colorized lidar.
The reader accepts both context-manager style objects and ordinary `LasData`
objects returned by `laspy.read()`.

Point-cloud profiling now also carries a metadata/capability layer. Readable LAS
headers contribute `stats["las_metadata"]` with VLR/EVLR counts and compact
record summaries, including `user_id`, `record_id`, description, and
record-data byte size. These records often carry CRS, GeoTIFF keys, waveform
metadata, processing lineage, or vendor-specific context, so MMFE emits
`point_cloud_metadata` hints instead of treating them as opaque bytes. For
`.laz` sources, MMFE records `stats["laz"]` with compressed/readable/backend
status. When no LAZ backend is available, profiling preserves the point-cloud
source type and emits `laz_backend_unavailable` capability evidence rather than
silently dropping the limitation.

Large point-cloud profiling now also emits `stats["chunking"]`. The plan uses
the existing large-dataset point threshold as a recommended chunk size and marks
chunking required when point count or file size crosses configured thresholds.
The plan records point count, file size when available, chunk size, estimated
chunk count, last chunk size, strategy, and trigger reasons. MMFE also emits a
`point_cloud_processing` hint with `value="chunking_required"` so future PDAL
pipelines, model runners, vector indexing jobs, and UI review workflows can
route large sources to streaming execution. This is still a planning contract;
it does not stream points, write chunk files, or run inference over chunks.

PDAL integration now has a dependency-free planning contract. The
`data_agent/fusion/pdal_pipeline.py` module builds `mmfe.pdal_pipeline.v1`
documents that combine point-cloud source path, LAZ status, chunking plan,
optional filter stages, writer options, and output path into a PDAL JSON
pipeline. The same module validates reader/writer stages and writes `.pdal.json`
plans beside intended outputs. MMFE still treats PDAL as an external execution
tool: the contract is ready for a future runner, but this iteration does not
invoke PDAL, install PDAL, or materialize point chunks.

PDAL execution now also has a runner contract. `build_pdal_runner_spec()` turns
a planned pipeline into an `mmfe.pdal_runner.v1` job with the command
`pdal pipeline <spec_path>`, expected output path, timeout, task, and chunking
metadata. `run_pdal_pipeline()` accepts an injectable executor, validates the
process return code and expected output creation, and returns structured
stdout/stderr/error evidence. This enables local subprocess runners, remote job
dispatchers, or test mocks to share one contract while keeping PDAL optional in
MMFE core.

Point-cloud chunk artifact planning now has its own manifest contract.
`build_point_cloud_chunk_artifact_manifest()` turns a profiling
`stats["chunking"]` plan into an `mmfe.point_cloud_chunks.v1` document with
source metadata, artifact directory, output format, per-chunk point offsets,
planned point counts, artifact paths, status, and semantic processing hints.
`write_point_cloud_chunk_artifact_manifest()` writes the manifest as
`manifest.chunks.json` in the artifact directory. MMFE now also has
`materialize_point_cloud_chunk_artifacts()`, a runner contract that executes an
injected writer per planned chunk, verifies that each artifact path was created,
records file size, materialization metadata, per-chunk success/failure status,
and writes the updated manifest back to disk. The default core still does not
split LAS/LAZ bytes by itself; real chunk materialization must come from a
laspy, PDAL, container, remote job, or test writer supplied by the caller.

Raster profiling now carries pixel-value semantics instead of stopping at
filename and band-description hints. For each readable band, MMFE captures
`nodata`, `scale`, `offset`, and `unit` from raster metadata or tags, and emits
scaled statistics when scale/offset metadata is present. Nearby sidecar metadata
files such as `.stac.json`, `.metadata.json`, or `.json` are parsed without
adding new dependencies. STAC-like sidecars contribute evidence for platform,
instrument, `eo:bands`, and `raster:bands`, including per-band scale, offset,
nodata, and unit metadata. These hints remain evidence in the source profile and
semantic manifest; they do not force a physical pixel transformation or replace
future CRS-aware raster feature extraction.

Raster profiling now also emits CRS-aware grid semantics. The source profile
records raster width/height, pixel width/height, CRS unit, whether the CRS is
geographic or projected, and metric pixel area only when the CRS is projected.
For geographic CRS rasters, MMFE emits an explicit
`requires_projection_for_area` warning so downstream business logic and AI
agents do not treat degree-based pixels as square metres. This closes the first
CRS-aware pixel-semantics gap without adding automatic reprojection or zonal
aggregation behavior.

Raster sidecar parsing now handles a broader metadata evidence layer. STAC JSON
sidecars contribute collection, datetime, title/description, keywords, GSD, and
`proj:epsg` in addition to platform, instrument, `eo:bands`, and
`raster:bands`. ISO 19115-style XML sidecars are parsed with the Python standard
library for common title, abstract, keywords, topic category, date stamp, and
lineage statements. These text fields also participate in deterministic raster
theme inference, so a product can be recognized from authoritative metadata even
when the filename and band description are weak. This is intentionally a
conservative core-field parser, not a complete ISO metadata engine.

Raster profiling now derives lightweight feature-chip summaries for AI-facing
inspection without writing chip image files. MMFE samples a deterministic center
window, records per-band min/max/mean/std, carries scaled statistics when
scale/offset metadata is available, and summarizes dominant values for
low-cardinality classification rasters. The same summaries emit
`raster_feature_chip` semantic hints marked as embedding-ready evidence. This
creates a future handoff point for actual chip export, vision embeddings, or
LanceDB indexing while keeping the current runtime dependency-free.

MMFE now distinguishes deterministic semantic evidence from AI model inference.
Metadata, band tags, CRS/grid facts, feature-chip summaries, and LAS dimensions
are deterministic source-profile evidence. Labels such as cropland, forest,
tree, or building generally require a trained image or point-cloud model unless
they are already present in authoritative metadata/classification dimensions.
For that higher semantic layer, MMFE can ingest sidecar model outputs such as
`.ai.json`, normalize each observation as a `model_inference` semantic hint, and
preserve model name, version, task, confidence, target, domain, and evidence.
This keeps the fusion engine honest: it can fuse and govern AI-derived semantics
without pretending that metadata/statistics alone performed visual recognition.

Third-party AI integration is now represented by a small sidecar contract module
instead of direct model dependencies. `data_agent/fusion/ai_semantics.py`
publishes a model catalog for external tools such as Prithvi EO, TerraMind,
SAM2+GroundingDINO, RandLA-Net, and Pointcept/PTv3, and provides helpers to
build, validate, and write `.ai.json` sidecars. This makes the integration
boundary explicit: model runners produce normalized observations, while MMFE
profiles, validates, fuses, and publishes those observations as semantic
evidence.

The same contract module now also defines an external runner wrapper contract.
`build_ai_semantic_runner_spec()` creates an `mmfe.ai_runner.v1` job document
with model id, model task, source path, expected `.ai.json` output path,
rendered command arguments, model version, and runner parameters.
`validate_ai_semantic_runner_spec()` checks the job document before dispatch,
including task/model compatibility against the model catalog.
`run_ai_semantic_runner()` executes the rendered command through an injectable
executor, captures stdout/stderr/return code, checks the expected output file,
and validates the produced sidecar with the normal AI semantic sidecar contract.
`validate_ai_semantic_runner_output()` remains available for runners executed
outside the current process. This keeps MMFE responsible for orchestration and
evidence governance, while Prithvi, SAM, Pointcept, PDAL/container pipelines,
or customer models remain independent third-party tools.

Semantic product publishing now has a dependency-free vector-index contract.
`build_semantic_vector_publish_spec()` converts `ai_metadata.chunks` into
`mmfe.semantic_vector_publish.v1` records with stable record ids, chunk text,
product metadata, target store, collection name, and embedding model metadata.
`embed_semantic_vector_records()` executes an injected embedding adapter and
adds vectors, embedding model, and dimension metadata to the records before
publishing. `run_semantic_vector_publish()` executes an injected publisher
adapter for targets such as `pgvector` or `lancedb` and returns structured
publish results. `build_pgvector_publisher()` and `build_lancedb_publisher()`
provide backend adapter contracts: they validate embedded records and build pure
payloads for injected executors, without opening database connections
themselves.
MMFE still does not add pgvector, LanceDB, embedding generation, or database
drivers as required runtime dependencies; those remain backend adapters behind
the publisher contract.
For pgvector, embedding dimension is a table-column contract, not just record
metadata: a table created as `vector(768)` cannot accept 16-dimensional smoke
vectors, and a `vector(16)` smoke table cannot accept real 768-dimensional
model embeddings. Production deployments should isolate pgvector tables by
embedding model or dimension, or recreate the table during controlled
migrations.

MMFE now treats storage as a dual-lake architecture. S3-backed Iceberg tables
are the authoritative analytical geospatial lakehouse for governed business
outputs, SQL analytics, and spatial engines such as Apache Sedona.
Lance/LanceDB is the AI-native multimodal lakehouse for semantic chunks,
embeddings, model outputs, image chips, point-cloud feature vectors, and
retrieval/training views. The two layers are linked through stable product ids,
source paths, table identifiers, snapshot metadata, and lineage in the semantic
manifest; LanceDB records should reference authoritative Iceberg/S3 assets
instead of becoming a second source of truth for business data.

Analytical lakehouse publishing now has a dependency-free Iceberg contract.
`build_iceberg_publish_spec()` converts a semantic product manifest into
`mmfe.iceberg_publish.v1` with catalog, namespace, table, S3 warehouse URI,
business output path, CRS, row count, lineage, quality, partition hints, and
the intended spatial compute engine such as `sedona`. `run_iceberg_publish()`
executes an injected publisher adapter, while `build_iceberg_publisher()` builds
a pure executor payload without importing Spark, Iceberg, Sedona, pyiceberg, or
S3 clients. This keeps Iceberg/Sedona production wiring outside MMFE core while
making the authoritative analytical lakehouse boundary explicit.
Successful Iceberg publish results also return a `manifest_patch` containing
`lakehouse.iceberg`, including the table identity and backend-reported snapshot
or partition metadata when available. `apply_iceberg_manifest_patch()` merges
that patch into a copy of the semantic product manifest without mutating the
original, giving callers a clean handoff from analytical lakehouse publishing to
AI vector publishing.

Sedona-on-Iceberg spatial execution now has a dependency-free runner contract.
`build_sedona_iceberg_runner_spec()` creates `mmfe.sedona_iceberg_runner.v1`
jobs that describe the task, Iceberg catalog, S3 warehouse URI, input table
identifiers, output table, SQL, Spark configuration, and metadata.
`run_sedona_iceberg_job()` validates the job and executes an injected executor,
then normalizes return code, stdout/stderr, rows written, and snapshot id. MMFE
does not import Spark, Sedona, Iceberg, or S3 clients; those remain production
adapters behind the runner contract.

Vector publishing now preserves that boundary in AI retrieval records. When a
semantic product manifest includes `lakehouse.iceberg`, the semantic vector
publisher copies a normalized `authoritative_lakehouse` reference into
`source_manifest` and every chunk record's metadata before embedding or
LanceDB/pgvector publishing. The reference carries Iceberg table identity,
S3-backed business output path, optional snapshot id, partition metadata, and
the spatial engine. This makes LanceDB and pgvector retrieval records point back
to authoritative Iceberg/S3 assets instead of becoming separate business-data
authorities.

Geospatial discovery publishing now has a dependency-free STAC catalog
contract. `build_stac_publish_spec()` converts a semantic product manifest into
`mmfe.stac_publish.v1`, including a STAC Item-shaped payload with collection,
datetime, bbox/geometry when supplied, business output asset, CRS EPSG metadata,
quality score, lineage, and an authoritative Iceberg/S3 lakehouse reference
when present. `run_stac_publish()` executes an injected publisher adapter, and
`build_stac_publisher()` builds a pure executor payload for static STAC writers,
STAC API clients, object-store writers, or platform catalog services. MMFE does
not import `pystac`, STAC API clients, or object-store SDKs in core. STAC is a
discovery/catalog layer: it should help users and services find published
products, while Iceberg/S3 remains the authoritative analytical asset and
LanceDB/pgvector remain optional AI retrieval/indexing targets.

Semantic product publishing now also has a small orchestration contract.
`publish_semantic_product()` routes one semantic product manifest through
requested targets such as `iceberg`, `stac`, `pgvector`, or `lancedb` using the
existing dependency-free target contracts and injected publishers. The same
production readiness gate used by dry-run planning is now enforced before any
backend adapter is called: production publishing requires
`production_ready=true`, while validation/development publishing can flow with
`validation_ready=true` and preserved production-gap warnings. The same runtime
orchestration also runs the lakehouse infrastructure preflight before backend
execution and returns the preflight report alongside the gate result. When
Iceberg publishing succeeds, the orchestration applies the returned manifest
patch before running STAC or vector publishing, so catalog items and AI
retrieval rows refer to the authoritative Iceberg/S3 table, snapshot, and
business output. A gate failure, infrastructure preflight failure, or target
failure returns structured errors and stops dependent targets instead of
silently publishing inconsistent downstream records. This is the backend-neutral
foundation for a future `publish_semantic_product()` tool or API route; it still
does not import Spark, Iceberg, STAC, pgvector, LanceDB, embedding, or
object-store clients in MMFE core.

Production-readiness metadata is now a first-class MMFE contract rather than a
free-text warning. `mmfe.production_readiness.v1` records source-level
authority, authority level, license/access rights, update date, lineage, CRS,
scale or resolution, official standard version, security classification, and
synthetic/not-for-production flags. `diagnose_semantic_product_readiness()`
consumes that contract through `production_metadata_contract`: production
metadata must be present and complete before the broader `production_authority`
check can pass. The TWM validation bundle emits
`twm_mmfe_production_readiness.json`, publishes it as a STAC asset, embeds the
summary in the semantic product, and intentionally marks the current validation
sources as blocked for production so operators can see exactly which metadata
must be replaced by authoritative release records.

Enriched standard-source registries now feed the same production-readiness
contract. `standard_source_production_metadata_from_registry()` maps archived
and extracted official standards into `standard_source` metadata rows with
archive URI, checksum, access rights, citation-anchor counts, extraction status,
and production blocking flags. The TWM bundle appends those rows to
`twm_mmfe_production_readiness.json`, so standard-source ingestion completion is
visible in the same gate that checks authoritative data-source metadata.
`production_readiness_from_manifest()` now derives this contract from
`mmfe_bundle.source_production_metadata`, source metadata records, and
`mmfe_bundle.standard_source_registry`, deduplicating explicit rows and registry
rows. `source_production_metadata_from_records()` turns authoritative metadata
tables or platform API responses into the same source metadata rows without
binding MMFE core to a database, platform service, or network client.

The same layer now exposes a publish-plan dry run contract.
`build_semantic_product_publish_plan()` builds the Iceberg, STAC, pgvector, or
LanceDB target specs without executing any publisher, embedder, database, Spark
job, or object-store write. The plan records target order, dependency edges
such as STAC/vector publishing depending on Iceberg lineage, target validation
errors, and whether required publishers or embedders have been configured. This
gives operators and future tool/API routes a cheap preflight check before
launching production publishing jobs.

Publish planning now includes an infrastructure preflight contract.
`mmfe.infrastructure_preflight.v1` checks the lakehouse object-store endpoint,
bucket and URI shape, Iceberg warehouse/table identity, STAC catalog location,
Spark S3A settings, credential presence, and production-environment risk such
as local MinIO endpoints or local default credentials. It also checks
cross-component consistency so the object-store warehouse URI, Iceberg
warehouse URI, lakehouse bucket, STAC catalog URI, Spark S3A endpoint, Spark
credentials, path-style access flag, and SSL flag do not silently point to
different lakehouse locations or incompatible runtime settings. For the simple
S3A credentials provider, Spark access and secret keys must be configured. The
preflight report redacts secret values in its sanitized config.
It also emits a stable SHA-256 `config_fingerprint` over non-secret lakehouse
configuration material so operators can compare publish plans, runtime publish
results, and direct agent preflight checks without exposing access keys or
secret keys.
`build_semantic_product_publish_plan()` adds this as an
`infrastructure_preflight` step after the production gate, and
`publish_semantic_product()` enforces the same preflight before any injected
backend publisher is called. Production runs with local MinIO endpoints, local
default credentials, missing Spark S3A credentials, or inconsistent lakehouse
wiring fail at the preflight layer; validation and development runs can continue
with warnings for local smoke testing.

The infrastructure preflight is also exposed directly through the ADK
FusionToolset as `preflight_mmfe_lakehouse_infrastructure()`. The tool accepts a
full config JSON or environment-variable override JSON, returns the sanitized
`mmfe.infrastructure_preflight.v1` contract plus compact errors and warnings,
and never performs object-store, Spark, database, or network work. The dry-run
publish plan is exposed through `plan_semantic_product_publish()`. That tool
accepts either an inline semantic product manifest JSON string or a manifest
path, plus Iceberg/STAC/vector target configuration and adapter-configured
flags. When a caller overrides the Iceberg warehouse URI while using environment
defaults, the tool normalizes the derived lakehouse bucket and default STAC
catalog URI to that explicit warehouse bucket before running preflight. It
returns structured JSON with `status`, a compact summary, target specs,
dependency edges, validation errors, and backend readiness without
executing any publish, embedding, Spark, database, or object-store operation.
This makes the dual-lake publication preflight reachable from agent workflows
while keeping real backend adapters optional and external to MMFE core.

MMFE now carries universal modality metadata through the source profile and
semantic product manifest. `FusionSource` includes additive `modality`,
`media_type`, and `adapter_family` fields. Current profiling adapters populate
them for geospatial vector, geospatial raster, point-cloud, and structured table
sources, while manually constructed sources can represent generic document,
text, image, audio, video, graph, event, or model-output modalities. This keeps
the existing geospatial strategies stable while moving the public semantic
contract toward the broader "universal multimodal semantic fusion engine with
geospatial-specialized adapters" principle.

MMFE now also has a lightweight generic multimodal profiling path. Extension
detection recognizes documents, images, audio, video, graph files, AI/model
output sidecars, and unknown binary artifacts instead of forcing every unknown
source through the tabular adapter. The generic profiler records file-level
metadata, modality, media type, adapter family, a minimal logical column, and a
`generic_modality` semantic hint. This is intentionally shallow: it does not yet
extract PDF text, image embeddings, audio transcripts, video keyframes, full
graph structure, or domain-specific binary semantics. Those are future
modality-specific adapters built on top of the same `FusionSource` and semantic
product contract.

Direct AI/model-output profiling now reads `.ai.json`, `.model.json`, and
`.inference.json` files as first-class generic sources. When those files contain
`observations` or `semantic_observations`, MMFE records model name, version,
task, and observation count in `stats["model_output"]`, then reuses the existing
AI semantic sidecar normalization to emit `model_inference` semantic hints. This
does not run models or validate task-specific output quality; it brings
model-produced semantics into the same evidence layer used by geospatial
sources, documents, and future multimodal adapters.

Text and Markdown document profiling now extracts lightweight document evidence
without new parser dependencies. For UTF-8 `.txt`, `.md`, `.markdown`, and
`.rst` files, MMFE records title, line counts, word count, and a capped content
preview in `stats["document"]`, then emits `document_title` and conservative
`document_keyword` semantic hints for common governance/project terms. This is
not full document understanding and does not cover PDF/DOCX extraction yet; it
creates the first deterministic text-document evidence layer for semantic
fusion, retrieval, and later entity/relation extraction.

GraphML profiling now extracts a shallow topology layer without adding graph
runtime dependencies. For `.graphml` files, MMFE parses XML with the standard
library, records graph count, node count, edge count, and directed/undirected
status when `edgedefault` is present in `stats["graph"]`, then emits a
`graph_topology` semantic hint. This is a graph-source evidence contract, not a
full graph database, RDF reasoner, network-analysis engine, or topology
materializer.

Derived raster asset publishing now has a validated geospatial multimodal path
over the TWM validation dataset. Sedona-on-Spark reads the real Sentinel-2 NDVI
GeoTIFF, transforms TWM project polygons from EPSG:4326 to EPSG:32648, computes
project-level NDVI zonal relations, clips project-level NDVI rasters with
`RS_Clip`, writes GeoTIFF assets to the MinIO lakehouse through S3A, and
publishes STAC discovery items for those derived raster artifacts. A host-side
optional raster publishing smoke then rewrites the Sedona-derived clips as
Cloud-Optimized GeoTIFFs with rasterio, validates COG layout, tiling, CRS, and
shape/type preservation, uploads the `.cog.tif` assets to MinIO, verifies
read-back checksums, and registers a separate STAC collection with the `cog`
asset role. The same adapter can publish a static STAC root `catalog.json` and
collection `collection.json` to object storage, linking the derived COG STAC
items through standard `rel=item` links. This is static catalog indexing, not a
full STAC API or concurrent catalog governance service. MMFE core remains
dependency-free: Spark/Sedona/S3A, boto3, and rasterio stay adapter/runtime
concerns rather than imports required by the semantic product contract.

GeoParquet lakehouse materialization is validated at the optional S3 adapter
boundary. `scripts/smoke_mmfe_minio_materialize.py --include-geoparquet`
generates a minimal GeoParquet artifact with GeoPandas/PyArrow, uploads it to
the MMFE curated MinIO prefix, marks the object as
`application/vnd.apache.parquet`, and verifies read-back SHA-256. This confirms
object-store transport and media-type handling for GeoParquet assets; production
GeoParquet generation, partitioning, and catalog governance remain separate
publisher/runtime responsibilities.

Standard-grounded semantic field alignment is now part of MMFE core. The
alignment module can turn role contracts, standard field catalogs, Chinese field
aliases, value-domain references, and TWM semantic binding keys into
JSON-compatible alignment decisions without importing GeoPandas, Spark, S3,
vector databases, or raster runtimes. Each field alignment now carries the
resolved standard field, match type, confidence, `accept` / `review` / `reject`
decision, evidence list, standard reference, optional TWM semantic key, and
whether human review is required. This moves MMFE beyond name-based matching:
the semantic basis is explicit and auditable.

The TWM validation bundle now consumes this standard-grounded alignment path.
`twm_mmfe_field_semantics.csv` includes alignment score, decision, evidence JSON,
standard reference JSON, value-domain code, and value-domain loading status.
`twm_mmfe_semantic_product.json` carries an `alignment_summary` under
`mmfe_bundle`, and the TWM state input contract exposes alignment decision
counts for the state builder. Current fixture output contains 274 field-level
semantic mappings: 120 accepted, 154 routed to review, and 0 rejected. Required
and recommended TWM role-contract fields such as `parcel_current.DLBM`,
`synthetic_projects.YDMJ`, `synthetic_projects.ZYGDMJ`, and
`synthetic_projects.SJSTHXMJ` are accepted with standard/role/binding evidence,
while fields only present in the broad catalog but not backed by a role contract
remain review items.

Value-domain readiness is intentionally separated from field semantic binding.
For example, `DLBM` can be accepted as the TWM `land_use_code` field because the
role contract, alias, standard catalog, and TWM binding agree. MMFE now also has
a value-domain audit path: `build_value_domain_catalog()`,
`audit_field_value_domain()`, and `build_value_domain_audit_summary()` normalize
domain items and check observed field values against the referenced domain. The
TWM bundle emits `twm_mmfe_value_domain_audit.csv`, carries
`value_domain_audit_summary` in the semantic product, exposes the audit summary
in `twm_state_input.json`, publishes it as a STAC asset, and exports an OKF
`standards/value_domain_audit.md` concept.

The current engineering fixture now loads a validation-domain version of
`gb_t_21010_2017_land_use_code` plus ownership, ecological-redline, planning,
urban-boundary, and yes/no domains. The value-domain audit currently covers 6
field/domain pairs, all valid, including `parcel_current.DLBM` with 4,900
observed values, 19 distinct land-use codes, 0 unknown values, and 100%
coverage. This closes the value-level semantic loop for the demo scaffold.
It still does not claim to be the authoritative production GB/T 21010-2017 value
domain: production deployments must replace the validation domain items with
the standards-platform or government-source value-domain release.

OKF export now exposes the same alignment evidence in field concept documents:
field docs include the resolved standard field, alignment score, alignment
decision, review flag, value-domain status, and evidence JSON. This makes the
semantic fusion product usable both as a machine contract and as a human/agent
review artifact.

Remaining hard-core MMFE work is now narrower and clearer:

- enrich the semantic ontology package with production standards-platform
  releases, extracted clauses, data elements, and authoritative value domains;
- convert spatial and multimodal relations such as project-parcel overlap,
  project-PBF conflict, project-planning-zone conflict, and project-NDVI
  evidence into first-class semantic graph edges with confidence, metric,
  source asset, and rule/standard references;
- replace validation value-domain items with authoritative standards-platform
  value-domain releases, especially for `gb_t_21010_2017_land_use_code`, so
  demo-valid value coverage becomes production-valid value coverage;
- harden the future TWM state builder implementation that consumes
  `twm_state_input.json` and dereferences raw sources through role/binding
  contracts, instead of hard-coding demo file names or raw column names.

The first spatial/multimodal semantic relation layer is now implemented for the
TWM validation bundle. Existing `relations/*.csv` spatial and evidence bridge
tables are normalized into `twm_mmfe_semantic_relations.csv` with stable
semantic relation types, source/target object types, source/target object ids,
Chinese predicates, business meaning, TWM usage, rule ids, optimization
objective ids, metric names/values, overlap ratios, confidence, semantic
strength, evidence source, and review flags. The current fixture emits 728
semantic relations:

- 354 `project_overlaps_parcel` relations for project-state impact building;
- 39 `project_overlaps_permanent_basic_farmland` relations for the
  `pbf_overlap_m2` hard constraint and `TWM-FARM-001`;
- 28 `project_overlaps_ecological_redline` relations for the `eco_overlap_m2`
  hard constraint and `TWM-ECO-001`;
- 151 `project_overlaps_planning_zone` relations for planning consistency and
  `planning_conflict_m2`;
- 7 `project_overlaps_urban_development_boundary` relations for urban-boundary
  consistency;
- 71 `project_observed_by_remote_sensing_tile` relations for multimodal remote
  sensing evidence;
- 78 `annual_change_of_parcel` relations for dynamic state transitions.

These relations are now part of the semantic product, the TWM state input
contract, the STAC asset list, the AI chunk set, the OKF sidecar, and the
lightweight semantic graph. The graph now materializes relation nodes and edges
that connect object ids to rules, objectives, and evidence context. This is a
meaningful MMFE step because TWM no longer has to infer semantics directly from
raw relation CSV filenames or column names: the relation layer explicitly tells
TWM whether a metric is a hard constraint, a planning-consistency signal, a
remote-sensing evidence bridge, or a dynamic-transition relation.

The first TWM downstream state-input handoff is now implemented without turning
MMFE into the TWM model itself. `data_agent/fusion/twm_state_input.py` builds
`mmfe.twm_state_input.v1` artifacts from the semantic product, the relation
table, and the state-input contract. The generated `twm_state_input.json`
contains source product metadata, role registries, canonical object-type
registries, field-binding registries, relation registries, state components,
standard readiness, AI grounding metadata, production-use warnings, and
optimization objective bindings. For the current TWM fixture it records 9 object
roles, 728 semantic relations, 67 hard-constraint relations, 71 remote-sensing
evidence relations, 78 dynamic-transition relations, and 13 optimization
objective bindings. The hard-constraint component links `pbf_overlap_m2` and
`eco_overlap_m2` to `TWM-FARM-001` and `TWM-ECO-001`; planning, urban-boundary,
remote-sensing, and annual-change components are kept as separate state
components.

This state-input artifact is the concrete MMFE-to-TWM interface: raw vector and
raster files remain the source of truth for geometry and attributes, while MMFE
supplies the semantics, standard bindings, relation meanings, rule references,
evidence hooks, and optimization objective bindings. It deliberately does not
run TWM dynamic projection, Pareto search, DRL/MPC, or policy decisions. Those
remain downstream TWM or paper-validation responsibilities.

The standard-source evidence chain is now explicit. `data_agent/fusion/
standard_sources.py` builds an auditable registry from the TWM role-contract
`source_documents`, and the bundle emits `twm_mmfe_standard_sources.csv`,
`mmfe_bundle.standard_source_registry`, a `fusion:standard-sources` AI chunk,
a STAC `standard_sources` asset, TWM `standard_readiness.standard_sources`, and
an OKF `standards/source_registry.md` concept.

The registry now has an execution-facing acquisition contract:
`mmfe.standard_source_ingestion_plan.v1`. The plan turns each registered
standard source into an auditable task with official URL/search URL, retrieval
status, required actions, download/checksum requirements, full-text extraction
status, and blocking reasons such as `official_source_missing`,
`checksum_missing`, `fulltext_extraction_missing`, or `production_gap`. The TWM
bundle emits `twm_mmfe_standard_source_ingestion_plan.json`, publishes it as a
STAC asset, embeds it in `mmfe_bundle`, and surfaces the readiness summary in
diagnostics/README. This is still a plan contract, not a network downloader or
PDF parser; it gives the production ingestion job a stable checklist and gives
the publish gate a machine-readable reason why standard-source evidence is not
production-ready.

The same standard-source layer now has a dependency-free runner surface:
`mmfe.standard_source_ingestion_run.v1`. `run_standard_source_ingestion_plan()`
executes ingestion tasks through injected `fetcher`, `archiver`, and `extractor`
adapters, returning per-task archive URI, SHA-256 checksum, extraction status,
and citation-anchor counts. Without injected adapters it returns structured
errors instead of attempting network or PDF work in MMFE core. This establishes
the production job boundary: platform-specific download, object-store archive,
and PDF/DOCX extraction implementations can plug into a stable MMFE contract.

The first concrete standard-source adapter path is now implemented for local
and offline production rehearsal. `build_local_standard_source_fetcher()` reads
task-local or identifier-mapped source files, `build_local_standard_source_archiver()`
writes archived bytes with SHA-256 checksums and stable archive URIs, and
`build_local_standard_source_extractor()` emits
`mmfe.standard_source_citation_anchors.v1` JSON sidecars from UTF-8-readable
text/CSV/JSON source material and dependency-free `.docx` files parsed through
the OOXML `word/document.xml` package. The sidecar records task id, standard
identifier, archive URI, source path, checksum, extraction status, extraction
method, and normalized citation anchors. Binary PDF and legacy `.doc`
extraction plus official network download policy remain external adapter
responsibilities.

The standard-source fetch/archive path can now cover authorized official HTTP
retrieval and S3-compatible persistence when explicitly injected.
`build_http_standard_source_fetcher()` reads an official or download URL through
`urllib`, supports an allowlist of official domains, records HTTP status,
content type, byte count, source URL, and SHA-256 checksum, and can be tested
with an injected opener without real network calls. `build_s3_standard_source_archiver()`
wraps `archive_standard_source_bytes_to_s3()`, imports `boto3` only when the
adapter runs, writes to a configured `s3://...` prefix, records bucket/key,
endpoint, content type, byte count, SHA-256 checksum, and returns the archive
URI to the same `mmfe.standard_source_ingestion_run.v1` result. This closes the
first official-fetch/object-store persistence adapter path while keeping
download authorization policy and PDF/legacy-DOC extraction outside MMFE core.

Successful ingestion runs can now be folded back into the auditable registry.
`apply_standard_source_ingestion_run()` copies successful task evidence into
matching registry entries: archive URI, local path, checksum, byte counts,
`downloaded_fulltext` retrieval status, `archived_fulltext` access mode,
extraction status, citation-anchor counts, sidecar schema/path, and extraction
method. Rebuilding `mmfe.standard_source_ingestion_plan.v1` from the enriched
registry turns completed sources from blocked tasks into ready tasks, while
failed task results are ignored so they cannot pollute source evidence.

For the current fixture the registry contains 7 standard sources. `GB/T
21010-2017 土地利用现状分类` has been verified against the official National
Standard Full Text Disclosure System entry
`https://openstd.samr.gov.cn/bzgk/gb/newGbInfo?hcno=224BF9DA69F053DA22AC758AAAADEEAA`.
The official page records standard number `GB/T 21010-2017`, Chinese name
`土地利用现状分类`, English name `Current land use classification`, status `现行`,
CCS `A76`, ICS `07.040`, publication date `2017-11-01`, implementation date
`2017-11-01`,主管/归口部门 `自然资源部（国土）`, and exposes online preview and
download actions. The registry therefore marks it as
`official_fulltext_available` with `online_preview_and_download` access.

The six natural-resource One Map database-architecture documents from the
local expert package remain marked as `local_expert_material_available`. They
are useful engineering scaffolds for MMFE semantic contracts, but not yet
production-grade authoritative source evidence. Production MMFE/TWM deployment
must replace or enrich these entries with official release URLs, formal version
identifiers, downloaded/archived full texts where permitted, and extracted
clause/data-element/value-domain evidence in the standards platform.

The semantic graph now consumes that standard-source registry instead of
leaving it as sidecar metadata. `twm_mmfe_semantic_graph.json` materializes
`standard_source` nodes for the 7 registered sources and `value_domain` nodes
for the loaded value domains. Field nodes with standard value domains now emit
`uses_value_domain` edges, roles emit `supported_by_standard_source` edges, and
`gb_t_21010_2017_land_use_code` emits `grounded_by_standard_source` to the
official `GB/T 21010-2017` node. The current graph has 1,424 nodes and 3,547
edges, including 7 standard-source nodes, 7 value-domain nodes, 6
field-to-value-domain edges, and the GB/T 21010-2017 value-domain grounding
edge. This is a concrete step from "field mapping table" toward a traversable
MMFE ontology surface: an agent can now walk from `parcel_current.DLBM` to its
land-use value domain, then to the official standard source that grounds that
domain.

The first graph-consumption layer is also implemented. `data_agent/fusion/
semantic_graph_trace.py` indexes the MMFE semantic graph and builds compact
trace cards for selected fields, value domains, standards, rules, and
objectives. The TWM bundle now emits `twm_mmfe_semantic_trace_cards.json`,
includes it in `business_outputs`, publishes it as a STAC asset, carries it in
`mmfe_bundle.semantic_trace_cards`, and exports an OKF
`graphs/semantic_trace_cards.md` concept. The current bundle creates 14 trace
cards. The `field:parcel_current.DLBM` trace card contains the path
`地类编码 -> gb_t_21010_2017_land_use_code -> 土地利用现状分类`, with relationships
`uses_value_domain` and `grounded_by_standard_source`. This gives downstream
agents a stable way to answer "why does this field mean this?" without scanning
the entire graph or raw sidecar tables.

MMFE now also emits a compact semantic ontology package independent of heavy
geospatial runtimes. `data_agent/fusion/semantic_ontology.py` builds
`mmfe.semantic_ontology.v1` from a semantic product plus optional sidecars:
field semantics, value-domain audits, standard-source rows, semantic relations,
and TWM state input. The package normalizes standard roles, object types,
fields, TWM semantic keys, value domains, standard sources, relation types,
rules, and optimization objectives into stable concept arrays plus explicit
concept relationships. `build_mmfe_semantic_ontology()` exposes this through
the FusionToolset and writes `mmfe_semantic_ontology.json` beside a TWM semantic
product by default. The TWM bundle builder now emits
`twm_mmfe_semantic_ontology.json`, records it in `business_outputs`, carries its
summary under `mmfe_bundle.semantic_ontology_summary`, publishes it as a STAC
`semantic_ontology` asset, and exports it as the OKF
`graphs/semantic_ontology.md` concept. For the current TWM fixture, the package
records 9 standard roles, 6 object types, 274 fields, 14 semantic keys, 6
audited value domains, 7 standard sources, 7 relation types, 7 rules, 13
optimization objectives, and 2,319 concept relationships. This closes the
earlier gap between field-level standard alignment and a machine-consumable
ontology surface; it still depends on validation-domain items and local One Map
standard-package evidence until production standards-platform releases replace
those scaffold inputs.
