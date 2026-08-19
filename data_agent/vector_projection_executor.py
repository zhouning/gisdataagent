"""Plan-bound pgvector projection execution.

This module is deliberately narrower than the existing semantic-vector
publisher.  A caller must register the exact target relation and submit rows
whose content fingerprint matches a sealed :class:`ProjectionRepairPlan`.
Arbitrary SQL, table names, and vector dimensions are never accepted from the
repair request.
"""

from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any, ClassVar
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.exc import DBAPIError, SQLAlchemyError

from .cross_store_projection_consistency import (
    ProjectionConsistencyError,
    ProjectionEngine,
    ProjectionRepairPlan,
    ProjectionTargetObservation,
)
from .platform_contracts import NonEmptyText, Sha256, TenantId, canonical_json_fingerprint


class VectorProjectionExecutionError(ProjectionConsistencyError):
    """A plan-bound pgvector action could not be safely completed."""


class VectorProjectionConfigurationError(VectorProjectionExecutionError):
    """The PostgreSQL/pgvector channel or registered target is unusable."""


class VectorProjectionValidationError(VectorProjectionExecutionError):
    """The plan, rows, or observed vector target is invalid."""


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class VectorProjectionTarget(_FrozenModel):
    """Explicit pgvector relation registration and fixed vector shape."""

    schema_id: ClassVar[str] = "gda.vector-projection-target.v1"
    tenant_id: TenantId
    projection_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{2,127}$")
    target_ref: NonEmptyText
    schema_name: str = Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]{0,62}$")
    table_name: str = Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]{0,62}$")
    embedding_dimension: int = Field(ge=1, le=8192)

    @model_validator(mode="after")
    def _target_is_canonical(self) -> VectorProjectionTarget:
        parsed = urlsplit(self.target_ref)
        if parsed.scheme != "vector" or not parsed.netloc:
            raise ValueError("target_ref must be vector://host/schema.table")
        if parsed.path != f"/{self.schema_name}.{self.table_name}":
            raise ValueError("target_ref does not match registered schema/table")
        if self.schema_name.lower() in {"pg_catalog", "information_schema", "gda_control"}:
            raise ValueError("system schemas cannot be registered as vector targets")
        if self.schema_name.lower().startswith("pg_"):
            raise ValueError("system schemas cannot be registered as vector targets")
        return self

    @property
    def identity(self) -> tuple[str, str, str]:
        return self.tenant_id, self.projection_id, self.target_ref


class VectorProjectionTargetRegistry:
    """Explicit immutable-by-convention target allowlist."""

    def __init__(self, targets: tuple[VectorProjectionTarget, ...] = ()) -> None:
        by_identity: dict[tuple[str, str, str], VectorProjectionTarget] = {}
        for target in targets:
            if target.identity in by_identity:
                raise VectorProjectionConfigurationError("duplicate vector target registration")
            by_identity[target.identity] = target
        self._targets = by_identity

    def register(self, target: VectorProjectionTarget) -> None:
        if target.identity in self._targets:
            raise VectorProjectionConfigurationError("duplicate vector target registration")
        self._targets[target.identity] = target

    def resolve(
        self, *, tenant_id: str, projection_id: str, target_ref: str
    ) -> VectorProjectionTarget:
        target = self._targets.get((tenant_id, projection_id, target_ref))
        if target is None:
            raise VectorProjectionValidationError("vector target is not explicitly registered")
        return target


class VectorProjectionRow(_FrozenModel):
    """Structured row accepted by the plan-bound vector executor."""

    record_id: NonEmptyText
    product_id: NonEmptyText
    collection: NonEmptyText
    content_text: str = Field(max_length=1_000_000)
    embedding: tuple[float, ...] = Field(min_length=1, max_length=8192)
    metadata: dict[str, Any] = Field(default_factory=dict)
    source_manifest: dict[str, Any] = Field(default_factory=dict)

    @field_validator("embedding")
    @classmethod
    def _finite_embedding(cls, value: tuple[float, ...]) -> tuple[float, ...]:
        if any(not math.isfinite(item) for item in value):
            raise ValueError("embedding values must be finite")
        return value


def _row_model(row: Mapping[str, Any] | VectorProjectionRow) -> VectorProjectionRow:
    if isinstance(row, VectorProjectionRow):
        return row
    try:
        return VectorProjectionRow.model_validate(row)
    except ValueError as exc:
        raise VectorProjectionValidationError("vector projection row is invalid") from exc


