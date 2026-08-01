#!/usr/bin/env python3
"""Build a diagnostic t-route MC runtime with explicit secant carry initialization."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import difflib
import hashlib
import json
from pathlib import Path
import platform
import shutil
import subprocess
from typing import Any

if __package__:
    from scripts import build_geotransport_troute_mc_runtime as official
else:
    import build_geotransport_troute_mc_runtime as official


REPO_ROOT = official.REPO_ROOT
DEFAULT_SOURCE_MANIFEST = official.DEFAULT_SOURCE_MANIFEST
DEFAULT_OUTPUT = (
    REPO_ROOT
    / "data/geotransport_v0_1/t_route_mc_initialized_diagnostic_runtime"
)
SCHEMA = "gwm.geotransport.t_route_mc_initialized_diagnostic_runtime.v1"
PATCH_ID = "explicit_secant_carry_initialization_v1"
CORE_SOURCE_ID = "mc_single_segment_kernel"
EXPECTED_CORE_SOURCE_SHA256 = (
    "1c0e47b3528c3fdf20c960408e41138921cb903e5035bd19e6c4e68f8f4b46da"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-manifest", type=Path, default=DEFAULT_SOURCE_MANIFEST)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--compiler", default="gfortran")
    return parser.parse_args()


def derive_initialized_source(source: str) -> tuple[str, list[dict[str, str]]]:
    changes = []
    derived = _replace_once(
        source,
        (
            "    real(prec) :: R, twl, h_1, h, h_0, Qj, Qj_0\n\n"
            "    ! qdc = 0.0\n"
        ),
        (
            "    real(prec) :: R, twl, h_1, h, h_0, Qj, Qj_0\n\n"
            "    ! Diagnostic initialization: make intended secant carry state defined.\n"
            "    qdc = 0.0_prec\n"
            "    Qj = 0.0_prec\n"
            "    Qj_0 = 0.0_prec\n"
            "    C1 = 0.0_prec\n"
            "    C2 = 0.0_prec\n"
            "    C3 = 0.0_prec\n"
            "    C4 = 0.0_prec\n"
            "    X = 0.5_prec\n\n"
            "    ! qdc = 0.0\n"
        ),
        change_id="initialize_caller_secant_carry_and_qdc",
        changes=changes,
    )
    derived = _replace_once(
        derived,
        "    real(prec), intent(out) :: Qj, C1, C2, C3, C4, X\n",
        (
            "    real(prec), intent(inout) :: Qj, C1, C2, C3, C4\n"
            "    real(prec), intent(out) :: X\n"
        ),
        change_id="declare_secant_carry_as_inout",
        changes=changes,
    )
    if derived == source or len(changes) != 2:
        raise ValueError("t_route_mc_initialized_derivation_incomplete")
    return derived, changes


def build_runtime(
    *,
    source_manifest_path: Path = DEFAULT_SOURCE_MANIFEST,
    output_root: Path = DEFAULT_OUTPUT,
    compiler: str = "gfortran",
) -> dict[str, Any]:
    manifest_body = source_manifest_path.read_bytes()
    manifest = json.loads(manifest_body)
    if (
        manifest.get("schema") != official.SOURCE_SCHEMA
        or manifest.get("mode") != "values"
        or manifest.get("commit") != official.T_ROUTE_COMMIT
    ):
        raise ValueError("t_route_mc_initialized_source_manifest_invalid")
    by_id = {str(item["source_id"]): item for item in manifest["artifacts"]}
    originals = {
        source_id: official._read_verified(by_id[source_id])
        for source_id in official.SOURCE_IDS
    }
    core_path, core_body = originals[CORE_SOURCE_ID]
    if hashlib.sha256(core_body).hexdigest() != EXPECTED_CORE_SOURCE_SHA256:
        raise ValueError("t_route_mc_initialized_core_source_identity_mismatch")
    derived_text, changes = derive_initialized_source(core_body.decode("utf-8"))
    derived_body = derived_text.encode("utf-8")

    compiler_path = shutil.which(compiler)
    if compiler_path is None:
        raise RuntimeError("t_route_mc_initialized_fortran_compiler_unavailable")
    compiler_version = subprocess.run(
        [compiler_path, "--version"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()[0]

    source_root = output_root / "source"
    source_root.mkdir(parents=True, exist_ok=True)
    derived_path = source_root / core_path.name
    derived_path.write_bytes(derived_body)
    diff_text = "".join(
        difflib.unified_diff(
            core_body.decode("utf-8").splitlines(keepends=True),
            derived_text.splitlines(keepends=True),
            fromfile=f"official/{core_path.name}",
            tofile=f"derived/{core_path.name}",
        )
    )
    patch_path = output_root / "initialized_source.patch"
    patch_body = diff_text.encode("utf-8")
    patch_path.write_bytes(patch_body)

    compile_sources = []
    for source_id in official.SOURCE_IDS:
        path, _ = originals[source_id]
        compile_sources.append(derived_path if source_id == CORE_SOURCE_ID else path)
    library = output_root / "libtroute_mc_initialized_diagnostic.so"
    command = [
        compiler_path,
        "-shared",
        "-fPIC",
        "-O2",
        *(str(path) for path in compile_sources),
        "-o",
        str(library),
    ]
    subprocess.run(command, check=True, cwd=output_root)
    library_body = library.read_bytes()
    report = {
        "schema": SCHEMA,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_commit": official.T_ROUTE_COMMIT,
        "source_manifest": _artifact(source_manifest_path, manifest_body),
        "official_core_source": _artifact(core_path, core_body),
        "derived_core_source": _artifact(derived_path, derived_body),
        "source_patch": _artifact(patch_path, patch_body),
        "patch_id": PATCH_ID,
        "patch_contract": changes,
        "official_source_unmodified": False,
        "derived_diagnostic_only": True,
        "compiler": {
            "executable": compiler_path,
            "version": compiler_version,
            "flags": ["-shared", "-fPIC", "-O2"],
        },
        "platform": {
            "system": platform.system(),
            "machine": platform.machine(),
            "python": platform.python_version(),
        },
        "entrypoint": "c_muskingcungenwm",
        "library_artifact": _artifact(library, library_body),
        "claim_boundary": {
            "derived_runtime_built": True,
            "official_runtime": False,
            "initialization_defined": True,
            "method_correctness_established": False,
            "professional_baseline_eligible": False,
            "geospatial_kernel_validated": False,
        },
    }
    (output_root / "build_manifest.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return report


def _replace_once(
    source: str,
    old: str,
    new: str,
    *,
    change_id: str,
    changes: list[dict[str, str]],
) -> str:
    if source.count(old) != 1:
        raise ValueError(f"t_route_mc_initialized_patch_anchor_invalid:{change_id}")
    changes.append(
        {
            "change_id": change_id,
            "old_sha256": hashlib.sha256(old.encode("utf-8")).hexdigest(),
            "new_sha256": hashlib.sha256(new.encode("utf-8")).hexdigest(),
        }
    )
    return source.replace(old, new, 1)


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
    report = build_runtime(
        source_manifest_path=args.source_manifest,
        output_root=args.output,
        compiler=args.compiler,
    )
    print(json.dumps(report["library_artifact"], sort_keys=True))
    print(f"patch_id={PATCH_ID}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
