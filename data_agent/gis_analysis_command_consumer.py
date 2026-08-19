"""Recoverable PlatformCommand delivery for governed PostGIS analysis."""

from __future__ import annotations

import hashlib
import json
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol
from uuid import UUID, uuid5

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, SQLAlchemyError

from .gis_algorithm_registry import (
    DEFAULT_GIS_ALGORITHM_REGISTRY,
    GISAlgorithmRegistry,
    GISAlgorithmRegistryError,
)
from .gis_analysis_execution import (
    GIS_POSTGIS_CANCELLER_WORKLOAD,
    GIS_POSTGIS_RECONCILER_WORKLOAD,
    GIS_POSTGIS_WORKLOAD,
    GISAnalysisBackendBinding,
    GISAnalysisCancelOutcome,
    GISAnalysisCompletionSpec,
    GISAnalysisExecutionAuthority,
    GISAnalysisExecutionError,
    GISAnalysisOutcome,
    GISAnalysisPlan,
    GISAnalysisProviderStartSpec,
    GISAnalysisRunRecord,
)
from .metric_query_result_store import (
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

GIS_ANALYSIS_RESULT_MEDIA_TYPE = "application/geo+json"
_IDENTIFIER_RE = re.compile(r"^[a-z_][a-z0-9_]{0,62}$")


def gis_analysis_command_identity(
    tenant_id: str,
    run_id: UUID,
    plan_artifact_id: UUID,
    plan_fingerprint: str,
) -> tuple[str, UUID]:
    dedupe_key = (
        f"gis_analysis.execute:{tenant_id}:{run_id}:"
        f"{plan_artifact_id}:{plan_fingerprint}"
    )
    value = hashlib.sha256(dedupe_key.encode("utf-8")).hexdigest()
    command_id = UUID(
        f"{value[:8]}-{value[8:12]}-5{value[13:16]}-"
        f"8{value[17:20]}-{value[20:32]}"
    )
    return dedupe_key, command_id


class GISAnalysisProviderError(RuntimeError):
    code = "gis_analysis_provider_error"


class GISAnalysisProviderTransientError(GISAnalysisProviderError):
    code = "gis_analysis_provider_transient"


class GISAnalysisProviderContractError(GISAnalysisProviderError):
    code = "gis_analysis_provider_contract"


class GISAnalysisResultLimitError(GISAnalysisProviderContractError):
    code = "gis_analysis_result_limit"


class GISAnalysisProviderCancelled(GISAnalysisProviderError):
    code = "gis_analysis_provider_cancelled"

    def __init__(self, binding: GISAnalysisBackendBinding):
        super().__init__("PostGIS cancelled the analysis by user request")
        self.binding = binding


@dataclass(frozen=True)
class GISAnalysisProviderResult:
    storage_uri: str
    media_type: str
    sha256: str
    size_bytes: int
    manifest: dict[str, Any]
    features_returned: int
    bytes_scanned: int
    duration_ms: int


class GISAnalysisProvider(Protocol):
    engine_name: str
    workload_subject: str

    def execute(
        self,
        plan: GISAnalysisPlan,
        *,
        run_id: UUID,
        plan_fingerprint: str,
        on_backend_ready: Callable[[GISAnalysisBackendBinding], None],
    ) -> GISAnalysisProviderResult: ...


@dataclass(frozen=True)
class GISAnalysisCommandBatchResult:
    claimed: int
    completed: int
    analysis_succeeded: int
    analysis_failed: int
    retry_pending: int
    failed: int
    command_ids: tuple[UUID, ...]


@dataclass(frozen=True)
class GISAnalysisCancelBatchResult:
    claimed: int
    completed: int
    signalled: int
    reconciliation_required: int
    retry_pending: int
    failed: int
    command_ids: tuple[UUID, ...]


@dataclass(frozen=True)
class GISAnalysisReconciliationBatchResult:
    claimed: int
    observations_recorded: int
    signalled: int
    retry_pending: int
    escalated: int
    terminal_converged: int
    failed: int
    command_ids: tuple[UUID, ...]


def _sqlstate(exc: DBAPIError) -> str | None:
    original = getattr(exc, "orig", None)
    return getattr(original, "sqlstate", None) or getattr(original, "pgcode", None)


class PostGISAnalysisProvider:
    """Compile one admitted GIS plan into a bounded, read-only PostGIS query."""

    engine_name = "postgis"
    workload_subject = GIS_POSTGIS_WORKLOAD

    def __init__(
        self,
        engine: Any,
        *,
        result_root: Path | None = None,
        result_store: MetricQueryResultStore | None = None,
        statement_timeout_ceiling_ms: int = 1_795_000,
        algorithm_registry: GISAlgorithmRegistry = DEFAULT_GIS_ALGORITHM_REGISTRY,
    ):
        if engine is None or engine.dialect.name != "postgresql":
            raise GISAnalysisProviderContractError(
                "PostGIS analysis provider requires PostgreSQL"
            )
        if not 100 <= statement_timeout_ceiling_ms <= 1_795_000:
            raise GISAnalysisProviderContractError(
                "GIS statement timeout ceiling is out of bounds"
            )
        if (result_root is None) == (result_store is None):
            raise GISAnalysisProviderContractError(
                "exactly one GIS analysis result store must be configured"
            )
        self.engine = engine
        try:
            self.result_store = (
                LocalMetricQueryResultStore(result_root)
                if result_store is None
                else result_store
            )
        except ValueError as exc:
            raise GISAnalysisProviderContractError(str(exc)) from exc
        self.statement_timeout_ceiling_ms = statement_timeout_ceiling_ms
        self.algorithm_registry = algorithm_registry

    def _algorithm(self, plan: GISAnalysisPlan):
        try:
            return self.algorithm_registry.require_plan_binding(
                operation=plan.operation,
                algorithm_id=plan.algorithm_id,
                algorithm_version=plan.algorithm_version,
                spec_fingerprint=plan.algorithm_spec_fingerprint,
                engine=plan.engine,
            )
        except GISAlgorithmRegistryError as exc:
            raise GISAnalysisProviderContractError(str(exc)) from exc

    @staticmethod
    def _identifier(value: str) -> str:
        if _IDENTIFIER_RE.fullmatch(value) is None:
            raise GISAnalysisProviderContractError(
                f"unsafe PostGIS identifier {value!r}"
            )
        return value

    def _quote(self, value: str) -> str:
        return self.engine.dialect.identifier_preparer.quote_identifier(
            self._identifier(value)
        )

    def _relation(self, value: str) -> str:
        parts = value.split(".")
        if not 1 <= len(parts) <= 2:
            raise GISAnalysisProviderContractError(
                "PostGIS relation must contain at most one schema qualifier"
            )
        return ".".join(self._quote(part) for part in parts)

    def _source_cte(self, plan: GISAnalysisPlan, index: int, alias: str) -> str:
        source = plan.sources[index]
        relation = self._relation(source.physical_relation)
        geometry = self._quote(source.geometry_column)
        return (
            f"{alias} AS (SELECT row_number() OVER (ORDER BY "
            f"ST_AsEWKB({geometry}), ctid) AS source_id, {geometry} AS geom, "
            f"pg_column_size(t)::bigint AS source_bytes FROM {relation} AS t "
            f"WHERE {geometry} IS NOT NULL AND NOT ST_IsEmpty({geometry}) "
            f"AND ST_SRID({geometry}) = {source.source_srid})"
        )

    def _analysis_ctes(self, plan: GISAnalysisPlan) -> tuple[list[str], str]:
        implementation_key = self._algorithm(plan).implementation_key
        input_cte = self._source_cte(plan, 0, "input_source")
        output_srid = plan.output_srid
        ctes = [input_cte]
        if implementation_key == "postgis.buffer_geography.v1":
            result = (
                "analysis AS (SELECT source_id AS input_source_id, NULL::bigint "
                "AS overlay_source_id, ST_Transform(ST_Buffer(ST_Transform(geom, 4326)"
                f"::geography, :distance_meters)::geometry, {output_srid}) AS geom "
                "FROM input_source)"
            )
        else:
            ctes.append(self._source_cte(plan, 1, "overlay_source"))
            if implementation_key == "postgis.clip.v1":
                ctes.append(
                    "overlay_union AS (SELECT ST_UnaryUnion(ST_Collect(geom)) AS geom "
                    "FROM overlay_source)"
                )
                result = (
                    "analysis AS (SELECT input.source_id AS input_source_id, "
                    "NULL::bigint AS overlay_source_id, "
                    f"ST_Transform(ST_Intersection(input.geom, ST_Transform(overlay.geom, "
                    f"{plan.sources[0].source_srid})), {output_srid}) AS geom "
                    "FROM input_source AS input CROSS JOIN overlay_union AS overlay "
                    "WHERE overlay.geom IS NOT NULL AND ST_Intersects(input.geom, "
                    f"ST_Transform(overlay.geom, {plan.sources[0].source_srid})))"
                )
            elif implementation_key == "postgis.intersection.v1":
                result = (
                    "analysis AS (SELECT input.source_id AS input_source_id, "
                    "overlay.source_id AS overlay_source_id, "
                    f"ST_Transform(ST_Intersection(input.geom, ST_Transform(overlay.geom, "
                    f"{plan.sources[0].source_srid})), {output_srid}) AS geom "
                    "FROM input_source AS input JOIN overlay_source AS overlay ON "
                    f"ST_Intersects(input.geom, ST_Transform(overlay.geom, "
                    f"{plan.sources[0].source_srid})))"
                )
            else:
                raise GISAnalysisProviderContractError(
                    "GIS algorithm implementation is not installed"
                )
        ctes.append(result)
        ctes.append(
            "non_empty AS (SELECT input_source_id, overlay_source_id, geom FROM analysis "
            "WHERE geom IS NOT NULL AND NOT ST_IsEmpty(geom))"
        )
        return ctes, "non_empty"

    def _queries(self, plan: GISAnalysisPlan) -> tuple[str, str, dict[str, Any]]:
        ctes, result_cte = self._analysis_ctes(plan)
        prefix = "WITH " + ", ".join(ctes)
        result_sql = (
            f"{prefix} SELECT input_source_id, overlay_source_id, "
            "ST_AsGeoJSON(geom, 9, 0) AS geometry_json FROM "
            f"{result_cte} ORDER BY input_source_id, overlay_source_id NULLS FIRST "
            f"LIMIT {plan.budget.max_features + 1}"
        )
        evidence_relations = [
            f"SELECT source_bytes FROM {self._relation(source.physical_relation)} AS t "
            f"CROSS JOIN LATERAL (SELECT pg_column_size(t)::bigint AS source_bytes) AS b "
            f"WHERE {self._quote(source.geometry_column)} IS NOT NULL"
            for source in plan.sources
        ]
        evidence_sql = (
            "SELECT COALESCE(sum(source_bytes), 0)::bigint AS bytes_scanned FROM ("
            + " UNION ALL ".join(evidence_relations)
            + ") AS source_evidence"
        )
        parameters = (
            {"distance_meters": plan.distance_meters}
            if plan.distance_meters is not None
            else {}
        )
        return result_sql, evidence_sql, parameters

    def _write_result(
        self,
        plan: GISAnalysisPlan,
        run_id: UUID,
        payload: bytes,
    ) -> MetricQueryResultPublication:
        try:
            return self.result_store.put(
                plan.tenant_id,
                run_id,
                payload,
                media_type=GIS_ANALYSIS_RESULT_MEDIA_TYPE,
            )
        except MetricQueryResultStoreConflict as exc:
            raise GISAnalysisProviderContractError(
                "stable GIS analysis result contains different content"
            ) from exc
        except MetricQueryResultStoreUnavailable as exc:
            raise GISAnalysisProviderTransientError(
                "GIS analysis result storage is unavailable"
            ) from exc

    def execute(
        self,
        plan: GISAnalysisPlan,
        *,
        run_id: UUID,
        plan_fingerprint: str,
        on_backend_ready: Callable[[GISAnalysisBackendBinding], None],
    ) -> GISAnalysisProviderResult:
        if plan.engine != self.engine_name or plan.execution_mode != "asynchronous":
            raise GISAnalysisProviderContractError(
                "PostGIS provider received a plan for another engine or mode"
            )
        started = time.monotonic()
        result_sql, evidence_sql, parameters = self._queries(plan)
        timeout_ms = min(
            plan.budget.max_duration_ms,
            self.statement_timeout_ceiling_ms,
        )
        backend: GISAnalysisBackendBinding | None = None
        try:
            with self.engine.connect() as connection, connection.begin():
                connection.exec_driver_sql(
                    "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY"
                )
                application_name = f"gda-gis-analysis/{run_id}"
                connection.execute(
                    text("SELECT set_config('application_name', :name, false)"),
                    {"name": application_name},
                )
                backend_row = connection.execute(
                    text(
                        "SELECT pg_backend_pid() AS backend_pid, "
                        "backend_start, datid::bigint AS database_oid, "
                        "usesysid::bigint AS user_oid, application_name "
                        "FROM pg_stat_activity "
                        "WHERE pid = pg_backend_pid()"
                    )
                ).mappings().one()
                backend = GISAnalysisBackendBinding.create(**backend_row)
                on_backend_ready(backend)
                connection.execute(
                    text("SELECT set_config('statement_timeout', :timeout, true)"),
                    {"timeout": f"{timeout_ms}ms"},
                )
                read_only = connection.execute(
                    text("SHOW transaction_read_only")
                ).scalar_one()
                isolation_level = connection.execute(
                    text("SHOW transaction_isolation")
                ).scalar_one()
                evidence = connection.execute(text(evidence_sql)).mappings().one()
                rows = connection.execute(text(result_sql), parameters).mappings().all()
        except DBAPIError as exc:
            state = _sqlstate(exc)
            if (
                state == "57014"
                and backend is not None
                and "user request" in str(getattr(exc, "orig", exc)).casefold()
            ):
                raise GISAnalysisProviderCancelled(backend) from exc
            if state is not None and (
                state.startswith(("08", "40", "53"))
                or state in {"55P03", "57014", "57P01", "57P02", "57P03"}
            ):
                raise GISAnalysisProviderTransientError(
                    "PostGIS analysis failed with a retryable database condition"
                ) from exc
            raise GISAnalysisProviderContractError(
                "PostGIS rejected the governed GIS analysis"
            ) from exc
        except SQLAlchemyError as exc:
            raise GISAnalysisProviderTransientError(
                "PostGIS analysis transport failed"
            ) from exc

        if len(rows) > plan.budget.max_features:
            raise GISAnalysisResultLimitError(
                "GIS analysis exceeded the admitted feature limit"
            )
        features = []
        for row in rows:
            geometry = json.loads(row["geometry_json"])
            properties = {"input_source_id": int(row["input_source_id"])}
            if row["overlay_source_id"] is not None:
                properties["overlay_source_id"] = int(row["overlay_source_id"])
            features.append(
                {"type": "Feature", "geometry": geometry, "properties": properties}
            )
        document = {
            "type": "FeatureCollection",
            "features": features,
            "gda": {
                "schema": "gda.gis_analysis_result.v1",
                "tenant_id": plan.tenant_id,
                "run_id": str(run_id),
                "plan_fingerprint": plan_fingerprint,
                "cache_key": plan.cache_key,
                "operation": plan.operation.value,
                "algorithm_id": plan.algorithm_id,
                "algorithm_version": plan.algorithm_version,
                "algorithm_spec_fingerprint": plan.algorithm_spec_fingerprint,
                "output_crs": f"EPSG:{plan.output_srid}",
            },
        }
        payload = json.dumps(
            document,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        duration_ms = max(0, round((time.monotonic() - started) * 1_000))
        if len(payload) > plan.budget.max_output_bytes:
            raise GISAnalysisResultLimitError(
                "GIS analysis exceeded the admitted output byte limit"
            )
        if duration_ms > plan.budget.max_duration_ms:
            raise GISAnalysisResultLimitError(
                "GIS analysis exceeded the admitted duration limit"
            )
        publication = self._write_result(plan, run_id, payload)
        return GISAnalysisProviderResult(
            storage_uri=publication.storage_uri,
            media_type=GIS_ANALYSIS_RESULT_MEDIA_TYPE,
            sha256=hashlib.sha256(payload).hexdigest(),
            size_bytes=len(payload),
            manifest={
                "format": "canonical-geojson",
                "result_schema": "gda.gis_analysis_result.v1",
                "output_crs": f"EPSG:{plan.output_srid}",
                "operation": plan.operation.value,
                "algorithm_id": plan.algorithm_id,
                "algorithm_version": plan.algorithm_version,
                "algorithm_spec_fingerprint": plan.algorithm_spec_fingerprint,
                "source_resource_versions": [
                    str(source.resource_version_id) for source in plan.sources
                ],
                "transaction_read_only": read_only == "on",
                "transaction_isolation": isolation_level,
                "statement_timeout_ms": timeout_ms,
                "storage_evidence": publication.storage_evidence(),
            },
            features_returned=len(features),
            bytes_scanned=int(evidence["bytes_scanned"]),
            duration_ms=duration_ms,
        )


class PostGISBackendCanceller:
    """Cancel only an exact, immutable PostGIS backend identity."""

    workload_subject = GIS_POSTGIS_CANCELLER_WORKLOAD

    def __init__(self, engine: Any):
        if engine is None or engine.dialect.name != "postgresql":
            raise GISAnalysisProviderContractError(
                "PostGIS backend canceller requires PostgreSQL"
            )
        self.engine = engine

    def cancel(
        self,
        binding: GISAnalysisBackendBinding,
    ) -> GISAnalysisCancelOutcome:
        try:
            with self.engine.connect() as connection, connection.begin():
                signalled = connection.execute(
                    text(
                        "SELECT pg_cancel_backend(pid) FROM pg_stat_activity "
                        "WHERE pid = :backend_pid "
                        "AND backend_start = :backend_start "
                        "AND datid = :database_oid "
                        "AND usesysid = :user_oid "
                        "AND application_name = :application_name"
                    ),
                    binding.model_dump(
                        mode="python", exclude={"schema_id", "binding_fingerprint"}
                    ),
                ).scalar_one_or_none()
                if signalled is None:
                    return GISAnalysisCancelOutcome.NOT_FOUND
                return (
                    GISAnalysisCancelOutcome.SIGNALLED
                    if signalled is True
                    else GISAnalysisCancelOutcome.UNKNOWN
                )
        except DBAPIError as exc:
            state = _sqlstate(exc)
            if state is not None and state.startswith(("08", "53", "57")):
                raise GISAnalysisProviderTransientError(
                    "PostGIS cancellation transport is unavailable"
                ) from exc
            raise GISAnalysisProviderContractError(
                "PostGIS rejected governed backend cancellation"
            ) from exc
        except SQLAlchemyError as exc:
            raise GISAnalysisProviderTransientError(
                "PostGIS cancellation transport failed"
            ) from exc


class GISAnalysisCancelCommandConsumer:
    """Deliver cancellation commands on a channel independent from long queries."""

    def __init__(
        self,
        canceller: PostGISBackendCanceller,
        *,
        gateway: PlatformGateway | None = None,
        authority: GISAnalysisExecutionAuthority | None = None,
    ):
        self.canceller = canceller
        self.gateway = gateway or PlatformGateway()
        self.authority = authority or GISAnalysisExecutionAuthority()

    @staticmethod
    def _retry_delay(command: PlatformCommand) -> int:
        return min(60, 2 * (2 ** max(0, command.attempt_count - 1)))

    def _validate_command(
        self,
        command: PlatformCommand,
        record: GISAnalysisRunRecord,
    ) -> GISAnalysisBackendBinding:
        admission = record.cancel_admission
        if admission is None:
            raise GISAnalysisProviderContractError(
                "GIS cancel command has no cancellation admission"
            )
        binding = admission.backend
        expected_dedupe_key = (
            f"gis_analysis.cancel:{admission.tenant_id}:{admission.run_id}:"
            f"{admission.cancel_request_id}:{binding.binding_fingerprint}"
        )
        expected_payload = {
            "schema": "gda.gis_analysis_cancel_command.v1",
            "run_id": str(command.run_id),
            "plan_artifact_id": str(record.admission.plan_artifact_id),
            "backend_pid": binding.backend_pid,
            "backend_start": binding.backend_start.isoformat().replace("+00:00", "Z"),
            "database_oid": binding.database_oid,
            "user_oid": binding.user_oid,
            "application_name": binding.application_name,
            "backend_binding_fingerprint": binding.binding_fingerprint,
        }
        payload_binding: GISAnalysisBackendBinding | None = None
        try:
            payload_binding = GISAnalysisBackendBinding.model_validate(
                {
                    "backend_pid": command.payload.get("backend_pid"),
                    "backend_start": command.payload.get("backend_start"),
                    "database_oid": command.payload.get("database_oid"),
                    "user_oid": command.payload.get("user_oid"),
                    "application_name": command.payload.get("application_name"),
                    "binding_fingerprint": command.payload.get(
                        "backend_binding_fingerprint"
                    ),
                }
            )
        except ValueError:
            pass
        expected_payload["backend_start"] = command.payload.get("backend_start")
        if (
            command.command_type is not PlatformCommandType.GIS_ANALYSIS_CANCEL
            or command.command_id != admission.cancel_command_id
            or command.dedupe_key != expected_dedupe_key
            or command.actor_subject != self.canceller.workload_subject
            or command.run_id != admission.run_id
            or command.trigger_observation_id != admission.start_observation_id
            or command.execution_plan_artifact_id
            != record.admission.plan_artifact_id
            or command.payload != expected_payload
            or payload_binding != binding
            or command.created_at != admission.requested_at
            or record.run.status
            not in {RunStatus.CANCELLING, RunStatus.RECONCILING, RunStatus.CANCELLED}
            or (
                record.cancel_receipt is not None
                and (
                    record.cancel_receipt.backend.binding_fingerprint
                    != binding.binding_fingerprint
                    or record.cancel_receipt.recorded_by
                    != self.canceller.workload_subject
                )
            )
        ):
            raise GISAnalysisProviderContractError(
                "GIS cancel command does not bind its admitted PostGIS backend"
            )
        return binding

    def run_once(
        self,
        tenant_id: str,
        *,
        worker_id: str,
        limit: int = 10,
        lease_seconds: int = 30,
    ) -> GISAnalysisCancelBatchResult:
        commands = self.gateway.claim_commands(
            tenant_id,
            worker_id,
            actor_subject=self.canceller.workload_subject,
            limit=limit,
            lease_seconds=lease_seconds,
        )
        completed = signalled = reconciliation_required = retry_pending = failed = 0
        for command in commands:
            try:
                record = self.authority.get(command.tenant_id, command.run_id)
                binding = self._validate_command(command, record)
                if record.cancel_receipt is not None:
                    outcome = record.cancel_receipt.outcome
                else:
                    outcome = self.canceller.cancel(binding)
                    self.authority.record_cancel_signal(
                        command.tenant_id,
                        command.run_id,
                        cancel_command_id=command.command_id,
                        outcome=outcome,
                        backend_binding_fingerprint=binding.binding_fingerprint,
                        actor_subject=self.canceller.workload_subject,
                    )
                self.gateway.complete_command(
                    command.tenant_id,
                    command.command_id,
                    worker_id=worker_id,
                )
                completed += 1
                signalled += int(outcome is GISAnalysisCancelOutcome.SIGNALLED)
                reconciliation_required += int(
                    outcome is not GISAnalysisCancelOutcome.SIGNALLED
                )
            except GISAnalysisProviderTransientError as exc:
                delivery = self.gateway.fail_command(
                    command.tenant_id,
                    command.command_id,
                    worker_id=worker_id,
                    error=f"{type(exc).__name__}: {exc}",
                    retry_delay_seconds=self._retry_delay(command),
                )
                if delivery.status is PlatformCommandStatus.FAILED:
                    failed += 1
                else:
                    retry_pending += 1
            except (
                GISAnalysisExecutionError,
                GISAnalysisProviderContractError,
                PlatformGatewayError,
            ) as exc:
                delivery = self.gateway.fail_command(
                    command.tenant_id,
                    command.command_id,
                    worker_id=worker_id,
                    error=f"{type(exc).__name__}: {exc}",
                    retry_delay_seconds=0,
                )
                failed += int(delivery.status is PlatformCommandStatus.FAILED)
                retry_pending += int(delivery.status is not PlatformCommandStatus.FAILED)
        return GISAnalysisCancelBatchResult(
            claimed=len(commands),
            completed=completed,
            signalled=signalled,
            reconciliation_required=reconciliation_required,
            retry_pending=retry_pending,
            failed=failed,
            command_ids=tuple(command.command_id for command in commands),
        )


class GISAnalysisReconciliationCommandConsumer:
    """Re-probe exact PostGIS backends until evidence converges or escalates."""

    def __init__(
        self,
        canceller: PostGISBackendCanceller,
        *,
        gateway: PlatformGateway | None = None,
        authority: GISAnalysisExecutionAuthority | None = None,
    ):
        self.canceller = canceller
        self.gateway = gateway or PlatformGateway()
        self.authority = authority or GISAnalysisExecutionAuthority()

    @staticmethod
    def _retry_delay(command: PlatformCommand) -> int:
        return min(120, 5 * (2 ** max(0, command.attempt_count - 1)))

    @staticmethod
    def _validate_command(
        command: PlatformCommand,
        record: GISAnalysisRunRecord,
    ) -> GISAnalysisBackendBinding:
        admission = record.cancel_admission
        receipt = record.cancel_receipt
        if admission is None or receipt is None:
            raise GISAnalysisProviderContractError(
                "GIS reconciliation command has no cancellation evidence"
            )
        binding = admission.backend
        expected_dedupe = (
            f"gis_analysis.reconcile:{command.tenant_id}:{command.run_id}:"
            f"{receipt.cancel_observation_id}"
        )
        try:
            payload_binding = GISAnalysisBackendBinding.model_validate(
                {
                    "backend_pid": command.payload.get("backend_pid"),
                    "backend_start": command.payload.get("backend_start"),
                    "database_oid": command.payload.get("database_oid"),
                    "user_oid": command.payload.get("user_oid"),
                    "application_name": command.payload.get("application_name"),
                    "binding_fingerprint": command.payload.get(
                        "backend_binding_fingerprint"
                    ),
                }
            )
            deadline = datetime.fromisoformat(
                str(command.payload["reconciliation_deadline"]).replace(
                    "Z", "+00:00"
                )
            )
            max_attempts = int(command.payload["max_reconciliation_attempts"])
        except (KeyError, TypeError, ValueError) as exc:
            raise GISAnalysisProviderContractError(
                "GIS reconciliation command policy is invalid"
            ) from exc
        if (
            command.command_type is not PlatformCommandType.GIS_ANALYSIS_RECONCILE
            or command.dedupe_key != expected_dedupe
            or command.actor_subject != GIS_POSTGIS_RECONCILER_WORKLOAD
            or command.execution_plan_artifact_id
            != record.admission.plan_artifact_id
            or command.trigger_observation_id != admission.start_observation_id
            or command.payload.get("schema")
            != "gda.gis_analysis_reconcile_command.v1"
            or command.payload.get("run_id") != str(command.run_id)
            or command.payload.get("plan_artifact_id")
            != str(record.admission.plan_artifact_id)
            or command.payload.get("cancel_command_id")
            != str(admission.cancel_command_id)
            or command.payload.get("cancel_observation_id")
            != str(receipt.cancel_observation_id)
            or command.payload.get("initial_cancel_outcome")
            != receipt.outcome.value
            or payload_binding != binding
            or deadline.tzinfo is None
            or deadline.utcoffset() is None
            or deadline.astimezone(UTC) < receipt.observed_at
            or not 1 <= max_attempts <= 100
        ):
            raise GISAnalysisProviderContractError(
                "GIS reconciliation command does not bind exact cancellation evidence"
            )
        return binding

    def run_once(
        self,
        tenant_id: str,
        *,
        worker_id: str,
        limit: int = 10,
        lease_seconds: int = 30,
    ) -> GISAnalysisReconciliationBatchResult:
        commands = self.gateway.claim_commands(
            tenant_id,
            worker_id,
            actor_subject=GIS_POSTGIS_RECONCILER_WORKLOAD,
            limit=limit,
            lease_seconds=lease_seconds,
        )
        observed = signalled = retrying = escalated = converged = failed = 0
        for command in commands:
            try:
                record = self.authority.get(command.tenant_id, command.run_id)
                binding = self._validate_command(command, record)
                if record.run.status in TERMINAL_RUN_STATUSES:
                    self.gateway.complete_command(
                        command.tenant_id,
                        command.command_id,
                        worker_id=worker_id,
                    )
                    converged += 1
                    continue
                try:
                    outcome = self.canceller.cancel(binding)
                except GISAnalysisProviderTransientError:
                    outcome = GISAnalysisCancelOutcome.UNKNOWN
                delivery = self.authority.settle_reconciliation(
                    command,
                    worker_id=worker_id,
                    outcome=outcome,
                    backend_binding_fingerprint=binding.binding_fingerprint,
                    retry_delay_seconds=self._retry_delay(command),
                )
                observed += 1
                signalled += int(outcome is GISAnalysisCancelOutcome.SIGNALLED)
                retrying += int(delivery.status is PlatformCommandStatus.PENDING)
                escalated += int(delivery.status is PlatformCommandStatus.FAILED)
            except (
                GISAnalysisExecutionError,
                GISAnalysisProviderContractError,
                PlatformGatewayError,
            ) as exc:
                delivery = self.gateway.fail_command(
                    command.tenant_id,
                    command.command_id,
                    worker_id=worker_id,
                    error=f"{type(exc).__name__}: {exc}",
                    retry_delay_seconds=self._retry_delay(command),
                )
                failed += int(delivery.status is PlatformCommandStatus.FAILED)
                retrying += int(delivery.status is PlatformCommandStatus.PENDING)
        return GISAnalysisReconciliationBatchResult(
            claimed=len(commands),
            observations_recorded=observed,
            signalled=signalled,
            retry_pending=retrying,
            escalated=escalated,
            terminal_converged=converged,
            failed=failed,
            command_ids=tuple(command.command_id for command in commands),
        )


class GISAnalysisCommandConsumer:
    """Deliver PostGIS analysis commands with outbox lease recovery."""

    def __init__(
        self,
        provider: GISAnalysisProvider,
        *,
        gateway: PlatformGateway | None = None,
        authority: GISAnalysisExecutionAuthority | None = None,
        cancel_receipt_wait_seconds: float = 5.0,
    ):
        if (
            provider.engine_name != "postgis"
            or provider.workload_subject != GIS_POSTGIS_WORKLOAD
        ):
            raise GISAnalysisProviderContractError(
                "GIS provider has no governed PostGIS workload identity"
            )
        self.provider = provider
        self.gateway = gateway or PlatformGateway()
        self.authority = authority or GISAnalysisExecutionAuthority()
        if not 0.1 <= cancel_receipt_wait_seconds <= 30:
            raise GISAnalysisProviderContractError(
                "GIS cancellation receipt wait is out of bounds"
            )
        self.cancel_receipt_wait_seconds = cancel_receipt_wait_seconds

    @staticmethod
    def _retry_delay(command: PlatformCommand) -> int:
        return min(300, 5 * (2 ** max(0, command.attempt_count - 1)))

    def _validate_command(
        self,
        command: PlatformCommand,
        record: GISAnalysisRunRecord,
    ) -> None:
        admission = record.admission
        expected_payload = {
            "schema": "gda.gis_analysis_execute_command.v1",
            "run_id": str(admission.run_id),
            "plan_artifact_id": str(admission.plan_artifact_id),
            "plan_fingerprint": admission.plan_fingerprint,
            "cache_key": admission.cache_key,
            "engine": "postgis",
            "execution_mode": "asynchronous",
            "operation": admission.plan.operation.value,
            "algorithm_id": admission.plan.algorithm_id,
            "algorithm_version": admission.plan.algorithm_version,
            "algorithm_spec_fingerprint": admission.plan.algorithm_spec_fingerprint,
        }
        expected_dedupe, expected_command_id = gis_analysis_command_identity(
            admission.tenant_id,
            admission.run_id,
            admission.plan_artifact_id,
            admission.plan_fingerprint,
        )
        if (
            command.command_type is not PlatformCommandType.GIS_ANALYSIS_EXECUTE
            or command.actor_subject != self.provider.workload_subject
            or command.command_id != expected_command_id
            or command.dedupe_key != expected_dedupe
            or command.run_id != admission.run_id
            or command.execution_plan_artifact_id != admission.plan_artifact_id
            or command.payload != expected_payload
            or command.created_at != admission.admitted_at
        ):
            raise GISAnalysisProviderContractError(
                "GIS analysis command does not bind the admitted plan"
            )

    @staticmethod
    def _start_spec(
        command: PlatformCommand,
        *,
        observed_at: datetime,
        backend: GISAnalysisBackendBinding,
    ) -> GISAnalysisProviderStartSpec:
        return GISAnalysisProviderStartSpec(
            attempt_no=1,
            external_namespace="gda/gis-analysis/postgis",
            external_run_id=str(command.command_id),
            external_attempt_id="provider-attempt-1",
            observed_at=observed_at,
            backend=backend,
        )

    @staticmethod
    def _start_observation_id(
        command: PlatformCommand,
        spec: GISAnalysisProviderStartSpec,
    ) -> UUID:
        return uuid5(
            command.run_id,
            f"gis-analysis-start:{spec.attempt_no}:"
            f"{spec.external_namespace}:{spec.external_run_id}",
        )

    def _start(
        self,
        command: PlatformCommand,
        record: GISAnalysisRunRecord,
        backend: GISAnalysisBackendBinding,
    ) -> UUID:
        if record.run.status not in {RunStatus.ACCEPTED, RunStatus.RUNNING}:
            raise GISAnalysisProviderContractError(
                "GIS analysis command found a non-executable Run state"
            )
        spec = self._start_spec(
            command,
            observed_at=self._observed_at(command.created_at),
            backend=backend,
        )
        if record.run.status is RunStatus.ACCEPTED:
            self.authority.start(
                command.tenant_id,
                command.run_id,
                spec,
                actor_subject=self.provider.workload_subject,
                expected_state_version=0,
            )
        return self._start_observation_id(command, spec)

    def _complete_cancelled(
        self,
        command: PlatformCommand,
        start_observation_id: UUID,
        error: GISAnalysisProviderCancelled,
    ) -> None:
        self.authority.complete_cancelled(
            command.tenant_id,
            command.run_id,
            start_observation_id=start_observation_id,
            backend_binding_fingerprint=error.binding.binding_fingerprint,
            actor_subject=self.provider.workload_subject,
            observed_at=self._observed_at(command.created_at),
        )

    def _await_cancel_signal(
        self,
        command: PlatformCommand,
        binding: GISAnalysisBackendBinding,
    ) -> GISAnalysisRunRecord:
        deadline = time.monotonic() + self.cancel_receipt_wait_seconds
        while True:
            record = self.authority.get(command.tenant_id, command.run_id)
            if record.run.status is RunStatus.CANCELLED:
                return record
            receipt = record.cancel_receipt
            if receipt is not None:
                if (
                    receipt.outcome is GISAnalysisCancelOutcome.SIGNALLED
                    and receipt.backend.binding_fingerprint
                    == binding.binding_fingerprint
                ):
                    return record
                raise GISAnalysisProviderContractError(
                    "PostGIS cancellation does not bind a signalled receipt"
                )
            if time.monotonic() >= deadline:
                raise GISAnalysisProviderTransientError(
                    "PostGIS cancellation signal receipt is not visible yet"
                )
            time.sleep(0.02)

    @staticmethod
    def _observed_at(started_at: datetime) -> datetime:
        now = datetime.now(UTC)
        return now if now >= started_at else started_at

    def _complete_success(
        self,
        command: PlatformCommand,
        start_observation_id: UUID,
        result: GISAnalysisProviderResult,
    ) -> None:
        current = self.authority.get(command.tenant_id, command.run_id)
        if current.run.status not in {RunStatus.RUNNING, RunStatus.RECONCILING}:
            raise GISAnalysisProviderContractError(
                "GIS success receipt found a conflicting Run state"
            )
        self.authority.complete(
            command.tenant_id,
            command.run_id,
            GISAnalysisCompletionSpec(
                start_observation_id=start_observation_id,
                outcome=GISAnalysisOutcome.SUCCEEDED,
                features_returned=result.features_returned,
                bytes_scanned=result.bytes_scanned,
                duration_ms=result.duration_ms,
                result_storage_uri=result.storage_uri,
                result_media_type=result.media_type,
                result_sha256=result.sha256,
                result_size_bytes=result.size_bytes,
                result_manifest=result.manifest,
                observed_at=self._observed_at(command.created_at),
            ),
            actor_subject=self.provider.workload_subject,
            expected_state_version=current.run.state_version,
        )

    def _complete_failure(
        self,
        command: PlatformCommand,
        start_observation_id: UUID,
        error: GISAnalysisProviderError,
        *,
        error_code: str | None = None,
    ) -> None:
        message = f"{type(error).__name__}: {error}"[:2048]
        current = self.authority.get(command.tenant_id, command.run_id)
        if current.run.status not in {RunStatus.RUNNING, RunStatus.RECONCILING}:
            raise GISAnalysisProviderContractError(
                "GIS failure receipt found a conflicting Run state"
            )
        self.authority.complete(
            command.tenant_id,
            command.run_id,
            GISAnalysisCompletionSpec(
                start_observation_id=start_observation_id,
                outcome=GISAnalysisOutcome.FAILED,
                duration_ms=0,
                error_code=error_code or error.code,
                error_message=message or "GIS analysis provider failed",
                observed_at=self._observed_at(command.created_at),
            ),
            actor_subject=self.provider.workload_subject,
            expected_state_version=current.run.state_version,
        )

    def run_once(
        self,
        tenant_id: str,
        *,
        worker_id: str,
        limit: int = 10,
        lease_seconds: int = 60,
    ) -> GISAnalysisCommandBatchResult:
        commands = self.gateway.claim_commands(
            tenant_id,
            worker_id,
            actor_subject=self.provider.workload_subject,
            limit=limit,
            lease_seconds=lease_seconds,
        )
        completed = 0
        analysis_succeeded = 0
        analysis_failed = 0
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
                if record.run.status in {RunStatus.CANCELLING, RunStatus.RECONCILING}:
                    delivery = self.gateway.fail_command(
                        command.tenant_id,
                        command.command_id,
                        worker_id=worker_id,
                        error="GIS analysis cancellation is awaiting reconciliation",
                        retry_delay_seconds=self._retry_delay(command),
                    )
                    failed += int(delivery.status is PlatformCommandStatus.FAILED)
                    retry_pending += int(
                        delivery.status is not PlatformCommandStatus.FAILED
                    )
                    continue
                start_observation_id: UUID | None = None

                def start_with_backend(
                    binding: GISAnalysisBackendBinding,
                    command: PlatformCommand = command,
                    record: GISAnalysisRunRecord = record,
                ) -> None:
                    nonlocal start_observation_id
                    start_observation_id = self._start(command, record, binding)

                try:
                    result = self.provider.execute(
                        record.admission.plan,
                        run_id=command.run_id,
                        plan_fingerprint=record.admission.plan_fingerprint,
                        on_backend_ready=start_with_backend,
                    )
                    if start_observation_id is None:
                        raise GISAnalysisProviderContractError(
                            "PostGIS provider did not publish backend start evidence"
                        )
                except GISAnalysisProviderCancelled as exc:
                    if start_observation_id is None:
                        raise GISAnalysisProviderContractError(
                            "PostGIS cancelled before backend start evidence"
                        ) from exc
                    try:
                        cancellation = self._await_cancel_signal(command, exc.binding)
                    except GISAnalysisProviderTransientError as wait_error:
                        delivery = self.gateway.fail_command(
                            command.tenant_id,
                            command.command_id,
                            worker_id=worker_id,
                            error=f"{type(wait_error).__name__}: {wait_error}",
                            retry_delay_seconds=self._retry_delay(command),
                        )
                        failed += int(
                            delivery.status is PlatformCommandStatus.FAILED
                        )
                        retry_pending += int(
                            delivery.status is not PlatformCommandStatus.FAILED
                        )
                        continue
                    if cancellation.run.status is not RunStatus.CANCELLED:
                        self._complete_cancelled(command, start_observation_id, exc)
                    self.gateway.complete_command(
                        command.tenant_id,
                        command.command_id,
                        worker_id=worker_id,
                    )
                    completed += 1
                    continue
                except GISAnalysisProviderTransientError as exc:
                    if start_observation_id is None:
                        raise GISAnalysisProviderContractError(
                            "PostGIS failed before backend start evidence"
                        ) from exc
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
                        analysis_failed += 1
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
                except GISAnalysisProviderError as exc:
                    if start_observation_id is None:
                        raise GISAnalysisProviderContractError(
                            "PostGIS failed before backend start evidence"
                        ) from exc
                    self._complete_failure(command, start_observation_id, exc)
                    self.gateway.complete_command(
                        command.tenant_id,
                        command.command_id,
                        worker_id=worker_id,
                    )
                    completed += 1
                    analysis_failed += 1
                    continue
                self._complete_success(command, start_observation_id, result)
                self.gateway.complete_command(
                    command.tenant_id,
                    command.command_id,
                    worker_id=worker_id,
                )
                completed += 1
                analysis_succeeded += 1
            except (GISAnalysisExecutionError, PlatformGatewayError):
                delivery = self.gateway.fail_command(
                    command.tenant_id,
                    command.command_id,
                    worker_id=worker_id,
                    error="GIS analysis control-plane delivery failed",
                    retry_delay_seconds=self._retry_delay(command),
                )
                if delivery.status is PlatformCommandStatus.FAILED:
                    failed += 1
                else:
                    retry_pending += 1
            except GISAnalysisProviderContractError as exc:
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
        return GISAnalysisCommandBatchResult(
            claimed=len(commands),
            completed=completed,
            analysis_succeeded=analysis_succeeded,
            analysis_failed=analysis_failed,
            retry_pending=retry_pending,
            failed=failed,
            command_ids=tuple(command.command_id for command in commands),
        )


__all__ = [
    "GIS_ANALYSIS_RESULT_MEDIA_TYPE",
    "GISAnalysisCommandBatchResult",
    "GISAnalysisCommandConsumer",
    "GISAnalysisCancelBatchResult",
    "GISAnalysisCancelCommandConsumer",
    "GISAnalysisProvider",
    "GISAnalysisProviderContractError",
    "GISAnalysisProviderCancelled",
    "GISAnalysisProviderError",
    "GISAnalysisProviderResult",
    "GISAnalysisProviderTransientError",
    "GISAnalysisResultLimitError",
    "PostGISAnalysisProvider",
    "PostGISBackendCanceller",
    "gis_analysis_command_identity",
]
