"""Semantic fusion product builder for MMFE.

This module converts a physical fused GeoDataFrame into a portable semantic
product: enriched business columns plus an AI-ready JSON manifest.
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from typing import Any

import geopandas as gpd
import pandas as pd

from .explainability import COL_CONFIDENCE, _classify_quality
from .models import FusionSource
from .semantic_alignment import (
    build_alignment_review_items,
    build_alignment_summary,
    score_semantic_alignment,
)


SEMANTIC_PRODUCT_VERSION = "1.1"

SEMANTIC_PRODUCT_SCHEMA = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "title": "MMFE Semantic Fusion Product",
    "type": "object",
    "required": [
        "product_type",
        "version",
        "product_id",
        "business_output",
        "sources",
        "semantic_mappings",
        "field_contracts",
        "derived_fields",
        "inferred_fields",
        "feature_semantics",
        "ai_metadata",
        "quality",
        "lineage",
    ],
    "properties": {
        "product_type": {"type": "string"},
        "version": {"type": "string"},
        "product_id": {"type": "string"},
        "created_at": {"type": "string"},
        "business_output": {
            "type": "object",
            "required": ["path", "format", "row_count", "column_count", "crs"],
            "properties": {
                "path": {"type": "string"},
                "format": {"type": "string"},
                "row_count": {"type": "integer"},
                "column_count": {"type": "integer"},
                "crs": {"type": ["string", "null"]},
            },
        },
        "sources": {"type": "array"},
        "semantic_mappings": {"type": "array"},
        "field_contracts": {"type": "array"},
        "derived_fields": {"type": "array"},
        "inferred_fields": {"type": "array"},
        "feature_semantics": {"type": "array"},
        "ai_metadata": {
            "type": "object",
            "required": [
                "retrieval_text",
                "chunks",
                "embedding_ready",
                "recommended_vector_targets",
            ],
            "properties": {
                "retrieval_text": {"type": "string"},
                "chunks": {"type": "array"},
                "embedding_ready": {"type": "boolean"},
                "recommended_vector_targets": {"type": "array"},
            },
        },
        "quality": {
            "type": "object",
            "required": ["score", "warnings"],
            "properties": {
                "score": {"type": ["number", "null"]},
                "warnings": {"type": "array"},
            },
        },
        "lineage": {"type": "object"},
    },
}


DEFAULT_SEMANTIC_PRODUCT_CONFIG = {
    "enabled": True,
    "use_ontology": True,
    "derive_fields": True,
    "infer_fields": True,
    "feature_sample_limit": 25,
    "ai_chunks": True,
    "document_context": None,
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
    document_context = cfg.get("document_context")
    semantic_mappings = _normalize_field_matches(
        field_matches or [],
        sources,
        document_context=document_context,
    )
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
        semantic_mappings,
        enabled=bool(cfg.get("ai_chunks", True)),
    )

    manifest = {
        "product_type": "semantic_fusion_product",
        "version": SEMANTIC_PRODUCT_VERSION,
        "product_id": _build_product_id(enriched, sources, strategy),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "business_output": {
            "path": "",
            "format": "GeoJSON",
            "row_count": int(len(enriched)),
            "column_count": len([c for c in enriched.columns if c != "geometry"]),
            "crs": str(enriched.crs) if getattr(enriched, "crs", None) else None,
        },
        "sources": [_source_manifest(source) for source in sources],
        "semantic_mappings": semantic_mappings,
        "field_contracts": _build_field_contracts(
            enriched,
            sources,
            derived_fields,
            inferred_fields,
            field_matches or [],
            document_context=document_context,
        ),
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
    mmfe_bundle = _build_optional_mmfe_bundle(cfg)
    if mmfe_bundle:
        manifest["mmfe_bundle"] = mmfe_bundle
    return enriched, manifest


def write_semantic_product_manifest(manifest: dict, output_path: str) -> str:
    """Write manifest JSON next to the fused dataset and return its path."""
    root, _ = os.path.splitext(output_path)
    manifest_path = f"{root}.semantic.json"
    manifest_to_write = dict(manifest)
    business_output = dict(manifest_to_write.get("business_output", {}))
    business_output["path"] = output_path
    manifest_to_write["business_output"] = business_output
    errors = validate_semantic_product_manifest(manifest_to_write)
    if errors:
        raise ValueError(
            "Invalid semantic fusion product manifest: " + "; ".join(errors)
        )
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(
            manifest_to_write,
            f,
            ensure_ascii=False,
            indent=2,
            default=_json_default,
        )
    return manifest_path


def validate_semantic_product_manifest(
    manifest: dict,
    schema: dict | None = None,
) -> list[str]:
    """Validate a manifest against the supported JSON Schema subset."""
    return _validate_schema_subset(
        manifest,
        schema or SEMANTIC_PRODUCT_SCHEMA,
        path="",
    )


def _source_manifest(source: FusionSource) -> dict:
    return {
        "path": source.file_path,
        "data_type": source.data_type,
        "modality": source.modality or source.data_type,
        "media_type": source.media_type,
        "adapter_family": source.adapter_family or "generic",
        "row_count": int(source.row_count or 0),
        "crs": source.crs,
        "semantic_domain": source.semantic_domain,
        "semantic_hints": list(source.semantic_hints or []),
        "columns": [column.get("name") for column in source.columns],
    }


def _build_optional_mmfe_bundle(config: dict) -> dict:
    """Carry optional MMFE sidecar contracts into the semantic product."""
    bundle = {}
    configured_bundle = config.get("mmfe_bundle")
    if isinstance(configured_bundle, dict):
        bundle.update(dict(configured_bundle))

    for key in (
        "standard_source_registry",
        "standard_source_ingestion_plan",
        "standard_source_ingestion_run",
        "production_readiness",
        "semantic_graph",
        "semantic_trace_cards",
        "semantic_ontology",
        "semantic_diagnostic",
        "twm_consumption",
        "twm_state_input",
    ):
        value = config.get(key)
        if isinstance(value, dict):
            bundle[key] = value

    list_mappings = {
        "field_semantics": "field_semantics",
        "value_domain_audits": "value_domain_audits",
        "standard_source_rows": "standard_source_rows",
        "semantic_relations": "semantic_relations",
    }
    for config_key, bundle_key in list_mappings.items():
        value = config.get(config_key)
        if isinstance(value, list):
            bundle[bundle_key] = list(value)

    return bundle


def _normalize_field_matches(
    matches: list[dict],
    sources: list[FusionSource] | None = None,
    document_context: Any | None = None,
) -> list[dict]:
    field_profiles = _field_profiles_by_name(sources or [])
    document_index = _build_document_context_index(document_context)
    normalized = []
    for match in matches:
        source_field = match.get("left", "")
        target_field = match.get("right", "")
        confidence = match.get("confidence")
        match_type = match.get(
            "match_type",
            "exact" if confidence == 1.0 else "semantic",
        )
        source_profile = _first_field_profile(field_profiles, source_field)
        target_profile = _first_field_profile(field_profiles, target_field)
        evidence = _build_mapping_evidence(
            match,
            match_type,
            source_profile,
            target_profile,
            document_index,
        )
        alignment_score = score_semantic_alignment(
            confidence,
            match_type,
            evidence,
        )
        normalized.append({
            "source_field": source_field,
            "target_field": target_field,
            "confidence": confidence,
            "confidence_band": _confidence_band(confidence),
            "match_type": match_type,
            "source_profile": source_profile,
            "target_profile": target_profile,
            "evidence": evidence,
            "alignment_score": alignment_score,
            "explanation": _mapping_explanation(
                source_field,
                target_field,
                match_type,
                confidence,
                evidence,
            ),
        })
    return normalized


def _field_profiles_by_name(sources: list[FusionSource]) -> dict[str, list[dict]]:
    profiles: dict[str, list[dict]] = {}
    for source in sources:
        source_name = os.path.basename(source.file_path)
        columns = source.columns or []
        for column in columns:
            name = column.get("name")
            if not name:
                continue
            stats = source.stats.get(name, {}) if source.stats else {}
            profile = {
                "source": source_name,
                "field": name,
                "dtype": column.get("dtype", ""),
                "null_pct": column.get("null_pct"),
            }
            if stats:
                profile["stats"] = stats
            profiles.setdefault(name.lower(), []).append(profile)
    return profiles


def _first_field_profile(
    profiles: dict[str, list[dict]],
    field_name: str,
) -> dict:
    matches = profiles.get(str(field_name).lower(), [])
    return matches[0] if matches else {}


def _build_mapping_evidence(
    match: dict,
    match_type: str,
    source_profile: dict,
    target_profile: dict,
    document_index: dict[str, list[dict]] | None = None,
) -> list[dict]:
    evidence = []
    source_field = match.get("left", "")
    target_field = match.get("right", "")
    group_id = match.get("group_id")
    if match_type == "ontology" and group_id:
        evidence.append({
            "type": "ontology",
            "detail": f"same ontology group: {group_id}",
        })
    elif match_type:
        evidence.append({
            "type": "matcher",
            "detail": f"matched by {match_type}",
        })

    source_dtype = source_profile.get("dtype")
    target_dtype = target_profile.get("dtype")
    if source_dtype and target_dtype:
        detail = f"{source_dtype} -> {target_dtype}"
        evidence.append({
            "type": "dtype",
            "detail": detail,
            "compatible": _dtype_compatible(source_dtype, target_dtype),
        })

    if source_profile.get("stats") or target_profile.get("stats"):
        evidence.append({
            "type": "value_profile",
            "detail": "source statistics available",
        })

    evidence.extend(
        _document_context_evidence(source_field, target_field, document_index or {})
    )

    return evidence


def _build_document_context_index(document_context: Any | None) -> dict[str, list[dict]]:
    if not document_context:
        return {}

    if isinstance(document_context, dict):
        entries = document_context.get("source_metadata")
        if entries is None:
            entries = [document_context]
    elif isinstance(document_context, list):
        entries = document_context
    else:
        return {}

    index: dict[str, list[dict]] = {}
    for entry in entries or []:
        if not isinstance(entry, dict):
            continue
        source = entry.get("file") or entry.get("source") or entry.get("path") or ""
        definitions = entry.get("field_definitions") or []
        if isinstance(definitions, dict):
            iterable = [
                {"field": field, "meaning": meaning}
                for field, meaning in definitions.items()
            ]
        elif isinstance(definitions, list):
            iterable = definitions
        else:
            iterable = []

        for definition in iterable:
            normalized = _normalize_document_field_definition(definition, source)
            if not normalized:
                continue
            for term in normalized["terms"]:
                index.setdefault(term, []).append(normalized)
    return index


def _normalize_document_field_definition(
    definition: Any,
    source: str,
) -> dict | None:
    if isinstance(definition, str):
        field, _, meaning = definition.partition(":")
        terms = _terms_from_values([field])
        if not terms:
            return None
        return {
            "source": source,
            "terms": terms,
            "meaning": meaning.strip() or definition.strip(),
        }

    if not isinstance(definition, dict):
        return None

    values: list[Any] = [
        definition.get("field"),
        definition.get("name"),
        definition.get("canonical_field"),
        definition.get("standard_field"),
        definition.get("target_field"),
    ]
    aliases = definition.get("aliases", [])
    if isinstance(aliases, str):
        values.extend([item.strip() for item in aliases.split(",")])
    elif isinstance(aliases, list):
        values.extend(aliases)

    terms = _terms_from_values(values)
    if not terms:
        return None

    meaning = (
        definition.get("meaning")
        or definition.get("description")
        or definition.get("definition")
        or ""
    )
    return {
        "source": source,
        "terms": terms,
        "meaning": str(meaning),
    }


def _terms_from_values(values: list[Any]) -> list[str]:
    terms = []
    for value in values:
        if value is None:
            continue
        term = str(value).strip().lower()
        if term and term not in terms:
            terms.append(term)
    return terms


def _document_context_evidence(
    source_field: str,
    target_field: str,
    document_index: dict[str, list[dict]],
) -> list[dict]:
    source_key = str(source_field).strip().lower()
    target_key = str(target_field).strip().lower()
    if not source_key or not target_key:
        return []

    candidates = document_index.get(source_key, []) + document_index.get(target_key, [])
    seen: set[tuple[str, str]] = set()
    for definition in candidates:
        terms = set(definition.get("terms", []))
        meaning = str(definition.get("meaning", ""))
        meaning_lower = meaning.lower()
        direct_link = source_key in terms and target_key in terms
        meaning_link = (
            (source_key in terms and target_key in meaning_lower)
            or (target_key in terms and source_key in meaning_lower)
        )
        if not direct_link and not meaning_link:
            continue

        source = definition.get("source", "")
        key = (source, meaning)
        if key in seen:
            continue
        seen.add(key)
        support = 1.0 if direct_link else 0.8
        detail = f"document context links {source_field} and {target_field}"
        if meaning:
            detail = f"{detail}: {meaning[:160]}"
        evidence = {
            "type": "document_context",
            "detail": detail,
            "support": support,
        }
        if source:
            evidence["source"] = source
        return [evidence]
    return []


def _confidence_band(confidence: Any) -> str:
    try:
        score = float(confidence)
    except (TypeError, ValueError):
        return "unknown"
    if score >= 0.8:
        return "high"
    if score >= 0.6:
        return "medium"
    return "low"


def _dtype_compatible(source_dtype: str, target_dtype: str) -> bool:
    numeric_indicators = ("int", "float", "double", "numeric", "decimal")
    text_indicators = ("object", "str", "string", "text", "char")
    left = source_dtype.lower()
    right = target_dtype.lower()
    left_numeric = any(item in left for item in numeric_indicators)
    right_numeric = any(item in right for item in numeric_indicators)
    left_text = any(item in left for item in text_indicators)
    right_text = any(item in right for item in text_indicators)
    if (left_numeric and right_text) or (left_text and right_numeric):
        return False
    return True


def _mapping_explanation(
    source_field: str,
    target_field: str,
    match_type: str,
    confidence: Any,
    evidence: list[dict],
) -> str:
    evidence_bits = [item["detail"] for item in evidence if item.get("detail")]
    details = "; ".join(evidence_bits)
    return (
        f"{source_field} -> {target_field} matched by {match_type} "
        f"with confidence {confidence}. {details}"
    ).strip()


def _build_field_contracts(
    gdf: gpd.GeoDataFrame,
    sources: list[FusionSource],
    derived_fields: list[dict[str, Any]],
    inferred_fields: list[dict[str, Any]],
    field_matches: list[dict],
    document_context: Any | None = None,
) -> list[dict]:
    derived_names = {item["field"] for item in derived_fields}
    inferred_names = {item["field"] for item in inferred_fields}
    source_columns = _source_columns_by_name(sources)
    mapping_by_target = {}
    for match in _normalize_field_matches(
        field_matches,
        sources,
        document_context=document_context,
    ):
        target = match.get("target_field")
        if target:
            mapping_by_target.setdefault(target, []).append(match)

    contracts = []
    for col in gdf.columns:
        if col == "geometry":
            continue
        source_refs = source_columns.get(col.lower(), [])
        mappings = mapping_by_target.get(col, [])
        role = _semantic_role(col, derived_names, inferred_names, source_refs)
        contract = {
            "field": col,
            "dtype": str(gdf[col].dtype),
            "semantic_role": role,
            "nullable_pct": round(float(gdf[col].isna().mean()), 4),
            "source_fields": source_refs,
            "mappings": mappings,
            "value_profile": _build_value_profile(gdf[col]),
        }
        if col in derived_names:
            contract["lineage"] = {"type": "derived"}
        elif col in inferred_names:
            contract["lineage"] = {"type": "inferred"}
        elif source_refs:
            contract["lineage"] = {"type": "source"}
        else:
            contract["lineage"] = {"type": "fusion_output"}
        contracts.append(contract)
    return contracts


def _build_value_profile(series: pd.Series) -> dict:
    values = series.dropna()
    if values.empty:
        return {"kind": "empty", "samples": []}

    if pd.api.types.is_numeric_dtype(values):
        return {
            "kind": "numeric",
            "min": _json_default(values.min()),
            "max": _json_default(values.max()),
            "mean": round(float(values.mean()), 6),
        }

    samples = []
    for value in values.astype(str).drop_duplicates().head(5):
        samples.append(value)
    return {
        "kind": "categorical",
        "unique_count": int(values.nunique(dropna=True)),
        "samples": samples,
    }


def _source_columns_by_name(sources: list[FusionSource]) -> dict[str, list[dict]]:
    source_columns: dict[str, list[dict]] = {}
    for source in sources:
        source_name = os.path.basename(source.file_path)
        for column in source.columns:
            name = column.get("name")
            if not name:
                continue
            source_columns.setdefault(name.lower(), []).append(
                {
                    "source": source_name,
                    "field": name,
                    "dtype": column.get("dtype", ""),
                }
            )
    return source_columns


def _semantic_role(
    field: str,
    derived_names: set[str],
    inferred_names: set[str],
    source_refs: list[dict],
) -> str:
    if field in derived_names:
        return "derived"
    if field in inferred_names:
        return "inferred"
    if field.startswith("_"):
        return "system_metadata"
    if source_refs:
        return "source_attribute"
    return "fusion_output"


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
    semantic_mappings: list[dict],
    enabled: bool,
) -> dict:
    source_names = [os.path.basename(source.file_path) for source in sources]
    alignment_summary = build_alignment_summary(semantic_mappings)
    review_items = build_alignment_review_items(semantic_mappings)
    alignment_review = {
        "requires_human_review": bool(review_items),
        "review_item_count": len(review_items),
        "items": review_items,
    }
    retrieval_text = (
        f"Semantic fusion product generated with {strategy}. "
        f"Sources: {', '.join(source_names)}. "
        f"Rows: {len(gdf)}. Quality score: {quality.get('score')}. "
        f"Semantic mappings: {alignment_summary['total_mappings']}; "
        f"accepted mappings: {alignment_summary['decisions']['accept']}; "
        f"review mappings: {alignment_summary['decisions']['review']}; "
        f"rejected mappings: {alignment_summary['decisions']['reject']}; "
        f"review items: {len(review_items)}."
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
                    "alignment_summary": alignment_summary,
                    "alignment_review": alignment_review,
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
        "alignment_summary": alignment_summary,
        "alignment_review": alignment_review,
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


def _build_product_id(
    gdf: gpd.GeoDataFrame,
    sources: list[FusionSource],
    strategy: str,
) -> str:
    source_part = "|".join(source.file_path for source in sources)
    columns_part = "|".join(str(col) for col in gdf.columns if col != "geometry")
    raw = f"{strategy}|{len(gdf)}|{source_part}|{columns_part}"
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
    return f"sfp-{digest}"


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


def _validate_schema_subset(instance: Any, schema: dict, path: str) -> list[str]:
    errors: list[str] = []
    expected_type = schema.get("type")
    if expected_type is not None and not _type_matches(instance, expected_type):
        label = path or "manifest"
        errors.append(f"{label} expected type {_format_type(expected_type)}")
        return errors

    if isinstance(instance, dict):
        for key in schema.get("required", []):
            if key not in instance:
                label = f"{path}." if path else ""
                errors.append(f"{label}missing required property: {key}")
        properties = schema.get("properties", {})
        for key, child_schema in properties.items():
            if key in instance:
                child_path = f"{path}.{key}" if path else key
                errors.extend(
                    _validate_schema_subset(instance[key], child_schema, child_path)
                )

    return errors


def _type_matches(value: Any, expected_type: str | list[str]) -> bool:
    expected_types = (
        expected_type if isinstance(expected_type, list) else [expected_type]
    )
    for item in expected_types:
        if item == "null" and value is None:
            return True
        if item == "object" and isinstance(value, dict):
            return True
        if item == "array" and isinstance(value, list):
            return True
        if item == "string" and isinstance(value, str):
            return True
        if item == "boolean" and isinstance(value, bool):
            return True
        if item == "integer" and isinstance(value, int) and not isinstance(value, bool):
            return True
        if (
            item == "number"
            and isinstance(value, (int, float))
            and not isinstance(value, bool)
        ):
            return True
    return False


def _format_type(expected_type: str | list[str]) -> str:
    if isinstance(expected_type, list):
        return "|".join(expected_type)
    return expected_type
