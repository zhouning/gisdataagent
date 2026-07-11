"""Routes for the traditional static urban livability analysis tab."""

from __future__ import annotations

import asyncio
import json
import os
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from .helpers import _get_user_from_request, _set_user_context
from ..uwm.traditional_livability_analysis import (
    build_traditional_livability_analysis,
    queue_traditional_livability_map,
)
from ..uwm.traditional_livability_facility_dictionary import (
    COMPATIBILITY_SCHEMA,
    DICTIONARY_SCHEMA,
    compute_canonical_content_digest,
    unavailable_compatibility_matrix,
    unavailable_facility_dictionary,
    validate_compatibility_matrix,
    validate_facility_dictionary,
)
from ..uwm.traditional_livability_s6 import analyze_s6_facility_proposal
from ..uwm.traditional_livability_s6_s1_service import (
    HandoffConflict,
    HandoffNotFound,
    TraditionalLivabilityS6S1Service,
)
from ..uwm.traditional_livability_s4 import assess_s4_project
from ..uwm.traditional_livability_s4_project import validate_s4_project_request


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATA_ROOT = ROOT / "data/uwm_public_proxy/chongqing_central"
S1_SCHEMA = "uwm.traditional_livability.s1_assessment.v1"
S7_SCHEMA = "uwm.traditional_livability.s7_siting.v1"
S6_RESOURCE_SCHEMA = "uwm.traditional_livability.s6_fulu_resources.v1"
S6_AUTHORITY_STATUS_SCHEMA = "uwm.traditional_livability.s6_authority_status.v1"
S4_RESOURCE_SCHEMA = "uwm.traditional_livability.s4_resources.v1"
S6_RESOURCE_FILES = {
    "resources": "uwm_traditional_livability_s6_resources.json",
    "dictionary": "uwm_traditional_livability_s6_dictionary.json",
    "compatibility": "uwm_traditional_livability_s6_compatibility.json",
}
S6_SCHEMAS = {
    "resources": S6_RESOURCE_SCHEMA,
    "dictionary": DICTIONARY_SCHEMA,
    "compatibility": COMPATIBILITY_SCHEMA,
}
S4_ENGINE_INPUT_BLOCKERS = {
    "analysis_area_id_missing",
    "confirmed_class_authoritative_mismatch",
    "confirmed_class_confirmation_mismatch",
    "confirmed_class_requires_valid_human_confirmation",
    "confirmed_standard_class_id_mismatch",
    "invalid_point_coordinates",
    "original_input_digest_mismatch",
    "original_input_digest_missing",
    "planning_parcel_id_missing",
    "point_outside_selected_area",
    "unsupported_input_mode",
    "actor_id_missing",
    "confirmed_at_invalid",
    "confirmed_at_missing",
    "confirmed_at_timezone_missing",
    "dictionary_version_mismatch",
    "dictionary_version_missing",
    "selected_candidate_class_mismatch",
    "selected_candidate_evidence_mismatch",
    "selected_candidate_evidence_missing",
    "selected_standard_class_id_missing",
}
S4_ENGINE_INPUT_BLOCKER_PREFIXES = (
    "human_selected_",
    "unknown_analysis_area:",
    "unknown_planning_parcel:",
    "planning_parcel_distance_crs_mismatch:",
    "planning_parcel_geometry_missing:",
    "planning_parcel_outside_",
)

_S6_S1_SERVICE: TraditionalLivabilityS6S1Service | None = None


def configure_s6_s1_service(service: TraditionalLivabilityS6S1Service | None) -> None:
    global _S6_S1_SERVICE
    _S6_S1_SERVICE = service


def _get_s6_s1_service() -> TraditionalLivabilityS6S1Service:
    if _S6_S1_SERVICE is None:
        raise RuntimeError("s6_s1_product_not_configured")
    return _S6_S1_SERVICE


class S1SnapshotUnavailable(RuntimeError):
    def __init__(self, payload: dict):
        super().__init__("traditional livability S1 snapshot unavailable")
        self.payload = payload


class S7SnapshotUnavailable(RuntimeError):
    def __init__(self, payload: dict):
        super().__init__("traditional livability S7 snapshot unavailable")
        self.payload = payload


