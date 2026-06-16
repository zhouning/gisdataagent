"""Backward-compatible proxy — all code now lives in data_agent.fusion/ package.

This module re-exports every public and private symbol so that existing imports
(``from data_agent.fusion_engine import X``) and module-attribute access
(``fusion_engine.profile_source(…)``) continue to work unchanged.

For mock.patch compatibility, patch targets that reference symbols used inside
sub-module functions must use the sub-module path instead:
  - ``data_agent.fusion.db.get_engine``          (was fusion_engine.get_engine)
  - ``data_agent.fusion.db.current_user_id``     (was fusion_engine.current_user_id)
  - ``data_agent.fusion.execution._llm_select_strategy``
  - ``data_agent.fusion.matching._get_embeddings``
"""

# Re-export everything from the fusion package
from data_agent.fusion import *  # noqa: F401,F403

# Explicitly import underscore-prefixed names (not covered by import *)
from data_agent.fusion import (  # noqa: F401
    _is_large_dataset,
    _read_vector_chunked,
    _read_tabular_lazy,
    _materialize_df,
    _reproject_raster,
    _resample_raster_to_match,
    _detect_data_type,
    _profile_vector,
    _profile_raster,
    _profile_tabular,
    _profile_point_cloud,
    _embedding_cache,
    _get_embeddings,
    _cosine_similarity,
    _get_equiv_groups,
    _load_catalog_equiv_groups,
    _catalog_equiv_cache,
    _tokenize_field_name,
    _tokenized_similarity,
    _types_compatible,
    _detect_unit,
    _strip_unit_suffix,
    _find_field_matches,
    _compute_spatial_overlap,
    _apply_unit_conversions,
    _convert_column_units,
    _resolve_column_conflicts,
    _auto_select_strategy,
    _score_strategies,
    _orchestrate_multisource,
    _llm_select_strategy,
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
    DEFAULT_SEMANTIC_PRODUCT_CONFIG,
    SEMANTIC_PRODUCT_SCHEMA,
    SEMANTIC_PRODUCT_VERSION,
    build_semantic_fusion_product,
    validate_semantic_product_manifest,
    write_semantic_product_manifest,
    DEFAULT_ALIGNMENT_SCORING_WEIGHTS,
    alignment_decision,
    build_alignment_review_items,
    build_alignment_summary,
    score_semantic_alignment,
    SEMANTIC_VECTOR_PUBLISH_SCHEMA,
    build_lancedb_publisher,
    build_pgvector_publisher,
    build_semantic_vector_publish_spec,
    embed_semantic_vector_records,
    run_semantic_vector_publish,
    validate_semantic_vector_publish_spec,
    ICEBERG_PUBLISH_SCHEMA,
    SEDONA_ICEBERG_RUNNER_SCHEMA,
    STAC_PUBLISH_SCHEMA,
    apply_iceberg_manifest_patch,
    build_iceberg_publish_spec,
    build_iceberg_publisher,
    build_sedona_iceberg_runner_spec,
    build_stac_publish_spec,
    build_stac_publisher,
    run_iceberg_publish,
    run_sedona_iceberg_job,
    run_stac_publish,
    validate_iceberg_publish_spec,
    validate_sedona_iceberg_runner_spec,
    validate_stac_publish_spec,
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

# Patch-target shims: these symbols were previously in fusion_engine.py's globals
# and some tests patch them here. Import them so they exist as module attributes.
from data_agent.db_engine import get_engine  # noqa: F401
from data_agent.user_context import current_user_id  # noqa: F401
