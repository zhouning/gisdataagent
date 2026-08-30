"""Managed process for governed DuckDB Blueprint execution commands."""

from __future__ import annotations

import argparse
import json
import math
import os
import signal
import sys
import tempfile
import threading
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from .db_engine import get_engine
from .duckdb_blueprint_command_consumer import (
    DuckDBBlueprintCommandBatchResult,
    DuckDBBlueprintCommandConsumer,
)
from .duckdb_blueprint_object_store import (
    DuckDBBlueprintObjectStoreError,
    build_s3_duckdb_blueprint_object_store,
    validate_blueprint_s3_input_prefixes,
    validate_blueprint_s3_location,
)
from .duckdb_blueprint_provider import (
    DUCKDB_BLUEPRINT_WORKLOAD,
    DuckDBBlueprintProvider,
    DuckDBBlueprintProviderError,
)
from .observability import get_logger, setup_logging
from .platform_contracts import TenantId
from .platform_gateway import PlatformGateway, PlatformGatewayError

WORKER_SCHEMA = "gda.duckdb_blueprint_command_worker.v1"
DEFAULT_STATUS_FILE = Path("/tmp/gda-duckdb-blueprint-command-worker.json")

load_dotenv(Path(__file__).resolve().parent / ".env", override=False)
setup_logging()
logger = get_logger("duckdb_blueprint_command_worker")


class WorkerConfigurationError(RuntimeError):
    """The worker cannot start safely with its current configuration."""


class WorkerProviderUnavailable(RuntimeError):
    """DuckDB, PyArrow or the local output root is not ready."""

    code = "duckdb_blueprint_provider_unavailable"