class S6SnapshotUnavailable(RuntimeError):
    def __init__(self, payload: dict):
        super().__init__("traditional livability S6 snapshot unavailable")
        self.payload = payload


def _scene_path() -> Path:
    configured = os.environ.get("UWM_TRADITIONAL_LIVABILITY_SCENE_PATH", "").strip()
    if configured:
        return Path(configured).expanduser()
    return (
        DEFAULT_DATA_ROOT
        / "multisource_livability_scene_2026_07_06/uwm_multisource_livability_scene.json"
    )


def _admin_units_path() -> Path:
    configured = os.environ.get("UWM_TRADITIONAL_LIVABILITY_ADMIN_GEOJSON", "").strip()
    if configured:
        return Path(configured).expanduser()
    return DEFAULT_DATA_ROOT / "admin_units/chongqing_township_admin_units.geojson"


def _s1_path() -> Path:
    configured = os.environ.get("UWM_TRADITIONAL_LIVABILITY_S1_PATH", "").strip()
    if configured:
        return Path(configured).expanduser()
    return DEFAULT_DATA_ROOT / "traditional_livability_phase1a/uwm_traditional_livability_s1.json"


def _load_s1_snapshot() -> dict:
    path = _s1_path()
    if not path.is_file():
        raise S1SnapshotUnavailable(
            {
                "schema": S1_SCHEMA,
                "ready": False,
                "blockers": ["s1_snapshot_missing"],
                "claim_boundary": {
                    "assessment_fabricated": False,
                    "source_path_disclosed": False,
                },
            }
        )
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema") != S1_SCHEMA:
        raise S1SnapshotUnavailable(
            {
                "schema": S1_SCHEMA,
                "ready": False,
                "blockers": ["s1_snapshot_schema_invalid"],
                "claim_boundary": {"assessment_fabricated": False},
            }
        )
    return payload


def _load_required_s4_s1_snapshot() -> dict:
    payload = _load_s1_snapshot()
    if not isinstance(payload.get("supply_metrics"), list):
        raise S1SnapshotUnavailable(
            {
                "schema": S1_SCHEMA,
                "ready": False,
                "blockers": ["s1_snapshot_contract_invalid"],
                "claim_boundary": {"assessment_fabricated": False},
            }
        )
    provided_digest = payload.get("content_digest")
    try:
        digest_valid = (
            isinstance(provided_digest, str)
            and provided_digest
            and compute_canonical_content_digest(payload) == provided_digest
        )
    except Exception:
        digest_valid = False
    if not digest_valid:
        blocker = (
            "s1_snapshot_digest_missing"
            if not isinstance(provided_digest, str) or not provided_digest
            else "s1_snapshot_digest_mismatch"
        )
        raise S1SnapshotUnavailable(
            {
                "schema": S1_SCHEMA,
                "ready": False,
                "blockers": [blocker],
                "claim_boundary": {"assessment_fabricated": False},
            }
        )
    return payload


def _s7_path() -> Path:
    configured = os.environ.get("UWM_TRADITIONAL_LIVABILITY_S7_PATH", "").strip()
    if configured:
        return Path(configured).expanduser()
    return DEFAULT_DATA_ROOT / "traditional_livability_s7_fulu/uwm_traditional_livability_s7.json"


def _load_s7_snapshot() -> dict:
    path = _s7_path()
    if not path.is_file():
        raise S7SnapshotUnavailable(
            {
                "schema": S7_SCHEMA,
                "ready": False,
                "blockers": ["s7_snapshot_missing"],
                "claim_boundary": {
                    "recommendation_fabricated": False,
                    "source_path_disclosed": False,
                },
            }
        )
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schema") != S7_SCHEMA:
        raise S7SnapshotUnavailable(
            {
                "schema": S7_SCHEMA,
                "ready": False,
                "blockers": ["s7_snapshot_schema_invalid"],
                "claim_boundary": {"recommendation_fabricated": False},
            }
        )
    return payload


