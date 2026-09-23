#!/usr/bin/env python3
"""Preflight and smoke-test entry point for the portable hydro runtime."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


APP_ROOT = Path(__file__).resolve().parents[1]
FIXTURES = APP_ROOT / "fixtures"
MANIFEST = APP_ROOT / "manifests" / "customer-data.example.json"


def ensure_runtime_directories() -> None:
    for variable, fallback in (
        ("HOME", "/tmp/hydro-home"),
        ("MPLCONFIGDIR", "/tmp/matplotlib"),
        ("XDG_CACHE_HOME", "/tmp/cache"),
    ):
        Path(os.environ.get(variable, fallback)).mkdir(parents=True, exist_ok=True)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def command_version(command: list[str]) -> str:
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    output = (result.stdout + result.stderr).strip().splitlines()
    return output[0][:200] if output else f"returncode={result.returncode}"


def check_core() -> dict[str, object]:
    swmm = Path(os.environ.get("ABU_DHABI_SWMM_EXECUTABLE", "/opt/swmm/bin/runswmm"))
    swmm_lib = Path(os.environ.get("ABU_DHABI_SWMM_LIBRARY", "/opt/swmm/lib/libswmm5.so"))
    checks: dict[str, object] = {
        "python": sys.version.split()[0],
        "swmm_executable": str(swmm),
        "swmm_executable_exists": swmm.is_file(),
        "swmm_library": str(swmm_lib),
        "swmm_library_exists": swmm_lib.is_file(),
    }
    try:
        import anuga  # type: ignore

        checks["anuga_version"] = str(getattr(anuga, "__version__", "unknown"))
        checks["anuga_imported"] = True
    except Exception as error:  # pragma: no cover - diagnostic path
        checks["anuga_imported"] = False
        checks["anuga_error"] = f"{type(error).__name__}: {error}"
    if swmm.is_file():
        checks["swmm_probe"] = command_version([str(swmm)])
    checks["data_root"] = os.environ.get("ABU_DHABI_HYDRO_DATA_ROOT", "/data/input")
    checks["run_root"] = os.environ.get("ABU_DHABI_HYDRO_RUN_ROOT", "/data/runs")
    checks["customer_data"] = check_customer_data()
    return checks


def check_customer_data() -> dict[str, object]:
    root = Path(os.environ.get("ABU_DHABI_HYDRO_DATA_ROOT", "/data/input")).expanduser()
    manifest_path = Path(
        os.environ.get("ABU_DHABI_HYDRO_DATA_MANIFEST", str(root / "manifest.json"))
    ).expanduser()
    if not manifest_path.is_file():
        return {
            "status": "not_configured",
            "root": str(root),
            "manifest": str(manifest_path),
            "message": "No customer manifest mounted; public smoke mode is still available.",
        }
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        return {
            "status": "invalid_manifest",
            "root": str(root),
            "manifest": str(manifest_path),
            "error": f"{type(error).__name__}: {error}",
        }
    artifacts = payload.get("artifacts") if isinstance(payload, dict) else None
    if not isinstance(artifacts, list):
        return {"status": "invalid_manifest", "manifest": str(manifest_path), "error": "artifacts_missing"}
    results = []
    failures = []
    for item in artifacts:
        if not isinstance(item, dict) or not item.get("relative_path"):
            failures.append("artifact_record_invalid")
            continue
        if item.get("required", True) is False:
            continue
        relative = Path(str(item["relative_path"]))
        if relative.is_absolute() or ".." in relative.parts:
            failures.append(f"unsafe_path:{relative}")
            continue
        path = root / relative
        record = {"id": item.get("id"), "path": str(path), "exists": path.is_file()}
        if path.is_file():
            record["size_bytes"] = path.stat().st_size
            if item.get("size_bytes") is not None:
                record["size_matches"] = record["size_bytes"] == int(item["size_bytes"])
        if path.is_file() and item.get("sha256"):
            observed = sha256(path)
            record["sha256"] = observed
            record["sha256_matches"] = observed == item["sha256"]
        if (
            not record["exists"]
            or record.get("size_matches") is False
            or record.get("sha256_matches") is False
        ):
            failures.append(str(item.get("id") or relative))
        results.append(record)
    return {
        "status": "ready" if not failures else "failed",
        "root": str(root),
        "manifest": str(manifest_path),
        "artifacts": results,
        "failures": failures,
    }


def run_swmm_smoke(output: Path) -> dict[str, object]:
    executable = Path(os.environ.get("ABU_DHABI_SWMM_EXECUTABLE", "/opt/swmm/bin/runswmm"))
    output.mkdir(parents=True, exist_ok=True)
    report = output / "swmm_smoke.rpt"
    binary = output / "swmm_smoke.out"
    result = subprocess.run(
        [str(executable), str(FIXTURES / "swmm_synthetic.inp"), str(report), str(binary)],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"swmm_smoke_failed:{result.returncode}:{result.stderr[-500:]}")
    if not report.is_file() or not binary.is_file():
        raise RuntimeError("swmm_smoke_outputs_missing")
    return {
        "solver": "epa_swmm",
        "status": "completed",
        "returncode": result.returncode,
        "report": str(report),
        "report_sha256": sha256(report),
        "binary_output": str(binary),
        "binary_sha256": sha256(binary),
    }


def run_anuga_smoke(output: Path) -> dict[str, object]:
    output.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        [sys.executable, str(FIXTURES / "anuga_smoke.py")],
        cwd=output,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"anuga_smoke_failed:{result.returncode}:{result.stderr[-1000:]}")
    summary_path = output / "anuga_smoke_summary.json"
    if not summary_path.is_file():
        raise RuntimeError("anuga_smoke_summary_missing")
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    if summary.get("status") != "completed" or not summary.get("finite"):
        raise RuntimeError("anuga_smoke_quality_failed")
    return {"solver": "anuga_2d", **summary}


def run_coupling_smoke(output: Path) -> dict[str, object]:
    import numpy as np

    output.mkdir(parents=True, exist_ok=True)
    fixture_root = output / "input"
    fixture_root.mkdir()
    grid = fixture_root / "terrain_grid.npz"
    np.savez_compressed(
        grid,
        values=np.zeros((3, 3), dtype=np.float32),
        x=np.asarray([0.0, 50.0, 100.0], dtype=np.float64),
        y=np.asarray([100.0, 50.0, 0.0], dtype=np.float64),
        land_mask=np.ones((2, 2), dtype=bool),
    )
    (fixture_root / "grid_metadata.json").write_text(
        json.dumps({"selected_node_ids": ["J1"]}, indent=2) + "\n",
        encoding="utf-8",
    )
    pilot = APP_ROOT / "scripts" / "run_abu_dhabi_swmm_anuga_bidirectional_pilot.py"

    def execute(mode: str) -> dict[str, object]:
        run_root = output / mode
        result = subprocess.run(
            [
                sys.executable,
                str(pilot),
                "--swmm-inp",
                str(FIXTURES / "swmm_synthetic.inp"),
                "--grid",
                str(grid),
                "--output",
                str(run_root),
                "--swmm-library",
                os.environ.get("ABU_DHABI_SWMM_LIBRARY", "/opt/swmm/lib/libswmm5.so"),
                "--duration-seconds",
                "600",
                "--window-seconds",
                "300",
                "--coupling-mode",
                mode,
                "--binding-limit",
                "1",
                "--interface-detail-limit",
                "1",
                "--run-id",
                f"portable-{mode}-smoke",
                "--quiet",
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=180,
        )
        if result.returncode != 0:
            raise RuntimeError(
                f"coupling_smoke_failed:{mode}:{result.returncode}:"
                f"{(result.stderr or result.stdout)[-1500:]}"
            )
        receipt_path = run_root / "bidirectional_coupling_receipt.json"
        summary_path = run_root / "delivery_summary.json"
        if not receipt_path.is_file() or not summary_path.is_file():
            raise RuntimeError(f"coupling_smoke_outputs_missing:{mode}")
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        if receipt.get("status") != "completed" or len(receipt.get("windows") or []) != 2:
            raise RuntimeError(f"coupling_smoke_receipt_invalid:{mode}")
        for relative in (
            "maximum_depth_wgs84.geojson",
            "temporal_snapshots/manifest.json",
            "abu_dhabi_swmm_anuga_bidirectional_pilot.sww",
        ):
            if not (run_root / relative).is_file():
                raise RuntimeError(f"coupling_smoke_artifact_missing:{mode}:{relative}")
        reverse_volume = sum(
            float(item.get("total_anuga_to_swmm_m3", 0.0))
            for item in receipt.get("windows") or []
        )
        if mode == "one_way_swmm_to_anuga" and abs(reverse_volume) > 1.0e-12:
            raise RuntimeError("one_way_coupling_smoke_reverse_volume_nonzero")
        return {
            "status": "completed",
            "coupling_mode": mode,
            "window_count": len(receipt["windows"]),
            "interface_count": len(receipt.get("interface_bindings") or []),
            "quality_passed": bool(receipt.get("quality_passed")),
            "receipt_sha256": sha256(receipt_path),
            "maximum_depth_m": summary.get("results", {}).get("maximum_depth_m"),
            "reverse_volume_m3": reverse_volume,
            "map_outputs_created": True,
        }

    one_way = execute("one_way_swmm_to_anuga")
    two_way = execute("two_way_swmm_anuga")
    return {
        "solver": "epa_swmm_anuga_synchronous_coupling",
        "status": "completed",
        "quality_passed": bool(one_way["quality_passed"] and two_way["quality_passed"]),
        "one_way": one_way,
        "two_way": two_way,
    }


def run_smoke() -> dict[str, object]:
    root = Path(os.environ.get("ABU_DHABI_HYDRO_RUN_ROOT", "/data/runs"))
    with tempfile.TemporaryDirectory(prefix="abu-hydro-smoke-", dir=root if root.is_dir() else None) as temporary:
        output = Path(temporary)
        result = {
            "schema": "gwm.abu_dhabi_flood.hydrodynamics_smoke_receipt.v1",
            "status": "completed",
            "swmm": run_swmm_smoke(output / "swmm"),
            "anuga": run_anuga_smoke(output / "anuga"),
            "coupling": run_coupling_smoke(output / "coupling"),
        }
    return result


def main() -> int:
    ensure_runtime_directories()
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="check installed runtime and paths")
    parser.add_argument("--smoke", action="store_true", help="run the SWMM and ANUGA fixtures")
    parser.add_argument(
        "--require-customer-data",
        action="store_true",
        help="fail unless the mounted customer manifest and all required hashes pass",
    )
    args = parser.parse_args()
    if not args.check and not args.smoke:
        parser.print_help()
        return 0
    payload: dict[str, object] = {}
    if args.check:
        payload["preflight"] = check_core()
        if args.require_customer_data and payload["preflight"]["customer_data"].get("status") != "ready":
            print(json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True))
            return 2
    if args.smoke:
        payload["smoke"] = run_smoke()
    print(json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
