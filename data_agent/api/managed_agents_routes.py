"""CRUD and lifecycle routes for versioned, deployable custom agents."""

import json
import re
from datetime import date, datetime
from typing import Any

from sqlalchemy import text
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from ..custom_skills import TOOLSET_NAMES, VALID_MODEL_TIERS
from ..db_engine import get_engine
from ..user_context import current_tenant_id
from .helpers import _get_user_from_request, _set_user_context


_SLUG_RE = re.compile(r"[^a-z0-9-]+")
_MAX_INSTRUCTION_LENGTH = 10000
_DATA_POLICY_MODES = {"inherit", "read_only", "restricted"}
_DATA_POLICY_FIELDS = {
    "mode", "allowed_resources", "allow_mutations", "allow_discovery",
}
_ALLOWED_FIELDS = {
    "name", "description", "instruction", "model_tier", "allowed_toolsets",
    "skill_refs", "data_policy", "budget_policy", "output_schema",
}


def _json_value(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: _json_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(v) for v in value]
    return value


def _scope(user: Any) -> tuple[str, str, str, bool]:
    username, role = _set_user_context(user)
    tenant_id = current_tenant_id.get().strip() or "local-dev"
    return username, role, tenant_id, role == "admin"


def _slug(name: str) -> str:
    return _SLUG_RE.sub("-", name.strip().lower()).strip("-")[:140] or "agent"


def _validate_data_policy(value: object) -> tuple[dict | None, str | None]:
    """Normalise the policy stored in an immutable Agent Version snapshot."""
    if value is None:
        value = {}
    if not isinstance(value, dict):
        return None, "data_policy must be an object"
    unknown = sorted(set(value) - _DATA_POLICY_FIELDS)
    if unknown:
        return None, f"Unsupported data_policy fields: {', '.join(unknown)}"
    mode = value.get("mode", "inherit")
    if not isinstance(mode, str) or mode not in _DATA_POLICY_MODES:
        return None, f"data_policy.mode must be one of {sorted(_DATA_POLICY_MODES)}"
    resources = value.get("allowed_resources", [])
    if not isinstance(resources, list) or any(
        not isinstance(item, str) or not item.strip() or len(item.strip()) > 512
        for item in resources
    ):
        return None, "data_policy.allowed_resources must be a list of non-empty strings"
    resources = [item.strip() for item in resources]
    if len(resources) != len(set(resources)):
        return None, "data_policy.allowed_resources cannot contain duplicates"
    if mode == "restricted" and not resources:
        return None, "restricted data_policy requires at least one allowed resource"
    for flag in ("allow_mutations", "allow_discovery"):
        if flag in value and not isinstance(value[flag], bool):
            return None, f"data_policy.{flag} must be a boolean"
    return {
        "mode": mode,
        "allowed_resources": resources,
        "allow_mutations": bool(value.get("allow_mutations", False)),
        "allow_discovery": bool(value.get("allow_discovery", False)),
    }, None


