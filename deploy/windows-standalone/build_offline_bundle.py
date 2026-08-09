#!/usr/bin/env python3
"""Build a reproducible GIS Data Agent Windows offline bundle.

The builder is intentionally a *collector*, not a downloader.  It runs on a
connected Windows x64 staging host, reads the pinned manifest and vendor
directory, validates every required artifact, and only then creates a ZIP.
Missing wheels, native installers, model files, or Paper9 assets are fatal.
This prevents a partial bundle from reaching the physically isolated site.
"""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import re
import shutil
import sys
import tempfile
import zipfile
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_DIR = Path(__file__).resolve().parent
MANIFEST_TEMPLATE = SCRIPT_DIR / "bundle-manifest.json"
_REQ = re.compile(r"^([A-Za-z0-9][A-Za-z0-9_.-]*)(?:\[[^]]+\])?\s*(?:==|~=|>=|<=|>|<|;|$)")


def utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def iter_files(path: Path) -> Iterable[Path]:
    if path.is_file():
        yield path
        return
    for child in sorted(path.rglob("*")):
        if child.is_file() and not child.is_symlink():
            yield child


def sha256_tree(path: Path) -> tuple[str, int, int]:
    digest = hashlib.sha256()
    size = 0
    count = 0
    for child in iter_files(path):
        relative = child.relative_to(path).as_posix() if path.is_dir() else child.name
        digest.update(relative.encode("utf-8"))
        digest.update(str(child.stat().st_size).encode("ascii"))
        digest.update(sha256_file(child).encode("ascii"))
        size += child.stat().st_size
        count += 1
    return digest.hexdigest(), size, count


def _matches_exclude(relative: str, patterns: list[str]) -> bool:
    return any(fnmatch.fnmatch(relative, pattern) for pattern in patterns)


def copy_tree(source: Path, target: Path, excludes: list[str] | None = None) -> None:
    excludes = excludes or []
    for item in sorted(source.rglob("*")):
        relative = item.relative_to(source).as_posix()
        if _matches_exclude(relative, excludes):
            continue
        destination = target / item.relative_to(source)
        if item.is_dir():
            destination.mkdir(parents=True, exist_ok=True)
        elif item.is_file():
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, destination)


def copy_item(source: Path, target: Path, *, excludes: list[str] | None = None) -> None:
    if source.is_dir():
        copy_tree(source, target, excludes)
    else:
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)


def _portable_source(path: Path, vendor_root: Path) -> str:
    for prefix, root in (("repo", REPO_ROOT), ("vendor", vendor_root)):
        try:
            return f"{prefix}:{path.resolve().relative_to(root.resolve()).as_posix()}"
        except ValueError:
            continue
    return f"external:{path.name}"


def _resolve_source(spec: dict[str, Any], vendor_root: Path) -> Path:
    kind = spec["source_type"]
    source = spec["source"]
    if kind.startswith("repo_") or kind == "repo_trees":
        if isinstance(source, list):
            raise ValueError("repo_trees is resolved by _collect_artifact")
        return (REPO_ROOT / source).resolve()
    if isinstance(source, str) and source.startswith("vendor/"):
        # The manifest is readable from the repository (where paths are shown
        # under vendor/) while --vendor-root points at the directory itself.
        source = source.removeprefix("vendor/")
    pattern = (vendor_root / source).resolve()
    if kind in {"vendor_glob"}:
        matches = sorted(Path(value) for value in pattern.parent.glob(pattern.name))
        if len(matches) != 1:
            raise FileNotFoundError(
                f"{spec['id']}: expected exactly one vendor match for {source}, got {len(matches)}"
            )
        return matches[0]
    return pattern


