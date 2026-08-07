"""Offline, Windows-friendly ingest primitives for geospatial file assets.

This module deliberately has no database, object-store, or container dependency.
It is the control-plane contract used by the optional HTTP routes and by a
future Windows collector service.  The raw file is immutable; every scan,
quality decision, mapping proposal, and lineage edge is persisted under the
same run directory so an isolated deployment can export a diagnostic bundle.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
import uuid
import zipfile
from collections.abc import AsyncIterable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger("data_agent.offline_ingest")

CHUNK_SIZE_DEFAULT = 128 * 1024 * 1024
CHUNK_SIZE_MIN = 1 * 1024 * 1024
CHUNK_SIZE_MAX = 512 * 1024 * 1024
HASH_BLOCK_SIZE = 8 * 1024 * 1024
_SAFE_NAME = re.compile(r'[\x00-\x1f<>:"/\\|?*]+')
_SHP_SIDECARS = (".dbf", ".shx", ".prj", ".cpg", ".sbn", ".sbx", ".qpj", ".qmd")

# The workbook is a discovery list, not a complete schema.  These aliases are
# intentionally small, auditable defaults; a project can replace/extend them
# with GDA_STANDARD_CONTRACTS (JSON) or GDA_STANDARD_CONTRACT_XLSX after the
# EA and standard documents are reconciled.  Workbook/screenshot contracts are
# candidate evidence only; a mapping is never silently promoted when required
# fields are missing.
DEFAULT_FIELD_ALIASES: dict[str, dict[str, set[str]]] = {
    "DLTB": {
        "标识码": {"标识码", "bsm", "objectid", "fid"},
        "要素代码": {"要素代码", "ysdm", "yydm", "featurecode"},
        "图斑编号": {"图斑编号", "tbbh", "tbid"},
        "地类编码": {"地类编码", "dlbm", "landusecode"},
        "地类名称": {"地类名称", "dlmc", "landusename"},
        "图斑面积": {"图斑面积", "tbmj", "tbdlmj", "shape_area", "面积"},
    },
    "ZRZ": {
        "实体标识码": {"实体标识码", "stbsm", "stbsm1", "objectid"},
        "不动产单元号": {"不动产单元号", "bdcdyh"},
        "宗地代码": {"宗地代码", "zddm"},
        "幢号": {"幢号", "zh", "zjzh"},
        "建筑物高度": {"建筑物高度", "jzwgd", "height"},
        "总层数": {"总层数", "zcs"},
    },
    "PDT": {},
    "STBHHX": {"标识码": {"标识码", "bsm", "objectid"}},
    "YJJBNT": {
        "标识码": {"标识码", "bsm", "objectid"},
        "地类编码": {"地类编码", "dlbm"},
    },
    "XZQH": {"行政区划代码": {"行政区划代码", "xzqdm", "xzqhdm", "code"}},
}


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _safe_name(value: str, fallback: str = "asset") -> str:
    """Return a filename safe for the local lake, preserving its extension."""
    name = Path(value or fallback).name
    name = _SAFE_NAME.sub("_", name).strip(" .") or fallback
    return name[:220]


def _atomic_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, default=str)
            handle.write("\n")
        os.replace(tmp_name, path)
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while block := handle.read(HASH_BLOCK_SIZE):
            digest.update(block)
    return digest.hexdigest()


def sha256_tree(path: Path) -> str:
    """Stable hash for a FileGDB/OBJ bundle without following symlinks."""
    digest = hashlib.sha256()
    if path.is_file():
        return sha256_file(path)
    for child in sorted(path.rglob("*")):
        if child.is_symlink() or not child.is_file():
            continue
        rel = child.relative_to(path).as_posix().encode("utf-8")
        digest.update(rel)
        digest.update(str(child.stat().st_size).encode("ascii"))
        digest.update(sha256_file(child).encode("ascii"))
    return digest.hexdigest()


def _shapefile_parts(path: Path) -> list[Path]:
    if path.suffix.lower() != ".shp":
        return [path]
    return [path] + [
        path.with_suffix(ext) for ext in _SHP_SIDECARS if path.with_suffix(ext).is_file()
    ]


def _sha256_parts(parts: list[Path]) -> tuple[int, str]:
    digest = hashlib.sha256()
    size = 0
    for part in parts:
        digest.update(part.name.encode("utf-8"))
        digest.update(sha256_file(part).encode("ascii"))
        size += part.stat().st_size
    return size, digest.hexdigest()


def _asset_kind(path: Path) -> str:
    lower = path.name.lower()
    suffix = path.suffix.lower()
    if path.is_dir() and lower.endswith(".gdb"):
        return "filegdb_bundle"
    if suffix in {".tif", ".tiff", ".cog"}:
        return "raster"
    if suffix in {".osgb", ".obj", ".ply", ".las", ".laz"}:
        return "3d_asset"
    if suffix in {".zip", ".7z", ".rar"}:
        return "archive"
    if suffix in {".gpkg", ".shp", ".geojson", ".json", ".parquet"}:
        return "vector_or_table"
    return "file"


def _allowed_roots() -> list[Path]:
    values = os.environ.get("GDA_LOCAL_INGEST_DIRS", "").split(os.pathsep)
    roots = [Path(v).expanduser().resolve() for v in values if v.strip()]
    if roots:
        return roots
    return [Path(os.environ.get("GDA_FILE_LAKE_INBOX", "./file_lake/inbox")).expanduser().resolve()]


def _field_aliases() -> dict[str, dict[str, set[str]]]:
    """Load an auditable project contract without making it a hard dependency."""
    path = os.environ.get("GDA_STANDARD_CONTRACTS", "").strip()
    if not path:
        return DEFAULT_FIELD_ALIASES
    try:
        contract_aliases: dict[str, dict[str, set[str]]] = {}
        if Path(path).suffix.lower() in {".xlsx", ".xlsm", ".xltx"}:
            from .standard_contracts import aliases_from_catalog, load_contract_catalog

            contract_aliases = aliases_from_catalog(load_contract_catalog(path))
            raw: dict[str, Any] = {}
        else:
            raw = json.loads(Path(path).expanduser().read_text(encoding="utf-8"))
            if "contracts" in raw:
                from .standard_contracts import aliases_from_catalog

                contract_aliases = aliases_from_catalog(raw)
                raw = raw.get("field_aliases") or {}
        merged = {
            domain: {field: set(values) for field, values in fields.items()}
            for domain, fields in DEFAULT_FIELD_ALIASES.items()
        }
        for domain, fields in raw.items():
            merged.setdefault(domain, {})
            for field, values in fields.items():
                merged[domain].setdefault(field, set()).update(
                    str(value).lower() for value in values
                )
        for domain, fields in contract_aliases.items():
            merged.setdefault(domain, {})
            for field, values in fields.items():
                merged[domain].setdefault(field, set()).update(values)
        return merged
    except (OSError, ValueError, TypeError) as exc:
        logger.warning("Unable to load GDA_STANDARD_CONTRACTS=%s: %s", path, exc)
        return DEFAULT_FIELD_ALIASES


def ensure_under_allowed_root(path: str | Path) -> Path:
    candidate = Path(path).expanduser().resolve()
    for root in _allowed_roots():
        try:
            candidate.relative_to(root)
            return candidate
        except ValueError:
            continue
    raise ValueError(f"path is outside configured ingest roots: {candidate}")


@dataclass
class ChunkRecord:
    index: int
    size: int
    sha256: str
    committed_at: str


@dataclass
class UploadSession:
    session_id: str
    filename: str
    expected_size: int
    chunk_size: int
    expected_sha256: str | None = None
    asset_kind: str | None = None
    source_system: str | None = None
    created_at: str = field(default_factory=_utc_now)
    updated_at: str = field(default_factory=_utc_now)
    status: str = "staging"
    chunks: dict[str, ChunkRecord] = field(default_factory=dict)
    committed_path: str | None = None
    run_id: str | None = None

    @property
    def total_chunks(self) -> int:
        if self.expected_size == 0:
            return 1
        return (self.expected_size + self.chunk_size - 1) // self.chunk_size

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["chunks"] = {key: asdict(item) for key, item in self.chunks.items()}
        value["total_chunks"] = self.total_chunks
        return value

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> UploadSession:
        chunks = {
            str(key): ChunkRecord(**record) for key, record in (value.get("chunks") or {}).items()
        }
        value = dict(value)
        value.pop("total_chunks", None)
        value["chunks"] = chunks
        return cls(**value)


class RunLogger:
    """Per-run event logger with durable JSON and JSONL artifacts."""

    def __init__(self, root: Path, run_id: str, kind: str, actor: str = "system"):
        self.run_id = run_id
        self.path = root / "runs" / run_id
        self.path.mkdir(parents=True, exist_ok=True)
        self.manifest_path = self.path / "run.json"
        self.events_path = self.path / "events.jsonl"
        self.manifest: dict[str, Any] = {
            "run_id": run_id,
            "kind": kind,
            "actor": actor,
            "status": "running",
            "started_at": _utc_now(),
            "updated_at": _utc_now(),
            "event_count": 0,
            "assets": [],
            "lineage": [],
            "quality": [],
        }
        _atomic_json(self.manifest_path, self.manifest)

    def event(self, name: str, **details: Any) -> None:
        entry = {"ts": _utc_now(), "run_id": self.run_id, "event": name, **details}
        with self.events_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")
        self.manifest["event_count"] += 1
        self.manifest["updated_at"] = entry["ts"]
        _atomic_json(self.manifest_path, self.manifest)
        logger.info("offline ingest event run=%s event=%s", self.run_id, name)

    def add_lineage(self, source: str, target: str, relation: str, **details: Any) -> None:
        self.manifest["lineage"].append(
            {
                "source": source,
                "target": target,
                "relation": relation,
                **details,
            }
        )
        _atomic_json(self.manifest_path, self.manifest)
        self.event("lineage_recorded", source=source, target=target, relation=relation)

    def finish(self, status: str, **details: Any) -> dict[str, Any]:
        self.manifest.update({"status": status, "finished_at": _utc_now(), **details})
        self.manifest["updated_at"] = self.manifest["finished_at"]
        _atomic_json(self.manifest_path, self.manifest)
        self.event("run_finished", status=status, **details)
        return self.manifest

    def diagnostic_paths(self) -> list[Path]:
        return sorted(self.path.rglob("*"))


class OfflineIngestStore:
    """File-lake store and scanner for isolated Windows installations."""

    def __init__(self, root: str | Path | None = None):
        configured = root or os.environ.get("GDA_FILE_LAKE_ROOT", "./file_lake")
        self.root = Path(configured).expanduser().resolve()
        self.sessions_dir = self.root / "sessions"
        self.staging_dir = self.root / "staging"
        self.raw_dir = self.root / "raw"
        self.manifests_dir = self.root / "manifests"
        self.runs_dir = self.root / "runs"
        for directory in (
            self.sessions_dir,
            self.staging_dir,
            self.raw_dir,
            self.manifests_dir,
            self.runs_dir,
        ):
            directory.mkdir(parents=True, exist_ok=True)

    def _session_path(self, session_id: str) -> Path:
        if not re.fullmatch(r"[a-f0-9-]{16,64}", session_id):
            raise ValueError("invalid session id")
        return self.sessions_dir / f"{session_id}.json"

    def _load_session(self, session_id: str) -> UploadSession:
        path = self._session_path(session_id)
        if not path.exists():
            raise FileNotFoundError(session_id)
        return UploadSession.from_dict(json.loads(path.read_text(encoding="utf-8")))

    def _save_session(self, session: UploadSession) -> None:
        session.updated_at = _utc_now()
        _atomic_json(self._session_path(session.session_id), session.to_dict())

    def create_session(
        self,
        filename: str,
        expected_size: int,
        *,
        chunk_size: int = CHUNK_SIZE_DEFAULT,
        expected_sha256: str | None = None,
        asset_kind: str | None = None,
        source_system: str | None = None,
    ) -> dict[str, Any]:
        if expected_size < 0:
            raise ValueError("expected_size must be non-negative")
        if not CHUNK_SIZE_MIN <= chunk_size <= CHUNK_SIZE_MAX:
            raise ValueError(f"chunk_size must be between {CHUNK_SIZE_MIN} and {CHUNK_SIZE_MAX}")
        if expected_sha256 and not re.fullmatch(r"[0-9a-fA-F]{64}", expected_sha256):
            raise ValueError("expected_sha256 must be a SHA-256 hex digest")
        session = UploadSession(
            session_id=str(uuid.uuid4()),
            filename=_safe_name(filename),
            expected_size=expected_size,
            chunk_size=chunk_size,
            expected_sha256=expected_sha256.lower() if expected_sha256 else None,
            asset_kind=asset_kind,
            source_system=source_system,
        )
        self._save_session(session)
        (self.staging_dir / session.session_id / "parts").mkdir(parents=True, exist_ok=True)
        return session.to_dict()

    def session_status(self, session_id: str) -> dict[str, Any]:
        session = self._load_session(session_id)
        return session.to_dict()

    async def write_chunk(
        self,
        session_id: str,
        index: int,
        stream: AsyncIterable[bytes],
        *,
        supplied_sha256: str | None = None,
    ) -> dict[str, Any]:
        session = self._load_session(session_id)
        if session.status not in {"staging", "interrupted"}:
            raise ValueError(f"session is not writable: {session.status}")
        if index < 0 or index >= session.total_chunks:
            raise ValueError(f"chunk index must be between 0 and {session.total_chunks - 1}")
        expected = session.chunk_size
        if index == session.total_chunks - 1:
            expected = session.expected_size - session.chunk_size * index
        part_dir = self.staging_dir / session.session_id / "parts"
        final_path = part_dir / f"{index:08d}.part"
        tmp_path = part_dir / f".{index:08d}.{uuid.uuid4().hex}.tmp"
        digest = hashlib.sha256()
        size = 0
        try:
            with tmp_path.open("wb") as handle:
                async for block in stream:
                    if not block:
                        continue
                    size += len(block)
                    if size > expected:
                        raise ValueError("chunk exceeds expected size")
                    digest.update(block)
                    handle.write(block)
            if size != expected:
                raise ValueError(f"chunk size {size} does not match expected {expected}")
            actual_hash = digest.hexdigest()
            if supplied_sha256 and supplied_sha256.lower() != actual_hash:
                raise ValueError("chunk sha256 mismatch")
            os.replace(tmp_path, final_path)
            session.chunks[str(index)] = ChunkRecord(index, size, actual_hash, _utc_now())
            self._save_session(session)
            return session.to_dict()
        except Exception:
            session.status = "interrupted"
            self._save_session(session)
            raise
        finally:
            if tmp_path.exists():
                tmp_path.unlink()

    def finalize_session(self, session_id: str, *, actor: str = "system") -> dict[str, Any]:
        session = self._load_session(session_id)
        if session.status == "committed":
            return session.to_dict()
        missing = [i for i in range(session.total_chunks) if str(i) not in session.chunks]
        if missing:
            raise ValueError(f"missing chunks: {missing[:20]}")
        run = RunLogger(self.root, str(uuid.uuid4()), "upload_finalize", actor)
        source_id = f"upload:{session.session_id}"
        run.event(
            "finalize_started",
            session_id=session.session_id,
            filename=session.filename,
            expected_size=session.expected_size,
        )
        staged = self.staging_dir / session.session_id / session.filename
        digest = hashlib.sha256()
        size = 0
        with staged.open("wb") as output:
            for index in range(session.total_chunks):
                part = self.staging_dir / session.session_id / "parts" / f"{index:08d}.part"
                with part.open("rb") as source:
                    while block := source.read(HASH_BLOCK_SIZE):
                        digest.update(block)
                        output.write(block)
                        size += len(block)
        actual_hash = digest.hexdigest()
        run.event("assembled", size=size, sha256=actual_hash)
        if size != session.expected_size:
            run.finish("blocked", error="assembled size mismatch")
            raise ValueError("assembled size mismatch")
        if session.expected_sha256 and session.expected_sha256 != actual_hash:
            run.finish(
                "blocked",
                error="file sha256 mismatch",
                expected=session.expected_sha256,
                actual=actual_hash,
            )
            raise ValueError("file sha256 mismatch")
        dated = self.raw_dir / datetime.now(UTC).strftime("%Y/%m/%d")
        dated.mkdir(parents=True, exist_ok=True)
        committed = dated / f"{session.session_id}_{session.filename}"
        os.replace(staged, committed)
        manifest = {
            "asset_id": f"raw:{session.session_id}",
            "session_id": session.session_id,
            "path": str(committed),
            "filename": session.filename,
            "kind": session.asset_kind or _asset_kind(committed),
            "size": size,
            "sha256": actual_hash,
            "source_system": session.source_system,
            "status": "raw_committed",
            "committed_at": _utc_now(),
        }
        _atomic_json(self.manifests_dir / f"raw_{session.session_id}.json", manifest)
        run.manifest["assets"].append(manifest)
        run.add_lineage(source_id, manifest["asset_id"], "staged_to_raw")
        run.finish("succeeded", committed_path=str(committed), asset_id=manifest["asset_id"])
        session.status = "committed"
        session.committed_path = str(committed)
        session.run_id = run.run_id
        self._save_session(session)
        return {**session.to_dict(), "asset": manifest, "run_id": run.run_id}

    def _new_scan_run(self, actor: str) -> RunLogger:
        return RunLogger(self.root, str(uuid.uuid4()), "local_scan", actor)

    def scan_local_path(self, path: str | Path, *, actor: str = "system") -> dict[str, Any]:
        source = ensure_under_allowed_root(path)
        if not source.exists():
            raise FileNotFoundError(str(source))
        run = self._new_scan_run(actor)
        run.event("source_discovered", path=str(source), kind=_asset_kind(source))
        candidates: list[Path] = []
        if source.is_dir() and source.name.lower().endswith(".gdb"):
            candidates = [source]
        elif source.is_file():
            candidates = [source]
        else:
            for item in sorted(source.rglob("*")):
                if item.is_dir() and item.name.lower().endswith(".gdb"):
                    candidates.append(item)
                elif item.is_file() and item.suffix.lower() in {
                    ".tif",
                    ".tiff",
                    ".cog",
                    ".osgb",
                    ".obj",
                    ".ply",
                    ".las",
                    ".laz",
                    ".gpkg",
                    ".shp",
                    ".geojson",
                    ".parquet",
                    ".zip",
                }:
                    candidates.append(item)
        assets = []
        for item in candidates:
            asset = self._scan_asset(item, run)
            asset = self._commit_local_asset(item, asset, run)
            assets.append(asset)
            run.manifest["assets"].append(asset)
            run.add_lineage(str(source), asset["asset_id"], "discovered")
        quality = [self._quality_for_asset(asset) for asset in assets]
        run.manifest["quality"] = quality
        status = "succeeded"
        if any(item["status"] == "blocked" for item in quality):
            status = "blocked"
        elif any(item["status"] == "review" for item in quality):
            status = "review"
        _atomic_json(run.path / "manifest.json", {"assets": assets, "quality": quality})
        _atomic_json(run.path / "quality_report.json", {"run_id": run.run_id, "items": quality})
        return run.finish(status, asset_count=len(assets), source=str(source))

    def _commit_local_asset(
        self, source: Path, asset: dict[str, Any], run: RunLogger
    ) -> dict[str, Any]:
        """Copy a discovered local asset into the immutable raw zone.

        A source already inside ``raw`` is left in place.  Directory bundles
        (FileGDB and 3D tiles) are copied as directories so their internal
        structure remains recoverable.
        """
        try:
            source.relative_to(self.raw_dir.resolve())
            raw_path = source
        except ValueError:
            dated = self.raw_dir / datetime.now(UTC).strftime("%Y/%m/%d")
            dated.mkdir(parents=True, exist_ok=True)
            raw_path = dated / f"{run.run_id}_{asset['sha256'][:12]}_{_safe_name(source.name)}"
            if source.is_dir():
                shutil.copytree(source, raw_path, dirs_exist_ok=False)
            elif source.suffix.lower() == ".shp":
                raw_path.parent.mkdir(parents=True, exist_ok=True)
                for part in _shapefile_parts(source):
                    target = raw_path.with_suffix(part.suffix.lower())
                    shutil.copy2(part, target)
            else:
                shutil.copy2(source, raw_path)
        asset = {**asset, "raw_path": str(raw_path), "raw_status": "committed"}
        run.event(
            "raw_committed",
            asset_id=asset["asset_id"],
            raw_path=str(raw_path),
            size=asset["size"],
            sha256=asset["sha256"],
        )
        run.add_lineage(str(source), str(raw_path), "source_to_raw", asset_id=asset["asset_id"])
        return asset

    def _scan_asset(self, path: Path, run: RunLogger) -> dict[str, Any]:
        kind = _asset_kind(path)
        parts = _shapefile_parts(path)
        bundle_size, bundle_hash = _sha256_parts(parts) if len(parts) > 1 else (None, None)
        stat = path.stat()
        asset = {
            "asset_id": f"scan:{run.run_id}:{uuid.uuid4().hex[:12]}",
            "name": path.name,
            "path": str(path),
            "kind": kind,
            "size": bundle_size
            if bundle_size is not None
            else stat.st_size
            if path.is_file()
            else sum(child.stat().st_size for child in path.rglob("*") if child.is_file()),
            "sha256": bundle_hash or sha256_tree(path),
            "discovered_at": _utc_now(),
        }
        if len(parts) > 1:
            asset["bundle_files"] = [str(part) for part in parts]
        run.event(
            "hash_computed",
            asset_id=asset["asset_id"],
            path=str(path),
            size=asset["size"],
            sha256=asset["sha256"],
        )
        if kind == "filegdb_bundle":
            asset.update(self._scan_filegdb(path, run))
        elif kind == "raster":
            asset.update(self._scan_raster(path, run))
        elif kind == "3d_asset":
            asset.update(self._scan_3d(path))
        elif kind == "archive":
            asset.update(self._scan_archive(path))
        elif kind == "vector_or_table" and path.suffix.lower() == ".shp":
            asset.update(self._scan_shapefile(path, run))
        return asset

    def _scan_filegdb(self, path: Path, run: RunLogger) -> dict[str, Any]:
        layers: list[dict[str, Any]] = []
        adapter = "unavailable"
        # The bundled Python GIS runtime is the production path.  It carries
        # GDAL's OpenFileGDB driver in the pyogrio wheel and works on a plain
        # isolated Windows host without ArcGIS Pro or ArcPy.
        try:
            from .local_gis_runtime import inspect_vector

            layers = inspect_vector(path)
            adapter = "python_gis_runtime"
            run.event("filegdb_scanned", adapter=adapter, layer_count=len(layers))
        except Exception as exc:
            logger.debug("Bundled Python FileGDB scan unavailable: %s", exc)
            run.event("filegdb_python_adapter_unavailable", error=str(exc))
        # ArcPy and osgeo remain compatibility fallbacks for installations
        # that intentionally provision them; neither is required in the
        # Windows deployment contract.
        if not layers:
            try:
                import arcpy  # type: ignore

                old_workspace = arcpy.env.workspace
                try:
                    arcpy.env.workspace = str(path)
                    names = list(arcpy.ListFeatureClasses() or []) + list(arcpy.ListTables() or [])
                    for name in names:
                        desc = arcpy.Describe(name)
                        fields = [
                            {
                                "name": f.name,
                                "type": f.type,
                                "length": getattr(f, "length", None),
                                "nullable": getattr(f, "isNullable", None),
                            }
                            for f in arcpy.ListFields(name)
                        ]
                        count = int(arcpy.management.GetCount(name)[0])
                        sr = getattr(getattr(desc, "spatialReference", None), "factoryCode", None)
                        layers.append(
                            {
                                "name": name,
                                "geometry_type": getattr(desc, "shapeType", None),
                                "feature_count": count,
                                "srid": sr,
                                "fields": fields,
                            }
                        )
                finally:
                    arcpy.env.workspace = old_workspace
                adapter = "arcpy"
                run.event("filegdb_scanned", adapter="arcpy", layer_count=len(layers))
            except Exception as exc:
                logger.debug("ArcPy FileGDB scan unavailable: %s", exc)
        if not layers:
            try:
                from osgeo import ogr  # type: ignore

                datasource = ogr.Open(str(path), 0)
                if datasource:
                    for index in range(datasource.GetLayerCount()):
                        layer = datasource.GetLayer(index)
                        definition = layer.GetLayerDefn()
                        fields = [
                            {
                                "name": definition.GetFieldDefn(i).GetName(),
                                "type": definition.GetFieldDefn(i).GetFieldTypeName(),
                            }
                            for i in range(definition.GetFieldCount())
                        ]
                        layers.append(
                            {
                                "name": layer.GetName(),
                                "geometry_type": layer.GetGeomType(),
                                "feature_count": layer.GetFeatureCount(),
                                "fields": fields,
                            }
                        )
                    adapter = "ogr"
                    run.event("filegdb_scanned", adapter="ogr", layer_count=len(layers))
            except Exception as exc:
                logger.debug("osgeo FileGDB scan unavailable: %s", exc)
        if not layers:
            layers, adapter = self._scan_filegdb_with_ogrinfo(path, run, adapter)
        mapped = [self._map_layer(layer) for layer in layers]
        for layer in mapped:
            run.event(
                "schema_scanned",
                asset_name=layer["name"],
                field_count=len(layer.get("fields", [])),
                mapping=layer.get("mapping"),
            )
        return {
            "layers": mapped,
            "adapter": adapter,
        }

    @staticmethod
    def _scan_filegdb_with_ogrinfo(
        path: Path, run: RunLogger, current_adapter: str
    ) -> tuple[list[dict[str, Any]], str]:
        """Use the GDAL command line when Python GDAL bindings are absent."""
        executable = os.environ.get("GDA_OGRINFO_PATH", "").strip() or shutil.which("ogrinfo")
        if not executable:
            return [], current_adapter
        command = [executable, "-json", "-ro", "-al", "-so", str(path)]
        env = os.environ.copy()
        proj_data = os.environ.get("GDA_PROJ_DATA", "").strip()
        if proj_data:
            env["PROJ_DATA"] = proj_data
        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=max(10, int(os.environ.get("GDA_OGRINFO_TIMEOUT_SECONDS", "300"))),
                check=False,
                env=env,
            )
            if completed.returncode != 0:
                run.event(
                    "filegdb_scan_unavailable",
                    adapter="ogrinfo",
                    returncode=completed.returncode,
                    stderr=completed.stderr[-4000:],
                )
                return [], current_adapter
            payload = json.loads(completed.stdout)
            layers = OfflineIngestStore._layers_from_ogrinfo(payload)
            run.event(
                "filegdb_scanned", adapter="ogrinfo", layer_count=len(layers), executable=executable
            )
            return layers, "ogrinfo"
        except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
            run.event("filegdb_scan_unavailable", adapter="ogrinfo", error=str(exc))
            return [], current_adapter

    def _scan_raster(self, path: Path, run: RunLogger) -> dict[str, Any]:
        metadata: dict[str, Any] = {}
        try:
            import rasterio  # type: ignore

            with rasterio.open(path) as dataset:
                metadata = {
                    "driver": dataset.driver,
                    "width": dataset.width,
                    "height": dataset.height,
                    "count": dataset.count,
                    "dtype": list(dataset.dtypes),
                    "crs": str(dataset.crs) if dataset.crs else None,
                    "bounds": list(dataset.bounds),
                    "resolution": list(dataset.res),
                    "nodata": dataset.nodata,
                    "transform": list(dataset.transform),
                }
            run.event("raster_scanned", adapter="rasterio", **metadata)
        except Exception as exc:
            metadata = {"scan_status": "unavailable", "scan_error": str(exc)}
            run.event("raster_scan_unavailable", error=str(exc))
        metadata["derived_assets"] = ["cog"]
        return {"raster": metadata}

    def _scan_shapefile(self, path: Path, run: RunLogger) -> dict[str, Any]:
        """Profile a SHP bundle with the same OGR contract as FileGDB layers."""
        try:
            from .local_gis_runtime import inspect_vector

            layers = [self._map_layer(layer) for layer in inspect_vector(path)]
            run.event(
                "shapefile_scanned",
                adapter="python_gis_runtime",
                layer_count=len(layers),
            )
            for layer in layers:
                run.event(
                    "schema_scanned",
                    asset_name=layer["name"],
                    field_count=len(layer.get("fields", [])),
                    mapping=layer.get("mapping"),
                )
            return {"adapter": "python_gis_runtime", "layers": layers}
        except Exception as exc:
            logger.debug("Bundled Python shapefile scan unavailable: %s", exc)
            run.event("shapefile_python_adapter_unavailable", error=str(exc))
        executable = os.environ.get("GDA_OGRINFO_PATH", "").strip() or shutil.which("ogrinfo")
        if not executable:
            run.event("shapefile_scan_unavailable", adapter="ogrinfo", error="ogrinfo not found")
            return {"adapter": "unavailable", "layers": []}
        command = [executable, "-json", "-ro", "-al", "-so", str(path)]
        env = os.environ.copy()
        proj_data = os.environ.get("GDA_PROJ_DATA", "").strip()
        if proj_data:
            env["PROJ_DATA"] = proj_data
        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=max(10, int(os.environ.get("GDA_OGRINFO_TIMEOUT_SECONDS", "300"))),
                check=False,
                env=env,
            )
            if completed.returncode != 0:
                run.event(
                    "shapefile_scan_unavailable",
                    adapter="ogrinfo",
                    returncode=completed.returncode,
                    stderr=completed.stderr[-4000:],
                )
                return {"adapter": "unavailable", "layers": []}
            payload = json.loads(completed.stdout)
            layers = [self._map_layer(layer) for layer in self._layers_from_ogrinfo(payload)]
            run.event(
                "shapefile_scanned",
                adapter="ogrinfo",
                layer_count=len(layers),
                executable=executable,
            )
            for layer in layers:
                run.event(
                    "schema_scanned",
                    asset_name=layer["name"],
                    field_count=len(layer.get("fields", [])),
                    mapping=layer.get("mapping"),
                )
            return {"adapter": "ogrinfo", "layers": layers}
        except (OSError, ValueError, subprocess.TimeoutExpired) as exc:
            run.event("shapefile_scan_unavailable", adapter="ogrinfo", error=str(exc))
            return {"adapter": "unavailable", "layers": []}

    @staticmethod
    def _layers_from_ogrinfo(payload: dict[str, Any]) -> list[dict[str, Any]]:
        layers = []
        for item in payload.get("layers", []):
            geometry = (item.get("geometryFields") or [{}])[0]
            coordinate_system = geometry.get("coordinateSystem") or {}
            projjson = coordinate_system.get("projjson") or {}
            authority = projjson.get("id") or {}
            layers.append(
                {
                    "name": item.get("name"),
                    "geometry_type": geometry.get("type"),
                    "feature_count": item.get("featureCount"),
                    "srid": authority.get("code"),
                    "crs_name": projjson.get("name") or coordinate_system.get("wkt"),
                    "extent": geometry.get("extent"),
                    "fields": item.get("fields") or [],
                    "fid_column": item.get("fidColumnName"),
                }
            )
        return layers

    @staticmethod
    def _scan_3d(path: Path) -> dict[str, Any]:
        return {
            "three_d": {
                "format": path.suffix.lower().lstrip("."),
                "index_required": True,
                "source_files": sum(1 for child in path.rglob("*") if child.is_file())
                if path.is_dir()
                else 1,
            }
        }

    @staticmethod
    def _scan_archive(path: Path) -> dict[str, Any]:
        result = {"archive": {"format": path.suffix.lower().lstrip("."), "entries": None}}
        if path.suffix.lower() == ".zip":
            try:
                with zipfile.ZipFile(path) as archive:
                    result["archive"]["entries"] = len(archive.infolist())
                    result["archive"]["contains_filegdb"] = any(
                        name.lower().endswith(".gdb/") or ".gdb/" in name.lower()
                        for name in archive.namelist()
                    )
            except (OSError, zipfile.BadZipFile) as exc:
                result["archive"]["scan_error"] = str(exc)
        return result

    @staticmethod
    def _map_layer(layer: dict[str, Any]) -> dict[str, Any]:
        default_aliases = {
            "DLTB": {"dltb", "jqdltb", "地类图斑", "土地利用现状", "现状用地"},
            "ZRZ": {"zrz", "zjdzrz", "自然幢", "宅基地自然幢"},
            "PDT": {"pdt", "坡度图", "坡度"},
            "STBHHX": {"stbhhx", "生态保护红线", "生态保护重要性"},
            "YJJBNT": {"yjjbnt", "永久基本农田"},
            "XZQH": {"xzqh", "行政区", "行政区划"},
        }
        name = str(layer.get("name", ""))
        from .standard_contracts import normalize_identifier

        normalized = normalize_identifier(name)
        contract = None
        contract_source = None
        # The reviewed/versioned JSON contract is the runtime source of truth.
        # The workbook is discovery evidence and only a fallback for bootstrap.
        configured = os.environ.get("GDA_STANDARD_CONTRACTS", "").strip()
        if not configured:
            configured = os.environ.get("GDA_STANDARD_CONTRACT_XLSX", "").strip()
        if configured:
            try:
                from .standard_contracts import load_contract_catalog

                catalog = load_contract_catalog(configured)
                for candidate, value in (catalog.get("contracts") or {}).items():
                    candidate_name = normalize_identifier(value.get("name", ""))
                    if normalized == normalize_identifier(candidate) or (
                        candidate_name and candidate_name in normalized
                    ):
                        contract = {**value, "code": candidate}
                        contract_source = configured
                        break
            except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
                logger.warning("Unable to load standard contract catalog %s: %s", configured, exc)
        canonical = contract.get("code") if contract else None
        if not canonical:
            for candidate, values in default_aliases.items():
                if normalized == normalize_identifier(candidate) or any(
                    normalize_identifier(value) in normalized for value in values
                ):
                    canonical = candidate
                    break
        fields = layer.get("fields") or []
        aliases = _field_aliases()
        if contract:
            required = set(contract.get("required_fields") or [])
            if not required:
                required = set(contract.get("candidate_fields") or [])
            if not required:
                required = {
                    str(item.get("code") or item.get("name"))
                    for item in contract.get("fields") or []
                    if item.get("code") or item.get("name")
                }
            contract_fields = {
                str(item.get("code") or item.get("name")): item
                for item in contract.get("fields") or []
                if item.get("code") or item.get("name")
            }
            optional_fields = set(contract.get("recommended_fields") or [])
            if not optional_fields:
                optional_fields = set(contract_fields) - required
            field_aliases = {
                field: {
                    str(field).lower(),
                    normalize_identifier(field),
                    str(contract_fields.get(field, {}).get("name", "")).lower(),
                    normalize_identifier(contract_fields.get(field, {}).get("name", "")),
                    *(
                        str(value).lower()
                        for item in [contract_fields.get(field, {})]
                        for value in item.get("aliases", [])
                    ),
                }
                for field in contract_fields
            }
        else:
            required = set(aliases.get(canonical or "", {}))
            field_aliases = aliases.get(canonical or "", {})
        field_mappings = []
        matched = []
        for canonical_field in sorted(required):
            accepted_names = {str(value).lower() for value in field_aliases[canonical_field]}
            source_field = next(
                (
                    value.get("name")
                    for value in fields
                    if str(value.get("name", "")).lower() in accepted_names
                    or normalize_identifier(value.get("name")) in accepted_names
                ),
                None,
            )
            if source_field:
                matched.append(canonical_field)
                field_mappings.append(
                    {
                        "canonical_field": canonical_field,
                        "source_field": source_field,
                        "source_type": next(
                            (
                                value.get("type")
                                for value in fields
                                if str(value.get("name", "")).lower() == str(source_field).lower()
                            ),
                            None,
                        )
                        if source_field
                        else None,
                        "source_length": next(
                            (
                                value.get("length")
                                for value in fields
                                if str(value.get("name", "")).lower() == str(source_field).lower()
                            ),
                            None,
                        )
                        if source_field
                        else None,
                        "standard_type": contract_fields.get(canonical_field, {}).get("data_type")
                        if contract
                        else None,
                        "standard_length": contract_fields.get(canonical_field, {}).get("length")
                        if contract
                        else None,
                        "required": canonical_field in required,
                        "confidence": 1.0,
                    }
                )
        optional_matched = []
        for optional_field in sorted(optional_fields if contract else set()):
            accepted_names = {str(value).lower() for value in field_aliases[optional_field]}
            if any(
                str(value.get("name", "")).lower() in accepted_names
                or normalize_identifier(value.get("name")) in accepted_names
                for value in fields
            ):
                optional_matched.append(optional_field)
        confidence = (
            0.0 if canonical is None else (1.0 if not required else len(matched) / len(required))
        )
        candidate_only = bool(
            (contract and contract.get("authority") != "ea_standard")
            or (not contract and canonical in {"PDT", "STBHHX", "YJJBNT"})
        )
        mapping_status = (
            "manual_review"
            if candidate_only and canonical
            else "accepted"
            if confidence == 1.0
            else "manual_review"
            if canonical
            else "unmatched"
        )
        return {
            **layer,
            "contract": {
                "code": contract.get("code") if contract else canonical,
                "name": contract.get("name") if contract else None,
                "authority": contract.get("authority")
                if contract
                else "default_alias_candidate"
                if canonical in {"PDT", "STBHHX", "YJJBNT"}
                else "default_alias",
                "source": contract_source,
                "publication_gate": contract.get("publication_gate") if contract else "automatic",
                "requires_source_schema_verification": contract.get(
                    "requires_source_schema_verification", False
                )
                if contract
                else False,
                "field_categories": contract.get("field_categories", {}) if contract else {},
                "completeness_note": contract.get("completeness_note") if contract else None,
            },
            "canonical_dataset": canonical,
            "mapping": {
                "status": mapping_status,
                "confidence": round(confidence, 3),
                "evidence": ["name_alias", "field_exact_match"] if canonical else [],
                "contract_source": contract_source,
                "contract_authority": contract.get("authority")
                if contract
                else "default_alias_candidate"
                if canonical in {"PDT", "STBHHX", "YJJBNT"}
                else "default_alias",
                "auto_publish": mapping_status == "accepted",
                "standard_version": os.environ.get(
                    "GDA_NATURAL_RESOURCE_STANDARD_VERSION", "pending-confirmation"
                ),
                "ea_model_candidate": canonical,
                "required_fields": sorted(required),
                "matched_fields": matched,
                "missing_fields": sorted(required - set(matched)),
                "optional_fields": sorted(optional_fields if contract else set()),
                "matched_optional_fields": optional_matched,
                "missing_optional_fields": sorted(
                    (optional_fields if contract else set()) - set(optional_matched)
                ),
                "field_mappings": field_mappings,
            },
        }

    @staticmethod
    def _quality_for_asset(asset: dict[str, Any]) -> dict[str, Any]:
        checks: list[dict[str, Any]] = []
        checks.append({"rule": "asset_hash", "status": "pass" if asset.get("sha256") else "fail"})
        if asset.get("kind") == "filegdb_bundle":
            layers = asset.get("layers") or []
            checks.append(
                {
                    "rule": "filegdb_readable",
                    "status": "pass"
                    if asset.get("adapter") not in {None, "", "unavailable", "none"}
                    else "review",
                }
            )
            checks.append(
                {
                    "rule": "layer_schema",
                    "status": "pass"
                    if layers
                    and all(item.get("mapping", {}).get("status") == "accepted" for item in layers)
                    else ("review" if layers else "blocked"),
                }
            )
            checks.append(
                {
                    "rule": "geometry_and_crs",
                    "status": "review"
                    if any(
                        not item.get("geometry_type")
                        or not (item.get("srid") or item.get("crs_name"))
                        for item in layers
                    )
                    else "pass",
                }
            )
        elif asset.get("kind") == "vector_or_table":
            layers = asset.get("layers") or []
            checks.append(
                {
                    "rule": "vector_schema_readable",
                    "status": "pass"
                    if asset.get("adapter") not in {None, "", "unavailable", "none"}
                    else "review",
                }
            )
            checks.append(
                {
                    "rule": "vector_layer_schema",
                    "status": "pass"
                    if layers
                    and all(item.get("mapping", {}).get("status") == "accepted" for item in layers)
                    else ("review" if layers else "blocked"),
                }
            )
            checks.append(
                {
                    "rule": "geometry_and_crs",
                    "status": "review"
                    if any(
                        not item.get("geometry_type")
                        or not (item.get("srid") or item.get("crs_name"))
                        for item in layers
                    )
                    else "pass",
                }
            )
        elif asset.get("kind") == "raster":
            raster = asset.get("raster", {})
            checks.append(
                {
                    "rule": "raster_metadata",
                    "status": "pass" if raster.get("width") and raster.get("crs") else "review",
                }
            )
            checks.append(
                {
                    "rule": "nodata_and_extent",
                    "status": "review" if raster.get("scan_status") == "unavailable" else "pass",
                }
            )
        elif asset.get("kind") == "archive":
            checks.append(
                {
                    "rule": "archive_readable",
                    "status": "fail" if asset.get("archive", {}).get("scan_error") else "pass",
                }
            )
        blocking = [item for item in checks if item["status"] in {"fail", "blocked"}]
        status = (
            "blocked"
            if blocking
            else ("review" if any(item["status"] == "review" for item in checks) else "pass")
        )
        return {
            "asset_id": asset["asset_id"],
            "status": status,
            "checks": checks,
            "planned_rules": [
                "geometry_validity",
                "primary_key_uniqueness",
                "geometry_area_consistency",
                "topology_overlap_and_gap",
                "administrative_extent",
                "crs_srid_and_axis_order",
                "temporal_validity",
                "code_value_domain",
                "referential_integrity",
                "classification_and_access_policy",
                "filegdb_layer_consistency",
                "raster_nodata_resolution_extent",
                "paper9_input_coverage",
            ],
            "uncomputed_rules": [
                "geometry_validity",
                "primary_key_uniqueness",
                "geometry_area_consistency",
                "topology_overlap_and_gap",
                "administrative_extent",
                "temporal_validity",
                "code_value_domain",
                "referential_integrity",
                "classification_and_access_policy",
                "paper9_input_coverage",
            ],
            "blocking_failures": [item["rule"] for item in blocking],
            "evaluated_at": _utc_now(),
        }

    def run_deep_quality(self, run_id: str, *, actor: str = "system") -> dict[str, Any]:
        """Read real features/pixels and persist deterministic quality evidence."""

        parent = self.get_run(run_id)
        quality_run = RunLogger(self.root, str(uuid.uuid4()), "deep_quality", actor)
        items: list[dict[str, Any]] = []

        def record(item: dict[str, Any], asset_id: Any) -> None:
            items.append(item)
            quality_run.add_lineage(
                str(asset_id),
                f"quality:{quality_run.run_id}:{len(items)}",
                "deep_quality_evaluated",
                status=item["status"],
                layer=item.get("layer"),
            )

        for asset in parent.get("assets") or []:
            kind = asset.get("kind")
            source = Path(str(asset.get("raw_path") or ""))
            if kind in {"filegdb_bundle", "vector_or_table"} and asset.get("layers"):
                for layer in asset.get("layers") or []:
                    field_names = {
                        str(field.get("name") or "") for field in layer.get("fields") or []
                    }
                    key_fields = [field for field in ("BSM", "OBJECTID") if field in field_names]
                    try:
                        from .local_gis_runtime import quality_vector

                        result = quality_vector(
                            source,
                            layer=(
                                layer.get("name")
                                if source.suffix.lower() not in {".shp", ".geojson"}
                                else None
                            ),
                            key_fields=key_fields[:1],
                        )
                        semantic_status = (layer.get("mapping") or {}).get("status")
                        status = result["status"]
                        if status == "pass" and semantic_status not in {"accepted"}:
                            status = "review"
                        item = {
                            "asset_id": asset.get("asset_id"),
                            "asset_name": asset.get("name"),
                            "layer": layer.get("name"),
                            "kind": "vector",
                            "status": status,
                            "semantic_mapping_status": semantic_status,
                            "checks": result,
                        }
                    except Exception as exc:
                        item = {
                            "asset_id": asset.get("asset_id"),
                            "asset_name": asset.get("name"),
                            "layer": layer.get("name"),
                            "kind": "vector",
                            "status": "blocked",
                            "error": str(exc),
                        }
                    record(item, asset.get("asset_id"))
                continue
            elif kind == "raster":
                try:
                    from .local_gis_runtime import quality_raster

                    result = quality_raster(source)
                    item = {
                        "asset_id": asset.get("asset_id"),
                        "asset_name": asset.get("name"),
                        "layer": asset.get("name"),
                        "kind": "raster",
                        "status": result["status"],
                        "checks": result,
                    }
                except Exception as exc:
                    item = {
                        "asset_id": asset.get("asset_id"),
                        "asset_name": asset.get("name"),
                        "layer": asset.get("name"),
                        "kind": "raster",
                        "status": "blocked",
                        "error": str(exc),
                    }
            else:
                item = {
                    "asset_id": asset.get("asset_id"),
                    "asset_name": asset.get("name"),
                    "layer": None,
                    "kind": kind,
                    "status": "not_applicable",
                }
            record(item, asset.get("asset_id"))

        counts: dict[str, int] = {}
        for item in items:
            counts[item["status"]] = counts.get(item["status"], 0) + 1
        status = (
            "blocked"
            if counts.get("blocked")
            else "review"
            if counts.get("review")
            else "pass"
        )
        report = {
            "quality_run_id": quality_run.run_id,
            "parent_run_id": run_id,
            "status": status,
            "counts": counts,
            "items": items,
            "evaluated_at": _utc_now(),
        }
        report_root = self.root / "quality" / quality_run.run_id
        _atomic_json(report_root / "deep_quality_report.json", report)
        # Attach the evidence to the parent scan manifest so a subsequent
        # standardization request cannot accidentally use only shallow checks.
        parent_path = self.runs_dir / run_id / "run.json"
        parent["deep_quality_run_id"] = quality_run.run_id
        parent["deep_quality"] = report
        _atomic_json(parent_path, parent)
        quality_run.manifest["deep_quality"] = report
        return quality_run.finish(status, parent_run_id=run_id, counts=counts)

    def get_run(self, run_id: str) -> dict[str, Any]:
        if not re.fullmatch(r"[a-f0-9-]{16,64}", run_id):
            raise ValueError("invalid run id")
        path = self.runs_dir / run_id / "run.json"
        if not path.exists():
            raise FileNotFoundError(run_id)
        return json.loads(path.read_text(encoding="utf-8"))

    def list_runs(self, *, limit: int = 50) -> list[dict[str, Any]]:
        """Return recent durable runs for the operations console.

        Run manifests are the source of truth in an isolated deployment, so
        this deliberately avoids introducing a second database index.  A
        corrupt or half-written manifest is reported as a failed inspection
        row instead of making the whole list unavailable after a power loss.
        """
        try:
            bounded_limit = max(1, min(int(limit), 200))
        except (TypeError, ValueError) as exc:
            raise ValueError("limit must be an integer") from exc
        candidates = sorted(
            self.runs_dir.glob("*/run.json"),
            key=lambda item: item.stat().st_mtime,
            reverse=True,
        )[:bounded_limit]
        runs: list[dict[str, Any]] = []
        for path in candidates:
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                payload["manifest_path"] = str(path)
            except (OSError, ValueError, TypeError) as exc:
                payload = {
                    "run_id": path.parent.name,
                    "kind": "unknown",
                    "status": "blocked",
                    "manifest_path": str(path),
                    "error": f"invalid run manifest: {exc}",
                }
            runs.append(payload)
        return runs

    def overview(self, *, limit: int = 50) -> dict[str, Any]:
        """Build a bounded dashboard summary from immutable local artifacts."""
        runs = self.list_runs(limit=limit)
        status_counts: dict[str, int] = {}
        quality_counts: dict[str, int] = {}
        asset_count = 0
        for run in runs:
            status = str(run.get("status") or "unknown")
            status_counts[status] = status_counts.get(status, 0) + 1
            assets = run.get("assets") or []
            asset_count += len(assets)
            for quality in run.get("quality") or []:
                quality_status = str(quality.get("status") or "unknown")
                quality_counts[quality_status] = quality_counts.get(quality_status, 0) + 1
        return {
            "schema": "gda.offline-ingest-overview.v1",
            "lake_root": str(self.root),
            "run_count": len(runs),
            "asset_count_in_recent_runs": asset_count,
            "status_counts": status_counts,
            "quality_counts": quality_counts,
            "runs": runs,
            "generated_at": _utc_now(),
        }

    def create_standardization_plan(
        self,
        run_id: str,
        *,
        actor: str = "system",
        allow_review: bool = False,
    ) -> dict[str, Any]:
        """Create a durable standardization/promotion contract after QC.

        This is intentionally a durable plan. The bundled Python GIS runtime
        performs FileGDB->GeoParquet and TIFF->COG conversion on Windows;
        PostGIS and external GDAL are optional target adapters.
        """
        parent = self.get_run(run_id)
        deep_quality = parent.get("deep_quality") or {}
        quality = deep_quality.get("items") or parent.get("quality") or []
        blocked = [item for item in quality if item.get("status") == "blocked"]
        review = [item for item in quality if item.get("status") == "review"]
        if blocked:
            raise ValueError(f"quality gate blocked: {len(blocked)} asset(s)")
        if review and not allow_review:
            raise ValueError("quality review is required before promotion")

        plan_run = RunLogger(self.root, str(uuid.uuid4()), "standardization_plan", actor)
        plan_run.event("promotion_started", parent_run_id=run_id, allow_review=allow_review)
        plan_root = self.root / "standardized" / plan_run.run_id
        plan_root.mkdir(parents=True, exist_ok=True)
        outputs: list[dict[str, Any]] = []
        for asset in parent.get("assets", []):
            kind = asset.get("kind")
            layers = asset.get("layers") or []
            if kind in {"filegdb_bundle", "vector_or_table"} and layers:
                for layer in layers:
                    mapping = layer.get("mapping") or {}
                    canonical = mapping.get("ea_model_candidate") or layer.get("name")
                    asset_suffix = _safe_name(str(asset.get("asset_id", "asset"))[-12:])
                    target_id = (
                        f"standardized:{plan_run.run_id}:"
                        f"{_safe_name(str(canonical))}:{asset_suffix}"
                    )
                    output = {
                        "target_id": target_id,
                        "source_asset_id": asset.get("asset_id"),
                        "source_raw_path": asset.get("raw_path"),
                        "source_layer": layer.get("name"),
                        "canonical_dataset": mapping.get("ea_model_candidate"),
                        "target_kind": "postgis_or_geoparquet",
                        "target_name": f"{_safe_name(str(canonical))}__{asset_suffix}",
                        "mapping": mapping,
                        "execution_status": "planned",
                    }
                    outputs.append(output)
                    plan_run.add_lineage(
                        asset["asset_id"],
                        target_id,
                        "standardization_planned",
                        source_layer=layer.get("name"),
                    )
            elif kind == "raster":
                asset_suffix = _safe_name(str(asset.get("asset_id", "asset"))[-12:])
                target_id = (
                    f"derived:{plan_run.run_id}:"
                    f"{_safe_name(asset.get('name', 'raster'))}:{asset_suffix}.cog"
                )
                output = {
                    "target_id": target_id,
                    "source_asset_id": asset.get("asset_id"),
                    "source_raw_path": asset.get("raw_path"),
                    "target_kind": "cog_stac",
                    "target_name": (
                        f"{_safe_name(asset.get('name', 'raster'))}__{asset_suffix}.cog.tif"
                    ),
                    "execution_status": "planned",
                    "parameters": {"compression": "DEFLATE"},
                }
                outputs.append(output)
                plan_run.add_lineage(asset["asset_id"], target_id, "derivation_planned")
            elif kind == "3d_asset":
                asset_suffix = _safe_name(str(asset.get("asset_id", "asset"))[-12:])
                target_id = (
                    f"derived:{plan_run.run_id}:"
                    f"{_safe_name(asset.get('name', 'model'))}:{asset_suffix}:index"
                )
                outputs.append(
                    {
                        "target_id": target_id,
                        "source_asset_id": asset.get("asset_id"),
                        "source_raw_path": asset.get("raw_path"),
                        "target_kind": "three_d_index",
                        "target_name": (
                            f"{_safe_name(asset.get('name', 'model'))}__{asset_suffix}.index.json"
                        ),
                        "execution_status": "planned",
                    }
                )
                plan_run.add_lineage(asset["asset_id"], target_id, "index_planned")
            else:
                target_id = (
                    f"standardized:{plan_run.run_id}:{_safe_name(asset.get('name', 'asset'))}"
                )
                outputs.append(
                    {
                        "target_id": target_id,
                        "source_asset_id": asset.get("asset_id"),
                        "source_raw_path": asset.get("raw_path"),
                        "target_kind": "catalog_reference",
                        "target_name": _safe_name(asset.get("name", "asset")),
                        "execution_status": "planned",
                    }
                )
                plan_run.add_lineage(asset["asset_id"], target_id, "catalog_reference_planned")
        plan = {
            "plan_id": plan_run.run_id,
            "parent_run_id": run_id,
            "status": "planned",
            "created_at": _utc_now(),
            "standard_version": os.environ.get(
                "GDA_NATURAL_RESOURCE_STANDARD_VERSION", "pending-confirmation"
            ),
            "outputs": outputs,
            "ontology_binding": "pending_after_standardization_and_quality_gate",
        }
        _atomic_json(plan_root / "standardization_plan.json", plan)
        plan_run.manifest["standardization_plan"] = plan
        return plan_run.finish("planned", parent_run_id=run_id, output_count=len(outputs))

    def execute_standardization_plan(
        self,
        plan_id: str,
        *,
        actor: str = "system",
        vector_format: str | None = None,
    ) -> dict[str, Any]:
        """Materialize a reviewed plan with the bundled Python GIS runtime.

        The default local target is GeoParquet and COG.  A Windows host may
        override the vector format to ``GPKG`` or provide a separate PostGIS
        executor. External GDAL is an optional fallback. Every output hash and
        lineage edge is durable; a missing adapter fails closed instead of
        changing the plan to success.
        """
        if not re.fullmatch(r"[a-f0-9-]{16,64}", plan_id):
            raise ValueError("invalid plan id")
        plan_path = self.root / "standardized" / plan_id / "standardization_plan.json"
        if not plan_path.exists():
            raise FileNotFoundError(plan_id)
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        if plan.get("status") != "planned":
            raise ValueError(f"plan is not executable: {plan.get('status')}")
        parent_run = self.get_run(plan["parent_run_id"])
        source_assets = {item.get("asset_id"): item for item in parent_run.get("assets") or []}
        execution_run = RunLogger(self.root, str(uuid.uuid4()), "standardization_execute", actor)
        output_root = self.root / "materialized" / plan_id
        output_root.mkdir(parents=True, exist_ok=True)
        selected_vector_format = (
            vector_format or os.environ.get("GDA_STANDARDIZED_VECTOR_FORMAT", "Parquet")
        ).strip()
        if selected_vector_format not in {"Parquet", "GPKG", "PostgreSQL"}:
            raise ValueError("GDA_STANDARDIZED_VECTOR_FORMAT must be Parquet, GPKG or PostgreSQL")
        ogr2ogr = os.environ.get("GDA_OGR2OGR_PATH", "").strip() or shutil.which("ogr2ogr")
        gdal_translate = os.environ.get("GDA_GDAL_TRANSLATE_PATH", "").strip() or shutil.which(
            "gdal_translate"
        )
        command_env = os.environ.copy()
        for key in ("GDA_PROJ_DATA", "GDA_GDAL_DATA"):
            value = os.environ.get(key, "").strip()
            if value:
                command_env["PROJ_DATA" if key == "GDA_PROJ_DATA" else "GDAL_DATA"] = value
        outputs: list[dict[str, Any]] = []
        failures: list[dict[str, Any]] = []

        for planned in plan.get("outputs") or []:
            target_kind = planned.get("target_kind")
            source_raw = planned.get("source_raw_path")
            source = Path(source_raw).expanduser().resolve() if source_raw else None
            record = {**planned, "execution_status": "blocked"}
            if source and not source.exists():
                record["error"] = "source raw path does not exist"
                failures.append(record)
                execution_run.event("materialization_blocked", **record)
                outputs.append(record)
                continue
            if source:
                try:
                    source.relative_to(self.raw_dir.resolve())
                except ValueError:
                    record["error"] = "source is outside immutable raw zone"
                    failures.append(record)
                    execution_run.event("materialization_blocked", **record)
                    outputs.append(record)
                    continue
            try:
                if target_kind == "postgis_or_geoparquet":
                    target_name = _safe_name(planned.get("target_name", "layer"))
                    if selected_vector_format == "PostgreSQL":
                        if not ogr2ogr:
                            raise RuntimeError(
                                "PostgreSQL output requires the optional ogr2ogr/PostGIS adapter"
                            )
                        postgis_dsn = os.environ.get("GDA_POSTGIS_DSN", "").strip()
                        if not postgis_dsn:
                            raise RuntimeError("GDA_POSTGIS_DSN is required for PostgreSQL output")
                        target = None
                        command = [
                            ogr2ogr,
                            "-f",
                            "PostgreSQL",
                            postgis_dsn,
                            str(source),
                            str(planned.get("source_layer", "")),
                            "-nln",
                            target_name,
                            "-overwrite",
                        ]
                    elif selected_vector_format in {"Parquet", "GPKG"}:
                        target_suffix = (
                            ".parquet" if selected_vector_format == "Parquet" else ".gpkg"
                        )
                        target = output_root / f"{target_name}{target_suffix}"
                        python_result = None
                        try:
                            from .local_gis_runtime import write_vector

                            python_result = write_vector(
                                source,
                                target,
                                layer=(
                                    planned.get("source_layer")
                                    if source.suffix.lower() not in {".shp", ".geojson"}
                                    else None
                                ),
                                format_name=selected_vector_format,
                            )
                        except Exception as python_exc:
                            if not ogr2ogr:
                                raise RuntimeError(
                                    f"built-in vector adapter failed: {python_exc}"
                                ) from python_exc
                            command = [
                                ogr2ogr,
                                "-f",
                                selected_vector_format,
                                str(target),
                                str(source),
                                str(planned.get("source_layer", "")),
                                "-overwrite",
                            ]
                            completed = subprocess.run(
                                command,
                                capture_output=True,
                                text=True,
                                encoding="utf-8",
                                errors="replace",
                                timeout=max(
                                    30,
                                    int(
                                        os.environ.get(
                                            "GDA_OGR2OGR_TIMEOUT_SECONDS", "3600"
                                        )
                                    ),
                                ),
                                check=False,
                                env=command_env,
                            )
                            if completed.returncode != 0:
                                raise RuntimeError(
                                    completed.stderr[-4000:] or "ogr2ogr failed"
                                ) from python_exc
                            python_result = {"adapter": "ogr2ogr"}
                        record.update(
                            {
                                "execution_status": "succeeded",
                                "adapter": python_result.get("adapter", "python_gis_runtime"),
                                "target_path": str(target),
                                "target_locator": None,
                                "target_format": selected_vector_format,
                                "target_sha256": sha256_tree(target),
                                "target_size": target.stat().st_size,
                                "materialization_profile": python_result,
                            }
                        )
                elif target_kind == "cog_stac":
                    target = output_root / f"{_safe_name(planned.get('target_name', 'raster'))}"
                    try:
                        from .local_gis_runtime import write_cog

                        raster_profile = write_cog(source, target)
                    except Exception as python_exc:
                        if not gdal_translate:
                            raise RuntimeError(
                                f"built-in raster adapter failed: {python_exc}"
                            ) from python_exc
                        command = [
                            gdal_translate,
                            str(source),
                            str(target),
                            "-of",
                            "COG",
                            "-co",
                            "COMPRESS=DEFLATE",
                            "-co",
                            "BIGTIFF=IF_SAFER",
                        ]
                        completed = subprocess.run(
                            command,
                            capture_output=True,
                            text=True,
                            encoding="utf-8",
                            errors="replace",
                            timeout=max(
                                30,
                                int(
                                    os.environ.get(
                                        "GDA_GDAL_TRANSLATE_TIMEOUT_SECONDS", "3600"
                                    )
                                ),
                            ),
                            check=False,
                            env=command_env,
                        )
                        if completed.returncode != 0:
                            raise RuntimeError(
                                completed.stderr[-4000:] or "gdal_translate failed"
                            ) from python_exc
                        raster_profile = {"adapter": "gdal_translate"}
                    stac_path = target.with_suffix(".stac-item.json")
                    raster = (
                        source_assets.get(planned.get("source_asset_id"), {}).get("raster") or {}
                    )
                    stac = {
                        "stac_version": "1.0.0",
                        "type": "Feature",
                        "id": target.stem,
                        "bbox": raster.get("bounds"),
                        "geometry": None,
                        "properties": {
                            "datetime": None,
                            "proj:epsg": raster.get("crs"),
                            "gda:source_asset_id": planned.get("source_asset_id"),
                        },
                        "assets": {
                            "data": {
                                "href": str(target),
                                "type": "image/tiff; application=geotiff",
                            }
                        },
                    }
                    _atomic_json(stac_path, stac)
                    record.update(
                        {
                            "execution_status": "succeeded",
                            "adapter": raster_profile.get("adapter", "python_gis_runtime"),
                            "target_path": str(target),
                            "stac_item_path": str(stac_path),
                            "target_sha256": sha256_tree(target),
                            "target_size": target.stat().st_size,
                            "materialization_profile": raster_profile,
                        }
                    )
                elif target_kind == "three_d_index":
                    target = output_root / _safe_name(
                        planned.get("target_name", "model.index.json")
                    )
                    _atomic_json(
                        target,
                        {
                            "type": "three_d_asset_index",
                            "source_asset_id": planned.get("source_asset_id"),
                            "source_raw_path": str(source) if source else None,
                            "status": "indexed_reference",
                        },
                    )
                    record.update(
                        {
                            "execution_status": "succeeded",
                            "adapter": "json_index",
                            "target_path": str(target),
                            "target_sha256": sha256_tree(target),
                            "target_size": target.stat().st_size,
                        }
                    )
                else:
                    record.update({"execution_status": "catalog_only"})
                execution_run.add_lineage(
                    planned.get("source_asset_id", "unknown"),
                    planned.get("target_id", "unknown"),
                    "materialized",
                    target_path=record.get("target_path"),
                )
            except (OSError, RuntimeError, subprocess.TimeoutExpired) as exc:
                record["error"] = str(exc)
                failures.append(record)
                execution_run.event("materialization_blocked", **record)
            outputs.append(record)
        status = "blocked" if failures else "succeeded"
        materialization = {
            "execution_id": execution_run.run_id,
            "plan_id": plan_id,
            "status": status,
            "vector_format": selected_vector_format,
            "outputs": outputs,
            "failures": failures,
            "created_at": _utc_now(),
        }
        _atomic_json(output_root / "materialization.json", materialization)
        execution_run.manifest["materialization"] = materialization
        return execution_run.finish(status, plan_id=plan_id, output_count=len(outputs))

    def create_ontology_binding(
        self,
        plan_id: str,
        *,
        actor: str = "system",
        ontology_version: str | None = None,
        binding_mode: str = "production",
    ) -> dict[str, Any]:
        """Bind materialized products to ontology references.

        Production mode remains fail-closed.  Rehearsal mode writes to an
        explicitly non-production binding and is used to prove the semantic
        path with supplied sample data without claiming it is authoritative.
        """
        if not re.fullmatch(r"[a-f0-9-]{16,64}", plan_id):
            raise ValueError("invalid plan id")
        if binding_mode not in {"production", "rehearsal"}:
            raise ValueError("binding_mode must be production or rehearsal")
        plan_path = self.root / "standardized" / plan_id / "standardization_plan.json"
        materialization_path = self.root / "materialized" / plan_id / "materialization.json"
        if not plan_path.exists() or not materialization_path.exists():
            raise FileNotFoundError(plan_id)
        materialization = json.loads(materialization_path.read_text(encoding="utf-8"))
        if materialization.get("status") != "succeeded":
            raise ValueError("ontology binding requires successful materialization")
        rejected = []
        bindings = []
        skipped = []
        for output in materialization.get("outputs") or []:
            mapping = output.get("mapping") or {}
            authority = mapping.get("contract_authority")
            if output.get("execution_status") not in {"succeeded", "catalog_only"}:
                rejected.append(
                    {"target_id": output.get("target_id"), "reason": "not_materialized"}
                )
                continue
            if output.get("target_kind") not in {"postgis_or_geoparquet", "cog_stac"}:
                continue
            canonical = output.get("canonical_dataset")
            if binding_mode == "rehearsal" and not canonical:
                target_name = str(output.get("target_name") or "").casefold()
                if output.get("target_kind") == "cog_stac" and any(
                    token in target_name for token in ("gdem", "dem", "高程")
                ):
                    canonical = "SZGCMX"
                elif output.get("target_kind") == "cog_stac":
                    canonical = "SZZSYX"
            if binding_mode == "rehearsal":
                if not canonical:
                    skipped.append(
                        {
                            "target_id": output.get("target_id"),
                            "reason": "no_ontology_schema_candidate",
                        }
                    )
                    continue
                bindings.append(
                    {
                        "target_id": output.get("target_id"),
                        "canonical_dataset": canonical,
                        "target_path": output.get("target_path"),
                        "source_asset_id": output.get("source_asset_id"),
                        "binding_mode": "reference_only_rehearsal",
                        "mapping_status": mapping.get("status")
                        or "observed_raster_mapping",
                        "mapping_authority": authority or "rehearsal_observation",
                        "production_eligible": False,
                    }
                )
                continue
            if mapping.get("status") != "accepted" or authority != "ea_standard":
                rejected.append(
                    {
                        "target_id": output.get("target_id"),
                        "canonical_dataset": canonical,
                        "mapping_status": mapping.get("status"),
                        "contract_authority": authority,
                        "reason": "authoritative_contract_required",
                    }
                )
                continue
            bindings.append(
                {
                    "target_id": output.get("target_id"),
                    "canonical_dataset": canonical,
                    "target_path": output.get("target_path"),
                    "source_asset_id": output.get("source_asset_id"),
                    "binding_mode": "reference_only",
                }
            )
        if rejected or not bindings:
            reason = (
                "authoritative contracts required"
                if binding_mode == "production"
                else "no ontology schema candidate available for rehearsal"
            )
            raise ValueError(
                f"ontology binding rejected {len(rejected)} output(s); {reason}"
            )
        binding_run = RunLogger(self.root, str(uuid.uuid4()), "ontology_binding", actor)
        binding = {
            "binding_id": binding_run.run_id,
            "plan_id": plan_id,
            "ontology_version": ontology_version
            or os.environ.get("GDA_ONTOLOGY_VERSION", "natural-resource-ontology-pending"),
            "status": "accepted"
            if binding_mode == "production"
            else "accepted_for_rehearsal",
            "created_at": _utc_now(),
            "binding_mode": binding_mode,
            "production_eligible": binding_mode == "production",
            "instance_policy": "reference_only_no_raw_record_copy",
            "bindings": bindings,
            "skipped": skipped,
        }
        binding_root = self.root / "ontology_bindings" / binding_run.run_id
        _atomic_json(binding_root / "binding.json", binding)
        for item in bindings:
            binding_run.add_lineage(
                item["target_id"],
                f"ontology:{item['canonical_dataset']}",
                "ontology_reference_bound",
                binding_mode=item["binding_mode"],
            )
        binding_run.manifest["ontology_binding"] = binding
        return binding_run.finish("succeeded", plan_id=plan_id, binding_count=len(bindings))

    def export_diagnostics(self, run_id: str, destination: str | Path | None = None) -> Path:
        run_path = self.runs_dir / run_id
        if not run_path.is_dir():
            raise FileNotFoundError(run_id)
        target = (
            Path(destination).expanduser().resolve() if destination else self.root / "diagnostics"
        )
        target.mkdir(parents=True, exist_ok=True)
        archive = target / f"{run_id}.zip"
        with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as output:
            for child in run_path.rglob("*"):
                if child.is_file():
                    output.write(child, child.relative_to(run_path.parent))
        return archive


def run_local_scan(
    path: str | Path, *, root: str | Path | None = None, actor: str = "system"
) -> dict[str, Any]:
    """Convenience entry point for the Windows collector and CLI."""
    return OfflineIngestStore(root).scan_local_path(path, actor=actor)