def _validate_spec(body: dict, *, require_name: bool = True) -> tuple[dict | None, str | None]:
    unknown = sorted(set(body) - _ALLOWED_FIELDS)
    if unknown:
        return None, f"Unsupported fields: {', '.join(unknown)}"
    name = body.get("name", "").strip() if isinstance(body.get("name", ""), str) else ""
    if require_name and (not name or len(name) > 120):
        return None, "name is required and must be at most 120 characters"
    instruction = body.get("instruction", "")
    if not isinstance(instruction, str) or not instruction.strip():
        return None, "instruction is required"
    if len(instruction) > _MAX_INSTRUCTION_LENGTH:
        return None, f"instruction exceeds {_MAX_INSTRUCTION_LENGTH} characters"
    lower_instruction = instruction.lower()
    for marker in ("<|im_start|>", "<|im_end|>", "system:", "ignore previous", "ignore above"):
        if marker in lower_instruction:
            return None, f"instruction contains forbidden pattern: {marker}"
    model_tier = body.get("model_tier", "standard")
    if model_tier not in VALID_MODEL_TIERS:
        return None, f"model_tier must be one of {sorted(VALID_MODEL_TIERS)}"
    toolsets = body.get("allowed_toolsets", [])
    if not isinstance(toolsets, list) or any(not isinstance(v, str) for v in toolsets):
        return None, "allowed_toolsets must be a list of strings"
    unknown_tools = sorted(set(toolsets) - TOOLSET_NAMES)
    if unknown_tools:
        return None, f"unknown toolsets: {unknown_tools}"
    if len(set(toolsets)) != len(toolsets):
        return None, "allowed_toolsets cannot contain duplicates"
    skill_refs = body.get("skill_refs", [])
    if not isinstance(skill_refs, list):
        return None, "skill_refs must be a list"
    normalized_refs = []
    seen_skill_ids = set()
    for ref in skill_refs:
        if (not isinstance(ref, dict) or not isinstance(ref.get("skill_id"), int)
                or isinstance(ref.get("skill_id"), bool)):
            return None, "each skill_refs item must include an integer skill_id"
        skill_id = ref["skill_id"]
        version = ref.get("version", 1)
        if (skill_id <= 0 or not isinstance(version, int)
                or isinstance(version, bool) or version <= 0):
            return None, "skill_id and version must be positive integers"
        if skill_id in seen_skill_ids:
            return None, "skill_refs cannot contain duplicate skill_id values"
        seen_skill_ids.add(skill_id)
        normalized_refs.append({"skill_id": skill_id, "version": version})
    data_policy, data_policy_error = _validate_data_policy(body.get("data_policy", {}))
    if data_policy_error:
        return None, data_policy_error
    if "budget_policy" in body and not isinstance(body["budget_policy"], dict):
        return None, "budget_policy must be an object"
    for field in ("description", "output_schema"):
        if field in body and not isinstance(body[field], str):
            return None, f"{field} must be a string"
    return {
        "name": name,
        "description": body.get("description", ""),
        "instruction": instruction.strip(),
        "model_tier": model_tier,
        "allowed_toolsets": toolsets,
        "skill_refs": normalized_refs,
        "data_policy": data_policy,
        "budget_policy": body.get("budget_policy", {}),
        "output_schema": body.get("output_schema", ""),
    }, None


def _canonical_payload(body: dict) -> tuple[dict | None, str | None]:
    """Accept the flat API shape and the management UI's nested config shape."""
    nested = body.get("config", body.get("spec_json"))
    if nested is None:
        return body, None
    if not isinstance(nested, dict):
        return None, "config must be an object"
    payload = dict(nested)
    if "name" in body:
        payload["name"] = body["name"]
    if "data_policy" not in payload and "data_access_policy" in payload:
        mode = payload.pop("data_access_policy")
        payload["data_policy"] = mode if isinstance(mode, dict) else {"mode": mode}
    if "budget_policy" not in payload and "budget" in payload:
        budget = payload.pop("budget")
        if isinstance(budget, str):
            try:
                budget = float(budget)
            except ValueError:
                return None, "budget must be numeric"
        payload["budget_policy"] = {"max": budget}
    refs = payload.get("skill_refs", [])
    if isinstance(refs, list):
        normalized_refs = []
        for ref in refs:
            if not isinstance(ref, dict):
                normalized_refs.append(ref)
                continue
            normalized = dict(ref)
            for field in ("skill_id", "version"):
                value = normalized.get(field)
                if isinstance(value, str) and value.isdigit():
                    normalized[field] = int(value)
            normalized_refs.append(normalized)
        payload["skill_refs"] = normalized_refs
    return payload, None


def _skill_snapshot(conn, skill_id: int, version: int) -> dict | None:
    row = conn.execute(text("""
        SELECT instruction, description, toolset_names
        FROM agent_skill_versions WHERE skill_id = :skill AND version = :version
    """), {"skill": skill_id, "version": version}).mappings().first()
    if not row:
        return None
    return {
        "instruction": row["instruction"],
        "description": row["description"] or "",
        "toolset_names": list(row["toolset_names"] or []),
    }


def _check_skill_refs(conn, refs: list[dict], username: str, is_admin: bool) -> str | None:
    for ref in refs:
        row = conn.execute(text("""
            SELECT owner_username, is_shared, enabled
            FROM agent_custom_skills WHERE id = :id
        """), {"id": ref["skill_id"]}).mappings().first()
        if not row or (row["owner_username"] != username and not row["is_shared"]):
            return f"skill {ref['skill_id']} is not available to this user"
        if not row["enabled"]:
            return f"skill {ref['skill_id']} is disabled"
        if _skill_snapshot(conn, ref["skill_id"], ref["version"]) is None:
            return f"skill {ref['skill_id']} version {ref['version']} does not exist"
    return None