class WorkerControlPlaneUnavailable(RuntimeError):
    """The platform control-plane database did not pass its bounded probe."""

    code = "platform_unavailable"


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class DuckDBBlueprintCommandWorkerConfig(_FrozenModel):
    tenant_id: TenantId
    worker_id: str = Field(pattern=r"^worker:[A-Za-z0-9][A-Za-z0-9._:-]{0,246}$")
    output_root: Path
    result_backend: Literal["local", "s3"] = "local"
    output_s3_bucket: str | None = None
    output_s3_prefix: str = "blueprint-duckdb-results/v1"
    input_s3_prefixes: tuple[str, ...] = ()
    batch_size: int = Field(default=1, ge=1, le=4)
    lease_seconds: int = Field(default=900, ge=5, le=3600)
    provider_timeout_ceiling_seconds: Literal[600] = 600
    provider_io_budget_seconds: Literal[240] = 240
    object_store_connect_timeout_seconds: float = Field(default=5, ge=0.1, le=30)
    object_store_read_timeout_seconds: float = Field(default=60, ge=1, le=300)
    retry_delay_seconds: int = Field(default=30, ge=0, le=86_400)
    poll_interval_seconds: float = Field(default=5.0, ge=0.1, le=3600)
    status_file: Path = DEFAULT_STATUS_FILE
    health_max_age_seconds: float = Field(default=1200.0, ge=1, le=7200)

    @model_validator(mode="after")
    def _safe_runtime_bounds(self) -> DuckDBBlueprintCommandWorkerConfig:
        if not self.output_root.is_absolute() or not self.status_file.is_absolute():
            raise ValueError("worker output and status paths must be absolute")
        output_root = self.output_root.expanduser().resolve()
        status_file = self.status_file.expanduser().resolve()
        if output_root == Path(output_root.anchor):
            raise ValueError("DuckDB Blueprint output root must not be a filesystem root")
        if output_root == status_file or output_root in status_file.parents:
            raise ValueError("worker status file must be outside the provider output root")
        if self.result_backend == "s3":
            try:
                validate_blueprint_s3_location(
                    self.output_s3_bucket or "",
                    self.output_s3_prefix,
                )
                validate_blueprint_s3_input_prefixes(self.input_s3_prefixes)
            except ValueError as exc:
                raise ValueError(
                    "DuckDB Blueprint worker S3 result location is invalid"
                ) from exc
        execution_budget = self.batch_size * (
            self.provider_timeout_ceiling_seconds
            + self.provider_io_budget_seconds
            + 30
        )
        if self.lease_seconds <= execution_budget:
            raise ValueError("command lease must cover the full claimed execution batch")
        if self.health_max_age_seconds < (
            self.lease_seconds + (self.poll_interval_seconds * 2)
        ):
            raise ValueError("worker health max age must cover its command lease")
        return self

    @classmethod
    def from_env(cls) -> DuckDBBlueprintCommandWorkerConfig:
        try:
            output_root = str(
                os.getenv("GDA_BLUEPRINT_DUCKDB_OUTPUT_ROOT") or ""
            ).strip()
            if not output_root:
                raise ValueError("GDA_BLUEPRINT_DUCKDB_OUTPUT_ROOT is required")
            return cls(
                tenant_id=str(
                    os.getenv("GDA_BLUEPRINT_DUCKDB_TENANT_ID") or ""
                ).strip(),
                worker_id=str(
                    os.getenv("GDA_BLUEPRINT_DUCKDB_WORKER_ID") or ""
                ).strip(),
                output_root=Path(output_root),
                result_backend=str(
                    os.getenv("GDA_BLUEPRINT_DUCKDB_RESULT_BACKEND") or "local"
                ).strip(),
                output_s3_bucket=(
                    str(
                        os.getenv("GDA_BLUEPRINT_DUCKDB_OUTPUT_S3_BUCKET") or ""
                    ).strip()
                    or None
                ),
                output_s3_prefix=str(
                    os.getenv("GDA_BLUEPRINT_DUCKDB_OUTPUT_S3_PREFIX")
                    or "blueprint-duckdb-results/v1"
                ).strip(),
                input_s3_prefixes=tuple(
                    item.strip()
                    for item in str(
                        os.getenv("GDA_BLUEPRINT_DUCKDB_INPUT_S3_PREFIXES") or ""
                    ).split(",")
                    if item.strip()
                ),
                batch_size=int(
                    os.getenv("GDA_BLUEPRINT_DUCKDB_BATCH_SIZE") or "1"
                ),
                lease_seconds=int(
                    os.getenv("GDA_BLUEPRINT_DUCKDB_LEASE_SECONDS") or "900"
                ),
                provider_timeout_ceiling_seconds=int(
                    os.getenv("GDA_BLUEPRINT_DUCKDB_TIMEOUT_CEILING_SECONDS")
                    or "600"
                ),
                provider_io_budget_seconds=int(
                    os.getenv("GDA_BLUEPRINT_DUCKDB_IO_BUDGET_SECONDS") or "240"
                ),
                object_store_connect_timeout_seconds=float(
                    os.getenv("GDA_BLUEPRINT_DUCKDB_S3_CONNECT_TIMEOUT_SECONDS") or "5"
                ),
                object_store_read_timeout_seconds=float(
                    os.getenv("GDA_BLUEPRINT_DUCKDB_S3_READ_TIMEOUT_SECONDS") or "60"
                ),
                retry_delay_seconds=int(
                    os.getenv("GDA_BLUEPRINT_DUCKDB_RETRY_SECONDS") or "30"
                ),
                poll_interval_seconds=float(
                    os.getenv("GDA_BLUEPRINT_DUCKDB_POLL_SECONDS") or "5"
                ),
                status_file=Path(
                    os.getenv("GDA_BLUEPRINT_DUCKDB_STATUS_FILE")
                    or DEFAULT_STATUS_FILE
                ),
                health_max_age_seconds=float(
                    os.getenv("GDA_BLUEPRINT_DUCKDB_HEALTH_MAX_AGE_SECONDS")
                    or "1200"
                ),
            )
        except (TypeError, ValueError, ValidationError) as exc:
            raise WorkerConfigurationError(
                "DuckDB Blueprint command worker configuration is invalid"
            ) from exc

    def safe_summary(self) -> dict[str, object]:
        return {
            "tenant_id": self.tenant_id,
            "worker_id": self.worker_id,
            "engine": "duckdb",
            "workload_subject": DUCKDB_BLUEPRINT_WORKLOAD,
            "output_root": self.output_root.as_posix(),
            "result_backend": self.result_backend,
            "output_s3_bucket": self.output_s3_bucket,
            "output_s3_prefix": self.output_s3_prefix,
            "input_s3_prefixes": list(self.input_s3_prefixes),
            "batch_size": self.batch_size,
            "lease_seconds": self.lease_seconds,
            "provider_timeout_ceiling_seconds": self.provider_timeout_ceiling_seconds,
            "provider_io_budget_seconds": self.provider_io_budget_seconds,
            "object_store_connect_timeout_seconds": (
                self.object_store_connect_timeout_seconds
            ),
            "object_store_read_timeout_seconds": self.object_store_read_timeout_seconds,
            "retry_delay_seconds": self.retry_delay_seconds,
            "poll_interval_seconds": self.poll_interval_seconds,
            "status_file": self.status_file.as_posix(),
        }


