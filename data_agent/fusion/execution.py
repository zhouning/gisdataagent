"""Fusion execution — strategy selection, multi-source orchestration."""
import json
import logging
import os
import time
from typing import Optional

import geopandas as gpd

from .models import FusionSource, CompatibilityReport, FusionResult
from .constants import STRATEGY_MATRIX
from .compatibility import _compute_spatial_overlap
from .validation import validate_quality
from .strategies import _STRATEGY_REGISTRY, _extract_geodataframe
from ..gis_processors import _generate_output_path

logger = logging.getLogger(__name__)


def execute_fusion(
    aligned_data: list[tuple[str, object]],
    strategy: str,
    sources: list[FusionSource],
    params: Optional[dict] = None,
    report: CompatibilityReport | None = None,
    user_hint: str = "",
) -> FusionResult:
    """Execute a fusion strategy on aligned data.

    Args:
        aligned_data: List of (data_type, data_object) tuples from align_sources.
        strategy: Fusion strategy name ('auto', 'llm_auto', or specific strategy).
        sources: Original source profiles (for provenance).
        params: Strategy-specific parameters (join_column, spatial_predicate, etc.).
        report: Compatibility report (used by LLM routing).
        user_hint: User intent description (used by LLM routing).

    Returns:
        FusionResult with output path and quality metrics.
    """
    params = params or {}
    start = time.time()

    # v7.1: llm_auto deprecated — downgrade to rule-based auto
    if strategy == "llm_auto":
        logger.warning("strategy='llm_auto' is deprecated; falling back to 'auto' (rule-based)")
        strategy = "auto"
    if strategy == "auto":
        strategy = _auto_select_strategy(
            aligned_data, sources,
            report=report, user_hint=user_hint,
        )

    strategy_fn = _STRATEGY_REGISTRY.get(strategy)
    if not strategy_fn:
        raise ValueError(f"Unknown fusion strategy: {strategy}. "
                         f"Available: {list(_STRATEGY_REGISTRY.keys())}")

    # v5.6: Multi-source orchestration for N>2 inputs
    if len(aligned_data) > 2:
        return _orchestrate_multisource(aligned_data, strategy, sources, params)

    # v7.1: PostGIS push-down for large datasets
    from .strategies.postgis_pushdown import _should_pushdown, has_postgis_equivalent, execute_pushdown
    if (_should_pushdown(sources) and has_postgis_equivalent(strategy)):
        try:
            output_gdf, alignment_log = execute_pushdown(strategy, sources, params)
            logger.info("PostGIS push-down executed for strategy=%s", strategy)
        except Exception as e:
            logger.warning("PostGIS push-down failed (%s), falling back to Python", e)
            output_gdf, alignment_log = strategy_fn(aligned_data, params)
    else:
        output_gdf, alignment_log = strategy_fn(aligned_data, params)

    # Save output
    output_path = _generate_output_path("fused", "geojson")
    output_gdf.to_file(output_path, driver="GeoJSON")

    duration = round(time.time() - start, 2)

    # Quality validation
    quality = validate_quality(output_gdf, sources)

    return FusionResult(
        output_path=output_path,
        strategy_used=strategy,
        row_count=len(output_gdf),
        column_count=len([c for c in output_gdf.columns if c != "geometry"]),
        quality_score=quality["score"],
        quality_warnings=quality["warnings"],
        alignment_log=alignment_log,
        duration_s=duration,
        provenance={
            "sources": [s.file_path for s in sources],
            "strategy": strategy,
            "params": params,
        },
    )


def _auto_select_strategy(
    aligned_data: list[tuple[str, object]],
    sources: list[FusionSource],
    report: CompatibilityReport | None = None,
    user_hint: str = "",
    use_llm: bool = False,
) -> str:
    """Automatically select the best fusion strategy based on data characteristics.

    v7.1: LLM routing removed (use_llm parameter kept for API compat, ignored).
    v5.6: Data-aware scoring (MGIM-inspired context-aware reasoning). Considers:
      - Spatial overlap IoU (prefer nearest_join when low)
      - Geometry type compatibility (point vs polygon)
      - Data volume ratio
      - User hint keywords
    """
    if use_llm:
        logger.warning("use_llm=True is deprecated; using rule-based scoring")

    if len(aligned_data) < 2:
        raise ValueError("Need at least 2 data sources for fusion.")

    type_pair = (aligned_data[0][0], aligned_data[1][0])
    strategies = STRATEGY_MATRIX.get(type_pair, [])
    if not strategies:
        type_pair_rev = (aligned_data[1][0], aligned_data[0][0])
        strategies = STRATEGY_MATRIX.get(type_pair_rev, [])

    if not strategies:
        raise ValueError(f"No strategy available for {type_pair[0]} + {type_pair[1]}")

    if len(strategies) == 1:
        return strategies[0]

    # Rule-based scoring with user hint support
    return _score_strategies(strategies, aligned_data, sources, user_hint=user_hint)


