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
    _EMBEDDING_MODEL,
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

# --- LLM Semantic Understanding (v2) ---
from .semantic_llm import SemanticLLM

# --- Knowledge Graph Integration (v2) ---
from .kg_integration import KGIntegration

# --- Conflict Resolution (v2) ---
from .conflict_resolver import ConflictResolver
