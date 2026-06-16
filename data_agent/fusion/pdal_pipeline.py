"""Contracts for external PDAL point-cloud pipeline execution.

MMFE keeps PDAL as an optional external tool. This module builds and validates
small JSON pipeline specs that can later be handed to a PDAL runner.
"""

from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime, timezone
from typing import Any


PDAL_PIPELINE_SCHEMA = "mmfe.pdal_pipeline.v1"
PDAL_RUNNER_SCHEMA = "mmfe.pdal_runner.v1"
POINT_CLOUD_CHUNK_ARTIFACT_SCHEMA = "mmfe.point_cloud_chunks.v1"


def build_point_cloud_chunk_artifact_manifest(
    source_profile: dict,
    artifact_dir: str,
    output_format: str = "las",
    metadata: dict | None = None,
) -> dict:
    """Build a manifest for planned point-cloud chunk artifacts.

    The manifest is a dependency-free bridge between profiling chunk plans and
    future streaming/PDAL jobs. It records what chunks should be materialized,
    but does not read point data or create chunk files.
    """
    source_path = _source_path(source_profile)
    stats = source_profile.get("stats") if isinstance(source_profile, dict) else {}
    stats = stats if isinstance(stats, dict) else {}
    chunking = _normalize_chunking(dict(stats.get("chunking") or {}))
    laz_status = dict(stats.get("laz") or {})
    chunks = _planned_chunk_artifacts(chunking, artifact_dir, output_format)

    source = {
        "path": source_path,
        "format": os.path.splitext(source_path)[1].lower().lstrip(".") or "unknown",
        "compressed": bool(laz_status.get("compressed")),
    }
    if isinstance(source_profile, dict) and source_profile.get("crs"):
        source["crs"] = source_profile["crs"]
    if laz_status:
        source["laz"] = laz_status

    manifest = {
        "schema": POINT_CLOUD_CHUNK_ARTIFACT_SCHEMA,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "artifact_type": "point_cloud_chunk_manifest",
        "source": source,
        "artifact_dir": artifact_dir,
        "output_format": output_format,
        "chunking": chunking,
        "chunks": chunks,
        "embedding_ready": True,
        "semantic_hints": _point_cloud_chunk_artifact_hints(chunking, output_format),
    }
    if metadata:
        manifest["metadata"] = dict(metadata)
    return manifest


def validate_point_cloud_chunk_artifact_manifest(manifest: dict) -> list[str]:
    """Return contract errors for a point-cloud chunk artifact manifest."""
    errors = []
    if not isinstance(manifest, dict):
        return ["point-cloud chunk artifact manifest must be an object"]
    if manifest.get("schema") != POINT_CLOUD_CHUNK_ARTIFACT_SCHEMA:
        errors.append(f"schema must be {POINT_CLOUD_CHUNK_ARTIFACT_SCHEMA}")

    source = manifest.get("source")
    if not isinstance(source, dict):
        errors.append("source must be an object")
        source = {}
    if not source.get("path"):
        errors.append("source.path is required")
    if not manifest.get("artifact_dir"):
        errors.append("artifact_dir is required")
    if not manifest.get("output_format"):
        errors.append("output_format is required")

    chunking = manifest.get("chunking")
    if not isinstance(chunking, dict):
        errors.append("chunking must be an object")
        chunking = {}
    chunk_count = _safe_int(chunking.get("chunk_count"), 0)
    if chunk_count < 1:
        errors.append("chunking.chunk_count must be positive")

    chunks = manifest.get("chunks")
    if not isinstance(chunks, list):
        errors.append("chunks must be a list")
        chunks = []
    if chunk_count > 0 and len(chunks) != chunk_count:
        errors.append("chunks length must match chunking.chunk_count")
    for i, chunk in enumerate(chunks):
        if not isinstance(chunk, dict):
            errors.append(f"chunks[{i}] must be an object")
            continue
        if not chunk.get("chunk_id"):
            errors.append(f"chunks[{i}].chunk_id is required")
        if not chunk.get("artifact_path"):
            errors.append(f"chunks[{i}].artifact_path is required")
        if _safe_int(chunk.get("point_start"), -1) < 0:
            errors.append(f"chunks[{i}].point_start must be non-negative")
        if _safe_int(chunk.get("point_count"), 0) < 1:
            errors.append(f"chunks[{i}].point_count must be positive")
    return errors