def _resolve_s6_path(snapshot: str) -> Path:
    filename = S6_RESOURCE_FILES[snapshot]
    configured = os.environ.get("UWM_TRADITIONAL_LIVABILITY_S6_PATH", "").strip()
    if configured:
        path = Path(configured).expanduser()
        if path.is_dir() or path.suffix.lower() != ".json":
            return path / filename
        return path if snapshot == "resources" else path.parent / filename
    return DEFAULT_DATA_ROOT / "traditional_livability_s6_fulu" / filename


def _s6_unavailable_payload(snapshot: str, blocker: str) -> dict:
    return {
        "schema": S6_SCHEMAS[snapshot],
        "ready": False,
        "blockers": [blocker],
        "claim_boundary": {
            "analysis_fabricated": False,
            "source_path_disclosed": False,
        },
    }


def _load_s6_snapshot(snapshot: str) -> dict:
    path = _resolve_s6_path(snapshot)
    if not path.is_file():
        raise S6SnapshotUnavailable(
            _s6_unavailable_payload(snapshot, f"s6_{snapshot}_snapshot_missing")
        )
    try:
        payload = json.loads(
            path.read_text(encoding="utf-8"),
            parse_constant=lambda value: (_ for _ in ()).throw(
                ValueError(f"non-finite JSON constant: {value}")
            ),
        )
        json.dumps(payload, ensure_ascii=False, allow_nan=False)
    except Exception as exc:
        raise S6SnapshotUnavailable(
            _s6_unavailable_payload(snapshot, f"s6_{snapshot}_snapshot_unreadable")
        ) from exc
    if not isinstance(payload, dict) or payload.get("schema") != S6_SCHEMAS[snapshot]:
        raise S6SnapshotUnavailable(
            _s6_unavailable_payload(snapshot, f"s6_{snapshot}_snapshot_schema_invalid")
        )
    if snapshot == "resources":
        if (
            payload.get("ready") is not True
            or not isinstance(payload.get("scope"), str)
            or not payload["scope"].strip()
            or any(
                not isinstance(payload.get(field), list)
                for field in (
                    "planning_areas",
                    "planning_resources",
                    "current_facilities",
                )
            )
        ):
            raise S6SnapshotUnavailable(
                _s6_unavailable_payload(
                    snapshot, "s6_resources_snapshot_contract_invalid"
                )
            )
        provided_digest = payload.get("content_digest")
        if not isinstance(provided_digest, str) or not provided_digest.strip():
            raise S6SnapshotUnavailable(
                _s6_unavailable_payload(
                    snapshot, "s6_resources_snapshot_digest_missing"
                )
            )
        try:
            computed_digest = compute_canonical_content_digest(payload)
        except Exception as exc:
            raise S6SnapshotUnavailable(
                _s6_unavailable_payload(
                    snapshot, "s6_resources_snapshot_digest_mismatch"
                )
            ) from exc
        if provided_digest != computed_digest:
            raise S6SnapshotUnavailable(
                _s6_unavailable_payload(
                    snapshot, "s6_resources_snapshot_digest_mismatch"
                )
            )
        return payload
    return _revalidate_s6_authority_snapshot(snapshot, payload)


def _authority_source_payload(snapshot: str, payload: dict) -> dict:
    metadata = payload.get("source_metadata") or {}
    effective_date = metadata.get("effective_date")
    version_date = metadata.get("version_date")
    date_fields = {"version_date": version_date}
    if effective_date != version_date:
        date_fields["effective_date"] = effective_date
    if snapshot == "dictionary":
        return {
            "schema": DICTIONARY_SCHEMA,
            "dictionary_version": metadata.get("dictionary_version"),
            "issuing_organization": metadata.get("issuing_organization"),
            "source_reference": metadata.get("source_reference"),
            **date_fields,
            "imported_at": metadata.get("imported_at"),
            "authoritative_complete_43_class_dictionary": payload.get(
                "authoritative_complete_43_class_dictionary"
            ),
            "classes": payload.get("classes"),
            "aliases": payload.get("aliases"),
            "keywords": payload.get("keywords"),
            "content_digest": payload.get("provided_content_digest"),
        }
    return {
        "schema": COMPATIBILITY_SCHEMA,
        "matrix_version": metadata.get("matrix_version"),
        "issuing_organization": metadata.get("issuing_organization"),
        "source_reference": metadata.get("source_reference"),
        **date_fields,
        "imported_at": metadata.get("imported_at"),
        "rules": payload.get("rules"),
        "content_digest": payload.get("provided_content_digest"),
    }


