"""Managed process for governed PostGIS metric-query commands."""

from __future__ import annotations

import argparse
import json
import math
import os
import signal
import stat
import sys
import threading
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from dotenv import load_dotenv
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError, SQLAlchemyError

from .db_engine import get_engine
from .metric_observation import MetricObservationAuthority
from .metric_query_command_consumer import (
    POSTGIS_WORKLOAD,
    MetricQueryCommandBatchResult,
    MetricQueryCommandConsumer,
    PostGISMetricQueryProvider,
)
from .metric_query_execution import (
    MetricQueryExecutionAuthority,
    MetricQueryExecutionError,
)
from .metric_query_result_store import (
    LocalMetricQueryResultStore,
    MetricQueryResultStore,
    MetricQueryResultStoreUnavailable,
    S3MetricQueryResultStore,
    validate_s3_result_location,
)
from .observability import get_logger, setup_logging
from .platform_contracts import TenantId
from .platform_gateway import PlatformGateway, PlatformGatewayError

WORKER_SCHEMA = "gda.metric_query_command_worker.v1"
DEFAULT_STATUS_FILE = Path("/tmp/gda-metric-query-command-worker.json")

load_dotenv(Path(__file__).resolve().parent / ".env", override=False)
setup_logging()
logger = get_logger("metric_query_command_worker")


class WorkerConfigurationError(RuntimeError):
    """The worker cannot start safely with its current configuration."""


class WorkerProviderUnavailable(RuntimeError):
    """The configured PostGIS provider did not pass its bounded probe."""

    code = "postgis_provider_unavailable"