def _agent_record(conn, agent_id: int, tenant_id: str, username: str, is_admin: bool) -> dict | None:
    owner_clause = "" if is_admin else " AND d.owner_username = :owner"
    row = conn.execute(text(f"""
        SELECT d.*, v.id AS version_id, v.version AS version_number,
               v.status AS version_status, v.spec_json, v.test_passed_at,
               dep.id AS deployment_id, dep.revision AS deployment_revision,
               dep.state AS deployment_state
        FROM agent_definitions d
        JOIN agent_versions v ON v.agent_id = d.id AND v.version = d.current_version
        LEFT JOIN LATERAL (
            SELECT * FROM agent_deployments x
            WHERE x.agent_id = d.id AND x.environment = 'production'
            ORDER BY x.revision DESC LIMIT 1
        ) dep ON TRUE
        WHERE d.id = :id AND d.tenant_id = :tenant {owner_clause}
    """), {"id": agent_id, "tenant": tenant_id, "owner": username}).mappings().first()
    if not row:
        return None
    data = dict(row)
    data["spec"] = _json_value(data.pop("spec_json") or {})
    for key in ("created_at", "updated_at", "archived_at", "test_passed_at"):
        if data.get(key) is not None:
            data[key] = _json_value(data[key])
    data["id"] = str(data["id"])
    return data


def _record_event(conn, agent_id: int, version: int, event: str, actor: str, details: dict | None = None):
    conn.execute(text("""
        INSERT INTO agent_lifecycle_events (agent_id, version, event_type, actor_username, details)
        VALUES (:agent, :version, :event, :actor, CAST(:details AS jsonb))
    """), {"agent": agent_id, "version": version, "event": event,
           "actor": actor, "details": json.dumps(details or {})})


def _get_engine_or_error():
    engine = get_engine()
    if engine is None:
        return None, JSONResponse({"error": "Database is not configured"}, status_code=503)
    return engine, None


async def managed_agents_list(request: Request):
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    username, _role, tenant_id, is_admin = _scope(user)
    engine, error = _get_engine_or_error()
    if error:
        return error
    owner_clause = "" if is_admin else " AND d.owner_username = :owner"
    with engine.connect() as conn:
        rows = conn.execute(text(f"""
            SELECT d.id, d.name, d.slug, d.description, d.status,
                   d.current_version, d.active_version, d.owner_username,
                   d.created_at, d.updated_at, v.spec_json,
                   dep.revision AS deployment_revision
            FROM agent_definitions d
            JOIN agent_versions v ON v.agent_id = d.id AND v.version = d.current_version
            LEFT JOIN LATERAL (
                SELECT revision FROM agent_deployments x
                WHERE x.agent_id = d.id AND x.environment = 'production' AND x.state = 'active'
                ORDER BY x.revision DESC LIMIT 1
            ) dep ON TRUE
            WHERE d.tenant_id = :tenant AND d.status <> 'archived' {owner_clause}
            ORDER BY d.updated_at DESC
        """), {"tenant": tenant_id, "owner": username}).mappings().all()
    agents = []
    for row in rows:
        item = dict(row)
        item["spec"] = _json_value(item.pop("spec_json") or {})
        item["id"] = str(item["id"])
        item["created_at"] = _json_value(item["created_at"])
        item["updated_at"] = _json_value(item["updated_at"])
        agents.append(item)
    return JSONResponse({"agents": agents})


async def managed_agents_create(request: Request):
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    username, _role, tenant_id, is_admin = _scope(user)
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON body"}, status_code=400)
    if not isinstance(body, dict):
        return JSONResponse({"error": "JSON body must be an object"}, status_code=400)
    body, error_text = _canonical_payload(body)
    if error_text:
        return JSONResponse({"error": error_text}, status_code=400)
    spec, error_text = _validate_spec(body)
    if error_text:
        return JSONResponse({"error": error_text}, status_code=400)
    engine, error = _get_engine_or_error()
    if error:
        return error
    with engine.begin() as conn:
        error_text = _check_skill_refs(conn, spec["skill_refs"], username, is_admin)
        if error_text:
            return JSONResponse({"error": error_text}, status_code=400)
        try:
            agent = conn.execute(text("""
                INSERT INTO agent_definitions
                    (tenant_id, owner_username, name, slug, description)
                VALUES (:tenant, :owner, :name, :slug, :description)
                RETURNING id
            """), {"tenant": tenant_id, "owner": username, "name": spec["name"],
                   "slug": _slug(spec["name"]), "description": spec["description"]}).scalar_one()
        except Exception as exc:
            if "unique" in str(exc).lower():
                return JSONResponse({"error": "An agent with this name already exists"}, status_code=409)
            raise
        _insert_version(conn, int(agent), 1, spec, username)
        _record_event(conn, int(agent), 1, "created", username)
        record = _agent_record(conn, int(agent), tenant_id, username, is_admin)
    return JSONResponse({"agent": record}, status_code=201)


