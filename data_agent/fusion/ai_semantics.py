"""Contracts for third-party AI semantic inference sidecars.

MMFE does not need to import heavy model runtimes to use AI-derived semantics.
External tools can run Prithvi, SAM, Pointcept, or custom models and hand MMFE a
small `.ai.json` sidecar with normalized observations.
"""

from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime, timezone
from typing import Any


AI_SEMANTIC_SIDECAR_SCHEMA = "mmfe.ai_semantics.v1"
AI_SEMANTIC_RUNNER_SCHEMA = "mmfe.ai_runner.v1"

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


def build_ai_semantic_runner_spec(
    model_id: str,
    source_path: str,
    task: str,
    command_template: list[str] | tuple[str, ...] | str,
    output_path: str | None = None,
    model_name: str | None = None,
    model_version: str | None = None,
    parameters: dict | None = None,
    metadata: dict | None = None,
) -> dict:
    """Build a normalized contract for an external AI semantic runner.

    The spec is deliberately declarative. MMFE can create, review, and validate
    runner inputs/outputs without importing model runtimes or executing commands.
    """
    model_profile = _model_profile(model_id)
    resolved_output_path = output_path or _default_ai_sidecar_path(source_path)
    model = {
        "id": model_id,
        "name": model_name or model_profile.get("name") or model_id,
        "task": task,
    }
    if model_profile.get("source_type"):
        model["source_type"] = model_profile["source_type"]
    if model_version:
        model["version"] = model_version

    context = {
        "model_id": model_id,
        "model_name": model["name"],
        "model_version": model_version or "",
        "source_path": source_path,
        "output_path": resolved_output_path,
        "task": task,
    }
    spec = {
        "schema": AI_SEMANTIC_RUNNER_SCHEMA,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "integration_mode": "external_command",
        "model": model,
        "source_path": source_path,
        "expected_output_path": resolved_output_path,
        "sidecar_schema": AI_SEMANTIC_SIDECAR_SCHEMA,
        "command": _render_command_template(command_template, context),
        "parameters": dict(parameters or {}),
    }
    if metadata:
        spec["metadata"] = dict(metadata)
    return spec


def validate_ai_semantic_runner_spec(spec: dict) -> list[str]:
    """Return contract errors for an external AI semantic runner spec."""
    errors = []
    if not isinstance(spec, dict):
        return ["runner spec must be an object"]
    if spec.get("schema") != AI_SEMANTIC_RUNNER_SCHEMA:
        errors.append(f"schema must be {AI_SEMANTIC_RUNNER_SCHEMA}")
    if spec.get("integration_mode") != "external_command":
        errors.append("integration_mode must be external_command")
    if spec.get("sidecar_schema") != AI_SEMANTIC_SIDECAR_SCHEMA:
        errors.append(f"sidecar_schema must be {AI_SEMANTIC_SIDECAR_SCHEMA}")
    if not spec.get("source_path"):
        errors.append("source_path is required")
    if not spec.get("expected_output_path"):
        errors.append("expected_output_path is required")

    command = spec.get("command")
    if not isinstance(command, list) or not command:
        errors.append("command must be a non-empty list")
    elif not all(isinstance(part, str) and part for part in command):
        errors.append("command entries must be non-empty strings")

    model = spec.get("model")
    if not isinstance(model, dict):
        errors.append("model must be an object")
        model = {}
    model_id = model.get("id")
    task = model.get("task")
    if not model_id:
        errors.append("model.id is required")
    if not model.get("name"):
        errors.append("model.name is required")
    if not task:
        errors.append("model.task is required")
    elif model_id:
        profile = _model_profile(str(model_id))
        allowed_tasks = profile.get("tasks") or []
        if allowed_tasks and task not in allowed_tasks:
            errors.append(f"model.task must be one of: {', '.join(allowed_tasks)}")
    return errors


