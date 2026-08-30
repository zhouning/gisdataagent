"""Managed process for release-bound Martin endpoint warmup commands."""

from __future__ import annotations

import argparse
import json
import os
import signal
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlsplit
from uuid import uuid4

from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from .db_engine import get_engine
from .gis_provider_runtime import MartinVectorTileProvider
from .gis_service_endpoint_warmup_consumer import (
    GISServiceEndpointWarmupBatchResult,
    GISServiceEndpointWarmupConsumer,
    LocalWarmupReceiptStore,
    WarmupReceiptStoreError,
    build_s3_warmup_receipt_store,
    validate_warmup_s3_location,
)
from .observability import get_logger, setup_logging
from .platform_contracts import TenantId
from .platform_gateway import PlatformGateway, PlatformGatewayError

WORKER_SCHEMA = "gda.gis_service_endpoint_warmup_worker.v1"
DEFAULT_STATUS_FILE = Path("/tmp/gda-gis-endpoint-warmup-worker.json")
MAX_PROVIDER_REQUESTS_PER_COMMAND = 102

load_dotenv(Path(__file__).resolve().parent / ".env", override=False)
setup_logging()
logger = get_logger("gis_service_endpoint_warmup_worker")


class WarmupWorkerConfigurationError(RuntimeError):
    """The worker cannot start safely with its configured boundaries."""


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class GISServiceEndpointWarmupWorkerConfig(_FrozenModel):
    tenant_id: TenantId
    worker_id: str = Field(
        pattern=r"^worker:[A-Za-z0-9][A-Za-z0-9._:-]{0,246}$"
    )
    martin_origin_uri: str
    receipt_backend: Literal["local", "s3"] = "local"
    receipt_root: Path | None = None
    s3_bucket: str | None = None
    s3_prefix: str | None = None
    s3_connect_timeout_seconds: float = Field(default=5.0, gt=0, le=30)
    s3_read_timeout_seconds: float = Field(default=60.0, gt=0, le=300)
    provider_timeout_seconds: float = Field(default=10.0, gt=0, le=30)
    batch_size: int = Field(default=1, ge=1, le=100)
    lease_seconds: int = Field(default=1200, ge=5, le=3600)
    retry_delay_seconds: int = Field(default=30, ge=0, le=86_400)
    poll_interval_seconds: float = Field(default=5.0, ge=0.1, le=3600)
    status_file: Path = DEFAULT_STATUS_FILE

    @model_validator(mode="after")
    def _safe_runtime(self) -> GISServiceEndpointWarmupWorkerConfig:
        origin = urlsplit(self.martin_origin_uri)
        if (
            origin.scheme not in {"http", "https"}
            or not origin.hostname
            or origin.username is not None
            or origin.password is not None
            or origin.query
            or origin.fragment
        ):
            raise ValueError(
                "Martin origin must be credential-free HTTP(S) without query"
            )
        if not self.status_file.is_absolute():
            raise ValueError("warmup status path must be absolute")
        status_file = self.status_file.expanduser().resolve()
        if status_file == Path(status_file.anchor):
            raise ValueError("warmup status path must not be a filesystem root")
        if self.receipt_backend == "local":
            if self.receipt_root is None or not self.receipt_root.is_absolute():
                raise ValueError(
                    "local warmup receipt backend requires an absolute receipt root"
                )
            receipt_root = self.receipt_root.expanduser().resolve()
            if receipt_root == Path(receipt_root.anchor):
                raise ValueError("warmup receipt root must not be a filesystem root")
            if status_file == receipt_root or receipt_root in status_file.parents:
                raise ValueError(
                    "worker status file must be outside the receipt root"
                )
            if self.s3_bucket is not None or self.s3_prefix is not None:
                raise ValueError(
                    "local warmup receipt backend cannot configure S3 location"
                )
        else:
            if self.receipt_root is not None:
                raise ValueError("S3 warmup receipt backend cannot configure receipt root")
            if not self.s3_bucket or not self.s3_prefix:
                raise ValueError(
                    "S3 warmup receipt backend requires bucket and prefix"
                )
            validate_warmup_s3_location(self.s3_bucket, self.s3_prefix)
        worst_case_seconds = (
            self.provider_timeout_seconds
            * MAX_PROVIDER_REQUESTS_PER_COMMAND
            * self.batch_size
        )
        if self.receipt_backend == "s3":
            worst_case_seconds += (
                3
                * (
                    self.s3_connect_timeout_seconds
                    + self.s3_read_timeout_seconds
                )
                * self.batch_size
            )
        if self.lease_seconds <= worst_case_seconds + 5:
            raise ValueError(
                "command lease must cover every claimed command provider request budget"
            )
        return self

    @classmethod
    def from_env(cls) -> GISServiceEndpointWarmupWorkerConfig:
        try:
            receipt_root_value = str(
                os.getenv("GDA_GIS_WARMUP_RECEIPT_ROOT") or ""
            ).strip()
            backend = str(
                os.getenv("GDA_GIS_WARMUP_RECEIPT_BACKEND") or "local"
            ).strip().lower()
            return cls(
                tenant_id=str(
                    os.getenv("GDA_GIS_WARMUP_TENANT_ID") or ""
                ).strip(),
                worker_id=str(
                    os.getenv("GDA_GIS_WARMUP_WORKER_ID") or ""
                ).strip(),
                martin_origin_uri=str(
                    os.getenv("GDA_GIS_WARMUP_MARTIN_ORIGIN_URI") or ""
                ).strip(),
                receipt_backend=backend,
                receipt_root=Path(receipt_root_value)
                if receipt_root_value
                else None,
                s3_bucket=(
                    str(os.getenv("GDA_GIS_WARMUP_S3_BUCKET") or "").strip()
                    or None
                ),
                s3_prefix=(
                    str(os.getenv("GDA_GIS_WARMUP_S3_PREFIX") or "").strip()
                    or None
                ),
                s3_connect_timeout_seconds=float(
                    os.getenv("GDA_GIS_WARMUP_S3_CONNECT_TIMEOUT_SECONDS") or "5"
                ),
                s3_read_timeout_seconds=float(
                    os.getenv("GDA_GIS_WARMUP_S3_READ_TIMEOUT_SECONDS") or "60"
                ),
                provider_timeout_seconds=float(
                    os.getenv("GDA_GIS_WARMUP_PROVIDER_TIMEOUT_SECONDS") or "10"
                ),
                batch_size=int(
                    os.getenv("GDA_GIS_WARMUP_BATCH_SIZE") or "1"
                ),
                lease_seconds=int(
                    os.getenv("GDA_GIS_WARMUP_LEASE_SECONDS") or "1200"
                ),
                retry_delay_seconds=int(
                    os.getenv("GDA_GIS_WARMUP_RETRY_DELAY_SECONDS") or "30"
                ),
                poll_interval_seconds=float(
                    os.getenv("GDA_GIS_WARMUP_POLL_INTERVAL_SECONDS") or "5"
                ),
                status_file=Path(
                    os.getenv("GDA_GIS_WARMUP_STATUS_FILE")
                    or DEFAULT_STATUS_FILE
                ),
            )
        except (TypeError, ValueError, ValidationError) as exc:
            raise WarmupWorkerConfigurationError(
                "GIS endpoint warmup worker configuration is invalid"
            ) from exc


