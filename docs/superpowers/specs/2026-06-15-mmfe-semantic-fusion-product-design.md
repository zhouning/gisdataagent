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
   The pipeline should emit a JSON manifest with stable keys that agent memory, RAG, pgvector, LanceDB, or future STAC/GeoParquet publishers can consume.

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

The `recommended_vector_targets` field is informational. This iteration does not implement LanceDB writing. It makes the intended AI storage boundary explicit.

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

Do not expose LanceDB as a required parameter yet. A future `publish_semantic_product()` or `index_semantic_product()` tool can route manifests to pgvector, LanceDB, STAC, or GeoParquet.

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

This iteration should emit `ai_metadata.chunks` and mark the product as `embedding_ready`. That gives a clean handoff point for pgvector or LanceDB later.

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
6. Lance/LanceDB is documented as a future AI indexing target, not added as a required dependency.

## Non-Goals

- No new LanceDB implementation in this iteration.
- No STAC or GeoParquet publisher in this iteration.
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
`manifest.chunks.json` in the artifact directory. This is still a planning and
audit artifact: MMFE records exactly what chunk files should be materialized,
but it does not yet stream LAS/LAZ points, write physical chunk files, or
schedule per-chunk PDAL/model jobs.

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
`validate_ai_semantic_runner_output()` reads the expected sidecar after an
external runner finishes and validates it with the normal AI semantic sidecar
contract. This keeps MMFE responsible for orchestration and evidence governance,
while Prithvi, SAM, Pointcept, PDAL/container pipelines, or customer models
remain independent third-party tools.

LanceDB remains a future indexing target in this iteration. MMFE emits
`ai_metadata.chunks` and recommends `pgvector`/`lancedb` as downstream vector
stores, but it does not add LanceDB as a required runtime dependency.
