# ArcPy MCP Server Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (- [ ]) syntax for tracking.

**Goal:** Build and privately publish a Windows service that exposes allowlisted ArcPy operations through authenticated Streamable HTTP MCP, resumable artifacts, and a persistent single-worker job queue.

**Architecture:** A FastMCP/Starlette gateway runs in its own uv-managed environment and owns TLS, authentication, artifacts, SQLite, and jobs. It supervises a JSON Lines worker launched with the ArcGIS Pro default Python at D:\Program Files\ArcGIS\Pro\bin\Python\envs\arcgispro-py3\python.exe, so no gateway dependency is installed into the Esri environment.

**Tech Stack:** Python 3.13, uv, FastMCP 3.2.4, Starlette, Uvicorn, Pydantic Settings, aiosqlite, cryptography, PyYAML, pytest, pytest-asyncio, httpx, ArcPy 3.7.1, PowerShell, Windows Task Scheduler.

---

This is plan 1 of 2. Complete this server plan before executing the Codex plugin plan.

## File Map

Repository root during execution: D:\adk\standalone\arcpy-mcp-server

- pyproject.toml: gateway and development dependencies plus pytest and Ruff configuration.
- .gitignore: virtual environment, secrets, certificates, databases, test output, and ArcGIS scratch data.
- .env.example: non-secret deployment configuration.
- src/arcpy_mcp_server/config.py: validated settings and deployment paths.
- src/arcpy_mcp_server/models.py: job, artifact, capability, and protocol types.
- src/arcpy_mcp_server/auth.py: static Bearer verifier and HMAC artifact URL signer.
- src/arcpy_mcp_server/db.py: SQLite lifecycle, schema, and typed persistence methods.
- src/arcpy_mcp_server/workspace.py: workspace containment and safe ZIP extraction.
- src/arcpy_mcp_server/artifacts.py: resumable upload, hash verification, packaging, download, and retention.
- src/arcpy_mcp_server/jobs.py: queue, state transitions, cancellation, reconciliation, and retention.
- src/arcpy_mcp_server/catalog.py: YAML catalog loading and JSON Schema validation.
- src/arcpy_mcp_server/worker_protocol.py: JSON Lines request and response parsing.
- src/arcpy_mcp_server/worker_supervisor.py: persistent worker lifecycle, request serialization, timeout, and restart.
- src/arcpy_mcp_server/worker/main.py: ArcGIS Python process entry point.
- src/arcpy_mcp_server/worker/health.py: ArcPy product, license, extension, and CPU/GPU capability probe.
- src/arcpy_mcp_server/worker/executor.py: allowlisted dispatch and ArcPy message capture.
- src/arcpy_mcp_server/worker/tool_bindings.py: explicit ArcPy vector, raster, map, and deep-learning bindings.
- src/arcpy_mcp_server/mcp_tools.py: stable MCP tools and dedicated convenience tools.
- src/arcpy_mcp_server/app.py: FastMCP and Starlette assembly.
- src/arcpy_mcp_server/__main__.py: TLS Uvicorn launcher.
- src/arcpy_mcp_server/tls_bootstrap.py: local CA and IP-SAN server certificate generation.
- config/tool_catalog.yaml: executable allowlist and parameter schemas.
- scripts/*.ps1: bootstrap, firewall, scheduled task, start, stop, and status operations.
- tests/: unit, protocol, HTTP, worker recovery, security, and real ArcPy smoke tests.

### Task 1: Create the Independent Server Repository

**Files:**
- Create: D:\adk\standalone\arcpy-mcp-server\pyproject.toml
- Create: D:\adk\standalone\arcpy-mcp-server\.gitignore
- Create: D:\adk\standalone\arcpy-mcp-server\.env.example
- Create: D:\adk\standalone\arcpy-mcp-server\src\arcpy_mcp_server\__init__.py
- Create: D:\adk\standalone\arcpy-mcp-server\tests\test_package.py

- [ ] **Step 1: Create and initialize the repository**

Run:

~~~powershell
New-Item -ItemType Directory -Force D:\adk\standalone\arcpy-mcp-server
Set-Location D:\adk\standalone\arcpy-mcp-server
git init -b main
~~~

Expected: an empty Git repository on branch main.

- [ ] **Step 2: Write the failing package test**

~~~python
def test_package_version():
    import arcpy_mcp_server

    assert arcpy_mcp_server.__version__ == "0.1.0"
~~~

- [ ] **Step 3: Run the test and verify the package is missing**

Run:

~~~powershell
uvx pytest tests\test_package.py -v
~~~

Expected: FAIL with ModuleNotFoundError for arcpy_mcp_server.

- [ ] **Step 4: Create the project metadata**

Create pyproject.toml:

~~~toml
[build-system]
requires = ["hatchling>=1.27"]
build-backend = "hatchling.build"

[project]
name = "arcpy-mcp-server"
version = "0.1.0"
description = "Authenticated remote ArcPy MCP server"
requires-python = ">=3.13,<3.14"
dependencies = [
  "aiosqlite>=0.21,<1",
  "cryptography>=45,<46",
  "fastmcp==3.2.4",
  "jsonschema>=4.24,<5",
  "pydantic>=2.11,<3",
  "pydantic-settings>=2.10,<3",
  "PyYAML>=6.0,<7",
  "starlette>=0.46,<1",
  "uvicorn[standard]>=0.34,<1",
]

[dependency-groups]
dev = [
  "httpx>=0.28,<1",
  "pytest>=8.4,<9",
  "pytest-asyncio>=1.0,<2",
  "ruff>=0.12,<1",
]

[tool.hatch.build.targets.wheel]
packages = ["src/arcpy_mcp_server"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]

[tool.ruff]
line-length = 100
target-version = "py313"
~~~

Create .gitignore:

~~~gitignore
.venv/
__pycache__/
.pytest_cache/
.ruff_cache/
*.pyc
*.db
*.db-shm
*.db-wal
.env
certs/private/
data/
dist/
~~~

Create .env.example:

~~~dotenv
ARCPY_MCP_PUBLIC_BASE_URL=https://192.168.25.228:8765
ARCPY_MCP_BIND_HOST=0.0.0.0
ARCPY_MCP_BIND_PORT=8765
ARCPY_MCP_ARCPY_PYTHON=D:\Program Files\ArcGIS\Pro\bin\Python\envs\arcgispro-py3\python.exe
ARCPY_MCP_DATA_ROOT=%LOCALAPPDATA%\ArcPyMCP\data
ARCPY_MCP_TLS_CERT=%LOCALAPPDATA%\ArcPyMCP\certs\server.crt
ARCPY_MCP_TLS_KEY=%LOCALAPPDATA%\ArcPyMCP\certs\server.key
ARCPY_MCP_BEARER_TOKEN=
ARCPY_MCP_ARTIFACT_SIGNING_KEY=
ARCPY_MCP_RETENTION_DAYS=7
ARCPY_MCP_MAX_UPLOAD_BYTES=21474836480
ARCPY_MCP_MAX_EXPANDED_BYTES=53687091200
ARCPY_MCP_MAX_ZIP_ENTRIES=100000
ARCPY_MCP_MAX_ZIP_DEPTH=16
~~~

Create src/arcpy_mcp_server/__init__.py:

~~~python
__version__ = "0.1.0"
~~~

- [ ] **Step 5: Install dependencies and run the package test**

Run:

~~~powershell
uv sync --dev
uv run pytest tests\test_package.py -v
~~~

Expected: PASS.

- [ ] **Step 6: Commit and create the private GitHub repository**

Run:

~~~powershell
git add pyproject.toml .gitignore .env.example src tests
git commit -m "chore: scaffold ArcPy MCP server"
gh repo create zhouning/arcpy-mcp-server --private --source . --remote origin --push
~~~

Expected: private repository zhouning/arcpy-mcp-server exists and main is pushed.

### Task 2: Add Validated Configuration

**Files:**
- Create: src/arcpy_mcp_server/config.py
- Create: tests/test_config.py

- [ ] **Step 1: Write configuration tests**

~~~python
from pathlib import Path

import pytest
from pydantic import ValidationError

from arcpy_mcp_server.config import Settings


def test_settings_expand_environment_paths(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    settings = Settings(
        bearer_token="a" * 32,
        artifact_signing_key="b" * 32,
        arcpy_python=Path("D:/Program Files/ArcGIS/Pro/bin/Python/envs/arcgispro-py3/python.exe"),
    )

    assert settings.data_root == tmp_path / "ArcPyMCP" / "data"
    assert settings.database_path == settings.data_root / "state.db"


def test_short_bearer_token_is_rejected(tmp_path):
    with pytest.raises(ValidationError):
        Settings(
            bearer_token="short",
            artifact_signing_key="b" * 32,
            data_root=tmp_path,
            arcpy_python=tmp_path / "python.exe",
        )
~~~

- [ ] **Step 2: Run tests and verify failure**

Run: uv run pytest tests/test_config.py -v

Expected: FAIL because arcpy_mcp_server.config does not exist.

- [ ] **Step 3: Implement Settings**

~~~python
import os
from pathlib import Path

from pydantic import AnyHttpUrl, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _default_local_app_data() -> Path:
    value = os.environ.get("LOCALAPPDATA")
    if not value:
        raise RuntimeError("LOCALAPPDATA is required on Windows")
    return Path(value)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="ARCPY_MCP_",
        env_file=None,
        case_sensitive=False,
    )

    public_base_url: AnyHttpUrl = AnyHttpUrl("https://192.168.25.228:8765")
    bind_host: str = "0.0.0.0"
    bind_port: int = Field(default=8765, ge=1, le=65535)
    arcpy_python: Path = Path(
        r"D:\Program Files\ArcGIS\Pro\bin\Python\envs\arcgispro-py3\python.exe"
    )
    data_root: Path = Field(default_factory=lambda: _default_local_app_data() / "ArcPyMCP" / "data")
    tls_cert: Path = Field(
        default_factory=lambda: _default_local_app_data() / "ArcPyMCP" / "certs" / "server.crt"
    )
    tls_key: Path = Field(
        default_factory=lambda: _default_local_app_data() / "ArcPyMCP" / "certs" / "server.key"
    )
    bearer_token: SecretStr = Field(min_length=32)
    artifact_signing_key: SecretStr = Field(min_length=32)
    retention_days: int = Field(default=7, ge=1, le=365)
    max_upload_bytes: int = Field(default=20 * 1024**3, ge=1)
    max_expanded_bytes: int = Field(default=50 * 1024**3, ge=1)
    max_zip_entries: int = Field(default=100_000, ge=1)
    max_zip_depth: int = Field(default=16, ge=1, le=64)
    incomplete_upload_hours: int = Field(default=24, ge=1, le=168)

    @field_validator("data_root", "tls_cert", "tls_key", mode="before")
    @classmethod
    def expand_percent_variables(cls, value):
        if isinstance(value, str):
            return Path(os.path.expandvars(value))
        return value

    @property
    def database_path(self) -> Path:
        return self.data_root / "state.db"

    @property
    def worker_script(self) -> Path:
        return Path(__file__).parent / "worker" / "main.py"
~~~

- [ ] **Step 4: Run tests**

Run: uv run pytest tests/test_config.py -v

Expected: PASS.

- [ ] **Step 5: Commit**

Run:

~~~powershell
git add src/arcpy_mcp_server/config.py tests/test_config.py
git commit -m "feat: add validated server settings"
~~~

### Task 3: Implement Bearer Authentication and Signed URLs

**Files:**
- Create: src/arcpy_mcp_server/auth.py
- Create: tests/test_auth.py

- [ ] **Step 1: Write failing authentication tests**

~~~python
import time

import pytest

from arcpy_mcp_server.auth import ArtifactSigner, StaticBearerVerifier


@pytest.mark.asyncio
async def test_static_bearer_verifier_accepts_only_exact_token():
    verifier = StaticBearerVerifier("x" * 32, "https://192.168.25.228:8765")

    accepted = await verifier.verify_token("x" * 32)
    rejected = await verifier.verify_token("x" * 31 + "y")

    assert accepted is not None
    assert accepted.client_id == "codex-macos"
    assert rejected is None


def test_artifact_signature_binds_operation_and_expiry():
    signer = ArtifactSigner(b"k" * 32)
    expires = int(time.time()) + 60
    signature = signer.sign("upload", "artifact-1", expires)

    assert signer.verify("upload", "artifact-1", expires, signature)
    assert not signer.verify("download", "artifact-1", expires, signature)
    assert not signer.verify("upload", "artifact-1", int(time.time()) - 1, signature)
~~~

- [ ] **Step 2: Run tests and verify failure**

Run: uv run pytest tests/test_auth.py -v

Expected: FAIL because auth.py does not exist.

- [ ] **Step 3: Implement the verifier and signer**

~~~python
import hashlib
import hmac
import time

from fastmcp.server.auth import AccessToken, TokenVerifier


class StaticBearerVerifier(TokenVerifier):
    def __init__(self, expected_token: str, base_url: str):
        super().__init__(base_url=base_url)
        self._expected = expected_token.encode("utf-8")

    async def verify_token(self, token: str) -> AccessToken | None:
        if not hmac.compare_digest(token.encode("utf-8"), self._expected):
            return None
        return AccessToken(
            token=token,
            client_id="codex-macos",
            scopes=[],
            claims={"auth_method": "static_bearer"},
        )


class ArtifactSigner:
    def __init__(self, key: bytes):
        self._key = key

    def sign(self, operation: str, artifact_id: str, expires_at: int) -> str:
        payload = f"{operation}:{artifact_id}:{expires_at}".encode("utf-8")
        return hmac.new(self._key, payload, hashlib.sha256).hexdigest()

    def verify(
        self,
        operation: str,
        artifact_id: str,
        expires_at: int,
        signature: str,
    ) -> bool:
        if expires_at < int(time.time()):
            return False
        expected = self.sign(operation, artifact_id, expires_at)
        return hmac.compare_digest(expected, signature)
~~~

- [ ] **Step 4: Run tests**

Run: uv run pytest tests/test_auth.py -v

Expected: PASS.

- [ ] **Step 5: Commit**

Run:

~~~powershell
git add src/arcpy_mcp_server/auth.py tests/test_auth.py
git commit -m "feat: add MCP and artifact authentication"
~~~

### Task 4: Define Persistent Models and SQLite Schema

**Files:**
- Create: src/arcpy_mcp_server/models.py
- Create: src/arcpy_mcp_server/db.py
- Create: tests/test_db.py

- [ ] **Step 1: Write the failing database lifecycle test**

~~~python
from arcpy_mcp_server.db import Database
from arcpy_mcp_server.models import ArtifactRecord, ArtifactState, JobRecord, JobStatus


async def test_database_round_trips_artifacts_and_jobs(tmp_path):
    db = Database(tmp_path / "state.db")
    await db.start()
    artifact = ArtifactRecord(
        id="artifact-1",
        logical_name="roads.zip",
        state=ArtifactState.INCOMPLETE,
        expected_size=100,
        expected_sha256="a" * 64,
        committed_size=0,
        media_type="application/zip",
    )
    job = JobRecord(id="job-1", tool_id="vector.buffer", status=JobStatus.QUEUED, request={})

    await db.insert_artifact(artifact)
    await db.insert_job(job)

    assert (await db.get_artifact("artifact-1")).logical_name == "roads.zip"
    assert (await db.get_job("job-1")).status is JobStatus.QUEUED
    await db.stop()
~~~

- [ ] **Step 2: Run tests and verify failure**

Run: uv run pytest tests/test_db.py -v

Expected: FAIL because models.py and db.py do not exist.

- [ ] **Step 3: Create the typed records**

~~~python
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class ArtifactInputDefinition(BaseModel):
    artifact_id_field: str
    path_field: str
    multiple: bool = False
    container_field: str | None = None


class OutputDefinition(BaseModel):
    name_field: str
    kind: str


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ArtifactState(StrEnum):
    INCOMPLETE = "incomplete"
    READY = "ready"
    DELETED = "deleted"


class JobStatus(StrEnum):
    QUEUED = "queued"
    STARTING = "starting"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    CANCELLING = "cancelling"
    CANCELLED = "cancelled"
    INTERRUPTED = "interrupted"


class ArtifactRecord(BaseModel):
    id: str
    logical_name: str
    state: ArtifactState
    expected_size: int
    expected_sha256: str
    committed_size: int = 0
    actual_sha256: str | None = None
    media_type: str
    storage_path: str | None = None
    content_root: str | None = None
    created_at: datetime = Field(default_factory=utc_now)
    completed_at: datetime | None = None


class JobRecord(BaseModel):
    id: str
    tool_id: str
    status: JobStatus
    request: dict[str, Any]
    result: dict[str, Any] | None = None
    error_code: str | None = None
    error_message: str | None = None
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
~~~

- [ ] **Step 4: Implement the database**

~~~python
import json
from pathlib import Path

import aiosqlite

from .models import ArtifactRecord, JobRecord, JobStatus, utc_now


SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS artifacts (
    id TEXT PRIMARY KEY,
    payload TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    payload TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS job_events (
    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    payload TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS job_artifacts (
    job_id TEXT NOT NULL,
    artifact_id TEXT NOT NULL,
    role TEXT NOT NULL,
    PRIMARY KEY (job_id, artifact_id, role)
);
"""


class Database:
    def __init__(self, path: Path):
        self.path = path
        self.connection: aiosqlite.Connection | None = None

    async def start(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = await aiosqlite.connect(self.path)
        await self.connection.executescript(SCHEMA)
        await self.connection.commit()

    async def stop(self) -> None:
        if self.connection is not None:
            await self.connection.close()
            self.connection = None

    def _conn(self) -> aiosqlite.Connection:
        if self.connection is None:
            raise RuntimeError("database is not started")
        return self.connection

    async def insert_artifact(self, record: ArtifactRecord) -> None:
        await self._conn().execute(
            "INSERT INTO artifacts(id, payload) VALUES (?, ?)",
            (record.id, record.model_dump_json()),
        )
        await self._conn().commit()

    async def update_artifact(self, record: ArtifactRecord) -> None:
        await self._conn().execute(
            "UPDATE artifacts SET payload = ? WHERE id = ?",
            (record.model_dump_json(), record.id),
        )
        await self._conn().commit()

    async def get_artifact(self, artifact_id: str) -> ArtifactRecord | None:
        cursor = await self._conn().execute(
            "SELECT payload FROM artifacts WHERE id = ?",
            (artifact_id,),
        )
        row = await cursor.fetchone()
        return ArtifactRecord.model_validate_json(row[0]) if row else None

    async def list_artifacts(self) -> list[ArtifactRecord]:
        cursor = await self._conn().execute("SELECT payload FROM artifacts ORDER BY rowid DESC")
        return [ArtifactRecord.model_validate_json(row[0]) async for row in cursor]

    async def insert_job(self, record: JobRecord) -> None:
        await self._conn().execute(
            "INSERT INTO jobs(id, status, payload) VALUES (?, ?, ?)",
            (record.id, record.status.value, record.model_dump_json()),
        )
        await self._conn().commit()

    async def update_job(self, record: JobRecord) -> None:
        record.updated_at = utc_now()
        await self._conn().execute(
            "UPDATE jobs SET status = ?, payload = ? WHERE id = ?",
            (record.status.value, record.model_dump_json(), record.id),
        )
        await self._conn().commit()

    async def get_job(self, job_id: str) -> JobRecord | None:
        cursor = await self._conn().execute("SELECT payload FROM jobs WHERE id = ?", (job_id,))
        row = await cursor.fetchone()
        return JobRecord.model_validate_json(row[0]) if row else None

    async def list_jobs(self, limit: int = 100) -> list[JobRecord]:
        cursor = await self._conn().execute(
            "SELECT payload FROM jobs ORDER BY rowid DESC LIMIT ?",
            (limit,),
        )
        return [JobRecord.model_validate_json(row[0]) async for row in cursor]

    async def list_jobs_by_status(self, statuses: set[JobStatus]) -> list[JobRecord]:
        placeholders = ",".join("?" for _ in statuses)
        cursor = await self._conn().execute(
            f"SELECT payload FROM jobs WHERE status IN ({placeholders})",
            tuple(status.value for status in statuses),
        )
        return [JobRecord.model_validate_json(row[0]) async for row in cursor]

    async def append_event(self, job_id: str, event_type: str, payload: dict) -> None:
        await self._conn().execute(
            "INSERT INTO job_events(job_id, event_type, payload, created_at) VALUES (?, ?, ?, ?)",
            (job_id, event_type, json.dumps(payload), utc_now().isoformat()),
        )
        await self._conn().commit()

    async def list_events(self, job_id: str) -> list[dict]:
        cursor = await self._conn().execute(
            "SELECT event_type, payload, created_at FROM job_events "
            "WHERE job_id = ? ORDER BY sequence",
            (job_id,),
        )
        return [
            {
                "event_type": row[0],
                "payload": json.loads(row[1]),
                "created_at": row[2],
            }
            async for row in cursor
        ]

    async def link_artifact(self, job_id: str, artifact_id: str, role: str) -> None:
        await self._conn().execute(
            "INSERT OR IGNORE INTO job_artifacts(job_id, artifact_id, role) VALUES (?, ?, ?)",
            (job_id, artifact_id, role),
        )
        await self._conn().commit()

    async def artifact_has_active_job(self, artifact_id: str) -> bool:
        active = (
            JobStatus.QUEUED.value,
            JobStatus.STARTING.value,
            JobStatus.RUNNING.value,
            JobStatus.CANCELLING.value,
        )
        cursor = await self._conn().execute(
            "SELECT 1 FROM job_artifacts ja JOIN jobs j ON j.id = ja.job_id "
            "WHERE ja.artifact_id = ? AND j.status IN (?, ?, ?, ?) LIMIT 1",
            (artifact_id, *active),
        )
        return await cursor.fetchone() is not None
~~~

- [ ] **Step 5: Run tests**

Run: uv run pytest tests/test_db.py -v

Expected: PASS.

- [ ] **Step 6: Commit**

Run:

~~~powershell
git add src/arcpy_mcp_server/models.py src/arcpy_mcp_server/db.py tests/test_db.py
git commit -m "feat: add persistent artifact and job state"
~~~

### Task 5: Enforce Workspace Containment and Safe ZIP Extraction

**Files:**
- Create: src/arcpy_mcp_server/workspace.py
- Create: tests/test_workspace.py

- [ ] **Step 1: Write traversal and extraction tests**

~~~python
import io
import zipfile

import pytest

from arcpy_mcp_server.workspace import UnsafeArchiveError, Workspace


def test_resolve_rejects_absolute_and_parent_paths(tmp_path):
    workspace = Workspace(tmp_path, 1024, 10, 4)

    with pytest.raises(ValueError):
        workspace.resolve_relative(tmp_path, "../outside.txt")
    with pytest.raises(ValueError):
        workspace.resolve_relative(tmp_path, "C:/Windows/system.ini")


def test_extract_zip_rejects_zip_slip(tmp_path):
    archive = tmp_path / "bad.zip"
    with zipfile.ZipFile(archive, "w") as output:
        output.writestr("../escape.txt", "blocked")

    workspace = Workspace(tmp_path, 1024, 10, 4)
    with pytest.raises(UnsafeArchiveError):
        workspace.extract_zip(archive, tmp_path / "out")
~~~

- [ ] **Step 2: Run tests and verify failure**

Run: uv run pytest tests/test_workspace.py -v

Expected: FAIL because workspace.py does not exist.

- [ ] **Step 3: Implement containment and extraction**

~~~python
import os
import shutil
import stat
import zipfile
from pathlib import Path, PurePosixPath


class UnsafeArchiveError(ValueError):
    pass


class Workspace:
    def __init__(
        self,
        root: Path,
        max_expanded_bytes: int,
        max_zip_entries: int,
        max_zip_depth: int,
    ):
        self.root = root.resolve()
        self.max_expanded_bytes = max_expanded_bytes
        self.max_zip_entries = max_zip_entries
        self.max_zip_depth = max_zip_depth
        self.root.mkdir(parents=True, exist_ok=True)

    def job_root(self, job_id: str) -> Path:
        path = self.root / "jobs" / job_id
        for name in ("input", "work", "output", "logs"):
            (path / name).mkdir(parents=True, exist_ok=True)
        return path

    def resolve_relative(self, base: Path, relative: str) -> Path:
        if not relative or os.path.isabs(relative) or ":" in relative or relative.startswith("\\\\"):
            raise ValueError("absolute, drive-prefixed, and UNC paths are rejected")
        candidate = (base / relative).resolve(strict=False)
        if os.path.commonpath([base.resolve(), candidate]) != str(base.resolve()):
            raise ValueError("path leaves the workspace")
        return candidate

    def extract_zip(self, archive: Path, destination: Path) -> None:
        destination.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(archive) as source:
            entries = source.infolist()
            if len(entries) > self.max_zip_entries:
                raise UnsafeArchiveError("archive contains too many entries")
            expanded = 0
            for entry in entries:
                normalized = PurePosixPath(entry.filename)
                if normalized.is_absolute() or ".." in normalized.parts:
                    raise UnsafeArchiveError("archive path traversal detected")
                if len(normalized.parts) > self.max_zip_depth:
                    raise UnsafeArchiveError("archive nesting limit exceeded")
                mode = entry.external_attr >> 16
                if stat.S_ISLNK(mode):
                    raise UnsafeArchiveError("archive symlinks are rejected")
                expanded += entry.file_size
                if expanded > self.max_expanded_bytes:
                    raise UnsafeArchiveError("expanded archive size limit exceeded")
                target = self.resolve_relative(destination, normalized.as_posix())
                if entry.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                with source.open(entry) as input_stream, target.open("wb") as output_stream:
                    shutil.copyfileobj(input_stream, output_stream, length=1024 * 1024)
~~~

- [ ] **Step 4: Run tests**

Run: uv run pytest tests/test_workspace.py -v

Expected: PASS.

- [ ] **Step 5: Commit**

Run:

~~~powershell
git add src/arcpy_mcp_server/workspace.py tests/test_workspace.py
git commit -m "feat: isolate workspaces and archives"
~~~

### Task 6: Implement Resumable Artifact Upload and Range Download

**Files:**
- Create: src/arcpy_mcp_server/artifacts.py
- Create: tests/test_artifacts.py

- [ ] **Step 1: Write failing artifact service tests**

~~~python
import hashlib

from arcpy_mcp_server.artifacts import ArtifactService
from arcpy_mcp_server.auth import ArtifactSigner
from arcpy_mcp_server.db import Database
from arcpy_mcp_server.workspace import Workspace


async def test_upload_resumes_and_completes(tmp_path):
    payload = b"abcdef"
    db = Database(tmp_path / "state.db")
    await db.start()
    workspace = Workspace(tmp_path / "workspace", 1024, 10, 4)
    service = ArtifactService(
        db,
        tmp_path / "artifacts",
        workspace,
        ArtifactSigner(b"k" * 32),
        1024,
    )

    created = await service.create_upload(
        "data.bin",
        len(payload),
        hashlib.sha256(payload).hexdigest(),
        "application/octet-stream",
    )
    await service.append_upload(created.id, 0, payload[:3])
    status = await service.get_upload_status(created.id)
    await service.append_upload(created.id, status.committed_size, payload[3:])
    completed = await service.complete_upload(created.id)

    assert completed.state.value == "ready"
    assert completed.actual_sha256 == hashlib.sha256(payload).hexdigest()
    await db.stop()
~~~

- [ ] **Step 2: Run tests and verify failure**

Run: uv run pytest tests/test_artifacts.py -v

Expected: FAIL because artifacts.py does not exist.

- [ ] **Step 3: Implement the artifact service**

~~~python
import hashlib
import time
import uuid
from datetime import timedelta
from pathlib import Path

from .auth import ArtifactSigner
from .db import Database
from .models import ArtifactRecord, ArtifactState, utc_now
from .workspace import Workspace


class ArtifactService:
    def __init__(
        self,
        db: Database,
        root: Path,
        workspace: Workspace,
        signer: ArtifactSigner,
        max_upload_bytes: int,
    ):
        self.db = db
        self.root = root
        self.workspace = workspace
        self.signer = signer
        self.max_upload_bytes = max_upload_bytes
        self.root.mkdir(parents=True, exist_ok=True)

    async def create_upload(
        self,
        logical_name: str,
        expected_size: int,
        expected_sha256: str,
        media_type: str,
    ) -> ArtifactRecord:
        if expected_size < 0 or expected_size > self.max_upload_bytes:
            raise ValueError("upload size exceeds configured limit")
        if len(expected_sha256) != 64:
            raise ValueError("expected_sha256 must be a SHA-256 hex digest")
        artifact_id = str(uuid.uuid4())
        record = ArtifactRecord(
            id=artifact_id,
            logical_name=logical_name,
            state=ArtifactState.INCOMPLETE,
            expected_size=expected_size,
            expected_sha256=expected_sha256.lower(),
            media_type=media_type,
            storage_path=str(self.root / f"{artifact_id}.part"),
        )
        await self.db.insert_artifact(record)
        return record

    async def get_upload_status(self, artifact_id: str) -> ArtifactRecord:
        record = await self.db.get_artifact(artifact_id)
        if record is None:
            raise KeyError(artifact_id)
        return record

    async def append_upload(self, artifact_id: str, offset: int, chunk: bytes) -> ArtifactRecord:
        record = await self.get_upload_status(artifact_id)
        if record.state is not ArtifactState.INCOMPLETE:
            raise ValueError("artifact is not uploadable")
        if offset != record.committed_size:
            raise ValueError(f"offset mismatch; expected {record.committed_size}")
        if record.committed_size + len(chunk) > record.expected_size:
            raise ValueError("chunk exceeds declared upload size")
        path = Path(record.storage_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("ab") as output:
            output.write(chunk)
        record.committed_size += len(chunk)
        await self.db.update_artifact(record)
        return record

    async def complete_upload(self, artifact_id: str) -> ArtifactRecord:
        record = await self.get_upload_status(artifact_id)
        if record.committed_size != record.expected_size:
            raise ValueError("upload is incomplete")
        digest = hashlib.sha256()
        with Path(record.storage_path).open("rb") as input_stream:
            for block in iter(lambda: input_stream.read(1024 * 1024), b""):
                digest.update(block)
        actual = digest.hexdigest()
        if actual != record.expected_sha256:
            raise ValueError("artifact hash mismatch")
        final_path = self.root / artifact_id / record.logical_name
        final_path.parent.mkdir(parents=True, exist_ok=True)
        Path(record.storage_path).replace(final_path)
        record.storage_path = str(final_path)
        if final_path.suffix.casefold() == ".zip":
            content_root = self.root / artifact_id / "content"
            self.workspace.extract_zip(final_path, content_root)
            record.content_root = str(content_root)
        else:
            record.content_root = str(final_path.parent)
        record.actual_sha256 = actual
        record.state = ArtifactState.READY
        record.completed_at = utc_now()
        await self.db.update_artifact(record)
        return record

    async def resolve_ready_path(self, artifact_id: str, relative_path: str) -> Path:
        record = await self.get_upload_status(artifact_id)
        if record.state is not ArtifactState.READY or record.content_root is None:
            raise ValueError("artifact is not ready")
        base = Path(record.content_root)
        resolved = self.workspace.resolve_relative(base, relative_path)
        if not resolved.exists():
            raise ValueError("artifact-relative path does not exist")
        return resolved

    async def list_artifacts(self) -> list[ArtifactRecord]:
        return [
            record
            for record in await self.db.list_artifacts()
            if record.state is not ArtifactState.DELETED
        ]

    async def delete_artifact(self, artifact_id: str) -> ArtifactRecord:
        record = await self.get_upload_status(artifact_id)
        import shutil

        artifact_root = self.root / artifact_id
        if artifact_root.exists():
            shutil.rmtree(artifact_root)
        if record.storage_path:
            stored = Path(record.storage_path)
            if stored.exists() and stored.is_file():
                stored.unlink()
        record.state = ArtifactState.DELETED
        await self.db.update_artifact(record)
        return record

    async def register_output(
        self,
        output_path: Path,
        logical_name: str,
        media_type: str,
    ) -> ArtifactRecord:
        if output_path.suffix.casefold() == ".shp":
            import shutil
            import tempfile

            with tempfile.TemporaryDirectory(dir=self.root) as staging_name:
                staging = Path(staging_name)
                for component in output_path.parent.glob(f"{output_path.stem}.*"):
                    shutil.copy2(component, staging / component.name)
                archive_base = self.root / str(uuid.uuid4()) / output_path.stem
                archive_base.parent.mkdir(parents=True, exist_ok=True)
                output_path = Path(shutil.make_archive(str(archive_base), "zip", staging))
                logical_name = f"{output_path.stem}.zip"
                media_type = "application/zip"
        if output_path.is_dir():
            import shutil

            archive_base = self.root / str(uuid.uuid4()) / logical_name
            archive_base.parent.mkdir(parents=True, exist_ok=True)
            output_path = Path(shutil.make_archive(str(archive_base), "zip", output_path))
            logical_name = f"{logical_name}.zip"
            media_type = "application/zip"
        digest = hashlib.sha256()
        size = 0
        with output_path.open("rb") as input_stream:
            for block in iter(lambda: input_stream.read(1024 * 1024), b""):
                size += len(block)
                digest.update(block)
        artifact_id = str(uuid.uuid4())
        destination = self.root / artifact_id / logical_name
        destination.parent.mkdir(parents=True, exist_ok=True)
        output_path.replace(destination)
        record = ArtifactRecord(
            id=artifact_id,
            logical_name=logical_name,
            state=ArtifactState.READY,
            expected_size=size,
            expected_sha256=digest.hexdigest(),
            committed_size=size,
            actual_sha256=digest.hexdigest(),
            media_type=media_type,
            storage_path=str(destination),
            content_root=str(destination.parent),
            completed_at=utc_now(),
        )
        await self.db.insert_artifact(record)
        return record

    async def cleanup_expired(
        self,
        retention_days: int,
        incomplete_upload_hours: int,
    ) -> list[str]:
        cutoff = utc_now() - timedelta(days=retention_days)
        incomplete_cutoff = utc_now() - timedelta(hours=incomplete_upload_hours)
        deleted = []
        for record in await self.list_artifacts():
            if record.state is ArtifactState.INCOMPLETE:
                if record.created_at < incomplete_cutoff:
                    await self.delete_artifact(record.id)
                    deleted.append(record.id)
                continue
            reference_time = record.completed_at or record.created_at
            if reference_time >= cutoff:
                continue
            if await self.db.artifact_has_active_job(record.id):
                continue
            await self.delete_artifact(record.id)
            deleted.append(record.id)
        return deleted

    def signed_url(self, base_url: str, artifact_id: str, operation: str, ttl: int) -> str:
        expires = int(time.time()) + ttl
        signature = self.signer.sign(operation, artifact_id, expires)
        base_url = base_url.rstrip("/")
        return (
            f"{base_url}/artifacts/{artifact_id}/content"
            f"?op={operation}&expires={expires}&signature={signature}"
        )
~~~

- [ ] **Step 4: Add Starlette upload and range-download route tests**

Create tests/test_artifact_http.py with a TestClient fixture that:

1. creates an upload record;
2. sends PUT with Upload-Offset 0 and body abc;
3. sends PUT with Upload-Offset 3 and body def;
4. completes the artifact through the service;
5. sends GET with Range bytes=2-4;
6. asserts status 206, Content-Range bytes 2-4/6, and body cde;
7. sends a tampered signature and asserts status 403.

Implement Starlette endpoints in artifacts.py as functions upload_content(request) and download_content(request). Read request.stream() incrementally, require Upload-Offset, call append_upload per chunk, and use StreamingResponse for full or ranged downloads. Never call request.body() for uploads.

- [ ] **Step 5: Run artifact tests**

Run:

~~~powershell
uv run pytest tests/test_artifacts.py tests/test_artifact_http.py -v
~~~

Expected: PASS.

- [ ] **Step 6: Commit**

Run:

~~~powershell
git add src/arcpy_mcp_server/artifacts.py tests/test_artifacts.py tests/test_artifact_http.py
git commit -m "feat: add resumable artifact transfer"
~~~

### Task 7: Implement the Persistent Job State Machine

**Files:**
- Create: src/arcpy_mcp_server/jobs.py
- Create: tests/test_jobs.py

- [ ] **Step 1: Write state transition tests**

~~~python
import pytest

from arcpy_mcp_server.db import Database
from arcpy_mcp_server.jobs import InvalidTransition, JobService
from arcpy_mcp_server.models import JobStatus


async def test_job_transitions_and_restart_reconciliation(tmp_path):
    db = Database(tmp_path / "state.db")
    await db.start()
    service = JobService(db)
    job = await service.submit("vector.buffer", {"distance": "10 Meters"})

    await service.transition(job.id, JobStatus.STARTING)
    await service.transition(job.id, JobStatus.RUNNING)
    await service.reconcile_after_restart()

    assert (await service.get(job.id)).status is JobStatus.INTERRUPTED
    with pytest.raises(InvalidTransition):
        await service.transition(job.id, JobStatus.SUCCEEDED)
    await db.stop()
~~~

- [ ] **Step 2: Run tests and verify failure**

Run: uv run pytest tests/test_jobs.py -v

Expected: FAIL because jobs.py does not exist.

- [ ] **Step 3: Implement the state machine**

~~~python
import uuid

from .db import Database
from .models import JobRecord, JobStatus


class InvalidTransition(ValueError):
    pass


ALLOWED_TRANSITIONS = {
    JobStatus.QUEUED: {JobStatus.STARTING, JobStatus.CANCELLED},
    JobStatus.STARTING: {JobStatus.RUNNING, JobStatus.FAILED, JobStatus.CANCELLED},
    JobStatus.RUNNING: {
        JobStatus.SUCCEEDED,
        JobStatus.FAILED,
        JobStatus.TIMED_OUT,
        JobStatus.CANCELLING,
        JobStatus.INTERRUPTED,
    },
    JobStatus.CANCELLING: {JobStatus.CANCELLED, JobStatus.FAILED},
}


class JobService:
    def __init__(self, db: Database):
        self.db = db

    async def submit(self, tool_id: str, request: dict) -> JobRecord:
        record = JobRecord(
            id=str(uuid.uuid4()),
            tool_id=tool_id,
            status=JobStatus.QUEUED,
            request=request,
        )
        await self.db.insert_job(record)
        await self.db.append_event(record.id, "submitted", {"tool_id": tool_id})
        return record

    async def get(self, job_id: str) -> JobRecord:
        record = await self.db.get_job(job_id)
        if record is None:
            raise KeyError(job_id)
        return record

    async def transition(
        self,
        job_id: str,
        status: JobStatus,
        *,
        result: dict | None = None,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> JobRecord:
        record = await self.get(job_id)
        if status not in ALLOWED_TRANSITIONS.get(record.status, set()):
            raise InvalidTransition(f"{record.status.value} -> {status.value}")
        record.status = status
        record.result = result
        record.error_code = error_code
        record.error_message = error_message
        await self.db.update_job(record)
        await self.db.append_event(job_id, "status", {"status": status.value})
        return record

    async def reconcile_after_restart(self) -> None:
        stale = await self.db.list_jobs_by_status(
            {JobStatus.STARTING, JobStatus.RUNNING, JobStatus.CANCELLING}
        )
        for record in stale:
            record.status = JobStatus.INTERRUPTED
            record.error_code = "WORKER_UNAVAILABLE"
            record.error_message = "service restarted while the job was active"
            await self.db.update_job(record)
            await self.db.append_event(record.id, "interrupted", {})
~~~

- [ ] **Step 4: Run tests**

Run: uv run pytest tests/test_jobs.py -v

Expected: PASS.

- [ ] **Step 5: Commit**

Run:

~~~powershell
git add src/arcpy_mcp_server/jobs.py tests/test_jobs.py
git commit -m "feat: add persistent ArcPy jobs"
~~~

### Task 8: Load and Validate the ArcPy Tool Catalog

**Files:**
- Create: src/arcpy_mcp_server/catalog.py
- Create: config/tool_catalog.yaml
- Create: tests/test_catalog.py

- [ ] **Step 1: Write catalog tests**

~~~python
from pathlib import Path

import pytest

from arcpy_mcp_server.catalog import ToolCatalog


def test_catalog_search_and_parameter_validation():
    catalog = ToolCatalog.load(Path("config/tool_catalog.yaml"))

    matches = catalog.search("buffer")
    validated = catalog.validate_request(
        "vector.buffer",
        {
            "input_artifact_id": "artifact-1",
            "input_path": "roads.shp",
            "output_name": "roads_buffer.shp",
            "distance": "50 Meters",
        },
    )

    assert matches[0].id == "vector.buffer"
    assert validated["distance"] == "50 Meters"


def test_catalog_rejects_unknown_parameters():
    catalog = ToolCatalog.load(Path("config/tool_catalog.yaml"))
    with pytest.raises(ValueError):
        catalog.validate_request("vector.buffer", {"python_code": "import os"})
~~~

- [ ] **Step 2: Run tests and verify failure**

Run: uv run pytest tests/test_catalog.py -v

Expected: FAIL because catalog.py and tool_catalog.yaml do not exist.

- [ ] **Step 3: Implement catalog loading**

~~~python
from pathlib import Path

import jsonschema
import yaml
from pydantic import BaseModel, Field


class ToolDefinition(BaseModel):
    id: str
    title: str
    category: str
    description: str
    timeout_seconds: int
    required_extensions: list[str] = Field(default_factory=list)
    inputs: list[ArtifactInputDefinition] = Field(default_factory=list)
    output: OutputDefinition | None = None
    parameters: dict


class ToolCatalog:
    def __init__(self, tools: dict[str, ToolDefinition]):
        self.tools = tools

    @classmethod
    def load(cls, path: Path) -> "ToolCatalog":
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
        definitions = [ToolDefinition.model_validate(item) for item in payload["tools"]]
        tools = {item.id: item for item in definitions}
        if len(tools) != len(definitions):
            raise ValueError("tool IDs must be unique")
        return cls(tools)

    def search(self, query: str, category: str | None = None) -> list[ToolDefinition]:
        needle = query.casefold()
        results = []
        for tool in self.tools.values():
            if category and tool.category != category:
                continue
            haystack = f"{tool.id} {tool.title} {tool.description}".casefold()
            if needle in haystack:
                results.append(tool)
        return sorted(results, key=lambda item: item.id)

    def describe(self, tool_id: str) -> ToolDefinition:
        try:
            return self.tools[tool_id]
        except KeyError as error:
            raise ValueError("tool is not allowlisted") from error

    def validate_request(self, tool_id: str, parameters: dict) -> dict:
        definition = self.describe(tool_id)
        try:
            jsonschema.validate(parameters, definition.parameters)
        except jsonschema.ValidationError as error:
            raise ValueError(error.message) from error
        return parameters
~~~

- [ ] **Step 4: Create the initial catalog**

Create entries for each confirmed tool ID with additionalProperties false and explicit required properties. Start with these IDs:

~~~yaml
tools:
  - id: inspect.dataset
    title: Inspect dataset
    category: inspection
    description: Return ArcPy Describe metadata, fields, count, extent, and spatial reference.
    timeout_seconds: 120
    inputs:
      - artifact_id_field: input_artifact_id
        path_field: input_path
    parameters:
      type: object
      additionalProperties: false
      required: [input_artifact_id, input_path]
      properties:
        input_artifact_id: {type: string, minLength: 1}
        input_path: {type: string, minLength: 1}

  - id: vector.buffer
    title: Buffer
    category: vector
    description: Create polygon buffers around input features.
    timeout_seconds: 600
    inputs:
      - artifact_id_field: input_artifact_id
        path_field: input_path
    output:
      name_field: output_name
      kind: dataset
    parameters:
      type: object
      additionalProperties: false
      required: [input_artifact_id, input_path, output_name, distance]
      properties:
        input_artifact_id: {type: string, minLength: 1}
        input_path: {type: string, minLength: 1}
        output_name: {type: string, pattern: "^[A-Za-z0-9_.-]+$"}
        distance: {type: string, minLength: 1, maxLength: 100}
        dissolve_option: {type: string, enum: [NONE, ALL, LIST], default: NONE}

  - id: raster.slope
    title: Slope
    category: raster
    description: Derive slope from an elevation raster.
    timeout_seconds: 1800
    required_extensions: [Spatial]
    inputs:
      - artifact_id_field: input_artifact_id
        path_field: input_path
    output:
      name_field: output_name
      kind: raster
    parameters:
      type: object
      additionalProperties: false
      required: [input_artifact_id, input_path, output_name]
      properties:
        input_artifact_id: {type: string, minLength: 1}
        input_path: {type: string, minLength: 1}
        output_name: {type: string, pattern: "^[A-Za-z0-9_.-]+$"}
        output_measurement: {type: string, enum: [DEGREE, PERCENT_RISE], default: DEGREE}

  - id: dl.detect_objects
    title: Detect objects using deep learning
    category: deep-learning
    description: Run ArcGIS Image Analyst object detection in CPU mode.
    timeout_seconds: 21600
    required_extensions: [ImageAnalyst]
    inputs:
      - artifact_id_field: input_artifact_id
        path_field: input_path
      - artifact_id_field: model_artifact_id
        path_field: model_path
    output:
      name_field: output_name
      kind: dataset
    parameters:
      type: object
      additionalProperties: false
      required:
        [input_artifact_id, input_path, model_artifact_id, model_path, output_name]
      properties:
        input_artifact_id: {type: string, minLength: 1}
        input_path: {type: string, minLength: 1}
        model_artifact_id: {type: string, minLength: 1}
        model_path: {type: string, minLength: 1}
        output_name: {type: string, pattern: "^[A-Za-z0-9_.-]+$"}
        arguments: {type: string, default: ""}
        run_nms: {type: string, enum: [NO_NMS, NMS], default: NMS}
        confidence_score_field: {type: string, default: Confidence}
        class_value_field: {type: string, default: Class}
        max_overlap_ratio: {type: number, minimum: 0, maximum: 1, default: 0}
~~~

Append exactly these catalog entries. Every schema uses type object and additionalProperties false.

| Tool ID | Required properties | Optional constrained properties |
|---|---|---|
| vector.clip | input_artifact_id, input_path, clip_artifact_id, clip_path, output_name | none |
| vector.dissolve | input_artifact_id, input_path, output_name | dissolve_fields as an array of strings |
| vector.intersect | inputs as an array of artifact_id/path objects, output_name | join_attributes enum ALL, NO_FID, ONLY_FID |
| vector.union | inputs as an array of artifact_id/path objects, output_name | gaps enum GAPS, NO_GAPS |
| vector.spatial_join | target_artifact_id, target_path, join_artifact_id, join_path, output_name | join_operation enum JOIN_ONE_TO_ONE, JOIN_ONE_TO_MANY; match_option as a non-empty string |
| vector.project | input_artifact_id, input_path, output_name, output_spatial_reference | geographic_transform as a string |
| vector.merge | inputs as an array of artifact_id/path objects, output_name | none |
| vector.check_geometry | input_artifact_id, input_path, output_name | validation_method enum ESRI, OGC |
| vector.repair_geometry | input_artifact_id, input_path, output_name | delete_null enum DELETE_NULL, KEEP_NULL; validation_method enum ESRI, OGC |
| raster.clip | input_artifact_id, input_path, template_artifact_id, template_path, output_name | clipping_geometry as boolean |
| raster.project | input_artifact_id, input_path, output_name, output_spatial_reference | resampling_type enum NEAREST, BILINEAR, CUBIC, MAJORITY; cell_size as number greater than zero |
| raster.resample | input_artifact_id, input_path, output_name, cell_size | resampling_type enum NEAREST, BILINEAR, CUBIC, MAJORITY |
| raster.extract_by_mask | input_artifact_id, input_path, mask_artifact_id, mask_path, output_name | none |
| raster.slope | input_artifact_id, input_path, output_name | output_measurement enum DEGREE, PERCENT_RISE; z_factor as number greater than zero |
| raster.zonal_statistics | zone_artifact_id, zone_path, zone_field, value_artifact_id, value_path, output_name | statistics_type enum ALL, MEAN, MAXIMUM, MINIMUM, MEDIAN, STD, SUM, VARIETY |
| raster.mosaic | inputs as an array of artifact_id/path objects, output_name, coordinate_system | pixel_type and number_of_bands |
| map.inspect_aprx | input_artifact_id, aprx_path | none |
| map.export_layout | input_artifact_id, aprx_path, layout_name, output_name, format | format enum PDF, PNG; dpi integer from 72 through 1200 |
| dl.detect_objects | input_artifact_id, input_path, model_artifact_id, model_path, output_name | arguments, run_nms, confidence_score_field, class_value_field, max_overlap_ratio |
| dl.classify_pixels | input_artifact_id, input_path, model_artifact_id, model_path, output_name | arguments |
| dl.classify_objects | input_artifact_id, input_path, model_artifact_id, model_path, output_name | arguments |
| dl.detect_change | from_artifact_id, from_path, to_artifact_id, to_path, model_artifact_id, model_path, output_name | arguments |
| dl.translate_pixels | input_artifact_id, input_path, model_artifact_id, model_path, output_name | arguments |
| dl.export_training_data | input_artifact_id, input_path, output_name, tile_size_x, tile_size_y, stride_x, stride_y, metadata_format | image_format enum TIFF, PNG, JPEG; metadata_format as a non-empty string |

For every output_name property use pattern ^[A-Za-z0-9_.-]+$. For every artifact ID and relative path use a non-empty string. For every inputs array require at least one element and reject extra object properties. Do not add a callable or Python module property to any entry.

For each table row, add inputs entries for every artifact-ID/path pair named in Required properties. For tools with inputs arrays, set one input definition with container_field inputs, artifact_id_field artifact_id, path_field path, and multiple true. Add output for every tool with output_name; use kind dataset for vector and deep-learning feature outputs, raster for raster outputs, table for zonal statistics, archive for exported training data, and file for PDF/PNG map exports. inspect.dataset and map.inspect_aprx have output null.

- [ ] **Step 5: Run tests and catalog lint**

Run:

~~~powershell
uv run pytest tests/test_catalog.py -v
uv run python -c "from pathlib import Path; from arcpy_mcp_server.catalog import ToolCatalog; print(len(ToolCatalog.load(Path('config/tool_catalog.yaml')).tools))"
~~~

Expected: tests PASS and the printed catalog count equals the number of committed entries.

- [ ] **Step 6: Commit**

Run:

~~~powershell
git add src/arcpy_mcp_server/catalog.py config/tool_catalog.yaml tests/test_catalog.py
git commit -m "feat: add allowlisted ArcPy catalog"
~~~

### Task 9: Implement the JSON Lines Worker Protocol and Supervisor

**Files:**
- Create: src/arcpy_mcp_server/worker_protocol.py
- Create: src/arcpy_mcp_server/worker_supervisor.py
- Create: tests/fixtures/fake_worker.py
- Create: tests/test_worker_supervisor.py

- [ ] **Step 1: Write the worker restart test**

~~~python
import sys
from pathlib import Path

import pytest

from arcpy_mcp_server.worker_supervisor import WorkerSupervisor


async def test_supervisor_executes_and_restarts_after_timeout():
    supervisor = WorkerSupervisor(
        executable=Path(sys.executable),
        script=Path("tests/fixtures/fake_worker.py"),
    )
    await supervisor.start()
    result = await supervisor.execute("job-1", "echo", {"value": 7}, timeout=2)
    assert result["value"] == 7

    first_pid = supervisor.pid
    with pytest.raises(TimeoutError):
        await supervisor.execute("job-2", "hang", {}, timeout=0.1)
    assert supervisor.pid != first_pid
    await supervisor.stop()
~~~

- [ ] **Step 2: Run tests and verify failure**

Run: uv run pytest tests/test_worker_supervisor.py -v

Expected: FAIL because the supervisor does not exist.

- [ ] **Step 3: Define protocol messages**

~~~python
import json
from typing import Any, Literal

from pydantic import BaseModel


class WorkerRequest(BaseModel):
    type: Literal["execute"] = "execute"
    job_id: str
    tool_id: str
    parameters: dict[str, Any]

    def to_line(self) -> bytes:
        return (self.model_dump_json() + "\n").encode("utf-8")


class WorkerMessage(BaseModel):
    type: Literal["ready", "event", "result", "error"]
    job_id: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)

    @classmethod
    def from_line(cls, line: bytes) -> "WorkerMessage":
        return cls.model_validate(json.loads(line.decode("utf-8")))
~~~

- [ ] **Step 4: Implement the supervisor**

~~~python
import asyncio
import inspect
import time
from collections.abc import Callable
from pathlib import Path

from .worker_protocol import WorkerMessage, WorkerRequest


class WorkerCrashed(RuntimeError):
    pass


class WorkerSupervisor:
    def __init__(
        self,
        executable: Path,
        script: Path,
        event_callback: Callable[[WorkerMessage], object] | None = None,
    ):
        self.executable = executable
        self.script = script
        self.event_callback = event_callback
        self.process: asyncio.subprocess.Process | None = None
        self._execute_lock = asyncio.Lock()

    @property
    def pid(self) -> int | None:
        return self.process.pid if self.process else None

    async def start(self) -> None:
        if self.process and self.process.returncode is None:
            return
        self.process = await asyncio.create_subprocess_exec(
            str(self.executable),
            "-u",
            str(self.script),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        message = await asyncio.wait_for(self._read_message(), timeout=120)
        if message.type != "ready":
            await self.stop()
            raise WorkerCrashed("worker did not send a ready message")

    async def stop(self) -> None:
        process = self.process
        self.process = None
        if process is None or process.returncode is not None:
            return
        process.terminate()
        try:
            await asyncio.wait_for(process.wait(), timeout=5)
        except TimeoutError:
            process.kill()
            await process.wait()

    async def restart(self) -> None:
        await self.stop()
        await self.start()

    async def _read_message(self) -> WorkerMessage:
        if self.process is None or self.process.stdout is None:
            raise WorkerCrashed("worker is not running")
        line = await self.process.stdout.readline()
        if not line:
            raise WorkerCrashed("worker closed stdout")
        return WorkerMessage.from_line(line)

    async def _emit_event(self, message: WorkerMessage) -> None:
        if self.event_callback is None:
            return
        result = self.event_callback(message)
        if inspect.isawaitable(result):
            await result

    async def execute(
        self,
        job_id: str,
        tool_id: str,
        parameters: dict,
        timeout: float,
    ) -> dict:
        async with self._execute_lock:
            await self.start()
            assert self.process is not None and self.process.stdin is not None
            request = WorkerRequest(job_id=job_id, tool_id=tool_id, parameters=parameters)
            self.process.stdin.write(request.to_line())
            await self.process.stdin.drain()
            deadline = time.monotonic() + timeout
            try:
                while True:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise TimeoutError
                    message = await asyncio.wait_for(self._read_message(), timeout=remaining)
                    if message.job_id not in (None, job_id):
                        raise WorkerCrashed("worker returned a mismatched job ID")
                    if message.type == "event":
                        await self._emit_event(message)
                    elif message.type == "result":
                        return message.payload
                    elif message.type == "error":
                        raise WorkerCrashed(message.payload.get("message", "worker error"))
            except TimeoutError:
                await self.restart()
                raise
            except Exception:
                await self.restart()
                raise
~~~

- [ ] **Step 5: Create the deterministic fake worker**

~~~python
import json
import sys
import time


def emit(message):
    sys.stdout.write(json.dumps(message) + "\n")
    sys.stdout.flush()


emit({"type": "ready", "payload": {"worker": "fake"}})
for line in sys.stdin:
    request = json.loads(line)
    job_id = request["job_id"]
    tool_id = request["tool_id"]
    if tool_id == "hang":
        time.sleep(60)
    elif tool_id == "fail":
        emit(
            {
                "type": "error",
                "job_id": job_id,
                "payload": {"message": "requested fake failure"},
            }
        )
    else:
        emit({"type": "result", "job_id": job_id, "payload": request["parameters"]})
~~~

- [ ] **Step 6: Run supervisor tests**

Run: uv run pytest tests/test_worker_supervisor.py -v

Expected: PASS and no fake worker process remains.

- [ ] **Step 7: Commit**

Run:

~~~powershell
git add src/arcpy_mcp_server/worker_protocol.py src/arcpy_mcp_server/worker_supervisor.py tests/fixtures/fake_worker.py tests/test_worker_supervisor.py
git commit -m "feat: supervise persistent ArcPy worker"
~~~

### Task 10: Add ArcPy Worker Health and Explicit Tool Bindings

**Files:**
- Create: src/arcpy_mcp_server/worker/main.py
- Create: src/arcpy_mcp_server/worker/health.py
- Create: src/arcpy_mcp_server/worker/executor.py
- Create: src/arcpy_mcp_server/worker/tool_bindings.py
- Create: tests/arcpy/test_worker_health.py
- Create: tests/arcpy/test_vector_smoke.py

- [ ] **Step 1: Write a real ArcPy health smoke test**

~~~python
import json
import subprocess
from pathlib import Path


ARCPY_PYTHON = Path(r"D:\Program Files\ArcGIS\Pro\bin\Python\envs\arcgispro-py3\python.exe")
WORKER = Path("src/arcpy_mcp_server/worker/main.py")


def test_worker_reports_arcgis_371_capabilities():
    process = subprocess.Popen(
        [str(ARCPY_PYTHON), "-u", str(WORKER)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    ready = json.loads(process.stdout.readline())
    process.terminate()

    assert ready["type"] == "ready"
    assert ready["payload"]["install"]["Version"] == "3.7.1"
    assert ready["payload"]["product"] == "ArcInfo"
    assert ready["payload"]["extensions"]["ImageAnalyst"] in {"Available", "CheckedOut"}
~~~

- [ ] **Step 2: Run the ArcPy test and verify failure**

Run:

~~~powershell
uv run pytest tests/arcpy/test_worker_health.py -v
~~~

Expected: FAIL because worker/main.py does not exist.

- [ ] **Step 3: Implement the capability probe**

~~~python
def collect_health():
    import arcpy

    return {
        "install": arcpy.GetInstallInfo(),
        "product": arcpy.ProductInfo(),
        "extensions": {
            "Spatial": arcpy.CheckExtension("Spatial"),
            "ImageAnalyst": arcpy.CheckExtension("ImageAnalyst"),
        },
        "processor_type": "CPU",
        "tools": {
            "DetectObjectsUsingDeepLearning": hasattr(
                arcpy.ia, "DetectObjectsUsingDeepLearning"
            ),
            "ClassifyPixelsUsingDeepLearning": hasattr(
                arcpy.ia, "ClassifyPixelsUsingDeepLearning"
            ),
            "DetectChangeUsingDeepLearning": hasattr(
                arcpy.ia, "DetectChangeUsingDeepLearning"
            ),
        },
    }
~~~

- [ ] **Step 4: Implement explicit bindings**

In tool_bindings.py define one Python function per catalog tool ID. Resolve no function name from request data. The initial vector bindings must call:

- arcpy.analysis.Buffer
- arcpy.analysis.Clip
- arcpy.management.Dissolve
- arcpy.analysis.Intersect
- arcpy.analysis.Union
- arcpy.analysis.SpatialJoin
- arcpy.management.Project
- arcpy.management.Merge
- arcpy.management.CheckGeometry
- arcpy.management.RepairGeometry

Each function receives server-resolved absolute input and output paths, calls ArcPy, and returns output metadata including GetCount where applicable.

Define BINDINGS as a literal dictionary from catalog tool ID to the corresponding function object.

Use these concrete binding shapes:

~~~python
def _count(arcpy, dataset):
    return int(arcpy.management.GetCount(dataset)[0])


def inspect_dataset(arcpy, p):
    described = arcpy.Describe(p["input_path"])
    fields = [
        {"name": field.name, "type": field.type, "length": field.length}
        for field in arcpy.ListFields(p["input_path"])
    ]
    extent = getattr(described, "extent", None)
    spatial_reference = getattr(described, "spatialReference", None)
    return {
        "data_type": described.dataType,
        "name": described.baseName,
        "count": _count(arcpy, p["input_path"]),
        "fields": fields,
        "extent": (
            {
                "xmin": extent.XMin,
                "ymin": extent.YMin,
                "xmax": extent.XMax,
                "ymax": extent.YMax,
            }
            if extent
            else None
        ),
        "spatial_reference": spatial_reference.name if spatial_reference else None,
    }


def buffer_features(arcpy, p):
    arcpy.analysis.Buffer(
        p["input_path"],
        p["output_path"],
        p["distance"],
        dissolve_option=p.get("dissolve_option", "NONE"),
    )
    return {"outputs": [p["output_path"]], "count": _count(arcpy, p["output_path"])}


def clip_features(arcpy, p):
    arcpy.analysis.Clip(p["input_path"], p["clip_path"], p["output_path"])
    return {"outputs": [p["output_path"]], "count": _count(arcpy, p["output_path"])}


def dissolve_features(arcpy, p):
    arcpy.management.Dissolve(
        p["input_path"],
        p["output_path"],
        p.get("dissolve_fields", []),
    )
    return {"outputs": [p["output_path"]], "count": _count(arcpy, p["output_path"])}


def intersect_features(arcpy, p):
    arcpy.analysis.Intersect(
        p["inputs"],
        p["output_path"],
        p.get("join_attributes", "ALL"),
    )
    return {"outputs": [p["output_path"]], "count": _count(arcpy, p["output_path"])}


def union_features(arcpy, p):
    arcpy.analysis.Union(
        p["inputs"],
        p["output_path"],
        gaps=p.get("gaps", "GAPS"),
    )
    return {"outputs": [p["output_path"]], "count": _count(arcpy, p["output_path"])}


def spatial_join(arcpy, p):
    arcpy.analysis.SpatialJoin(
        p["target_path"],
        p["join_path"],
        p["output_path"],
        join_operation=p.get("join_operation", "JOIN_ONE_TO_ONE"),
        match_option=p.get("match_option", "INTERSECT"),
    )
    return {"outputs": [p["output_path"]], "count": _count(arcpy, p["output_path"])}


def project_features(arcpy, p):
    arcpy.management.Project(
        p["input_path"],
        p["output_path"],
        p["output_spatial_reference"],
        p.get("geographic_transform"),
    )
    return {"outputs": [p["output_path"]], "count": _count(arcpy, p["output_path"])}


def merge_features(arcpy, p):
    arcpy.management.Merge(p["inputs"], p["output_path"])
    return {"outputs": [p["output_path"]], "count": _count(arcpy, p["output_path"])}


def check_geometry(arcpy, p):
    arcpy.management.CheckGeometry(
        p["input_path"],
        p["output_path"],
        p.get("validation_method", "ESRI"),
    )
    return {"outputs": [p["output_path"]], "count": _count(arcpy, p["output_path"])}


def repair_geometry(arcpy, p):
    arcpy.management.CopyFeatures(p["input_path"], p["output_path"])
    arcpy.management.RepairGeometry(
        p["output_path"],
        p.get("delete_null", "DELETE_NULL"),
        p.get("validation_method", "ESRI"),
    )
    return {"outputs": [p["output_path"]], "count": _count(arcpy, p["output_path"])}


BINDINGS = {
    "inspect.dataset": inspect_dataset,
    "vector.buffer": buffer_features,
    "vector.clip": clip_features,
    "vector.dissolve": dissolve_features,
    "vector.intersect": intersect_features,
    "vector.union": union_features,
    "vector.spatial_join": spatial_join,
    "vector.project": project_features,
    "vector.merge": merge_features,
    "vector.check_geometry": check_geometry,
    "vector.repair_geometry": repair_geometry,
}
~~~

- [ ] **Step 5: Implement executor and worker main loop**

executor.py must:

1. reject IDs missing from BINDINGS;
2. set arcpy.env.overwriteOutput to False;
3. set arcpy.env.processorType to CPU;
4. call the binding;
5. return arcpy.GetMessages(0), GetMessages(1), and GetMessages(2);
6. convert arcpy.ExecuteError into error code ARCPY_EXECUTION_FAILED.

main.py must:

1. print the ready capability message from collect_health;
2. read one JSON request per stdin line;
3. emit event messages before and after execution;
4. emit result or error with the same job ID;
5. never print non-protocol text to stdout.

Use this executor:

~~~python
def execute(tool_id, parameters):
    import arcpy

    from tool_bindings import BINDINGS

    binding = BINDINGS.get(tool_id)
    if binding is None:
        return {
            "ok": False,
            "error_code": "TOOL_NOT_ALLOWED",
            "message": "tool ID is not bound by the ArcPy worker",
        }
    arcpy.env.overwriteOutput = False
    arcpy.env.processorType = "CPU"
    try:
        with arcpy.EnvManager(
            workspace=parameters["work_dir"],
            scratchWorkspace=parameters["work_dir"],
        ):
            result = binding(arcpy, parameters)
        return {
            "ok": True,
            "result": result,
            "messages": {
                "all": arcpy.GetMessages(0),
                "warnings": arcpy.GetMessages(1),
                "errors": arcpy.GetMessages(2),
            },
        }
    except arcpy.ExecuteError:
        return {
            "ok": False,
            "error_code": "ARCPY_EXECUTION_FAILED",
            "message": arcpy.GetMessages(2),
            "messages": {"all": arcpy.GetMessages(0)},
        }
    except Exception as error:
        return {
            "ok": False,
            "error_code": "WORKER_CRASHED",
            "message": f"{type(error).__name__}: {error}",
        }
~~~

Use this main loop:

~~~python
import json
import sys

from executor import execute
from health import collect_health


def emit(message):
    sys.stdout.write(json.dumps(message, ensure_ascii=True, default=str) + "\n")
    sys.stdout.flush()


emit({"type": "ready", "payload": collect_health()})
for line in sys.stdin:
    request = json.loads(line)
    job_id = request["job_id"]
    emit({"type": "event", "job_id": job_id, "payload": {"stage": "started"}})
    response = execute(request["tool_id"], request["parameters"])
    if response["ok"]:
        emit(
            {
                "type": "result",
                "job_id": job_id,
                "payload": response,
            }
        )
    else:
        emit(
            {
                "type": "error",
                "job_id": job_id,
                "payload": response,
            }
        )
~~~

- [ ] **Step 6: Add a real vector smoke test**

The test creates a temporary FileGDB with arcpy.management.CreateFileGDB, creates a point feature class, inserts two points, sends vector.buffer to the worker, and asserts the output feature count is two. Cleanup uses arcpy.management.Delete inside a finally block.

- [ ] **Step 7: Run ArcPy worker tests**

Run:

~~~powershell
uv run pytest tests/arcpy/test_worker_health.py tests/arcpy/test_vector_smoke.py -v
~~~

Expected: PASS using ArcGIS Pro 3.7.1.

- [ ] **Step 8: Commit**

Run:

~~~powershell
git add src/arcpy_mcp_server/worker tests/arcpy
git commit -m "feat: execute allowlisted ArcPy vector tools"
~~~

### Task 11: Add Raster, Map, and Deep-Learning Bindings

**Files:**
- Modify: src/arcpy_mcp_server/worker/tool_bindings.py
- Modify: config/tool_catalog.yaml
- Create: tests/arcpy/test_raster_smoke.py
- Create: tests/arcpy/test_map_export.py
- Create: tests/arcpy/test_deep_learning_capabilities.py

- [ ] **Step 1: Write failing raster and capability tests**

The raster smoke test creates a 3-by-3 numeric raster with arcpy.NumPyArrayToRaster, executes raster.slope, and asserts arcpy.Exists on the output.

The deep-learning capability test asserts the health payload reports DetectObjectsUsingDeepLearning, ClassifyPixelsUsingDeepLearning, and DetectChangeUsingDeepLearning as true, processor_type as CPU, and no train-model binding in BINDINGS.

- [ ] **Step 2: Run tests and verify failure**

Run:

~~~powershell
uv run pytest tests/arcpy/test_raster_smoke.py tests/arcpy/test_deep_learning_capabilities.py -v
~~~

Expected: FAIL because the bindings are missing.

- [ ] **Step 3: Add raster bindings**

Add explicit functions for:

- arcpy.management.Clip
- arcpy.management.ProjectRaster
- arcpy.management.Resample
- arcpy.sa.ExtractByMask
- arcpy.sa.Slope
- arcpy.sa.ZonalStatisticsAsTable
- arcpy.management.MosaicToNewRaster

Use with arcpy.EnvManager(scratchWorkspace=work_dir, workspace=work_dir) and check out required extensions only for the duration of each call. Save Raster objects to the gateway-selected output path before returning.

Use these call forms:

~~~python
def clip_raster(arcpy, p):
    arcpy.management.Clip(
        p["input_path"],
        "#",
        p["output_path"],
        p["template_path"],
        "#",
        "ClippingGeometry" if p.get("clipping_geometry", True) else "NONE",
    )
    return {"outputs": [p["output_path"]]}


def project_raster(arcpy, p):
    arcpy.management.ProjectRaster(
        p["input_path"],
        p["output_path"],
        p["output_spatial_reference"],
        p.get("resampling_type", "NEAREST"),
        p.get("cell_size"),
    )
    return {"outputs": [p["output_path"]]}


def resample_raster(arcpy, p):
    arcpy.management.Resample(
        p["input_path"],
        p["output_path"],
        p["cell_size"],
        p.get("resampling_type", "NEAREST"),
    )
    return {"outputs": [p["output_path"]]}


def extract_by_mask(arcpy, p):
    with checked_out_extension(arcpy, "Spatial"):
        arcpy.sa.ExtractByMask(p["input_path"], p["mask_path"]).save(p["output_path"])
    return {"outputs": [p["output_path"]]}


def slope(arcpy, p):
    with checked_out_extension(arcpy, "Spatial"):
        arcpy.sa.Slope(
            p["input_path"],
            p.get("output_measurement", "DEGREE"),
            p.get("z_factor", 1),
        ).save(p["output_path"])
    return {"outputs": [p["output_path"]]}


def zonal_statistics(arcpy, p):
    with checked_out_extension(arcpy, "Spatial"):
        arcpy.sa.ZonalStatisticsAsTable(
            p["zone_path"],
            p["zone_field"],
            p["value_path"],
            p["output_path"],
            statistics_type=p.get("statistics_type", "ALL"),
        )
    return {"outputs": [p["output_path"]]}


def checked_out_extension(arcpy, name):
    class Extension:
        def __enter__(self):
            if arcpy.CheckExtension(name) != "Available":
                raise RuntimeError(f"{name} extension is unavailable")
            arcpy.CheckOutExtension(name)

        def __exit__(self, exc_type, exc, traceback):
            arcpy.CheckInExtension(name)

    return Extension()
~~~

- [ ] **Step 4: Add APRX inspection and export bindings**

Use arcpy.mp.ArcGISProject, listMaps, listLayouts, and layout.exportToPDF or layout.exportToPNG. Require exact layout name matching one layout. Reject zero or multiple matches.

~~~python
def inspect_aprx(arcpy, p):
    project = arcpy.mp.ArcGISProject(p["aprx_path"])
    return {
        "maps": [item.name for item in project.listMaps()],
        "layouts": [item.name for item in project.listLayouts()],
    }


def export_layout(arcpy, p):
    project = arcpy.mp.ArcGISProject(p["aprx_path"])
    layouts = [item for item in project.listLayouts() if item.name == p["layout_name"]]
    if len(layouts) != 1:
        raise ValueError("layout_name must match exactly one layout")
    if p["format"] == "PDF":
        layouts[0].exportToPDF(p["output_path"], resolution=p.get("dpi", 300))
    else:
        layouts[0].exportToPNG(p["output_path"], resolution=p.get("dpi", 300))
    return {"outputs": [p["output_path"]]}
~~~

- [ ] **Step 5: Add CPU deep-learning bindings**

Add explicit functions for:

- arcpy.ia.DetectObjectsUsingDeepLearning
- arcpy.ia.ClassifyPixelsUsingDeepLearning
- arcpy.ia.ClassifyObjectsUsingDeepLearning
- arcpy.ia.DetectChangeUsingDeepLearning
- arcpy.ia.TranslatePixelsUsingDeepLearning
- arcpy.ia.ExportTrainingDataForDeepLearning

Set arcpy.env.processorType to CPU before every call. Do not add TrainDeepLearningModel or SuperResolution. Model paths must be resolved from ready model artifacts by the gateway.

~~~python
def detect_objects(arcpy, p):
    with checked_out_extension(arcpy, "ImageAnalyst"):
        arcpy.ia.DetectObjectsUsingDeepLearning(
            p["input_path"],
            p["output_path"],
            p["model_path"],
            p.get("arguments", ""),
            p.get("run_nms", "NMS"),
            p.get("confidence_score_field", "Confidence"),
            p.get("class_value_field", "Class"),
            p.get("max_overlap_ratio", 0),
            "PROCESS_AS_MOSAICKED_IMAGE",
        )
    return {"outputs": [p["output_path"]]}


def classify_pixels(arcpy, p):
    with checked_out_extension(arcpy, "ImageAnalyst"):
        arcpy.ia.ClassifyPixelsUsingDeepLearning(
            p["input_path"],
            p["output_path"],
            p["model_path"],
            p.get("arguments", ""),
            "PROCESS_AS_MOSAICKED_IMAGE",
        )
    return {"outputs": [p["output_path"]]}


def detect_change(arcpy, p):
    with checked_out_extension(arcpy, "ImageAnalyst"):
        arcpy.ia.DetectChangeUsingDeepLearning(
            p["from_path"],
            p["to_path"],
            p["output_path"],
            p["model_path"],
            p.get("arguments", ""),
        )
    return {"outputs": [p["output_path"]]}
~~~

Verify every deep-learning signature against arcpy.Usage for its ArcGIS Pro 3.7.1 tool before committing. Record the returned usage text in the corresponding assertion fixture so an ArcGIS upgrade produces a visible failure rather than a silent argument shift.

- [ ] **Step 6: Add the map fixture and test**

Use a committed minimal APRX fixture only if it is legally redistributable and under 5 MiB. Otherwise create the APRX fixture locally in the test setup and mark the export test skipped with reason "ArcPy cannot create a new APRX without a template fixture". The skip is explicit test evidence, not a pass.

- [ ] **Step 7: Run ArcPy tests**

Run:

~~~powershell
uv run pytest tests/arcpy -v
~~~

Expected: vector, raster, and capability tests PASS. Map export is PASS with a fixture or explicitly SKIPPED with the stated reason. Real DL inference is SKIPPED unless ARCPY_MCP_DL_TEST_MODEL points to a compatible model.

- [ ] **Step 8: Commit**

Run:

~~~powershell
git add src/arcpy_mcp_server/worker/tool_bindings.py config/tool_catalog.yaml tests/arcpy
git commit -m "feat: add raster map and deep learning tools"
~~~

### Task 12: Connect Jobs to the Worker

**Files:**
- Modify: src/arcpy_mcp_server/jobs.py
- Modify: src/arcpy_mcp_server/db.py
- Create: tests/test_job_runner.py

- [ ] **Step 1: Write the serialized queue test**

Use the fake worker to submit two jobs, assert the second remains queued while the first is running, then assert both succeed in submission order. Add tests for timeout, cancellation, and worker crash mapping to JOB_TIMEOUT, JOB_CANCELLED, and WORKER_CRASHED.

- [ ] **Step 2: Run tests and verify failure**

Run: uv run pytest tests/test_job_runner.py -v

Expected: FAIL because JobService has no runner.

- [ ] **Step 3: Implement JobRunner**

JobRunner owns one asyncio.Queue, one background task, and the WorkerSupervisor. submit enqueues the persisted job ID. The loop transitions queued to starting to running, calls supervisor.execute with the catalog timeout, records worker events, registers declared outputs, and transitions to succeeded or the correct terminal error state.

cancel marks queued jobs cancelled immediately. For a running job it transitions to cancelling, calls supervisor.restart, removes incomplete output contents, and transitions to cancelled.

Resolve client artifact references before calling the worker with this helper:

~~~python
from copy import deepcopy


async def resolve_worker_parameters(
    definition,
    request: dict,
    artifact_service,
    workspace,
    job_id: str,
) -> dict:
    resolved = deepcopy(request)
    for input_definition in definition.inputs:
        if input_definition.multiple:
            container = input_definition.container_field
            if container is None:
                raise ValueError("multiple artifact input requires container_field")
            values = []
            for item in resolved[container]:
                path = await artifact_service.resolve_ready_path(
                    item[input_definition.artifact_id_field],
                    item[input_definition.path_field],
                )
                values.append(str(path))
            resolved[container] = values
            continue
        artifact_id = resolved.pop(input_definition.artifact_id_field)
        relative_path = resolved[input_definition.path_field]
        resolved[input_definition.path_field] = str(
            await artifact_service.resolve_ready_path(artifact_id, relative_path)
        )

    job_root = workspace.job_root(job_id)
    resolved["work_dir"] = str(job_root / "work")
    if definition.output is not None:
        output_name = resolved.pop(definition.output.name_field)
        output_path = workspace.resolve_relative(job_root / "output", output_name)
        resolved["output_path"] = str(output_path)
        resolved["output_kind"] = definition.output.kind
    return resolved
~~~

The runner must persist only the original client request, never the resolved Windows paths. Worker events containing paths are sanitized to artifact-relative names before insertion into job_events.

When a worker succeeds, remove its outputs path list before persisting the result. Register every declared path with ArtifactService, then persist only output_artifact_ids and non-path metrics:

~~~python
worker_result = response["result"]
declared_paths = [Path(value) for value in worker_result.pop("outputs", [])]
output_ids = []
for path in declared_paths:
    artifact = await artifact_service.register_output(
        path,
        path.name,
        "application/octet-stream",
    )
    output_ids.append(artifact.id)
safe_result = {**worker_result, "output_artifact_ids": output_ids}
~~~

Before enqueueing, link every input artifact ID with role input. After register_output, link each new artifact with role output:

~~~python
async def link_job_artifacts(db, job_id, definition, request, output_ids=()):
    for input_definition in definition.inputs:
        if input_definition.multiple:
            for item in request[input_definition.container_field]:
                await db.link_artifact(
                    job_id,
                    item[input_definition.artifact_id_field],
                    "input",
                )
        else:
            await db.link_artifact(
                job_id,
                request[input_definition.artifact_id_field],
                "input",
            )
    for artifact_id in output_ids:
        await db.link_artifact(job_id, artifact_id, "output")
~~~

- [ ] **Step 4: Run queue and recovery tests**

Run:

~~~powershell
uv run pytest tests/test_job_runner.py tests/test_jobs.py tests/test_worker_supervisor.py -v
~~~

Expected: PASS and no child worker remains.

- [ ] **Step 5: Commit**

Run:

~~~powershell
git add src/arcpy_mcp_server/jobs.py src/arcpy_mcp_server/db.py tests/test_job_runner.py
git commit -m "feat: run ArcPy jobs through one worker"
~~~

### Task 13: Expose MCP Tools and the Combined HTTPS Application

**Files:**
- Create: src/arcpy_mcp_server/mcp_tools.py
- Create: src/arcpy_mcp_server/app.py
- Create: src/arcpy_mcp_server/__main__.py
- Create: tests/test_mcp_tools.py
- Create: tests/test_app.py

- [ ] **Step 1: Write failing MCP and HTTP tests**

Test that:

- unauthenticated MCP initialization returns 401;
- the correct Bearer Token can call health_check;
- create_upload returns artifact ID, offset, and signed URL;
- submit_job rejects an unknown tool ID;
- artifact PUT with a valid signature is accepted without the Bearer header;
- /healthz returns only service status and version.

- [ ] **Step 2: Run tests and verify failure**

Run:

~~~powershell
uv run pytest tests/test_mcp_tools.py tests/test_app.py -v
~~~

Expected: FAIL because app.py and mcp_tools.py do not exist.

- [ ] **Step 3: Register stable MCP tools**

Create register_tools(mcp, services) and define typed async tools for:

- health_check
- get_capabilities
- search_tools
- describe_tool
- create_upload
- get_upload_status
- renew_upload
- complete_upload
- list_artifacts
- create_download
- delete_artifact
- submit_job
- get_job
- list_jobs
- cancel_job
- get_job_log

Register dedicated wrappers for the confirmed common tools. Each wrapper constructs a strict request for one catalog ID and returns the created job ID and status.

Use this exact external-name mapping:

| MCP tool name | Catalog tool ID |
|---|---|
| inspect_dataset | inspect.dataset |
| buffer_features | vector.buffer |
| clip_features | vector.clip |
| project_features | vector.project |
| dissolve_features | vector.dissolve |
| intersect_features | vector.intersect |
| spatial_join | vector.spatial_join |
| check_geometry | vector.check_geometry |
| repair_geometry | vector.repair_geometry |
| clip_raster | raster.clip |
| project_raster | raster.project |
| calculate_slope | raster.slope |
| zonal_statistics | raster.zonal_statistics |
| export_map_layout | map.export_layout |
| detect_objects | dl.detect_objects |
| classify_pixels | dl.classify_pixels |
| classify_objects | dl.classify_objects |
| detect_change | dl.detect_change |

- [ ] **Step 4: Assemble the application**

Create a Services dataclass containing settings, database, workspace, signer, artifact service, catalog, supervisor, job service, and runner.

Use an async FastMCP lifespan to start the database, reconcile stale jobs, start the worker and runner, then stop them in reverse order.

Construct:

~~~python
verifier = StaticBearerVerifier(
    settings.bearer_token.get_secret_value(),
    str(settings.public_base_url),
)
mcp = FastMCP(
    "ArcPy MCP",
    version="0.1.0",
    auth=verifier,
    lifespan=lifespan,
    strict_input_validation=True,
    mask_error_details=True,
)
register_tools(mcp, services)
app = mcp.http_app(path="/mcp", stateless_http=True, json_response=True)
~~~

Append signed artifact PUT, HEAD, and GET routes plus public /healthz to the returned Starlette app.

- [ ] **Step 5: Implement the TLS launcher**

__main__.py loads Settings and calls uvicorn.run with host, port, ssl_certfile, ssl_keyfile, log_config, and factory false. Abort before binding if certificate or key is missing.

- [ ] **Step 6: Run MCP and app tests**

Run:

~~~powershell
uv run pytest tests/test_mcp_tools.py tests/test_app.py -v
~~~

Expected: PASS.

- [ ] **Step 7: Commit**

Run:

~~~powershell
git add src/arcpy_mcp_server/mcp_tools.py src/arcpy_mcp_server/app.py src/arcpy_mcp_server/__main__.py tests/test_mcp_tools.py tests/test_app.py
git commit -m "feat: expose authenticated ArcPy MCP service"
~~~

### Task 14: Add TLS, Secrets, Firewall, and Scheduled Task Automation

**Files:**
- Create: src/arcpy_mcp_server/tls_bootstrap.py
- Create: scripts/bootstrap.ps1
- Create: scripts/bootstrap_tls.ps1
- Create: scripts/install_scheduled_task.ps1
- Create: scripts/uninstall_scheduled_task.ps1
- Create: scripts/start.ps1
- Create: scripts/stop.ps1
- Create: scripts/status.ps1
- Create: tests/test_tls_bootstrap.py
- Create: tests/test_powershell_scripts.py

- [ ] **Step 1: Write certificate tests**

Generate into a temporary directory and assert:

- CA BasicConstraints has ca true;
- server certificate IP SAN contains 192.168.25.228;
- server certificate verifies against the CA;
- private key files are not created beneath the repository root.

- [ ] **Step 2: Run tests and verify failure**

Run: uv run pytest tests/test_tls_bootstrap.py -v

Expected: FAIL because tls_bootstrap.py does not exist.

- [ ] **Step 3: Implement certificate generation**

Use cryptography to create:

- a 4096-bit RSA local CA valid for 10 years;
- a 2048-bit RSA server certificate valid for 825 days;
- IPAddress SAN 192.168.25.228;
- ExtendedKeyUsage SERVER_AUTH;
- PEM files with server key permission restricted to the current user.

The command is idempotent: it refuses to overwrite an existing CA private key unless --rotate is explicitly supplied.

- [ ] **Step 4: Implement bootstrap.ps1**

The script:

1. runs uv sync --dev;
2. creates %LOCALAPPDATA%\ArcPyMCP\config, certs, and data;
3. generates 48 random bytes for the Bearer Token and signing key;
4. writes server.env with ACL restricted to the current user;
5. calls bootstrap_tls.ps1;
6. prints the CA public certificate path and never prints either secret.

- [ ] **Step 5: Implement firewall and task scripts**

install_scheduled_task.ps1 must:

- require elevation only for New-NetFirewallRule;
- create rule ArcPy MCP 8765 for TCP 8765, Private profile, RemoteAddress 192.168.25.0/24;
- register task ArcPyMCPServer for the current user at logon;
- execute scripts/start.ps1 with hidden window style;
- set restart count 3 and restart interval 1 minute.

start.ps1 loads server.env into the process environment and starts:

~~~powershell
uv run python -m arcpy_mcp_server
~~~

stop.ps1 stops only the process recorded in %LOCALAPPDATA%\ArcPyMCP\server.pid. status.ps1 reports task state, PID state, TCP listener, and HTTPS health.

- [ ] **Step 6: Validate scripts**

Run:

~~~powershell
uv run pytest tests/test_tls_bootstrap.py tests/test_powershell_scripts.py -v
Get-ChildItem scripts\*.ps1 | ForEach-Object {
  $null = [scriptblock]::Create((Get-Content -Raw $_.FullName))
}
~~~

Expected: tests PASS and PowerShell parsing reports no error.

- [ ] **Step 7: Commit**

Run:

~~~powershell
git add src/arcpy_mcp_server/tls_bootstrap.py scripts tests/test_tls_bootstrap.py tests/test_powershell_scripts.py
git commit -m "feat: automate secure Windows deployment"
~~~

### Task 15: Complete Security, Recovery, and End-to-End Server Verification

**Files:**
- Create: tests/security/test_path_attacks.py
- Create: tests/security/test_archive_limits.py
- Create: tests/integration/test_gateway_fake_worker.py
- Create: tests/integration/test_worker_recovery.py
- Create: tests/arcpy/test_end_to_end_local.py
- Create: README.md

- [ ] **Step 1: Add adversarial tests**

Cover:

- .. traversal and percent-encoded traversal;
- drive paths, UNC paths, and alternate data streams;
- ZIP symlinks, too many entries, too much expanded data, and excessive depth;
- expired and tampered signatures;
- wrong upload offsets;
- oversized uploads;
- unknown tool IDs and extra parameters;
- unauthenticated MCP requests;
- secrets absent from logs.

- [ ] **Step 2: Add worker recovery tests**

Use the fake worker to force EOF, malformed JSON, timeout, and explicit failure. Assert the job terminal code, incomplete output cleanup, a new worker PID, and a successful following echo job.

- [ ] **Step 3: Add local real ArcPy end-to-end test**

The test:

1. creates a small zipped shapefile fixture;
2. uses the artifact service to upload and complete it;
3. submits vector.buffer;
4. waits for success;
5. verifies the output artifact exists and has a matching SHA-256;
6. creates a download URL and reads the result;
7. cleans the disposable workspace.

- [ ] **Step 4: Write operational documentation**

README.md must include:

- prerequisites and verified ArcGIS version;
- bootstrap and scheduled task commands;
- firewall and fixed-IP requirement;
- secret rotation;
- CA export for the plugin repository;
- health and log locations;
- backup and seven-day retention behavior;
- CPU deep-learning limitations;
- exact test commands;
- uninstall steps that preserve data unless -RemoveData is supplied.

- [ ] **Step 5: Run the complete server verification**

Run:

~~~powershell
uv run ruff check .
uv run pytest tests -v
git diff --check
~~~

Expected: Ruff PASS; all non-model tests PASS; map or DL tests are only skipped for the explicit fixture/model reasons; no whitespace errors.

- [ ] **Step 6: Install and smoke-test the Windows service**

Run from an elevated PowerShell only for the firewall step:

~~~powershell
.\scripts\bootstrap.ps1
.\scripts\install_scheduled_task.ps1
.\scripts\start.ps1
.\scripts\status.ps1
~~~

Expected: HTTPS health is healthy, ArcGIS version is 3.7.1, product is ArcInfo, and Spatial/ImageAnalyst are available.

- [ ] **Step 7: Commit and push**

Run:

~~~powershell
git add README.md tests
git commit -m "test: verify secure ArcPy MCP service"
git push origin main
git status --short
~~~

Expected: push succeeds and status is clean.
