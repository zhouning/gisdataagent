"""Managed process for the tenant-scoped DolphinScheduler command consumer."""

from __future__ import annotations

import argparse
import json
import math
import os
import signal
import sys
import threading
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

from .db_engine import get_engine
from .dolphinscheduler_adapter import (
    DolphinSchedulerAdapter,
    DolphinSchedulerClient,
    DolphinSchedulerConfigurationError,
    DolphinSchedulerProfile,
    _read_token_file,
)
from .dolphinscheduler_command_consumer import (
    CommandBatchResult,
    DolphinSchedulerCommandConsumer,
)
from .observability import get_logger, setup_logging
from .platform_contracts import TenantId
from .platform_gateway import PlatformGateway, PlatformGatewayError

WORKER_SCHEMA = "gda.dolphinscheduler_command_worker.v1"
DEFAULT_STATUS_FILE = Path("/tmp/gda-dolphinscheduler-command-worker.json")

load_dotenv(Path(__file__).resolve().parent / ".env", override=False)
setup_logging()
logger = get_logger("dolphinscheduler_command_worker")


class WorkerConfigurationError(RuntimeError):
    """The worker cannot start safely with its current configuration."""


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class DolphinSchedulerCommandWorkerConfig(_FrozenModel):
    tenant_id: TenantId
    worker_id: str = Field(
        pattern=r"^worker:[A-Za-z0-9][A-Za-z0-9._:-]{0,246}$"
    )
    base_url: str
    token_file: Path
    project_code: int = Field(gt=0)
    workload_subject: str
    policy_evaluator_subject: str
    tenant_code: str = Field(default="default", min_length=1, max_length=128)
    worker_group: str = Field(default="default", min_length=1, max_length=255)
    request_timeout_seconds: float = Field(default=15.0, gt=0, le=300)
    reconciliation_page_limit: int = Field(default=5, ge=1, le=100)
    batch_size: int = Field(default=10, ge=1, le=100)
    lease_seconds: int = Field(default=60, ge=5, le=3600)
    poll_interval_seconds: float = Field(default=5.0, ge=0.1, le=3600)
    status_file: Path = DEFAULT_STATUS_FILE
    health_max_age_seconds: float = Field(default=30.0, ge=1, le=7200)

    @model_validator(mode="after")
    def _safe_runtime_bounds(self) -> DolphinSchedulerCommandWorkerConfig:
        if not self.token_file.is_absolute():
            raise ValueError("DolphinScheduler token file must be an absolute path")
        if not self.status_file.is_absolute():
            raise ValueError("worker status file must be an absolute path")
        if self.token_file == self.status_file:
            raise ValueError("token and worker status files must be different")
        if self.lease_seconds <= self.request_timeout_seconds:
            raise ValueError("command lease must exceed provider request timeout")
        if self.health_max_age_seconds < self.poll_interval_seconds * 2:
            raise ValueError(
                "worker health max age must cover at least two polling intervals"
            )
        return self

    @classmethod
    def from_env(cls) -> DolphinSchedulerCommandWorkerConfig:
        try:
            token_file = str(
                os.getenv("DOLPHINSCHEDULER_TOKEN_FILE") or ""
            ).strip()
            if not token_file:
                raise ValueError("DOLPHINSCHEDULER_TOKEN_FILE is required")
            return cls(
                tenant_id=str(
                    os.getenv("DOLPHINSCHEDULER_COMMAND_TENANT_ID") or ""
                ).strip(),
                worker_id=str(
                    os.getenv("DOLPHINSCHEDULER_COMMAND_WORKER_ID") or ""
                ).strip(),
                base_url=str(
                    os.getenv("DOLPHINSCHEDULER_BASE_URL") or ""
                ).strip(),
                token_file=Path(token_file),
                project_code=int(
                    os.getenv("DOLPHINSCHEDULER_PROJECT_CODE") or "0"
                ),
                workload_subject=str(
                    os.getenv("DOLPHINSCHEDULER_WORKLOAD_SUBJECT") or ""
                ).strip(),
                policy_evaluator_subject=str(
                    os.getenv("DOLPHINSCHEDULER_POLICY_EVALUATOR_SUBJECT") or ""
                ).strip(),
                tenant_code=str(
                    os.getenv("DOLPHINSCHEDULER_TENANT_CODE") or "default"
                ).strip(),
                worker_group=str(
                    os.getenv("DOLPHINSCHEDULER_WORKER_GROUP") or "default"
                ).strip(),
                request_timeout_seconds=float(
                    os.getenv("DOLPHINSCHEDULER_REQUEST_TIMEOUT_SECONDS") or "15"
                ),
                reconciliation_page_limit=int(
                    os.getenv("DOLPHINSCHEDULER_RECONCILIATION_PAGE_LIMIT") or "5"
                ),
                batch_size=int(
                    os.getenv("DOLPHINSCHEDULER_COMMAND_BATCH_SIZE") or "10"
                ),
                lease_seconds=int(
                    os.getenv("DOLPHINSCHEDULER_COMMAND_LEASE_SECONDS") or "60"
                ),
                poll_interval_seconds=float(
                    os.getenv("DOLPHINSCHEDULER_COMMAND_POLL_INTERVAL_SECONDS")
                    or "5"
                ),
                status_file=Path(
                    os.getenv("DOLPHINSCHEDULER_COMMAND_STATUS_FILE")
                    or DEFAULT_STATUS_FILE
                ),
                health_max_age_seconds=float(
                    os.getenv("DOLPHINSCHEDULER_COMMAND_HEALTH_MAX_AGE_SECONDS")
                    or "30"
                ),
            )
        except (TypeError, ValueError, ValidationError) as exc:
            raise WorkerConfigurationError(
                "DolphinScheduler command worker configuration is invalid"
            ) from exc

    def build_profile(self) -> DolphinSchedulerProfile:
        if not self.token_file.is_file():
            raise WorkerConfigurationError(
                "DolphinScheduler token file is missing or not a regular file"
            )
        try:
            token = _read_token_file(self.token_file)
            return DolphinSchedulerProfile(
                base_url=self.base_url,
                access_token=token,
                project_code=self.project_code,
                workload_subject=self.workload_subject,
                policy_evaluator_subject=self.policy_evaluator_subject,
                tenant_code=self.tenant_code,
                worker_group=self.worker_group,
                request_timeout_seconds=self.request_timeout_seconds,
                reconciliation_page_limit=self.reconciliation_page_limit,
            )
        except (DolphinSchedulerConfigurationError, OSError, ValidationError) as exc:
            raise WorkerConfigurationError(
                "DolphinScheduler provider profile is invalid"
            ) from exc

    def safe_summary(self) -> dict[str, object]:
        return {
            "tenant_id": self.tenant_id,
            "worker_id": self.worker_id,
            "base_url": self.base_url,
            "project_code": self.project_code,
            "workload_subject": self.workload_subject,
            "policy_evaluator_subject": self.policy_evaluator_subject,
            "batch_size": self.batch_size,
            "lease_seconds": self.lease_seconds,
            "poll_interval_seconds": self.poll_interval_seconds,
            "status_file": self.status_file.as_posix(),
            "token_file_configured": True,
        }


