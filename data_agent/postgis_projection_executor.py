"""Plan-bound PostGIS projection repair execution.

The executor is intentionally narrower than a general SQL/data-loading API. A
caller must register the exact tenant/projection/target relation and provide
structured rows for a sealed :class:`ProjectionRepairPlan`. SQL is generated
only from the registered column specification; arbitrary SQL is never accepted.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import StrEnum
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
from .platform_contracts import (
    NonEmptyText,
    Sha256,
    TenantId,
    canonical_json_fingerprint,
)


class PostGISProjectionExecutionError(ProjectionConsistencyError):
    """A plan-bound PostGIS action could not be safely completed."""


class PostGISProjectionConfigurationError(PostGISProjectionExecutionError):
    """The engine or registered target is not usable."""


class PostGISProjectionValidationError(PostGISProjectionExecutionError):
    """The plan, rows, or observed target state is invalid."""


class PostGISColumnKind(StrEnum):
    TEXT = "text"
    INTEGER = "integer"
    BIGINT = "bigint"
    DOUBLE = "double_precision"
    BOOLEAN = "boolean"
    JSONB = "jsonb"
    DATE = "date"
    TIMESTAMPTZ = "timestamptz"
    GEOMETRY = "geometry"


_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,62}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_FORBIDDEN_SCHEMAS = frozenset({"pg_catalog", "information_schema", "gda_control"})


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class PostGISColumnSpec(_FrozenModel):
    """Allowlisted physical column definition used to generate DDL/DML."""

    name: str = Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]{0,62}$")
    kind: PostGISColumnKind
    nullable: bool = True
    geometry_srid: int | None = Field(default=None, ge=1, le=998_999)

    @model_validator(mode="after")
    def _geometry_srid(self) -> PostGISColumnSpec:
        if self.kind is PostGISColumnKind.GEOMETRY and self.geometry_srid is None:
            raise ValueError("geometry column requires geometry_srid")
        if self.kind is not PostGISColumnKind.GEOMETRY and self.geometry_srid is not None:
            raise ValueError("geometry_srid is only valid for geometry columns")
        return self


class PostGISProjectionTarget(_FrozenModel):
    """An explicitly registered PostGIS relation and its safe write shape."""

    schema_id: ClassVar[str] = "gda.postgis-projection-target.v1"
    tenant_id: TenantId
    projection_id: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{2,127}$")
    target_ref: NonEmptyText
    schema_name: str = Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]{0,62}$")
    table_name: str = Field(pattern=r"^[A-Za-z_][A-Za-z0-9_]{0,62}$")
    columns: tuple[PostGISColumnSpec, ...] = Field(min_length=1)
    order_by: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def _target_is_canonical(self) -> PostGISProjectionTarget:
        if self.schema_name.lower() in _FORBIDDEN_SCHEMAS or self.schema_name.lower().startswith(
            "pg_"
        ):
            raise ValueError("system schemas cannot be registered as projection targets")
        names = tuple(column.name for column in self.columns)
        if len(names) != len(set(names)):
            raise ValueError("target column names must be unique")
        if len(self.order_by) != len(set(self.order_by)) or any(
            item not in names for item in self.order_by
        ):
            raise ValueError("order_by must contain unique registered columns")
        if any(column.name in self.order_by and column.nullable for column in self.columns):
            raise ValueError("order_by columns must be non-nullable")
        parsed = urlsplit(self.target_ref)
        expected_path = f"/{self.schema_name}.{self.table_name}"
        if parsed.scheme != "postgis" or not parsed.netloc or parsed.path != expected_path:
            raise ValueError(
                "target_ref must be postgis://host/schema.table for the registered target"
            )
        return self

    @property
    def identity(self) -> tuple[str, str, str]:
        return self.tenant_id, self.projection_id, self.target_ref

    @property
    def column_map(self) -> dict[str, PostGISColumnSpec]:
        return {column.name: column for column in self.columns}


class PostGISProjectionTargetRegistry:
    """Small explicit allowlist; registrations are immutable after creation."""

    def __init__(self, targets: tuple[PostGISProjectionTarget, ...] = ()) -> None:
        by_identity: dict[tuple[str, str, str], PostGISProjectionTarget] = {}
        for target in targets:
            if target.identity in by_identity:
                raise PostGISProjectionConfigurationError("duplicate PostGIS target registration")
            by_identity[target.identity] = target
        self._targets = by_identity

    def register(self, target: PostGISProjectionTarget) -> None:
        if target.identity in self._targets:
            raise PostGISProjectionConfigurationError("duplicate PostGIS target registration")
        self._targets[target.identity] = target

    def resolve(
        self, *, tenant_id: str, projection_id: str, target_ref: str
    ) -> PostGISProjectionTarget:
        target = self._targets.get((tenant_id, projection_id, target_ref))
        if target is None:
            raise PostGISProjectionValidationError("PostGIS target is not explicitly registered")
        return target


def _canonical_scalar(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, bool, float)):
        return value
    if isinstance(value, (datetime, date)):
        return (
            value.astimezone(UTC).isoformat().replace("+00:00", "Z")
            if isinstance(value, datetime)
            else value.isoformat()
        )
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, bytes):
        return {"bytes_hex": value.hex()}
    if isinstance(value, Mapping):
        return {
            str(key): _canonical_scalar(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (list, tuple)):
        return [_canonical_scalar(item) for item in value]
    return str(value)


def _canonical_geometry(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, str):
        normalized = " ".join(value.strip().split())
        normalized = normalized.replace(" (", "(").replace("( ", "(").replace(" )", ")")
        normalized = normalized.replace(", ", ",")
        return {"wkt": normalized}
    if isinstance(value, bytes):
        raise PostGISProjectionValidationError("geometry bytes are not accepted by the WKT writer")
    raise PostGISProjectionValidationError("geometry values must be WKT text")


def projection_rows_fingerprint(
    target: PostGISProjectionTarget,
    rows: tuple[Mapping[str, Any], ...] | list[Mapping[str, Any]],
) -> str:
    """Fingerprint the structured row contract used by the executor."""

    names = tuple(column.name for column in target.columns)
    documents = []
    for row in rows:
        if set(row) != set(names):
            raise PostGISProjectionValidationError(
                "projection row columns do not match target registration"
            )
        document = {
            name: (
                _canonical_geometry(row[name])
                if target.column_map[name].kind is PostGISColumnKind.GEOMETRY
                else _canonical_scalar(row[name])
            )
            for name in names
        }
        documents.append(document)
    documents.sort(key=lambda item: tuple(repr(item[name]) for name in target.order_by))
    return canonical_json_fingerprint(
        {
            "schema": "gda.postgis-target-content.v1",
            "columns": [column.model_dump(mode="json") for column in target.columns],
            "order_by": list(target.order_by),
            "rows": documents,
        }
    )


class PostGISProjectionRepairReceipt(_FrozenModel):
    """Provider commit evidence suitable for ``build_projection_checkpoint_from_repair``."""

    schema_id: ClassVar[str] = "gda.postgis-projection-repair-receipt.v1"
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
    def _state(self) -> PostGISProjectionRepairReceipt:
        if self.target_exists != (self.target_content_sha256 is not None):
            raise ValueError("receipt target content must match target existence")
        if not self.target_exists and self.target_row_count != 0:
            raise ValueError("deleted receipt must have zero rows")
        if self.provider_commit_ref.get("plan_sha256") != self.plan_sha256:
            raise ValueError("provider commit ref must bind plan_sha256")
        if self.provider_commit_ref.get("idempotency_key") != self.idempotency_key:
            raise ValueError("provider commit ref must bind idempotency key")
        return self


def postgis_projection_receipt_fingerprint(
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
    """Fingerprint stable provider evidence without its self-referential hash."""

    commit_ref = dict(provider_commit_ref)
    commit_ref.pop("receipt_sha256", None)
    return canonical_json_fingerprint(
        {
            "schema": "gda.postgis-projection-provider-receipt.v1",
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


class PostGISProjectionRepairExecutor:
    """Execute only sealed, registered PostGIS projection repair plans."""

    def __init__(self, engine: Engine, registry: PostGISProjectionTargetRegistry) -> None:
        if engine is None or engine.dialect.name != "postgresql":
            raise PostGISProjectionConfigurationError(
                "PostGIS projection execution requires PostgreSQL"
            )
        self.engine = engine
        self.registry = registry

    @staticmethod
    def _quote(value: str) -> str:
        if _IDENTIFIER_RE.fullmatch(value) is None:
            raise PostGISProjectionValidationError("unsafe PostGIS identifier")
        return '"' + value.replace('"', '""') + '"'

    def _relation(self, target: PostGISProjectionTarget) -> str:
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
            FROM gda_provider.postgis_projection_repair_receipt
            WHERE tenant_id = :tenant_id
              AND plan_idempotency_key = :plan_idempotency_key
            """
        )

    def _receipt_from_row(
        self,
        row: Mapping[str, Any],
        plan: ProjectionRepairPlan,
    ) -> PostGISProjectionRepairReceipt:
        commit_ref = row["provider_commit_ref"]
        if isinstance(commit_ref, str):
            commit_ref = json.loads(commit_ref)
        if not isinstance(commit_ref, dict):
            raise PostGISProjectionValidationError(
                "stored PostGIS provider receipt commit reference is invalid"
            )
        expected_sha256 = postgis_projection_receipt_fingerprint(
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
            raise PostGISProjectionValidationError(
                "stored PostGIS provider receipt is not bound to the sealed plan"
            )
        return PostGISProjectionRepairReceipt(
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
    ) -> PostGISProjectionRepairReceipt | None:
        row = connection.execute(
            self._receipt_query(),
            {
                "tenant_id": plan.tenant_id,
                "plan_idempotency_key": plan.plan_idempotency_key,
            },
        ).mappings().one_or_none()
        return None if row is None else self._receipt_from_row(row, plan)

    @staticmethod
    def _assert_receipt_matches_target(
        receipt: PostGISProjectionRepairReceipt,
        observation: ProjectionTargetObservation,
        plan: ProjectionRepairPlan,
    ) -> None:
        desired = plan.desired_state
        if (
            receipt.target_exists != desired.target_exists
            or receipt.target_content_sha256
            != desired.expected_target_content_sha256
            or receipt.target_row_count != desired.expected_row_count
            or observation.target_exists != receipt.target_exists
            or observation.observed_content_sha256 != receipt.target_content_sha256
            or observation.observed_row_count != receipt.target_row_count
        ):
            raise PostGISProjectionValidationError(
                "stored PostGIS provider receipt does not match the current target"
            )

    def recover_receipt(
        self,
        plan: ProjectionRepairPlan,
    ) -> PostGISProjectionRepairReceipt | None:
        """Read exact same-transaction commit evidence without mutating the target."""

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
        except PostGISProjectionExecutionError:
            raise
        except DBAPIError as exc:
            raise PostGISProjectionExecutionError(
                "PostGIS provider receipt recovery failed"
            ) from exc
        except SQLAlchemyError as exc:
            raise PostGISProjectionConfigurationError(
                "PostGIS provider receipt channel is unavailable"
            ) from exc

    def _stage_name(self, target: PostGISProjectionTarget, plan: ProjectionRepairPlan) -> str:
        suffix = plan.plan_idempotency_key[:16]
        value = f"__gda_stage_{target.table_name[:38]}_{suffix}"
        return value[:63]

    def _backup_name(self, target: PostGISProjectionTarget, plan: ProjectionRepairPlan) -> str:
        value = f"__gda_old_{target.table_name[:38]}_{plan.plan_idempotency_key[:16]}"
        return value[:63]

    def _table_exists(self, connection: Any, target: PostGISProjectionTarget) -> bool:
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

    def _relation_kind_exists(self, connection: Any, target: PostGISProjectionTarget) -> bool:
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

    def _select_sql(self, target: PostGISProjectionTarget) -> str:
        expressions = []
        for column in target.columns:
            quoted = self._quote(column.name)
            if column.kind is PostGISColumnKind.GEOMETRY:
                expressions.append(f"ST_AsText({quoted}) AS {quoted}")
            else:
                expressions.append(quoted)
        order = ", ".join(self._quote(name) for name in target.order_by)
        return f"SELECT {', '.join(expressions)} FROM {self._relation(target)} ORDER BY {order}"

    def observe(
        self, target: PostGISProjectionTarget, *, connection: Any | None = None
    ) -> ProjectionTargetObservation:
        owns_connection = connection is None
        if owns_connection:
            connection_context = self.engine.connect()
            connection = connection_context.__enter__()
        try:
            exists = self._relation_kind_exists(connection, target)
            if not exists:
                return ProjectionTargetObservation(
                    tenant_id=target.tenant_id,
                    projection_id=target.projection_id,
                    target_engine=ProjectionEngine.POSTGIS,
                    target_ref=target.target_ref,
                    target_exists=False,
                    observed_content_sha256=None,
                    observed_row_count=0,
                    observed_by="workload:postgis-projection-executor",
                    observed_at=datetime.now(UTC),
                )
            if not self._table_exists(connection, target):
                raise PostGISProjectionValidationError(
                    "registered PostGIS target exists but is not a table"
                )
            rows = connection.execute(text(self._select_sql(target))).mappings().all()
            documents = []
            for row in rows:
                document = {}
                for column in target.columns:
                    value = row[column.name]
                    if column.kind is PostGISColumnKind.GEOMETRY and value is not None:
                        value = str(value)
                    document[column.name] = value
                documents.append(document)
            return ProjectionTargetObservation(
                tenant_id=target.tenant_id,
                projection_id=target.projection_id,
                target_engine=ProjectionEngine.POSTGIS,
                target_ref=target.target_ref,
                target_exists=True,
                observed_content_sha256=projection_rows_fingerprint(target, documents),
                observed_row_count=len(documents),
                observed_by="workload:postgis-projection-executor",
                observed_at=datetime.now(UTC),
            )
        finally:
            if owns_connection:
                connection_context.__exit__(None, None, None)

    def _assert_observation(
        self, plan: ProjectionRepairPlan, current: ProjectionTargetObservation
    ) -> None:
        expected = plan.observation
        if (
            current.target_exists != expected.target_exists
            or current.observed_content_sha256 != expected.observed_content_sha256
            or current.observed_row_count != expected.observed_row_count
        ):
            raise PostGISProjectionValidationError(
                "PostGIS target changed after the repair plan was sealed"
            )

    def _column_sql(self, column: PostGISColumnSpec) -> str:
        name = self._quote(column.name)
        nullable = "" if column.nullable else " NOT NULL"
        types = {
            PostGISColumnKind.TEXT: "TEXT",
            PostGISColumnKind.INTEGER: "INTEGER",
            PostGISColumnKind.BIGINT: "BIGINT",
            PostGISColumnKind.DOUBLE: "DOUBLE PRECISION",
            PostGISColumnKind.BOOLEAN: "BOOLEAN",
            PostGISColumnKind.JSONB: "JSONB",
            PostGISColumnKind.DATE: "DATE",
            PostGISColumnKind.TIMESTAMPTZ: "TIMESTAMPTZ",
        }
        if column.kind is PostGISColumnKind.GEOMETRY:
            return f"{name} geometry(Geometry, {column.geometry_srid}){nullable}"
        return f"{name} {types[column.kind]}{nullable}"

    def _insert_sql(self, target: PostGISProjectionTarget, stage: str) -> str:
        names = [self._quote(column.name) for column in target.columns]
        values = []
        for column in target.columns:
            placeholder = f":v_{column.name}"
            if column.kind is PostGISColumnKind.GEOMETRY:
                values.append(f"ST_GeomFromText({placeholder}, {column.geometry_srid})")
            else:
                values.append(placeholder)
        return (
            f"INSERT INTO {self._quote(target.schema_name)}.{self._quote(stage)} "
            f"({', '.join(names)}) VALUES ({', '.join(values)})"
        )

    def _row_parameters(
        self, target: PostGISProjectionTarget, row: Mapping[str, Any]
    ) -> dict[str, Any]:
        names = tuple(column.name for column in target.columns)
        if set(row) != set(names):
            raise PostGISProjectionValidationError(
                "projection row columns do not match target registration"
            )
        params: dict[str, Any] = {}
        for column in target.columns:
            value = row[column.name]
            if value is None and not column.nullable:
                raise PostGISProjectionValidationError(
                    f"non-nullable column {column.name!r} received NULL"
                )
            if column.kind is PostGISColumnKind.GEOMETRY and not (
                value is None or isinstance(value, str)
            ):
                raise PostGISProjectionValidationError("geometry input must be WKT text")
            params[f"v_{column.name}"] = value
        return params

    def _assert_plan(self, plan: ProjectionRepairPlan, target: PostGISProjectionTarget) -> None:
        if plan.target_engine is not ProjectionEngine.POSTGIS:
            raise PostGISProjectionValidationError("PostGIS executor only accepts postgis plans")
        if (
            plan.tenant_id != target.tenant_id
            or plan.projection_id != target.projection_id
            or plan.target_ref != target.target_ref
        ):
            raise PostGISProjectionValidationError(
                "repair plan target identity does not match registered PostGIS target"
            )
        if plan.action == "fail_closed":
            raise PostGISProjectionValidationError("fail-closed repair plans cannot be executed")

    def execute(
        self,
        plan: ProjectionRepairPlan,
        *,
        rows: tuple[Mapping[str, Any], ...] | list[Mapping[str, Any]] = (),
        observed_at: datetime | None = None,
    ) -> PostGISProjectionRepairReceipt:
        target = self.registry.resolve(
            tenant_id=plan.tenant_id,
            projection_id=plan.projection_id,
            target_ref=plan.target_ref,
        )
        self._assert_plan(plan, target)
        if plan.action in {"delete", "checkpoint"} and rows:
            raise PostGISProjectionValidationError(
                f"{plan.action} plans must not carry rebuild rows"
            )
        if plan.action == "rebuild" and not rows and plan.desired_state.expected_row_count:
            raise PostGISProjectionValidationError("rebuild plan requires structured rows")
        if plan.action == "rebuild":
            expected_hash = plan.desired_state.expected_target_content_sha256
            actual_rows_hash = projection_rows_fingerprint(target, rows)
            if (
                actual_rows_hash != expected_hash
                or len(rows) != plan.desired_state.expected_row_count
            ):
                raise PostGISProjectionValidationError(
                    "rebuild rows do not match desired target content"
                )
        now = observed_at or datetime.now(UTC)
        if now.tzinfo is None or now.utcoffset() is None:
            raise PostGISProjectionValidationError("observed_at must be timezone-aware")
        now = now.astimezone(UTC)
        try:
            with self.engine.begin() as connection:
                self._set_tenant(connection, plan.tenant_id)
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
                    if (
                        current.target_exists != desired.target_exists
                        or current.observed_content_sha256 != desired.expected_target_content_sha256
                        or current.observed_row_count != desired.expected_row_count
                    ):
                        raise PostGISProjectionValidationError(
                            "checkpoint target does not match desired state"
                        )
                    status = "checkpointed"
                elif already_desired:
                    pass
                elif plan.action == "delete":
                    if not self._table_exists(connection, target):
                        raise PostGISProjectionValidationError("delete plan target is not a table")
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
                    connection.execute(
                        text(
                            f"CREATE TABLE {self._quote(target.schema_name)}.{self._quote(stage)} "
                            f"({', '.join(self._column_sql(column) for column in target.columns)})"
                        )
                    )
                    insert = text(self._insert_sql(target, stage))
                    for row in rows:
                        connection.execute(insert, self._row_parameters(target, row))
                    if self._relation_kind_exists(connection, target):
                        if not self._table_exists(connection, target):
                            raise PostGISProjectionValidationError(
                                "registered PostGIS target exists but is not a table"
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
                    if self._relation_kind_exists(connection, target) and self._table_exists(
                        connection, target
                    ):
                        connection.execute(
                            text(
                                f"DROP TABLE IF EXISTS {self._quote(target.schema_name)}."
                                f"{self._quote(backup)}"
                            )
                        )
                    status = "completed"
                if post is None:
                    post = self.observe(target, connection=connection)
                desired = plan.desired_state
                if (
                    post.target_exists != desired.target_exists
                    or post.observed_content_sha256 != desired.expected_target_content_sha256
                    or post.observed_row_count != desired.expected_row_count
                ):
                    raise PostGISProjectionExecutionError(
                        "PostGIS post-repair observation does not match desired state"
                    )
                provider_transaction_id = str(
                    connection.execute(
                        text("SELECT pg_current_xact_id()::text")
                    ).scalar_one()
                )
                commit_ref = {
                    "provider": "postgis",
                    "provider_commit": (
                        f"{target.schema_name}.{target.table_name}:"
                        f"{plan.next_checkpoint_version}"
                    ),
                    "provider_transaction_id": provider_transaction_id,
                    "plan_sha256": plan.plan_sha256,
                    "idempotency_key": plan.plan_idempotency_key,
                }
                receipt_sha256 = postgis_projection_receipt_fingerprint(
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
                receipt = PostGISProjectionRepairReceipt(
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
                        INSERT INTO gda_provider.postgis_projection_repair_receipt (
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
        except PostGISProjectionExecutionError:
            raise
        except DBAPIError as exc:
            raise PostGISProjectionExecutionError("PostGIS repair transaction failed") from exc
        except SQLAlchemyError as exc:
            raise PostGISProjectionConfigurationError(
                "PostGIS repair channel is unavailable"
            ) from exc
        return receipt


__all__ = [
    "PostGISColumnKind",
    "PostGISColumnSpec",
    "PostGISProjectionConfigurationError",
    "PostGISProjectionExecutionError",
    "PostGISProjectionRepairExecutor",
    "PostGISProjectionRepairReceipt",
    "PostGISProjectionTarget",
    "PostGISProjectionTargetRegistry",
    "PostGISProjectionValidationError",
    "postgis_projection_receipt_fingerprint",
    "projection_rows_fingerprint",
]