def _insert_version(conn, agent_id: int, version: int, spec: dict, username: str) -> int:
    version_id = conn.execute(text("""
        INSERT INTO agent_versions (agent_id, version, spec_json, created_by)
        VALUES (:agent, :version, CAST(:spec AS jsonb), :owner) RETURNING id
    """), {"agent": agent_id, "version": version, "spec": json.dumps(spec),
           "owner": username}).scalar_one()
    for ref in spec["skill_refs"]:
        snapshot = _skill_snapshot(conn, ref["skill_id"], ref["version"])
        if snapshot is None:
            raise ValueError(f"Missing skill snapshot {ref['skill_id']}@{ref['version']}")
        conn.execute(text("""
            INSERT INTO agent_version_skills (version_id, skill_id, skill_version, snapshot_json)
            VALUES (:version, :skill, :skill_version, CAST(:snapshot AS jsonb))
        """), {"version": version_id, "skill": ref["skill_id"],
               "skill_version": ref["version"], "snapshot": json.dumps(snapshot)})
    for toolset in spec["allowed_toolsets"]:
        conn.execute(text("""
            INSERT INTO agent_version_tools (version_id, toolset_name) VALUES (:version, :tool)
        """), {"version": version_id, "tool": toolset})
    return int(version_id)


async def managed_agents_detail(request: Request):
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    username, _role, tenant_id, is_admin = _scope(user)
    agent_id = int(request.path_params["id"])
    engine, error = _get_engine_or_error()
    if error:
        return error
    with engine.connect() as conn:
        record = _agent_record(conn, agent_id, tenant_id, username, is_admin)
        if record is None:
            return JSONResponse({"error": "Agent not found"}, status_code=404)
        versions = conn.execute(text("""
            SELECT version, status, test_passed_at, created_by, created_at
            FROM agent_versions WHERE agent_id = :agent ORDER BY version DESC
        """), {"agent": agent_id}).mappings().all()
        deployments = conn.execute(text("""
            SELECT revision, version_id, environment, state, traffic_percent, deployed_by, created_at
            FROM agent_deployments WHERE agent_id = :agent ORDER BY revision DESC
        """), {"agent": agent_id}).mappings().all()
    record["versions"] = [_json_value(dict(v)) for v in versions]
    record["deployments"] = [_json_value(dict(d)) for d in deployments]
    return JSONResponse({"agent": record})


async def managed_agents_update(request: Request):
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    username, _role, tenant_id, is_admin = _scope(user)
    agent_id = int(request.path_params["id"])
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON body"}, status_code=400)
    if not isinstance(body, dict):
        return JSONResponse({"error": "JSON body must be an object"}, status_code=400)
    engine, error = _get_engine_or_error()
    if error:
        return error
    with engine.begin() as conn:
        agent = conn.execute(text("""
            SELECT d.*, v.version AS version_number, v.status AS version_status,
                   v.spec_json, v.id AS version_id
            FROM agent_definitions d JOIN agent_versions v
                ON v.agent_id = d.id AND v.version = d.current_version
            WHERE d.id = :id AND d.tenant_id = :tenant
              AND (:admin OR d.owner_username = :owner) AND d.status <> 'archived'
            FOR UPDATE OF d
        """), {"id": agent_id, "tenant": tenant_id, "owner": username, "admin": is_admin}).mappings().first()
        if not agent:
            return JSONResponse({"error": "Agent not found"}, status_code=404)
        payload, error_text = _canonical_payload(body)
        if error_text:
            return JSONResponse({"error": error_text}, status_code=400)
        merged = dict(agent["spec_json"] or {})
        merged.update(payload)
        spec, error_text = _validate_spec(merged)
        if error_text:
            return JSONResponse({"error": error_text}, status_code=400)
        error_text = _check_skill_refs(conn, spec["skill_refs"], username, is_admin)
        if error_text:
            return JSONResponse({"error": error_text}, status_code=400)
        if agent["version_status"] == "draft":
            version_id = int(agent["version_id"])
            conn.execute(text("""
                UPDATE agent_versions SET spec_json = CAST(:spec AS jsonb), test_passed_at = NULL,
                    test_report = '{}'::jsonb WHERE id = :id
            """), {"spec": json.dumps(spec), "id": version_id})
            conn.execute(text("DELETE FROM agent_version_skills WHERE version_id = :id"), {"id": version_id})
            conn.execute(text("DELETE FROM agent_version_tools WHERE version_id = :id"), {"id": version_id})
            _sync_version_refs(conn, version_id, spec)
            version = int(agent["version_number"])
        else:
            version = int(agent["version_number"]) + 1
            _insert_version(conn, agent_id, version, spec, username)
            conn.execute(text("UPDATE agent_definitions SET current_version = :version WHERE id = :id"),
                         {"version": version, "id": agent_id})
        conn.execute(text("""
            UPDATE agent_definitions SET name = :name, slug = :slug, description = :description,
                status = 'draft', updated_at = NOW() WHERE id = :id
        """), {"name": spec["name"], "slug": _slug(spec["name"]),
               "description": spec["description"], "id": agent_id})
        _record_event(conn, agent_id, version, "updated", username)
        record = _agent_record(conn, agent_id, tenant_id, username, is_admin)
    return JSONResponse({"agent": record})


