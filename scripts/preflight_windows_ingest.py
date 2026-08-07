#!/usr/bin/env python3
"""Preflight a GIS Data Agent Windows physical-isolation installation.

The command validates the GIS Data Agent's bundled Python GIS runtime first.
ArcGIS Pro, ArcPy MCP and external GDAL commands are optional and are never a
production prerequisite. It emits machine-readable evidence and a human report.
Production mode validates that a Ningxia workbook/EA baseline is installed.
It does not block the host merely because the baseline still requires
per-dataset physical schema checks; those checks run when each asset arrives.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import platform
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _check(
    checks: list[dict[str, Any]],
    name: str,
    severity: str,
    status: str,
    detail: str,
    remediation: str = "",
) -> None:
    checks.append(
        {
            "name": name,
            "severity": severity,
            "status": status,
            "detail": detail,
            "remediation": remediation,
        }
    )


def _executable(value: str | None, fallback: str) -> str | None:
    configured = (value or "").strip()
    if configured:
        return configured if Path(configured).is_file() else None
    return shutil.which(fallback)


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)))
    except ValueError:
        return default


def _path_check(
    checks: list[dict[str, Any]], name: str, path: Path, create: bool, required: bool = True
) -> None:
    try:
        if not path.exists() and create:
            path.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            _check(
                checks,
                name,
                "critical" if required else "warning",
                "fail" if required else "warn",
                f"directory does not exist: {path}",
                "Create it and grant the service account read/write ACL.",
            )
            return
        if not path.is_dir():
            _check(
                checks,
                name,
                "critical",
                "fail",
                f"not a directory: {path}",
                "Point the setting to a directory.",
            )
            return
        probe = path / ".gda_preflight_write_test"
        probe.write_text("ok", encoding="ascii")
        probe.unlink()
        _check(checks, name, "info", "pass", f"read/write available: {path}")
    except OSError as exc:
        _check(
            checks,
            name,
            "critical" if required else "warning",
            "fail" if required else "warn",
            f"directory is not writable: {path}: {exc}",
            "Fix ACL, disk quota or endpoint protection policy.",
        )


def run_preflight(args: argparse.Namespace) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []
    lake = (
        Path(args.lake or os.environ.get("GDA_FILE_LAKE_ROOT", "./file_lake"))
        .expanduser()
        .resolve()
    )
    inbox = (
        Path(args.inbox or os.environ.get("GDA_FILE_LAKE_INBOX", "./file_lake/inbox"))
        .expanduser()
        .resolve()
    )
    contract_path = (
        args.contracts
        or os.environ.get("GDA_STANDARD_CONTRACTS", "")
        or os.environ.get("GDA_STANDARD_CONTRACT_XLSX", "")
    )
    ontology_path = (
        Path(args.ontology or "data_agent/ontology/packages/natural_resource_one_map/active.json")
        .expanduser()
        .resolve()
    )

    _check(
        checks,
        "python_version",
        "critical",
        "pass" if sys.version_info >= (3, 11) else "fail",
        platform.python_version(),
        "Install the supported Python 3.11+ runtime.",
    )
    _check(
        checks,
        "platform",
        "warning",
        "pass" if platform.system() == "Windows" else "warn",
        platform.platform(),
        "The production worker must run on the Windows host; non-Windows is development-only.",
    )
    for module in ("data_agent.offline_ingest", "data_agent.standard_contracts"):
        available = importlib.util.find_spec(module) is not None
        _check(
            checks,
            f"python_module:{module}",
            "critical",
            "pass" if available else "fail",
            "importable" if available else "not importable",
            "Install the GIS Data Agent package and run from its deployment directory.",
        )

    _path_check(checks, "lake_root", lake, args.create_directories)
    _path_check(checks, "lake_inbox", inbox, args.create_directories)
    for name in ("raw", "runs", "standardized", "materialized", "diagnostics", "sessions"):
        _path_check(checks, f"lake_{name}", lake / name, args.create_directories)
    log_dir = Path(os.environ.get("GDA_LOG_DIR", str(lake / "logs"))).expanduser().resolve()
    _path_check(checks, "log_dir", log_dir, args.create_directories)

    usage = shutil.disk_usage(lake.parent)
    min_free = int(args.min_free_gb * 1024**3)
    _check(
        checks,
        "disk_free",
        "critical",
        "pass" if usage.free >= min_free else "fail",
        f"{usage.free / 1024**3:.1f} GiB free; required >= {args.min_free_gb:.1f} GiB",
        "Provision separate raw/materialized/backup capacity; raw assets are immutable.",
    )
    _check(
        checks,
        "path_length",
        "warning",
        "pass" if max(len(str(p)) for p in (lake, inbox, log_dir)) < 220 else "warn",
        f"max configured path length={max(len(str(p)) for p in (lake, inbox, log_dir))}",
        "Keep the lake and inbox near a drive root to avoid Windows MAX_PATH failures.",
    )

    ogrinfo = _executable(os.environ.get("GDA_OGRINFO_PATH"), "ogrinfo")
    ogr2ogr = _executable(os.environ.get("GDA_OGR2OGR_PATH"), "ogr2ogr")
    gdal_translate = _executable(os.environ.get("GDA_GDAL_TRANSLATE_PATH"), "gdal_translate")
    try:
        from data_agent.local_gis_runtime import runtime_info

        gis_runtime = runtime_info()
    except Exception as exc:
        gis_runtime = {"adapter": "python_gis_runtime", "error": str(exc)}
    _check(
        checks,
        "python_gis_runtime",
        "critical",
        "pass" if gis_runtime.get("filegdb_reader") else "fail",
        json.dumps(gis_runtime, ensure_ascii=False, default=str),
        "Install the versioned offline GIS wheelhouse (pyogrio/geopandas/rasterio/pyarrow).",
    )
    _check(
        checks,
        "filegdb_reader",
        "critical",
        "pass" if gis_runtime.get("filegdb_reader") else "fail",
        "bundled pyogrio/OpenFileGDB"
        if gis_runtime.get("filegdb_reader")
        else "bundled FileGDB reader missing",
        "Install the versioned offline GIS wheelhouse; ArcPy is not required.",
    )
    _check(
        checks,
        "vector_materializer",
        "critical",
        "pass" if gis_runtime.get("vector_writer") else "fail",
        "bundled geopandas/pyogrio/pyarrow"
        if gis_runtime.get("vector_writer")
        else "bundled vector writer missing",
        "Install the versioned offline GIS wheelhouse; ogr2ogr is optional.",
    )
    _check(
        checks,
        "raster_materializer",
        "critical",
        "pass" if gis_runtime.get("raster_cog_writer") else "fail",
        "bundled rasterio/GDAL COG writer"
        if gis_runtime.get("raster_cog_writer")
        else "bundled raster writer missing",
        "Install the versioned offline GIS wheelhouse; gdal_translate is optional.",
    )
    _check(
        checks,
        "optional_external_gdal",
        "info",
        "pass",
        f"ogrinfo={ogrinfo or 'not installed'}; ogr2ogr={ogr2ogr or 'not installed'}; "
        f"gdal_translate={gdal_translate or 'not installed'}",
        "External GDAL may be used for very large jobs, but is not a production prerequisite.",
    )
    for var in ("GDA_PROJ_DATA", "GDA_GDAL_DATA"):
        value = os.environ.get(var, "").strip()
        if value:
            _check(
                checks,
                var,
                "info",
                "pass" if Path(value).exists() else "fail",
                value,
                "Set the GDAL/PROJ data directory shipped with the same GDAL build.",
            )
        else:
            _check(
                checks,
                var,
                "warning",
                "warn",
                "not configured; GDAL may use its compiled default",
                "Set an absolute path for an isolated Windows installation.",
            )

    contract = None
    if not contract_path:
        _check(
            checks,
            "standard_contract",
            "critical",
            "fail",
            "GDA_STANDARD_CONTRACTS is not configured",
            "Install the versioned JSON contract produced by compile_nx_standard_contract.py.",
        )
    else:
        path = Path(contract_path).expanduser().resolve()
        if not path.exists():
            _check(
                checks,
                "standard_contract",
                "critical",
                "fail",
                f"missing: {path}",
                (
                    "Copy the Ningxia workbook baseline or compiled JSON catalog "
                    "to the protected configuration directory."
                ),
            )
        else:
            try:
                from data_agent.standard_contracts import (
                    load_contract_catalog,
                    validate_contract_catalog,
                )

                contract = load_contract_catalog(path)
                # Authority review is a per-dataset publication concern. The
                # host must be able to start with the supplied Ningxia baseline.
                blockers = validate_contract_catalog(contract, require_authoritative=False)
                _check(
                    checks,
                    "standard_contract",
                    "critical" if blockers else "info",
                    "fail" if blockers else "pass",
                    (
                        f"{path}; {len(contract.get('contracts') or {})} contracts; "
                        f"{len(blockers)} blocker(s)"
                    ),
                    (
                        "Repair the Ningxia workbook/EA baseline JSON before starting ingestion."
                        if blockers
                        else ""
                    ),
                )
                _check(checks, "standard_contract_hash", "info", "pass", _sha256(path))
            except Exception as exc:
                _check(
                    checks,
                    "standard_contract",
                    "critical",
                    "fail",
                    str(exc),
                    "Regenerate the contract and validate JSON encoding.",
                )

    _check(
        checks,
        "ontology_package",
        "critical",
        "pass" if ontology_path.is_file() else "fail",
        str(ontology_path),
        "Install the versioned ontology 2.3 package before enabling ontology binding.",
    )
    if os.environ.get("GDA_STANDARDIZED_VECTOR_FORMAT", "Parquet") == "PostgreSQL":
        _check(
            checks,
            "postgis_dsn",
            "critical",
            "pass" if os.environ.get("GDA_POSTGIS_DSN") else "fail",
            "configured" if os.environ.get("GDA_POSTGIS_DSN") else "missing",
            "Set GDA_POSTGIS_DSN using a protected secret store.",
        )
    _check(
        checks,
        "log_rotation",
        "warning",
        "pass" if _env_int("GDA_LOG_ROTATION_MB", 50) > 0 else "fail",
        (
            f"rotation_mb={os.environ.get('GDA_LOG_ROTATION_MB', '50')}; "
            f"backups={os.environ.get('GDA_LOG_BACKUP_COUNT', '14')}"
        ),
        "Use non-zero rotation and retain logs for the agreed audit period.",
    )

    failures = [
        item for item in checks if item["status"] == "fail" and item["severity"] == "critical"
    ]
    warnings = [item for item in checks if item["status"] in {"fail", "warn"}]
    return {
        "schema_version": "gda.windows-ingest-preflight.v1",
        "generated_at": _utc_now(),
        "mode": args.mode,
        "host": {"platform": platform.platform(), "python": platform.python_version()},
        "paths": {
            "lake": str(lake),
            "inbox": str(inbox),
            "logs": str(log_dir),
            "ontology": str(ontology_path),
        },
        "contract": {
            "path": str(Path(contract_path).expanduser().resolve()) if contract_path else None,
            "authority": contract.get("authority") if contract else None,
            "production_ready": contract.get("production_ready") if contract else False,
            "runtime_baseline_ready": contract.get("runtime_baseline_ready", True)
            if contract
            else False,
            "validation_policy": "per_dataset_schema_quality_gate",
        },
        "checks": checks,
        "status": "blocked" if failures else "ready_with_warnings" if warnings else "ready",
        "critical_failures": len(failures),
        "warnings": len(warnings),
    }


def _sha256(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Windows GIS Data Agent 部署预检",
        "",
        f"- 时间：{report['generated_at']}",
        f"- 模式：`{report['mode']}`",
        f"- 结论：**{report['status']}**",
        f"- 关键阻断：{report['critical_failures']}",
        f"- 警告：{report['warnings']}",
        "",
        "| 检查项 | 级别 | 状态 | 结果 |",
        "|---|---|---|---|",
    ]
    for item in report["checks"]:
        detail = str(item["detail"]).replace("|", "\\|").replace("\n", " ")
        lines.append(f"| {item['name']} | {item['severity']} | {item['status']} | {detail} |")
    lines.extend(["", "## 处理建议", ""])
    for item in report["checks"]:
        if item.get("remediation") and item["status"] != "pass":
            lines.append(f"- `{item['name']}`：{item['remediation']}")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Preflight Windows offline ingest deployment")
    parser.add_argument("--mode", choices=("development", "production"), default="production")
    parser.add_argument("--lake", type=Path)
    parser.add_argument("--inbox", type=Path)
    parser.add_argument("--contracts", type=Path)
    parser.add_argument("--ontology", type=Path)
    parser.add_argument("--min-free-gb", type=float, default=20.0)
    parser.add_argument("--create-directories", action="store_true")
    parser.add_argument("--output", type=Path, default=Path("preflight_windows_ingest.json"))
    parser.add_argument("--markdown", type=Path)
    args = parser.parse_args()
    report = run_preflight(args)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    markdown = args.markdown or args.output.with_suffix(".md")
    markdown.write_text(_markdown(report), encoding="utf-8")
    print(
        json.dumps(
            {
                "status": report["status"],
                "output": str(args.output.resolve()),
                "markdown": str(markdown.resolve()),
                "critical_failures": report["critical_failures"],
            },
            ensure_ascii=False,
        )
    )
    return 2 if report["status"] == "blocked" else 0


if __name__ == "__main__":
    raise SystemExit(main())
