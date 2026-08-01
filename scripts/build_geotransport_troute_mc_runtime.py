#!/usr/bin/env python3
"""Build a shared library from the verified official t-route MC source bundle."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform
import shutil
import subprocess
from typing import Any, Mapping


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SOURCE_MANIFEST = (
    REPO_ROOT
    / "data/geotransport_v0_1/t_route_mc_source_audit/acquisition_manifest.json"
)
DEFAULT_OUTPUT = REPO_ROOT / "data/geotransport_v0_1/t_route_mc_runtime"
SOURCE_SCHEMA = "gwm.geotransport.t_route_mc_source_audit.v1"
BUILD_SCHEMA = "gwm.geotransport.t_route_mc_runtime_build.v1"
T_ROUTE_COMMIT = "12a8eae0cdfed437143c590659fa7077605a5e70"
SOURCE_IDS = (
    "precision_module",
    "mc_single_segment_kernel",
    "mc_c_binding",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-manifest", type=Path, default=DEFAULT_SOURCE_MANIFEST)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--compiler", default="gfortran")
    return parser.parse_args()


def build_runtime(
    *,
    source_manifest_path: Path = DEFAULT_SOURCE_MANIFEST,
    output_root: Path = DEFAULT_OUTPUT,
    compiler: str = "gfortran",
) -> dict[str, Any]:
    body = source_manifest_path.read_bytes()
    manifest = json.loads(body)
    if (
        manifest.get("schema") != SOURCE_SCHEMA
        or manifest.get("mode") != "values"
        or manifest.get("commit") != T_ROUTE_COMMIT
    ):
        raise ValueError("t_route_mc_build_source_manifest_invalid")
    by_id = {str(item["source_id"]): item for item in manifest["artifacts"]}
    sources = [_read_verified(by_id[source_id]) for source_id in SOURCE_IDS]
    compiler_path = shutil.which(compiler)
    if compiler_path is None:
        raise RuntimeError("t_route_mc_build_fortran_compiler_unavailable")
    compiler_version = subprocess.run(
        [compiler_path, "--version"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()[0]
    output_root.mkdir(parents=True, exist_ok=True)
    library = output_root / "libtroute_mc_12a8eae.so"
    command = [
        compiler_path,
        "-shared",
        "-fPIC",
        "-O2",
        *(str(path) for path, _ in sources),
        "-o",
        str(library),
    ]
    subprocess.run(command, check=True, cwd=output_root)
    library_body = library.read_bytes()
    result = {
        "schema": BUILD_SCHEMA,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_commit": T_ROUTE_COMMIT,
        "source_manifest": _artifact(source_manifest_path, body),
        "source_artifacts": [
            _artifact(path, source_body) for path, source_body in sources
        ],
        "official_source_unmodified": True,
        "compiler": {
            "executable": compiler_path,
            "version": compiler_version,
        },
        "platform": {
            "system": platform.system(),
            "machine": platform.machine(),
            "python": platform.python_version(),
        },
        "entrypoint": "c_muskingcungenwm",
        "library_artifact": _artifact(library, library_body),
        "claim_boundary": {
            "runtime_built": True,
            "official_kernel_executed": False,
            "center_hill_execution_admitted": False,
            "geospatial_kernel_validated": False,
        },
    }
    (output_root / "build_manifest.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return result


def _read_verified(descriptor: Mapping[str, Any]) -> tuple[Path, bytes]:
    path = (REPO_ROOT / str(descriptor["path"])).resolve()
    try:
        path.relative_to(REPO_ROOT)
    except ValueError as exc:
        raise ValueError("t_route_mc_build_source_outside_repository") from exc
    body = path.read_bytes()
    if (
        hashlib.sha256(body).hexdigest() != descriptor.get("sha256")
        or len(body) != descriptor.get("size_bytes")
    ):
        raise ValueError("t_route_mc_build_source_identity_mismatch")
    return path, body


def _artifact(path: Path, body: bytes) -> dict[str, Any]:
    resolved = path.resolve()
    try:
        display = resolved.relative_to(REPO_ROOT).as_posix()
    except ValueError:
        display = resolved.as_posix()
    return {
        "path": display,
        "sha256": hashlib.sha256(body).hexdigest(),
        "size_bytes": len(body),
    }


def main() -> int:
    args = parse_args()
    result = build_runtime(
        source_manifest_path=args.source_manifest,
        output_root=args.output,
        compiler=args.compiler,
    )
    print(json.dumps(result["library_artifact"], sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
