"""
Multi-modal Data Fusion Engine — intelligent fusion of heterogeneous data sources.

This package refactors the monolithic fusion_engine.py into focused modules:
  - models.py:        Data structures (FusionSource, CompatibilityReport, FusionResult)
  - constants.py:     Strategy matrix, unit tables, thresholds
  - io.py:            Large dataset detection, chunked I/O
  - raster_utils.py:  Raster reprojection and resampling
  - profiling.py:     Source profiling (vector/raster/tabular/point_cloud)
  - matching.py:      4-tier semantic field matching + embedding
  - compatibility.py: Compatibility assessment
  - alignment.py:     Source alignment (CRS, units, column conflicts)
  - execution.py:     Fusion execution, strategy selection, multi-source orchestration
  - validation.py:    10-point quality validation
  - db.py:            Database recording
  - llm_routing.py:   LLM strategy routing (deprecated, re-exports from execution)
  - strategies/:      10 strategy implementations + registry
"""

# --- Models ---
from .models import FusionSource, CompatibilityReport, FusionResult

# --- Constants ---
from .constants import (
    STRATEGY_MATRIX,
    UNIT_CONVERSIONS,
    UNIT_PATTERNS,
    T_FUSION_OPS,
    LARGE_ROW_THRESHOLD,
    LARGE_FILE_MB,
)

# --- I/O ---
from .io import (
    _is_large_dataset,
    _read_vector_chunked,
    _read_tabular_lazy,
    _materialize_df,
)

# --- Raster utilities ---
from .raster_utils import _reproject_raster, _resample_raster_to_match

# --- Profiling ---
from .profiling import (
    profile_source,
    _detect_data_type,
    _profile_vector,
    _profile_raster,
    _profile_tabular,
    _profile_point_cloud,
    profile_postgis_source,
)

# --- Matching ---
from .matching import (
    _embedding_cache,
    _get_embeddings,
    _cosine_similarity,
    _catalog_equiv_cache,
    _get_equiv_groups,
    _load_catalog_equiv_groups,
    _tokenize_field_name,
    _tokenized_similarity,
    _types_compatible,
    _detect_unit,
    _strip_unit_suffix,
    _find_field_matches,
)

# --- Compatibility ---
from .compatibility import assess_compatibility, _compute_spatial_overlap

# --- Alignment ---
from .alignment import (
    align_sources,
    _apply_unit_conversions,
    _convert_column_units,
    _resolve_column_conflicts,
)

# --- Execution (includes _llm_select_strategy for shared-globals patching) ---
from .execution import (
    execute_fusion,
    _auto_select_strategy,
    _score_strategies,
    _orchestrate_multisource,
    _llm_select_strategy,
)

# --- Strategies ---
from .strategies import (
    _STRATEGY_REGISTRY,
    _extract_geodataframe,
    _fuse_large_datasets_spatial,
    _auto_detect_join_column,
    _strategy_spatial_join,
    _strategy_overlay,
    _strategy_nearest_join,
    _strategy_attribute_join,
    _strategy_zonal_statistics,
    _strategy_point_sampling,
    _strategy_band_stack,
    _strategy_time_snapshot,
    _strategy_height_assign,
    _strategy_raster_vectorize,
)

# --- Validation ---
from .validation import validate_quality

# --- Database ---
from .db import ensure_fusion_tables, record_operation

# --- Schema alignment (LLM-based, opt-in) ---
from .schema_alignment import llm_align_schemas

# --- Explainability (v2) ---
from .explainability import (
    add_explainability_fields,
    generate_quality_heatmap,
    generate_lineage_trace,
    explain_decision,
    COL_CONFIDENCE,
    COL_SOURCES,
    COL_CONFLICTS,
    COL_METHOD,
)

# --- Temporal Alignment (v2) ---
from .temporal import TemporalAligner

# --- Ontology Reasoning (v2) ---
from .ontology import OntologyReasoner

# --- Semantic Fusion Product ---
from .semantic_product import (
    DEFAULT_SEMANTIC_PRODUCT_CONFIG,
    SEMANTIC_PRODUCT_SCHEMA,
    SEMANTIC_PRODUCT_VERSION,
    build_semantic_fusion_product,
    validate_semantic_product_manifest,
    write_semantic_product_manifest,
)

# --- Semantic Alignment Scoring ---
from .semantic_alignment import (
    DEFAULT_ALIGNMENT_SCORING_WEIGHTS,
    alignment_decision,
    build_alignment_review_items,
    build_alignment_summary,
    score_semantic_alignment,
)

# --- Semantic Vector Publisher Contracts ---
from .semantic_publisher import (
    SEMANTIC_VECTOR_PUBLISH_SCHEMA,
    build_lancedb_publisher,
    build_pgvector_publisher,
    build_semantic_vector_publish_spec,
    embed_semantic_vector_records,
    run_semantic_vector_publish,
    validate_semantic_vector_publish_spec,
)

# --- Analytical Lakehouse Publisher Contracts ---
from .lakehouse_publisher import (
    ICEBERG_PUBLISH_SCHEMA,
    apply_iceberg_manifest_patch,
    build_iceberg_publish_spec,
    build_iceberg_publisher,
    run_iceberg_publish,
    validate_iceberg_publish_spec,
)

# --- AI Semantic Sidecar Contracts ---
from .ai_semantics import (
    AI_SEMANTIC_RUNNER_SCHEMA,
    AI_SEMANTIC_SIDECAR_SCHEMA,
    build_ai_semantic_runner_spec,
    build_ai_semantic_sidecar,
    get_ai_semantic_model_catalog,
    run_ai_semantic_runner,
    validate_ai_semantic_runner_output,
    validate_ai_semantic_runner_spec,
    validate_ai_semantic_sidecar,
    write_ai_semantic_sidecar,
)

# --- PDAL Pipeline Contracts ---
from .pdal_pipeline import (
    PDAL_PIPELINE_SCHEMA,
    PDAL_RUNNER_SCHEMA,
    POINT_CLOUD_CHUNK_ARTIFACT_SCHEMA,
    build_pdal_pipeline_spec,
    build_pdal_runner_spec,
    build_point_cloud_chunk_artifact_manifest,
    materialize_point_cloud_chunk_artifacts,
    run_pdal_pipeline,
    validate_pdal_pipeline_spec,
    validate_pdal_runner_spec,
    validate_point_cloud_chunk_artifact_manifest,
    write_pdal_pipeline_spec,
    write_point_cloud_chunk_artifact_manifest,
)

# --- LLM Semantic Understanding (v2) ---
from .semantic_llm import SemanticLLM

# --- Knowledge Graph Integration (v2) ---
from .kg_integration import KGIntegration

# --- Conflict Resolution (v2) ---
from .conflict_resolver import ConflictResolver
