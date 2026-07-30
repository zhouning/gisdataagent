"""Managed process for the tenant-scoped Active Metadata consumer."""

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
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from .active_metadata_consumer import (
    ActiveMetadataBatchResult,
    ActiveMetadataConsumer,
)
from .db_engine import get_engine
from .observability import get_logger, setup_logging
from .platform_contracts import TenantId
from .platform_gateway import PlatformGateway, PlatformGatewayError

WORKER_SCHEMA = "gda.active_metadata_consumer_worker.v1"
DEFAULT_STATUS_FILE = Path("/tmp/gda-active-metadata-consumer.json")

load_dotenv(Path(__file__).resolve().parent / ".env", override=False)
setup_logging()
logger = get_logger("active_metadata_consumer_worker")


class ActiveMetadataWorkerConfigurationError(RuntimeError):
    """The worker cannot start safely with its current configuration."""


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ActiveMetadataConsumerWorkerConfig(_FrozenModel):
    enabled: Literal[True]
    tenant_id: TenantId
    worker_id: str = Field(
        pattern=r"^worker:[A-Za-z0-9][A-Za-z0-9._:-]{0,246}$"
    )
    consumer_subject: str = Field(
        pattern=r"^workload:[A-Za-z0-9][A-Za-z0-9._:@/-]{0,247}$"
    )
    batch_size: int = Field(default=10, ge=1, le=100)
    lease_seconds: int = Field(default=60, ge=5, le=3600)
    poll_interval_seconds: float = Field(default=5.0, ge=0.1, le=3600)
    status_file: Path = DEFAULT_STATUS_FILE
    health_max_age_seconds: float = Field(default=30.0, ge=1, le=7200)

    @field_validator("status_file")
    @classmethod
    def _absolute_status_path(cls, value: Path) -> Path:
        if not value.is_absolute():
            raise ValueError("worker status file must be an absolute path")
        return value

    @classmethod
    def from_env(cls) -> ActiveMetadataConsumerWorkerConfig:
        try:
            config = cls(
                enabled=(
                    str(os.getenv("ACTIVE_METADATA_CONSUMER_ENABLED") or "")
                    .strip()
                    .lower()
                    == "true"
                ),
                tenant_id=str(
                    os.getenv("ACTIVE_METADATA_CONSUMER_TENANT_ID") or ""
                ).strip(),
                worker_id=str(
                    os.getenv("ACTIVE_METADATA_CONSUMER_WORKER_ID") or ""
                ).strip(),
                consumer_subject=str(
                    os.getenv("ACTIVE_METADATA_CONSUMER_SUBJECT") or ""
                ).strip(),
                batch_size=int(
                    os.getenv("ACTIVE_METADATA_CONSUMER_BATCH_SIZE") or "10"
                ),
                lease_seconds=int(
                    os.getenv("ACTIVE_METADATA_CONSUMER_LEASE_SECONDS") or "60"
                ),
                poll_interval_seconds=float(
                    os.getenv("ACTIVE_METADATA_CONSUMER_POLL_INTERVAL_SECONDS")
                    or "5"
                ),
                status_file=Path(
                    os.getenv("ACTIVE_METADATA_CONSUMER_STATUS_FILE")
                    or DEFAULT_STATUS_FILE
                ),
                health_max_age_seconds=float(
                    os.getenv("ACTIVE_METADATA_CONSUMER_HEALTH_MAX_AGE_SECONDS")
                    or "30"
                ),
            )
        except (TypeError, ValueError, ValidationError) as exc:
            raise ActiveMetadataWorkerConfigurationError(
                "Active Metadata consumer worker configuration is invalid"
            ) from exc
        if config.health_max_age_seconds < config.poll_interval_seconds * 2:
            raise ActiveMetadataWorkerConfigurationError(
                "worker health max age must cover at least two polling intervals"
            )
        return config

    def safe_summary(self) -> dict[str, object]:
        return {
            "enabled": self.enabled,
            "tenant_id": self.tenant_id,
            "worker_id": self.worker_id,
            "consumer_subject": self.consumer_subject,
            "batch_size": self.batch_size,
            "lease_seconds": self.lease_seconds,
            "poll_interval_seconds": self.poll_interval_seconds,
            "status_file": self.status_file.as_posix(),
            "provider_credentials_configured": False,
            "scheduler_credentials_configured": False,
        }