class WorkerStatus(_FrozenModel):
    schema_name: Literal["gda.dolphinscheduler_command_worker.v1"] = Field(
        default=WORKER_SCHEMA,
        alias="schema",
    )
    state: Literal["starting", "ready", "degraded", "stopped"]
    tenant_id: TenantId
    worker_id: str
    started_at: datetime
    updated_at: datetime
    last_success_at: datetime | None = None
    cycles: int = Field(default=0, ge=0)
    claimed: int = Field(default=0, ge=0)
    completed: int = Field(default=0, ge=0)
    deferred_to_reconcile: int = Field(default=0, ge=0)
    retry_pending: int = Field(default=0, ge=0)
    failed: int = Field(default=0, ge=0)
    consecutive_gateway_failures: int = Field(default=0, ge=0)
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
        temporary = self.path.parent / (
            f".{self.path.name}.{os.getpid()}.tmp"
        )
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
            if temporary.exists():
                temporary.unlink()

    def read(self) -> WorkerStatus:
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        return WorkerStatus.model_validate(payload)


class DolphinSchedulerCommandWorker:
    """Own worker lifecycle while PostgreSQL retains command state."""

    def __init__(
        self,
        consumer: DolphinSchedulerCommandConsumer,
        config: DolphinSchedulerCommandWorkerConfig,
        *,
        status_store: WorkerStatusStore | None = None,
        stop_event: threading.Event | None = None,
        clock: Callable[[], datetime] | None = None,
    ):
        self.consumer = consumer
        self.config = config
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

    def run_cycle(self) -> CommandBatchResult | None:
        if self.status is None:
            self._start()
        assert self.status is not None
        try:
            result = self.consumer.run_once(
                self.config.tenant_id,
                worker_id=self.config.worker_id,
                limit=self.config.batch_size,
                lease_seconds=self.config.lease_seconds,
            )
        except PlatformGatewayError as exc:
            self.status = self.status.model_copy(
                update={
                    "state": "degraded",
                    "updated_at": self.clock(),
                    "consecutive_gateway_failures": (
                        self.status.consecutive_gateway_failures + 1
                    ),
                    "last_error_code": exc.code,
                }
            )
            self.status_store.write(self.status)
            logger.warning("platform command claim/delivery cycle failed: %s", exc.code)
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
                "deferred_to_reconcile": (
                    self.status.deferred_to_reconcile
                    + result.deferred_to_reconcile
                ),
                "retry_pending": (
                    self.status.retry_pending + result.retry_pending
                ),
                "failed": self.status.failed + result.failed,
                "consecutive_gateway_failures": 0,
                "last_error_code": None,
            }
        )
        self.status_store.write(self.status)
        logger.info(
            "platform command batch claimed=%d completed=%d deferred=%d retry=%d failed=%d",
            result.claimed,
            result.completed,
            result.deferred_to_reconcile,
            result.retry_pending,
            result.failed,
        )
        return result

    def run(self, *, once: bool = False) -> int:
        self._start()
        logger.info(
            "DolphinScheduler command worker starting tenant=%s worker=%s",
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
            logger.info("DolphinScheduler command worker stopped")
        return exit_code


def evaluate_worker_health(
    status_store: WorkerStatusStore,
    *,
    max_age_seconds: float,
    now: datetime | None = None,
) -> tuple[dict[str, object], bool]:
    current = now or datetime.now(UTC)
    if (
        current.tzinfo is None
        or current.utcoffset() is None
        or not math.isfinite(max_age_seconds)
        or max_age_seconds <= 0
    ):
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
        "cycles": status.cycles,
        "failed_commands": status.failed,
    }, True


