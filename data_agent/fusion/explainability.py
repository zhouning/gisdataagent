"""Fusion v2.0 — Explainability module.

Per-feature metadata injection, quality heatmap generation,
lineage tracing, and natural language decision explanation.
"""
import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Optional

import geopandas as gpd

logger = logging.getLogger(__name__)

# Standard explainability column names (convention for all v2 modules)
COL_CONFIDENCE = "_fusion_confidence"
COL_SOURCES = "_fusion_sources"
COL_CONFLICTS = "_fusion_conflicts"
COL_METHOD = "_fusion_method"


def add_explainability_fields(
    gdf: gpd.GeoDataFrame,
    fusion_metadata: dict,
) -> gpd.GeoDataFrame:
    """Inject per-feature explainability columns into a fused GeoDataFrame.

    Args:
        gdf: Fused result GeoDataFrame.
        fusion_metadata: Dict with keys: strategy, sources (list[str]).

    Returns:
        The same GeoDataFrame with added/updated explainability columns.
    """
    if gdf.empty:
        return gdf

    strategy = fusion_metadata.get("strategy", "unknown")
    sources = fusion_metadata.get("sources", [])
    source_basenames = [os.path.basename(s) for s in sources]
    sources_json = json.dumps(source_basenames, ensure_ascii=False)

    # _fusion_confidence: default 1.0 — conflict resolver will override later
    if COL_CONFIDENCE not in gdf.columns:
        gdf[COL_CONFIDENCE] = 1.0

    # _fusion_sources: JSON array of source file basenames
    if COL_SOURCES not in gdf.columns:
        gdf[COL_SOURCES] = sources_json

    # _fusion_conflicts: empty JSON for now — conflict resolver will populate
    if COL_CONFLICTS not in gdf.columns:
        gdf[COL_CONFLICTS] = "{}"

    # _fusion_method: strategy name
    if COL_METHOD not in gdf.columns:
        gdf[COL_METHOD] = strategy

    return gdf


def generate_quality_heatmap(
    gdf: gpd.GeoDataFrame,
    output_dir: str,
) -> str:
    """Generate a simplified GeoJSON with confidence-based quality classification.

    Bins features into low (<0.3), medium (0.3-0.7), high (>0.7) quality levels.
    For large datasets (>100K features), simplifies geometries.

    Args:
        gdf: GeoDataFrame with _fusion_confidence column.
        output_dir: Directory to write the heatmap GeoJSON.

    Returns:
        Output file path, or "" on failure.
    """
    if gdf.empty or COL_CONFIDENCE not in gdf.columns:
        logger.warning("Cannot generate quality heatmap: empty or missing confidence column")
        return ""

    try:
        # Classify confidence levels
        heatmap_gdf = gdf[[COL_CONFIDENCE, "geometry"]].copy()
        heatmap_gdf["_quality_level"] = heatmap_gdf[COL_CONFIDENCE].apply(_classify_quality)

        # Simplify large datasets
        if len(heatmap_gdf) > 100_000:
            heatmap_gdf["geometry"] = heatmap_gdf.geometry.simplify(
                tolerance=0.0001, preserve_topology=True
            )

        # Compute summary stats
        counts = heatmap_gdf["_quality_level"].value_counts().to_dict()
        avg_confidence = round(float(heatmap_gdf[COL_CONFIDENCE].mean()), 4)

        # Write output
        from ..gis_processors import _generate_output_path
        output_path = _generate_output_path("fusion_quality_heatmap", "geojson")
        heatmap_gdf.to_file(output_path, driver="GeoJSON")

        logger.info(
            "Quality heatmap generated: %d features, avg_confidence=%.4f, levels=%s",
            len(heatmap_gdf), avg_confidence, counts,
        )
        return output_path

    except Exception as e:
        logger.warning("Failed to generate quality heatmap: %s", e)
        return ""


def generate_lineage_trace(
    sources: list,
    strategy: str,
    alignment_log: list[str],
    row_count: int,
    duration_s: float,
    temporal_log: Optional[list] = None,
    conflict_summary: Optional[dict] = None,
) -> dict:
    """Build a structured lineage trace for a fusion operation.

    Args:
        sources: List of FusionSource objects or file path strings.
        strategy: Fusion strategy used.
        alignment_log: Alignment/transformation steps.
        row_count: Output row count.
        duration_s: Execution duration in seconds.
        temporal_log: Optional temporal alignment steps.
        conflict_summary: Optional conflict resolution summary.

    Returns:
        Structured lineage dict.
    """
    source_info = []
    for s in sources:
        if hasattr(s, "file_path"):
            source_info.append({
                "file": os.path.basename(s.file_path),
                "type": getattr(s, "data_type", "unknown"),
                "rows": getattr(s, "row_count", 0),
                "crs": getattr(s, "crs", None),
            })
        else:
            source_info.append({"file": str(s)})

    trace = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "sources": source_info,
        "strategy": strategy,
        "alignment_steps": alignment_log,
        "output_rows": row_count,
        "duration_s": duration_s,
    }

    if temporal_log:
        trace["temporal_alignment"] = temporal_log
    if conflict_summary:
        trace["conflict_resolution"] = conflict_summary

    return trace


def explain_decision(row_data: dict) -> str:
    """Generate a natural language explanation of a fusion decision for one feature.

    Uses template-based generation (no LLM required).

    Args:
        row_data: Dict with explainability columns for a single feature.

    Returns:
        Human-readable explanation string.
    """
    confidence = row_data.get(COL_CONFIDENCE, 1.0)
    sources = row_data.get(COL_SOURCES, "[]")
    method = row_data.get(COL_METHOD, "unknown")
    conflicts = row_data.get(COL_CONFLICTS, "{}")

    # Parse JSON strings if needed
    if isinstance(sources, str):
        try:
            sources = json.loads(sources)
        except (json.JSONDecodeError, TypeError):
            sources = [sources]

    if isinstance(conflicts, str):
        try:
            conflicts = json.loads(conflicts)
        except (json.JSONDecodeError, TypeError):
            conflicts = {}

    source_list = "、".join(sources) if sources else "未知来源"
    quality_label = _classify_quality(confidence)

    parts = [
        f"该要素由 {source_list} 融合生成，使用 {method} 策略。",
        f"置信度: {confidence:.2f} ({quality_label})。",
    ]

    if conflicts:
        conflict_count = len(conflicts) if isinstance(conflicts, dict) else 0
        if conflict_count > 0:
            parts.append(f"存在 {conflict_count} 个属性冲突，已按规则解决。")

    return " ".join(parts)


def _classify_quality(confidence: float) -> str:
    """Classify confidence into quality level."""
    if confidence < 0.3:
        return "low"
    elif confidence < 0.7:
        return "medium"
    return "high"
