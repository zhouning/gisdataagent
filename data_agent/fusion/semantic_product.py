"""Semantic fusion product builder for MMFE.

This module converts a physical fused GeoDataFrame into a portable semantic
product: enriched business columns plus an AI-ready JSON manifest.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any

import geopandas as gpd
import pandas as pd

from .explainability import COL_CONFIDENCE, _classify_quality
from .models import FusionSource


DEFAULT_SEMANTIC_PRODUCT_CONFIG = {
    "enabled": True,
    "use_ontology": True,
    "derive_fields": True,
    "infer_fields": True,
    "feature_sample_limit": 25,
    "ai_chunks": True,
}


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
    cfg = {**DEFAULT_SEMANTIC_PRODUCT_CONFIG, **(config or {})}
    enriched = output_gdf.copy()
    semantic_warnings: list[str] = []
    derived_fields: list[dict[str, Any]] = []
    inferred_fields: list[dict[str, Any]] = []

    if cfg.get("enabled", True) and cfg.get("use_ontology", True):
        try:
            from .ontology import OntologyReasoner

            reasoner = OntologyReasoner()
            if reasoner.is_loaded and cfg.get("derive_fields", True):
                enriched = _add_canonical_semantic_fields(enriched)
                enriched, derived = reasoner.derive_missing_fields(enriched)
                derived_fields = [
                    {
                        "field": field,
                        "method": "ontology_derivation",
                        "description": _derivation_description(reasoner, field),
                    }
                    for field in derived
                ]
            if reasoner.is_loaded and cfg.get("infer_fields", True):
                enriched, inferred = reasoner.apply_inference_rules(enriched)
                inferred_fields = [
                    {"field": field, "method": "ontology_inference"}
                    for field in inferred
                ]
        except Exception as exc:
            semantic_warnings.append(f"semantic enrichment failed: {exc}")

    quality = quality or {"score": None, "warnings": []}
    feature_semantics = _build_feature_semantics(
        enriched,
        sources,
        sample_limit=int(cfg.get("feature_sample_limit", 25)),
    )
    ai_metadata = _build_ai_metadata(
        enriched,
        sources,
        strategy,
        quality,
        feature_semantics,
        enabled=bool(cfg.get("ai_chunks", True)),
    )

    manifest = {
        "product_type": "semantic_fusion_product",
        "version": "1.0",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "business_output": {
            "path": "",
            "format": "GeoJSON",
            "row_count": int(len(enriched)),
            "column_count": len([c for c in enriched.columns if c != "geometry"]),
            "crs": str(enriched.crs) if getattr(enriched, "crs", None) else None,
        },
        "sources": [_source_manifest(source) for source in sources],
        "semantic_mappings": _normalize_field_matches(field_matches or []),
        "derived_fields": derived_fields,
        "inferred_fields": inferred_fields,
        "feature_semantics": feature_semantics,
        "ai_metadata": ai_metadata,
        "quality": {
            "score": quality.get("score"),
            "warnings": list(quality.get("warnings", [])) + semantic_warnings,
        },
        "lineage": {
            "strategy": strategy,
            "alignment_steps": alignment_log or [],
            "temporal_alignment": temporal_log or [],
            "conflict_resolution": conflict_summary or {},
        },
    }
    return enriched, manifest


def write_semantic_product_manifest(manifest: dict, output_path: str) -> str:
    """Write manifest JSON next to the fused dataset and return its path."""
    root, _ = os.path.splitext(output_path)
    manifest_path = f"{root}.semantic.json"
    manifest_to_write = dict(manifest)
    business_output = dict(manifest_to_write.get("business_output", {}))
    business_output["path"] = output_path
    manifest_to_write["business_output"] = business_output
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(
            manifest_to_write,
            f,
            ensure_ascii=False,
            indent=2,
            default=_json_default,
        )
    return manifest_path


def _source_manifest(source: FusionSource) -> dict:
    return {
        "path": source.file_path,
        "data_type": source.data_type,
        "row_count": int(source.row_count or 0),
        "crs": source.crs,
        "semantic_domain": source.semantic_domain,
        "columns": [column.get("name") for column in source.columns],
    }


def _normalize_field_matches(matches: list[dict]) -> list[dict]:
    normalized = []
    for match in matches:
        normalized.append(
            {
                "source_field": match.get("left", ""),
                "target_field": match.get("right", ""),
                "confidence": match.get("confidence"),
                "match_type": match.get(
                    "match_type",
                    "exact" if match.get("confidence") == 1.0 else "semantic",
                ),
            }
        )
    return normalized


def _build_feature_semantics(
    gdf: gpd.GeoDataFrame,
    sources: list[FusionSource],
    sample_limit: int,
) -> list[dict]:
    if gdf.empty or sample_limit <= 0:
        return []

    source_refs = [os.path.basename(source.file_path) for source in sources]
    semantic_cols = _pick_semantic_columns(gdf)
    rows = []
    for idx, row in gdf.head(sample_limit).iterrows():
        confidence = _safe_float(row.get(COL_CONFIDENCE), default=1.0)
        attrs = []
        for col in semantic_cols:
            value = row.get(col)
            if pd.notna(value):
                attrs.append(f"{col}={value}")
        summary = f"Feature {idx}: " + "; ".join(attrs[:12])
        rows.append(
            {
                "row_index": int(idx) if isinstance(idx, int) else str(idx),
                "summary": summary,
                "source_refs": source_refs,
                "quality": _classify_quality(confidence),
            }
        )
    return rows


def _build_ai_metadata(
    gdf: gpd.GeoDataFrame,
    sources: list[FusionSource],
    strategy: str,
    quality: dict,
    feature_semantics: list[dict],
    enabled: bool,
) -> dict:
    source_names = [os.path.basename(source.file_path) for source in sources]
    retrieval_text = (
        f"Semantic fusion product generated with {strategy}. "
        f"Sources: {', '.join(source_names)}. "
        f"Rows: {len(gdf)}. Quality score: {quality.get('score')}."
    )
    chunks = []
    if enabled:
        chunks.append(
            {
                "chunk_id": "fusion:product",
                "text": retrieval_text,
                "metadata": {
                    "strategy": strategy,
                    "row_count": int(len(gdf)),
                    "quality_score": quality.get("score"),
                    "sources": source_names,
                },
            }
        )
        for i, feature in enumerate(feature_semantics):
            chunks.append(
                {
                    "chunk_id": f"fusion:feature:{i}",
                    "text": feature["summary"],
                    "metadata": {
                        "strategy": strategy,
                        "quality": feature["quality"],
                        "source_refs": feature["source_refs"],
                    },
                }
            )

    return {
        "retrieval_text": retrieval_text,
        "chunks": chunks,
        "embedding_ready": True,
        "recommended_vector_targets": ["pgvector", "lancedb"],
    }


def _pick_semantic_columns(gdf: gpd.GeoDataFrame) -> list[str]:
    priority = [
        "parcel_id",
        "name",
        "land_use_code",
        "land_use_name",
        "area",
        "area_mu",
        "population",
        "population_density",
        "floors",
        "building_height",
        "slope",
        "slope_class",
        "building_type",
        "district",
    ]
    existing = [col for col in priority if col in gdf.columns]
    if len(existing) >= 12:
        return existing

    extra = [
        col
        for col in gdf.columns
        if col != "geometry" and not col.startswith("_") and col not in existing
    ]
    return existing + extra[: 12 - len(existing)]


def _add_canonical_semantic_fields(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Expose canonical fields from common fusion suffixes for ontology rules."""
    canonical_aliases = {
        "area": ["area", "mj", "zmj", "shape_area", "tbmj"],
        "perimeter": ["perimeter", "shape_length", "shape_len"],
        "land_use_code": ["land_use_code", "dlbm", "land_code"],
        "land_use_name": ["land_use_name", "dlmc", "land_name"],
        "elevation": ["elevation", "dem", "height", "altitude"],
        "slope": ["slope", "gradient", "pd"],
        "population": ["population", "pop", "rk", "pop_count"],
        "floors": ["floors", "cs", "floor_count", "building_floors"],
        "building_area": ["building_area", "jzmj", "bldg_area"],
        "green_area": ["green_area", "lhmj"],
        "parcel_id": ["parcel_id", "dkbh", "parcel_no", "lot_id"],
        "district": ["district", "qx", "county"],
    }
    suffixes = ("_left", "_right", "_x", "_y", "_1", "_2")
    result = gdf.copy()
    columns_by_lower = {col.lower(): col for col in result.columns}

    for canonical, aliases in canonical_aliases.items():
        if canonical in result.columns:
            continue

        candidates = []
        for alias in aliases:
            alias_lower = alias.lower()
            exact = columns_by_lower.get(alias_lower)
            if exact and exact not in candidates:
                candidates.append(exact)
            for suffix in suffixes:
                candidate = columns_by_lower.get(f"{alias_lower}{suffix}")
                if candidate and candidate not in candidates:
                    candidates.append(candidate)

        if candidates:
            result[canonical] = result[candidates].bfill(axis=1).iloc[:, 0]

    return result


def _derivation_description(reasoner: Any, field: str) -> str:
    rule = getattr(reasoner, "_derivation_index", {}).get(field, {})
    return rule.get("description") or f"Derived field {field}"


def _safe_float(value: Any, default: float) -> float:
    try:
        if pd.isna(value):
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _json_default(value: Any) -> Any:
    if hasattr(value, "item"):
        return value.item()
    return str(value)