def evaluate_worker_liveness(
    status_store: WorkerStatusStore,
    *,
    max_age_seconds: float,
    now: datetime | None = None,
) -> tuple[dict[str, object], bool]:
    current = now or datetime.now(UTC)
    if (
        current.tzinfo is None
        or current.utcoffset() is None
        or not math.isfinite(max_age_seconds)
        or max_age_seconds <= 0
    ):
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
    }, True


def _build_worker(
    config: DolphinSchedulerCommandWorkerConfig,
    profile: DolphinSchedulerProfile,
) -> tuple[DolphinSchedulerCommandWorker, DolphinSchedulerClient]:
    engine = get_engine()
    if engine is None:
        raise WorkerConfigurationError("platform database is not configured")
    gateway = PlatformGateway(engine)
    client = DolphinSchedulerClient(profile)
    adapter = DolphinSchedulerAdapter(
        profile,
        gateway=gateway,
        client=client,
    )
    consumer = DolphinSchedulerCommandConsumer(adapter, gateway=gateway)
    return DolphinSchedulerCommandWorker(consumer, config), client


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
            os.getenv("DOLPHINSCHEDULER_COMMAND_STATUS_FILE")
            or DEFAULT_STATUS_FILE
        )
        try:
            max_age = (
                args.max_age_seconds
                if args.max_age_seconds is not None
                else float(
                    os.getenv("DOLPHINSCHEDULER_COMMAND_HEALTH_MAX_AGE_SECONDS")
                    or "30"
                )
            )
        except ValueError:
            _render({"status": "unhealthy", "reason": "invalid_max_age"})
            return 1
        if max_age <= 0:
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
        config = DolphinSchedulerCommandWorkerConfig.from_env()
        profile = config.build_profile()
        if args.command == "validate":
            if get_engine() is None:
                raise WorkerConfigurationError(
                    "platform database is not configured"
                )
            _render(
                {
                    "schema": WORKER_SCHEMA,
                    "status": "valid",
                    "api_profile": profile.api_profile,
                    "server_version": profile.server_version,
                    "config": config.safe_summary(),
                }
            )
            return 0

        worker, client = _build_worker(config, profile)
        _install_signal_handlers(worker.stop_event)
        try:
            return worker.run(once=args.once)
        finally:
            client.close()
    except (WorkerConfigurationError, OSError) as exc:
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