def _sync_version_refs(conn, version_id: int, spec: dict):
    for ref in spec["skill_refs"]:
        snapshot = _skill_snapshot(conn, ref["skill_id"], ref["version"])
        if snapshot is None:
            raise ValueError(f"Missing skill snapshot {ref['skill_id']}@{ref['version']}")
        conn.execute(text("""
            INSERT INTO agent_version_skills (version_id, skill_id, skill_version, snapshot_json)
            VALUES (:version, :skill, :skill_version, CAST(:snapshot AS jsonb))
        """), {"version": version_id, "skill": ref["skill_id"],
               "skill_version": ref["version"], "snapshot": json.dumps(snapshot)})
    for toolset in spec["allowed_toolsets"]:
        conn.execute(text("""
            INSERT INTO agent_version_tools (version_id, toolset_name) VALUES (:version, :tool)
        """), {"version": version_id, "tool": toolset})


async def managed_agents_test(request: Request):
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    username, _role, tenant_id, is_admin = _scope(user)
    agent_id = int(request.path_params["id"])
    engine, error = _get_engine_or_error()
    if error:
        return error
    with engine.begin() as conn:
        agent = conn.execute(text("""
            SELECT d.current_version, d.status AS agent_status,
                   v.id AS version_id, v.spec_json
            FROM agent_definitions d JOIN agent_versions v
              ON v.agent_id = d.id AND v.version = d.current_version
            WHERE d.id = :id AND d.tenant_id = :tenant
              AND (:admin OR d.owner_username = :owner) AND d.status <> 'archived'
            FOR UPDATE OF d
        """), {"id": agent_id, "tenant": tenant_id, "owner": username, "admin": is_admin}).mappings().first()
        if not agent:
            return JSONResponse({"error": "Agent not found"}, status_code=404)
        if agent["agent_status"] not in ("draft", "testing"):
            return JSONResponse({"error": "Only a draft or testing agent can be tested"}, status_code=409)
        spec = dict(agent["spec_json"] or {})
        expected_refs = {
            (ref["skill_id"], ref["version"])
            for ref in spec.get("skill_refs", [])
        }
        stored_refs = conn.execute(text("""
            SELECT skill_id, skill_version, snapshot_json
            FROM agent_version_skills WHERE version_id = :version
        """), {"version": agent["version_id"]}).mappings().all()
        actual_refs = {(row["skill_id"], row["skill_version"]) for row in stored_refs}
        if actual_refs != expected_refs or any(
            not isinstance(row["snapshot_json"], dict)
            or not row["snapshot_json"].get("instruction")
            for row in stored_refs
        ):
            return JSONResponse({"passed": False, "error": "Skill snapshots are incomplete or inconsistent"}, status_code=422)
        report = {"passed": True, "validated_tools": len(spec.get("allowed_toolsets", [])),
                  "validated_skills": len(spec.get("skill_refs", [])),
                  "note": "Configuration validation completed; this does not execute model tools."}
        conn.execute(text("""
            UPDATE agent_versions SET status = 'testing', test_passed_at = NOW(),
                test_report = CAST(:report AS jsonb) WHERE id = :version
        """), {"report": json.dumps(report), "version": agent["version_id"]})
        conn.execute(text("UPDATE agent_definitions SET status = 'testing', updated_at = NOW() WHERE id = :id"),
                     {"id": agent_id})
        _record_event(conn, agent_id, int(agent["current_version"]), "tested", username, report)
    return JSONResponse(report)


