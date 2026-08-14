"""Authenticated API for governed ontology model drafts.

These routes expose draft commands, validation and diff only. They do not
write the active ontology tables and are deliberately absent from the public
read-only ontology route set.
"""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any
from urllib.parse import urlsplit

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from ..ontology.drafting import (
    OntologyDraftConflict,
    OntologyDraftForbidden,
    OntologyDraftNotFound,
    OntologyDraftValidationError,
    get_ontology_draft_service,
)
from .helpers import _get_user_from_request, _set_user_context

logger = logging.getLogger("data_agent.api.ontology_draft_routes")

_EDITOR_ROLES = {"admin", "standard_editor"}
_REVIEW_ROLES = {"admin", "standard_editor", "standard_reviewer"}


def _auth(request: Request, *, editor: bool = False):
    user = _get_user_from_request(request)
    if not user:
        return None, None, JSONResponse({"error": "Unauthorized"}, status_code=401)
    username, role = _set_user_context(user)
    if (editor and role not in _EDITOR_ROLES) or (not editor and role not in _REVIEW_ROLES):
        return (
            username,
            role,
            JSONResponse({"error": "Forbidden — ontology editor role required"}, status_code=403),
        )
    return username, role, None


def _service_or_error(request: Request):
    try:
        ontology_key = request.path_params.get("ontology_key")
        # Keep the no-argument call for legacy integrations and test doubles;
        # scoped routes pass the explicit profile key.
        service = (
            get_ontology_draft_service(ontology_key)
            if ontology_key
            else get_ontology_draft_service()
        )
        return service, None
    except Exception:
        logger.exception("ontology draft service unavailable")
        return None, JSONResponse({"error": "ontology draft service unavailable"}, status_code=503)


def _domain_error(exc: Exception) -> JSONResponse:
    if isinstance(exc, OntologyDraftNotFound):
        return JSONResponse({"error": str(exc)}, status_code=404)
    if isinstance(exc, OntologyDraftForbidden):
        return JSONResponse({"error": str(exc)}, status_code=403)
    if isinstance(exc, OntologyDraftConflict):
        payload: dict[str, Any] = {"error": str(exc), "code": "draft_revision_conflict"}
        if exc.current_revision is not None:
            payload["current_revision"] = exc.current_revision
        return JSONResponse(payload, status_code=409)
    if isinstance(exc, OntologyDraftValidationError):
        return JSONResponse({"error": str(exc), "code": "draft_validation_error"}, status_code=400)
    if isinstance(exc, (json.JSONDecodeError, UnicodeDecodeError, ValueError)):
        return JSONResponse({"error": "invalid ontology draft request"}, status_code=400)
    logger.exception("ontology draft request failed")
    return JSONResponse({"error": "ontology draft service unavailable"}, status_code=503)


def _csrf_error(request: Request) -> JSONResponse | None:
    """Reject cross-origin cookie writes while keeping non-browser clients usable."""
    origin = request.headers.get("origin")
    if not origin:
        return None
    origin_parts = urlsplit(origin)
    request_host = request.headers.get("host") or request.url.netloc
    if origin_parts.scheme not in {"http", "https"} or origin_parts.netloc != request_host:
        return JSONResponse(
            {"error": "cross-origin ontology draft write rejected"}, status_code=403
        )
    return None


def _body_string(body: dict[str, Any], field: str, *, required: bool = True) -> str:
    value = body.get(field)
    if value is None and not required:
        return ""
    if not isinstance(value, str):
        raise OntologyDraftValidationError(f"{field} must be a string")
    value = value.strip()
    if required and not value:
        raise OntologyDraftValidationError(f"{field} is required")
    return value


def _draft_id(request: Request) -> str:
    try:
        return str(uuid.UUID(str(request.path_params["draft_id"])))
    except (ValueError, AttributeError, TypeError) as exc:
        raise OntologyDraftValidationError("draft_id must be a UUID") from exc


def _audit(request: Request, username: str, action: str, details: dict[str, Any]) -> None:
    try:
        from ..audit_logger import record_audit

        record_audit(
            username,
            action,
            ip_address=request.client.host if request.client else None,
            details=details,
        )
    except Exception:
        logger.warning("ontology draft audit failed", exc_info=True)