def _collect_artifact(spec: dict[str, Any], stage: Path, vendor_root: Path) -> dict[str, Any]:
    artifact_id = spec["id"]
    source_type = spec["source_type"]
    destination = stage / spec["target"]
    sources: list[tuple[Path, Path]] = []
    if source_type == "repo_trees":
        for source_name in spec["source"]:
            source = (REPO_ROOT / source_name).resolve()
            if not source.is_dir():
                raise FileNotFoundError(f"{artifact_id}: missing repository tree {source}")
            sources.append((source, destination / source.name))
    else:
        source = _resolve_source(spec, vendor_root)
        if not source.exists():
            raise FileNotFoundError(f"{artifact_id}: missing source {source}")
        if source_type == "vendor_glob" and source.is_file():
            sources.append((source, destination))
        elif source.is_file():
            sources.append((source, destination))
        else:
            sources.append((source, destination))

    for source, target in sources:
        copy_item(source, target, excludes=spec.get("exclude"))

    copied_root = destination
    digest, size, count = sha256_tree(copied_root)
    minimum = int(spec.get("min_files", 0))
    if count < minimum:
        raise ValueError(f"{artifact_id}: copied {count} file(s), requires at least {minimum}")
    minimum_bytes = int(spec.get("min_size_bytes", 0))
    if size < minimum_bytes:
        raise ValueError(f"{artifact_id}: copied {size} byte(s), requires at least {minimum_bytes}")
    archive_members = [str(value) for value in spec.get("required_archive_members", [])]
    if archive_members:
        archives = [path for path in iter_files(copied_root) if path.suffix.lower() == ".zip"]
        missing_members = [
            member
            for member in archive_members
            if not any(_zip_contains(archive, Path(member).name) for archive in archives)
        ]
        if missing_members:
            raise ValueError(f"{artifact_id}: archive is missing {', '.join(missing_members)}")
    required_paths = [
        str(value).replace("\\", "/") for value in spec.get("required_relative_paths", [])
    ]
    for relative in required_paths:
        if any(
            path.is_file() and fnmatch.fnmatch(path.name, Path(relative).name)
            for path in iter_files(copied_root)
        ):
            continue
        # pgvector is commonly delivered as the vendor ZIP containing the
        # Windows DLL and extension SQL.  Validate its contents here and let
        # the installer expand it into the selected PostgreSQL installation.
        if artifact_id == "pgvector_extension" or spec.get("install") == "pgvector_extension":
            archives = [path for path in iter_files(copied_root) if path.suffix.lower() == ".zip"]
            if any(_zip_contains(archive, Path(relative).name) for archive in archives):
                continue
        raise ValueError(f"{artifact_id}: missing required path {relative}")
    if spec.get("kind") == "wheelhouse":
        wheel_files = [path for path in iter_files(copied_root) if path.suffix.lower() == ".whl"]
        if len(wheel_files) != count:
            raise ValueError(f"{artifact_id}: wheelhouse contains non-wheel files")
        _validate_windows_wheels(artifact_id, wheel_files)
        if spec.get("requirements"):
            _validate_requirements(spec, copied_root, stage)
    record = dict(spec)
    record.update(
        {
            "resolved_source": [_portable_source(source, vendor_root) for source, _ in sources],
            "sha256": digest,
            "size_bytes": size,
            "file_count": count,
        }
    )
    return record


def _zip_contains(path: Path, filename: str) -> bool:
    """Return whether a ZIP contains a file with the requested basename."""
    try:
        with zipfile.ZipFile(path) as archive:
            return any(
                fnmatch.fnmatch(Path(member).name.lower(), filename.lower())
                for member in archive.namelist()
            )
    except (OSError, zipfile.BadZipFile):
        return False


def _requirement_names(path: Path, seen: set[Path] | None = None) -> set[str]:
    seen = seen or set()
    path = path.resolve()
    if path in seen or not path.exists():
        return set()
    seen.add(path)
    names: set[str] = set()
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        if line.startswith("-r ") or line.startswith("--requirement "):
            nested = line.split(maxsplit=1)[1].strip()
            names.update(_requirement_names((path.parent / nested).resolve(), seen))
            continue
        if line.startswith("-"):
            continue
        match = _REQ.match(line)
        if match:
            names.add(match.group(1).lower().replace("_", "-").replace(".", "-"))
    return names


def _wheel_distribution(path: Path) -> str:
    stem = path.name[:-4]
    tokens = stem.split("-")
    for index, token in enumerate(tokens[1:], start=1):
        if re.match(r"^\d", token):
            return "-".join(tokens[:index]).lower().replace("_", "-").replace(".", "-")
    return tokens[0].lower().replace("_", "-").replace(".", "-")


def _validate_windows_wheels(artifact_id: str, wheels: list[Path]) -> None:
    incompatible: list[str] = []
    for wheel in wheels:
        tags = wheel.stem.rsplit("-", 3)
        if len(tags) != 4:
            incompatible.append(wheel.name)
            continue
        python_tag, abi_tag, platform_tag = tags[-3:]
        platform_ok = platform_tag == "any" or "win_amd64" in platform_tag.split(".")
        python_tags = python_tag.split(".")
        abi_tags = abi_tag.split(".")
        abi3_compatible = "abi3" in abi_tags
        python_ok = any(
            tag.startswith("py3")
            or tag == "cp311"
            or (
                tag.startswith("cp3")
                and tag[2:].isdigit()
                and int(tag[2:]) <= 311
                and abi3_compatible
            )
            for tag in python_tags
        )
        abi_ok = any(tag in {"none", "abi3", "cp311"} for tag in abi_tags)
        if not (platform_ok and python_ok and abi_ok):
            incompatible.append(wheel.name)
    if incompatible:
        raise ValueError(
            f"{artifact_id}: incompatible with CPython 3.11 win_amd64: "
            + ", ".join(incompatible[:10])
        )


def _validate_requirements(spec: dict[str, Any], copied_root: Path, stage: Path) -> None:
    requirement_path = stage / spec["requirements"]
    required = _requirement_names(requirement_path)
    wheel_roots = [copied_root]
    wheel_roots.extend(stage / value for value in spec.get("additional_wheelhouses", []))
    available = {
        _wheel_distribution(path) for wheel_root in wheel_roots for path in iter_files(wheel_root)
    }
    missing = sorted(required - available)
    if missing:
        raise ValueError(
            f"{spec['id']}: wheelhouse is missing direct requirements: {', '.join(missing)}"
        )