def _revalidate_s6_authority_snapshot(snapshot: str, payload: dict) -> dict:
    if payload.get("ready") is False and payload.get("status") in {
        "dictionary_unavailable",
        "compatibility_matrix_unavailable",
    }:
        validator = (
            validate_facility_dictionary
            if snapshot == "dictionary"
            else validate_compatibility_matrix
        )
        validator(_authority_source_payload(snapshot, payload))
        return (
            unavailable_facility_dictionary()
            if snapshot == "dictionary"
            else unavailable_compatibility_matrix()
        )
    source_payload = _authority_source_payload(snapshot, payload)
    if snapshot == "dictionary":
        return validate_facility_dictionary(source_payload)
    return validate_compatibility_matrix(source_payload)


def _load_optional_s6_snapshot(snapshot: str) -> dict:
    try:
        return _load_s6_snapshot(snapshot)
    except S6SnapshotUnavailable as exc:
        if snapshot == "dictionary":
            payload = unavailable_facility_dictionary()
        else:
            payload = unavailable_compatibility_matrix()
        payload["blockers"] = list(
            dict.fromkeys([*(payload.get("blockers") or []), *exc.payload["blockers"]])
        )
        return payload


def _s6_authority_status(
    dictionary: dict,
    compatibility: dict,
) -> dict:
    dictionary_blockers = list(
        dictionary.get("blockers") or dictionary.get("production_blockers") or []
    )
    compatibility_blockers = list(
        compatibility.get("blockers")
        or compatibility.get("production_blockers")
        or []
    )
    dictionary_metadata = dictionary.get("source_metadata") or {}
    compatibility_metadata = compatibility.get("source_metadata") or {}
    dictionary_classes = []
    if dictionary.get("ready") is True:
        for row in dictionary.get("classes") or []:
            if not isinstance(row, dict):
                continue
            class_id = row.get("class_id")
            label = row.get("label")
            if isinstance(class_id, str) and class_id and isinstance(label, str) and label:
                dictionary_classes.append({"class_id": class_id, "label": label})
    dictionary_status = {
        "status": dictionary.get("status"),
        "version": dictionary_metadata.get("dictionary_version"),
        "ready": dictionary.get("ready") is True,
        "blockers": dictionary_blockers,
        "content_digest": dictionary.get("content_digest"),
        "classes": dictionary_classes,
    }
    compatibility_status = {
        "status": compatibility.get("status"),
        "version": compatibility_metadata.get("matrix_version"),
        "ready": compatibility.get("ready") is True,
        "blockers": compatibility_blockers,
    }
    return {
        "schema": S6_AUTHORITY_STATUS_SCHEMA,
        "ready": dictionary_status["ready"] and compatibility_status["ready"],
        "blockers": list(
            dict.fromkeys([*dictionary_blockers, *compatibility_blockers])
        ),
        "facility_dictionary": dictionary_status,
        "compatibility_matrix": compatibility_status,
    }


def _snapshot_blockers(payload: dict) -> list[str]:
    return list(
        payload.get("blockers")
        or payload.get("production_blockers")
        or []
    )