def _score_strategies(
    candidates: list[str],
    aligned_data: list[tuple[str, object]],
    sources: list[FusionSource],
    user_hint: str = "",
) -> str:
    """Score candidate strategies and return the best one.

    Scoring heuristics:
      - spatial_join: prefers high IoU + polygon geometry
      - nearest_join: prefers low IoU or point geometry
      - overlay: prefers polygon × polygon with moderate overlap
      - point_sampling: prefers point vector + raster
      - zonal_statistics: prefers polygon vector + raster
      - user_hint: keyword boost (e.g., "nearest" → nearest_join +0.5)
    """
    scores = {}
    iou = _compute_spatial_overlap(sources) if len(sources) >= 2 else 0.0
    geom_types = [s.geometry_type for s in sources if s.geometry_type]
    has_point = any("point" in (g or "").lower() for g in geom_types)
    has_polygon = any("polygon" in (g or "").lower() for g in geom_types)
    row_ratio = 1.0
    if len(sources) >= 2 and sources[0].row_count > 0 and sources[1].row_count > 0:
        row_ratio = min(sources[0].row_count, sources[1].row_count) / \
                    max(sources[0].row_count, sources[1].row_count)

    # User hint keyword → strategy boost mapping
    hint_lower = user_hint.lower() if user_hint else ""
    hint_keywords = {
        "nearest": "nearest_join",
        "最近": "nearest_join",
        "邻近": "nearest_join",
        "overlay": "overlay",
        "叠加": "overlay",
        "union": "overlay",
        "join": "spatial_join",
        "连接": "spatial_join",
        "attribute": "attribute_join",
        "属性": "attribute_join",
        "zonal": "zonal_statistics",
        "分区": "zonal_statistics",
        "sample": "point_sampling",
        "采样": "point_sampling",
    }

    for strategy in candidates:
        score = 1.0  # base score

        if strategy == "spatial_join":
            score += 0.3 if iou > 0.1 else -0.2
            score += 0.2 if has_polygon else 0.0
            score += 0.1 if row_ratio > 0.3 else -0.1

        elif strategy == "nearest_join":
            score += 0.3 if iou < 0.1 else -0.1
            score += 0.2 if has_point else 0.0

        elif strategy == "overlay":
            score += 0.2 if has_polygon else -0.3
            score += 0.1 if 0.05 < iou < 0.8 else -0.1

        elif strategy == "zonal_statistics":
            score += 0.3 if has_polygon else -0.2

        elif strategy == "point_sampling":
            score += 0.3 if has_point else -0.2

        # User hint boost
        for keyword, target in hint_keywords.items():
            if keyword in hint_lower and target == strategy:
                score += 0.5
                break

        scores[strategy] = round(score, 2)

    return max(scores, key=scores.get)