def vector_rows_fingerprint(
    target: VectorProjectionTarget,
    rows: tuple[Mapping[str, Any] | VectorProjectionRow, ...]
    | list[Mapping[str, Any] | VectorProjectionRow],
) -> str:
    """Return an order-independent content fingerprint for structured rows."""

    documents = []
    for row in rows:
        normalized = _row_model(row)
        if len(normalized.embedding) != target.embedding_dimension:
            raise VectorProjectionValidationError(
                "vector embedding dimension does not match registered target"
            )
        documents.append(normalized.model_dump(mode="json"))
    documents.sort(key=lambda item: item["record_id"])
    return canonical_json_fingerprint(
        {
            "schema": "gda.vector-target-content.v1",
            "embedding_dimension": target.embedding_dimension,
            "rows": documents,
        }
    )


class VectorProjectionRepairReceipt(_FrozenModel):
    """Provider commit evidence suitable for checkpoint construction."""

    schema_id: ClassVar[str] = "gda.vector-projection-repair-receipt.v1"
    status: str = Field(pattern=r"^(completed|replayed|checkpointed|deleted)$")
    tenant_id: TenantId
    projection_id: str
    target_ref: NonEmptyText
    action: str = Field(pattern=r"^(checkpoint|rebuild|delete)$")
    plan_sha256: Sha256
    idempotency_key: Sha256
    provider_commit_ref: dict[str, Any]
    target_exists: bool
    target_content_sha256: Sha256 | None = None
    target_row_count: int = Field(ge=0)
    observed_at: datetime

    @field_validator("observed_at")
    @classmethod
    def _utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("receipt timestamp must be timezone-aware")
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def _state(self) -> VectorProjectionRepairReceipt:
        if self.target_exists != (self.target_content_sha256 is not None):
            raise ValueError("receipt target content must match target existence")
        if not self.target_exists and self.target_row_count != 0:
            raise ValueError("deleted receipt must have zero rows")
        if self.provider_commit_ref.get("plan_sha256") != self.plan_sha256:
            raise ValueError("provider commit ref must bind plan_sha256")
        if self.provider_commit_ref.get("idempotency_key") != self.idempotency_key:
            raise ValueError("provider commit ref must bind idempotency key")
        return self


def vector_projection_receipt_fingerprint(
    *,
    tenant_id: str,
    projection_id: str,
    target_ref: str,
    action: str,
    plan_sha256: str,
    idempotency_key: str,
    provider_commit_ref: Mapping[str, Any],
    target_exists: bool,
    target_content_sha256: str | None,
    target_row_count: int,
) -> str:
    """Fingerprint stable pgvector evidence without its embedded hash."""

    commit_ref = dict(provider_commit_ref)
    commit_ref.pop("receipt_sha256", None)
    return canonical_json_fingerprint(
        {
            "schema": "gda.pgvector-projection-provider-receipt.v1",
            "tenant_id": tenant_id,
            "projection_id": projection_id,
            "target_ref": target_ref,
            "action": action,
            "plan_sha256": plan_sha256,
            "idempotency_key": idempotency_key,
            "provider_commit_ref": commit_ref,
            "target_exists": target_exists,
            "target_content_sha256": target_content_sha256,
            "target_row_count": target_row_count,
        }
    )


_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,62}$")