def _s4_resources_payload(
    s1_snapshot: dict,
    s6_resources: dict,
    dictionary: dict,
    compatibility: dict,
) -> dict:
    parcels = []
    for row in s6_resources.get("planning_resources") or []:
        if not isinstance(row, dict):
            continue
        parcel_id = row.get("resource_id")
        area_id = row.get("planning_area_id")
        if not isinstance(parcel_id, str) or not parcel_id or not isinstance(area_id, str) or not area_id:
            continue
        parcels.append(
            {
                "planning_parcel_id": parcel_id,
                "analysis_area_id": area_id,
                "raw_land_use_code": row.get("raw_land_use_code"),
                "raw_land_use_name": row.get("raw_land_use_name"),
                "resource_domain": row.get("resource_domain"),
                "planning_status": row.get("planning_status"),
                "display_geometry_wgs84": row.get("display_geometry_wgs84"),
            }
        )
    classes = []
    if dictionary.get("ready") is True:
        for row in dictionary.get("classes") or []:
            if not isinstance(row, dict):
                continue
            class_id = row.get("class_id")
            label = row.get("label")
            if isinstance(class_id, str) and class_id and isinstance(label, str) and label:
                classes.append({"class_id": class_id, "label": label})
    inventory = s6_resources.get("facility_inventory") or {}
    s1_blockers = _snapshot_blockers(s1_snapshot)
    resource_blockers = _snapshot_blockers(s6_resources)
    dictionary_blockers = _snapshot_blockers(dictionary)
    compatibility_blockers = _snapshot_blockers(compatibility)
    return {
        "schema": S4_RESOURCE_SCHEMA,
        "planning_parcels": parcels,
        "facility_classes": classes,
        "readiness": {
            "s1": {
                "ready": s1_snapshot.get("ready") is not False,
                "complete": not s1_blockers,
                "blockers": s1_blockers,
            },
            "s6_resources": {
                "ready": s6_resources.get("ready") is True,
                "complete": inventory.get("complete_inventory") is True,
                "blockers": resource_blockers,
            },
            "dictionary": {
                "ready": dictionary.get("ready") is True,
                "complete": dictionary.get("authoritative_complete_43_class_dictionary") is True,
                "blockers": dictionary_blockers,
            },
            "compatibility": {
                "ready": compatibility.get("ready") is True,
                "complete": compatibility.get("ready") is True,
                "blockers": compatibility_blockers,
            },
        },
    }


def _validate_s4_parcel(project: dict, resources: dict) -> list[str]:
    normalized = project.get("normalized_request") or {}
    area_id = normalized.get("analysis_area_id")
    parcel_id = normalized.get("planning_parcel_id")
    candidates = [
        row
        for row in resources.get("planning_resources") or []
        if isinstance(row, dict) and row.get("resource_id") == parcel_id
    ]
    if not candidates:
        return [f"unknown_planning_parcel:{parcel_id}"]
    if not any(row.get("planning_area_id") == area_id for row in candidates):
        return [f"planning_parcel_outside_analysis_area:{parcel_id}"]
    return []


def _bind_s4_confirmation_actors(payload: dict, actor_id: str) -> dict:
    rebound = deepcopy(payload)
    uses = rebound.get("uses")
    if not isinstance(uses, list):
        return rebound
    for use in uses:
        if not isinstance(use, dict):
            continue
        confirmation = use.get("human_confirmation")
        if isinstance(confirmation, dict):
            confirmation["actor_id"] = actor_id
    return rebound


def _s4_engine_input_blockers(result: dict) -> list[str]:
    candidates = []
    for value in result.get("validation_blockers") or []:
        candidates.append(str(value))
    for assessment in result.get("use_assessments") or []:
        if not isinstance(assessment, dict):
            continue
        for value in assessment.get("blockers") or []:
            candidates.append(str(value))
    return list(
        dict.fromkeys(
            blocker
            for blocker in candidates
            if blocker in S4_ENGINE_INPUT_BLOCKERS
            or blocker.startswith(S4_ENGINE_INPUT_BLOCKER_PREFIXES)
        )
    )


def _load_default_analysis(top_n: int = 8) -> dict:
    scene = json.loads(_scene_path().read_text(encoding="utf-8"))
    return build_traditional_livability_analysis(
        analysis_id="uwm-traditional-livability-analysis-chongqing-central-current",
        created_at=_utc_now(),
        multisource_livability_scene=scene,
        top_n=top_n,
    )


async def uwm_traditional_livability(request: Request):
    """GET /api/uwm/traditional-livability"""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)

    top_n = _safe_int(request.query_params.get("top_n"), default=8)
    top_n = max(1, min(top_n, 20))
    try:
        return JSONResponse(await asyncio.to_thread(_load_default_analysis, top_n))
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