class WorkerControlPlaneUnavailable(RuntimeError):
    """The platform control-plane database did not pass its bounded probe."""

    code = "platform_unavailable"


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class MetricQueryCommandWorkerConfig(_FrozenModel):
    tenant_id: TenantId
    worker_id: str = Field(
        pattern=r"^worker:[A-Za-z0-9][A-Za-z0-9._:-]{0,246}$"
    )
    provider_database_url_file: Path
    provider_database_role: str = Field(pattern=r"^[a-z_][a-z0-9_]{0,62}$")
    result_backend: Literal["local", "s3"] = "local"
    result_root: Path | None = None
    result_s3_bucket: str | None = None
    result_s3_prefix: str = "metric-query-results/v1"
    result_store_timeout_seconds: int = Field(default=10, ge=1, le=60)
    relation_authority: str = Field(
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,254}$"
    )
    provider_connect_timeout_seconds: int = Field(default=5, ge=1, le=30)
    statement_timeout_ms: int = Field(default=30_000, ge=1, le=1_795_000)
    max_result_rows: int = Field(default=10_000, ge=1, le=1_000_000)
    batch_size: int = Field(default=10, ge=1, le=100)
    lease_seconds: int = Field(default=90, ge=5, le=3600)
    poll_interval_seconds: float = Field(default=5.0, ge=0.1, le=3600)
    status_file: Path = DEFAULT_STATUS_FILE
    health_max_age_seconds: float = Field(default=120.0, ge=1, le=7200)

    @model_validator(mode="after")
    def _safe_runtime_bounds(self) -> MetricQueryCommandWorkerConfig:
        paths = [self.provider_database_url_file, self.status_file]
        if self.result_backend == "local":
            if self.result_root is None:
                raise ValueError("local metric query result root is required")
            if self.result_s3_bucket is not None:
                raise ValueError("local metric query results cannot configure an S3 bucket")
            paths.append(self.result_root)
            resolved_root = self.result_root.expanduser().resolve()
            if resolved_root == Path(resolved_root.anchor):
                raise ValueError("metric query result root must not be a filesystem root")
        else:
            if self.result_root is not None:
                raise ValueError("S3 metric query results cannot configure a local root")
            if self.result_s3_bucket is None:
                raise ValueError("metric query result S3 bucket is required")
            validate_s3_result_location(
                self.result_s3_bucket,
                self.result_s3_prefix,
            )
        if any(not path.is_absolute() for path in paths):
            raise ValueError("worker secret, result, and status paths must be absolute")
        if len({path.resolve() for path in paths}) != len(paths):
            raise ValueError("worker secret, result, and status paths must be distinct")

        # A provider execution may reconnect, then issues evidence and result queries.
        query_budget_seconds = (self.statement_timeout_ms * 2) / 1000
        result_publication_budget_seconds = (
            self.result_store_timeout_seconds * 2
            if self.result_backend == "s3"
            else 0
        )
        execution_budget_seconds = (
            self.provider_connect_timeout_seconds
            + query_budget_seconds
            + result_publication_budget_seconds
        )
        if self.lease_seconds <= execution_budget_seconds:
            raise ValueError(
                "command lease must exceed provider connection and query budgets"
            )
        health_budget_seconds = (
            self.provider_connect_timeout_seconds * 2
            + ((self.statement_timeout_ms * 3) / 1000)
            + (self.poll_interval_seconds * 2)
            + result_publication_budget_seconds
            + (
                self.result_store_timeout_seconds
                if self.result_backend == "s3"
                else 0
            )
        )
        if self.health_max_age_seconds < (
            health_budget_seconds
        ):
            raise ValueError(
                "worker health max age must cover query and polling budgets"
            )
        return self

    @classmethod
    def from_env(cls) -> MetricQueryCommandWorkerConfig:
        try:
            database_url_file = str(
                os.getenv("GDA_METRIC_QUERY_POSTGIS_DATABASE_URL_FILE") or ""
            ).strip()
            result_backend = str(
                os.getenv("GDA_METRIC_QUERY_RESULT_BACKEND") or "local"
            ).strip()
            result_root = str(
                os.getenv("GDA_METRIC_QUERY_RESULT_ROOT") or ""
            ).strip()
            if not database_url_file:
                raise ValueError(
                    "GDA_METRIC_QUERY_POSTGIS_DATABASE_URL_FILE is required"
                )
            if result_backend == "local" and not result_root:
                raise ValueError("GDA_METRIC_QUERY_RESULT_ROOT is required")
            return cls(
                tenant_id=str(
                    os.getenv("GDA_METRIC_QUERY_TENANT_ID") or ""
                ).strip(),
                worker_id=str(
                    os.getenv("GDA_METRIC_QUERY_WORKER_ID") or ""
                ).strip(),
                provider_database_url_file=Path(database_url_file),
                provider_database_role=str(
                    os.getenv("GDA_METRIC_QUERY_POSTGIS_DATABASE_ROLE") or ""
                ).strip(),
                result_backend=result_backend,
                result_root=Path(result_root) if result_root else None,
                result_s3_bucket=(
                    str(
                        os.getenv("GDA_METRIC_QUERY_RESULT_S3_BUCKET") or ""
                    ).strip()
                    or None
                ),
                result_s3_prefix=str(
                    os.getenv("GDA_METRIC_QUERY_RESULT_S3_PREFIX")
                    or "metric-query-results/v1"
                ).strip(),
                result_store_timeout_seconds=int(
                    os.getenv("GDA_METRIC_QUERY_RESULT_STORE_TIMEOUT_SECONDS")
                    or "10"
                ),
                relation_authority=str(
                    os.getenv("GDA_METRIC_QUERY_POSTGIS_RELATION_AUTHORITY") or ""
                ).strip(),
                provider_connect_timeout_seconds=int(
                    os.getenv("GDA_METRIC_QUERY_POSTGIS_CONNECT_TIMEOUT_SECONDS")
                    or "5"
                ),
                statement_timeout_ms=int(
                    os.getenv("GDA_METRIC_QUERY_POSTGIS_STATEMENT_TIMEOUT_MS")
                    or "30000"
                ),
                max_result_rows=int(
                    os.getenv("GDA_METRIC_QUERY_MAX_RESULT_ROWS") or "10000"
                ),
                batch_size=int(
                    os.getenv("GDA_METRIC_QUERY_BATCH_SIZE") or "10"
                ),
                lease_seconds=int(
                    os.getenv("GDA_METRIC_QUERY_LEASE_SECONDS") or "90"
                ),
                poll_interval_seconds=float(
                    os.getenv("GDA_METRIC_QUERY_POLL_INTERVAL_SECONDS") or "5"
                ),
                status_file=Path(
                    os.getenv("GDA_METRIC_QUERY_STATUS_FILE")
                    or DEFAULT_STATUS_FILE
                ),
                health_max_age_seconds=float(
                    os.getenv("GDA_METRIC_QUERY_HEALTH_MAX_AGE_SECONDS") or "120"
                ),
            )
        except (TypeError, ValueError, ValidationError) as exc:
            raise WorkerConfigurationError(
                "metric query command worker configuration is invalid"
            ) from exc

    def provider_database_url(self) -> str:
        path = self.provider_database_url_file
        if not path.is_file():
            raise WorkerConfigurationError(
                "PostGIS provider database URL file is missing or not a regular file"
            )
        try:
            mode = stat.S_IMODE(path.stat().st_mode)
            if mode & 0o077:
                raise WorkerConfigurationError(
                    "PostGIS provider database URL file must be owner-only"
                )
            value = path.read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise WorkerConfigurationError(
                "PostGIS provider database URL file cannot be read"
            ) from exc
        if not value or "\n" in value or "\r" in value:
            raise WorkerConfigurationError(
                "PostGIS provider database URL file must contain one URL"
            )
        try:
            parsed = make_url(value)
        except (ArgumentError, ValueError) as exc:
            raise WorkerConfigurationError(
                "PostGIS provider database URL is invalid"
            ) from exc
        if (
            not parsed.drivername.startswith("postgresql")
            or not parsed.username
            or not parsed.database
        ):
            raise WorkerConfigurationError(
                "PostGIS provider database URL must identify PostgreSQL, a user, and a database"
            )
        if parsed.username != self.provider_database_role:
            raise WorkerConfigurationError(
                "PostGIS provider database URL user does not match the governed role"
            )
        return value

    def safe_summary(self) -> dict[str, object]:
        summary: dict[str, object] = {
            "tenant_id": self.tenant_id,
            "worker_id": self.worker_id,
            "engine": "postgis",
            "workload_subject": POSTGIS_WORKLOAD,
            "provider_database_role": self.provider_database_role,
            "relation_authority": self.relation_authority,
            "result_backend": self.result_backend,
            "provider_connect_timeout_seconds": (
                self.provider_connect_timeout_seconds
            ),
            "statement_timeout_ms": self.statement_timeout_ms,
            "max_result_rows": self.max_result_rows,
            "batch_size": self.batch_size,
            "lease_seconds": self.lease_seconds,
            "poll_interval_seconds": self.poll_interval_seconds,
            "status_file": self.status_file.as_posix(),
            "provider_database_url_file_configured": True,
        }
        if self.result_backend == "local":
            assert self.result_root is not None
            summary["result_root"] = self.result_root.as_posix()
        else:
            summary["result_storage_prefix"] = (
                f"s3://{self.result_s3_bucket}/{self.result_s3_prefix}/"
            )
            summary["result_store_timeout_seconds"] = (
                self.result_store_timeout_seconds
            )
        return summary