class VectorProjectionRepairExecutor:
    """Execute only sealed, explicitly registered pgvector repair plans."""

    def __init__(self, engine: Engine, registry: VectorProjectionTargetRegistry) -> None:
        if engine is None or engine.dialect.name != "postgresql":
            raise VectorProjectionConfigurationError(
                "vector projection execution requires PostgreSQL"
            )
        self.engine = engine
        self.registry = registry

    @staticmethod
    def _quote(value: str) -> str:
        if _IDENTIFIER_RE.fullmatch(value) is None:
            raise VectorProjectionValidationError("unsafe vector identifier")
        return f'"{value}"'

    @staticmethod
    def _json(value: Mapping[str, Any]) -> str:
        try:
            return json.dumps(
                value,
                allow_nan=False,
                ensure_ascii=True,
                sort_keys=True,
                separators=(",", ":"),
            )
        except (TypeError, ValueError) as exc:
            raise VectorProjectionValidationError(
                "vector row JSON metadata is not serializable"
            ) from exc

    def _relation(self, target: VectorProjectionTarget) -> str:
        return f"{self._quote(target.schema_name)}.{self._quote(target.table_name)}"

    @staticmethod
    def _set_tenant(connection: Any, tenant_id: str) -> None:
        connection.execute(
            text("SELECT set_config('app.current_tenant', :tenant_id, true)"),
            {"tenant_id": tenant_id},
        )

    @staticmethod
    def _receipt_query() -> Any:
        return text(
            """
            SELECT tenant_id, projection_id, target_ref, action, status,
                   checkpoint_version, plan_sha256, plan_idempotency_key,
                   provider_transaction_id, provider_commit_ref,
                   target_exists, target_content_sha256, target_row_count,
                   observed_at, receipt_sha256
            FROM gda_provider.pgvector_projection_repair_receipt
            WHERE tenant_id = :tenant_id
              AND plan_idempotency_key = :plan_idempotency_key
            """
        )

    def _receipt_from_row(
        self,
        row: Mapping[str, Any],
        plan: ProjectionRepairPlan,
    ) -> VectorProjectionRepairReceipt:
        commit_ref = row["provider_commit_ref"]
        if isinstance(commit_ref, str):
            commit_ref = json.loads(commit_ref)
        if not isinstance(commit_ref, dict):
            raise VectorProjectionValidationError(
                "stored pgvector provider receipt commit reference is invalid"
            )
        expected_sha256 = vector_projection_receipt_fingerprint(
            tenant_id=str(row["tenant_id"]),
            projection_id=str(row["projection_id"]),
            target_ref=str(row["target_ref"]),
            action=str(row["action"]),
            plan_sha256=str(row["plan_sha256"]),
            idempotency_key=str(row["plan_idempotency_key"]),
            provider_commit_ref=commit_ref,
            target_exists=bool(row["target_exists"]),
            target_content_sha256=row["target_content_sha256"],
            target_row_count=int(row["target_row_count"]),
        )
        if (
            str(row["tenant_id"]) != plan.tenant_id
            or str(row["projection_id"]) != plan.projection_id
            or str(row["target_ref"]) != plan.target_ref
            or str(row["action"]) != plan.action
            or int(row["checkpoint_version"]) != plan.next_checkpoint_version
            or str(row["plan_sha256"]) != plan.plan_sha256
            or str(row["plan_idempotency_key"]) != plan.plan_idempotency_key
            or str(row["provider_transaction_id"])
            != str(commit_ref.get("provider_transaction_id", ""))
            or str(row["receipt_sha256"]) != expected_sha256
            or commit_ref.get("receipt_sha256") != expected_sha256
        ):
            raise VectorProjectionValidationError(
                "stored pgvector provider receipt is not bound to the sealed plan"
            )
        return VectorProjectionRepairReceipt(
            status=str(row["status"]),
            tenant_id=plan.tenant_id,
            projection_id=plan.projection_id,
            target_ref=plan.target_ref,
            action=plan.action,
            plan_sha256=plan.plan_sha256,
            idempotency_key=plan.plan_idempotency_key,
            provider_commit_ref=commit_ref,
            target_exists=bool(row["target_exists"]),
            target_content_sha256=row["target_content_sha256"],
            target_row_count=int(row["target_row_count"]),
            observed_at=row["observed_at"],
        )

    def _stored_receipt(
        self,
        connection: Any,
        plan: ProjectionRepairPlan,
    ) -> VectorProjectionRepairReceipt | None:
        row = (
            connection.execute(
                self._receipt_query(),
                {
                    "tenant_id": plan.tenant_id,
                    "plan_idempotency_key": plan.plan_idempotency_key,
                },
            )
            .mappings()
            .one_or_none()
        )
        return None if row is None else self._receipt_from_row(row, plan)

    @staticmethod
    def _assert_receipt_matches_target(
        receipt: VectorProjectionRepairReceipt,
        observation: ProjectionTargetObservation,
        plan: ProjectionRepairPlan,
    ) -> None:
        desired = plan.desired_state
        if (
            receipt.target_exists != desired.target_exists
            or receipt.target_content_sha256 != desired.expected_target_content_sha256
            or receipt.target_row_count != desired.expected_row_count
            or observation.target_exists != receipt.target_exists
            or observation.observed_content_sha256 != receipt.target_content_sha256
            or observation.observed_row_count != receipt.target_row_count
        ):
            raise VectorProjectionValidationError(
                "stored pgvector provider receipt does not match the current target"
            )

    def recover_receipt(
        self,
        plan: ProjectionRepairPlan,
    ) -> VectorProjectionRepairReceipt | None:
        """Read exact same-transaction vector evidence without a target mutation."""

        target = self.registry.resolve(
            tenant_id=plan.tenant_id,
            projection_id=plan.projection_id,
            target_ref=plan.target_ref,
        )
        self._assert_plan(plan, target)
        try:
            with self.engine.begin() as connection:
                self._set_tenant(connection, plan.tenant_id)
                receipt = self._stored_receipt(connection, plan)
                if receipt is None:
                    return None
                observation = self.observe(target, connection=connection)
                self._assert_receipt_matches_target(receipt, observation, plan)
                return receipt
        except VectorProjectionExecutionError:
            raise
        except DBAPIError as exc:
            raise VectorProjectionExecutionError(
                "pgvector provider receipt recovery failed"
            ) from exc
        except SQLAlchemyError as exc:
            raise VectorProjectionConfigurationError(
                "pgvector provider receipt channel is unavailable"
            ) from exc

    def _stage_name(self, target: VectorProjectionTarget, plan: ProjectionRepairPlan) -> str:
        return f"__gda_vec_stage_{target.table_name[:31]}_{plan.plan_idempotency_key[:16]}"[:63]

    def _backup_name(self, target: VectorProjectionTarget, plan: ProjectionRepairPlan) -> str:
        return f"__gda_vec_old_{target.table_name[:31]}_{plan.plan_idempotency_key[:16]}"[:63]

    def _relation_kind_exists(self, connection: Any, target: VectorProjectionTarget) -> bool:
        return bool(
            connection.execute(
                text(
                    """
                    SELECT EXISTS (
                        SELECT 1 FROM pg_class c
                        JOIN pg_namespace n ON n.oid = c.relnamespace
                        WHERE n.nspname = :schema AND c.relname = :table
                    )
                    """
                ),
                {"schema": target.schema_name, "table": target.table_name},
            ).scalar_one()
        )

    def _table_exists(self, connection: Any, target: VectorProjectionTarget) -> bool:
        return bool(
            connection.execute(
                text(
                    """
                    SELECT EXISTS (
                        SELECT 1 FROM pg_class c
                        JOIN pg_namespace n ON n.oid = c.relnamespace
                        WHERE n.nspname = :schema AND c.relname = :table AND c.relkind = 'r'
                    )
                    """
                ),
                {"schema": target.schema_name, "table": target.table_name},
            ).scalar_one()
        )

    def _select_sql(self, target: VectorProjectionTarget) -> str:
        return (
            f"SELECT {self._quote('record_id')}, {self._quote('product_id')}, "
            f"{self._quote('collection')}, {self._quote('content_text')}, "
            f"{self._quote('embedding')}::text AS {self._quote('embedding_text')}, "
            f"{self._quote('metadata')}, {self._quote('source_manifest')} "
            f"FROM {self._relation(target)} ORDER BY {self._quote('record_id')}"
        )

    @staticmethod
    def _parse_embedding(value: Any) -> list[float]:
        try:
            parsed = json.loads(str(value))
            if not isinstance(parsed, list):
                raise ValueError
            values = [float(item) for item in parsed]
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise VectorProjectionValidationError("stored pgvector embedding is invalid") from exc
        if not values or any(not math.isfinite(item) for item in values):
            raise VectorProjectionValidationError("stored pgvector embedding is invalid")
        return values

    def observe(
        self,
        target: VectorProjectionTarget,
        *,
        connection: Any | None = None,
    ) -> ProjectionTargetObservation:
        owns_connection = connection is None
        connection_context = None
        if owns_connection:
            connection_context = self.engine.connect()
            connection = connection_context.__enter__()
        try:
            exists = self._relation_kind_exists(connection, target)
            if not exists:
                return ProjectionTargetObservation(
                    tenant_id=target.tenant_id,
                    projection_id=target.projection_id,
                    target_engine=ProjectionEngine.VECTOR,
                    target_ref=target.target_ref,
                    target_exists=False,
                    observed_content_sha256=None,
                    observed_row_count=0,
                    observed_by="workload:vector-projection-executor",
                    observed_at=datetime.now(UTC),
                )
            if not self._table_exists(connection, target):
                raise VectorProjectionValidationError(
                    "registered vector target exists but is not a table"
                )
            rows = connection.execute(text(self._select_sql(target))).mappings().all()
            documents: list[dict[str, Any]] = []
            for row in rows:
                embedding = self._parse_embedding(row["embedding_text"])
                if len(embedding) != target.embedding_dimension:
                    raise VectorProjectionValidationError(
                        "stored vector dimension differs from registered target"
                    )
                metadata = row["metadata"]
                source_manifest = row["source_manifest"]
                if isinstance(metadata, str):
                    metadata = json.loads(metadata)
                if isinstance(source_manifest, str):
                    source_manifest = json.loads(source_manifest)
                documents.append(
                    _row_model(
                        {
                            "record_id": row["record_id"],
                            "product_id": row["product_id"],
                            "collection": row["collection"],
                            "content_text": row["content_text"],
                            "embedding": tuple(embedding),
                            "metadata": metadata or {},
                            "source_manifest": source_manifest or {},
                        }
                    ).model_dump(mode="json")
                )
            return ProjectionTargetObservation(
                tenant_id=target.tenant_id,
                projection_id=target.projection_id,
                target_engine=ProjectionEngine.VECTOR,
                target_ref=target.target_ref,
                target_exists=True,
                observed_content_sha256=vector_rows_fingerprint(target, documents),
                observed_row_count=len(documents),
                observed_by="workload:vector-projection-executor",
                observed_at=datetime.now(UTC),
            )
        finally:
            if owns_connection and connection_context is not None:
                connection_context.__exit__(None, None, None)

    def _assert_observation(
        self,
        plan: ProjectionRepairPlan,
        current: ProjectionTargetObservation,
    ) -> None:
        expected = plan.observation
        if (
            current.target_exists != expected.target_exists
            or current.observed_content_sha256 != expected.observed_content_sha256
            or current.observed_row_count != expected.observed_row_count
        ):
            raise VectorProjectionValidationError(
                "vector target changed after the repair plan was sealed"
            )

    def _assert_plan(self, plan: ProjectionRepairPlan, target: VectorProjectionTarget) -> None:
        if plan.target_engine is not ProjectionEngine.VECTOR:
            raise VectorProjectionValidationError("vector executor only accepts vector plans")
        if (
            plan.tenant_id != target.tenant_id
            or plan.projection_id != target.projection_id
            or plan.target_ref != target.target_ref
        ):
            raise VectorProjectionValidationError(
                "repair plan target identity does not match registered vector target"
            )
        if plan.action == "fail_closed":
            raise VectorProjectionValidationError("fail-closed repair plans cannot be executed")

    def _create_table_sql(self, target: VectorProjectionTarget, table_name: str) -> str:
        return f"""
            CREATE TABLE {self._quote(target.schema_name)}.{self._quote(table_name)} (
                {self._quote("record_id")} TEXT PRIMARY KEY,
                {self._quote("product_id")} TEXT NOT NULL,
                {self._quote("collection")} TEXT NOT NULL,
                {self._quote("content_text")} TEXT NOT NULL,
                {self._quote("embedding")} VECTOR({target.embedding_dimension}) NOT NULL,
                {self._quote("metadata")} JSONB NOT NULL DEFAULT '{{}}'::jsonb,
                {self._quote("source_manifest")} JSONB NOT NULL DEFAULT '{{}}'::jsonb,
                {self._quote("created_at")} TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                {self._quote("updated_at")} TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
        """

    def _insert_sql(self, target: VectorProjectionTarget, stage: str) -> str:
        return f"""
            INSERT INTO {self._quote(target.schema_name)}.{self._quote(stage)}
                (record_id, product_id, collection, content_text, embedding,
                 metadata, source_manifest)
            VALUES
                (:record_id, :product_id, :collection, :content_text,
                 CAST(:embedding AS vector), CAST(:metadata AS jsonb),
                 CAST(:source_manifest AS jsonb))
        """

    def _row_parameters(self, row: Mapping[str, Any] | VectorProjectionRow) -> dict[str, Any]:
        normalized = _row_model(row)
        return {
            "record_id": normalized.record_id,
            "product_id": normalized.product_id,
            "collection": normalized.collection,
            "content_text": normalized.content_text,
            "embedding": "[" + ",".join(str(float(value)) for value in normalized.embedding) + "]",
            "metadata": self._json(normalized.metadata),
            "source_manifest": self._json(normalized.source_manifest),
        }

    def execute(
        self,
        plan: ProjectionRepairPlan,
        *,
        rows: tuple[Mapping[str, Any] | VectorProjectionRow, ...]
        | list[Mapping[str, Any] | VectorProjectionRow] = (),
        observed_at: datetime | None = None,
    ) -> VectorProjectionRepairReceipt:
        target = self.registry.resolve(
            tenant_id=plan.tenant_id,
            projection_id=plan.projection_id,
            target_ref=plan.target_ref,
        )
        self._assert_plan(plan, target)
        if plan.action in {"delete", "checkpoint"} and rows:
            raise VectorProjectionValidationError(f"{plan.action} plans must not carry vector rows")
        if plan.action == "rebuild":
            expected_hash = plan.desired_state.expected_target_content_sha256
            actual_hash = vector_rows_fingerprint(target, rows)
            if actual_hash != expected_hash or len(rows) != plan.desired_state.expected_row_count:
                raise VectorProjectionValidationError(
                    "rebuild rows do not match desired vector target content"
                )
        now = observed_at or datetime.now(UTC)
        if now.tzinfo is None or now.utcoffset() is None:
            raise VectorProjectionValidationError("observed_at must be timezone-aware")
        now = now.astimezone(UTC)
        status = "completed"
        try:
            with self.engine.begin() as connection:
                self._set_tenant(connection, plan.tenant_id)
                vector_available = bool(
                    connection.execute(
                        text("SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'vector')")
                    ).scalar_one()
                )
                if not vector_available:
                    raise VectorProjectionConfigurationError(
                        "pgvector extension must be installed by deployment"
                    )
                stored_receipt = self._stored_receipt(connection, plan)
                if stored_receipt is not None:
                    stored_observation = self.observe(target, connection=connection)
                    self._assert_receipt_matches_target(
                        stored_receipt,
                        stored_observation,
                        plan,
                    )
                    return stored_receipt.model_copy(update={"status": "replayed"})
                current = self.observe(target, connection=connection)
                desired = plan.desired_state
                already_desired = (
                    current.target_exists == desired.target_exists
                    and current.observed_content_sha256 == desired.expected_target_content_sha256
                    and current.observed_row_count == desired.expected_row_count
                )
                if already_desired:
                    status = "replayed"
                    post = current
                else:
                    self._assert_observation(plan, current)
                    post = None
                if plan.action == "checkpoint":
                    if not already_desired:
                        raise VectorProjectionValidationError(
                            "checkpoint target does not match desired vector state"
                        )
                    status = "checkpointed"
                elif already_desired:
                    pass
                elif plan.action == "delete":
                    if not self._table_exists(connection, target):
                        raise VectorProjectionValidationError("delete plan target is not a table")
                    connection.execute(text(f"DROP TABLE {self._relation(target)}"))
                    status = "deleted"
                else:
                    stage = self._stage_name(target, plan)
                    backup = self._backup_name(target, plan)
                    connection.execute(
                        text(
                            f"DROP TABLE IF EXISTS {self._quote(target.schema_name)}."
                            f"{self._quote(stage)}"
                        )
                    )
                    connection.execute(text(self._create_table_sql(target, stage)))
                    insert = text(self._insert_sql(target, stage))
                    for row in rows:
                        connection.execute(insert, self._row_parameters(row))
                    if self._relation_kind_exists(connection, target):
                        if not self._table_exists(connection, target):
                            raise VectorProjectionValidationError(
                                "registered vector target exists but is not a table"
                            )
                        connection.execute(
                            text(
                                f"DROP TABLE IF EXISTS {self._quote(target.schema_name)}."
                                f"{self._quote(backup)}"
                            )
                        )
                        connection.execute(
                            text(
                                f"ALTER TABLE {self._relation(target)} RENAME TO "
                                f"{self._quote(backup)}"
                            )
                        )
                    connection.execute(
                        text(
                            f"ALTER TABLE {self._quote(target.schema_name)}.{self._quote(stage)} "
                            f"RENAME TO {self._quote(target.table_name)}"
                        )
                    )
                    connection.execute(
                        text(
                            f"DROP TABLE IF EXISTS {self._quote(target.schema_name)}."
                            f"{self._quote(backup)}"
                        )
                    )
                    status = "completed"
                if post is None:
                    post = self.observe(target, connection=connection)
                if (
                    post.target_exists != desired.target_exists
                    or post.observed_content_sha256 != desired.expected_target_content_sha256
                    or post.observed_row_count != desired.expected_row_count
                ):
                    raise VectorProjectionExecutionError(
                        "vector post-repair observation does not match desired state"
                    )
                provider_transaction_id = str(
                    connection.execute(text("SELECT pg_current_xact_id()::text")).scalar_one()
                )
                commit_ref = {
                    "provider": "pgvector",
                    "provider_commit": (
                        f"{target.schema_name}.{target.table_name}:{plan.next_checkpoint_version}"
                    ),
                    "provider_transaction_id": provider_transaction_id,
                    "plan_sha256": plan.plan_sha256,
                    "idempotency_key": plan.plan_idempotency_key,
                }
                receipt_sha256 = vector_projection_receipt_fingerprint(
                    tenant_id=plan.tenant_id,
                    projection_id=plan.projection_id,
                    target_ref=plan.target_ref,
                    action=plan.action,
                    plan_sha256=plan.plan_sha256,
                    idempotency_key=plan.plan_idempotency_key,
                    provider_commit_ref=commit_ref,
                    target_exists=post.target_exists,
                    target_content_sha256=post.observed_content_sha256,
                    target_row_count=post.observed_row_count,
                )
                commit_ref["receipt_sha256"] = receipt_sha256
                receipt = VectorProjectionRepairReceipt(
                    status=status,
                    tenant_id=plan.tenant_id,
                    projection_id=plan.projection_id,
                    target_ref=plan.target_ref,
                    action=plan.action,
                    plan_sha256=plan.plan_sha256,
                    idempotency_key=plan.plan_idempotency_key,
                    provider_commit_ref=commit_ref,
                    target_exists=post.target_exists,
                    target_content_sha256=post.observed_content_sha256,
                    target_row_count=post.observed_row_count,
                    observed_at=now,
                )
                connection.execute(
                    text(
                        """
                        INSERT INTO gda_provider.pgvector_projection_repair_receipt (
                            tenant_id, projection_id, target_ref, action, status,
                            checkpoint_version, plan_sha256, plan_idempotency_key,
                            provider_transaction_id, provider_commit_ref,
                            target_exists, target_content_sha256, target_row_count,
                            observed_at, receipt_sha256
                        ) VALUES (
                            :tenant_id, :projection_id, :target_ref, :action, :status,
                            :checkpoint_version, :plan_sha256, :plan_idempotency_key,
                            :provider_transaction_id, CAST(:provider_commit_ref AS jsonb),
                            :target_exists, :target_content_sha256, :target_row_count,
                            :observed_at, :receipt_sha256
                        )
                        """
                    ),
                    {
                        "tenant_id": plan.tenant_id,
                        "projection_id": plan.projection_id,
                        "target_ref": plan.target_ref,
                        "action": plan.action,
                        "status": status,
                        "checkpoint_version": plan.next_checkpoint_version,
                        "plan_sha256": plan.plan_sha256,
                        "plan_idempotency_key": plan.plan_idempotency_key,
                        "provider_transaction_id": provider_transaction_id,
                        "provider_commit_ref": json.dumps(
                            commit_ref,
                            ensure_ascii=True,
                            sort_keys=True,
                            separators=(",", ":"),
                        ),
                        "target_exists": post.target_exists,
                        "target_content_sha256": post.observed_content_sha256,
                        "target_row_count": post.observed_row_count,
                        "observed_at": now,
                        "receipt_sha256": receipt_sha256,
                    },
                )
        except VectorProjectionExecutionError:
            raise
        except DBAPIError as exc:
            raise VectorProjectionExecutionError("vector repair transaction failed") from exc
        except SQLAlchemyError as exc:
            raise VectorProjectionConfigurationError(
                "vector repair channel is unavailable"
            ) from exc
        return receipt


__all__ = [
    "VectorProjectionConfigurationError",
    "VectorProjectionExecutionError",
    "VectorProjectionRepairExecutor",
    "VectorProjectionRepairReceipt",
    "VectorProjectionRow",
    "VectorProjectionTarget",
    "VectorProjectionTargetRegistry",
    "VectorProjectionValidationError",
    "vector_projection_receipt_fingerprint",
    "vector_rows_fingerprint",
]