async def uwm_traditional_livability_map(request: Request):
    """POST /api/uwm/traditional-livability/map"""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    username, _ = _set_user_context(user)

    try:
        body = await request.json()
    except Exception:
        body = {}
    if not isinstance(body, dict):
        body = {}

    top_n = max(1, min(_safe_int(body.get("top_n"), default=8), 20))
    try:
        analysis = await asyncio.to_thread(_load_default_analysis, top_n)
        payload = await asyncio.to_thread(
            queue_traditional_livability_map,
            username=username,
            analysis=analysis,
            admin_units_geojson_path=_admin_units_path(),
        )
        return JSONResponse(payload)
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


async def uwm_traditional_livability_s1(request: Request):
    """GET /api/uwm/traditional-livability/s1"""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)
    try:
        return JSONResponse(await asyncio.to_thread(_load_s1_snapshot))
    except S1SnapshotUnavailable as exc:
        return JSONResponse(exc.payload, status_code=503)
    except Exception:
        return JSONResponse(
            {
                "schema": S1_SCHEMA,
                "ready": False,
                "blockers": ["s1_snapshot_unreadable"],
                "claim_boundary": {"assessment_fabricated": False},
            },
            status_code=503,
        )


async def uwm_traditional_livability_s7(request: Request):
    """GET /api/uwm/traditional-livability/s7"""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)
    try:
        return JSONResponse(await asyncio.to_thread(_load_s7_snapshot))
    except S7SnapshotUnavailable as exc:
        return JSONResponse(exc.payload, status_code=503)
    except Exception:
        return JSONResponse(
            {
                "schema": S7_SCHEMA,
                "ready": False,
                "blockers": ["s7_snapshot_unreadable"],
                "claim_boundary": {"recommendation_fabricated": False},
            },
            status_code=503,
        )


async def uwm_traditional_livability_s6_resources(request: Request):
    """GET /api/uwm/traditional-livability/s6/resources"""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)
    try:
        return JSONResponse(await asyncio.to_thread(_load_s6_snapshot, "resources"))
    except S6SnapshotUnavailable as exc:
        return JSONResponse(exc.payload, status_code=503)
    except Exception:
        return JSONResponse(
            _s6_unavailable_payload("resources", "s6_resources_snapshot_unreadable"),
            status_code=503,
        )


async def uwm_traditional_livability_s4_resources(request: Request):
    """GET /api/uwm/traditional-livability/s4/resources"""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)
    try:
        s1_snapshot, s6_resources, dictionary, compatibility = await asyncio.gather(
            asyncio.to_thread(_load_required_s4_s1_snapshot),
            asyncio.to_thread(_load_s6_snapshot, "resources"),
            asyncio.to_thread(_load_optional_s6_snapshot, "dictionary"),
            asyncio.to_thread(_load_optional_s6_snapshot, "compatibility"),
        )
        return JSONResponse(
            _s4_resources_payload(
                s1_snapshot,
                s6_resources,
                dictionary,
                compatibility,
            )
        )
    except (S1SnapshotUnavailable, S6SnapshotUnavailable) as exc:
        return JSONResponse(exc.payload, status_code=503)
    except Exception:
        return JSONResponse(
            {
                "schema": S4_RESOURCE_SCHEMA,
                "ready": False,
                "blockers": ["s4_required_snapshot_unreadable"],
            },
            status_code=503,
        )