def write_point_cloud_chunk_artifact_manifest(
    manifest: dict,
    manifest_path: str | None = None,
) -> str:
    """Write a point-cloud chunk artifact manifest and return its path."""
    errors = validate_point_cloud_chunk_artifact_manifest(manifest)
    if errors:
        raise ValueError("; ".join(errors))
    path = manifest_path or os.path.join(manifest["artifact_dir"], "manifest.chunks.json")
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2, default=_json_default)
    return path


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


def build_pdal_runner_spec(
    pipeline_spec: dict,
    pipeline_path: str,
    pdal_binary: str = "pdal",
    timeout_s: int = 3600,
    metadata: dict | None = None,
) -> dict:
    """Build a runner contract for an external `pdal pipeline` invocation."""
    runner = {
        "schema": PDAL_RUNNER_SCHEMA,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "execution_mode": "external_pdal",
        "pipeline_path": pipeline_path,
        "expected_output_path": pipeline_spec.get("output_path", ""),
        "pipeline_schema": pipeline_spec.get("schema"),
        "pipeline_task": pipeline_spec.get("pipeline_task", ""),
        "chunking": dict(pipeline_spec.get("chunking") or {}),
        "command": [pdal_binary, "pipeline", pipeline_path],
        "timeout_s": int(timeout_s),
    }
    if metadata:
        runner["metadata"] = dict(metadata)
    return runner


def validate_pdal_runner_spec(runner_spec: dict) -> list[str]:
    """Return contract errors for a PDAL runner spec."""
    errors = []
    if not isinstance(runner_spec, dict):
        return ["pdal runner spec must be an object"]
    if runner_spec.get("schema") != PDAL_RUNNER_SCHEMA:
        errors.append(f"schema must be {PDAL_RUNNER_SCHEMA}")
    if runner_spec.get("execution_mode") != "external_pdal":
        errors.append("execution_mode must be external_pdal")
    if not runner_spec.get("pipeline_path"):
        errors.append("pipeline_path is required")
    if not runner_spec.get("expected_output_path"):
        errors.append("expected_output_path is required")
    command = runner_spec.get("command")
    if not isinstance(command, list) or len(command) < 3:
        errors.append("command must be a list like: pdal pipeline <path>")
    else:
        if command[1] != "pipeline":
            errors.append("command must invoke pdal pipeline")
        if command[-1] != runner_spec.get("pipeline_path"):
            errors.append("command pipeline path must match pipeline_path")
    return errors


