"""Read-only host preflight checks for the Gemma 4 finals demo."""

from __future__ import annotations

import ast
import json
import tomllib
import urllib.request
from pathlib import Path
from typing import Any

from .paper9_agent_governance import (
    EXPECTED_ALGORITHM_VERSION,
    EXPECTED_PACKAGE_VERSION,
)


def inspect_finals_host(
    *,
    paper9_repo: str | Path,
    bishan_runs: str | Path,
    model_tag: str,
    ollama_tags: list[str],
) -> dict[str, Any]:
    """Inspect local resources without importing Paper9 or changing state."""

    repo = Path(paper9_repo).expanduser().resolve()
    runs = Path(bishan_runs).expanduser().resolve()
    prepared = runs / "prepared"
    ensemble = prepared / "ensemble_seed0"
    package_version = _read_project_version(repo / "pyproject.toml")
    algorithm_version = _read_python_constant(
        repo / "src" / "paper9_mnr" / "version.py", "ALGORITHM_VERSION"
    )
    dltb = prepared / "dem_slope_analysis" / "output" / "DLTB_with_slope.shp"
    onnx_members = sorted(ensemble.rglob("*.onnx")) if ensemble.is_dir() else []

    checks = [
        _check("paper9_repo", repo.is_dir(), str(repo)),
        _check(
            "paper9_package_version",
            package_version == EXPECTED_PACKAGE_VERSION,
            package_version,
            expected=EXPECTED_PACKAGE_VERSION,
        ),
        _check(
            "paper9_algorithm_version",
            algorithm_version == EXPECTED_ALGORITHM_VERSION,
            algorithm_version,
            expected=EXPECTED_ALGORITHM_VERSION,
        ),
        _check("bishan_prepared", dltb.is_file(), str(dltb)),
        _check(
            "bishan_onnx_ensemble",
            bool(onnx_members),
            {"directory": str(ensemble), "member_count": len(onnx_members)},
        ),
        _check(
            "ollama_model_tag",
            model_tag in ollama_tags,
            {"required": model_tag, "available": sorted(ollama_tags)},
        ),
    ]
    failed = [check["name"] for check in checks if not check["passed"]]
    return {
        "schema_version": "gemma4.finals_preflight.v1",
        "ready": not failed,
        "failed_checks": failed,
        "checks": checks,
    }


def fetch_ollama_tags(api_base: str, *, timeout: float = 5.0) -> list[str]:
    """Return exact model tags from an Ollama server."""

    url = f"{api_base.rstrip('/')}/api/tags"
    with urllib.request.urlopen(url, timeout=timeout) as response:  # noqa: S310
        payload = json.load(response)
    return [
        str(model.get("name"))
        for model in payload.get("models", [])
        if model.get("name")
    ]


def _read_project_version(path: Path) -> str | None:
    if not path.is_file():
        return None
    try:
        with path.open("rb") as handle:
            return str(tomllib.load(handle).get("project", {}).get("version") or "") or None
    except (OSError, tomllib.TOMLDecodeError):
        return None


def _read_python_constant(path: Path, name: str) -> str | None:
    if not path.is_file():
        return None
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError, UnicodeError):
        return None
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(target, ast.Name) and target.id == name for target in node.targets):
            continue
        try:
            value = ast.literal_eval(node.value)
        except (ValueError, TypeError):
            return None
        return str(value)
    return None


def _check(
    name: str,
    passed: bool,
    actual: Any,
    *,
    expected: Any | None = None,
) -> dict[str, Any]:
    result = {"name": name, "passed": bool(passed), "actual": actual}
    if expected is not None:
        result["expected"] = expected
    return result