def _write_checksums(stage: Path) -> None:
    lines = []
    for path in sorted(iter_files(stage)):
        if path.name in {"SHA256SUMS"}:
            continue
        lines.append(f"{sha256_file(path)}  {path.relative_to(stage).as_posix()}")
    (stage / "SHA256SUMS").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _zip_directory(stage: Path, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path in sorted(iter_files(stage)):
            archive.write(path, path.relative_to(stage.parent).as_posix())


def build(profile: str, vendor_root: Path, output: Path, force: bool = False) -> dict[str, Any]:
    if profile not in {"core", "native-lite", "production"}:
        raise ValueError(f"unsupported profile: {profile}")
    if not vendor_root.is_dir():
        raise FileNotFoundError(f"vendor root does not exist: {vendor_root}")
    if output.exists() and not force:
        raise FileExistsError(f"output already exists (use --force): {output}")

    template = json.loads(MANIFEST_TEMPLATE.read_text(encoding="utf-8"))
    required = set(template["profiles"][profile]["required_artifacts"])
    optional = set(template["profiles"][profile].get("optional_artifacts", []))
    selected = [
        item for item in template["artifacts"] if item["id"] in required or item["id"] in optional
    ]
    selected_ids = {item["id"] for item in selected}
    missing_manifest_ids = required - selected_ids
    if missing_manifest_ids:
        raise ValueError(f"profile references unknown artifacts: {sorted(missing_manifest_ids)}")

    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix="gda-windows-bundle-", dir=str(output.parent)))
    stage = temporary / f"GIS-Data-Agent-{template['bundle_version']}-{profile}"
    stage.mkdir(parents=True)
    records: list[dict[str, Any]] = []
    missing_optional: list[str] = []
    try:
        for spec in selected:
            try:
                records.append(_collect_artifact(spec, stage, vendor_root))
            except (FileNotFoundError, ValueError) as exc:
                if spec["id"] in optional:
                    missing_optional.append(f"{spec['id']}: {exc}")
                    continue
                raise

        # Deployment scripts are part of every profile and are kept outside the
        # application payload so operators can inspect them before install.
        script_names = [
            "README.md",
            "install_offline_bundle.ps1",
            "start_gda.ps1",
            "stop_gda.ps1",
            "register_tasks.ps1",
            "unregister_tasks.ps1",
            "collect_diagnostics.ps1",
            "bundle-manifest.json",
        ]
        for name in script_names:
            source = SCRIPT_DIR / name
            if source.is_file():
                shutil.copy2(source, stage / name)
        (stage / "config").mkdir(parents=True, exist_ok=True)
        (stage / "scripts").mkdir(parents=True, exist_ok=True)
        shutil.copy2(SCRIPT_DIR / "templates" / "gda.env", stage / "config" / "gda.env.template")
        shutil.copy2(
            SCRIPT_DIR / "templates" / "install-config.json",
            stage / "config" / "install-config.template.json",
        )
        shutil.copy2(
            SCRIPT_DIR / "templates" / "prometheus.yml",
            stage / "config" / "prometheus.yml",
        )
        verify_source = REPO_ROOT / "scripts" / "verify_windows_offline_bundle.py"
        shutil.copy2(verify_source, stage / "scripts" / "verify_windows_offline_bundle.py")
        preflight_source = REPO_ROOT / "scripts" / "preflight_windows_ingest.py"
        shutil.copy2(preflight_source, stage / "scripts" / "preflight_windows_ingest.py")
        worker_source = REPO_ROOT / "scripts" / "windows_ingest_worker.py"
        shutil.copy2(worker_source, stage / "scripts" / "windows_ingest_worker.py")

        final_manifest = dict(template)
        final_manifest["generated_at"] = utc_now()
        final_manifest["profile"] = profile
        final_manifest["artifacts"] = records
        final_manifest["optional_missing"] = missing_optional
        (stage / "manifest.json").write_text(
            json.dumps(final_manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        _write_checksums(stage)
        zip_path = output
        if zip_path.exists() and force:
            zip_path.unlink()
        _zip_directory(stage, zip_path)
        return {
            "status": "ready",
            "profile": profile,
            "bundle": str(zip_path.resolve()),
            "manifest_member": f"{stage.name}/manifest.json",
            "artifacts": len(records),
            "optional_missing": missing_optional,
        }
    finally:
        shutil.rmtree(temporary, ignore_errors=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Build GIS Data Agent Windows offline bundle")
    parser.add_argument("--profile", choices=("core", "native-lite", "production"), default="core")
    parser.add_argument("--vendor-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True, help="final ZIP path")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    try:
        result = build(args.profile, args.vendor_root.resolve(), args.output.resolve(), args.force)
    except Exception as exc:
        print(
            json.dumps({"status": "blocked", "error": str(exc)}, ensure_ascii=False),
            file=sys.stderr,
        )
        return 2
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