def validate_ai_semantic_runner_output(spec: dict) -> dict:
    """Validate a runner's produced `.ai.json` sidecar against the MMFE contract."""
    errors = validate_ai_semantic_runner_spec(spec)
    output_path = spec.get("expected_output_path") if isinstance(spec, dict) else None
    if errors:
        return {
            "valid": False,
            "errors": errors,
            "expected_output_path": output_path,
            "observation_count": 0,
            "sidecar": None,
        }
    if not output_path or not os.path.exists(output_path):
        return {
            "valid": False,
            "errors": [f"expected_output_path does not exist: {output_path}"],
            "expected_output_path": output_path,
            "observation_count": 0,
            "sidecar": None,
        }

    try:
        with open(output_path, "r", encoding="utf-8") as f:
            sidecar = json.load(f)
    except json.JSONDecodeError as exc:
        return {
            "valid": False,
            "errors": [f"expected_output_path is not valid JSON: {exc}"],
            "expected_output_path": output_path,
            "observation_count": 0,
            "sidecar": None,
        }

    sidecar_errors = validate_ai_semantic_sidecar(sidecar)
    observations = sidecar.get("observations") if isinstance(sidecar, dict) else []
    return {
        "valid": not sidecar_errors,
        "errors": sidecar_errors,
        "expected_output_path": output_path,
        "observation_count": len(observations) if isinstance(observations, list) else 0,
        "sidecar": sidecar,
    }


def run_ai_semantic_runner(
    spec: dict,
    executor=None,
) -> dict:
    """Run an external AI semantic command and validate its `.ai.json` output."""
    errors = validate_ai_semantic_runner_spec(spec)
    command = spec.get("command") if isinstance(spec, dict) else []
    output_path = spec.get("expected_output_path") if isinstance(spec, dict) else None
    if errors:
        return _ai_runner_result(
            command=command,
            output_path=output_path,
            returncode=None,
            stdout="",
            stderr="",
            validation={"valid": False, "errors": errors, "observation_count": 0, "sidecar": None},
            process_errors=errors,
        )

    run_executor = executor or _subprocess_executor
    try:
        completed = run_executor(
            command,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as exc:
        return _ai_runner_result(
            command=command,
            output_path=output_path,
            returncode=None,
            stdout="",
            stderr=str(exc),
            validation={
                "valid": False,
                "errors": ["AI semantic runner executable was not found"],
                "observation_count": 0,
                "sidecar": None,
            },
            process_errors=["AI semantic runner executable was not found"],
        )

    process_errors = []
    returncode = getattr(completed, "returncode", None)
    if returncode != 0:
        process_errors.append(f"AI semantic runner returncode was {returncode}")
    validation = validate_ai_semantic_runner_output(spec)
    return _ai_runner_result(
        command=command,
        output_path=output_path,
        returncode=returncode,
        stdout=str(getattr(completed, "stdout", "") or ""),
        stderr=str(getattr(completed, "stderr", "") or ""),
        validation=validation,
        process_errors=process_errors,
    )


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


def _default_ai_sidecar_path(source_path: str) -> str:
    root, _ = os.path.splitext(source_path)
    return f"{root}.ai.json"


def _render_command_template(
    command_template: list[str] | tuple[str, ...] | str,
    context: dict[str, str],
) -> list[str]:
    if isinstance(command_template, str):
        template_parts = [command_template]
    elif isinstance(command_template, (list, tuple)):
        template_parts = [str(part) for part in command_template]
    else:
        template_parts = []
    return [part.format(**context) for part in template_parts]


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


def _subprocess_executor(command: list[str], **kwargs):
    return subprocess.run(command, **kwargs)


def _ai_runner_result(
    command: list | None,
    output_path: str | None,
    returncode: int | None,
    stdout: str,
    stderr: str,
    validation: dict,
    process_errors: list[str],
) -> dict:
    validation_errors = list(validation.get("errors") or [])
    errors = process_errors + [
        error for error in validation_errors if error not in process_errors
    ]
    return {
        "valid": not errors,
        "errors": errors,
        "command": command or [],
        "expected_output_path": output_path,
        "output_exists": bool(output_path and os.path.exists(output_path)),
        "returncode": returncode,
        "stdout": stdout,
        "stderr": stderr,
        "observation_count": int(validation.get("observation_count") or 0),
        "sidecar": validation.get("sidecar"),
    }