async def managed_agents_submit(request: Request):
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    username, _role, tenant_id, is_admin = _scope(user)
    agent_id = int(request.path_params["id"])
    engine, error = _get_engine_or_error()
    if error:
        return error
    with engine.begin() as conn:
        row = conn.execute(text("""
            SELECT d.current_version, v.id AS version_id, v.test_passed_at
            FROM agent_definitions d JOIN agent_versions v
              ON v.agent_id = d.id AND v.version = d.current_version
            WHERE d.id = :id AND d.tenant_id = :tenant
              AND (:admin OR d.owner_username = :owner) AND d.status <> 'archived'
            FOR UPDATE OF d
        """), {"id": agent_id, "tenant": tenant_id, "owner": username, "admin": is_admin}).mappings().first()
        if not row:
            return JSONResponse({"error": "Agent not found"}, status_code=404)
        if not row["test_passed_at"]:
            return JSONResponse({"error": "Run a successful configuration test before requesting approval"}, status_code=409)
        conn.execute(text("UPDATE agent_versions SET status = 'pending_approval' WHERE id = :id"), {"id": row["version_id"]})
        conn.execute(text("UPDATE agent_definitions SET status = 'pending_approval', updated_at = NOW() WHERE id = :id"),
                     {"id": agent_id})
        _record_event(conn, agent_id, int(row["current_version"]), "submitted", username)
    return JSONResponse({"ok": True, "status": "pending_approval"})


async def managed_agents_approve(request: Request):
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    username, role, tenant_id, _ = _scope(user)
    if role != "admin":
        return JSONResponse({"error": "Admin required"}, status_code=403)
    agent_id = int(request.path_params["id"])
    try:
        body = await request.json()
    except Exception:
        body = {}
    approve = body.get("approve", True) is True
    note = str(body.get("note", ""))[:1000]
    engine, error = _get_engine_or_error()
    if error:
        return error
    with engine.begin() as conn:
        row = conn.execute(text("""
            SELECT d.current_version, v.id AS version_id, v.status
            FROM agent_definitions d JOIN agent_versions v
              ON v.agent_id = d.id AND v.version = d.current_version
            WHERE d.id = :id AND d.tenant_id = :tenant AND d.status <> 'archived'
            FOR UPDATE OF d
        """), {"id": agent_id, "tenant": tenant_id}).mappings().first()
        if not row:
            return JSONResponse({"error": "Agent not found"}, status_code=404)
        if row["status"] != "pending_approval":
            return JSONResponse({"error": "Agent version is not pending approval"}, status_code=409)
        next_status = "approved" if approve else "rejected"
        next_agent_status = next_status if approve else "draft"
        conn.execute(text("UPDATE agent_versions SET status = :status WHERE id = :id"),
                     {"status": next_status, "id": row["version_id"]})
        conn.execute(text("UPDATE agent_definitions SET status = :status, updated_at = NOW() WHERE id = :id"),
                     {"status": next_agent_status, "id": agent_id})
        _record_event(conn, agent_id, int(row["current_version"]), next_status, username, {"note": note})
    return JSONResponse({"ok": True, "status": next_status})


