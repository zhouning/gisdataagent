from __future__ import annotations

import hmac
from typing import Annotated

from fastapi import Depends, FastAPI, Header, Query, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from . import __version__
from .config import Settings
from .engine import GwmEngine
from .errors import GwmApiError
from .schemas import CompatibilityRolloutRequest, RolloutRequest


_bearer = HTTPBearer(auto_error=False)


def create_app(settings: Settings | None = None, engine: GwmEngine | None = None) -> FastAPI:
    resolved_settings = settings or Settings.from_environment()
    resolved_engine = engine or GwmEngine(resolved_settings)
    app = FastAPI(
        title="Abu Dhabi Urban Flood GWM API",
        version=__version__,
        description="Offline, database-free inference API for the frozen Abu Dhabi urban-flood GWM.",
        docs_url=None,
        redoc_url=None,
        openapi_url="/openapi.json",
    )
    app.state.settings = resolved_settings
    app.state.engine = resolved_engine

    @app.exception_handler(GwmApiError)
    async def handle_gwm_error(_: Request, error: GwmApiError) -> JSONResponse:
        headers = {"Retry-After": "2"} if error.status_code == 429 else None
        payload = {"error": error.code}
        if error.detail:
            payload["detail"] = error.detail
        return JSONResponse(payload, status_code=error.status_code, headers=headers)

    def require_token(
        credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    ) -> None:
        if (
            credentials is None
            or credentials.scheme.lower() != "bearer"
            or not hmac.compare_digest(credentials.credentials, resolved_settings.api_token)
        ):
            raise GwmApiError("unauthorized", 401)

    @app.get("/health/live", include_in_schema=False)
    def live() -> dict[str, str]:
        return {"status": "alive", "service": "abu-dhabi-gwm-api", "version": __version__}

    @app.get("/health/ready", include_in_schema=False)
    def ready() -> JSONResponse:
        payload = resolved_engine.readiness()
        return JSONResponse(payload, status_code=200 if payload["status"] == "ready" else 503)

    @app.get("/v1/model", dependencies=[Depends(require_token)])
    def model_metadata() -> dict:
        return resolved_engine.model_metadata()

    @app.post("/v1/rollouts", status_code=201, dependencies=[Depends(require_token)])
    def create_rollout(
        payload: RolloutRequest,
        idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    ) -> dict:
        public = resolved_engine.run(
            payload.total_rainfall_mm,
            payload.duration_hours,
            idempotency_key=idempotency_key,
        )
        return resolved_engine.v1_run(str(public["run_id"]))

    @app.get("/v1/runs/{run_id}", dependencies=[Depends(require_token)])
    def get_run(run_id: str) -> dict:
        return resolved_engine.v1_run(run_id)

    @app.get("/v1/runs/{run_id}/map", dependencies=[Depends(require_token)])
    def get_map(run_id: str) -> dict:
        return resolved_engine.map_bootstrap(run_id)

    @app.get("/v1/runs/{run_id}/timeseries", dependencies=[Depends(require_token)])
    def get_timeseries(
        run_id: str,
        time_index: Annotated[int, Query(alias="timeIndex", ge=0)],
    ) -> dict:
        return resolved_engine.map_timeseries(run_id, time_index)

    @app.get("/v1/runs/{run_id}/artifacts/{artifact_name}", dependencies=[Depends(require_token)])
    def get_artifact(run_id: str, artifact_name: str) -> FileResponse:
        path = resolved_engine.artifact_path(run_id, artifact_name)
        media_type = "application/json" if artifact_name == "run.json" else "application/octet-stream"
        return FileResponse(path, media_type=media_type, filename=artifact_name)

    # Compatibility endpoints allow the current GIS Data Agent phase-4 client to
    # switch to this container without changing its response parser.
    @app.get(
        "/api/abu-dhabi/flood/gwm/trained/events",
        dependencies=[Depends(require_token)],
    )
    def compatibility_events() -> dict:
        return resolved_engine.compatibility_events()

    @app.post(
        "/api/abu-dhabi/flood/gwm/trained/rainfall-scenarios",
        status_code=202,
        dependencies=[Depends(require_token)],
    )
    def compatibility_rollout(
        payload: CompatibilityRolloutRequest,
        idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    ) -> dict:
        profile_id = str(resolved_engine.profile["profile_id"])
        if payload.event_id is not None and payload.event_id != profile_id:
            raise GwmApiError("trained_gwm_event_not_admitted", 422)
        return resolved_engine.run(
            payload.total_rainfall_mm,
            payload.duration_hours,
            idempotency_key=idempotency_key,
        )

    @app.get(
        "/api/abu-dhabi/flood/gwm/trained/runs/{run_id}",
        dependencies=[Depends(require_token)],
    )
    def compatibility_run(run_id: str) -> dict:
        return resolved_engine.public_run(run_id)

    @app.get(
        "/api/abu-dhabi/flood/gwm/trained/runs/{run_id}/map",
        dependencies=[Depends(require_token)],
    )
    def compatibility_map(run_id: str) -> dict:
        return resolved_engine.map_bootstrap(run_id)

    @app.get(
        "/api/abu-dhabi/flood/gwm/trained/runs/{run_id}/map/timeseries",
        dependencies=[Depends(require_token)],
    )
    def compatibility_timeseries(
        run_id: str,
        time_index: Annotated[int, Query(ge=0)] = 0,
    ) -> dict:
        return resolved_engine.map_timeseries(run_id, time_index)

    return app
