"""Contracts for third-party AI semantic inference sidecars.

MMFE does not need to import heavy model runtimes to use AI-derived semantics.
External tools can run Prithvi, SAM, Pointcept, or custom models and hand MMFE a
small `.ai.json` sidecar with normalized observations.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any


AI_SEMANTIC_SIDECAR_SCHEMA = "mmfe.ai_semantics.v1"

AI_SEMANTIC_MODEL_CATALOG = [
    {
        "id": "prithvi-eo-2",
        "name": "Prithvi EO 2.0",
        "source_type": "raster",
        "modalities": ["multispectral", "multitemporal"],
        "tasks": [
            "land_cover_classification",
            "crop_mapping",
            "flood_mapping",
            "change_detection",
        ],
        "integration_mode": "external_sidecar",
    },
    {
        "id": "terramind",
        "name": "TerraMind",
        "source_type": "raster",
        "modalities": ["optical", "sar", "multimodal_eo"],
        "tasks": [
            "land_cover_classification",
            "cross_modal_retrieval",
            "change_detection",
            "disaster_mapping",
        ],
        "integration_mode": "external_sidecar",
    },
    {
        "id": "sam2-grounding-dino",
        "name": "SAM 2 + Grounding DINO",
        "source_type": "raster",
        "modalities": ["rgb", "orthophoto", "image_chip"],
        "tasks": [
            "open_vocabulary_detection",
            "prompted_segmentation",
            "object_mask_generation",
        ],
        "integration_mode": "external_sidecar",
    },
    {
        "id": "randla-net",
        "name": "RandLA-Net",
        "source_type": "point_cloud",
        "modalities": ["lidar", "point_cloud"],
        "tasks": ["point_semantic_segmentation"],
        "integration_mode": "external_sidecar",
    },
    {
        "id": "pointcept-ptv3",
        "name": "Pointcept / Point Transformer V3",
        "source_type": "point_cloud",
        "modalities": ["lidar", "point_cloud"],
        "tasks": [
            "point_semantic_segmentation",
            "point_cloud_object_detection",
            "instance_segmentation",
        ],
        "integration_mode": "external_sidecar",
    },
    {
        "id": "custom-model",
        "name": "Custom external AI model",
        "source_type": "any",
        "modalities": ["raster", "point_cloud", "vector", "tabular"],
        "tasks": ["custom_semantic_inference"],
        "integration_mode": "external_sidecar",
    },
]


def get_ai_semantic_model_catalog() -> list[dict]:
    """Return supported third-party AI model profiles."""
    return [dict(model) for model in AI_SEMANTIC_MODEL_CATALOG]


def build_ai_semantic_sidecar(
    model_id: str,
    observations: list[dict],
    source_path: str = "",
    model_name: str | None = None,
    model_version: str | None = None,
    task: str | None = None,
    metadata: dict | None = None,
) -> dict:
    """Build a normalized MMFE AI semantic sidecar."""
    model_profile = _model_profile(model_id)
    model = {
        "id": model_id,
        "name": model_name or model_profile.get("name") or model_id,
    }
    if model_version:
        model["version"] = model_version
    if task:
        model["task"] = task

    sidecar = {
        "schema": AI_SEMANTIC_SIDECAR_SCHEMA,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_path": source_path,
        "model": model,
        "observations": [
            _normalize_observation(observation)
            for observation in observations
            if isinstance(observation, dict)
        ],
    }
    if metadata:
        sidecar["metadata"] = dict(metadata)
    return sidecar


def validate_ai_semantic_sidecar(sidecar: dict) -> list[str]:
    """Return contract errors for an AI semantic sidecar."""
    errors = []
    if not isinstance(sidecar, dict):
        return ["sidecar must be an object"]
    if sidecar.get("schema") != AI_SEMANTIC_SIDECAR_SCHEMA:
        errors.append(f"schema must be {AI_SEMANTIC_SIDECAR_SCHEMA}")
    model = sidecar.get("model")
    if not isinstance(model, dict):
        errors.append("model must be an object")
        model = {}
    if not model.get("id"):
        errors.append("model.id is required")
    if not model.get("name"):
        errors.append("model.name is required")

    observations = sidecar.get("observations")
    if not isinstance(observations, list):
        errors.append("observations must be a list")
        return errors
    for index, observation in enumerate(observations):
        if not isinstance(observation, dict):
            errors.append(f"observations[{index}] must be an object")
            continue
        prefix = f"observations[{index}]"
        for key in ["target", "type", "value"]:
            if not observation.get(key):
                errors.append(f"{prefix}.{key} is required")
        confidence = observation.get("confidence")
        if confidence is not None:
            try:
                confidence_value = float(confidence)
            except (TypeError, ValueError):
                errors.append(f"{prefix}.confidence must be numeric")
            else:
                if not 0.0 <= confidence_value <= 1.0:
                    errors.append(f"{prefix}.confidence must be between 0 and 1")
    return errors


def write_ai_semantic_sidecar(sidecar: dict, source_path: str) -> str:
    """Write an AI semantic sidecar next to a source dataset."""
    errors = validate_ai_semantic_sidecar(sidecar)
    if errors:
        raise ValueError("; ".join(errors))
    root, _ = os.path.splitext(source_path)
    output_path = f"{root}.ai.json"
    sidecar_to_write = dict(sidecar)
    sidecar_to_write["source_path"] = source_path
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(sidecar_to_write, f, ensure_ascii=False, indent=2, default=_json_default)
    return output_path


def _normalize_observation(observation: dict) -> dict:
    value = observation.get("value", observation.get("label"))
    normalized = {
        "target": str(observation.get("target", "source")),
        "type": str(observation.get("type", "model_semantic_observation")),
        "value": "" if value is None else str(value),
        "confidence": _safe_confidence(observation.get("confidence")),
        "semantic_level": "model_inference",
        "evidence": _as_text_list(observation.get("evidence")),
    }
    for key in ["domain", "bbox", "geometry", "feature_id", "class_id"]:
        if observation.get(key) is not None:
            normalized[key] = observation[key]
    return normalized


def _model_profile(model_id: str) -> dict:
    for model in AI_SEMANTIC_MODEL_CATALOG:
        if model["id"] == model_id:
            return model
    return {"id": model_id, "name": model_id}


def _safe_confidence(value: Any) -> float:
    try:
        confidence = float(value)
    except (TypeError, ValueError):
        return 0.0
    return round(max(0.0, min(confidence, 1.0)), 6)


def _as_text_list(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, (list, tuple, set)):
        return [str(item) for item in value if item is not None and str(item) != ""]
    return [str(value)]


def _json_default(value: object) -> object:
    if hasattr(value, "item"):
        return value.item()
    return str(value)