async def managed_agents_publish(request: Request):
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    username, _role, tenant_id, is_admin = _scope(user)
    agent_id = int(request.path_params["id"])
    engine, error = _get_engine_or_error()
    if error:
        return error
    with engine.begin() as conn:
        row = conn.execute(text("""
            SELECT d.current_version, v.id AS version_id, v.status, v.test_passed_at
            FROM agent_definitions d JOIN agent_versions v
              ON v.agent_id = d.id AND v.version = d.current_version
            WHERE d.id = :id AND d.tenant_id = :tenant
              AND (:admin OR d.owner_username = :owner) AND d.status <> 'archived'
            FOR UPDATE OF d
        """), {"id": agent_id, "tenant": tenant_id, "owner": username, "admin": is_admin}).mappings().first()
        if not row:
            return JSONResponse({"error": "Agent not found"}, status_code=404)
        if row["status"] != "approved" or not row["test_passed_at"]:
            return JSONResponse({"error": "A tested and approved version is required before publishing"}, status_code=409)
        previous_revision = conn.execute(text("""
            SELECT COALESCE(MAX(revision), 0) FROM agent_deployments WHERE agent_id = :id
        """), {"id": agent_id}).scalar_one()
        conn.execute(text("UPDATE agent_deployments SET state = 'superseded' WHERE agent_id = :id AND state = 'active'"),
                     {"id": agent_id})
        revision = int(previous_revision) + 1
        conn.execute(text("""
            INSERT INTO agent_deployments (agent_id, version_id, revision, deployed_by)
            VALUES (:agent, :version, :revision, :actor)
        """), {"agent": agent_id, "version": row["version_id"], "revision": revision, "actor": username})
        conn.execute(text("UPDATE agent_versions SET status = 'published' WHERE id = :id"), {"id": row["version_id"]})
        conn.execute(text("""
            UPDATE agent_definitions SET status = 'published', active_version = :version,
                updated_at = NOW() WHERE id = :id
        """), {"version": row["current_version"], "id": agent_id})
        _record_event(conn, agent_id, int(row["current_version"]), "published", username, {"revision": revision})
        record = _agent_record(conn, agent_id, tenant_id, username, is_admin)
    return JSONResponse({"ok": True, "revision": revision, "agent": record})


async def managed_agents_disable(request: Request):
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    username, _role, tenant_id, is_admin = _scope(user)
    agent_id = int(request.path_params["id"])
    engine, error = _get_engine_or_error()
    if error:
        return error
    with engine.begin() as conn:
        row = conn.execute(text("""
            SELECT d.current_version FROM agent_definitions d
            WHERE d.id = :id AND d.tenant_id = :tenant
              AND (:admin OR d.owner_username = :owner) AND d.status <> 'archived'
            FOR UPDATE
        """), {"id": agent_id, "tenant": tenant_id, "owner": username, "admin": is_admin}).mappings().first()
        if not row:
            return JSONResponse({"error": "Agent not found"}, status_code=404)
        conn.execute(text("UPDATE agent_deployments SET state = 'disabled' WHERE agent_id = :id AND state = 'active'"),
                     {"id": agent_id})
        conn.execute(text("UPDATE agent_definitions SET status = 'disabled', updated_at = NOW() WHERE id = :id"),
                     {"id": agent_id})
        _record_event(conn, agent_id, int(row["current_version"]), "disabled", username)
    return JSONResponse({"ok": True, "status": "disabled"})


async def managed_agents_archive(request: Request):
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    username, _role, tenant_id, is_admin = _scope(user)
    agent_id = int(request.path_params["id"])
    engine, error = _get_engine_or_error()
    if error:
        return error
    with engine.begin() as conn:
        row = conn.execute(text("""
            SELECT current_version FROM agent_definitions
            WHERE id = :id AND tenant_id = :tenant
              AND (:admin OR owner_username = :owner) AND status <> 'archived'
            FOR UPDATE
        """), {"id": agent_id, "tenant": tenant_id, "owner": username, "admin": is_admin}).mappings().first()
        if not row:
            return JSONResponse({"error": "Agent not found"}, status_code=404)
        conn.execute(text("UPDATE agent_deployments SET state = 'disabled' WHERE agent_id = :id AND state = 'active'"),
                     {"id": agent_id})
        conn.execute(text("UPDATE agent_definitions SET status = 'archived', archived_at = NOW(), updated_at = NOW() WHERE id = :id"),
                     {"id": agent_id})
        _record_event(conn, agent_id, int(row["current_version"]), "archived", username)
    return JSONResponse({"ok": True, "status": "archived"})


