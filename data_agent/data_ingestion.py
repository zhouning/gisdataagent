"""Durable, governed materialization of virtual ArcGIS data sources.

The operational ledger is deliberately separate from data assets: runs and
batches may fail or retry, while a new asset version is published only after
the requested sinks have committed successfully.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import math
import os
import re
import shutil
import socket
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import text

from .db_engine import get_engine

logger = logging.getLogger(__name__)

INGESTION_SCHEMA = "gda.virtual_source_ingestion.v1"
TARGET_MODES = frozenset({"lakehouse", "postgis", "lakehouse_postgis"})
SCHEDULE_POLICIES = frozenset(
    {"on_demand", "interval:5m", "interval:30m", "interval:1h"}
)
_IDENTIFIER_RE = re.compile(r"^[a-z][a-z0-9_]{0,62}$")
_INTERVALS = {
    "interval:5m": timedelta(minutes=5),
    "interval:30m": timedelta(minutes=30),
    "interval:1h": timedelta(hours=1),
}
_SCHEDULE_DRIVERS = frozenset({"internal", "external"})
_GEOMETRY_DIMENSION_POLICIES = frozenset({"source", "xy", "xyz"})
_GEOMETRY_TYPE_POLICIES = frozenset({"source", "multi"})


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=True, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _fingerprint(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def _frame_content_sha256(frame) -> str:
    """Hash one bounded page, including attributes and geometry."""
    try:
        document = json.loads(frame.to_json(drop_id=True, default=str))
    except TypeError:
        document = json.loads(
            frame.to_json(orient="table", index=False, date_format="iso")
        )
    return _fingerprint(document)


def _as_object(value: Any) -> dict:
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value:
        parsed = json.loads(value)
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _safe_component(value: str, fallback: str) -> str:
    normalized = re.sub(r"[^a-z0-9_-]+", "-", value.lower()).strip("-_")
    return (normalized or fallback)[:120]


def safe_table_name(value: str, fallback: str = "arcgis_dataset") -> str:
    normalized = re.sub(r"[^a-z0-9_]+", "_", value.lower()).strip("_")
    if not normalized or not normalized[0].isalpha():
        normalized = f"d_{normalized or fallback}"
    return normalized[:63]


def _schedule_next(policy: str, base: datetime | None = None) -> datetime | None:
    delta = _INTERVALS.get(policy)
    if delta is None:
        return None
    return (base or datetime.now(UTC)) + delta


class IngestionDefinitionSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_name: str = Field(min_length=1, max_length=200)
    target_mode: Literal["lakehouse", "postgis", "lakehouse_postgis"] = (
        "lakehouse_postgis"
    )
    target_table: str | None = Field(default=None, max_length=63)
    schedule_policy: Literal[
        "on_demand", "interval:5m", "interval:30m", "interval:1h"
    ] = "on_demand"
    write_mode: Literal["full_snapshot"] = "full_snapshot"
    max_records: int = Field(default=1_000_000, ge=1, le=1_000_000)
    page_size: int = Field(default=2_000, ge=1, le=5_000)
    config: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True

    @field_validator("target_name")
    @classmethod
    def _trim_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("target_name must not be blank")
        return value

    @model_validator(mode="after")
    def _target_is_consistent(self) -> IngestionDefinitionSpec:
        if self.target_mode == "lakehouse":
            if self.target_table is not None:
                raise ValueError("lakehouse-only ingestion must not set target_table")
        elif not self.target_table or not _IDENTIFIER_RE.fullmatch(self.target_table):
            raise ValueError(
                "PostGIS target_table must be a lowercase SQL identifier"
            )
        geometry_policy = str(
            self.config.get("geometry_dimension_policy", "source")
        ).strip().lower()
        if geometry_policy not in _GEOMETRY_DIMENSION_POLICIES:
            raise ValueError(
                "config.geometry_dimension_policy must be source, xy, or xyz"
            )
        geometry_type_policy = str(
            self.config.get("geometry_type_policy", "source")
        ).strip().lower()
        if geometry_type_policy not in _GEOMETRY_TYPE_POLICIES:
            raise ValueError(
                "config.geometry_type_policy must be source or multi"
            )
        return self


class IngestionCancelled(RuntimeError):
    pass


class IngestionStateConflict(RuntimeError):
    """The run no longer belongs to this worker or cannot transition."""


class IngestionRepository:
    """PostgreSQL operational ledger and lease-based work queue."""

    def __init__(self, engine=None) -> None:
        self.engine = engine or get_engine()
        if self.engine is None:
            raise RuntimeError("Database not available")

    @staticmethod
    def _definition(row) -> dict | None:
        if row is None:
            return None
        value = dict(row)
        value["config"] = _as_object(value.get("config"))
        return value

    @staticmethod
    def _run(row) -> dict | None:
        if row is None:
            return None
        value = dict(row)
        value["quality_summary"] = _as_object(value.get("quality_summary"))
        value["metadata_summary"] = _as_object(value.get("metadata_summary"))
        if value.get("run_id") is not None:
            value["run_id"] = str(value["run_id"])
        return value

    def create_definition(
        self,
        source_id: int,
        owner_username: str,
        tenant_id: str,
        spec: IngestionDefinitionSpec,
    ) -> dict:
        next_run_at = _schedule_next(spec.schedule_policy)
        params = {
            "source_id": source_id,
            "owner": owner_username,
            "tenant": tenant_id,
            **spec.model_dump(exclude={"config"}),
            "config": json.dumps(spec.config),
            "next_run_at": next_run_at,
        }
        with self.engine.begin() as connection:
            row = (
                connection.execute(
                    text(
                        """
                        INSERT INTO agent_ingestion_definitions (
                            source_id, owner_username, tenant_id, target_name,
                            target_mode, target_table, schedule_policy, write_mode,
                            max_records, page_size, config, enabled, next_run_at
                        ) VALUES (
                            :source_id, :owner, :tenant, :target_name,
                            :target_mode, :target_table, :schedule_policy, :write_mode,
                            :max_records, :page_size, CAST(:config AS jsonb),
                            :enabled, :next_run_at
                        )
                        ON CONFLICT (source_id, target_name, owner_username)
                        DO UPDATE SET
                            tenant_id = EXCLUDED.tenant_id,
                            target_mode = EXCLUDED.target_mode,
                            target_table = EXCLUDED.target_table,
                            schedule_policy = EXCLUDED.schedule_policy,
                            write_mode = EXCLUDED.write_mode,
                            max_records = EXCLUDED.max_records,
                            page_size = EXCLUDED.page_size,
                            config = EXCLUDED.config,
                            enabled = EXCLUDED.enabled,
                            next_run_at = EXCLUDED.next_run_at,
                            updated_at = NOW()
                        RETURNING *
                        """
                    ),
                    params,
                )
                .mappings()
                .one()
            )
        return self._definition(row)

    def get_definition(self, definition_id: int, owner_username: str) -> dict | None:
        with self.engine.connect() as connection:
            row = (
                connection.execute(
                    text(
                        """
                        SELECT * FROM agent_ingestion_definitions
                        WHERE id = :id AND owner_username = :owner
                        """
                    ),
                    {"id": definition_id, "owner": owner_username},
                )
                .mappings()
                .one_or_none()
            )
        return self._definition(row)

    def list_definitions(self, source_id: int, owner_username: str) -> list[dict]:
        with self.engine.connect() as connection:
            rows = (
                connection.execute(
                    text(
                        """
                        SELECT * FROM agent_ingestion_definitions
                        WHERE source_id = :source_id AND owner_username = :owner
                        ORDER BY created_at DESC
                        """
                    ),
                    {"source_id": source_id, "owner": owner_username},
                )
                .mappings()
                .all()
            )
        return [self._definition(row) for row in rows]

    def enqueue_run(
        self,
        definition: dict,
        *,
        trigger_type: str,
        idempotency_key: str | None = None,
    ) -> dict:
        run_id = uuid4()
        key = idempotency_key or f"{trigger_type}:{run_id}"
        with self.engine.begin() as connection:
            row = (
                connection.execute(
                    text(
                        """
                        INSERT INTO agent_ingestion_runs (
                            run_id, definition_id, source_id, owner_username,
                            tenant_id, idempotency_key, trigger_type
                        ) VALUES (
                            :run_id, :definition_id, :source_id, :owner,
                            :tenant, :key, :trigger
                        )
                        ON CONFLICT (definition_id, idempotency_key) DO UPDATE SET
                            idempotency_key = EXCLUDED.idempotency_key
                        RETURNING *
                        """
                    ),
                    {
                        "run_id": run_id,
                        "definition_id": definition["id"],
                        "source_id": definition["source_id"],
                        "owner": definition["owner_username"],
                        "tenant": definition["tenant_id"],
                        "key": key[:200],
                        "trigger": trigger_type,
                    },
                )
                .mappings()
                .one()
            )
        return self._run(row)

    def get_run(self, run_id: str, owner_username: str | None = None) -> dict | None:
        where = "run_id = :run_id"
        params: dict[str, Any] = {"run_id": UUID(str(run_id))}
        if owner_username is not None:
            where += " AND owner_username = :owner"
            params["owner"] = owner_username
        with self.engine.connect() as connection:
            row = (
                connection.execute(
                    text(f"SELECT * FROM agent_ingestion_runs WHERE {where}"),
                    params,
                )
                .mappings()
                .one_or_none()
            )
        return self._run(row)

    def list_runs(
        self,
        owner_username: str,
        *,
        definition_id: int | None = None,
        source_id: int | None = None,
        limit: int = 20,
    ) -> list[dict]:
        clauses = ["owner_username = :owner"]
        params: dict[str, Any] = {"owner": owner_username, "limit": min(limit, 100)}
        if definition_id is not None:
            clauses.append("definition_id = :definition_id")
            params["definition_id"] = definition_id
        if source_id is not None:
            clauses.append("source_id = :source_id")
            params["source_id"] = source_id
        with self.engine.connect() as connection:
            rows = (
                connection.execute(
                    text(
                        "SELECT * FROM agent_ingestion_runs WHERE "
                        + " AND ".join(clauses)
                        + " ORDER BY CASE WHEN status IN "
                        "('queued', 'running', 'committing', 'cancelling') "
                        "THEN 0 ELSE 1 END, created_at DESC LIMIT :limit"
                    ),
                    params,
                )
                .mappings()
                .all()
            )
        return [self._run(row) for row in rows]

    def enqueue_due_schedules(self, now: datetime | None = None) -> int:
        current = now or datetime.now(UTC)
        queued = 0
        with self.engine.begin() as connection:
            rows = (
                connection.execute(
                    text(
                        """
                        SELECT * FROM agent_ingestion_definitions
                        WHERE enabled = TRUE AND next_run_at IS NOT NULL
                          AND next_run_at <= :now
                        ORDER BY next_run_at
                        LIMIT 20
                        FOR UPDATE SKIP LOCKED
                        """
                    ),
                    {"now": current},
                )
                .mappings()
                .all()
            )
            for row in rows:
                scheduled_for = row["next_run_at"]
                key = f"schedule:{scheduled_for.astimezone(UTC).isoformat()}"
                result = connection.execute(
                    text(
                        """
                        INSERT INTO agent_ingestion_runs (
                            run_id, definition_id, source_id, owner_username,
                            tenant_id, idempotency_key, trigger_type
                        ) VALUES (
                            :run_id, :definition_id, :source_id, :owner,
                            :tenant, :key, 'schedule'
                        ) ON CONFLICT (definition_id, idempotency_key) DO NOTHING
                        """
                    ),
                    {
                        "run_id": uuid4(),
                        "definition_id": row["id"],
                        "source_id": row["source_id"],
                        "owner": row["owner_username"],
                        "tenant": row["tenant_id"],
                        "key": key,
                    },
                )
                queued += max(0, result.rowcount)
                connection.execute(
                    text(
                        """
                        UPDATE agent_ingestion_definitions
                        SET next_run_at = :next_run_at, last_run_at = :now,
                            updated_at = :now
                        WHERE id = :id
                        """
                    ),
                    {
                        "id": row["id"],
                        "now": current,
                        "next_run_at": _schedule_next(row["schedule_policy"], current),
                    },
                )
        return queued

    def claim_next(self, worker_id: str, lease_seconds: int = 300) -> dict | None:
        with self.engine.begin() as connection:
            connection.execute(
                text(
                    """
                    UPDATE agent_ingestion_runs
                    SET status = 'queued', worker_id = NULL, lease_expires_at = NULL,
                        error_message = COALESCE(error_message, 'worker lease expired; resumed')
                    WHERE status IN ('running', 'committing')
                      AND lease_expires_at < NOW()
                    """
                )
            )
            row = (
                connection.execute(
                    text(
                        """
                        WITH candidate AS (
                            SELECT run_id FROM agent_ingestion_runs
                            WHERE status = 'queued'
                            ORDER BY created_at
                            LIMIT 1 FOR UPDATE SKIP LOCKED
                        )
                        UPDATE agent_ingestion_runs AS run
                        SET status = 'running', worker_id = :worker,
                            lease_expires_at = NOW()
                                + make_interval(secs => :lease_seconds),
                            started_at = COALESCE(started_at, NOW()),
                            heartbeat_at = NOW(), error_message = NULL
                        FROM candidate
                        WHERE run.run_id = candidate.run_id
                        RETURNING run.*
                        """
                    ),
                    {"worker": worker_id, "lease_seconds": lease_seconds},
                )
                .mappings()
                .one_or_none()
            )
        return self._run(row)

    def initialize_run(
        self,
        run_id: str,
        worker_id: str,
        *,
        records_total: int,
        batches_total: int,
        source_snapshot_sha256: str,
    ) -> None:
        with self.engine.begin() as connection:
            result = connection.execute(
                text(
                    """
                    UPDATE agent_ingestion_runs
                    SET records_total = :records_total, batches_total = :batches_total,
                        source_snapshot_sha256 = :snapshot_sha, heartbeat_at = NOW(),
                        lease_expires_at = NOW() + interval '5 minutes'
                    WHERE run_id = :run_id AND worker_id = :worker
                      AND status = 'running' AND cancellation_requested = FALSE
                    """
                ),
                {
                    "run_id": UUID(run_id),
                    "worker": worker_id,
                    "records_total": records_total,
                    "batches_total": batches_total,
                    "snapshot_sha": source_snapshot_sha256,
                },
            )
            if result.rowcount != 1:
                self._raise_transition_error(
                    connection, run_id, worker_id, "initialize ingestion run"
                )

    def renew_lease(
        self, run_id: str, worker_id: str, lease_seconds: int = 300
    ) -> bool:
        """Keep ownership while a long remote snapshot is still making progress."""
        with self.engine.begin() as connection:
            result = connection.execute(
                text(
                    """
                    UPDATE agent_ingestion_runs
                    SET heartbeat_at = NOW(),
                        lease_expires_at = NOW()
                            + make_interval(secs => :lease_seconds)
                    WHERE run_id = :run_id AND worker_id = :worker
                      AND status = 'running' AND cancellation_requested = FALSE
                    """
                ),
                {
                    "run_id": UUID(run_id),
                    "worker": worker_id,
                    "lease_seconds": lease_seconds,
                },
            )
        return result.rowcount == 1

    def record_batch(
        self,
        run_id: str,
        worker_id: str,
        batch: dict[str, Any],
        *,
        records_read: int,
        records_written: int,
    ) -> None:
        with self.engine.begin() as connection:
            result = connection.execute(
                text(
                    """
                    INSERT INTO agent_ingestion_batches (
                        run_id, batch_index, status, first_object_id,
                        last_object_id, records_read, records_written,
                        content_sha256, lake_uri, completed_at
                    ) VALUES (
                        :run_id, :batch_index, 'succeeded', :first_id,
                        :last_id, :batch_read, :batch_written,
                        :content_sha, :lake_uri, NOW()
                    ) ON CONFLICT (run_id, batch_index) DO UPDATE SET
                        status = 'succeeded', first_object_id = EXCLUDED.first_object_id,
                        last_object_id = EXCLUDED.last_object_id,
                        records_read = EXCLUDED.records_read,
                        records_written = EXCLUDED.records_written,
                        content_sha256 = EXCLUDED.content_sha256,
                        lake_uri = EXCLUDED.lake_uri,
                        error_message = NULL, completed_at = NOW()
                    """
                ),
                {
                    "run_id": UUID(run_id),
                    "batch_index": batch["batch_index"],
                    "first_id": str(batch["object_ids"][0]) if batch["object_ids"] else None,
                    "last_id": str(batch["object_ids"][-1]) if batch["object_ids"] else None,
                    "batch_read": batch["records_read"],
                    "batch_written": batch["records_written"],
                    "content_sha": batch.get("content_sha256"),
                    "lake_uri": batch.get("lake_uri"),
                },
            )
            result = connection.execute(
                text(
                    """
                    UPDATE agent_ingestion_runs
                    SET records_read = :records_read,
                        records_written = :records_written,
                        batches_completed = :batches_completed,
                        heartbeat_at = NOW(),
                        lease_expires_at = NOW() + interval '5 minutes'
                    WHERE run_id = :run_id AND worker_id = :worker
                      AND status = 'running' AND cancellation_requested = FALSE
                    """
                ),
                {
                    "run_id": UUID(run_id),
                    "worker": worker_id,
                    "records_read": records_read,
                    "records_written": records_written,
                    "batches_completed": batch["batch_index"] + 1,
                },
            )
            if result.rowcount != 1:
                self._raise_transition_error(
                    connection, run_id, worker_id, "record ingestion batch"
                )

    @staticmethod
    def _raise_transition_error(
        connection, run_id: str, worker_id: str, action: str
    ) -> None:
        row = (
            connection.execute(
                text(
                    """
                    SELECT status, worker_id, cancellation_requested
                    FROM agent_ingestion_runs
                    WHERE run_id = :run_id
                    """
                ),
                {"run_id": UUID(run_id)},
            )
            .mappings()
            .one_or_none()
        )
        if row and (
            row["cancellation_requested"] or row["status"] in {"cancelling", "cancelled"}
        ):
            raise IngestionCancelled("ingestion cancelled by user")
        if row is None:
            reason = "run does not exist"
        elif row["worker_id"] != worker_id:
            reason = "worker lease is no longer owned"
        else:
            reason = f"run is {row['status']}"
        raise IngestionStateConflict(f"cannot {action}: {reason}")

    def cancellation_requested(self, run_id: str) -> bool:
        with self.engine.connect() as connection:
            return bool(
                connection.execute(
                    text(
                        "SELECT cancellation_requested FROM agent_ingestion_runs "
                        "WHERE run_id = :run_id"
                    ),
                    {"run_id": UUID(run_id)},
                ).scalar()
            )

    def request_cancel(self, run_id: str, owner_username: str) -> dict | None:
        with self.engine.begin() as connection:
            row = (
                connection.execute(
                    text(
                        """
                        UPDATE agent_ingestion_runs
                        SET cancellation_requested = TRUE,
                            status = CASE WHEN status = 'queued'
                                THEN 'cancelled' ELSE 'cancelling' END,
                            completed_at = CASE WHEN status = 'queued'
                                THEN NOW() ELSE completed_at END
                        WHERE run_id = :run_id AND owner_username = :owner
                          AND status IN ('queued', 'running', 'cancelling')
                        RETURNING *
                        """
                    ),
                    {"run_id": UUID(run_id), "owner": owner_username},
                )
                .mappings()
                .one_or_none()
            )
        return self._run(row)

    def begin_commit(
        self, run_id: str, worker_id: str, lease_seconds: int = 1800
    ) -> None:
        """Cross the cancellation boundary before publishing durable outputs."""
        with self.engine.begin() as connection:
            result = connection.execute(
                text(
                    """
                    UPDATE agent_ingestion_runs
                    SET status = 'committing', heartbeat_at = NOW(),
                        lease_expires_at = NOW()
                            + make_interval(secs => :lease_seconds)
                    WHERE run_id = :run_id AND worker_id = :worker
                      AND status = 'running' AND cancellation_requested = FALSE
                    """
                ),
                {
                    "run_id": UUID(run_id),
                    "worker": worker_id,
                    "lease_seconds": lease_seconds,
                },
            )
            if result.rowcount != 1:
                self._raise_transition_error(
                    connection, run_id, worker_id, "begin ingestion commit"
                )

    def complete(
        self,
        run_id: str,
        worker_id: str,
        *,
        target_content_sha256: str,
        target_uri: str | None,
        postgis_table: str | None,
        asset_id: int,
        quality_summary: dict,
        metadata_summary: dict,
    ) -> None:
        with self.engine.begin() as connection:
            result = connection.execute(
                text(
                    """
                    UPDATE agent_ingestion_runs
                    SET status = 'succeeded', records_written = records_read,
                        target_content_sha256 = :content_sha,
                        target_uri = :target_uri, postgis_table = :postgis_table,
                        asset_id = :asset_id,
                        quality_summary = CAST(:quality AS jsonb),
                        metadata_summary = CAST(:metadata AS jsonb),
                        worker_id = NULL, lease_expires_at = NULL,
                        heartbeat_at = NOW(), completed_at = NOW()
                    WHERE run_id = :run_id AND worker_id = :worker
                      AND status = 'committing' AND cancellation_requested = FALSE
                    """
                ),
                {
                    "run_id": UUID(run_id),
                    "worker": worker_id,
                    "content_sha": target_content_sha256,
                    "target_uri": target_uri,
                    "postgis_table": postgis_table,
                    "asset_id": asset_id,
                    "quality": json.dumps(quality_summary),
                    "metadata": json.dumps(metadata_summary),
                },
            )
            if result.rowcount != 1:
                self._raise_transition_error(
                    connection, run_id, worker_id, "complete ingestion run"
                )

    def fail(
        self, run_id: str, worker_id: str, message: str, *, cancelled: bool = False
    ) -> bool:
        status = "cancelled" if cancelled else "failed"
        with self.engine.begin() as connection:
            result = connection.execute(
                text(
                    """
                    UPDATE agent_ingestion_runs
                    SET status = :status, error_message = :message,
                        worker_id = NULL, lease_expires_at = NULL,
                        heartbeat_at = NOW(), completed_at = NOW()
                    WHERE run_id = :run_id AND worker_id = :worker
                      AND status IN ('running', 'committing', 'cancelling')
                    """
                ),
                {
                    "run_id": UUID(run_id),
                    "worker": worker_id,
                    "status": status,
                    "message": message[:2000],
                },
            )
        return result.rowcount == 1


class GeoParquetLakeWriter:
    """Write an immutable partitioned GeoParquet snapshot and commit marker."""

    def __init__(self, run: dict, definition: dict) -> None:
        root = Path(
            os.environ.get(
                "GDA_INGEST_LAKE_ROOT",
                str(Path(__file__).resolve().parent / "data_lake" / "raw"),
            )
        ).expanduser().resolve()
        tenant = _safe_component(run["tenant_id"], "local-dev")
        owner = _safe_component(run["owner_username"], "anonymous")
        target = _safe_component(definition["target_name"], f"source-{run['source_id']}")
        self.staging = root / ".staging" / run["run_id"]
        self.final = root / tenant / owner / target / f"snapshot={run['run_id']}"
        if self.staging.exists():
            shutil.rmtree(self.staging)
        self.staging.mkdir(parents=True, exist_ok=True)
        self.parts: list[dict[str, Any]] = []
        self.definition = definition
        self.run = run

    def write(self, batch_index: int, frame) -> dict:
        path = self.staging / f"part-{batch_index:05d}.parquet"
        frame.to_parquet(path, index=False)
        content_sha = hashlib.sha256(path.read_bytes()).hexdigest()
        part = {
            "name": path.name,
            "records": len(frame),
            "size_bytes": path.stat().st_size,
            "sha256": content_sha,
        }
        self.parts.append(part)
        return {"content_sha256": content_sha, "lake_uri": path.resolve().as_uri()}

    def abort(self) -> None:
        """Discard an uncommitted local snapshot after a terminal run failure."""
        if self.staging.exists():
            shutil.rmtree(self.staging)

    def finalize(self, manifest: dict[str, Any]) -> dict[str, Any]:
        content_sha = _fingerprint(
            [{"name": part["name"], "sha256": part["sha256"]} for part in self.parts]
        )
        document = {
            **manifest,
            "schema": INGESTION_SCHEMA,
            "storage_format": "geoparquet",
            "layout": "partitioned_snapshot",
            "parts": self.parts,
            "content_sha256": content_sha,
            "committed_at": datetime.now(UTC).isoformat(),
        }
        (self.staging / "manifest.json").write_bytes(_canonical_json(document))
        (self.staging / "_SUCCESS").write_text(content_sha, encoding="ascii")
        self.final.parent.mkdir(parents=True, exist_ok=True)
        if self.final.exists():
            stored = json.loads((self.final / "manifest.json").read_text(encoding="utf-8"))
            if stored.get("content_sha256") != content_sha:
                raise RuntimeError("existing lake snapshot differs from ingestion replay")
            shutil.rmtree(self.staging)
        else:
            os.replace(self.staging, self.final)

        target_uri = self.final.resolve().as_uri()
        if os.environ.get("GDA_INGEST_LAKE_BACKEND", "local") == "cloud":
            from .cloud_storage import AWSS3Adapter, get_cloud_adapter

            lake_bucket = os.environ.get("GDA_INGEST_LAKE_BUCKET", "").strip()
            provider = os.environ.get("CLOUD_STORAGE_PROVIDER", "").strip().lower()
            adapter = (
                AWSS3Adapter(bucket=lake_bucket)
                if lake_bucket and provider == "aws"
                else get_cloud_adapter()
            )
            if adapter is None:
                raise RuntimeError("cloud lake backend is configured but unavailable")
            prefix = os.environ.get("GDA_INGEST_LAKE_PREFIX", "lakehouse/raw").strip("/")
            prefix = f"{prefix}/{self.final.relative_to(self.final.parents[3])}"
            success_key = f"{prefix}/_SUCCESS"
            manifest_key = f"{prefix}/manifest.json"
            if adapter.exists(success_key):
                remote_manifest = self.final / ".remote-manifest.json"
                try:
                    if not adapter.download(manifest_key, str(remote_manifest)):
                        raise RuntimeError(
                            "committed cloud lake snapshot has no readable manifest"
                        )
                    stored = json.loads(remote_manifest.read_text(encoding="utf-8"))
                finally:
                    remote_manifest.unlink(missing_ok=True)
                if stored.get("content_sha256") != content_sha:
                    raise RuntimeError(
                        "existing cloud lake snapshot differs from ingestion replay"
                    )
                return {
                    "target_uri": f"s3://{adapter.get_bucket_name()}/{prefix}",
                    "content_sha256": content_sha,
                    "manifest": document,
                }
            ordered = [*sorted(self.final.glob("part-*.parquet")), self.final / "manifest.json"]
            for path in ordered:
                key = f"{prefix}/{path.name}"
                if not adapter.upload(str(path), key):
                    raise RuntimeError(f"cloud lake upload failed for {path.name}")
            if not adapter.upload(str(self.final / "_SUCCESS"), success_key):
                raise RuntimeError("cloud lake commit marker upload failed")
            target_uri = f"s3://{adapter.get_bucket_name()}/{prefix}"
        return {"target_uri": target_uri, "content_sha256": content_sha, "manifest": document}


class PostGISSnapshotWriter:
    """Stage pages and atomically swap a complete serving table."""

    def __init__(self, engine, target_table: str, run_id: str) -> None:
        if engine.dialect.name != "postgresql":
            raise RuntimeError("PostGIS ingestion requires PostgreSQL")
        if not _IDENTIFIER_RE.fullmatch(target_table):
            raise ValueError("invalid PostGIS target table")
        self.engine = engine
        self.target_table = target_table
        self.staging_table = safe_table_name(
            f"ingest_{target_table[:30]}_{run_id.replace('-', '')[:10]}"
        )
        self._first = True

    def write(self, frame) -> None:
        if self._first:
            with self.engine.begin() as connection:
                connection.execute(
                    text(f'DROP TABLE IF EXISTS public."{self.staging_table}"')
                )
        if hasattr(frame, "to_postgis") and getattr(frame, "geometry", None) is not None:
            frame.to_postgis(
                self.staging_table,
                self.engine,
                schema="public",
                if_exists="replace" if self._first else "append",
                index=False,
                chunksize=1000,
            )
        else:
            frame.to_sql(
                self.staging_table,
                self.engine,
                schema="public",
                if_exists="replace" if self._first else "append",
                index=False,
                chunksize=1000,
            )
        self._first = False

    def abort(self) -> None:
        """Drop the run-scoped staging table if it has not been published."""
        with self.engine.begin() as connection:
            connection.execute(
                text(f'DROP TABLE IF EXISTS public."{self.staging_table}"')
            )

    def finalize(self) -> str:
        if self._first:
            raise RuntimeError("cannot publish an empty PostGIS snapshot without schema")
        backup = safe_table_name(f"old_{self.target_table[:45]}_{uuid4().hex[:8]}")
        with self.engine.begin() as connection:
            target_exists = connection.execute(
                text("SELECT to_regclass(:name) IS NOT NULL"),
                {"name": f"public.{self.target_table}"},
            ).scalar_one()
            if target_exists:
                connection.execute(
                    text(
                        f'ALTER TABLE public."{self.target_table}" '
                        f'RENAME TO "{backup}"'
                    )
                )
            connection.execute(
                text(
                    f'ALTER TABLE public."{self.staging_table}" '
                    f'RENAME TO "{self.target_table}"'
                )
            )
            if target_exists:
                connection.execute(text(f'DROP TABLE public."{backup}"'))
            geometry_column = connection.execute(
                text(
                    """
                    SELECT f_geometry_column, srid FROM geometry_columns
                    WHERE f_table_schema = 'public' AND f_table_name = :table
                    LIMIT 1
                    """
                ),
                {"table": self.target_table},
            ).first()
            if geometry_column:
                geometry_name = str(geometry_column[0])
                geometry_srid = int(geometry_column[1] or 0)
                index_name = safe_table_name(f"idx_{self.target_table}_{geometry_name}")
                staging_index_name = safe_table_name(
                    f"idx_{self.staging_table}_{geometry_name}"
                )
                staging_index_exists = connection.execute(
                    text("SELECT to_regclass(:name) IS NOT NULL"),
                    {"name": f"public.{staging_index_name}"},
                ).scalar_one()
                if staging_index_exists and staging_index_name != index_name:
                    connection.execute(
                        text(
                            f'ALTER INDEX public."{staging_index_name}" '
                            f'RENAME TO "{index_name}"'
                        )
                    )
                elif not staging_index_exists:
                    connection.execute(
                        text(
                            f'CREATE INDEX IF NOT EXISTS "{index_name}" '
                            f'ON public."{self.target_table}" '
                            f'USING GIST ("{geometry_name}")'
                        )
                    )
                if geometry_srid in {4326, 4490, 4610}:
                    geography_index_name = safe_table_name(
                        f"idx_{self.target_table}_{geometry_name}_geog"
                    )
                    connection.execute(
                        text(
                            f'CREATE INDEX IF NOT EXISTS "{geography_index_name}" '
                            f'ON public."{self.target_table}" '
                            f'USING GIST (("{geometry_name}"::geography))'
                        )
                    )
        return self.target_table


class QualityAccumulator:
    def __init__(self) -> None:
        self.records = 0
        self.null_geometry = 0
        self.invalid_geometry = 0
        self.columns: tuple[str, ...] | None = None

    def observe(self, frame) -> None:
        columns = tuple(str(column) for column in frame.columns)
        if self.columns is None:
            self.columns = columns
        elif self.columns != columns:
            raise RuntimeError("source schema changed during the ingestion snapshot")
        self.records += len(frame)
        geometry = getattr(frame, "geometry", None)
        if geometry is not None:
            null_mask = geometry.isna()
            self.null_geometry += int(null_mask.sum())
            if (~null_mask).any():
                self.invalid_geometry += int((~geometry[~null_mask].is_valid).sum())

    def summary(self, expected_records: int, *, truncated: bool) -> dict[str, Any]:
        complete = self.records == expected_records
        return {
            "schema": "gda.ingestion_quality.v1",
            "verdict": "passed" if complete else "failed",
            "records_expected": expected_records,
            "records_observed": self.records,
            "record_count_complete": complete,
            "null_geometry_count": self.null_geometry,
            "invalid_geometry_count": self.invalid_geometry,
            "source_was_truncated_by_policy": truncated,
            "schema_sha256": _fingerprint(list(self.columns or ())),
            "columns": list(self.columns or ()),
        }


class GeometryDimensionNormalizer:
    """Apply an explicit target geometry dimensionality and retain audit counts."""

    def __init__(self, policy: str = "source") -> None:
        self.policy = str(policy).strip().lower()
        if self.policy not in _GEOMETRY_DIMENSION_POLICIES:
            raise ValueError("geometry dimension policy must be source, xy, or xyz")
        self.records_with_geometry = 0
        self.source_records_with_z = 0
        self.records_normalized = 0

    def normalize(self, frame):
        geometry = getattr(frame, "geometry", None)
        if geometry is None:
            return frame

        import shapely

        non_null = ~geometry.isna()
        records_with_geometry = int(non_null.sum())
        has_z = shapely.has_z(geometry.array)
        source_records_with_z = int(has_z[non_null].sum())
        self.records_with_geometry += records_with_geometry
        self.source_records_with_z += source_records_with_z

        if self.policy == "source" or records_with_geometry == 0:
            return frame
        result = frame.copy()
        if self.policy == "xy":
            self.records_normalized += source_records_with_z
            result.geometry = shapely.force_2d(geometry.array)
        else:
            records_without_z = records_with_geometry - source_records_with_z
            self.records_normalized += records_without_z
            result.geometry = shapely.force_3d(geometry.array, z=0.0)
        return result

    def summary(self) -> dict[str, Any]:
        return {
            "policy": self.policy,
            "records_with_geometry": self.records_with_geometry,
            "source_records_with_z": self.source_records_with_z,
            "records_normalized": self.records_normalized,
            "xyz_fill_value": 0.0 if self.policy == "xyz" else None,
        }


class GeometryTypeNormalizer:
    """Normalize simple geometries to multi types for stable sink schemas."""

    def __init__(self, policy: str = "source") -> None:
        self.policy = str(policy).strip().lower()
        if self.policy not in _GEOMETRY_TYPE_POLICIES:
            raise ValueError("geometry type policy must be source or multi")
        self.source_types: Counter[str] = Counter()
        self.records_normalized = 0

    def normalize(self, frame):
        geometry = getattr(frame, "geometry", None)
        if geometry is None:
            return frame

        from shapely.geometry import (
            LineString,
            MultiLineString,
            MultiPoint,
            MultiPolygon,
            Point,
            Polygon,
        )

        values = []
        changed = False
        for value in geometry.array:
            if value is None:
                values.append(None)
                continue
            self.source_types[value.geom_type] += 1
            normalized = value
            if self.policy == "multi":
                if isinstance(value, Polygon):
                    normalized = MultiPolygon([value])
                elif isinstance(value, LineString):
                    normalized = MultiLineString([value])
                elif isinstance(value, Point):
                    normalized = MultiPoint([value])
            if normalized is not value:
                changed = True
                self.records_normalized += 1
            values.append(normalized)
        if not changed:
            return frame
        result = frame.copy()
        result.geometry = values
        return result

    def summary(self) -> dict[str, Any]:
        return {
            "policy": self.policy,
            "source_type_counts": dict(sorted(self.source_types.items())),
            "records_normalized": self.records_normalized,
        }


class AssetPublisher:
    """Publish source/target assets, version history, and a lineage edge."""

    def __init__(self, engine) -> None:
        self.engine = engine

    def publish(
        self,
        *,
        source: dict,
        definition: dict,
        run: dict,
        target_uri: str | None,
        postgis_table: str | None,
        file_size_bytes: int,
        content_sha256: str,
        source_snapshot_sha256: str,
        quality: dict,
    ) -> dict[str, Any]:
        owner = run["owner_username"]
        source_external_id = f"virtual-source:{source['id']}"
        target_external_id = f"ingestion-definition:{definition['id']}"
        target_name = definition["target_name"]
        storage_backend = (
            "lakehouse_postgis" if target_uri and postgis_table
            else "lakehouse" if target_uri else "postgis"
        )
        technical = {
            "storage": {
                "backend": storage_backend,
                "lakehouse_uri": target_uri,
                "postgis_table": postgis_table,
                "format": "geoparquet" if target_uri else "postgis",
                "size_bytes": file_size_bytes,
            },
            "spatial": {"crs": source.get("default_crs", "EPSG:4326")},
            "structure": {
                "feature_count": quality["records_observed"],
                "columns": quality["columns"],
                "schema_sha256": quality["schema_sha256"],
            },
            "checksums": {
                "source_snapshot_sha256": source_snapshot_sha256,
                "target_content_sha256": content_sha256,
            },
        }
        business = {
            "semantic": {
                "description": f"Materialized snapshot of {source['source_name']}",
                "keywords": ["arcgis", "ingestion", "ods", "geospatial"],
            },
            "classification": {
                "category": "vector",
                "source_access": "public_read_only",
                "logical_stage": "raw_ods",
            },
            "quality": quality,
        }
        with self.engine.begin() as connection:
            connection.execute(
                text(
                    """
                    SELECT set_config('app.current_user', :owner, true),
                           set_config('app.current_user_role',
                                      'ingestion_worker', true)
                    """
                ),
                {"owner": owner},
            )
            source_asset_id = connection.execute(
                text(
                    """
                    INSERT INTO agent_data_assets (
                        asset_name, display_name, owner_username,
                        external_system, external_id, external_url, external_metadata,
                        technical_metadata, business_metadata,
                        operational_metadata, lineage_metadata
                    ) VALUES (
                        :asset_name, :display_name, :owner,
                        'arcgis_rest', :external_id, :url, CAST(:external_meta AS jsonb),
                        CAST(:technical AS jsonb), CAST(:business AS jsonb),
                        CAST(:operational AS jsonb), '{}'::jsonb
                    ) ON CONFLICT (
                        owner_username, external_system, external_id
                    ) WHERE external_system IS NOT NULL AND external_id IS NOT NULL
                    DO UPDATE SET
                        asset_name = EXCLUDED.asset_name,
                        display_name = EXCLUDED.display_name,
                        external_id = EXCLUDED.external_id,
                        external_url = EXCLUDED.external_url,
                        external_metadata = EXCLUDED.external_metadata,
                        technical_metadata = EXCLUDED.technical_metadata,
                        business_metadata = EXCLUDED.business_metadata,
                        operational_metadata = EXCLUDED.operational_metadata,
                        updated_at = NOW()
                    RETURNING id
                    """
                ),
                {
                    "asset_name": f"arcgis:{source['source_name']}",
                    "display_name": source["source_name"],
                    "owner": owner,
                    "external_id": source_external_id,
                    "url": source["endpoint_url"],
                    "external_meta": json.dumps({
                        "source_type": source["source_type"],
                        "query_config": source.get("query_config", {}),
                    }),
                    "technical": json.dumps({
                        "service": {
                            "type": "arcgis_rest",
                            "endpoint_url": source["endpoint_url"],
                            "access": "read_only",
                        }
                    }),
                    "business": json.dumps({
                        "classification": {"source_access": "public_read_only"}
                    }),
                    "operational": json.dumps({
                        "refresh_policy": source.get("refresh_policy", "on_demand")
                    }),
                },
            ).scalar_one()

            existing = (
                connection.execute(
                    text(
                        """
                        SELECT id, technical_metadata, operational_metadata
                        FROM agent_data_assets
                        WHERE owner_username = :owner
                          AND external_system = 'gda_ingestion'
                          AND external_id = :external_id
                        """
                    ),
                    {"external_id": target_external_id, "owner": owner},
                )
                .mappings()
                .one_or_none()
            )
            existing_tech = _as_object(existing["technical_metadata"]) if existing else {}
            existing_ops = _as_object(existing["operational_metadata"]) if existing else {}
            previous_sha = (
                existing_tech.get("checksums", {}).get("target_content_sha256")
            )
            previous_version = int(existing_ops.get("version", {}).get("version", 0))
            version = previous_version if previous_sha == content_sha256 else previous_version + 1
            version = max(version, 1)
            operational = {
                "ingestion": {
                    "run_id": run["run_id"],
                    "definition_id": definition["id"],
                    "source_id": source["id"],
                    "trigger_type": run["trigger_type"],
                    "write_mode": definition["write_mode"],
                    "schedule_policy": definition["schedule_policy"],
                    "completed_at": datetime.now(UTC).isoformat(),
                },
                "version": {"version": version, "is_latest": True},
                "lifecycle": {"stage": "active", "logical_stage": "raw_ods"},
            }
            lineage = {
                "upstream": {
                    "asset_ids": [source_asset_id],
                    "external_system": "arcgis_rest",
                    "external_id": source_external_id,
                    "endpoint_url": source["endpoint_url"],
                },
                "transformation": {
                    "type": "full_snapshot_ingestion",
                    "run_id": run["run_id"],
                    "source_snapshot_sha256": source_snapshot_sha256,
                },
            }
            target_asset_id = connection.execute(
                text(
                    """
                    INSERT INTO agent_data_assets (
                        asset_name, display_name, owner_username,
                        external_system, external_id,
                        technical_metadata, business_metadata,
                        operational_metadata, lineage_metadata
                    ) VALUES (
                        :name, :name, :owner, 'gda_ingestion', :external_id,
                        CAST(:technical AS jsonb),
                        CAST(:business AS jsonb), CAST(:operational AS jsonb),
                        CAST(:lineage AS jsonb)
                    ) ON CONFLICT (
                        owner_username, external_system, external_id
                    ) WHERE external_system IS NOT NULL AND external_id IS NOT NULL
                    DO UPDATE SET
                        asset_name = EXCLUDED.asset_name,
                        display_name = EXCLUDED.display_name,
                        technical_metadata = EXCLUDED.technical_metadata,
                        business_metadata = EXCLUDED.business_metadata,
                        operational_metadata = EXCLUDED.operational_metadata,
                        lineage_metadata = EXCLUDED.lineage_metadata,
                        updated_at = NOW()
                    RETURNING id
                    """
                ),
                {
                    "name": target_name,
                    "owner": owner,
                    "external_id": target_external_id,
                    "technical": json.dumps(technical),
                    "business": json.dumps(business),
                    "operational": json.dumps(operational),
                    "lineage": json.dumps(lineage),
                },
            ).scalar_one()
            if previous_sha != content_sha256:
                connection.execute(
                    text(
                        """
                        INSERT INTO agent_asset_versions (
                            asset_id, version, snapshot_path, file_size_bytes,
                            feature_count, change_summary, created_by
                        ) VALUES (
                            :asset_id, :version, :snapshot_path, :file_size_bytes,
                            :feature_count, :summary, :owner
                        )
                        """
                    ),
                    {
                        "asset_id": target_asset_id,
                        "version": version,
                        "snapshot_path": target_uri or f"postgis://{postgis_table}",
                        "file_size_bytes": file_size_bytes,
                        "feature_count": quality["records_observed"],
                        "summary": f"ArcGIS ingestion run {run['run_id']}",
                        "owner": owner,
                    },
                )
            connection.execute(
                text(
                    """
                    INSERT INTO agent_asset_lineage (
                        source_asset_id, source_external_system, source_external_id,
                        target_asset_id, relationship, tool_name,
                        pipeline_run_id, metadata, created_by
                    ) SELECT
                        :source_asset_id, 'arcgis_rest', :source_external_id,
                        :target_asset_id, 'feeds_into', 'arcgis_data_ingestion',
                        :run_id, CAST(:metadata AS jsonb), :owner
                    WHERE NOT EXISTS (
                        SELECT 1 FROM agent_asset_lineage
                        WHERE source_asset_id = :source_asset_id
                          AND target_asset_id = :target_asset_id
                          AND pipeline_run_id = :run_id
                    )
                    """
                ),
                {
                    "source_asset_id": source_asset_id,
                    "source_external_id": source_external_id,
                    "target_asset_id": target_asset_id,
                    "run_id": run["run_id"],
                    "metadata": json.dumps({
                        "source_snapshot_sha256": source_snapshot_sha256,
                        "target_content_sha256": content_sha256,
                    }),
                    "owner": owner,
                },
            )
        return {
            "asset_id": target_asset_id,
            "source_asset_id": source_asset_id,
            "asset_version": version,
            "technical": technical,
            "business": business,
            "operational": operational,
            "lineage": lineage,
        }


def publish_platform_lineage(
    *,
    source: dict,
    definition: dict,
    run: dict,
    asset_id: int,
    source_snapshot_sha256: str,
    target_content_sha256: str,
    target_uri: str | None,
    postgis_table: str | None,
) -> dict[str, Any]:
    """Best-effort bridge to the tenant control ledger and metadata outbox."""
    if os.environ.get("GDA_INGEST_PLATFORM_BRIDGE", "1") == "0":
        return {"status": "disabled"}
    try:
        from .platform_contracts import (
            LineageEvent,
            LineageEventType,
            Resource,
            ResourceVersion,
            canonical_json_fingerprint,
        )
        from .platform_gateway import PlatformGateway

        tenant = run["tenant_id"]
        source_slug = f"arcgis-source-{source['id']}"
        target_slug = _safe_component(definition["target_name"], f"asset-{asset_id}")
        source_urn = f"gda://{tenant}/dataset/{source_slug}"
        target_urn = f"gda://{tenant}/dataset/{target_slug}"
        source_version_id = uuid5(
            NAMESPACE_URL, f"{source_urn}:{source_snapshot_sha256}"
        )
        target_version_id = uuid5(
            NAMESPACE_URL, f"{target_urn}:{target_content_sha256}"
        )
        now = datetime.now(UTC)
        gateway = PlatformGateway()
        gateway.register_resource(Resource(
            tenant_id=tenant,
            resource_urn=source_urn,
            resource_kind="dataset",
            authority_system="arcgis_rest",
            authority_locator=f"virtual-source:{source['id']}",
            owner_ref=f"human:{run['owner_username']}",
            governance_ref={"access": "public_read_only", "logical_stage": "source"},
            technical_refs=({"provider": "arcgis_rest"},),
        ))
        gateway.register_resource_version(ResourceVersion(
            tenant_id=tenant,
            resource_urn=source_urn,
            resource_version_id=source_version_id,
            version_key=f"sha256-{source_snapshot_sha256[:12]}",
            content_sha256=source_snapshot_sha256,
            authority_version_ref={
                "endpoint_url": source["endpoint_url"],
                "query_config": source.get("query_config", {}),
            },
            created_by="workload:gda-arcgis-ingestion",
            created_at=now,
        ))
        gateway.register_resource(Resource(
            tenant_id=tenant,
            resource_urn=target_urn,
            resource_kind="dataset",
            authority_system="gda_lakehouse",
            authority_locator=f"asset:{asset_id}",
            owner_ref=f"human:{run['owner_username']}",
            governance_ref={"logical_stage": "raw_ods"},
            technical_refs=({
                "lakehouse_uri": target_uri,
                "postgis_table": postgis_table,
            },),
        ))
        gateway.register_resource_version(ResourceVersion(
            tenant_id=tenant,
            resource_urn=target_urn,
            resource_version_id=target_version_id,
            version_key=f"sha256-{target_content_sha256[:12]}",
            content_sha256=target_content_sha256,
            authority_version_ref={
                "asset_id": asset_id,
                "ingestion_run_id": run["run_id"],
                "lakehouse_uri": target_uri,
                "postgis_table": postgis_table,
            },
            created_by="workload:gda-arcgis-ingestion",
            created_at=now,
        ))
        facets = {
            "schema": "gda.arcgis_ingestion_lineage.v1",
            "ingestion_run_id": run["run_id"],
            "source_endpoint": source["endpoint_url"],
            "source_snapshot_sha256": source_snapshot_sha256,
            "target_content_sha256": target_content_sha256,
            "write_mode": definition["write_mode"],
        }
        lineage_id = uuid5(
            target_version_id, f"copy:{source_version_id}:{run['run_id']}"
        )
        gateway.record_lineage(LineageEvent(
            tenant_id=tenant,
            lineage_event_id=lineage_id,
            event_type=LineageEventType.COPY,
            source_resource_version_id=source_version_id,
            target_resource_version_id=target_version_id,
            producer="workload:gda-arcgis-ingestion",
            event_sha256=canonical_json_fingerprint(facets),
            facets=facets,
            occurred_at=now,
        ))
        return {
            "status": "recorded",
            "source_resource_urn": source_urn,
            "source_resource_version_id": str(source_version_id),
            "target_resource_urn": target_urn,
            "target_resource_version_id": str(target_version_id),
            "lineage_event_id": str(lineage_id),
            "metadata_projection": "queued_by_lineage_outbox",
        }
    except Exception as exc:
        logger.warning("Platform ingestion lineage bridge failed: %s", exc)
        return {"status": "unavailable", "message": str(exc)[:300]}


class ArcGISIngestionExecutor:
    def __init__(self, repository: IngestionRepository, *, worker_id: str) -> None:
        self.repository = repository
        self.worker_id = worker_id

    async def execute(self, run: dict) -> None:
        run_id = run["run_id"]
        lake_writer = None
        postgis_writer = None
        lease_task = asyncio.create_task(
            self._maintain_lease(run_id),
            name=f"ingestion-lease-{run_id}",
        )
        try:
            definition = self.repository.get_definition(
                run["definition_id"], run["owner_username"]
            )
            if definition is None:
                raise RuntimeError("ingestion definition no longer exists")
            from .virtual_sources import (
                apply_schema_mapping,
                get_virtual_source,
            )

            source = get_virtual_source(run["source_id"], run["owner_username"])
            if source is None or not source.get("enabled", True):
                raise RuntimeError("virtual source is missing or disabled")
            if source.get("source_type") != "arcgis_rest":
                raise RuntimeError("this ingestion executor only accepts ArcGIS REST sources")
            from .connectors.arcgis_rest import ArcGISRestConnector

            connector = ArcGISRestConnector()

            async def renew_snapshot_lease() -> None:
                renewed = await asyncio.to_thread(
                    self.repository.renew_lease, run_id, self.worker_id
                )
                if not renewed:
                    raise IngestionStateConflict(
                        "cannot continue ArcGIS snapshot: worker lease is no longer owned"
                    )

            snapshot = await connector.create_query_snapshot(
                source["endpoint_url"],
                source.get("auth_config", {}),
                source.get("query_config", {}),
                max_records=definition["max_records"],
                progress_callback=renew_snapshot_lease,
            )
            snapshot_strategy = getattr(
                snapshot, "snapshot_strategy", "return_ids_only"
            )
            source_snapshot_sha = _fingerprint({
                "endpoint_url": source["endpoint_url"],
                "layer_id": snapshot.layer_id,
                "snapshot_strategy": snapshot_strategy,
                "where": snapshot.where,
                "out_fields": snapshot.out_fields,
                "object_id_field": snapshot.object_id_field,
                "object_ids": list(snapshot.object_ids),
            })
            batches_total = math.ceil(snapshot.record_count / definition["page_size"])
            self.repository.initialize_run(
                run_id,
                self.worker_id,
                records_total=snapshot.record_count,
                batches_total=batches_total,
                source_snapshot_sha256=source_snapshot_sha,
            )

            if definition["target_mode"] in {"lakehouse", "lakehouse_postgis"}:
                lake_writer = GeoParquetLakeWriter(run, definition)
            if definition["target_mode"] in {"postgis", "lakehouse_postgis"}:
                postgis_writer = PostGISSnapshotWriter(
                    self.repository.engine,
                    definition["target_table"],
                    run_id,
                )

            quality = QualityAccumulator()
            dimension_normalizer = GeometryDimensionNormalizer(
                definition.get("config", {}).get(
                    "geometry_dimension_policy", "source"
                )
            )
            type_normalizer = GeometryTypeNormalizer(
                definition.get("config", {}).get("geometry_type_policy", "source")
            )
            records_read = 0
            records_written = 0
            batch_content_hashes: list[str] = []
            async for page in connector.iter_snapshot_pages(
                snapshot,
                source.get("auth_config", {}),
                page_size=definition["page_size"],
                target_crs=source.get("default_crs", "EPSG:4326"),
                progress_callback=renew_snapshot_lease,
            ):
                if self.repository.cancellation_requested(run_id):
                    raise IngestionCancelled("ingestion cancelled by user")
                frame = apply_schema_mapping(
                    page["frame"], source.get("schema_mapping", {})
                )
                frame = dimension_normalizer.normalize(frame)
                frame = type_normalizer.normalize(frame)
                quality.observe(frame)
                evidence: dict[str, Any] = {}
                if lake_writer is not None:
                    evidence.update(lake_writer.write(page["batch_index"], frame))
                else:
                    evidence["content_sha256"] = _frame_content_sha256(frame)
                batch_content_hashes.append(evidence["content_sha256"])
                if postgis_writer is not None:
                    await asyncio.to_thread(postgis_writer.write, frame)
                records_read += page["records_read"]
                records_written += len(frame)
                self.repository.record_batch(
                    run_id,
                    self.worker_id,
                    {
                        **page,
                        **evidence,
                        "records_written": len(frame),
                    },
                    records_read=records_read,
                    records_written=records_written,
                )

            quality_summary = quality.summary(
                snapshot.record_count, truncated=snapshot.truncated,
            )
            quality_summary["geometry_dimension"] = dimension_normalizer.summary()
            quality_summary["geometry_type"] = type_normalizer.summary()
            if quality_summary["verdict"] != "passed":
                raise RuntimeError("ingestion quality gate rejected incomplete source read")
            self.repository.begin_commit(run_id, self.worker_id)
            lake_result = None
            if lake_writer is not None:
                lake_result = await asyncio.to_thread(
                    lake_writer.finalize,
                    {
                        "run_id": run_id,
                        "definition_id": definition["id"],
                        "source_id": source["id"],
                        "source_name": source["source_name"],
                        "source_endpoint": source["endpoint_url"],
                        "source_snapshot_strategy": snapshot_strategy,
                        "source_snapshot_sha256": source_snapshot_sha,
                        "source_matched_record_count": snapshot.matched_record_count,
                        "records_written": records_written,
                        "crs": source.get("default_crs", "EPSG:4326"),
                        "quality": quality_summary,
                    },
                )
            postgis_table = None
            if postgis_writer is not None:
                postgis_table = await asyncio.to_thread(postgis_writer.finalize)
            content_sha = (
                lake_result["content_sha256"]
                if lake_result is not None
                else _fingerprint({
                    "source_snapshot_sha256": source_snapshot_sha,
                    "records_written": records_written,
                    "schema_sha256": quality_summary["schema_sha256"],
                    "batch_content_sha256": batch_content_hashes,
                })
            )
            target_uri = lake_result["target_uri"] if lake_result else None
            published = AssetPublisher(self.repository.engine).publish(
                source=source,
                definition=definition,
                run=run,
                target_uri=target_uri,
                postgis_table=postgis_table,
                file_size_bytes=sum(
                    int(part.get("size_bytes") or 0)
                    for part in (
                        lake_result["manifest"].get("parts", [])
                        if lake_result is not None
                        else []
                    )
                ),
                content_sha256=content_sha,
                source_snapshot_sha256=source_snapshot_sha,
                quality=quality_summary,
            )
            platform = publish_platform_lineage(
                source=source,
                definition=definition,
                run=run,
                asset_id=published["asset_id"],
                source_snapshot_sha256=source_snapshot_sha,
                target_content_sha256=content_sha,
                target_uri=target_uri,
                postgis_table=postgis_table,
            )
            metadata_summary = {
                "schema": INGESTION_SCHEMA,
                "asset_version": published["asset_version"],
                "source_asset_id": published["source_asset_id"],
                "platform_control": platform,
                "lake_manifest": lake_result["manifest"] if lake_result else None,
            }
            self.repository.complete(
                run_id,
                self.worker_id,
                target_content_sha256=content_sha,
                target_uri=target_uri,
                postgis_table=postgis_table,
                asset_id=published["asset_id"],
                quality_summary=quality_summary,
                metadata_summary=metadata_summary,
            )
        except IngestionCancelled as exc:
            await self._abort_staging(lake_writer, postgis_writer, run_id)
            if not self.repository.fail(
                run_id, self.worker_id, str(exc), cancelled=True
            ):
                logger.warning(
                    "Cancelled ingestion run %s was no longer owned by %s",
                    run_id,
                    self.worker_id,
                )
        except Exception as exc:
            logger.exception("ArcGIS ingestion run %s failed", run_id)
            await self._abort_staging(lake_writer, postgis_writer, run_id)
            if not self.repository.fail(run_id, self.worker_id, str(exc)):
                logger.warning(
                    "Failed ingestion run %s was no longer owned by %s",
                    run_id,
                    self.worker_id,
                )
        finally:
            lease_task.cancel()
            try:
                await lease_task
            except asyncio.CancelledError:
                pass
            except Exception as exc:
                logger.warning(
                    "Ingestion lease heartbeat stopped for run %s: %s",
                    run_id,
                    exc,
                )

    async def _maintain_lease(self, run_id: str) -> None:
        """Renew independently of slow upstream requests and batch completion."""
        while True:
            await asyncio.sleep(60)
            renewed = await asyncio.to_thread(
                self.repository.renew_lease, run_id, self.worker_id
            )
            if not renewed:
                raise IngestionStateConflict(
                    "ingestion lease heartbeat lost worker ownership"
                )

    @staticmethod
    async def _abort_staging(lake_writer, postgis_writer, run_id: str) -> None:
        for writer in (lake_writer, postgis_writer):
            if writer is None:
                continue
            try:
                await asyncio.to_thread(writer.abort)
            except Exception as exc:
                logger.warning(
                    "Failed to discard staging output for ingestion run %s: %s",
                    run_id,
                    exc,
                )


class IngestionWorker:
    """Embedded worker; the same class can run as a standalone process."""

    def __init__(
        self,
        repository: IngestionRepository | None = None,
        *,
        worker_id: str | None = None,
        poll_seconds: float = 2.0,
        schedule_driver: str | None = None,
    ) -> None:
        self.repository = repository
        self.worker_id = worker_id or (
            f"worker:ingestion:{socket.gethostname()}:{os.getpid()}"
        )
        self.poll_seconds = poll_seconds
        self.schedule_driver = (
            schedule_driver
            or os.environ.get("GDA_INGEST_SCHEDULE_DRIVER", "internal")
        ).strip().lower()
        if self.schedule_driver not in _SCHEDULE_DRIVERS:
            raise ValueError(
                "GDA_INGEST_SCHEDULE_DRIVER must be 'internal' or 'external'"
            )
        self._task: asyncio.Task | None = None
        self._wake = asyncio.Event()
        self._stopping = False

    def start(self) -> None:
        if self._task is not None and not self._task.done():
            self._wake.set()
            return
        self._stopping = False
        self._task = asyncio.create_task(self.run_forever(), name="arcgis-ingestion-worker")

    def wake(self) -> None:
        self._wake.set()

    async def stop(self) -> None:
        self._stopping = True
        self._wake.set()
        if self._task is not None:
            await self._task
            self._task = None

    async def run_once(self) -> bool:
        repository = self.repository or IngestionRepository()
        self.repository = repository
        if self.schedule_driver == "internal":
            await asyncio.to_thread(repository.enqueue_due_schedules)
        run = await asyncio.to_thread(repository.claim_next, self.worker_id)
        if run is None:
            return False
        await ArcGISIngestionExecutor(
            repository, worker_id=self.worker_id,
        ).execute(run)
        return True

    async def run_forever(self) -> None:
        while not self._stopping:
            try:
                worked = await self.run_once()
                if worked:
                    continue
            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Ingestion worker loop failed")
            self._wake.clear()
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=self.poll_seconds)
            except TimeoutError:
                pass


_worker: IngestionWorker | None = None


def get_ingestion_worker() -> IngestionWorker:
    global _worker
    if _worker is None:
        _worker = IngestionWorker()
    return _worker


def start_embedded_ingestion_worker() -> None:
    if os.environ.get("GDA_INGEST_EMBEDDED_WORKER", "1") != "0":
        get_ingestion_worker().start()


async def run_worker() -> None:
    worker = IngestionWorker()
    await worker.run_forever()


if __name__ == "__main__":
    asyncio.run(run_worker())