class WorkerStatus(_FrozenModel):
    schema_name: Literal["gda.duckdb_blueprint_command_worker.v1"] = Field(
        default=WORKER_SCHEMA,
        alias="schema",
    )
    state: Literal["starting", "ready", "degraded", "stopped"]
    tenant_id: TenantId
    worker_id: str
    engine: Literal["duckdb"] = "duckdb"
    started_at: datetime
    updated_at: datetime
    last_success_at: datetime | None = None
    cycles: int = Field(default=0, ge=0)
    claimed: int = Field(default=0, ge=0)
    completed: int = Field(default=0, ge=0)
    execution_succeeded: int = Field(default=0, ge=0)
    execution_failed: int = Field(default=0, ge=0)
    terminal_reconciled: int = Field(default=0, ge=0)
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
        return WorkerStatus.model_validate_json(self.path.read_text(encoding="utf-8"))


class DuckDBBlueprintCommandWorker:
    """Own process lifecycle while PostgreSQL retains command state."""

    def __init__(
        self,
        consumer: DuckDBBlueprintCommandConsumer,
        config: DuckDBBlueprintCommandWorkerConfig,
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

    def run_cycle(self) -> DuckDBBlueprintCommandBatchResult | None:
        if self.status is None:
            self._start()
        assert self.status is not None
        try:
            self.provider_probe()
        except WorkerProviderUnavailable as exc:
            self._degrade(exc.code)
            logger.warning("DuckDB Blueprint provider probe failed: %s", exc.code)
            return None
        try:
            result = self.consumer.run_once(
                self.config.tenant_id,
                worker_id=self.config.worker_id,
                limit=self.config.batch_size,
                lease_seconds=self.config.lease_seconds,
            )
        except PlatformGatewayError as exc:
            self._degrade(getattr(exc, "code", WorkerControlPlaneUnavailable.code))
            logger.warning("DuckDB Blueprint control-plane cycle failed")
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
                "execution_succeeded": (
                    self.status.execution_succeeded + result.execution_succeeded
                ),
                "execution_failed": (
                    self.status.execution_failed + result.execution_failed
                ),
                "terminal_reconciled": (
                    self.status.terminal_reconciled + result.terminal_reconciled
                ),
                "retry_pending": self.status.retry_pending + result.retry_pending,
                "failed": self.status.failed + result.failed,
                "consecutive_dependency_failures": 0,
                "last_error_code": None,
            }
        )
        self.status_store.write(self.status)
        return result

    def run(self, *, once: bool = False) -> int:
        self._start()
        try:
            while not self.stop_event.is_set():
                result = self.run_cycle()
                if once:
                    return 0 if result is not None else 1
                if result is None or result.claimed < self.config.batch_size:
                    self.stop_event.wait(self.config.poll_interval_seconds)
        finally:
            assert self.status is not None
            self.status = self.status.model_copy(
                update={"state": "stopped", "updated_at": self.clock()}
            )
            self.status_store.write(self.status)
        return 0


def _valid_probe_window(max_age_seconds: float, now: datetime) -> bool:
    return (
        now.tzinfo is not None
        and now.utcoffset() is not None
        and math.isfinite(max_age_seconds)
        and max_age_seconds > 0
    )


def _evaluate_status(
    status_store: WorkerStatusStore,
    *,
    max_age_seconds: float,
    liveness: bool,
    now: datetime | None = None,
) -> tuple[dict[str, object], bool]:
    current = now or datetime.now(UTC)
    if not _valid_probe_window(max_age_seconds, current):
        return {"status": "unhealthy", "reason": "invalid_probe_window"}, False
    try:
        status = status_store.read()
    except (OSError, ValueError, ValidationError):
        return {"status": "unhealthy", "reason": "status_unavailable"}, False
    reference = status.updated_at if liveness else status.last_success_at
    acceptable_state = status.state != "stopped" if liveness else status.state == "ready"
    if not acceptable_state or reference is None:
        return {
            "status": "unhealthy",
            "reason": f"worker_{status.state}",
            "tenant_id": status.tenant_id,
            "worker_id": status.worker_id,
        }, False
    age_seconds = (current - reference).total_seconds()
    if age_seconds < -5 or age_seconds > max_age_seconds:
        return {
            "status": "unhealthy",
            "reason": "clock_skew" if age_seconds < -5 else "status_stale",
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
        "cycles": status.cycles,
        "execution_succeeded": status.execution_succeeded,
        "execution_failed": status.execution_failed,
        "terminal_reconciled": status.terminal_reconciled,
        "retry_pending": status.retry_pending,
        "failed_commands": status.failed,
    }, True