async def list_ontology_drafts(request: Request):
    username, role, error = _auth(request)
    if error:
        return error
    service, error = _service_or_error(request)
    if error:
        return error
    try:
        return JSONResponse(
            {
                "items": service.list_drafts(
                    actor=username,
                    is_admin=role in {"admin", "standard_reviewer"},
                ),
            }
        )
    except Exception as exc:
        return _domain_error(exc)


async def create_ontology_draft(request: Request):
    username, _role, error = _auth(request, editor=True)
    if error:
        return error
    if csrf_error := _csrf_error(request):
        return csrf_error
    service, error = _service_or_error(request)
    if error:
        return error
    try:
        body = await request.json()
        if not isinstance(body, dict):
            raise OntologyDraftValidationError("request body must be an object")
        title = _body_string(body, "title")
        description = _body_string(body, "description", required=False)
        result = service.create_draft(
            actor=username,
            title=title,
            description=description,
        )
        _audit(
            request,
            username,
            "ontology_draft.create",
            {
                "draft_id": result.get("draft_id"),
                "base_hash": result.get("base_content_sha256"),
            },
        )
        return JSONResponse(result, status_code=201)
    except Exception as exc:
        return _domain_error(exc)


async def get_ontology_draft(request: Request):
    username, role, error = _auth(request)
    if error:
        return error
    service, error = _service_or_error(request)
    if error:
        return error
    try:
        return JSONResponse(
            service.get_draft(
                _draft_id(request),
                actor=username,
                is_admin=role in {"admin", "standard_reviewer"},
            )
        )
    except Exception as exc:
        return _domain_error(exc)


async def get_ontology_draft_model(request: Request):
    username, role, error = _auth(request)
    if error:
        return error
    service, error = _service_or_error(request)
    if error:
        return error
    try:
        return JSONResponse(
            service.get_model(
                _draft_id(request),
                actor=username,
                is_admin=role in {"admin", "standard_reviewer"},
                concept_id=request.query_params.get("concept_id") or None,
            )
        )
    except Exception as exc:
        return _domain_error(exc)


async def append_ontology_draft_change(request: Request):
    username, role, error = _auth(request, editor=True)
    if error:
        return error
    if csrf_error := _csrf_error(request):
        return csrf_error
    service, error = _service_or_error(request)
    if error:
        return error
    try:
        body = await request.json()
        if not isinstance(body, dict):
            raise OntologyDraftValidationError("request body must be an object")
        expected_revision = body.get("expected_revision")
        if (
            isinstance(expected_revision, bool)
            or not isinstance(expected_revision, int)
            or expected_revision < 0
        ):
            raise OntologyDraftValidationError("expected_revision must be an integer")
        payload = body.get("payload")
        if not isinstance(payload, dict):
            raise OntologyDraftValidationError("payload must be an object")
        operation = _body_string(body, "operation")
        entity_type = _body_string(body, "entity_type")
        entity_id = _body_string(body, "entity_id", required=False)
        idempotency_key = _body_string(body, "idempotency_key")
        result = service.append_change(
            _draft_id(request),
            actor=username,
            is_admin=role == "admin",
            expected_revision=expected_revision,
            idempotency_key=idempotency_key,
            operation=operation,
            entity_type=entity_type,
            entity_id=entity_id,
            payload=payload,
        )
        _audit(
            request,
            username,
            "ontology_draft.change",
            {
                "draft_id": result.get("draft_id"),
                "revision": result.get("revision"),
                "operation": result.get("operation"),
                "entity_type": result.get("entity_type"),
                "entity_id": result.get("entity_id"),
            },
        )
        return JSONResponse(result, status_code=201)
    except Exception as exc:
        return _domain_error(exc)


async def validate_ontology_draft(request: Request):
    username, role, error = _auth(request)
    if error:
        return error
    service, error = _service_or_error(request)
    if error:
        return error
    try:
        return JSONResponse(
            service.validate_draft(
                _draft_id(request),
                actor=username,
                is_admin=role in {"admin", "standard_reviewer"},
            )
        )
    except Exception as exc:
        return _domain_error(exc)


async def diff_ontology_draft(request: Request):
    username, role, error = _auth(request)
    if error:
        return error
    service, error = _service_or_error(request)
    if error:
        return error
    try:
        return JSONResponse(
            service.diff(
                _draft_id(request),
                actor=username,
                is_admin=role in {"admin", "standard_reviewer"},
            )
        )
    except Exception as exc:
        return _domain_error(exc)