class GISServiceEndpointWarmupWorker:
    """Long-running process wrapper with a local machine-readable status file."""

    def __init__(
        self,
        config: GISServiceEndpointWarmupWorkerConfig,
        consumer: GISServiceEndpointWarmupConsumer,
    ) -> None:
        self.config = config
        self.consumer = consumer
        self.stop_event = threading.Event()
        self.started_at = datetime.now(UTC)
        self.iterations = 0
        self.claimed = 0
        self.completed = 0
        self.succeeded = 0
        self.retry_pending = 0
        self.failed = 0
        self.last_error: str | None = None
        self.last_iteration_at: datetime | None = None

    @classmethod
    def from_config(
        cls,
        config: GISServiceEndpointWarmupWorkerConfig,
    ) -> GISServiceEndpointWarmupWorker:
        gateway = PlatformGateway(get_engine())
        provider = MartinVectorTileProvider(
            config.martin_origin_uri,
            timeout=config.provider_timeout_seconds,
        )
        if config.receipt_backend == "local":
            assert config.receipt_root is not None
            receipt_store = LocalWarmupReceiptStore(config.receipt_root)
        else:
            assert config.s3_bucket is not None
            assert config.s3_prefix is not None
            try:
                receipt_store = build_s3_warmup_receipt_store(
                    bucket=config.s3_bucket,
                    prefix=config.s3_prefix,
                    connect_timeout_seconds=config.s3_connect_timeout_seconds,
                    read_timeout_seconds=config.s3_read_timeout_seconds,
                )
                receipt_store.probe()
            except (ValueError, WarmupReceiptStoreError) as exc:
                raise WarmupWorkerConfigurationError(
                    "GIS endpoint warmup S3 receipt store is unavailable"
                ) from exc
        consumer = GISServiceEndpointWarmupConsumer(
            gateway,
            provider,
            receipt_store,
            retry_delay_seconds=config.retry_delay_seconds,
        )
        return cls(config, consumer)

    def stop(self) -> None:
        self.stop_event.set()

    def _status(self, state: str) -> dict[str, Any]:
        now = datetime.now(UTC)
        return {
            "schema": WORKER_SCHEMA,
            "state": state,
            "tenant_id": self.config.tenant_id,
            "worker_id": self.config.worker_id,
            "martin_origin": self.config.martin_origin_uri,
            "receipt_backend": self.config.receipt_backend,
            "started_at": self.started_at.isoformat().replace("+00:00", "Z"),
            "updated_at": now.isoformat().replace("+00:00", "Z"),
            "last_iteration_at": (
                None
                if self.last_iteration_at is None
                else self.last_iteration_at.isoformat().replace("+00:00", "Z")
            ),
            "iterations": self.iterations,
            "claimed": self.claimed,
            "completed": self.completed,
            "succeeded": self.succeeded,
            "retry_pending": self.retry_pending,
            "failed": self.failed,
            "last_error": self.last_error,
        }

    def _write_status(self, state: str) -> None:
        path = self.config.status_file.expanduser().resolve()
        path.parent.mkdir(mode=0o750, parents=True, exist_ok=True)
        if path.is_symlink():
            raise WarmupWorkerConfigurationError(
                "warmup worker status file must not be a symlink"
            )
        payload = json.dumps(
            self._status(state),
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
        try:
            descriptor = os.open(
                temporary,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o640,
            )
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            if temporary.exists():
                temporary.unlink()

    def run_once(self) -> GISServiceEndpointWarmupBatchResult:
        result = self.consumer.run_once(
            self.config.tenant_id,
            worker_id=self.config.worker_id,
            limit=self.config.batch_size,
            lease_seconds=self.config.lease_seconds,
        )
        self.iterations += 1
        self.last_iteration_at = datetime.now(UTC)
        self.claimed += result.claimed
        self.completed += result.completed
        self.succeeded += result.succeeded
        self.retry_pending += result.retry_pending
        self.failed += result.failed
        self.last_error = None
        self._write_status("ready")
        return result

    def run_forever(self) -> None:
        self._write_status("starting")
        while not self.stop_event.is_set():
            try:
                self.run_once()
            except PlatformGatewayError as exc:
                self.iterations += 1
                self.last_iteration_at = datetime.now(UTC)
                self.last_error = f"{type(exc).__name__}: {exc}"[:2000]
                logger.error("GIS warmup control plane unavailable: %s", exc)
                self._write_status("degraded")
            if self.stop_event.wait(self.config.poll_interval_seconds):
                break
        self._write_status("stopped")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the managed GIS endpoint warmup command worker"
    )
    parser.add_argument(
        "--once", action="store_true", help="process one command batch and exit"
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        config = GISServiceEndpointWarmupWorkerConfig.from_env()
        worker = GISServiceEndpointWarmupWorker.from_config(config)
    except WarmupWorkerConfigurationError as exc:
        logger.error("GIS warmup worker configuration error: %s", exc)
        return 2

    if args.once:
        try:
            worker.run_once()
        except PlatformGatewayError as exc:
            logger.error("GIS warmup worker failed: %s", exc)
            return 1
        return 0

    def _stop(_signum, _frame) -> None:
        worker.stop()

    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)
    worker.run_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "DEFAULT_STATUS_FILE",
    "GISServiceEndpointWarmupWorker",
    "GISServiceEndpointWarmupWorkerConfig",
    "MAX_PROVIDER_REQUESTS_PER_COMMAND",
    "WORKER_SCHEMA",
    "WarmupWorkerConfigurationError",
    "main",
]