async def uwm_traditional_livability_s4_analyze(request: Request):
    """POST /api/uwm/traditional-livability/s4/analyze"""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    username, _ = _set_user_context(user)
    try:
        payload = await request.json()
    except Exception:
        return JSONResponse(
            {"error": "Invalid JSON payload", "validation_errors": ["request_json_invalid"]},
            status_code=400,
        )
    if not isinstance(payload, dict):
        return JSONResponse(
            {"error": "Invalid request payload", "validation_errors": ["project_request_not_object"]},
            status_code=400,
        )
    rebound_payload = _bind_s4_confirmation_actors(payload, username)
    project = await asyncio.to_thread(
        validate_s4_project_request,
        rebound_payload,
        actor_id=username,
    )
    if project.get("valid") is not True:
        return JSONResponse(project, status_code=400)
    try:
        s1_snapshot, s6_resources, dictionary, compatibility = await asyncio.gather(
            asyncio.to_thread(_load_required_s4_s1_snapshot),
            asyncio.to_thread(_load_s6_snapshot, "resources"),
            asyncio.to_thread(_load_optional_s6_snapshot, "dictionary"),
            asyncio.to_thread(_load_optional_s6_snapshot, "compatibility"),
        )
        parcel_errors = _validate_s4_parcel(project, s6_resources)
        if parcel_errors:
            return JSONResponse(
                {**project, "valid": False, "validation_errors": parcel_errors},
                status_code=400,
            )
        result = await asyncio.to_thread(
            assess_s4_project,
            project=project,
            s1_snapshot=s1_snapshot,
            s6_resources=s6_resources,
            facility_dictionary=dictionary,
            compatibility_matrix=compatibility,
        )
        input_blockers = _s4_engine_input_blockers(result)
        if input_blockers:
            return JSONResponse(
                {**result, "validation_blockers": input_blockers},
                status_code=400,
            )
        return JSONResponse(result)
    except (S1SnapshotUnavailable, S6SnapshotUnavailable) as exc:
        return JSONResponse(exc.payload, status_code=503)
    except Exception:
        return JSONResponse(
            {
                "schema": "uwm.traditional_livability.s4_project_assessment.v1",
                "status": "insufficient_evidence",
                "project_blockers": ["s4_analysis_failed"],
            },
            status_code=503,
        )


async def uwm_traditional_livability_s6_dictionary(request: Request):
    """GET /api/uwm/traditional-livability/s6/dictionary"""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)
    dictionary, compatibility = await asyncio.gather(
        asyncio.to_thread(_load_optional_s6_snapshot, "dictionary"),
        asyncio.to_thread(_load_optional_s6_snapshot, "compatibility"),
    )
    return JSONResponse(_s6_authority_status(dictionary, compatibility))


async def uwm_traditional_livability_s6_analyze(request: Request):
    """POST /api/uwm/traditional-livability/s6/analyze"""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    username, _ = _set_user_context(user)
    try:
        payload = await request.json()
    except Exception:
        return JSONResponse(
            {"error": "Invalid JSON payload", "blockers": ["request_json_invalid"]},
            status_code=400,
        )
    if not isinstance(payload, dict):
        return JSONResponse(
            {"error": "Invalid request payload", "blockers": ["request_object_required"]},
            status_code=400,
        )
    confirmation = payload.get("human_confirmation")
    if isinstance(confirmation, dict):
        payload = dict(payload)
        payload["human_confirmation"] = {
            **confirmation,
            "actor_id": username,
        }
    try:
        resources = await asyncio.to_thread(_load_s6_snapshot, "resources")
        dictionary, compatibility = await asyncio.gather(
            asyncio.to_thread(_load_optional_s6_snapshot, "dictionary"),
            asyncio.to_thread(_load_optional_s6_snapshot, "compatibility"),
        )
        result = await asyncio.to_thread(
            analyze_s6_facility_proposal,
            request=payload,
            resources=resources,
            dictionary=dictionary,
            compatibility=compatibility,
        )
    except S6SnapshotUnavailable as exc:
        return JSONResponse(exc.payload, status_code=503)
    except Exception:
        return JSONResponse(
            _s6_unavailable_payload("resources", "s6_analysis_failed"),
            status_code=503,
        )
    validation_blockers = result.get("validation_blockers") or []
    status_code = 400 if validation_blockers else 200
    return JSONResponse(result, status_code=status_code)


def _authenticated_actor(request: Request):
    user = _get_user_from_request(request)
    if not user:
        return None
    username, _ = _set_user_context(user)
    return username


async def uwm_traditional_livability_s1_profiles(request: Request):
    actor_id = _authenticated_actor(request)
    if actor_id is None:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    try:
        return JSONResponse(_get_s6_s1_service().list_profiles())
    except RuntimeError:
        return JSONResponse(
            {
                "schema": "uwm.traditional_livability.s1_metric_profile_collection.v1",
                "status": "unavailable",
                "profiles": [],
                "blockers": ["s6_s1_product_not_configured"],
            },
            status_code=503,
        )