def _orchestrate_multisource(
    aligned_data: list[tuple[str, object]],
    strategy: str,
    sources: list[FusionSource],
    params: dict,
) -> FusionResult:
    """Orchestrate fusion of N>2 sources via pairwise decomposition.

    Fuses sources progressively: (s0 + s1) -> intermediate -> (intermediate + s2) -> ...
    Selects optimal pairing order: vector sources first, then raster, then tabular.
    """
    start = time.time()
    all_log = []

    # Sort by priority: vector first (accumulates geometry), then others
    type_priority = {"vector": 0, "raster": 1, "tabular": 2, "point_cloud": 3, "stream": 4}
    indexed = list(enumerate(aligned_data))
    indexed.sort(key=lambda x: type_priority.get(x[1][0], 9))
    ordered_data = [item for _, item in indexed]
    ordered_sources = [sources[i] for i, _ in indexed]

    # Pairwise fusion: accumulate into the first result
    current_data = ordered_data[0]
    current_source = ordered_sources[0]

    for i in range(1, len(ordered_data)):
        pair = [current_data, ordered_data[i]]
        pair_sources = [current_source, ordered_sources[i]]

        # Select strategy for this pair
        pair_strategy = strategy
        if pair_strategy == "auto" or pair_strategy not in _STRATEGY_REGISTRY:
            pair_strategy = _auto_select_strategy(pair, pair_sources)

        strategy_fn = _STRATEGY_REGISTRY.get(pair_strategy)
        if not strategy_fn:
            all_log.append(f"Skipping source {i}: no strategy for pair")
            continue

        result_gdf, step_log = strategy_fn(pair, params)
        all_log.extend(step_log)
        all_log.append(f"Step {i}/{len(ordered_data)-1}: "
                       f"{pair[0][0]}+{pair[1][0]} via {pair_strategy} → {len(result_gdf)} rows")

        # Update current for next iteration
        current_data = ("vector", result_gdf)
        current_source = FusionSource(
            file_path="<intermediate>",
            data_type="vector",
            row_count=len(result_gdf),
            columns=[{"name": c, "dtype": str(result_gdf[c].dtype), "null_pct": 0}
                     for c in result_gdf.columns if c != "geometry"],
        )

    # Final output
    final_gdf = current_data[1]
    if not isinstance(final_gdf, gpd.GeoDataFrame):
        raise ValueError("Multi-source fusion did not produce a GeoDataFrame.")

    output_path = _generate_output_path("fused_multi", "geojson")
    final_gdf.to_file(output_path, driver="GeoJSON")

    duration = round(time.time() - start, 2)
    quality = validate_quality(final_gdf, sources)

    return FusionResult(
        output_path=output_path,
        strategy_used=f"multi_source({strategy})",
        row_count=len(final_gdf),
        column_count=len([c for c in final_gdf.columns if c != "geometry"]),
        quality_score=quality["score"],
        quality_warnings=quality["warnings"],
        alignment_log=all_log,
        duration_s=duration,
        provenance={
            "sources": [s.file_path for s in sources],
            "strategy": strategy,
            "params": params,
            "steps": len(ordered_data) - 1,
        },
    )


# ---------------------------------------------------------------------------
# LLM Strategy Routing (DEPRECATED — use rule-based scoring instead)
# ---------------------------------------------------------------------------

def _llm_select_strategy(
    candidates: list[str],
    sources: list[FusionSource],
    report: CompatibilityReport | None = None,
    user_hint: str = "",
) -> tuple[str, str]:
    """Use Gemini to reason about the best fusion strategy.

    Returns (selected_strategy, reasoning) or ("", "") on failure.
    """
    source_info = json.dumps([{
        "file": os.path.basename(s.file_path),
        "type": s.data_type,
        "rows": s.row_count,
        "geometry": s.geometry_type,
        "columns": len(s.columns),
    } for s in sources], ensure_ascii=False, indent=2)

    report_info = ""
    if report:
        report_info = (
            f"CRS兼容: {report.crs_compatible}\n"
            f"空间重叠IoU: {report.spatial_overlap_iou}\n"
            f"字段匹配数: {len(report.field_matches)}\n"
            f"总体评分: {report.overall_score}"
        )

    prompt = (
        "你是多模态数据融合专家。根据数据源特征和兼容性报告，"
        "从候选策略中选择最佳融合策略并给出简短理由。\n\n"
        f"数据源:\n{source_info}\n\n"
        f"兼容性报告:\n{report_info}\n\n"
        f"候选策略: {candidates}\n"
        + (f"用户意图: {user_hint}\n" if user_hint else "")
        + '\n请返回JSON: {"strategy": "策略名", "reasoning": "理由"}\n'
        "只返回JSON。"
    )

    try:
        from google import genai
        client = genai.Client()
        response = client.models.generate_content(
            model="gemini-2.0-flash",
            contents=prompt,
        )
        text = response.text.strip()
        # Strip markdown code fence if present
        if text.startswith("```"):
            text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
        result = json.loads(text)
        strategy = result.get("strategy", "")
        reasoning = result.get("reasoning", "")
        if strategy in candidates:
            return strategy, reasoning
        logger.warning("LLM suggested '%s' not in candidates %s", strategy, candidates)
    except Exception as e:
        logger.warning("LLM strategy routing failed: %s", e)

    return "", ""
