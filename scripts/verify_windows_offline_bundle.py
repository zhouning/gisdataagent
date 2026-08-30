#!/usr/bin/env python3
"""Verify a GIS Data Agent Windows offline bundle or installed profile.

The verifier has no third-party dependency and can run from the bundle's
staging directory with the bundled Python after installation.  It produces a
machine-readable report and returns non-zero for a critical failure.  It never
tries to download a package or repair an installation.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import socket
import subprocess
import urllib.error
import urllib.request
import zipfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def check(
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


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_manifest(root: Path) -> dict[str, Any]:
    path = root / "manifest.json"
    return json.loads(path.read_text(encoding="utf-8"))


def verify_checksums(root: Path, checks: list[dict[str, Any]]) -> None:
    sums = root / "SHA256SUMS"
    if not sums.is_file():
        check(checks, "sha256sums", "critical", "fail", str(sums), "重新生成不完整性清单。")
        return
    failures = []
    entries = 0
    for line in sums.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        parts = line.split(None, 1)
        if len(parts) != 2:
            failures.append(f"invalid line: {line}")
            continue
        expected, relative = parts[0].lower(), parts[1].strip().replace("/", os.sep)
        path = (root / relative).resolve()
        try:
            path.relative_to(root.resolve())
        except ValueError:
            failures.append(f"outside bundle: {relative}")
            continue
        if not path.is_file():
            failures.append(f"missing: {relative}")
            continue
        entries += 1
        actual = sha256_file(path)
        if actual != expected:
            failures.append(f"hash mismatch: {relative}")
    check(
        checks,
        "sha256sums",
        "critical",
        "fail" if failures else "pass",
        f"{entries} file(s); failures={len(failures)}"
        + (f"; {', '.join(failures[:5])}" if failures else ""),
        "介质传输或解压损坏时重新复制完整 ZIP。",
    )


def verify_artifacts(
    root: Path, manifest: dict[str, Any], profile: str, checks: list[dict[str, Any]]
) -> None:
    required = set(
        (manifest.get("profiles") or {}).get(profile, {}).get("required_artifacts") or []
    )
    artifacts = {item.get("id"): item for item in manifest.get("artifacts") or []}
    for artifact_id in sorted(required):
        item = artifacts.get(artifact_id)
        if not item:
            check(checks, f"artifact:{artifact_id}", "critical", "fail", "not declared in manifest")
            continue
        target = root / str(item.get("target", "")).replace("/", os.sep)
        present = target.exists()
        required_paths = item.get("required_relative_paths") or []
        missing_paths = []
        missing_archive_members = []
        archive_members = item.get("required_archive_members") or []
        archives = (
            list(target.rglob("*.zip"))
            if target.is_dir()
            else ([target] if target.suffix.lower() == ".zip" else [])
        )
        for member in archive_members:
            pattern = Path(str(member)).name
            found = False
            for archive in archives:
                try:
                    with zipfile.ZipFile(archive) as handle:
                        if any(Path(value).match(pattern) for value in handle.namelist()):
                            found = True
                            break
                except (OSError, zipfile.BadZipFile):
                    continue
            if not found:
                missing_archive_members.append(str(member))
        if present and target.is_dir():
            for relative in required_paths:
                pattern = Path(relative).name
                direct = any(path.is_file() and path.match(pattern) for path in target.rglob("*"))
                archive_match = False
                if not direct and artifact_id == "pgvector_extension":
                    for archive in target.rglob("*.zip"):
                        try:
                            with zipfile.ZipFile(archive) as handle:
                                archive_match = any(
                                    Path(member).name.lower() == pattern.lower()
                                    or Path(member).match(pattern)
                                    for member in handle.namelist()
                                )
                        except (OSError, zipfile.BadZipFile):
                            archive_match = False
                        if archive_match:
                            break
                if not direct and not archive_match:
                    missing_paths.append(relative)
        check(
            checks,
            f"artifact:{artifact_id}",
            "critical",
            "pass" if present and not missing_paths and not missing_archive_members else "fail",
            str(target)
            + (f"; missing={','.join(missing_paths)}" if missing_paths else "")
            + (
                f"; missing_archive={','.join(missing_archive_members)}"
                if missing_archive_members
                else ""
            ),
            "补齐构建器要求的 Windows 制品后重新生成 ZIP。",
        )
    optional_missing = manifest.get("optional_missing") or []
    if optional_missing:
        check(
            checks,
            "optional_artifacts",
            "warning",
            "warn",
            "; ".join(optional_missing),
            "可在下一版监控包补齐。",
        )


def _run_python(python: Path, code: str, env: dict[str, str]) -> tuple[int, str]:
    result = subprocess.run(
        [str(python), "-c", code], capture_output=True, text=True, env=env, timeout=90
    )
    return result.returncode, (result.stdout or result.stderr).strip()


def verify_python_runtime(root: Path, checks: list[dict[str, Any]], phase: str) -> Path | None:
    python = root / "runtime" / "python" / "python.exe"
    if phase == "artifact":
        check(
            checks,
            "python_installer",
            "critical",
            "pass" if (root / "payload/runtime/python-installer.exe").is_file() else "fail",
            str(root / "payload/runtime/python-installer.exe"),
        )
        return None
    if not python.is_file():
        check(
            checks,
            "python_runtime",
            "critical",
            "fail",
            str(python),
            "先运行 install_offline_bundle.ps1 安装 Python。",
        )
        return None
    code, output = _run_python(
        python, "import platform; print(platform.python_version())", os.environ.copy()
    )
    ok = code == 0 and output.startswith("3.11")
    check(
        checks,
        "python_runtime",
        "critical",
        "pass" if ok else "fail",
        output,
        "现场必须使用 CPython 3.11 x64。",
    )
    return python


def verify_python_modules(
    root: Path, python: Path | None, profile: str, checks: list[dict[str, Any]]
) -> None:
    if not python:
        return
    env = os.environ.copy()
    env["PYTHONPATH"] = str(root / "payload" / "app")
    modules = ["duckdb", "geopandas", "pyogrio", "rasterio", "pyarrow", "data_agent.offline_ingest"]
    if profile == "production":
        modules.extend(["litellm", "psycopg2", "rdflib", "pyshacl", "torch", "onnxruntime"])
    for module in modules:
        code = (
            f"import importlib; m=importlib.import_module({module!r}); "
            "print(getattr(m, '__version__', 'importable'))"
        )
        code_status, output = _run_python(python, code, env)
        check(
            checks,
            f"python_module:{module}",
            "critical",
            "pass" if code_status == 0 else "fail",
            output or "import failed",
            "检查 wheelhouse 和 PYTHONPATH。",
        )
    code = (
        "import json; from data_agent.local_gis_runtime import runtime_info; "
        "print(json.dumps(runtime_info(), ensure_ascii=False))"
    )
    code_status, output = _run_python(python, code, env)
    if code_status:
        check(checks, "gis_runtime", "critical", "fail", output, "安装 Windows GIS wheelhouse。")
        return
    try:
        runtime = json.loads(output.splitlines()[-1])
    except (ValueError, IndexError):
        runtime = {}
    required_flags = ("filegdb_reader", "vector_writer", "raster_cog_writer")
    missing = [flag for flag in required_flags if not runtime.get(flag)]
    check(
        checks,
        "gis_runtime",
        "critical",
        "fail" if missing else "pass",
        json.dumps(runtime, ensure_ascii=False),
        "pyogrio/OpenFileGDB、GeoParquet 和 COG 能力缺一不可。",
    )


def verify_duckdb_spatial(
    root: Path, python: Path | None, checks: list[dict[str, Any]]
) -> None:
    """Load the bundled extension and execute a real spatial expression."""
    if not python:
        return
    extension = (
        root
        / "payload"
        / "middleware"
        / "duckdb"
        / "extensions"
        / "spatial.duckdb_extension"
    )
    if not extension.is_file():
        check(
            checks,
            "duckdb_spatial",
            "critical",
            "fail",
            str(extension),
            "补齐 DuckDB 1.4.3 Windows AMD64 Spatial 离线扩展。",
        )
        return
    env = os.environ.copy()
    code = (
        "import duckdb,json; "
        f"p={str(extension)!r}; "
        "c=duckdb.connect(':memory:'); "
        "c.execute(\"LOAD '\" + p.replace(\"'\", \"''\") + \"'\"); "
        "area=c.execute("
        "\"SELECT ST_Area(ST_GeomFromText('POLYGON ((0 0, 1 0, 1 1, 0 1, 0 0))'))\""
        ").fetchone()[0]; "
        "print(json.dumps({'version': duckdb.__version__, 'area': area}))"
    )
    code_status, output = _run_python(python, code, env)
    try:
        result = json.loads(output.splitlines()[-1]) if code_status == 0 else {}
    except (ValueError, IndexError):
        result = {}
    ok = result.get("version") == "1.4.3" and abs(float(result.get("area")) - 1.0) < 1e-9
    check(
        checks,
        "duckdb_spatial",
        "critical",
        "pass" if ok else "fail",
        output or "extension load or ST_Area failed",
        (
            "确认 duckdb==1.4.3，并使用 v1.4.3/windows_amd64 的已解压 "
            "spatial.duckdb_extension 重新构建离线包。"
        ),
    )


def verify_ontology_and_contract(root: Path, profile: str, checks: list[dict[str, Any]]) -> None:
    ontology = root / "config" / "ontology" / "natural_resource_one_map" / "2.3.0" / "manifest.json"
    active = root / "config" / "ontology" / "natural_resource_one_map" / "active.json"
    check(
        checks,
        "ontology_package",
        "critical",
        "pass" if ontology.is_file() else "fail",
        str(ontology),
        "安装自然资源本体 2.3 包。",
    )
    check(
        checks,
        "ontology_active",
        "critical",
        "pass" if active.is_file() else "fail",
        str(active),
        "安装 ontology active.json。",
    )
    contract_path = Path(os.environ.get("GDA_STANDARD_CONTRACTS", ""))
    if not contract_path.is_file():
        candidate = root / "config" / "natural_resource_standard_contracts.json"
        contract_path = (
            candidate
            if candidate.is_file()
            else root / "config" / "natural_resource_standard_baseline.json"
        )
    if not contract_path.is_file():
        # Backward compatibility for bundles produced before the baseline
        # naming correction.
        contract_path = root / "config" / "natural_resource_standard_contracts.candidate.json"
    if not contract_path.is_file():
        check(
            checks,
            "standard_contract",
            "critical",
            "fail",
            "contract missing",
            "补齐 EA/标准合同。",
        )
        return
    try:
        contract = json.loads(contract_path.read_text(encoding="utf-8"))
        valid_baseline = (
            contract.get("schema_version")
            in {"gda.standard-contract-catalog.v1", "gda.standard-contract-catalog.v2"}
            and isinstance(contract.get("contracts"), dict)
        )
        status = "pass" if valid_baseline else "fail"
        severity = "info" if valid_baseline else "critical"
        check(
            checks,
            "standard_contract",
            severity,
            status,
            (
                f"{contract_path}; authority={contract.get('authority')}; "
                f"review_status={contract.get('review_status')}; "
                "policy=per_dataset_schema_quality_gate"
            ),
            (
                "修复宁夏清单/字段基线 JSON；真实数据集将在入湖时单独执行字段、CRS、"
                "几何和值域质量门禁。"
            ),
        )
    except (OSError, ValueError) as exc:
        check(checks, "standard_contract", "critical", "fail", str(exc), "修复合同 JSON。")


def _tcp_open(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def _ollama_tags() -> list[str]:
    try:
        with urllib.request.urlopen("http://127.0.0.1:11434/api/tags", timeout=3) as response:
            payload = json.loads(response.read().decode("utf-8"))
        return [str(item.get("name")) for item in payload.get("models", []) if item.get("name")]
    except (OSError, ValueError, urllib.error.URLError):
        return []


def verify_production_services(
    root: Path, require_running: bool, checks: list[dict[str, Any]]
) -> None:
    checks_spec = {
        "gis_data_agent": 8000,
        "postgres": 5432,
        "minio": 9000,
        "fuseki": 3030,
        "ollama": 11434,
    }
    for name, port in checks_spec.items():
        if require_running:
            opened = _tcp_open(port)
            check(
                checks,
                f"service:{name}",
                "critical",
                "pass" if opened else "fail",
                f"127.0.0.1:{port}",
                "启动原生中间件或检查其日志。",
            )
        else:
            check(
                checks,
                f"service_media:{name}",
                "info",
                "pass",
                f"port contract {port}; runtime check deferred",
            )
    for name, relative in {
        "paper9_models": "payload/models/paper9",
        "llm_model": "payload/models/ollama/gemma4-26b",
        "embedding_model": "payload/models/embedding/nomic-embed-text-v2-moe",
    }.items():
        path = root / relative
        files = list(path.rglob("*")) if path.is_dir() else []
        check(
            checks,
            name,
            "critical",
            "pass" if files else "fail",
            f"{len(files)} file(s) under {path}",
            "把批准版本的离线权重放入 bundle vendor。",
        )
    if require_running:
        tags = _ollama_tags()
        required_tags = {"Gemma4:26b", "nomic-embed-text-v2-moe:latest"}
        missing = sorted(required_tags - set(tags))
        check(
            checks,
            "ollama_model_registry",
            "critical",
            "pass" if not missing else "fail",
            f"available={sorted(tags)}; missing={missing}",
            "重新导入 ZIP 内的 Modelfile 和本地模型权重。",
        )


def markdown(report: dict[str, Any]) -> str:
    lines = [
        "# GIS Data Agent Windows 离线包验收",
        "",
        f"- 时间：{report['generated_at']}",
        f"- profile：`{report['profile']}`",
        f"- phase：`{report['phase']}`",
        f"- 结论：**{report['status']}**",
        "",
        "| 检查 | 级别 | 状态 | 详情 |",
        "|---|---|---|---|",
    ]
    for item in report["checks"]:
        detail = str(item["detail"]).replace("|", "\\|")
        lines.append(f"| {item['name']} | {item['severity']} | {item['status']} | {detail} |")
    lines += ["", "## 失败项处理", ""]
    for item in report["checks"]:
        if item.get("remediation") and item["status"] != "pass":
            lines.append(f"- `{item['name']}`：{item['remediation']}")
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify GDA Windows offline bundle")
    parser.add_argument("--bundle-root", type=Path, default=Path("."))
    parser.add_argument("--profile", choices=("core", "production"), required=True)
    parser.add_argument("--phase", choices=("artifact", "install", "runtime"), default="runtime")
    parser.add_argument("--require-running", action="store_true")
    parser.add_argument("--output", type=Path, default=Path("bundle-verification.json"))
    parser.add_argument("--markdown", type=Path)
    args = parser.parse_args()
    root = args.bundle_root.resolve()
    checks: list[dict[str, Any]] = []
    try:
        manifest = load_manifest(root)
    except (OSError, ValueError) as exc:
        check(checks, "manifest", "critical", "fail", str(exc), "从完整 ZIP 根目录执行验收。")
        manifest = {}
    if manifest:
        check(
            checks,
            "manifest",
            "critical",
            "pass" if manifest.get("profile") == args.profile else "fail",
            f"bundle={manifest.get('bundle_version')}; profile={manifest.get('profile')}",
            "profile 参数必须与 ZIP 一致。",
        )
        verify_checksums(root, checks)
        verify_artifacts(root, manifest, args.profile, checks)
    python = verify_python_runtime(root, checks, args.phase)
    verify_python_modules(root, python, args.profile, checks)
    verify_duckdb_spatial(root, python, checks)
    if args.phase != "artifact":
        verify_ontology_and_contract(root, args.profile, checks)
    if args.profile == "production":
        verify_production_services(root, args.require_running, checks)
    failures = [
        item for item in checks if item["status"] == "fail" and item["severity"] == "critical"
    ]
    warnings = [item for item in checks if item["status"] in {"warn", "fail"}]
    report = {
        "schema_version": "gda.windows-offline-verification.v1",
        "generated_at": utc_now(),
        "profile": args.profile,
        "phase": args.phase,
        "host": {"platform": platform.platform(), "python": platform.python_version()},
        "checks": checks,
        "status": "blocked" if failures else "ready_with_warnings" if warnings else "ready",
        "critical_failures": len(failures),
        "warnings": len(warnings),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    markdown_path = args.markdown or args.output.with_suffix(".md")
    markdown_path.write_text(markdown(report), encoding="utf-8")
    print(
        json.dumps(
            {
                "status": report["status"],
                "output": str(args.output.resolve()),
                "critical_failures": len(failures),
            },
            ensure_ascii=False,
        )
    )
    return 2 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
