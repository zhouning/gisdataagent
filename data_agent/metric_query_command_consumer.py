"""Recoverable PlatformCommand delivery for governed metric queries."""

from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlsplit
from uuid import UUID, uuid5

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, SQLAlchemyError

from .metric_query import MetricFilterOperator, MetricQueryPlan
from .metric_query_execution import (
    MetricQueryCacheStatus,
    MetricQueryCompletionSpec,
    MetricQueryExecutionAuthority,
    MetricQueryExecutionError,
    MetricQueryOutcome,
    MetricQueryRunRecord,
    MetricQueryStartSpec,
)
from .metric_query_result_store import (
    METRIC_QUERY_RESULT_MEDIA_TYPE,
    LocalMetricQueryResultStore,
    MetricQueryResultPublication,
    MetricQueryResultStore,
    MetricQueryResultStoreConflict,
    MetricQueryResultStoreUnavailable,
)
from .platform_contracts import (
    TERMINAL_RUN_STATUSES,
    PlatformCommand,
    PlatformCommandStatus,
    PlatformCommandType,
    RunStatus,
)
from .platform_gateway import PlatformGateway, PlatformGatewayError

POSTGIS_WORKLOAD = "workload:metric-query-postgis"
DUCKDB_WORKLOAD = "workload:metric-query-duckdb"
SPARK_WORKLOAD = "workload:metric-query-spark"
METRIC_QUERY_WORKLOADS = {
    "postgis": POSTGIS_WORKLOAD,
    "duckdb": DUCKDB_WORKLOAD,
    "iceberg_spark": SPARK_WORKLOAD,
}
_IDENTIFIER_RE = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")


def metric_query_command_identity(
    tenant_id: str,
    run_id: UUID,
    plan_artifact_id: UUID,
    plan_fingerprint: str,
) -> tuple[str, UUID]:
    dedupe_key = (
        f"metric_query.execute:{tenant_id}:{run_id}:"
        f"{plan_artifact_id}:{plan_fingerprint}"
    )
    value = hashlib.sha256(dedupe_key.encode("utf-8")).hexdigest()
    command_id = UUID(
        f"{value[:8]}-{value[8:12]}-5{value[13:16]}-"
        f"8{value[17:20]}-{value[20:32]}"
    )
    return dedupe_key, command_id


class MetricQueryProviderError(RuntimeError):
    code = "metric_query_provider_error"


class MetricQueryProviderTransientError(MetricQueryProviderError):
    code = "metric_query_provider_transient"


class MetricQueryProviderContractError(MetricQueryProviderError):
    code = "metric_query_provider_contract"


class MetricQueryResultLimitError(MetricQueryProviderContractError):
    code = "metric_query_result_limit"


@dataclass(frozen=True)
class MetricQueryProviderResult:
    storage_uri: str
    media_type: str
    sha256: str
    size_bytes: int
    manifest: dict[str, Any]
    rows_returned: int
    rows_scanned: int
    bytes_scanned: int
    duration_ms: int


class MetricQueryProvider(Protocol):
    engine_name: str
    workload_subject: str

    def execute(
        self,
        plan: MetricQueryPlan,
        *,
        run_id: UUID,
        plan_fingerprint: str,
    ) -> MetricQueryProviderResult: ...


@dataclass(frozen=True)
class MetricQueryCommandBatchResult:
    claimed: int
    completed: int
    query_succeeded: int
    query_failed: int
    retry_pending: int
    failed: int
    command_ids: tuple[UUID, ...]


def _json_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            return value.isoformat()
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, bytes):
        return value.hex()
    raise MetricQueryProviderContractError(
        f"query result contains unsupported value type {type(value).__name__}"
    )


def _sqlstate(exc: DBAPIError) -> str | None:
    original = getattr(exc, "orig", None)
    return getattr(original, "sqlstate", None) or getattr(original, "pgcode", None)