def evaluate_worker_health(
    status_store: WorkerStatusStore,
    *,
    max_age_seconds: float,
    now: datetime | None = None,
) -> tuple[dict[str, object], bool]:
    return _evaluate_status(
        status_store,
        max_age_seconds=max_age_seconds,
        liveness=False,
        now=now,
    )


def evaluate_worker_liveness(
    status_store: WorkerStatusStore,
    *,
    max_age_seconds: float,
    now: datetime | None = None,
) -> tuple[dict[str, object], bool]:
    return _evaluate_status(
        status_store,
        max_age_seconds=max_age_seconds,
        liveness=True,
        now=now,
    )


def _platform_engine() -> Any:
    try:
        engine = get_engine()
    except (ImportError, SQLAlchemyError, TypeError, ValueError) as exc:
        raise WorkerConfigurationError(
            "platform database configuration is invalid"
        ) from exc
    if engine is None or engine.dialect.name != "postgresql":
        raise WorkerConfigurationError(
            "DuckDB Blueprint worker requires a PostgreSQL platform database"
        )
    return engine


def _probe_platform_database(engine: Any) -> None:
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1")).scalar_one()
    except SQLAlchemyError as exc:
        raise WorkerControlPlaneUnavailable(
            "platform database probe failed"
        ) from exc


def _probe_provider(provider: DuckDBBlueprintProvider, output_root: Path) -> None:
    try:
        provider.probe()
        output_root.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            prefix=".gda-duckdb-probe-",
            dir=output_root,
        ) as handle:
            handle.write(b"ready")
            handle.flush()
    except (DuckDBBlueprintProviderError, OSError) as exc:
        raise WorkerProviderUnavailable(
            "DuckDB Blueprint provider dependencies are unavailable"
        ) from exc


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
            os.getenv("GDA_BLUEPRINT_DUCKDB_STATUS_FILE") or DEFAULT_STATUS_FILE
        )
        try:
            max_age = (
                args.max_age_seconds
                if args.max_age_seconds is not None
                else float(
                    os.getenv("GDA_BLUEPRINT_DUCKDB_HEALTH_MAX_AGE_SECONDS")
                    or "1200"
                )
            )
        except ValueError:
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

    try:
        config = DuckDBBlueprintCommandWorkerConfig.from_env()
        engine = _platform_engine()
        object_store = None
        if config.result_backend == "s3":
            assert config.output_s3_bucket is not None
            try:
                object_store = build_s3_duckdb_blueprint_object_store(
                    bucket=config.output_s3_bucket,
                    prefix=config.output_s3_prefix,
                    input_prefixes=config.input_s3_prefixes,
                    connect_timeout_seconds=(
                        config.object_store_connect_timeout_seconds
                    ),
                    read_timeout_seconds=config.object_store_read_timeout_seconds,
                )
            except DuckDBBlueprintObjectStoreError as exc:
                raise WorkerProviderUnavailable(
                    "DuckDB Blueprint object storage is unavailable"
                ) from exc
        provider = DuckDBBlueprintProvider(
            object_store=object_store,
            workspace_root=config.output_root,
        )
        if args.command == "validate":
            _probe_platform_database(engine)
            _probe_provider(provider, config.output_root)
            _render(
                {
                    "schema": WORKER_SCHEMA,
                    "status": "valid",
                    "config": config.safe_summary(),
                }
            )
            return 0
        gateway = PlatformGateway(
            engine,
            blueprint_duckdb_output_root=config.output_root,
            blueprint_duckdb_result_backend=config.result_backend,
            blueprint_duckdb_output_s3_bucket=config.output_s3_bucket,
            blueprint_duckdb_output_s3_prefix=config.output_s3_prefix,
            blueprint_duckdb_input_s3_prefixes=config.input_s3_prefixes,
            blueprint_duckdb_object_store=object_store,
        )
        consumer = DuckDBBlueprintCommandConsumer(
            gateway=gateway,
            provider=provider,
            retry_delay_seconds=config.retry_delay_seconds,
        )
        worker = DuckDBBlueprintCommandWorker(
            consumer,
            config,
            provider_probe=lambda: _probe_provider(provider, config.output_root),
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


if __name__ == "__main__":
    sys.exit(main())