class ActiveMetadataConsumerWorkerStatus(_FrozenModel):
    schema_name: Literal["gda.active_metadata_consumer_worker.v1"] = Field(
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
    staged: int = Field(default=0, ge=0)
    replayed: int = Field(default=0, ge=0)
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


class ActiveMetadataConsumerStatusStore:
    def __init__(self, path: Path):
        self.path = path

    def write(self, status: ActiveMetadataConsumerWorkerStatus) -> None:
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
            if temporary.exists():
                temporary.unlink()

    def read(self) -> ActiveMetadataConsumerWorkerStatus:
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        return ActiveMetadataConsumerWorkerStatus.model_validate(payload)


class ActiveMetadataConsumerWorker:
    """Own process lifecycle while PostgreSQL retains event/request state."""

    def __init__(
        self,
        consumer: ActiveMetadataConsumer,
        config: ActiveMetadataConsumerWorkerConfig,
        *,
        status_store: ActiveMetadataConsumerStatusStore | None = None,
        stop_event: threading.Event | None = None,
        clock: Callable[[], datetime] | None = None,
    ):
        self.consumer = consumer
        self.config = config
        self.status_store = status_store or ActiveMetadataConsumerStatusStore(
            config.status_file
        )
        self.stop_event = stop_event or threading.Event()
        self.clock = clock or (lambda: datetime.now(UTC))
        self.status: ActiveMetadataConsumerWorkerStatus | None = None

    def _start(self) -> None:
        now = self.clock()
        self.status = ActiveMetadataConsumerWorkerStatus(
            state="starting",
            tenant_id=self.config.tenant_id,
            worker_id=self.config.worker_id,
            started_at=now,
            updated_at=now,
        )
        self.status_store.write(self.status)

    def run_cycle(self) -> ActiveMetadataBatchResult | None:
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
            logger.warning("Active Metadata consumer cycle failed: %s", exc.code)
            return None

        now = self.clock()
        self.status = self.status.model_copy(
            update={
                "state": "ready",
                "updated_at": now,
                "last_success_at": now,
                "cycles": self.status.cycles + 1,
                "claimed": self.status.claimed + result.claimed,
                "staged": self.status.staged + result.staged,
                "replayed": self.status.replayed + result.replayed,
                "retry_pending": self.status.retry_pending + result.retry_pending,
                "failed": self.status.failed + result.failed,
                "consecutive_gateway_failures": 0,
                "last_error_code": None,
            }
        )
        self.status_store.write(self.status)
        logger.info(
            "Active Metadata batch claimed=%d staged=%d replayed=%d retry=%d failed=%d",
            result.claimed,
            result.staged,
            result.replayed,
            result.retry_pending,
            result.failed,
        )
        return result

    def run(self, *, once: bool = False) -> int:
        self._start()
        logger.info(
            "Active Metadata consumer worker starting tenant=%s worker=%s",
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
            logger.info("Active Metadata consumer worker stopped")
        return exit_code


def _evaluate_status(
    status_store: ActiveMetadataConsumerStatusStore,
    *,
    max_age_seconds: float,
    liveness: bool,
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
    if liveness:
        if status.state == "stopped":
            return {"status": "unhealthy", "reason": "worker_stopped"}, False
        reference = status.updated_at
    else:
        if status.state != "ready" or status.last_success_at is None:
            return {
                "status": "unhealthy",
                "reason": f"worker_{status.state}",
            }, False
        reference = status.last_success_at
    age_seconds = (current - reference).total_seconds()
    if age_seconds < -5:
        return {"status": "unhealthy", "reason": "clock_skew"}, False
    if age_seconds > max_age_seconds:
        return {
            "status": "unhealthy",
            "reason": "status_stale",
            "age_seconds": round(age_seconds, 3),
        }, False
    return {
        "status": "healthy",
        "age_seconds": round(max(0.0, age_seconds), 3),
        "tenant_id": status.tenant_id,
        "worker_id": status.worker_id,
        "cycles": status.cycles,
        "failed_requests": status.failed,
    }, True


def evaluate_worker_health(
    status_store: ActiveMetadataConsumerStatusStore,
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
    status_store: ActiveMetadataConsumerStatusStore,
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


def _build_worker(
    config: ActiveMetadataConsumerWorkerConfig,
) -> ActiveMetadataConsumerWorker:
    engine = get_engine()
    if engine is None:
        raise ActiveMetadataWorkerConfigurationError(
            "platform database is not configured"
        )
    gateway = PlatformGateway(engine)
    consumer = ActiveMetadataConsumer(
        gateway,
        consumer_subject=config.consumer_subject,
    )
    return ActiveMetadataConsumerWorker(consumer, config)


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
            os.getenv("ACTIVE_METADATA_CONSUMER_STATUS_FILE")
            or DEFAULT_STATUS_FILE
        )
        try:
            max_age = (
                args.max_age_seconds
                if args.max_age_seconds is not None
                else float(
                    os.getenv("ACTIVE_METADATA_CONSUMER_HEALTH_MAX_AGE_SECONDS")
                    or "30"
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
            ActiveMetadataConsumerStatusStore(status_file),
            max_age_seconds=max_age,
        )
        _render(report)
        return 0 if healthy else 1

    try:
        config = ActiveMetadataConsumerWorkerConfig.from_env()
        if args.command == "validate":
            if get_engine() is None:
                raise ActiveMetadataWorkerConfigurationError(
                    "platform database is not configured"
                )
            _render(
                {
                    "schema": WORKER_SCHEMA,
                    "status": "valid",
                    "config": config.safe_summary(),
                    "provider_apply_authorized": False,
                    "production_scheduler_submission_verified": False,
                    "production_ready": False,
                }
            )
            return 0

        worker = _build_worker(config)
        _install_signal_handlers(worker.stop_event)
        return worker.run(once=args.once)
    except (ActiveMetadataWorkerConfigurationError, OSError) as exc:
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