async def managed_agents_rollback(request: Request):
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    username, _role, tenant_id, is_admin = _scope(user)
    agent_id = int(request.path_params["id"])
    try:
        body = await request.json()
    except Exception:
        body = {}
    if not isinstance(body, dict):
        return JSONResponse({"error": "JSON body must be an object"}, status_code=400)
    target_version = body.get("version")
    if target_version is not None and (
        not isinstance(target_version, int) or isinstance(target_version, bool)
    ):
        return JSONResponse({"error": "version must be an integer"}, status_code=400)
    engine, error = _get_engine_or_error()
    if error:
        return error
    with engine.begin() as conn:
        agent = conn.execute(text("""
            SELECT * FROM agent_definitions
            WHERE id = :id AND tenant_id = :tenant
              AND (:admin OR owner_username = :owner) AND status <> 'archived'
            FOR UPDATE
        """), {"id": agent_id, "tenant": tenant_id, "owner": username, "admin": is_admin}).mappings().first()
        if not agent:
            return JSONResponse({"error": "Agent not found"}, status_code=404)
        if target_version is None:
            previous = conn.execute(text("""
                SELECT version FROM agent_deployments d JOIN agent_versions v ON v.id = d.version_id
                WHERE d.agent_id = :agent AND d.state = 'superseded' AND d.environment = 'production'
                ORDER BY d.revision DESC LIMIT 1
            """), {"agent": agent_id}).scalar()
            if previous is None:
                return JSONResponse({"error": "No previous published deployment is available for rollback"}, status_code=409)
            target_version = previous
        if not isinstance(target_version, int):
            return JSONResponse({"error": "version must be an integer"}, status_code=400)
        version = conn.execute(text("""
            SELECT id, version, status FROM agent_versions WHERE agent_id = :agent AND version = :version
        """), {"agent": agent_id, "version": target_version}).mappings().first()
        if not version or version["status"] != "published":
            return JSONResponse({"error": "Target version has no published release"}, status_code=409)
        revision = int(conn.execute(text("SELECT COALESCE(MAX(revision), 0) + 1 FROM agent_deployments WHERE agent_id = :id"),
                                    {"id": agent_id}).scalar_one())
        conn.execute(text("UPDATE agent_deployments SET state = 'superseded' WHERE agent_id = :id AND state = 'active'"),
                     {"id": agent_id})
        conn.execute(text("""
            INSERT INTO agent_deployments (agent_id, version_id, revision, deployed_by)
            VALUES (:agent, :version_id, :revision, :actor)
        """), {"agent": agent_id, "version_id": version["id"], "revision": revision, "actor": username})
        conn.execute(text("""
            UPDATE agent_definitions SET active_version = :version, status = 'published', updated_at = NOW()
            WHERE id = :id
        """), {"version": target_version, "id": agent_id})
        _record_event(conn, agent_id, target_version, "rolled_back", username, {"revision": revision})
    return JSONResponse({"ok": True, "version": target_version, "revision": revision})


async def managed_agents_events(request: Request):
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    username, _role, tenant_id, is_admin = _scope(user)
    agent_id = int(request.path_params["id"])
    engine, error = _get_engine_or_error()
    if error:
        return error
    with engine.connect() as conn:
        exists = conn.execute(text("""
            SELECT 1 FROM agent_definitions WHERE id = :id AND tenant_id = :tenant
              AND (:admin OR owner_username = :owner)
        """), {"id": agent_id, "tenant": tenant_id, "owner": username, "admin": is_admin}).first()
        if not exists:
            return JSONResponse({"error": "Agent not found"}, status_code=404)
        rows = conn.execute(text("""
            SELECT version, event_type, actor_username, details, created_at
            FROM agent_lifecycle_events WHERE agent_id = :id ORDER BY created_at DESC LIMIT 200
        """), {"id": agent_id}).mappings().all()
    return JSONResponse({"events": [_json_value(dict(row)) for row in rows]})


def get_managed_agent_routes() -> list[Route]:
    return [
        Route("/api/managed-agents", managed_agents_list, methods=["GET"]),
        Route("/api/managed-agents", managed_agents_create, methods=["POST"]),
        Route("/api/managed-agents/{id:int}", managed_agents_detail, methods=["GET"]),
        Route("/api/managed-agents/{id:int}", managed_agents_update, methods=["PUT"]),
        Route("/api/managed-agents/{id:int}/test", managed_agents_test, methods=["POST"]),
        Route("/api/managed-agents/{id:int}/submit", managed_agents_submit, methods=["POST"]),
        Route("/api/managed-agents/{id:int}/approve", managed_agents_approve, methods=["POST"]),
        Route("/api/managed-agents/{id:int}/publish", managed_agents_publish, methods=["POST"]),
        Route("/api/managed-agents/{id:int}/disable", managed_agents_disable, methods=["POST"]),
        Route("/api/managed-agents/{id:int}/archive", managed_agents_archive, methods=["POST"]),
        Route("/api/managed-agents/{id:int}/rollback", managed_agents_rollback, methods=["POST"]),
        Route("/api/managed-agents/{id:int}/events", managed_agents_events, methods=["GET"]),
    ]
