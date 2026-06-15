"""Contracts for external PDAL point-cloud pipeline execution.

MMFE keeps PDAL as an optional external tool. This module builds and validates
small JSON pipeline specs that can later be handed to a PDAL runner.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any


PDAL_PIPELINE_SCHEMA = "mmfe.pdal_pipeline.v1"


def build_pdal_pipeline_spec(
    source_profile: dict,
    output_path: str,
    pipeline_task: str = "prepare_point_cloud",
    filters: list[dict] | None = None,
    writer_type: str | None = None,
    writer_options: dict | None = None,
    metadata: dict | None = None,
) -> dict:
    """Build a dependency-free PDAL pipeline contract for a point-cloud source."""
    source_path = _source_path(source_profile)
    stats = source_profile.get("stats") if isinstance(source_profile, dict) else {}
    stats = stats if isinstance(stats, dict) else {}
    chunking = dict(stats.get("chunking") or {})
    laz_status = dict(stats.get("laz") or {})
    source = {
        "path": source_path,
        "format": os.path.splitext(source_path)[1].lower().lstrip(".") or "unknown",
        "compressed": bool(laz_status.get("compressed")),
    }
    if source_profile.get("crs"):
        source["crs"] = source_profile["crs"]
    if laz_status:
        source["laz"] = laz_status

    pipeline = [{"type": "readers.las", "filename": source_path}]
    for item in filters or []:
        if isinstance(item, dict):
            pipeline.append(dict(item))
    writer = {
        "type": writer_type or _default_writer_type(output_path),
        "filename": output_path,
    }
    writer.update(dict(writer_options or {}))
    pipeline.append(writer)

    spec = {
        "schema": PDAL_PIPELINE_SCHEMA,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "execution_mode": "external_pdal",
        "pipeline_task": pipeline_task,
        "source": source,
        "output_path": output_path,
        "chunking": _normalize_chunking(chunking),
        "pipeline": pipeline,
        "semantic_hints": _pdal_pipeline_hints(chunking, laz_status),
    }
    if metadata:
        spec["metadata"] = dict(metadata)
    return spec


def validate_pdal_pipeline_spec(spec: dict) -> list[str]:
    """Return contract errors for a PDAL pipeline spec."""
    errors = []
    if not isinstance(spec, dict):
        return ["pdal pipeline spec must be an object"]
    if spec.get("schema") != PDAL_PIPELINE_SCHEMA:
        errors.append(f"schema must be {PDAL_PIPELINE_SCHEMA}")
    if spec.get("execution_mode") != "external_pdal":
        errors.append("execution_mode must be external_pdal")
    source = spec.get("source")
    if not isinstance(source, dict):
        errors.append("source must be an object")
        source = {}
    if not source.get("path"):
        errors.append("source.path is required")
    if not spec.get("output_path"):
        errors.append("output_path is required")

    pipeline = spec.get("pipeline")
    if not isinstance(pipeline, list) or not pipeline:
        errors.append("pipeline must contain reader and writer stages")
    else:
        first = pipeline[0] if isinstance(pipeline[0], dict) else {}
        last = pipeline[-1] if isinstance(pipeline[-1], dict) else {}
        if not str(first.get("type", "")).startswith("readers."):
            errors.append("pipeline must start with a reader")
        if len(pipeline) < 2:
            errors.append("pipeline must contain reader and writer stages")
        if not str(last.get("type", "")).startswith("writers."):
            errors.append("pipeline must end with a writer")
        if not last.get("filename"):
            errors.append("pipeline writer filename is required")

    chunking = spec.get("chunking")
    if isinstance(chunking, dict) and chunking.get("required"):
        chunk_count = chunking.get("chunk_count", 0)
        try:
            chunk_count = int(chunk_count)
        except (TypeError, ValueError):
            chunk_count = 0
        if chunk_count < 1:
            errors.append("chunking.chunk_count must be positive when required")
    return errors


def write_pdal_pipeline_spec(spec: dict, output_path: str) -> str:
    """Write a PDAL pipeline spec beside the planned output path."""
    errors = validate_pdal_pipeline_spec(spec)
    if errors:
        raise ValueError("; ".join(errors))
    root, _ = os.path.splitext(output_path)
    spec_path = f"{root}.pdal.json"
    with open(spec_path, "w", encoding="utf-8") as f:
        json.dump(spec, f, ensure_ascii=False, indent=2, default=_json_default)
    return spec_path


def _source_path(source_profile: dict) -> str:
    if not isinstance(source_profile, dict):
        return ""
    return str(source_profile.get("file_path") or source_profile.get("path") or "")


def _default_writer_type(output_path: str) -> str:
    ext = os.path.splitext(output_path)[1].lower()
    if ext == ".laz" and output_path.lower().endswith(".copc.laz"):
        return "writers.copc"
    if ext == ".las":
        return "writers.las"
    if ext == ".laz":
        return "writers.las"
    return "writers.las"


def _normalize_chunking(chunking: dict) -> dict:
    if not chunking:
        return {"required": False, "strategy": "single_pass", "chunk_count": 1}
    normalized = dict(chunking)
    normalized.setdefault("required", False)
    normalized.setdefault("strategy", "single_pass")
    normalized.setdefault("chunk_count", 1)
    return normalized


def _pdal_pipeline_hints(chunking: dict, laz_status: dict) -> list[dict]:
    hints = []
    if chunking.get("required"):
        hints.append({
            "type": "point_cloud_processing",
            "value": "pdal_pipeline_required",
            "domain": "lidar",
            "confidence": 0.9,
            "evidence": list(chunking.get("reasons") or ["chunking required"]),
        })
    if laz_status.get("compressed"):
        value = (
            "pdal_laz_backend_required"
            if not laz_status.get("backend_available", True)
            else "pdal_laz_source"
        )
        hints.append({
            "type": "point_cloud_capability",
            "value": value,
            "domain": "lidar",
            "confidence": 0.86,
            "evidence": ["source format is LAZ"],
        })
    return hints


def _json_default(value: Any) -> object:
    if hasattr(value, "item"):
        return value.item()
    return str(value)
