"""Smoke test a real PDAL pipeline through the MMFE Docker executor."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from data_agent.fusion.pdal_pipeline import (
    build_docker_pdal_executor,
    build_docker_pdal_runner_spec,
    build_pdal_runner_spec,
    run_pdal_pipeline,
    validate_pdal_pipeline_spec,
    write_pdal_pipeline_spec,
)


DEFAULT_OUTPUT = Path(".tmp/mmfe-pdal-smoke/faux_points.las")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-path", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--image", default=os.environ.get("MMFE_PDAL_DOCKER_IMAGE", "pdal/pdal:latest"))
    parser.add_argument("--point-count", type=int, default=25)
    parser.add_argument("--timeout-s", type=int, default=180)
    args = parser.parse_args()

    summary = run_smoke(args)
    print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))


def run_smoke(args: argparse.Namespace) -> dict[str, Any]:
    output_path = args.output_path
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.exists():
        output_path.unlink()
    pipeline_spec = _build_faux_las_pipeline(output_path, args.point_count)
    errors = validate_pdal_pipeline_spec(pipeline_spec)
    if errors:
        _exit_error("invalid PDAL pipeline spec", {"errors": errors})

    pipeline_path = Path(write_pdal_pipeline_spec(pipeline_spec, str(output_path)))
    workspace_dir = Path.cwd()
    runner = build_pdal_runner_spec(
        pipeline_spec,
        str(pipeline_path),
        timeout_s=args.timeout_s,
        metadata={"smoke": "mmfe_pdal_docker"},
    )
    docker_runner = build_docker_pdal_runner_spec(
        runner,
        image=args.image,
        workspace_dir=str(workspace_dir),
    )
    executor = build_docker_pdal_executor(
        image=args.image,
        workspace_dir=str(workspace_dir),
    )
    result = run_pdal_pipeline(runner, executor=executor)
    if not result["valid"]:
        _exit_error("PDAL Docker smoke failed", result)

    info = _run_pdal_info(args.image, workspace_dir, output_path)
    point_count = int(info.get("summary", {}).get("num_points") or 0)
    if point_count != args.point_count:
        _exit_error(
            "unexpected PDAL output point count",
            {"expected": args.point_count, "actual": point_count, "info": info},
        )
    return {
        "status": "ok",
        "image": args.image,
        "pdal_version": _pdal_version(args.image),
        "pipeline_path": str(pipeline_path),
        "output_path": str(output_path),
        "output_size_bytes": output_path.stat().st_size,
        "point_count": point_count,
        "runner_result": result,
        "docker_runner": docker_runner,
        "info_summary": info.get("summary", {}),
    }


def _build_faux_las_pipeline(output_path: Path, point_count: int) -> dict[str, Any]:
    return {
        "schema": "mmfe.pdal_pipeline.v1",
        "created_at": "2026-06-17T00:00:00+00:00",
        "execution_mode": "external_pdal",
        "pipeline_task": "pdal_faux_las_smoke",
        "source": {
            "path": "readers.faux",
            "format": "faux",
            "compressed": False,
        },
        "output_path": str(output_path),
        "chunking": {"required": False, "strategy": "single_pass", "chunk_count": 1},
        "pipeline": [
            {
                "type": "readers.faux",
                "bounds": "([0,10],[0,10],[0,5])",
                "count": int(point_count),
                "mode": "ramp",
            },
            {
                "type": "writers.las",
                "filename": str(output_path),
                "minor_version": 4,
                "dataformat_id": 6,
            },
        ],
        "semantic_hints": [
            {
                "type": "point_cloud_processing",
                "value": "pdal_docker_smoke",
                "domain": "lidar",
                "confidence": 0.95,
                "evidence": ["readers.faux -> writers.las executed by PDAL Docker image"],
            }
        ],
    }


def _run_pdal_info(image: str, workspace_dir: Path, output_path: Path) -> dict[str, Any]:
    import subprocess

    command = [
        "docker",
        "run",
        "--rm",
        "-v",
        f"{workspace_dir}:/workspace",
        "-w",
        "/workspace",
        image,
        "pdal",
        "info",
        "--summary",
        _container_path(workspace_dir, output_path),
    ]
    completed = subprocess.run(command, capture_output=True, text=True, timeout=120)
    if completed.returncode != 0:
        _exit_error(
            "pdal info failed",
            {"returncode": completed.returncode, "stdout": completed.stdout, "stderr": completed.stderr},
        )
    return json.loads(completed.stdout)


def _pdal_version(image: str) -> str:
    import subprocess

    completed = subprocess.run(
        ["docker", "run", "--rm", image, "pdal", "--version"],
        capture_output=True,
        text=True,
        timeout=120,
    )
    if completed.returncode != 0:
        return ""
    return completed.stdout.strip()


def _container_path(workspace_dir: Path, path: Path) -> str:
    absolute = path.resolve()
    rel = absolute.relative_to(workspace_dir.resolve())
    return "/workspace/" + str(rel).replace(os.sep, "/")


def _exit_error(message: str, payload: dict[str, Any]) -> None:
    print(
        json.dumps(
            {"status": "error", "message": message, "details": payload},
            ensure_ascii=False,
            indent=2,
            default=str,
        ),
        file=sys.stderr,
    )
    raise SystemExit(1)


if __name__ == "__main__":
    main()