class PostGISMetricQueryProvider:
    """Compile a structured plan into one bounded, read-only PostGIS query."""

    engine_name = "postgis"
    workload_subject = POSTGIS_WORKLOAD

    def __init__(
        self,
        engine: Any,
        *,
        result_root: Path | None = None,
        result_store: MetricQueryResultStore | None = None,
        relation_authority: str | None = None,
        statement_timeout_ms: int = 30_000,
        max_result_rows: int = 10_000,
    ):
        if engine is None or engine.dialect.name != "postgresql":
            raise MetricQueryProviderContractError(
                "PostGIS metric query provider requires PostgreSQL"
            )
        if not 1 <= statement_timeout_ms <= 86_400_000:
            raise MetricQueryProviderContractError("statement timeout is out of bounds")
        if not 1 <= max_result_rows <= 1_000_000:
            raise MetricQueryProviderContractError("result row limit is out of bounds")
        if (result_root is None) == (result_store is None):
            raise MetricQueryProviderContractError(
                "exactly one metric query result store must be configured"
            )
        self.engine = engine
        try:
            if result_store is None:
                assert result_root is not None
                self.result_store = LocalMetricQueryResultStore(result_root)
            else:
                self.result_store = result_store
        except ValueError as exc:
            raise MetricQueryProviderContractError(str(exc)) from exc
        self.relation_authority = relation_authority
        self.statement_timeout_ms = statement_timeout_ms
        self.max_result_rows = max_result_rows

    @staticmethod
    def _identifier(value: str) -> str:
        if _IDENTIFIER_RE.fullmatch(value) is None:
            raise MetricQueryProviderContractError(
                f"unsafe PostGIS identifier {value!r}"
            )
        return value

    def _quote(self, value: str) -> str:
        return self.engine.dialect.identifier_preparer.quote_identifier(
            self._identifier(value)
        )

    def _relation(self, relation_ref: str) -> tuple[str, str, str]:
        parts = urlsplit(relation_ref)
        if (
            parts.scheme != "postgis"
            or not parts.netloc
            or parts.username
            or parts.password
            or parts.query
            or parts.fragment
            or not parts.path.startswith("/")
        ):
            raise MetricQueryProviderContractError(
                "PostGIS relation reference is invalid or credential-bearing"
            )
        if self.relation_authority is not None and parts.netloc != self.relation_authority:
            raise MetricQueryProviderContractError(
                "PostGIS relation authority does not match this provider"
            )
        relation = parts.path[1:]
        if relation.count(".") != 1:
            raise MetricQueryProviderContractError(
                "PostGIS relation must be schema-qualified"
            )
        schema, table = relation.split(".", 1)
        return parts.netloc, self._identifier(schema), self._identifier(table)

    def _where(self, plan: MetricQueryPlan) -> tuple[str, dict[str, Any]]:
        intent = plan.physical_intent
        predicates: list[str] = []
        parameters: dict[str, Any] = {}
        parameter_no = 0

        def bind(value: Any) -> str:
            nonlocal parameter_no
            name = f"p_{parameter_no}"
            parameter_no += 1
            parameters[name] = value
            return f":{name}"

        for item in intent.filters:
            column = f"source.{self._quote(item.column)}"
            if item.operator is MetricFilterOperator.EQ:
                predicates.append(f"{column} = {bind(item.values[0])}")
            elif item.operator is MetricFilterOperator.IN:
                placeholders = ", ".join(bind(value) for value in item.values)
                predicates.append(f"{column} IN ({placeholders})")
            elif item.operator is MetricFilterOperator.BETWEEN:
                predicates.append(
                    f"{column} BETWEEN {bind(item.values[0])} AND {bind(item.values[1])}"
                )
            else:  # pragma: no cover - closed enum, retained as a fail-closed guard
                raise MetricQueryProviderContractError("unsupported metric filter operator")

        if intent.time_range is not None:
            time_column = f"source.{self._quote(intent.time_range.column)}"
            predicates.append(
                f"{time_column} >= {bind(intent.time_range.start)} "
                f"AND {time_column} < {bind(intent.time_range.end)}"
            )

        if intent.spatial_filter is not None:
            spatial = intent.spatial_filter
            geometry = f"source.{self._quote(spatial.geometry_column)}"
            min_x, min_y, max_x, max_y = spatial.bbox
            envelope = (
                f"ST_MakeEnvelope({bind(min_x)}, {bind(min_y)}, "
                f"{bind(max_x)}, {bind(max_y)}, {bind(spatial.geometry_srid)})"
            )
            predicates_by_relationship = {
                "intersects": f"ST_Intersects({geometry}, {envelope})",
                "within": f"ST_Within({geometry}, {envelope})",
                "contains": f"ST_Contains({geometry}, {envelope})",
                "centroid_within": (
                    f"ST_Within(ST_Centroid({geometry}), {envelope})"
                ),
            }
            try:
                predicates.append(predicates_by_relationship[spatial.relationship])
            except KeyError as exc:
                raise MetricQueryProviderContractError(
                    "unsupported governed spatial relationship"
                ) from exc
        return (" WHERE " + " AND ".join(predicates)) if predicates else "", parameters

    def _queries(self, plan: MetricQueryPlan) -> tuple[str, str, dict[str, Any]]:
        _, schema, table = self._relation(plan.physical_intent.relation_ref)
        relation = f"{self._quote(schema)}.{self._quote(table)} AS source"
        where_sql, parameters = self._where(plan)
        group_columns = tuple(
            f"source.{self._quote(column)}"
            for column in plan.physical_intent.group_by_columns
        )
        value_column = f"source.{self._quote(plan.physical_intent.value_column)}"
        selected_groups = list(group_columns)
        value_alias = self._quote("metric_value")
        if plan.physical_intent.rollup_operator == "sum":
            value_expression = f"SUM({value_column}) AS {value_alias}"
            group_sql = " GROUP BY " + ", ".join(group_columns) if group_columns else ""
            order_columns = list(group_columns)
        elif plan.physical_intent.rollup_operator == "none":
            value_expression = f"{value_column} AS {value_alias}"
            group_sql = ""
            order_columns = [*group_columns, value_column]
        else:  # pragma: no cover - MetricQueryPlan forbids other values
            raise MetricQueryProviderContractError("unsupported metric rollup operator")
        select_items = [*selected_groups, value_expression]
        order_sql = (
            " ORDER BY " + ", ".join(f"{column} NULLS LAST" for column in order_columns)
            if order_columns
            else ""
        )
        result_sql = (
            f"SELECT {', '.join(select_items)} FROM {relation}"
            f"{where_sql}{group_sql}{order_sql} LIMIT {self.max_result_rows + 1}"
        )
        evidence_sql = (
            "SELECT count(*)::bigint AS rows_scanned, "
            "COALESCE(sum(pg_column_size(source)), 0)::bigint AS bytes_scanned "
            f"FROM {relation}{where_sql}"
        )
        return result_sql, evidence_sql, parameters

    def _write_result(
        self,
        plan: MetricQueryPlan,
        run_id: UUID,
        payload: bytes,
    ) -> MetricQueryResultPublication:
        try:
            return self.result_store.put(plan.tenant_id, run_id, payload)
        except MetricQueryResultStoreConflict as exc:
            raise MetricQueryProviderContractError(
                "stable metric query result contains different content"
            ) from exc
        except MetricQueryResultStoreUnavailable as exc:
            raise MetricQueryProviderTransientError(
                "metric query result storage is unavailable"
            ) from exc

    def execute(
        self,
        plan: MetricQueryPlan,
        *,
        run_id: UUID,
        plan_fingerprint: str,
    ) -> MetricQueryProviderResult:
        if plan.engine.value != self.engine_name or plan.execution_mode != "synchronous":
            raise MetricQueryProviderContractError(
                "PostGIS provider received a plan for another engine or mode"
            )
        started = time.monotonic()
        result_sql, evidence_sql, parameters = self._queries(plan)
        try:
            with self.engine.connect() as connection, connection.begin():
                connection.exec_driver_sql("SET TRANSACTION READ ONLY")
                connection.execute(
                    text(
                        "SELECT set_config('statement_timeout', :timeout, true)"
                    ),
                    {"timeout": f"{self.statement_timeout_ms}ms"},
                )
                read_only = connection.execute(
                    text("SHOW transaction_read_only")
                ).scalar_one()
                evidence = connection.execute(
                    text(evidence_sql), parameters
                ).mappings().one()
                rows = connection.execute(text(result_sql), parameters).mappings().all()
        except DBAPIError as exc:
            state = _sqlstate(exc)
            if state is not None and (
                state.startswith(("08", "40", "53"))
                or state in {"55P03", "57014", "57P01", "57P02", "57P03"}
            ):
                raise MetricQueryProviderTransientError(
                    "PostGIS query failed with a retryable database condition"
                ) from exc
            raise MetricQueryProviderContractError(
                "PostGIS rejected the governed metric query"
            ) from exc
        except SQLAlchemyError as exc:
            raise MetricQueryProviderTransientError(
                "PostGIS query transport failed"
            ) from exc

        if len(rows) > self.max_result_rows:
            raise MetricQueryResultLimitError(
                f"metric query exceeded the {self.max_result_rows} row result limit"
            )
        columns = list(rows[0].keys()) if rows else [
            *plan.physical_intent.group_by_columns,
            "metric_value",
        ]
        canonical_rows = [
            {key: _json_value(value) for key, value in row.items()} for row in rows
        ]
        result_document = {
            "schema": "gda.metric_query_result.v1",
            "tenant_id": plan.tenant_id,
            "run_id": str(run_id),
            "plan_fingerprint": plan_fingerprint,
            "cache_key": plan.cache_key,
            "source_snapshot_ref": plan.source_snapshot_ref,
            "columns": columns,
            "rows": canonical_rows,
        }
        payload = json.dumps(
            result_document,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        result_sha256 = hashlib.sha256(payload).hexdigest()
        publication = self._write_result(plan, run_id, payload)
        duration_ms = min(86_400_000, max(0, round((time.monotonic() - started) * 1000)))
        return MetricQueryProviderResult(
            storage_uri=publication.storage_uri,
            media_type=METRIC_QUERY_RESULT_MEDIA_TYPE,
            sha256=result_sha256,
            size_bytes=len(payload),
            manifest={
                "format": "canonical-json",
                "result_schema": "gda.metric_query_result.v1",
                "columns": columns,
                "decimal_encoding": "string",
                "relation_ref": plan.physical_intent.relation_ref,
                "logical_source_rows": int(evidence["rows_scanned"]),
                "logical_source_bytes": int(evidence["bytes_scanned"]),
                "transaction_read_only": read_only == "on",
                "statement_timeout_ms": self.statement_timeout_ms,
                "storage_evidence": publication.storage_evidence(),
            },
            rows_returned=len(rows),
            rows_scanned=int(evidence["rows_scanned"]),
            bytes_scanned=int(evidence["bytes_scanned"]),
            duration_ms=duration_ms,
        )


class MetricQueryCommandConsumer:
    """Deliver one provider workload's query commands with lease recovery."""

    def __init__(
        self,
        provider: MetricQueryProvider,
        *,
        gateway: PlatformGateway | None = None,
        authority: MetricQueryExecutionAuthority | None = None,
    ):
        expected_subject = METRIC_QUERY_WORKLOADS.get(provider.engine_name)
        if expected_subject is None or provider.workload_subject != expected_subject:
            raise MetricQueryProviderContractError(
                "metric query provider has no governed engine workload identity"
            )
        self.provider = provider
        self.gateway = gateway or PlatformGateway()
        self.authority = authority or MetricQueryExecutionAuthority()

    @staticmethod
    def _retry_delay(command: PlatformCommand) -> int:
        return min(300, 5 * (2 ** max(0, command.attempt_count - 1)))

    def _validate_command(
        self,
        command: PlatformCommand,
        record: MetricQueryRunRecord,
    ) -> None:
        admission = record.admission
        expected_payload = {
            "schema": "gda.metric_query_execute_command.v1",
            "run_id": str(admission.run_id),
            "plan_artifact_id": str(admission.plan_artifact_id),
            "plan_fingerprint": admission.plan_fingerprint,
            "cache_key": admission.cache_key,
            "engine": admission.engine,
            "execution_mode": admission.execution_mode,
        }
        expected_dedupe, expected_command_id = metric_query_command_identity(
            admission.tenant_id,
            admission.run_id,
            admission.plan_artifact_id,
            admission.plan_fingerprint,
        )
        if (
            command.command_type is not PlatformCommandType.METRIC_QUERY_EXECUTE
            or command.actor_subject != self.provider.workload_subject
            or command.command_id != expected_command_id
            or command.dedupe_key != expected_dedupe
            or command.run_id != admission.run_id
            or command.execution_plan_artifact_id != admission.plan_artifact_id
            or command.payload != expected_payload
            or admission.engine != self.provider.engine_name
            or command.created_at != admission.admitted_at
        ):
            raise MetricQueryProviderContractError(
                "metric query command does not bind the admitted plan"
            )

    @staticmethod
    def _start_spec(command: PlatformCommand, engine_name: str) -> MetricQueryStartSpec:
        return MetricQueryStartSpec(
            attempt_no=1,
            external_namespace=f"gda/metric-query/{engine_name}",
            external_run_id=str(command.command_id),
            external_attempt_id="provider-attempt-1",
            observed_at=command.created_at,
        )

    @staticmethod
    def _start_observation_id(
        command: PlatformCommand, spec: MetricQueryStartSpec
    ) -> UUID:
        return uuid5(
            command.run_id,
            f"metric-query-start:{spec.attempt_no}:"
            f"{spec.external_namespace}:{spec.external_run_id}",
        )

    def _start(
        self,
        command: PlatformCommand,
        record: MetricQueryRunRecord,
    ) -> tuple[MetricQueryRunRecord, UUID]:
        spec = self._start_spec(command, self.provider.engine_name)
        if record.run.status not in {RunStatus.ACCEPTED, RunStatus.RUNNING}:
            raise MetricQueryProviderContractError(
                "metric query command found a non-executable Run state"
            )
        started = self.authority.start(
            command.tenant_id,
            command.run_id,
            spec,
            actor_subject=self.provider.workload_subject,
            expected_state_version=0,
        )
        return started, self._start_observation_id(command, spec)

    @staticmethod
    def _observed_at(started_at: datetime, duration_ms: int) -> datetime:
        now = datetime.now(UTC)
        return now if now >= started_at else started_at

    def _complete_success(
        self,
        command: PlatformCommand,
        start_observation_id: UUID,
        result: MetricQueryProviderResult,
    ) -> None:
        self.authority.complete(
            command.tenant_id,
            command.run_id,
            MetricQueryCompletionSpec(
                attempt_no=1,
                start_observation_id=start_observation_id,
                outcome=MetricQueryOutcome.SUCCEEDED,
                cache_status=MetricQueryCacheStatus.MISS,
                rows_returned=result.rows_returned,
                rows_scanned=result.rows_scanned,
                bytes_scanned=result.bytes_scanned,
                duration_ms=result.duration_ms,
                result_storage_uri=result.storage_uri,
                result_media_type=result.media_type,
                result_sha256=result.sha256,
                result_size_bytes=result.size_bytes,
                result_manifest=result.manifest,
                observed_at=self._observed_at(command.created_at, result.duration_ms),
            ),
            actor_subject=self.provider.workload_subject,
            expected_state_version=2,
        )

    def _complete_failure(
        self,
        command: PlatformCommand,
        start_observation_id: UUID,
        error: MetricQueryProviderError,
        *,
        error_code: str | None = None,
    ) -> None:
        message = f"{type(error).__name__}: {error}"[:2048]
        self.authority.complete(
            command.tenant_id,
            command.run_id,
            MetricQueryCompletionSpec(
                attempt_no=1,
                start_observation_id=start_observation_id,
                outcome=MetricQueryOutcome.FAILED,
                cache_status=MetricQueryCacheStatus.BYPASS,
                duration_ms=0,
                error_code=error_code or error.code,
                error_message=message or "metric query provider failed",
                observed_at=self._observed_at(command.created_at, 0),
            ),
            actor_subject=self.provider.workload_subject,
            expected_state_version=2,
        )

    def run_once(
        self,
        tenant_id: str,
        *,
        worker_id: str,
        limit: int = 10,
        lease_seconds: int = 60,
    ) -> MetricQueryCommandBatchResult:
        commands = self.gateway.claim_commands(
            tenant_id,
            worker_id,
            actor_subject=self.provider.workload_subject,
            limit=limit,
            lease_seconds=lease_seconds,
        )
        completed = 0
        query_succeeded = 0
        query_failed = 0
        retry_pending = 0
        failed = 0
        for command in commands:
            try:
                record = self.authority.get(command.tenant_id, command.run_id)
                self._validate_command(command, record)
                if record.run.status in TERMINAL_RUN_STATUSES:
                    self.gateway.complete_command(
                        command.tenant_id,
                        command.command_id,
                        worker_id=worker_id,
                    )
                    completed += 1
                    continue
                _, start_observation_id = self._start(command, record)
                try:
                    result = self.provider.execute(
                        record.admission.plan,
                        run_id=command.run_id,
                        plan_fingerprint=record.admission.plan_fingerprint,
                    )
                except MetricQueryProviderTransientError as exc:
                    if command.attempt_count >= command.max_attempts:
                        self._complete_failure(
                            command,
                            start_observation_id,
                            exc,
                            error_code="provider_retry_exhausted",
                        )
                        delivery = self.gateway.fail_command(
                            command.tenant_id,
                            command.command_id,
                            worker_id=worker_id,
                            error=f"{type(exc).__name__}: {exc}",
                            retry_delay_seconds=0,
                        )
                        query_failed += 1
                        failed += int(delivery.status is PlatformCommandStatus.FAILED)
                    else:
                        self.gateway.fail_command(
                            command.tenant_id,
                            command.command_id,
                            worker_id=worker_id,
                            error=f"{type(exc).__name__}: {exc}",
                            retry_delay_seconds=self._retry_delay(command),
                        )
                        retry_pending += 1
                    continue
                except MetricQueryProviderError as exc:
                    self._complete_failure(command, start_observation_id, exc)
                    self.gateway.complete_command(
                        command.tenant_id,
                        command.command_id,
                        worker_id=worker_id,
                    )
                    completed += 1
                    query_failed += 1
                    continue
                self._complete_success(command, start_observation_id, result)
                self.gateway.complete_command(
                    command.tenant_id,
                    command.command_id,
                    worker_id=worker_id,
                )
                completed += 1
                query_succeeded += 1
            except (MetricQueryExecutionError, PlatformGatewayError):
                delivery = self.gateway.fail_command(
                    command.tenant_id,
                    command.command_id,
                    worker_id=worker_id,
                    error="metric query control-plane delivery failed",
                    retry_delay_seconds=self._retry_delay(command),
                )
                if delivery.status is PlatformCommandStatus.FAILED:
                    failed += 1
                else:
                    retry_pending += 1
            except MetricQueryProviderContractError as exc:
                delivery = self.gateway.fail_command(
                    command.tenant_id,
                    command.command_id,
                    worker_id=worker_id,
                    error=f"{type(exc).__name__}: {exc}",
                    retry_delay_seconds=0,
                )
                if delivery.status is PlatformCommandStatus.FAILED:
                    failed += 1
                else:
                    retry_pending += 1
        return MetricQueryCommandBatchResult(
            claimed=len(commands),
            completed=completed,
            query_succeeded=query_succeeded,
            query_failed=query_failed,
            retry_pending=retry_pending,
            failed=failed,
            command_ids=tuple(command.command_id for command in commands),
        )