class WorkerStatus(_FrozenModel):
    schema_name: Literal["gda.metric_query_command_worker.v1"] = Field(
        default=WORKER_SCHEMA,
        alias="schema",
    )
    state: Literal["starting", "ready", "degraded", "stopped"]
    tenant_id: TenantId
    worker_id: str
    engine: Literal["postgis"] = "postgis"
    started_at: datetime
    updated_at: datetime
    last_success_at: datetime | None = None
    cycles: int = Field(default=0, ge=0)
    claimed: int = Field(default=0, ge=0)
    completed: int = Field(default=0, ge=0)
    query_succeeded: int = Field(default=0, ge=0)
    query_failed: int = Field(default=0, ge=0)
    retry_pending: int = Field(default=0, ge=0)
    failed: int = Field(default=0, ge=0)
    consecutive_dependency_failures: int = Field(default=0, ge=0)
    last_error_code: str | None = None

    @field_validator("started_at", "updated_at", "last_success_at")
    @classmethod
    def _aware_timestamp(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("worker status timestamps must include a timezone")
        return value


class WorkerStatusStore:
    def __init__(self, path: Path):
        self.path = path

    def write(self, status: WorkerStatus) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.parent / f".{self.path.name}.{os.getpid()}.tmp"
        rendered = json.dumps(
            status.model_dump(mode="json", by_alias=True),
            ensure_ascii=True,
            indent=2,
            sort_keys=True,
        )
        try:
            temporary.write_text(rendered + "\n", encoding="utf-8")
            temporary.chmod(0o600)
            os.replace(temporary, self.path)
        finally:
            temporary.unlink(missing_ok=True)

    def read(self) -> WorkerStatus:
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        return WorkerStatus.model_validate(payload)


class MetricQueryCommandWorker:
    """Own process lifecycle while PostgreSQL retains command state."""

    def __init__(
        self,
        consumer: MetricQueryCommandConsumer,
        config: MetricQueryCommandWorkerConfig,
        *,
        provider_probe: Callable[[], None] | None = None,
        status_store: WorkerStatusStore | None = None,
        stop_event: threading.Event | None = None,
        clock: Callable[[], datetime] | None = None,
    ):
        self.consumer = consumer
        self.config = config
        self.provider_probe = provider_probe or (lambda: None)
        self.status_store = status_store or WorkerStatusStore(config.status_file)
        self.stop_event = stop_event or threading.Event()
        self.clock = clock or (lambda: datetime.now(UTC))
        self.status: WorkerStatus | None = None

    def _start(self) -> None:
        now = self.clock()
        self.status = WorkerStatus(
            state="starting",
            tenant_id=self.config.tenant_id,
            worker_id=self.config.worker_id,
            started_at=now,
            updated_at=now,
        )
        self.status_store.write(self.status)

    def _degrade(self, error_code: str) -> None:
        assert self.status is not None
        self.status = self.status.model_copy(
            update={
                "state": "degraded",
                "updated_at": self.clock(),
                "consecutive_dependency_failures": (
                    self.status.consecutive_dependency_failures + 1
                ),
                "last_error_code": error_code,
            }
        )
        self.status_store.write(self.status)

    def run_cycle(self) -> MetricQueryCommandBatchResult | None:
        if self.status is None:
            self._start()
        assert self.status is not None
        try:
            self.provider_probe()
        except WorkerProviderUnavailable as exc:
            self._degrade(exc.code)
            logger.warning("metric query provider probe failed: %s", exc.code)
            return None

        try:
            result = self.consumer.run_once(
                self.config.tenant_id,
                worker_id=self.config.worker_id,
                limit=self.config.batch_size,
                lease_seconds=self.config.lease_seconds,
            )
        except (PlatformGatewayError, MetricQueryExecutionError) as exc:
            self._degrade(exc.code)
            logger.warning("metric query control-plane cycle failed: %s", exc.code)
            return None

        now = self.clock()
        self.status = self.status.model_copy(
            update={
                "state": "ready",
                "updated_at": now,
                "last_success_at": now,
                "cycles": self.status.cycles + 1,
                "claimed": self.status.claimed + result.claimed,
                "completed": self.status.completed + result.completed,
                "query_succeeded": (
                    self.status.query_succeeded + result.query_succeeded
                ),
                "query_failed": self.status.query_failed + result.query_failed,
                "retry_pending": (
                    self.status.retry_pending + result.retry_pending
                ),
                "failed": self.status.failed + result.failed,
                "consecutive_dependency_failures": 0,
                "last_error_code": None,
            }
        )
        self.status_store.write(self.status)
        logger.info(
            "metric query batch claimed=%d completed=%d succeeded=%d "
            "query_failed=%d retry=%d failed=%d",
            result.claimed,
            result.completed,
            result.query_succeeded,
            result.query_failed,
            result.retry_pending,
            result.failed,
        )
        return result

    def run(self, *, once: bool = False) -> int:
        self._start()
        logger.info(
            "metric query command worker starting tenant=%s worker=%s engine=postgis",
            self.config.tenant_id,
            self.config.worker_id,
        )
        exit_code = 0
        try:
            while not self.stop_event.is_set():
                result = self.run_cycle()
                if once:
                    exit_code = 0 if result is not None else 1
                    break
                if result is not None and result.claimed >= self.config.batch_size:
                    continue
                self.stop_event.wait(self.config.poll_interval_seconds)
        finally:
            assert self.status is not None
            self.status = self.status.model_copy(
                update={"state": "stopped", "updated_at": self.clock()}
            )
            self.status_store.write(self.status)
            logger.info("metric query command worker stopped")
        return exit_code


def _valid_probe_window(
    max_age_seconds: float,
    now: datetime,
) -> bool:
    return (
        now.tzinfo is not None
        and now.utcoffset() is not None
        and math.isfinite(max_age_seconds)
        and max_age_seconds > 0
    )


def evaluate_worker_health(
    status_store: WorkerStatusStore,
    *,
    max_age_seconds: float,
    now: datetime | None = None,
) -> tuple[dict[str, object], bool]:
    current = now or datetime.now(UTC)
    if not _valid_probe_window(max_age_seconds, current):
        return {"status": "unhealthy", "reason": "invalid_health_window"}, False
    try:
        status = status_store.read()
    except (OSError, ValueError, json.JSONDecodeError, ValidationError):
        return {"status": "unhealthy", "reason": "status_unavailable"}, False
    if status.state != "ready" or status.last_success_at is None:
        return {
            "status": "unhealthy",
            "reason": f"worker_{status.state}",
            "tenant_id": status.tenant_id,
            "worker_id": status.worker_id,
            "engine": status.engine,
        }, False
    age_seconds = (current - status.last_success_at).total_seconds()
    if age_seconds < -5:
        return {
            "status": "unhealthy",
            "reason": "clock_skew",
            "tenant_id": status.tenant_id,
            "worker_id": status.worker_id,
        }, False
    if age_seconds > max_age_seconds:
        return {
            "status": "unhealthy",
            "reason": "status_stale",
            "age_seconds": round(age_seconds, 3),
            "tenant_id": status.tenant_id,
            "worker_id": status.worker_id,
        }, False
    return {
        "status": "healthy",
        "age_seconds": round(max(0.0, age_seconds), 3),
        "tenant_id": status.tenant_id,
        "worker_id": status.worker_id,
        "engine": status.engine,
        "cycles": status.cycles,
        "query_succeeded": status.query_succeeded,
        "query_failed": status.query_failed,
        "retry_pending": status.retry_pending,
        "failed_commands": status.failed,
    }, True


def evaluate_worker_liveness(
    status_store: WorkerStatusStore,
    *,
    max_age_seconds: float,
    now: datetime | None = None,
) -> tuple[dict[str, object], bool]:
    current = now or datetime.now(UTC)
    if not _valid_probe_window(max_age_seconds, current):
        return {"status": "unhealthy", "reason": "invalid_liveness_window"}, False
    try:
        status = status_store.read()
    except (OSError, ValueError, json.JSONDecodeError, ValidationError):
        return {"status": "unhealthy", "reason": "status_unavailable"}, False
    if status.state == "stopped":
        return {
            "status": "unhealthy",
            "reason": "worker_stopped",
            "tenant_id": status.tenant_id,
            "worker_id": status.worker_id,
        }, False
    age_seconds = (current - status.updated_at).total_seconds()
    if age_seconds < -5:
        return {
            "status": "unhealthy",
            "reason": "clock_skew",
            "tenant_id": status.tenant_id,
            "worker_id": status.worker_id,
        }, False
    if age_seconds > max_age_seconds:
        return {
            "status": "unhealthy",
            "reason": "status_stale",
            "age_seconds": round(age_seconds, 3),
            "tenant_id": status.tenant_id,
            "worker_id": status.worker_id,
        }, False
    return {
        "status": "healthy",
        "worker_state": status.state,
        "age_seconds": round(max(0.0, age_seconds), 3),
        "tenant_id": status.tenant_id,
        "worker_id": status.worker_id,
        "engine": status.engine,
    }, True


def _platform_engine() -> Any:
    try:
        engine = get_engine()
    except (ImportError, SQLAlchemyError, TypeError, ValueError) as exc:
        raise WorkerConfigurationError(
            "platform database configuration is invalid"
        ) from exc
    if engine is None or engine.dialect.name != "postgresql":
        raise WorkerConfigurationError(
            "metric query worker requires a PostgreSQL platform database"
        )
    return engine


def _provider_engine(config: MetricQueryCommandWorkerConfig) -> Any:
    try:
        return create_engine(
            config.provider_database_url(),
            pool_pre_ping=True,
            pool_size=1,
            max_overflow=0,
            pool_recycle=1800,
            connect_args={
                "connect_timeout": config.provider_connect_timeout_seconds
            },
        )
    except (ImportError, SQLAlchemyError, TypeError, ValueError) as exc:
        raise WorkerConfigurationError(
            "PostGIS provider database engine cannot be configured"
        ) from exc


def _build_result_store(
    config: MetricQueryCommandWorkerConfig,
) -> MetricQueryResultStore:
    if config.result_backend == "local":
        assert config.result_root is not None
        return LocalMetricQueryResultStore(config.result_root)
    try:
        import boto3
        from botocore.config import Config as BotoConfig

        endpoint_url = os.getenv("AWS_ENDPOINT_URL") or None
        client_options: dict[str, Any] = {
            "region_name": os.getenv("AWS_REGION") or "us-east-1",
            "config": BotoConfig(
                connect_timeout=config.result_store_timeout_seconds,
                read_timeout=config.result_store_timeout_seconds,
                retries={"total_max_attempts": 1, "mode": "standard"},
                s3={"addressing_style": "path"} if endpoint_url else None,
            ),
        }
        if endpoint_url is not None:
            client_options["endpoint_url"] = endpoint_url
        client = boto3.client("s3", **client_options)
        assert config.result_s3_bucket is not None
        return S3MetricQueryResultStore(
            client,
            bucket=config.result_s3_bucket,
            prefix=config.result_s3_prefix,
        )
    except Exception as exc:
        raise WorkerConfigurationError(
            "metric query result store cannot be configured"
        ) from exc


def _probe_platform_database(engine: Any) -> None:
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1")).scalar_one()
    except SQLAlchemyError as exc:
        raise WorkerControlPlaneUnavailable(
            "platform database probe failed"
        ) from exc


def _probe_postgis(
    engine: Any,
    expected_database_role: str,
    *,
    statement_timeout_ms: int = 5000,
) -> None:
    try:
        with engine.connect() as connection, connection.begin():
            connection.exec_driver_sql("SET TRANSACTION READ ONLY")
            connection.execute(
                text("SELECT set_config('statement_timeout', :timeout, true)"),
                {"timeout": f"{statement_timeout_ms}ms"},
            )
            row = connection.execute(
                text(
                    "SELECT current_user AS database_role, "
                    "current_setting('transaction_read_only') AS read_only, "
                    "PostGIS_Version() AS postgis_version, "
                    "(SELECT rolsuper FROM pg_roles WHERE rolname = current_user) "
                    "AS is_superuser, "
                    "COALESCE((SELECT pg_has_role(current_user, rolname, 'MEMBER') "
                    "FROM pg_roles WHERE rolname = 'gda_control_gateway'), false) "
                    "AS has_platform_gateway_role"
                )
            ).mappings().one()
        if (
            row["database_role"] != expected_database_role
            or row["read_only"] != "on"
            or not row["postgis_version"]
            or row["is_superuser"] is not False
            or row["has_platform_gateway_role"] is not False
        ):
            raise WorkerProviderUnavailable(
                "PostGIS provider identity or read-only probe was rejected"
            )
    except WorkerProviderUnavailable:
        raise
    except SQLAlchemyError as exc:
        raise WorkerProviderUnavailable("PostGIS provider probe failed") from exc


def _probe_result_store(result_store: MetricQueryResultStore) -> None:
    try:
        result_store.probe()
    except MetricQueryResultStoreUnavailable as exc:
        raise WorkerProviderUnavailable(
            "metric query result store probe failed"
        ) from exc


def _probe_provider_dependencies(
    provider_engine: Any,
    config: MetricQueryCommandWorkerConfig,
    result_store: MetricQueryResultStore,
) -> None:
    _probe_postgis(
        provider_engine,
        config.provider_database_role,
        statement_timeout_ms=config.statement_timeout_ms,
    )
    _probe_result_store(result_store)


def _install_signal_handlers(stop_event: threading.Event) -> None:
    def request_stop(signum: int, _frame: object) -> None:
        logger.info("received signal %d; stopping after the current batch", signum)
        stop_event.set()

    signal.signal(signal.SIGINT, request_stop)
    signal.signal(signal.SIGTERM, request_stop)


def _render(value: dict[str, object]) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    run_parser = subparsers.add_parser("run")
    run_parser.add_argument("--once", action="store_true")
    subparsers.add_parser("validate")
    for probe_command in ("health", "liveness"):
        probe_parser = subparsers.add_parser(probe_command)
        probe_parser.add_argument("--status-file", type=Path)
        probe_parser.add_argument("--max-age-seconds", type=float)
    args = parser.parse_args(argv)

    if args.command in {"health", "liveness"}:
        status_file = args.status_file or Path(
            os.getenv("GDA_METRIC_QUERY_STATUS_FILE") or DEFAULT_STATUS_FILE
        )
        try:
            max_age = (
                args.max_age_seconds
                if args.max_age_seconds is not None
                else float(
                    os.getenv("GDA_METRIC_QUERY_HEALTH_MAX_AGE_SECONDS") or "120"
                )
            )
        except ValueError:
            _render({"status": "unhealthy", "reason": "invalid_max_age"})
            return 1
        if not math.isfinite(max_age) or max_age <= 0:
            _render({"status": "unhealthy", "reason": "invalid_max_age"})
            return 1
        evaluator = (
            evaluate_worker_health
            if args.command == "health"
            else evaluate_worker_liveness
        )
        report, healthy = evaluator(
            WorkerStatusStore(status_file),
            max_age_seconds=max_age,
        )
        _render(report)
        return 0 if healthy else 1

    provider_engine: Any | None = None
    try:
        config = MetricQueryCommandWorkerConfig.from_env()
        platform_engine = _platform_engine()
        provider_engine = _provider_engine(config)
        result_store = _build_result_store(config)
        if args.command == "validate":
            _probe_platform_database(platform_engine)
            _probe_provider_dependencies(
                provider_engine,
                config,
                result_store,
            )
            _render(
                {
                    "schema": WORKER_SCHEMA,
                    "status": "valid",
                    "config": config.safe_summary(),
                }
            )
            return 0

        provider = PostGISMetricQueryProvider(
            provider_engine,
            result_store=result_store,
            relation_authority=config.relation_authority,
            statement_timeout_ms=config.statement_timeout_ms,
            max_result_rows=config.max_result_rows,
        )
        gateway = PlatformGateway(platform_engine)
        authority = MetricQueryExecutionAuthority(platform_engine)
        consumer = MetricQueryCommandConsumer(
            provider,
            gateway=gateway,
            authority=authority,
            observation_authority=MetricObservationAuthority(platform_engine),
        )
        worker = MetricQueryCommandWorker(
            consumer,
            config,
            provider_probe=lambda: _probe_provider_dependencies(
                provider_engine,
                config,
                result_store,
            ),
        )
        _install_signal_handlers(worker.stop_event)
        return worker.run(once=args.once)
    except (
        WorkerConfigurationError,
        WorkerControlPlaneUnavailable,
        WorkerProviderUnavailable,
    ) as exc:
        _render(
            {
                "schema": WORKER_SCHEMA,
                "status": "invalid",
                "error": type(exc).__name__,
                "message": str(exc),
            }
        )
        return 2
    finally:
        if provider_engine is not None:
            provider_engine.dispose()


if __name__ == "__main__":
    sys.exit(main())