async def uwm_traditional_livability_s6_create_handoff(request: Request):
    actor_id = _authenticated_actor(request)
    if actor_id is None:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    try:
        payload = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON payload", "blockers": ["request_json_invalid"]}, status_code=400)
    if not isinstance(payload, dict) or not isinstance(payload.get("s6_analysis"), dict):
        return JSONResponse({"error": "Invalid request payload", "blockers": ["s6_analysis_required"]}, status_code=400)
    try:
        handoff = _get_s6_s1_service().create_handoff(
            s6_analysis=payload["s6_analysis"],
            actor_id=actor_id,
            created_at=str(payload.get("created_at") or _utc_now()),
        )
    except RuntimeError:
        return JSONResponse({"error": "S6 to S1 product unavailable", "blockers": ["s6_s1_product_not_configured"]}, status_code=503)
    return JSONResponse(handoff)


async def uwm_traditional_livability_s6_get_handoff(request: Request):
    actor_id = _authenticated_actor(request)
    if actor_id is None:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    handoff_id = request.path_params.get("handoff_id")
    try:
        handoff = _get_s6_s1_service().get_handoff(str(handoff_id), actor_id=actor_id)
    except HandoffNotFound:
        return JSONResponse({"error": "Handoff not found"}, status_code=404)
    except RuntimeError:
        return JSONResponse({"error": "S6 to S1 product unavailable", "blockers": ["s6_s1_product_not_configured"]}, status_code=503)
    return JSONResponse(handoff)


async def uwm_traditional_livability_s6_execute_s1(request: Request):
    actor_id = _authenticated_actor(request)
    if actor_id is None:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    handoff_id = request.path_params.get("handoff_id")
    try:
        result = _get_s6_s1_service().execute_s1(str(handoff_id), actor_id=actor_id)
    except HandoffNotFound:
        return JSONResponse({"error": "Handoff not found"}, status_code=404)
    except HandoffConflict as exc:
        return JSONResponse({"error": str(exc), "blockers": [str(exc)]}, status_code=409)
    except RuntimeError:
        return JSONResponse({"error": "S6 to S1 product unavailable", "blockers": ["s6_s1_product_not_configured"]}, status_code=503)
    return JSONResponse(result)


def get_uwm_traditional_livability_routes() -> list:
    """Return Route objects for traditional livability analysis endpoints."""
    return [
        Route(
            "/api/uwm/traditional-livability",
            uwm_traditional_livability,
            methods=["GET"],
        ),
        Route(
            "/api/uwm/traditional-livability/map",
            uwm_traditional_livability_map,
            methods=["POST"],
        ),
        Route(
            "/api/uwm/traditional-livability/s1",
            uwm_traditional_livability_s1,
            methods=["GET"],
        ),
        Route(
            "/api/uwm/traditional-livability/s7",
            uwm_traditional_livability_s7,
            methods=["GET"],
        ),
        Route(
            "/api/uwm/traditional-livability/s4/resources",
            uwm_traditional_livability_s4_resources,
            methods=["GET"],
        ),
        Route(
            "/api/uwm/traditional-livability/s4/analyze",
            uwm_traditional_livability_s4_analyze,
            methods=["POST"],
        ),
        Route(
            "/api/uwm/traditional-livability/s6/resources",
            uwm_traditional_livability_s6_resources,
            methods=["GET"],
        ),
        Route(
            "/api/uwm/traditional-livability/s6/dictionary",
            uwm_traditional_livability_s6_dictionary,
            methods=["GET"],
        ),
        Route(
            "/api/uwm/traditional-livability/s6/analyze",
            uwm_traditional_livability_s6_analyze,
            methods=["POST"],
        ),
        Route(
            "/api/uwm/traditional-livability/s1/profiles",
            uwm_traditional_livability_s1_profiles,
            methods=["GET"],
        ),
        Route(
            "/api/uwm/traditional-livability/s6/handoffs",
            uwm_traditional_livability_s6_create_handoff,
            methods=["POST"],
        ),
        Route(
            "/api/uwm/traditional-livability/s6/handoffs/{handoff_id}",
            uwm_traditional_livability_s6_get_handoff,
            methods=["GET"],
        ),
        Route(
            "/api/uwm/traditional-livability/s6/handoffs/{handoff_id}/execute-s1",
            uwm_traditional_livability_s6_execute_s1,
            methods=["POST"],
        ),
    ]


def _safe_int(value, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00",
        "Z",
    )