async def submit_ontology_draft(request: Request):
    username, role, error = _auth(request, editor=True)
    if error:
        return error
    if csrf_error := _csrf_error(request):
        return csrf_error
    service, error = _service_or_error(request)
    if error:
        return error
    try:
        body = await request.json()
        if not isinstance(body, dict):
            raise OntologyDraftValidationError("request body must be an object")
        expected_revision = body.get("expected_revision")
        if (
            isinstance(expected_revision, bool)
            or not isinstance(expected_revision, int)
            or expected_revision < 0
        ):
            raise OntologyDraftValidationError("expected_revision must be an integer")
        result = service.submit(
            _draft_id(request),
            actor=username,
            is_admin=role == "admin",
            expected_revision=expected_revision,
        )
        _audit(
            request,
            username,
            "ontology_draft.submit_review",
            {
                "draft_id": result.get("draft_id"),
                "revision": result.get("revision"),
            },
        )
        return JSONResponse(result)
    except Exception as exc:
        return _domain_error(exc)


async def abandon_ontology_draft(request: Request):
    username, role, error = _auth(request, editor=True)
    if error:
        return error
    if csrf_error := _csrf_error(request):
        return csrf_error
    service, error = _service_or_error(request)
    if error:
        return error
    try:
        body = await request.json()
        if not isinstance(body, dict):
            raise OntologyDraftValidationError("request body must be an object")
        expected_revision = body.get("expected_revision")
        if (
            isinstance(expected_revision, bool)
            or not isinstance(expected_revision, int)
            or expected_revision < 0
        ):
            raise OntologyDraftValidationError("expected_revision must be an integer")
        result = service.abandon(
            _draft_id(request),
            actor=username,
            is_admin=role == "admin",
            expected_revision=expected_revision,
        )
        _audit(
            request,
            username,
            "ontology_draft.abandon",
            {
                "draft_id": result.get("draft_id"),
                "revision": result.get("revision"),
            },
        )
        return JSONResponse(result)
    except Exception as exc:
        return _domain_error(exc)


def get_ontology_draft_routes() -> list[Route]:
    prefix = "/api/ontology/drafts"
    legacy = [
        Route(prefix, list_ontology_drafts, methods=["GET"]),
        Route(prefix, create_ontology_draft, methods=["POST"]),
        Route(f"{prefix}/{{draft_id}}/model", get_ontology_draft_model, methods=["GET"]),
        Route(f"{prefix}/{{draft_id}}/changes", append_ontology_draft_change, methods=["POST"]),
        Route(f"{prefix}/{{draft_id}}/validate", validate_ontology_draft, methods=["POST"]),
        Route(f"{prefix}/{{draft_id}}/diff", diff_ontology_draft, methods=["GET"]),
        Route(f"{prefix}/{{draft_id}}/submit", submit_ontology_draft, methods=["POST"]),
        Route(f"{prefix}/{{draft_id}}/abandon", abandon_ontology_draft, methods=["POST"]),
        Route(f"{prefix}/{{draft_id}}", get_ontology_draft, methods=["GET"]),
    ]
    scoped_prefix = "/api/ontologies/{ontology_key}/drafts"
    scoped = [
        Route(scoped_prefix, list_ontology_drafts, methods=["GET"]),
        Route(scoped_prefix, create_ontology_draft, methods=["POST"]),
        Route(f"{scoped_prefix}/{{draft_id}}/model", get_ontology_draft_model, methods=["GET"]),
        Route(
            f"{scoped_prefix}/{{draft_id}}/changes",
            append_ontology_draft_change,
            methods=["POST"],
        ),
        Route(f"{scoped_prefix}/{{draft_id}}/validate", validate_ontology_draft, methods=["POST"]),
        Route(f"{scoped_prefix}/{{draft_id}}/diff", diff_ontology_draft, methods=["GET"]),
        Route(f"{scoped_prefix}/{{draft_id}}/submit", submit_ontology_draft, methods=["POST"]),
        Route(f"{scoped_prefix}/{{draft_id}}/abandon", abandon_ontology_draft, methods=["POST"]),
        Route(f"{scoped_prefix}/{{draft_id}}", get_ontology_draft, methods=["GET"]),
    ]
    return [*legacy, *scoped]