def run_pdal_pipeline(
    runner_spec: dict,
    executor=None,
) -> dict:
    """Run a PDAL pipeline through an injectable executor and validate output.

    This wrapper keeps PDAL optional: callers can inject an executor in tests or
    production tool layers. The default path calls `subprocess.run`.
    """
    errors = validate_pdal_runner_spec(runner_spec)
    command = runner_spec.get("command") if isinstance(runner_spec, dict) else []
    output_path = (
        runner_spec.get("expected_output_path")
        if isinstance(runner_spec, dict)
        else None
    )
    if errors:
        return _pdal_runner_result(
            command=command,
            output_path=output_path,
            returncode=None,
            stdout="",
            stderr="",
            errors=errors,
        )

    run_executor = executor or _subprocess_executor
    try:
        completed = run_executor(
            command,
            capture_output=True,
            text=True,
            timeout=runner_spec.get("timeout_s", 3600),
        )
    except FileNotFoundError as exc:
        return _pdal_runner_result(
            command=command,
            output_path=output_path,
            returncode=None,
            stdout="",
            stderr=str(exc),
            errors=["pdal executable was not found"],
        )
    except subprocess.TimeoutExpired as exc:
        return _pdal_runner_result(
            command=command,
            output_path=output_path,
            returncode=None,
            stdout=str(exc.stdout or ""),
            stderr=str(exc.stderr or ""),
            errors=["pdal pipeline timed out"],
        )

    result_errors = []
    returncode = getattr(completed, "returncode", None)
    if returncode != 0:
        result_errors.append(f"pdal returncode was {returncode}")
    if output_path and not os.path.exists(output_path):
        result_errors.append(f"expected output was not created: {output_path}")
    return _pdal_runner_result(
        command=command,
        output_path=output_path,
        returncode=returncode,
        stdout=str(getattr(completed, "stdout", "") or ""),
        stderr=str(getattr(completed, "stderr", "") or ""),
        errors=result_errors,
    )


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
    normalized["chunk_count"] = _safe_int(normalized.get("chunk_count"), 1)
    return normalized


def _planned_chunk_artifacts(
    chunking: dict,
    artifact_dir: str,
    output_format: str,
) -> list[dict]:
    chunk_count = max(_safe_int(chunking.get("chunk_count"), 1), 1)
    point_count = _safe_int(chunking.get("point_count"), 0)
    chunk_size = _safe_int(chunking.get("chunk_size_points"), 0)
    if chunk_size <= 0:
        chunk_size = point_count if point_count > 0 else 0
    if chunk_size <= 0:
        chunk_size = 1

    chunks = []
    extension = _chunk_artifact_extension(output_format)
    for index in range(chunk_count):
        point_start = index * chunk_size
        planned_count = chunk_size
        if point_count > 0:
            remaining = max(point_count - point_start, 0)
            planned_count = min(chunk_size, remaining)
        if index == chunk_count - 1 and chunking.get("last_chunk_points"):
            planned_count = _safe_int(chunking.get("last_chunk_points"), planned_count)
        planned_count = max(planned_count, 1)
        chunk_id = f"chunk-{index + 1:06d}"
        chunks.append({
            "chunk_id": chunk_id,
            "ordinal": index + 1,
            "point_start": point_start,
            "point_count": planned_count,
            "artifact_path": os.path.join(artifact_dir, f"{chunk_id}{extension}"),
            "status": "planned",
        })
    return chunks


def _chunk_artifact_extension(output_format: str) -> str:
    normalized = str(output_format or "las").lower().replace(".", "_")
    if normalized in {"copc_laz", "copc"}:
        return ".copc.laz"
    if normalized == "laz":
        return ".laz"
    if normalized == "las":
        return ".las"
    return f".{normalized.replace('_', '.')}"


def _point_cloud_chunk_artifact_hints(chunking: dict, output_format: str) -> list[dict]:
    evidence = list(chunking.get("reasons") or [])
    if not evidence:
        evidence = [
            f"{chunking.get('chunk_count', 1)} planned chunk artifact(s)",
            f"output_format={output_format}",
        ]
    return [{
        "type": "point_cloud_processing",
        "value": "chunk_artifacts_planned",
        "domain": "lidar",
        "confidence": 0.88,
        "evidence": evidence,
    }]


def _safe_int(value, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


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


def _subprocess_executor(command: list[str], **kwargs):
    return subprocess.run(command, **kwargs)


def _pdal_runner_result(
    command: list | None,
    output_path: str | None,
    returncode: int | None,
    stdout: str,
    stderr: str,
    errors: list[str],
) -> dict:
    output_exists = bool(output_path and os.path.exists(output_path))
    return {
        "valid": not errors,
        "errors": errors,
        "command": command or [],
        "expected_output_path": output_path,
        "output_exists": output_exists,
        "returncode": returncode,
        "stdout": stdout,
        "stderr": stderr,
    }
