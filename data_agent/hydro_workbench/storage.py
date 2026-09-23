"""Filesystem contract for shared PVC/object-store-backed run artifacts."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

DEFAULT_ROOT = Path(os.environ.get("HYDRO_RUN_ROOT", "/data/runs"))


def run_dir(run_id: str, root: Path | None = None) -> Path:
    if not run_id or "/" in run_id or ".." in run_id:
        raise ValueError("invalid_run_id")
    return (root or DEFAULT_ROOT) / run_id


def atomic_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def write_manifest(manifest: dict[str, Any], root: Path | None = None) -> Path:
    directory = run_dir(str(manifest["run_id"]), root)
    path = directory / "manifest.json"
    if path.exists():
        raise FileExistsError(f"run_already_exists:{manifest['run_id']}")
    atomic_json(path, manifest)
    atomic_json(
        directory / "status.json",
        {
            "run_id": manifest["run_id"],
            "status": "queued",
            "progress": 0,
            "message": "manifest_frozen",
        },
    )
    return path


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def read_manifest(run_id: str, root: Path | None = None) -> dict[str, Any]:
    return read_json(run_dir(run_id, root) / "manifest.json")


def read_status(run_id: str, root: Path | None = None) -> dict[str, Any]:
    path = run_dir(run_id, root) / "status.json"
    return read_json(path) if path.exists() else {"run_id": run_id, "status": "unknown"}


def update_status(
    run_id: str, status: str, *, progress: int, root: Path | None = None, **extra: Any
) -> None:
    payload = {
        "run_id": run_id,
        "status": status,
        "progress": max(0, min(100, int(progress))),
        **extra,
    }
    atomic_json(run_dir(run_id, root) / "status.json", payload)
