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
    _EMBEDDING_MODEL,
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
)

# Patch-target shims: these symbols were previously in fusion_engine.py's globals
# and some tests patch them here. Import them so they exist as module attributes.
from data_agent.db_engine import get_engine  # noqa: F401
from data_agent.user_context import current_user_id  # noqa: F401
