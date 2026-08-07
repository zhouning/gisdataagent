"""Authenticated executor boundary for governed spatial anonymization Runs."""

from __future__ import annotations

import argparse
import asyncio
import hmac
import stat
from pathlib import Path
from uuid import UUID

import uvicorn
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from .spatial_anonymization_worker import (
    SpatialAnonymizationWorker,
    SpatialAnonymizationWorkerError,
    SpatialAnonymizationWorkerResult,
)

SPATIAL_ANONYMIZATION_EXECUTOR_SCHEMA = (
    "gda.spatial_anonymization_executor.v1"
)


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class SpatialAnonymizationExecutionCommand(_FrozenModel):
    tenant_id: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{0,63}$")
    run_id: UUID


class SpatialAnonymizationExecutionResult(_FrozenModel):
    schema_name: str = Field(
        default=SPATIAL_ANONYMIZATION_EXECUTOR_SCHEMA,
        alias="schema",
    )
    tenant_id: str
    run_id: UUID
    attempt_id: UUID
    request_version_id: UUID
    status: str
    output_table: str
    output_row_count: int | None
    receipt_sha256: str | None
    outcome_event_id: UUID | None
    recovered_from_receipt: bool

    @classmethod
    def from_worker_result(
        cls,
        result: SpatialAnonymizationWorkerResult,
    ) -> SpatialAnonymizationExecutionResult:
        return cls(**result.as_dict())


class SpatialAnonymizationExecutorConfig(_FrozenModel):
    token_file: Path

    def validate_runtime(self) -> None:
        if not self.token_file.is_absolute() or not self.token_file.is_file():
            raise ValueError("executor token file must be an existing absolute file")
        if stat.S_IMODE(self.token_file.stat().st_mode) & 0o077:
            raise ValueError(
                "executor token file must not be group/world accessible"
            )
        if not self.token_file.read_text(encoding="utf-8").strip():
            raise ValueError("executor token file must not be empty")


class SpatialAnonymizationExecutor:
    def __init__(
        self,
        config: SpatialAnonymizationExecutorConfig,
        *,
        worker: SpatialAnonymizationWorker | None = None,
    ):
        config.validate_runtime()
        self.config = config
        self.worker = worker or SpatialAnonymizationWorker()

    def execute(
        self,
        command: SpatialAnonymizationExecutionCommand,
    ) -> SpatialAnonymizationExecutionResult:
        result = self.worker.execute(command.tenant_id, command.run_id)
        return SpatialAnonymizationExecutionResult.from_worker_result(result)


def _bearer_token(request: Request) -> str | None:
    value = request.headers.get("authorization") or ""
    prefix = "Bearer "
    return value[len(prefix) :] if value.startswith(prefix) else None


def create_app(service: SpatialAnonymizationExecutor) -> Starlette:
    async def health(_request: Request) -> JSONResponse:
        return JSONResponse(
            {
                "status": "ok",
                "schema": SPATIAL_ANONYMIZATION_EXECUTOR_SCHEMA,
                "database_authority": "gda-control-postgresql",
            }
        )

    async def execute(request: Request) -> JSONResponse:
        expected = service.config.token_file.read_text(encoding="utf-8").strip()
        actual = _bearer_token(request)
        if actual is None or not hmac.compare_digest(actual, expected):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        try:
            payload = await request.json()
            command = SpatialAnonymizationExecutionCommand.model_validate(payload)
            result = await asyncio.to_thread(service.execute, command)
        except (ValidationError, ValueError):
            return JSONResponse(
                {"error": "invalid_execution_request"},
                status_code=422,
            )
        except SpatialAnonymizationWorkerError as exc:
            return JSONResponse(
                {"error": "execution_failed", "code": exc.code},
                status_code=409,
            )
        except Exception:
            return JSONResponse(
                {"error": "execution_unavailable"},
                status_code=503,
            )
        return JSONResponse(result.model_dump(mode="json", by_alias=True))

    return Starlette(
        routes=[
            Route("/health", health, methods=["GET"]),
            Route(
                "/v1/execute/spatial-anonymization-run",
                execute,
                methods=["POST"],
            ),
        ]
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8091)
    parser.add_argument("--token-file", required=True, type=Path)
    args = parser.parse_args(argv)
    config = SpatialAnonymizationExecutorConfig(
        token_file=args.token_file.resolve(strict=True)
    )
    uvicorn.run(
        create_app(SpatialAnonymizationExecutor(config)),
        host=args.host,
        port=args.port,
        log_level="info",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
