"""Governed semantic CRUD and virtual-lake metadata read models.

The generated Abu Dhabi semantic artifacts remain immutable evidence.  This
module provides the product administration surface backed by a versioned
PostgreSQL registry.  Draft changes are visible to reviewers but are never
silently substituted into the query runtime; only a validated, explicitly
published version is eligible for a later runtime promotion.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import date, datetime
from typing import Any

from sqlalchemy import text
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from .helpers import _get_user_from_request, _set_user_context

logger = logging.getLogger("data_agent.api.abu_dhabi_semantic_admin")

_SCOPE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,31}$")
_ENTRY_TYPES = {"assets", "fields", "relationships", "metric_contracts"}
_EDIT_ROLES = {"analyst", "standard_editor", "admin"}
_REVIEW_ROLES = {"standard_reviewer", "admin"}
_MAX_LIMIT = 200
_MAX_PAYLOAD_BYTES = 120_000
_QUEUE_KINDS = {"table": "table_tasks", "field": "field_tasks", "relationship": "relationship_tasks"}
_QUEUE_STATUSES = {"all", "review_required", "reviewed"}
_BENCHMARK_QUEUE_STATUSES = {"all", "pending_business_gold_review", "reviewed"}
_BENCHMARK_REVIEW_DECISIONS = {"approved_for_gold", "rejected", "needs_changes"}
_SEMANTIC_REVIEW_DECISIONS = {"approved_for_draft", "rejected", "needs_changes"}
_MAX_REVIEW_NOTES = 4_000
_MAX_QUESTION_TEMPLATE_BYTES = 24_000


def _jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


def _public_evidence_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _public_evidence_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_public_evidence_value(item) for item in value]
    if isinstance(value, str) and value.startswith("/"):
        normalized = value.replace("\\", "/")
        return f"external_artifact/{normalized.rsplit('/', 1)[-1]}"
    return _jsonable(value)


def _engine():
    from ..db_engine import get_engine

    return get_engine()


def _artifact(scope: str) -> dict[str, Any]:
    from .abu_dhabi_nl2sql_product_routes import _load_source_artifacts, _source_spec

    try:
        return _load_source_artifacts(_source_spec(scope))["semantic"]
    except (KeyError, FileNotFoundError, ValueError):
        return {}


def _catalog(scope: str) -> dict[str, Any]:
    from .abu_dhabi_nl2sql_product_routes import _load_source_artifacts, _source_spec

    try:
        return _load_source_artifacts(_source_spec(scope))["catalog"]
    except (KeyError, FileNotFoundError, ValueError):
        return {"resources": [], "coverage": {}}


def _review_queue(scope: str) -> dict[str, Any]:
    """Load the source-bound expert review queue without making it executable."""
    from .abu_dhabi_nl2sql_product_routes import _load_source_artifacts, _source_spec

    try:
        artifacts = _load_source_artifacts(_source_spec(scope))
    except (KeyError, FileNotFoundError, ValueError):
        return {}
    queue = artifacts.get("business_semantic_task_queue") or {}
    return queue if isinstance(queue, dict) else {}


def _benchmark_review_queue(scope: str) -> dict[str, Any]:
    """Load business-question candidates without treating them as Gold."""
    from .abu_dhabi_nl2sql_product_routes import _load_source_artifacts, _source_spec

    try:
        artifacts = _load_source_artifacts(_source_spec(scope))
    except (KeyError, FileNotFoundError, ValueError):
        return {}
    queue = artifacts.get("business_benchmark_task_queue") or {}
    return queue if isinstance(queue, dict) else {}


def _benchmark_reviews(scope: str) -> tuple[dict[str, dict[str, Any]], bool]:
    """Read persisted human decisions without making them Gold or executable."""
    engine = _engine()
    if not engine:
        return {}, False
    try:
        with engine.connect() as conn:
            rows = (
                conn.execute(
                    text(
                        "SELECT task_id, decision, review_notes, question_templates, evidence, "
                        "reviewed_by, reviewed_at, updated_at "
                        "FROM agent_business_benchmark_reviews WHERE scope=:scope "
                        "ORDER BY updated_at DESC, id DESC"
                    ),
                    {"scope": scope},
                )
                .mappings()
                .all()
            )
        result: dict[str, dict[str, Any]] = {}
        for row in rows:
            templates = row["question_templates"]
            evidence = row["evidence"]
            if isinstance(templates, str):
                templates = json.loads(templates)
            if isinstance(evidence, str):
                evidence = json.loads(evidence)
            result[str(row["task_id"])] = _public_evidence_value(
                {
                    "decision": row["decision"],
                    "review_notes": row["review_notes"] or "",
                    "question_templates": templates if isinstance(templates, dict) else {},
                    "evidence": evidence if isinstance(evidence, dict) else {},
                    "reviewed_by": row["reviewed_by"],
                    "reviewed_at": row["reviewed_at"],
                    "updated_at": row["updated_at"],
                }
            )
        return result, True
    except Exception:
        # Older control databases can be running before migration 244.  The
        # queue remains readable, but a review cannot be represented as
        # persisted until the schema is upgraded.
        logger.exception("business benchmark review registry read failed")
        return {}, False


def _semantic_reviews(scope: str, queue_kind: str) -> tuple[dict[str, dict[str, Any]], bool]:
    """Read persisted semantic-task decisions without changing task artifacts."""
    if queue_kind not in _QUEUE_KINDS:
        return {}, False
    engine = _engine()
    if not engine:
        return {}, False
    try:
        with engine.connect() as conn:
            rows = (
                conn.execute(
                    text(
                        "SELECT task_id, decision, review_notes, evidence, reviewed_by, "
                        "reviewed_at, updated_at FROM agent_business_semantic_reviews "
                        "WHERE scope=:scope AND queue_kind=:queue_kind "
                        "ORDER BY updated_at DESC, id DESC"
                    ),
                    {"scope": scope, "queue_kind": queue_kind},
                )
                .mappings()
                .all()
            )
        result: dict[str, dict[str, Any]] = {}
        for row in rows:
            evidence = row["evidence"]
            if isinstance(evidence, str):
                evidence = json.loads(evidence)
            result[str(row["task_id"])] = _public_evidence_value(
                {
                    "decision": row["decision"],
                    "review_notes": row["review_notes"] or "",
                    "evidence": evidence if isinstance(evidence, dict) else {},
                    "reviewed_by": row["reviewed_by"],
                    "reviewed_at": row["reviewed_at"],
                    "updated_at": row["updated_at"],
                }
            )
        return result, True
    except Exception:
        logger.exception("business semantic review registry read failed")
        return {}, False


def _validate_semantic_review_payload(body: Any) -> dict[str, str]:
    if not isinstance(body, dict):
        raise ValueError("request body must be an object")
    decision = str(body.get("decision") or "").strip().casefold()
    if decision not in _SEMANTIC_REVIEW_DECISIONS:
        raise ValueError(
            "decision must be approved_for_draft, needs_changes, or rejected"
        )
    notes = body.get("review_notes", "")
    if not isinstance(notes, str) or len(notes) > _MAX_REVIEW_NOTES:
        raise ValueError("review_notes must be a string <= 4000 characters")
    if decision in {"rejected", "needs_changes"} and not notes.strip():
        raise ValueError("review_notes is required when rejecting or requesting changes")
    forbidden = {
        "execution_authorized",
        "execution_eligible_after_review",
        "published",
        "runtime_effect",
        "gold_sql",
        "expected_result",
        "gold_result",
        "sql",
    }
    if forbidden.intersection(body):
        raise ValueError("execution authorization and Gold fields are not accepted by this endpoint")
    return {"decision": decision, "review_notes": notes}


def _validate_benchmark_review_payload(body: Any) -> dict[str, Any]:
    if not isinstance(body, dict):
        raise ValueError("request body must be an object")
    decision = str(body.get("decision") or "").strip().casefold()
    if decision not in _BENCHMARK_REVIEW_DECISIONS:
        raise ValueError(
            "decision must be approved_for_gold, rejected, or needs_changes"
        )
    notes = body.get("review_notes", "")
    if not isinstance(notes, str) or len(notes) > _MAX_REVIEW_NOTES:
        raise ValueError("review_notes must be a string <= 4000 characters")
    if decision in {"rejected", "needs_changes"} and not notes.strip():
        raise ValueError("review_notes is required when rejecting or requesting changes")
    templates = body.get("question_templates", {})
    if templates is None:
        templates = {}
    if not isinstance(templates, dict):
        raise ValueError("question_templates must be an object")
    if set(templates) - {"zh", "en", "ar"}:
        raise ValueError("question_templates only supports zh, en, and ar")
    for language, value in templates.items():
        if not isinstance(value, str) or len(value) > 4_000:
            raise ValueError(f"question_templates.{language} must be a string <= 4000 characters")
    if len(json.dumps(templates, ensure_ascii=False).encode("utf-8")) > _MAX_QUESTION_TEMPLATE_BYTES:
        raise ValueError("question_templates exceeds the product limit")
    # Gold SQL/results are evaluator-owned data and can never be submitted via
    # the human review surface.
    forbidden = {"gold_sql", "expected_result", "gold_result", "sql"}
    if forbidden.intersection(body):
        raise ValueError("Gold SQL and expected results are not accepted by this endpoint")
    return {
        "decision": decision,
        "review_notes": notes,
        "question_templates": templates,
    }


def _public_review_queue_item(item: dict[str, Any]) -> dict[str, Any]:
    """Keep queue evidence useful to reviewers while removing workstation paths."""
    allowed = (
        "task_id",
        "kind",
        "physical_table",
        "target_table",
        "physical_field",
        "relation_id",
        "binding_status",
        "review_status",
        "execution_authorized",
        "current",
        "suggested",
        "candidate",
        "dictionary_evidence",
        "required_decisions",
        "execution_eligible_after_review",
        "source",
    )
    result = {key: _jsonable(item.get(key)) for key in allowed if key in item}
    # Evidence paths identify the document but are not useful as local paths
    # in a browser.  The public artifact helper also prevents workstation
    # paths from leaking through nested dictionaries.
    return _public_evidence_value(result)


def _review_draft_payload(
    scope: str,
    kind: str,
    item: dict[str, Any],
    asset_by_table: dict[str, str],
    binding_by_table: dict[str, dict[str, Any]],
) -> tuple[str, dict[str, Any]]:
    """Project queue evidence into an editable candidate, never an approval."""
    table = str(item.get("physical_table") or "")
    binding = binding_by_table.get(table) or {}
    asset_id = asset_by_table.get(table) or str(binding.get("semantic_entity") or "")
    if not asset_id:
        safe_table = re.sub(r"[^A-Za-z0-9_.-]+", "_", table).strip("_")
        asset_id = f"candidate.{scope}.{safe_table}"
    current = item.get("current") or {}
    suggested = item.get("suggested") or {}
    dictionary = item.get("dictionary_evidence") or {}
    evidence = _public_evidence_value(dictionary)
    trace = {
        "review_task_id": item.get("task_id"),
        "proposal_status": "candidate_review",
        "dictionary_evidence": evidence,
    }
    if kind == "table":
        labels = current.get("labels") or suggested.get("labels") or {}
        document = dictionary.get("dictionary_document") or {}
        return "assets", {
            "asset_id": asset_id,
            "physical_tables": [table],
            "labels": labels,
            "aliases": list(current.get("aliases") or []),
            "description": document.get("description") or "",
            "grain": "",
            "review_status": "candidate_review",
            **trace,
        }
    if kind == "field":
        labels = current.get("labels") or suggested.get("labels") or {}
        return "fields", {
            "asset_id": asset_id,
            "physical_tables": [table],
            "semantic_field": item.get("physical_field"),
            "physical_field": item.get("physical_field"),
            "labels": labels,
            "business_role": current.get("business_role") or "",
            "description": current.get("definition") or dictionary.get("dictionary_description") or "",
            "unit": current.get("unit") or "",
            "time_semantics": current.get("time_semantics"),
            "spatial_semantics": current.get("spatial_semantics"),
            "sensitivity": current.get("sensitivity"),
            "review_status": "candidate_review",
            **trace,
        }
    candidate = item.get("candidate") or {}
    predicate = str(candidate.get("predicate") or "equality")
    left = ".".join(value for value in (table, str(candidate.get("source_field") or "")) if value)
    target_table = str(item.get("target_table") or "")
    right = ".".join(
        value for value in (target_table, str(candidate.get("target_field") or "")) if value
    )
    return "relationships", {
        "left": left,
        "right": right,
        "kind": "spatial" if predicate.upper().startswith("ST_") else "equality",
        "spatial_predicate": predicate if predicate.upper().startswith("ST_") else "",
        "review_status": "candidate_review",
        "candidate_relation_id": item.get("relation_id"),
        "cardinality_notes": candidate.get("cardinality_notes"),
        "execution_authorized": False,
        **trace,
    }


def _baseline_entries(scope: str, entry_type: str) -> list[dict[str, Any]]:
    semantic = _artifact(scope)
    if entry_type == "assets":
        # Inferred full-table candidates are exposed by the read-only semantic
        # inspector and review queues, but are not baseline CRUD entries.  The
        # admin editor manages only published/reviewed business authority;
        # otherwise a generated suggestion would look like an active asset in
        # the governance editor.
        return [
            item
            for item in semantic.get("semantic_assets") or []
            if _published_review_status(item)
        ]
    if entry_type == "relationships":
        return list(semantic.get("relationships") or [])
    if entry_type == "metric_contracts":
        return list(semantic.get("metric_contracts") or [])
    fields: list[dict[str, Any]] = []
    for asset in semantic.get("semantic_assets") or []:
        if not _published_review_status(asset):
            continue
        asset_id = str(asset.get("asset_id") or "")
        physical_tables = list(asset.get("physical_tables") or [])
        for field in asset.get("fields") or []:
            item = dict(field)
            item["asset_id"] = asset_id
            item["physical_tables"] = physical_tables
            fields.append(item)
    return fields


def _valid_scope(scope: str) -> bool:
    return bool(_SCOPE_RE.fullmatch(str(scope or "")))


def _natural_key(entry_type: str, payload: dict[str, Any]) -> str:
    if entry_type == "assets":
        value = payload.get("asset_id")
    elif entry_type == "fields":
        value = f"{payload.get('asset_id', '')}:{payload.get('semantic_field') or payload.get('physical_field', '')}"
    elif entry_type == "relationships":
        value = f"{payload.get('left', '')}|{payload.get('right', '')}"
    else:
        value = payload.get("contract_id")
    value = str(value or "").strip()
    if not value or len(value) > 512:
        raise ValueError("semantic natural key is required and must be <= 512 characters")
    return value


def _validate_payload(entry_type: str, payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("payload must be an object")
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    if len(encoded.encode("utf-8")) > _MAX_PAYLOAD_BYTES:
        raise ValueError("payload exceeds the product limit")
    if entry_type == "assets":
        if not str(payload.get("asset_id") or "").strip():
            raise ValueError("asset_id is required")
        if not payload.get("physical_tables"):
            raise ValueError("physical_tables is required")
    elif entry_type == "fields":
        if not str(payload.get("asset_id") or "").strip():
            raise ValueError("fields require asset_id")
        if not str(payload.get("physical_field") or payload.get("semantic_field") or "").strip():
            raise ValueError("fields require physical_field or semantic_field")
    elif entry_type == "relationships":
        if not all(str(payload.get(key) or "").strip() for key in ("left", "right")):
            raise ValueError("relationships require left and right")
        if payload.get("cardinality") and payload["cardinality"] not in {
            "one_to_one",
            "one_to_many",
            "many_to_one",
            "many_to_many",
            "many_to_many_requires_municipality",
        }:
            raise ValueError("relationship cardinality is unsupported")
    elif entry_type == "metric_contracts":
        if not str(payload.get("contract_id") or "").strip():
            raise ValueError("contract_id is required")
        if not isinstance(payload.get("tables"), list) or not payload["tables"]:
            raise ValueError("metric contracts require tables")
    return payload


def _published_review_status(payload: dict[str, Any]) -> bool:
    status = str(payload.get("review_status") or payload.get("definition_status") or "").casefold()
    return status in {
        "reviewed",
        "reviewed_candidate",
        "reviewed_dictionary_supported_v1",
        "approved",
        "published",
        "active",
    }


def _validate_version(scope: str, version_id: int) -> dict[str, Any]:
    engine = _engine()
    if not engine:
        raise RuntimeError("database_unavailable")
    baseline = {kind: _baseline_entries(scope, kind) for kind in _ENTRY_TYPES}
    catalog = _catalog(scope)
    resources = {
        str(item.get("physical_table"))
        for item in catalog.get("resources") or []
        if item.get("physical_table")
    }
    resource_fields = {
        str(item.get("physical_table")): {
            str(field.get("physical_field") or field.get("semantic_field"))
            for field in item.get("fields") or []
            if field.get("physical_field") or field.get("semantic_field")
        }
        for item in catalog.get("resources") or []
        if item.get("physical_table")
    }
    with engine.connect() as conn:
        rows = (
            conn.execute(
                text(
                    "SELECT entry_type, natural_key, payload, state "
                    "FROM agent_semantic_admin_entries WHERE version_id=:version "
                    "AND scope=:scope AND state <> 'deleted'"
                ),
                {"version": version_id, "scope": scope},
            )
            .mappings()
            .all()
        )
    errors: list[str] = []
    counts: dict[str, int] = {}
    asset_tables: dict[str, list[str]] = {}
    for row in rows:
        if str(row["entry_type"]) != "assets":
            continue
        payload = row["payload"] if isinstance(row["payload"], dict) else json.loads(row["payload"])
        asset_tables[str(payload.get("asset_id") or "")] = [
            str(table) for table in payload.get("physical_tables") or []
        ]
    for row in rows:
        kind = str(row["entry_type"])
        payload = row["payload"] if isinstance(row["payload"], dict) else json.loads(row["payload"])
        counts[kind] = counts.get(kind, 0) + 1
        try:
            _validate_payload(kind, payload)
        except ValueError as exc:
            errors.append(f"{kind}:{row['natural_key']}:{exc}")
            continue
        if kind == "assets":
            if not any(str(table) in resources for table in payload.get("physical_tables") or []):
                errors.append(
                    f"assets:{row['natural_key']}:physical_table_not_in_technical_catalog"
                )
        elif kind == "fields":
            field_tables = [
                str(table)
                for table in payload.get("physical_tables")
                or asset_tables.get(str(payload.get("asset_id") or ""), [])
            ]
            if not field_tables:
                errors.append(f"fields:{row['natural_key']}:physical_tables_required")
            elif any(table not in resources for table in field_tables):
                errors.append(
                    f"fields:{row['natural_key']}:physical_table_not_in_technical_catalog"
                )
            physical_field = str(
                payload.get("physical_field") or payload.get("semantic_field") or ""
            )
            if field_tables and not any(
                physical_field in resource_fields.get(table, set()) for table in field_tables
            ):
                errors.append(
                    f"fields:{row['natural_key']}:physical_field_not_in_technical_catalog"
                )
        elif kind == "relationships":
            if not _published_review_status(payload):
                errors.append(f"relationships:{row['natural_key']}:review_status_required")
            for endpoint in (payload.get("left"), payload.get("right")):
                if len(str(endpoint).split(".")) < 3:
                    errors.append(f"relationships:{row['natural_key']}:qualified_endpoint_required")
        elif kind == "metric_contracts":
            if not _published_review_status(payload):
                errors.append(f"metric_contracts:{row['natural_key']}:review_status_required")
            unknown = [
                str(table) for table in payload.get("tables") or [] if str(table) not in resources
            ]
            if unknown:
                errors.append(
                    f"metric_contracts:{row['natural_key']}:unknown_tables={','.join(unknown)}"
                )
    return {
        "valid": not errors,
        "scope": scope,
        "version_id": version_id,
        "entry_count": len(rows),
        "entry_counts": counts,
        "baseline_entry_counts": {key: len(value) for key, value in baseline.items()},
        "errors": errors[:100],
        "runtime_effect": "none_until_explicit_runtime_promotion",
    }


def _auth(request: Request, *, mutation: bool = False, review: bool = False):
    user = _get_user_from_request(request)
    if not user:
        return None, None, JSONResponse({"error": "Unauthorized"}, status_code=401)
    username, role = _set_user_context(user)
    if mutation and not review and role not in _EDIT_ROLES:
        return user, role, JSONResponse({"error": "semantic_editor role required"}, status_code=403)
    if review and role not in _REVIEW_ROLES:
        return (
            user,
            role,
            JSONResponse({"error": "semantic_reviewer role required"}, status_code=403),
        )
    return username, role, None


def _query_int(request: Request, name: str, default: int, maximum: int) -> int:
    try:
        value = int(request.query_params.get(name) or default)
    except ValueError as exc:
        raise ValueError(f"{name} must be an integer") from exc
    if value < 0 or value > maximum:
        raise ValueError(f"{name} is outside the allowed range")
    return value


def _entry_response(
    entry_id: str,
    entry_type: str,
    payload: dict[str, Any],
    *,
    state: str,
    source: str,
    version_id: int | None = None,
) -> dict[str, Any]:
    return {
        "id": entry_id,
        "entry_type": entry_type,
        "payload": _jsonable(payload),
        "state": state,
        "source": source,
        "version_id": version_id,
        "execution_eligible": state == "published" and source == "registry",
    }


async def semantic_admin_entries(request: Request) -> JSONResponse:
    username, _role, error = _auth(request)
    if error:
        return error
    scope = str(request.query_params.get("scope") or "").strip()
    entry_type = str(request.path_params.get("entry_type") or "").strip()
    if not _valid_scope(scope) or entry_type not in _ENTRY_TYPES:
        return JSONResponse({"error": "unsupported scope or entry_type"}, status_code=400)
    try:
        offset = _query_int(request, "offset", 0, 1_000_000)
        limit = _query_int(request, "limit", 50, _MAX_LIMIT)
        search = str(request.query_params.get("search") or "").strip().casefold()
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    baseline = _baseline_entries(scope, entry_type)
    items: dict[str, dict[str, Any]] = {}
    for payload in baseline:
        try:
            key = _natural_key(entry_type, payload)
        except ValueError:
            continue
        items[key] = _entry_response(
            f"artifact:{entry_type}:{key}",
            entry_type,
            payload,
            state="published_baseline",
            source="artifact",
        )
    engine = _engine()
    versions: list[dict[str, Any]] = []
    if engine:
        try:
            with engine.connect() as conn:
                rows = (
                    conn.execute(
                        text(
                            "SELECT e.id, e.entry_type, e.natural_key, e.payload, e.state, e.version_id "
                            "FROM agent_semantic_admin_entries e "
                            "JOIN agent_semantic_admin_versions v ON v.id=e.version_id "
                            "WHERE e.scope=:scope AND e.entry_type=:entry_type "
                            "AND v.status IN ('draft','reviewed','published') "
                            "ORDER BY e.updated_at ASC, e.id ASC"
                        ),
                        {"scope": scope, "entry_type": entry_type},
                    )
                    .mappings()
                    .all()
                )
                versions = [
                    dict(row)
                    for row in conn.execute(
                        text(
                            "SELECT id, version_label, status, created_by, reviewed_by, published_by, "
                            "review_notes, validation_report, created_at, updated_at "
                            "FROM agent_semantic_admin_versions WHERE scope=:scope ORDER BY id DESC LIMIT 20"
                        ),
                        {"scope": scope},
                    )
                    .mappings()
                    .all()
                ]
            for row in rows:
                payload = (
                    row["payload"]
                    if isinstance(row["payload"], dict)
                    else json.loads(row["payload"])
                )
                key = str(row["natural_key"])
                if row["state"] == "deleted":
                    items.pop(key, None)
                else:
                    items[key] = _entry_response(
                        str(row["id"]),
                        entry_type,
                        payload,
                        state=str(row["state"]),
                        source="registry",
                        version_id=int(row["version_id"]),
                    )
        except Exception:
            logger.exception("semantic admin registry read failed")
    filtered = [
        item
        for item in items.values()
        if not search or search in json.dumps(item["payload"], ensure_ascii=False).casefold()
    ]
    filtered.sort(key=lambda item: str(item["id"]))
    return JSONResponse(
        {
            "schema": "gda.abu-dhabi-semantic-admin-entries.v1",
            "scope": scope,
            "entry_type": entry_type,
            "items": filtered[offset : offset + limit],
            "total": len(filtered),
            "has_more": offset + limit < len(filtered),
            "offset": offset,
            "limit": limit,
            "versions": [_jsonable(item) for item in versions],
            "baseline_is_immutable": True,
            "runtime_uses_published_registry": False,
            "source_rows_persisted": False,
        }
    )


async def semantic_review_queue(request: Request) -> JSONResponse:
    """Return a paged, non-executable expert review queue for one source."""
    username, _role, error = _auth(request)
    if error:
        return error
    scope = str(request.query_params.get("scope") or "").strip()
    if not _valid_scope(scope):
        return JSONResponse({"error": "unsupported scope"}, status_code=400)
    kind = str(request.query_params.get("kind") or "field").strip().casefold()
    status = str(request.query_params.get("status") or "review_required").strip().casefold()
    if kind not in _QUEUE_KINDS:
        return JSONResponse({"error": "unsupported review queue kind"}, status_code=400)
    if status not in _QUEUE_STATUSES:
        return JSONResponse({"error": "unsupported review queue status"}, status_code=400)
    try:
        offset = _query_int(request, "offset", 0, 1_000_000)
        limit = _query_int(request, "limit", 25, _MAX_LIMIT)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    search = str(request.query_params.get("search") or "").strip().casefold()
    queue = _review_queue(scope)
    persisted_reviews, review_registry_available = _semantic_reviews(scope, kind)
    semantic = _artifact(scope)
    asset_by_table: dict[str, str] = {}
    for asset in semantic.get("semantic_assets") or []:
        asset_id = str(asset.get("asset_id") or "")
        for table in asset.get("physical_tables") or []:
            if asset_id and table:
                asset_by_table[str(table)] = asset_id
    binding_by_table = {
        str(item.get("physical_table")): item
        for item in semantic.get("table_bindings") or []
        if item.get("physical_table")
    }
    raw_items = [item for item in queue.get(_QUEUE_KINDS[kind]) or [] if isinstance(item, dict)]
    filtered: list[dict[str, Any]] = []
    for item in raw_items:
        task_id = str(item.get("task_id") or "")
        review = persisted_reviews.get(task_id)
        candidate_status = str(item.get("review_status") or "review_required").casefold()
        # Keep the generated candidate status immutable and expose the human
        # decision separately.  A persisted decision makes the queue item
        # "reviewed" for triage purposes only; it does not publish or
        # authorize the semantic entry.
        item_status = "reviewed" if review or candidate_status == "reviewed" else "review_required"
        if status != "all" and item_status != status:
            continue
        if search and search not in json.dumps(item, ensure_ascii=False).casefold():
            continue
        public_item = _public_review_queue_item(item)
        public_item["candidate_review_status"] = item.get("review_status")
        public_item["review_status"] = item_status
        public_item["review"] = review
        try:
            entry_type, draft_payload = _review_draft_payload(
                scope, kind, item, asset_by_table, binding_by_table
            )
            public_item["draft"] = {
                "entry_type": entry_type,
                "payload": draft_payload,
                "not_approved": True,
            }
        except (TypeError, ValueError):
            # A malformed candidate remains visible for manual review, but it
            # must not produce an unsafe draft shortcut.
            public_item["draft"] = None
        filtered.append(public_item)
    coverage = dict(queue.get("coverage") or {})
    semantic_review_counts = {"approved_for_draft": 0, "needs_changes": 0, "rejected": 0}
    for review in persisted_reviews.values():
        decision = str(review.get("decision") or "")
        if decision in semantic_review_counts:
            semantic_review_counts[decision] += 1
    coverage.update(
        {
            "persisted_review_count": len(persisted_reviews),
            "approved_for_draft_review_count": semantic_review_counts["approved_for_draft"],
            "needs_changes_review_count": semantic_review_counts["needs_changes"],
            "rejected_review_count": semantic_review_counts["rejected"],
        }
    )
    return JSONResponse(
        {
            "schema": "gda.abu-dhabi-semantic-review-queue.v1",
            "scope": scope,
            "kind": kind,
            "status": status,
            "search": search,
            "items": filtered[offset : offset + limit],
            "total": len(filtered),
            "has_more": offset + limit < len(filtered),
            "offset": offset,
            "limit": limit,
            "coverage": coverage,
            "claim_boundary": {
                "is_runtime_semantic_config": False,
                "is_business_benchmark": False,
                "is_business_semantic_authority": False,
                "unreviewed_items_are_executable": False,
                "source_rows_persisted": False,
                "review_registry_available": review_registry_available,
            },
            "source": _public_evidence_value(queue.get("source") or {}),
        }
    )


async def semantic_review(request: Request) -> JSONResponse:
    """Persist one expert decision for a table/field/relationship candidate.

    This registry is deliberately independent of the generated queue artifact
    and the versioned semantic CRUD registry.  An approval only records that
    the candidate may be loaded into a draft; it never publishes the draft or
    grants runtime execution authority.
    """
    username, _role, error = _auth(request, mutation=True, review=True)
    if error:
        return error
    scope = str(request.query_params.get("scope") or "").strip()
    queue_kind = str(request.path_params.get("kind") or "").strip().casefold()
    task_id = str(request.path_params.get("task_id") or "").strip()
    if (
        not _valid_scope(scope)
        or queue_kind not in _QUEUE_KINDS
        or not task_id
        or len(task_id) > 255
    ):
        return JSONResponse({"error": "unsupported scope, kind, or task_id"}, status_code=400)
    queue = _review_queue(scope)
    task = next(
        (
            item
            for item in queue.get(_QUEUE_KINDS[queue_kind]) or []
            if isinstance(item, dict) and str(item.get("task_id") or "") == task_id
        ),
        None,
    )
    if task is None:
        return JSONResponse({"error": "semantic_task_not_found"}, status_code=404)
    try:
        body = await request.json()
        decision = _validate_semantic_review_payload(body)
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    engine = _engine()
    if not engine:
        return JSONResponse({"error": "database_unavailable"}, status_code=503)
    # Store only queue evidence needed for an audit trail.  It is not used as
    # an executable semantic artifact and workstation paths are redacted.
    evidence = {
        "queue_item": {
            key: task.get(key)
            for key in (
                "kind",
                "physical_table",
                "target_table",
                "physical_field",
                "relation_id",
                "binding_status",
                "review_status",
                "current",
                "suggested",
                "candidate",
                "dictionary_evidence",
                "required_decisions",
            )
            if task.get(key) is not None
        },
        "queue_source": _public_evidence_value(queue.get("source") or {}),
        "is_runtime_authority": False,
    }
    evidence_json = json.dumps(_public_evidence_value(evidence), ensure_ascii=False)
    try:
        with engine.begin() as conn:
            row = (
                conn.execute(
                    text(
                        "INSERT INTO agent_business_semantic_reviews "
                        "(scope, queue_kind, task_id, decision, review_notes, evidence, reviewed_by, reviewed_at, updated_at) "
                        "VALUES (:scope, :queue_kind, :task_id, :decision, :notes, CAST(:evidence AS jsonb), :user, NOW(), NOW()) "
                        "ON CONFLICT (scope, queue_kind, task_id) DO UPDATE SET "
                        "decision=EXCLUDED.decision, review_notes=EXCLUDED.review_notes, "
                        "evidence=EXCLUDED.evidence, reviewed_by=EXCLUDED.reviewed_by, "
                        "reviewed_at=NOW(), updated_at=NOW() "
                        "RETURNING task_id, queue_kind, decision, review_notes, evidence, reviewed_by, reviewed_at, updated_at"
                    ),
                    {
                        "scope": scope,
                        "queue_kind": queue_kind,
                        "task_id": task_id,
                        "decision": decision["decision"],
                        "notes": decision["review_notes"],
                        "evidence": evidence_json,
                        "user": username,
                    },
                )
                .mappings()
                .one()
            )
        payload = _public_evidence_value(
            {
                "task_id": row["task_id"],
                "queue_kind": row["queue_kind"],
                "decision": row["decision"],
                "review_notes": row["review_notes"] or "",
                "evidence": row["evidence"],
                "reviewed_by": row["reviewed_by"],
                "reviewed_at": row["reviewed_at"],
                "updated_at": row["updated_at"],
                "runtime_effect": "none_until_explicit_draft_publish_and_runtime_promotion",
            }
        )
        return JSONResponse(
            {
                "schema": "gda.abu-dhabi-business-semantic-review.v1",
                "scope": scope,
                "review": payload,
            }
        )
    except Exception as exc:
        logger.exception("business semantic review registry write failed")
        return JSONResponse(
            {"error": "semantic_review_write_failed", "detail": str(exc)[:200]}, status_code=503
        )


async def semantic_benchmark_review_queue(request: Request) -> JSONResponse:
    """Return reviewable question slots; no Gold or runtime rule is exposed."""
    username, _role, error = _auth(request)
    if error:
        return error
    scope = str(request.query_params.get("scope") or "").strip()
    if not _valid_scope(scope):
        return JSONResponse({"error": "unsupported scope"}, status_code=400)
    status = str(request.query_params.get("status") or "pending_business_gold_review").strip().casefold()
    if status not in _BENCHMARK_QUEUE_STATUSES:
        return JSONResponse({"error": "unsupported benchmark review queue status"}, status_code=400)
    try:
        offset = _query_int(request, "offset", 0, 1_000_000)
        limit = _query_int(request, "limit", 25, _MAX_LIMIT)
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    search = str(request.query_params.get("search") or "").strip().casefold()
    queue = _benchmark_review_queue(scope)
    persisted_reviews, review_registry_available = _benchmark_reviews(scope)
    raw_items = [item for item in queue.get("tasks") or [] if isinstance(item, dict)]
    filtered: list[dict[str, Any]] = []
    for item in raw_items:
        task_id = str(item.get("task_id") or "")
        review = persisted_reviews.get(task_id)
        item_status = (
            "reviewed"
            if review or str(item.get("review_status") or "").casefold() == "reviewed"
            else "pending_business_gold_review"
        )
        if status != "all" and item_status != status:
            continue
        if search and search not in json.dumps(item, ensure_ascii=False).casefold():
            continue
        allowed = (
            "task_id",
            "kind",
            "physical_table",
            "physical_field",
            "business_asset_id",
            "operation",
            "field_role",
            "labels",
            "question_templates",
            "languages",
            "review_status",
            "semantic_review_status",
            "requires_semantic_review",
            "promotion_requirements",
            "dictionary_evidence",
        )
        public_item = {key: item.get(key) for key in allowed if key in item}
        # Preserve the generated candidate status separately.  The effective
        # status includes a persisted reviewer decision, while the candidate
        # artifact remains immutable evidence.
        public_item["candidate_review_status"] = item.get("review_status")
        public_item["review_status"] = item_status
        public_item["review"] = review
        filtered.append(_public_evidence_value(public_item))
    coverage = dict(queue.get("coverage") or {})
    review_counts = {"approved_for_gold": 0, "rejected": 0, "needs_changes": 0}
    for item in persisted_reviews.values():
        decision = str(item.get("decision") or "")
        if decision in review_counts:
            review_counts[decision] += 1
    coverage.update(
        {
            "persisted_review_count": len(persisted_reviews),
            "approved_for_gold_review_count": review_counts["approved_for_gold"],
            "rejected_review_count": review_counts["rejected"],
            "needs_changes_review_count": review_counts["needs_changes"],
        }
    )
    return JSONResponse(
        {
            "schema": "gda.abu-dhabi-business-benchmark-review-queue.v1",
            "scope": scope,
            "status": status,
            "search": search,
            "items": filtered[offset : offset + limit],
            "total": len(filtered),
            "has_more": offset + limit < len(filtered),
            "offset": offset,
            "limit": limit,
            "coverage": coverage,
            "claim_boundary": {
                "is_scored_benchmark": False,
                "is_gold_set": False,
                "gold_sql_present": False,
                "runtime_router_input": False,
                "requires_business_review_before_promotion": True,
                "review_registry_available": review_registry_available,
                "approved_review_is_not_gold": True,
            },
            "source": _public_evidence_value(queue.get("source") or {}),
        }
    )


async def semantic_benchmark_review(request: Request) -> JSONResponse:
    """Persist one expert decision for a generated question slot.

    The decision is deliberately separate from both the immutable queue
    artifact and Gold contracts.  ``approved_for_gold`` means that a later
    contract-generation workflow may consider the slot; it never supplies SQL,
    expected results, or runtime routing rules.
    """
    username, _role, error = _auth(request, mutation=True, review=True)
    if error:
        return error
    scope = str(request.query_params.get("scope") or "").strip()
    task_id = str(request.path_params.get("task_id") or "").strip()
    if not _valid_scope(scope) or not task_id or len(task_id) > 255:
        return JSONResponse({"error": "unsupported scope or task_id"}, status_code=400)
    queue = _benchmark_review_queue(scope)
    task = next(
        (
            item
            for item in queue.get("tasks") or []
            if isinstance(item, dict) and str(item.get("task_id") or "") == task_id
        ),
        None,
    )
    if task is None:
        return JSONResponse({"error": "benchmark_task_not_found"}, status_code=404)
    try:
        body = await request.json()
        decision = _validate_benchmark_review_payload(body)
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    engine = _engine()
    if not engine:
        return JSONResponse({"error": "database_unavailable"}, status_code=503)
    evidence = {
        "queue_item": {
            key: task.get(key)
            for key in (
                "kind",
                "physical_table",
                "physical_field",
                "business_asset_id",
                "operation",
                "field_role",
            )
            if task.get(key) is not None
        },
        "queue_source": _public_evidence_value(queue.get("source") or {}),
        "is_gold": False,
    }
    try:
        with engine.begin() as conn:
            row = (
                conn.execute(
                    text(
                        "INSERT INTO agent_business_benchmark_reviews "
                        "(scope, task_id, decision, review_notes, question_templates, evidence, reviewed_by, reviewed_at, updated_at) "
                        "VALUES (:scope, :task_id, :decision, :notes, CAST(:templates AS jsonb), CAST(:evidence AS jsonb), :user, NOW(), NOW()) "
                        "ON CONFLICT (scope, task_id) DO UPDATE SET "
                        "decision=EXCLUDED.decision, review_notes=EXCLUDED.review_notes, "
                        "question_templates=EXCLUDED.question_templates, evidence=EXCLUDED.evidence, "
                        "reviewed_by=EXCLUDED.reviewed_by, reviewed_at=NOW(), updated_at=NOW() "
                        "RETURNING task_id, decision, review_notes, question_templates, evidence, reviewed_by, reviewed_at, updated_at"
                    ),
                    {
                        "scope": scope,
                        "task_id": task_id,
                        "decision": decision["decision"],
                        "notes": decision["review_notes"],
                        "templates": json.dumps(decision["question_templates"], ensure_ascii=False),
                        "evidence": json.dumps(evidence, ensure_ascii=False),
                        "user": username,
                    },
                )
                .mappings()
                .one()
            )
        payload = _public_evidence_value(
            {
                "task_id": row["task_id"],
                "decision": row["decision"],
                "review_notes": row["review_notes"] or "",
                "question_templates": row["question_templates"],
                "evidence": row["evidence"],
                "reviewed_by": row["reviewed_by"],
                "reviewed_at": row["reviewed_at"],
                "updated_at": row["updated_at"],
                "is_gold": False,
                "runtime_effect": "none_until_explicit_gold_generation_and_runtime_promotion",
            }
        )
        return JSONResponse(
            {
                "schema": "gda.abu-dhabi-business-benchmark-review.v1",
                "scope": scope,
                "review": payload,
            },
            status_code=200,
        )
    except Exception as exc:
        logger.exception("business benchmark review registry write failed")
        return JSONResponse(
            {"error": "benchmark_review_write_failed", "detail": str(exc)[:200]},
            status_code=503,
        )


def _body(request: Request) -> dict[str, Any]:
    # Starlette caches the parsed body, so this helper stays small and testable.
    raise RuntimeError("body helper must be awaited")


async def semantic_admin_create(request: Request) -> JSONResponse:
    username, _role, error = _auth(request, mutation=True)
    if error:
        return error
    scope = str(request.query_params.get("scope") or "").strip()
    entry_type = str(request.path_params.get("entry_type") or "").strip()
    if not _valid_scope(scope) or entry_type not in _ENTRY_TYPES:
        return JSONResponse({"error": "unsupported scope or entry_type"}, status_code=400)
    try:
        body = await request.json()
        payload = _validate_payload(entry_type, body.get("payload", body))
        key = _natural_key(entry_type, payload)
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    engine = _engine()
    if not engine:
        return JSONResponse({"error": "database_unavailable"}, status_code=503)
    try:
        with engine.begin() as conn:
            version = conn.execute(
                text(
                    "SELECT id FROM agent_semantic_admin_versions WHERE scope=:scope AND status='draft' "
                    "ORDER BY id DESC LIMIT 1 FOR UPDATE"
                ),
                {"scope": scope},
            ).scalar()
            if version is None:
                version = conn.execute(
                    text(
                        "INSERT INTO agent_semantic_admin_versions(scope, version_label, created_by) "
                        "VALUES (:scope, :label, :user) RETURNING id"
                    ),
                    {
                        "scope": scope,
                        "label": f"draft-{scope}-{int(datetime.now().timestamp())}",
                        "user": username,
                    },
                ).scalar()
            row = (
                conn.execute(
                    text(
                        "INSERT INTO agent_semantic_admin_entries(version_id, scope, entry_type, natural_key, payload, created_by, updated_by) "
                        "VALUES (:version,:scope,:kind,:key,CAST(:payload AS jsonb),:user,:user) "
                        "ON CONFLICT (version_id,entry_type,natural_key) DO UPDATE SET payload=EXCLUDED.payload,state='draft',updated_by=EXCLUDED.updated_by,updated_at=NOW() "
                        "RETURNING id, version_id"
                    ),
                    {
                        "version": version,
                        "scope": scope,
                        "kind": entry_type,
                        "key": key,
                        "payload": json.dumps(payload, ensure_ascii=False),
                        "user": username,
                    },
                )
                .mappings()
                .one()
            )
        return JSONResponse(
            _entry_response(
                str(row["id"]),
                entry_type,
                payload,
                state="draft",
                source="registry",
                version_id=int(row["version_id"]),
            ),
            status_code=201,
        )
    except Exception as exc:
        logger.exception("semantic admin create failed")
        return JSONResponse(
            {"error": "semantic_registry_write_failed", "detail": str(exc)[:200]}, status_code=503
        )


async def semantic_admin_update(request: Request) -> JSONResponse:
    username, _role, error = _auth(request, mutation=True)
    if error:
        return error
    entry_id = str(request.path_params.get("entry_id") or "")
    entry_type = str(request.path_params.get("entry_type") or "")
    scope = str(request.query_params.get("scope") or "")
    if not _valid_scope(scope) or entry_type not in _ENTRY_TYPES or not entry_id:
        return JSONResponse(
            {"error": "unsupported scope, entry_type, or entry_id"}, status_code=400
        )
    try:
        body = await request.json()
        payload = _validate_payload(entry_type, body.get("payload", body))
        key = _natural_key(entry_type, payload)
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    engine = _engine()
    if not engine:
        return JSONResponse({"error": "database_unavailable"}, status_code=503)
    try:
        with engine.begin() as conn:
            version = conn.execute(
                text(
                    "SELECT id FROM agent_semantic_admin_versions WHERE scope=:scope AND status='draft' ORDER BY id DESC LIMIT 1 FOR UPDATE"
                ),
                {"scope": scope},
            ).scalar()
            if version is None:
                version = conn.execute(
                    text(
                        "INSERT INTO agent_semantic_admin_versions(scope,version_label,created_by) VALUES (:scope,:label,:user) RETURNING id"
                    ),
                    {
                        "scope": scope,
                        "label": f"draft-{scope}-{int(datetime.now().timestamp())}",
                        "user": username,
                    },
                ).scalar()
            numeric_id = int(entry_id) if entry_id.isdigit() else None
            prior_key = None
            if numeric_id:
                existing = conn.execute(
                    text(
                        "SELECT natural_key FROM agent_semantic_admin_entries WHERE id=:id AND scope=:scope"
                    ),
                    {"id": numeric_id, "scope": scope},
                ).scalar()
                if existing is None:
                    return JSONResponse({"error": "entry_not_found"}, status_code=404)
                prior_key = str(existing)
            elif entry_id.startswith(f"artifact:{entry_type}:"):
                prior_key = entry_id.removeprefix(f"artifact:{entry_type}:")
            row = (
                conn.execute(
                    text(
                        "INSERT INTO agent_semantic_admin_entries(version_id,scope,entry_type,natural_key,payload,created_by,updated_by) "
                        "VALUES (:version,:scope,:kind,:key,CAST(:payload AS jsonb),:user,:user) "
                        "ON CONFLICT (version_id,entry_type,natural_key) DO UPDATE SET payload=EXCLUDED.payload,state='draft',updated_by=EXCLUDED.updated_by,updated_at=NOW() RETURNING id,version_id"
                    ),
                    {
                        "version": version,
                        "scope": scope,
                        "kind": entry_type,
                        "key": key,
                        "payload": json.dumps(payload, ensure_ascii=False),
                        "user": username,
                    },
                )
                .mappings()
                .one()
            )
            if prior_key and prior_key != key:
                conn.execute(
                    text(
                        "INSERT INTO agent_semantic_admin_entries "
                        "(version_id,scope,entry_type,natural_key,payload,state,created_by,updated_by) "
                        "VALUES (:version,:scope,:kind,:key,'{}'::jsonb,'deleted',:user,:user) "
                        "ON CONFLICT (version_id,entry_type,natural_key) DO UPDATE SET "
                        "state='deleted',updated_by=EXCLUDED.updated_by,updated_at=NOW()"
                    ),
                    {
                        "version": version,
                        "scope": scope,
                        "kind": entry_type,
                        "key": prior_key,
                        "user": username,
                    },
                )
        return JSONResponse(
            _entry_response(
                str(row["id"]),
                entry_type,
                payload,
                state="draft",
                source="registry",
                version_id=int(row["version_id"]),
            )
        )
    except Exception as exc:
        logger.exception("semantic admin update failed")
        return JSONResponse(
            {"error": "semantic_registry_write_failed", "detail": str(exc)[:200]}, status_code=503
        )


async def semantic_admin_delete(request: Request) -> JSONResponse:
    username, _role, error = _auth(request, mutation=True)
    if error:
        return error
    scope = str(request.query_params.get("scope") or "")
    entry_type = str(request.path_params.get("entry_type") or "")
    entry_id = str(request.path_params.get("entry_id") or "")
    if not _valid_scope(scope) or entry_type not in _ENTRY_TYPES or not entry_id:
        return JSONResponse(
            {"error": "unsupported scope, entry_type, or entry_id"}, status_code=400
        )
    engine = _engine()
    if not engine:
        return JSONResponse({"error": "database_unavailable"}, status_code=503)
    try:
        with engine.begin() as conn:
            if entry_id.isdigit():
                existing = conn.execute(
                    text(
                        "SELECT natural_key FROM agent_semantic_admin_entries "
                        "WHERE id=:id AND scope=:scope AND entry_type=:kind"
                    ),
                    {"id": int(entry_id), "scope": scope, "kind": entry_type, "user": username},
                ).scalar()
                if existing is None:
                    return JSONResponse({"error": "entry_not_found"}, status_code=404)
                key = str(existing)
            else:
                # A baseline artifact is immutable; represent a requested deletion
                # as a tombstone in the current draft instead of editing the file.
                key = entry_id.removeprefix(f"artifact:{entry_type}:")
            version = conn.execute(
                text(
                    "SELECT id FROM agent_semantic_admin_versions WHERE scope=:scope "
                    "AND status='draft' ORDER BY id DESC LIMIT 1 FOR UPDATE"
                ),
                {"scope": scope},
            ).scalar()
            if version is None:
                version = conn.execute(
                    text(
                        "INSERT INTO agent_semantic_admin_versions(scope,version_label,created_by) "
                        "VALUES (:scope,:label,:user) RETURNING id"
                    ),
                    {
                        "scope": scope,
                        "label": f"draft-{scope}-{int(datetime.now().timestamp())}",
                        "user": username,
                    },
                ).scalar()
            result = conn.execute(
                text(
                    "INSERT INTO agent_semantic_admin_entries(version_id,scope,entry_type,natural_key,payload,state,created_by,updated_by) "
                    "VALUES (:version,:scope,:kind,:key,'{}'::jsonb,'deleted',:user,:user) "
                    "ON CONFLICT (version_id,entry_type,natural_key) DO UPDATE SET state='deleted',updated_by=EXCLUDED.updated_by,updated_at=NOW()"
                ),
                {
                    "version": version,
                    "scope": scope,
                    "kind": entry_type,
                    "key": key,
                    "user": username,
                },
            )
        if not result.rowcount:
            return JSONResponse({"error": "entry_not_found"}, status_code=404)
        return JSONResponse(
            {"status": "deleted", "runtime_effect": "none_until_explicit_runtime_promotion"}
        )
    except Exception as exc:
        logger.exception("semantic admin delete failed")
        return JSONResponse(
            {"error": "semantic_registry_write_failed", "detail": str(exc)[:200]}, status_code=503
        )


async def semantic_admin_version_action(request: Request) -> JSONResponse:
    username, role, error = _auth(request, mutation=True, review=True)
    if error:
        return error
    version_id = str(request.path_params.get("version_id") or "")
    action = str(request.path_params.get("action") or "")
    if not version_id.isdigit() or action not in {"validate", "publish", "rollback"}:
        return JSONResponse({"error": "unsupported version action"}, status_code=400)
    engine = _engine()
    if not engine:
        return JSONResponse({"error": "database_unavailable"}, status_code=503)
    try:
        with engine.connect() as conn:
            row = (
                conn.execute(
                    text("SELECT id,scope,status FROM agent_semantic_admin_versions WHERE id=:id"),
                    {"id": int(version_id)},
                )
                .mappings()
                .first()
            )
        if not row:
            return JSONResponse({"error": "version_not_found"}, status_code=404)
        report = _validate_version(str(row["scope"]), int(row["id"]))
        if action == "validate":
            with engine.begin() as conn:
                conn.execute(
                    text(
                        "UPDATE agent_semantic_admin_versions SET validation_report=CAST(:report AS jsonb),status=CASE WHEN :valid THEN 'reviewed' ELSE 'draft' END,reviewed_by=:user,reviewed_at=NOW(),updated_at=NOW() WHERE id=:id"
                    ),
                    {
                        "report": json.dumps(report, ensure_ascii=False),
                        "valid": bool(report["valid"]),
                        "user": username,
                        "id": int(version_id),
                    },
                )
            return JSONResponse(report)
        if action == "publish":
            if not report["valid"]:
                return JSONResponse(
                    {"error": "version_validation_failed", "validation": report}, status_code=409
                )
            with engine.begin() as conn:
                conn.execute(
                    text(
                        "UPDATE agent_semantic_admin_versions SET status='rolled_back',updated_at=NOW() WHERE scope=:scope AND status='published'"
                    ),
                    {"scope": row["scope"]},
                )
                conn.execute(
                    text(
                        "UPDATE agent_semantic_admin_versions SET status='published',published_by=:user,published_at=NOW(),updated_at=NOW(),validation_report=CAST(:report AS jsonb) WHERE id=:id"
                    ),
                    {
                        "user": username,
                        "report": json.dumps(report, ensure_ascii=False),
                        "id": int(version_id),
                    },
                )
                conn.execute(
                    text(
                        "UPDATE agent_semantic_admin_entries SET state='published',updated_at=NOW() WHERE version_id=:id AND state='draft'"
                    ),
                    {"id": int(version_id)},
                )
            return JSONResponse(
                {
                    "status": "published",
                    "version_id": int(version_id),
                    "runtime_effect": "requires_explicit_runtime_promotion",
                    "validation": report,
                }
            )
        with engine.begin() as conn:
            conn.execute(
                text(
                    "UPDATE agent_semantic_admin_versions SET status='rolled_back',updated_at=NOW() WHERE id=:id"
                ),
                {"id": int(version_id)},
            )
        return JSONResponse({"status": "rolled_back", "version_id": int(version_id)})
    except Exception as exc:
        logger.exception("semantic admin version action failed")
        return JSONResponse(
            {"error": "semantic_version_action_failed", "detail": str(exc)[:200]}, status_code=503
        )


def _artifact_metadata(scope: str) -> tuple[str | None, list[dict[str, Any]]]:
    """Return technical-catalog evidence when live discovery is not present."""
    semantic = _artifact(scope)
    catalog = _catalog(scope)
    database_name = (semantic.get("source_binding") or {}).get("database_name")
    resources: list[dict[str, Any]] = []
    for item in catalog.get("resources") or []:
        fields = []
        for field in item.get("fields") or []:
            technical = field.get("technical_metadata") or {}
            fields.append(
                {
                    "name": field.get("physical_field") or field.get("semantic_field"),
                    "type": field.get("data_type") or technical.get("data_type") or "unknown",
                    "nullable": (
                        field.get("nullable")
                        if field.get("nullable") is not None
                        else technical.get("nullable", True)
                    ),
                }
            )
        physical_table = str(item.get("physical_table") or "")
        resources.append(
            {
                "schema": physical_table.split(".")[0] or "public",
                "name": physical_table.split(".")[-1],
                "columns": fields,
                "primary_key": list(item.get("primary_key") or []),
                "foreign_keys": list(item.get("foreign_keys") or []),
                "indexes": list(item.get("indexes") or []),
                "estimated_record_count": item.get("estimated_record_count"),
            }
        )
    return database_name, resources


def _metadata_view(
    source: dict[str, Any],
    discovery: dict[str, Any] | None,
    *,
    scope: str | None = None,
) -> dict[str, Any]:
    snapshot = (discovery or {}).get("discovery_snapshot") or {}
    profile = (discovery or {}).get("profile_snapshot") or {}
    resources = snapshot.get("resources") or []
    metadata_origin = "virtual_source_discovery_snapshot"
    if not resources and scope:
        fallback_database, resources = _artifact_metadata(scope)
        if not snapshot.get("database_name"):
            snapshot["database_name"] = fallback_database
        metadata_origin = "artifact_technical_catalog_evidence"
    normalized_resources: list[dict[str, Any]] = []
    for raw_resource in resources:
        resource = dict(raw_resource)
        qualified_name = str(resource.get("qualified_name") or resource.get("name") or "")
        if "." in qualified_name and not resource.get("schema"):
            resource["schema"], resource["name"] = qualified_name.split(".", 1)
        resource["qualified_name"] = qualified_name
        normalized_resources.append(resource)
    resources = normalized_resources
    return {
        "source_id": source.get("id"),
        "source_name": source.get("source_name"),
        "database_name": (
            snapshot.get("database_name") or (source.get("query_config") or {}).get("database")
        ),
        "source_type": source.get("source_type"),
        "metadata_origin": metadata_origin,
        "default_crs": source.get("default_crs") or "EPSG:4326",
        "spatial_extent": _jsonable(source.get("spatial_extent")),
        "virtual_ingestion_mode": "metadata_only_virtual_source",
        "source_rows_persisted": False,
        "registration_status": "registered",
        "health_status": source.get("health_status") or "unknown",
        "discovery_status": discovery.get("discovery_status")
        if discovery
        else source.get("discovery_status", "not_run"),
        "discovery_fingerprint": discovery.get("discovery_fingerprint")
        if discovery
        else source.get("discovery_fingerprint"),
        "profile_fingerprint": discovery.get("profile_fingerprint")
        if discovery
        else source.get("profile_fingerprint"),
        "last_discovery_at": discovery.get("last_discovery_at")
        if discovery
        else source.get("last_discovery_at"),
        "discovery_error": discovery.get("discovery_error") if discovery else None,
        "schema_count": len({str(item.get("schema") or "public") for item in resources}),
        "resource_count": len(resources),
        "field_count": int(
            profile.get("field_count") or sum(len(item.get("columns") or []) for item in resources)
        ),
        "geometry_resource_count": int(
            profile.get("geometry_resource_count")
            or sum(
                any(
                    "geometry" in str(column.get("type") or "").casefold()
                    for column in item.get("columns") or []
                )
                for item in resources
            )
        ),
        "profile": _jsonable(profile),
        "resources": _jsonable(resources),
    }


async def virtual_lake_metadata(request: Request) -> JSONResponse:
    username, _role, error = _auth(request)
    if error:
        return error
    from ..virtual_sources import get_virtual_source, get_virtual_source_discovery

    try:
        source_id = request.path_params.get("source_id")
        source_ids = [int(source_id)] if source_id else [12, 13]
    except (TypeError, ValueError):
        return JSONResponse({"error": "invalid source_id"}, status_code=400)
    result = []
    for item in source_ids:
        source = get_virtual_source(item, username)
        scope = "liveability" if item == 12 else "makani" if item == 13 else None
        if not source and scope:
            semantic = _artifact(scope)
            binding = semantic.get("source_binding") or {}
            source = {
                "id": item,
                "source_name": scope,
                "source_type": "database",
                "query_config": {"database": binding.get("database_name")},
                "health_status": "not_visible",
                "discovery_status": "not_run",
            }
        if not source:
            continue
        result.append(
            _metadata_view(
                source,
                get_virtual_source_discovery(item, username),
                scope=scope,
            )
        )
    if source_id and not result:
        return JSONResponse({"error": "source_not_found"}, status_code=404)
    return JSONResponse(
        {
            "schema": "gda.abu-dhabi-virtual-lake-metadata.v1",
            "items": result,
            "source_rows_persisted": False,
        }
    )


async def virtual_lake_discover(request: Request) -> JSONResponse:
    username, _role, error = _auth(request, mutation=True)
    if error:
        return error
    source_id = request.path_params.get("source_id")
    try:
        source_id = int(source_id)
    except (TypeError, ValueError):
        return JSONResponse({"error": "invalid source_id"}, status_code=400)
    from ..virtual_sources import discover_virtual_source

    result = await discover_virtual_source(source_id, username)
    if result.get("status") == "error":
        return JSONResponse({"error": result.get("message", "discovery_failed")}, status_code=502)
    return JSONResponse(
        {
            "status": "succeeded",
            "source_id": source_id,
            "source_rows_persisted": False,
            "discovery": result,
        }
    )


def get_abu_dhabi_semantic_admin_routes() -> list[Route]:
    routes: list[Route] = []
    # Exact paths must precede the /{entry_type} routes below; otherwise
    # ``review-queue`` would be interpreted as an entry type.
    routes.extend(
        [
            Route(
                "/api/abu-dhabi/nl2semantic2sql/semantic-admin/benchmark-review-queue",
                semantic_benchmark_review_queue,
                methods=["GET"],
            ),
            Route(
                "/api/abu-dhabi/nl2semantic2sql/semantic-admin/benchmark-review-queue/{task_id}/review",
                semantic_benchmark_review,
                methods=["POST"],
            ),
            Route(
                "/api/semantic/governance/benchmark-review-queue",
                semantic_benchmark_review_queue,
                methods=["GET"],
            ),
            Route(
                "/api/semantic/governance/benchmark-review-queue/{task_id}/review",
                semantic_benchmark_review,
                methods=["POST"],
            ),
            Route(
                "/api/abu-dhabi/nl2semantic2sql/semantic-admin/review-queue",
                semantic_review_queue,
                methods=["GET"],
            ),
            Route(
                "/api/semantic/governance/review-queue",
                semantic_review_queue,
                methods=["GET"],
            ),
            Route(
                "/api/abu-dhabi/nl2semantic2sql/semantic-admin/review-queue/{kind}/{task_id}/review",
                semantic_review,
                methods=["POST"],
            ),
            Route(
                "/api/semantic/governance/review-queue/{kind}/{task_id}/review",
                semantic_review,
                methods=["POST"],
            ),
        ]
    )
    for entry_type in sorted(_ENTRY_TYPES):
        routes.extend(
            [
                Route(
                    f"/api/abu-dhabi/nl2semantic2sql/semantic-admin/{entry_type}",
                    semantic_admin_entries,
                    methods=["GET"],
                ),
                Route(
                    f"/api/abu-dhabi/nl2semantic2sql/semantic-admin/{entry_type}",
                    semantic_admin_create,
                    methods=["POST"],
                ),
                Route(
                    f"/api/abu-dhabi/nl2semantic2sql/semantic-admin/{entry_type}/{{entry_id}}",
                    semantic_admin_update,
                    methods=["PATCH"],
                ),
                Route(
                    f"/api/abu-dhabi/nl2semantic2sql/semantic-admin/{entry_type}/{{entry_id}}",
                    semantic_admin_delete,
                    methods=["DELETE"],
                ),
                # Generic alias used by the unified semantic workspace. The
                # legacy product path above remains for existing clients.
                Route(
                    f"/api/semantic/governance/{entry_type}",
                    semantic_admin_entries,
                    methods=["GET"],
                ),
                Route(
                    f"/api/semantic/governance/{entry_type}",
                    semantic_admin_create,
                    methods=["POST"],
                ),
                Route(
                    f"/api/semantic/governance/{entry_type}/{{entry_id}}",
                    semantic_admin_update,
                    methods=["PATCH"],
                ),
                Route(
                    f"/api/semantic/governance/{entry_type}/{{entry_id}}",
                    semantic_admin_delete,
                    methods=["DELETE"],
                ),
            ]
        )
    return routes + [
        Route(
            "/api/abu-dhabi/nl2semantic2sql/semantic-admin/versions/{version_id}/{action}",
            semantic_admin_version_action,
            methods=["POST"],
        ),
        Route(
            "/api/semantic/governance/versions/{version_id}/{action}",
            semantic_admin_version_action,
            methods=["POST"],
        ),
        Route(
            "/api/abu-dhabi/nl2semantic2sql/virtual-lake-metadata",
            virtual_lake_metadata,
            methods=["GET"],
        ),
        Route(
            "/api/abu-dhabi/nl2semantic2sql/virtual-lake-metadata/{source_id:int}",
            virtual_lake_metadata,
            methods=["GET"],
        ),
        Route(
            "/api/abu-dhabi/nl2semantic2sql/virtual-lake-metadata/{source_id:int}/discover",
            virtual_lake_discover,
            methods=["POST"],
        ),
    ]


__all__ = ["get_abu_dhabi_semantic_admin_routes"]
