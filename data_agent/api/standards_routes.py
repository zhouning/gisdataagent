"""Standards Platform REST routes (P0). Auth via _get_user_from_request +
_set_user_context, role gates inline."""
from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path

from sqlalchemy import text
from starlette.requests import Request
from starlette.responses import JSONResponse, PlainTextResponse, Response
from starlette.routing import Route

from ..db_engine import get_engine
from ..observability import get_logger
from ..standards_platform import repository, outbox
from ..standards_platform import outbox_admin as _outbox_admin
from ..standards_platform.ingestion.uploader import ingest_upload
from ..standards_platform.ingestion.web_fetcher import fetch as web_fetch, save_manual, NotAllowed
from ..standards_platform.analysis.deduper import find_similar_clauses
from . import helpers as _helpers
from .helpers import _set_user_context, _require_admin

logger = get_logger("api.standards_routes")

_EDITOR_ROLES = {"admin", "analyst", "standard_editor"}
_REVIEWER_ROLES = {"admin", "analyst", "standard_editor", "standard_reviewer"}

from ..standards_platform.drafting import editor_session as _editor
from ..standards_platform.review import (
    round_repo as _round_repo,
    comment_repo as _comment_repo,
    gating as _gating,
)
from ..standards_platform.publishing import (
    publish_repo as _publish_repo,
    guards as _publish_guards,
)
from ..standards_platform.derivation import (
    runner as _derive_runner,
    link_repo as _link_repo,
)
from ..standards_platform.derivation.data_model_xmi_exporter import (
    export_pdm_to_ea_xmi,
)


def _require_editor_or_403(role: str | None) -> JSONResponse | None:
    if role not in _EDITOR_ROLES:
        return JSONResponse({"error": "Forbidden — editor role required"},
                            status_code=403)
    return None


def _require_admin_or_403(role: str | None) -> JSONResponse | None:
    if role != "admin":
        return JSONResponse({"error": "Forbidden — admin only"}, status_code=403)
    return None


def _block_if_reviewing(version_id: str) -> JSONResponse | None:
    """Wave 4 alias retained for compatibility — delegates to Wave 5's
    block_if_not_drafting (covers review/approved/released/retired)."""
    return _publish_guards.block_if_not_drafting(version_id)


def _auth_or_401(request: Request):
    u = _helpers._get_user_from_request(request)
    if not u:
        return None, None, JSONResponse({"error": "Unauthorized"}, status_code=401)
    username, role = _set_user_context(u)
    return username, role, None


def _parse_int_param(request: Request, name: str, default: int) -> int:
    raw = request.query_params.get(name)
    if raw is None:
        return default
    try:
        return int(raw)
    except ValueError as e:
        raise ValueError(f"{name} must be an integer") from e


async def list_documents(request: Request):
    username, role, err = _auth_or_401(request)
    if err: return err
    owner = request.query_params.get("owner")
    status = request.query_params.get("status")
    rows = repository.list_documents(owner_user_id=owner, status=status)
    return JSONResponse({"documents": [
        {"id": str(r["id"]), "doc_code": r["doc_code"], "title": r["title"],
         "source_type": r["source_type"], "status": r["status"],
         "owner_user_id": r["owner_user_id"]} for r in rows]})


async def upload_document(request: Request):
    username, role, err = _auth_or_401(request)
    if err: return err
    if role not in _EDITOR_ROLES:
        return JSONResponse({"error": "Forbidden"}, status_code=403)
    form = await request.form()
    upload = form.get("file")
    if upload is None:
        return JSONResponse({"error": "missing file"}, status_code=400)
    src_type = form.get("source_type", "enterprise")
    src_url = form.get("source_url") or None
    suffix = Path(upload.filename or "").suffix
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        shutil.copyfileobj(upload.file, tmp)
        tmp_path = Path(tmp.name)
    try:
        doc_id, ver_id = ingest_upload(tmp_path, original_name=upload.filename,
                                        source_type=src_type, source_url=src_url)
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    return JSONResponse({"document_id": doc_id, "version_id": ver_id})


async def get_document(request: Request):
    username, role, err = _auth_or_401(request)
    if err: return err
    doc_id = request.path_params["doc_id"]
    doc = repository.get_document(doc_id)
    if not doc:
        return JSONResponse({"error": "not found"}, status_code=404)
    return JSONResponse({"document": {k: (str(v) if hasattr(v, "hex") else v)
                                       for k, v in doc.items()}})


async def list_versions(request: Request):
    username, role, err = _auth_or_401(request)
    if err: return err
    eng = get_engine()
    with eng.connect() as conn:
        rows = conn.execute(text(
            "SELECT id, version_label, status, released_at FROM std_document_version "
            "WHERE document_id = :d ORDER BY semver_major DESC, semver_minor DESC, semver_patch DESC"
        ), {"d": request.path_params["doc_id"]}).mappings().all()
    return JSONResponse({"versions": [
        {"id": str(r["id"]), "version_label": r["version_label"],
         "status": r["status"],
         "released_at": r["released_at"].isoformat() if r["released_at"] else None}
        for r in rows]})


def _list_under_version(table: str, request: Request):
    """Generic helper for clauses / data-elements / terms / value-domains."""
    eng = get_engine()
    with eng.connect() as conn:
        rows = conn.execute(text(
            f"SELECT * FROM {table} WHERE document_version_id = :v ORDER BY 1"
        ), {"v": request.path_params["version_id"]}).mappings().all()
    return [{k: _json_safe(v) for k, v in dict(r).items() if k != "embedding"}
            for r in rows]


def _json_safe(v):
    if v is None:
        return None
    if hasattr(v, "hex"):
        return str(v)
    if hasattr(v, "isoformat"):
        return v.isoformat()
    return v


async def list_clauses(request: Request):
    username, role, err = _auth_or_401(request)
    if err: return err
    return JSONResponse({"clauses": _list_under_version("std_clause", request)})


async def list_data_elements(request: Request):
    username, role, err = _auth_or_401(request)
    if err: return err
    return JSONResponse({"data_elements":
        _list_under_version("std_data_element", request)})


async def list_clause_elements(request: Request):
    """List std_data_element rows whose defined_by_clause_id matches."""
    username, role, err = _auth_or_401(request)
    if err: return err
    cid = request.path_params["clause_id"]
    eng = get_engine()
    with eng.connect() as conn:
        rows = conn.execute(text(
            "SELECT * FROM std_data_element WHERE defined_by_clause_id = :c "
            "ORDER BY code"
        ), {"c": cid}).mappings().all()
    return JSONResponse({"data_elements": [
        {k: _json_safe(v) for k, v in dict(r).items() if k != "embedding"}
        for r in rows]})


async def list_terms(request: Request):
    username, role, err = _auth_or_401(request)
    if err: return err
    return JSONResponse({"terms": _list_under_version("std_term", request)})


async def list_value_domains(request: Request):
    username, role, err = _auth_or_401(request)
    if err: return err
    return JSONResponse({"value_domains":
        _list_under_version("std_value_domain", request)})


async def list_similar(request: Request):
    username, role, err = _auth_or_401(request)
    if err: return err
    hits = find_similar_clauses(version_id=request.path_params["version_id"],
                                top_k=20, min_similarity=0.7)
    return JSONResponse({"hits": [{**h, "source_clause_id": str(h["source_clause_id"]),
                                    "target_clause_id": str(h["target_clause_id"]),
                                    "document_version_id": str(h["document_version_id"]),
                                    "similarity": float(h["similarity"])} for h in hits]})


async def web_fetch_route(request: Request):
    username, role, err = _auth_or_401(request)
    if err: return err
    if role not in _EDITOR_ROLES:
        return JSONResponse({"error": "Forbidden"}, status_code=403)
    body = await request.json()
    try:
        out = web_fetch(body["url"])
    except NotAllowed as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    return JSONResponse({"status": out["status"], "truncated": out["truncated"],
                          "size": len(out["body"])})


async def web_manual_route(request: Request):
    username, role, err = _auth_or_401(request)
    if err: return err
    if role not in _EDITOR_ROLES:
        return JSONResponse({"error": "Forbidden"}, status_code=403)
    body = await request.json()
    snap = save_manual(body["url"], pasted_text=body["text"], user_id=username)
    return JSONResponse({"snapshot_id": snap})


async def outbox_status(request: Request):
    user, username, role, err = _require_admin(request)
    if err: return err
    return JSONResponse({"counts": _outbox_admin.get_counts()})


async def list_outbox_events(request: Request):
    user, username, role, err = _require_admin(request)
    if err: return err
    try:
        limit = _parse_int_param(request, "limit", 50)
        offset = _parse_int_param(request, "offset", 0)
        events = _outbox_admin.list_events(
            status=request.query_params.get("status"),
            event_type=request.query_params.get("event_type"),
            limit=limit,
            offset=offset,
        )
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=400)
    return JSONResponse({"events": events, "counts": _outbox_admin.get_counts()})


async def retry_outbox_event(request: Request):
    user, username, role, err = _require_admin(request)
    if err: return err
    result = _outbox_admin.retry_event(
        request.path_params["event_id"],
        by_user=username,
    )
    return JSONResponse({"result": result})


async def retry_outbox_events(request: Request):
    user, username, role, err = _require_admin(request)
    if err: return err
    try:
        body = await request.json()
    except json.JSONDecodeError:
        return JSONResponse({"error": "invalid JSON body"}, status_code=400)
    event_ids = body.get("event_ids") if isinstance(body, dict) else None
    if not isinstance(event_ids, list) or not event_ids:
        return JSONResponse(
            {"error": "event_ids must be a non-empty list"},
            status_code=400,
        )
    if any(not isinstance(event_id, str) or not event_id
           for event_id in event_ids):
        return JSONResponse(
            {"error": "event_ids must contain non-empty strings"},
            status_code=400,
        )
    return JSONResponse(
        _outbox_admin.retry_events(event_ids, by_user=username)
    )


async def lock_clause(request: Request):
    username, role, err = _auth_or_401(request)
    if err: return err
    forbid = _require_editor_or_403(role)
    if forbid: return forbid
    cid = request.path_params["clause_id"]
    # Wave 4: block drafting writes when version is in review
    eng = get_engine()
    with eng.connect() as conn:
        ver = conn.execute(text(
            "SELECT document_version_id FROM std_clause WHERE id=:i"
        ), {"i": cid}).first()
    if ver:
        forbid = _block_if_reviewing(str(ver[0]))
        if forbid: return forbid
    try:
        out = _editor.acquire_lock(cid, username)
    except _editor.LockError as e:
        return JSONResponse({"error": "Locked",
                             "holder": e.holder,
                             "expires_at": e.expires_at.isoformat()
                                if e.expires_at else None},
                            status_code=423)
    out["lock_expires_at"] = out["lock_expires_at"].isoformat()
    return JSONResponse(out)


async def heartbeat_clause(request: Request):
    username, role, err = _auth_or_401(request)
    if err: return err
    forbid = _require_editor_or_403(role)
    if forbid: return forbid
    cid = request.path_params["clause_id"]
    try:
        out = _editor.heartbeat(cid, username)
    except _editor.LockError:
        return JSONResponse({"error": "Lock lost"}, status_code=410)
    out["lock_expires_at"] = out["lock_expires_at"].isoformat()
    return JSONResponse(out)


async def release_clause_lock(request: Request):
    username, role, err = _auth_or_401(request)
    if err: return err
    forbid = _require_editor_or_403(role)
    if forbid: return forbid
    cid = request.path_params["clause_id"]
    _editor.release_lock(cid, username)
    return JSONResponse({"ok": True})


async def save_clause_route(request: Request):
    username, role, err = _auth_or_401(request)
    if err: return err
    forbid = _require_editor_or_403(role)
    if forbid: return forbid
    cid = request.path_params["clause_id"]
    # Wave 4: block drafting writes when version is in review
    eng = get_engine()
    with eng.connect() as conn:
        ver = conn.execute(text(
            "SELECT document_version_id FROM std_clause WHERE id=:i"
        ), {"i": cid}).first()
    if ver:
        forbid = _block_if_reviewing(str(ver[0]))
        if forbid: return forbid
    if_match = request.headers.get("if-match", "")
    body = await request.json()
    try:
        out = _editor.save_clause(cid, username,
                                  if_match_checksum=if_match,
                                  body_md=body.get("body_md", ""),
                                  body_html=body.get("body_html"),
                                  data_elements=body.get("data_elements"))
    except _editor.ConflictError as e:
        return JSONResponse({"error": "Conflict",
                             "server_checksum": e.server_checksum,
                             "server_body_md": e.server_body_md},
                            status_code=409)
    except _editor.LockError:
        return JSONResponse({"error": "Lock lost"}, status_code=410)
    out["updated_at"] = out["updated_at"].isoformat()
    return JSONResponse(out)


async def break_clause_lock(request: Request):
    username, role, err = _auth_or_401(request)
    if err: return err
    if role != "admin":
        return JSONResponse({"error": "Forbidden — admin only"},
                            status_code=403)
    cid = request.path_params["clause_id"]
    # Wave 5: even admin cannot break_lock on released versions.
    eng = get_engine()
    with eng.connect() as conn:
        ver = conn.execute(text(
            "SELECT document_version_id FROM std_clause WHERE id=:i"
        ), {"i": cid}).first()
    if ver:
        forbid = _block_if_reviewing(str(ver[0]))
        if forbid: return forbid
    out = _editor.break_lock(cid, username)
    return JSONResponse(out)


async def citation_search(request: Request):
    username, role, err = _auth_or_401(request)
    if err: return err
    forbid = _require_editor_or_403(role)
    if forbid: return forbid
    body = await request.json()
    clause_id = body.get("clause_id")
    query = (body.get("query") or "").strip()
    if not clause_id or not query:
        return JSONResponse({"error": "clause_id and query required"},
                            status_code=400)
    sources_list = body.get("sources")
    sources = set(sources_list) if sources_list else None
    from ..standards_platform.drafting.citation_assistant import (
        search_citations,
    )
    cands = search_citations(clause_id=clause_id, query=query,
                             sources=sources, top_k=20)
    return JSONResponse({"candidates": cands})


async def citation_insert(request: Request):
    username, role, err = _auth_or_401(request)
    if err: return err
    forbid = _require_editor_or_403(role)
    if forbid: return forbid
    body = await request.json()
    clause_id = body.get("clause_id")
    cand = body.get("candidate") or {}
    if not clause_id or not cand:
        return JSONResponse({"error": "clause_id and candidate required"},
                            status_code=400)

    # Wave 5: block when version not in 'draft'
    eng = get_engine()
    with eng.connect() as conn:
        ver = conn.execute(text(
            "SELECT document_version_id FROM std_clause WHERE id=:i"
        ), {"i": clause_id}).first()
    if ver:
        forbid = _block_if_reviewing(str(ver[0]))
        if forbid: return forbid

    # Fix #4: validate citation_text early
    citation_text = (cand.get("snippet") or "").strip()[:500]
    if not citation_text:
        return JSONResponse({"error": "citation_text is required"},
                            status_code=400)

    # Fix #3: dispatch target_kind to the correct FK column
    kind = cand.get("kind", "")
    target_clause_id = None
    target_data_element_id = None
    target_term_id = None
    target_document_id = None
    target_url = None
    snapshot_id = None

    if kind == "std_clause":
        target_kind = "std_clause"
        target_clause_id = cand.get("target_id")
    elif kind == "std_data_element":
        target_kind = "std_data_element"
        target_data_element_id = cand.get("target_id")
    elif kind == "std_term":
        target_kind = "std_term"
        target_term_id = cand.get("target_id")
    elif kind == "std_document":
        target_kind = "std_document"
        target_document_id = cand.get("target_id")
    elif kind == "kb_chunk":
        # KB chunk has no FK target — record as internet_search with the
        # source URL if the candidate carried one.
        target_kind = "internet_search"
        target_url = cand.get("target_url")
    elif kind == "web_snapshot":
        target_kind = "web_snapshot"
        snapshot_id = cand.get("target_id")
        target_url = cand.get("target_url")
    elif kind == "external_url":
        target_kind = "external_url"
        target_url = cand.get("target_url")
    else:
        return JSONResponse(
            {"error": f"unsupported candidate kind: {kind}"},
            status_code=400)

    confidence = cand.get("extra", {}).get("confidence")
    eng = get_engine()
    import uuid as _u
    ref_id = str(_u.uuid4())
    # Fix #5: inserted_by/inserted_at instead of verified_by/verified_at;
    # verification_status defaults to 'pending' via DB DEFAULT.
    with eng.begin() as conn:
        conn.execute(text("""
            INSERT INTO std_reference (
                id, source_clause_id, target_kind,
                target_clause_id, target_data_element_id, target_term_id,
                target_document_id, target_url, snapshot_id,
                citation_text, confidence,
                inserted_by, inserted_at)
            VALUES (:i, :sc, :tk,
                    :tc, :tde, :tt,
                    :td, :tu, :sn,
                    :ct, :cf,
                    :u, now())
        """), {
            "i": ref_id, "sc": clause_id, "tk": target_kind,
            "tc": target_clause_id, "tde": target_data_element_id,
            "tt": target_term_id, "td": target_document_id,
            "tu": target_url, "sn": snapshot_id,
            "ct": citation_text, "cf": confidence,
            "u": username,
        })
    return JSONResponse({"ref_id": ref_id, "citation_text": citation_text})


# ---------------------------------------------------------------------------
# Wave 4: Review stage handlers
# ---------------------------------------------------------------------------


def _round_or_404(round_id: str):
    r = _round_repo.get_round(round_id)
    if r is None:
        return None, JSONResponse({"error": "round not found"}, status_code=404)
    return r, None


def _require_round_reviewer_or_403(round_dict, username, role):
    """Allow if user is admin OR is the round's reviewer."""
    if role == "admin":
        return None
    if round_dict["reviewer_user_id"] == username:
        return None
    return JSONResponse({"error": "not the assigned reviewer"},
                        status_code=403)


async def review_round_start(request: Request):
    username, role, err = _auth_or_401(request)
    if err: return err
    forbid = _require_admin_or_403(role)
    if forbid: return forbid
    body = await request.json()
    version_id = body.get("document_version_id")
    reviewer = body.get("reviewer_user_id")
    if not version_id or not reviewer:
        return JSONResponse(
            {"error": "document_version_id and reviewer_user_id required"},
            status_code=400)
    eng = get_engine()
    with eng.connect() as conn:
        v = conn.execute(text(
            "SELECT status FROM std_document_version WHERE id=:i"
        ), {"i": version_id}).first()
    if v is None:
        return JSONResponse({"error": "version not found"}, status_code=404)
    existing = _round_repo.get_open_round_for_version(version_id)
    if existing is not None:
        return JSONResponse({"error": "round already open for this version",
                              "round_id": str(existing["id"])}, status_code=409)
    if v[0] != "draft":
        return JSONResponse({"error": "version status must be draft",
                              "current_status": v[0]}, status_code=409)
    rid = _round_repo.create_round(
        document_version_id=version_id,
        reviewer_user_id=reviewer,
        initiated_by=username)
    return JSONResponse({"round_id": rid}, status_code=201)


async def review_round_list(request: Request):
    username, role, err = _auth_or_401(request)
    if err: return err
    p = request.query_params
    rounds = _round_repo.list_rounds(
        version_id=p.get("version_id"),
        reviewer_user_id=p.get("reviewer_user_id"),
        status=p.get("status"))
    return JSONResponse({"rounds": [
        {"id": str(r["id"]),
         "document_version_id": str(r["document_version_id"]),
         "reviewer_user_id": r["reviewer_user_id"],
         "initiated_by": r["initiated_by"],
         "initiated_at": r["initiated_at"].isoformat() if r["initiated_at"] else None,
         "closed_at": r["closed_at"].isoformat() if r["closed_at"] else None,
         "status": r["status"],
         "outcome": r["outcome"]} for r in rounds]})


async def review_round_close_precheck(request: Request):
    username, role, err = _auth_or_401(request)
    if err: return err
    rid = request.path_params["round_id"]
    r, err404 = _round_or_404(rid)
    if err404: return err404
    forbid = _require_round_reviewer_or_403(r, username, role)
    if forbid: return forbid
    g = _gating.check_close_gating(round_id=rid,
                                   version_id=str(r["document_version_id"]))
    return JSONResponse(g)


async def review_round_close(request: Request):
    username, role, err = _auth_or_401(request)
    if err: return err
    rid = request.path_params["round_id"]
    r, err404 = _round_or_404(rid)
    if err404: return err404
    forbid = _require_round_reviewer_or_403(r, username, role)
    if forbid: return forbid
    body = await request.json()
    outcome = body.get("outcome")
    if outcome not in ("approved", "rejected"):
        return JSONResponse(
            {"error": "outcome must be 'approved' or 'rejected'"},
            status_code=400)
    if r["status"] == "closed":
        return JSONResponse({"error": "round already closed"}, status_code=409)
    if outcome == "approved":
        g = _gating.check_close_gating(round_id=rid,
                                       version_id=str(r["document_version_id"]))
        if g["blocking"]:
            return JSONResponse({"error": "cannot close: gating not satisfied",
                                  "pending_refs": g["pending_refs"],
                                  "open_comments": g["open_comments"]},
                                  status_code=409)
    try:
        out = _round_repo.close_round(round_id=rid, outcome=outcome)
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=409)
    return JSONResponse(out)


async def review_comment_list(request: Request):
    username, role, err = _auth_or_401(request)
    if err: return err
    rid = request.path_params["round_id"]
    r, err404 = _round_or_404(rid)
    if err404: return err404
    clause_id = request.query_params.get("clause_id")
    comments = _comment_repo.list_comments(round_id=rid, clause_id=clause_id)
    return JSONResponse({"comments": [
        {"id": str(c["id"]), "round_id": str(c["round_id"]),
         "clause_id": str(c["clause_id"]),
         "parent_comment_id": str(c["parent_comment_id"]) if c["parent_comment_id"] else None,
         "author_user_id": c["author_user_id"], "body_md": c["body_md"],
         "resolution": c["resolution"],
         "created_at": c["created_at"].isoformat() if c["created_at"] else None,
         "resolved_at": c["resolved_at"].isoformat() if c["resolved_at"] else None,
         "resolved_by": c["resolved_by"]} for c in comments]})


async def review_comment_post(request: Request):
    username, role, err = _auth_or_401(request)
    if err: return err
    rid = request.path_params["round_id"]
    r, err404 = _round_or_404(rid)
    if err404: return err404
    forbid = _require_round_reviewer_or_403(r, username, role)
    if forbid: return forbid
    if r["status"] == "closed":
        return JSONResponse({"error": "round closed"}, status_code=409)
    body = await request.json()
    clause_id = body.get("clause_id")
    body_md = (body.get("body_md") or "").strip()
    parent = body.get("parent_comment_id")
    if not clause_id:
        return JSONResponse({"error": "clause_id required"}, status_code=400)
    if not body_md:
        return JSONResponse({"error": "body_md is required"}, status_code=400)
    if parent:
        p = _comment_repo.get_comment(parent)
        if p is None or str(p["round_id"]) != rid:
            return JSONResponse({"error": "parent must belong to same round"},
                                status_code=400)
    cid = _comment_repo.create_comment(
        round_id=rid, clause_id=clause_id,
        author_user_id=username, body_md=body_md,
        parent_comment_id=parent)
    return JSONResponse({"comment_id": cid}, status_code=201)


async def review_comment_resolve(request: Request):
    username, role, err = _auth_or_401(request)
    if err: return err
    comm_id = request.path_params["comment_id"]
    c = _comment_repo.get_comment(comm_id)
    if c is None:
        return JSONResponse({"error": "comment not found"}, status_code=404)
    r, err404 = _round_or_404(str(c["round_id"]))
    if err404: return err404
    forbid = _require_round_reviewer_or_403(r, username, role)
    if forbid: return forbid
    if r["status"] == "closed":
        return JSONResponse({"error": "round closed"}, status_code=409)
    body = await request.json()
    resolution = body.get("resolution")
    if resolution not in ("accepted", "rejected", "duplicate"):
        return JSONResponse(
            {"error": "resolution must be accepted/rejected/duplicate"},
            status_code=400)
    _comment_repo.resolve_comment(
        comment_id=comm_id, resolution=resolution,
        resolver_user_id=username)
    return JSONResponse({"comment_id": comm_id, "resolution": resolution})


async def review_reference_patch_status(request: Request):
    username, role, err = _auth_or_401(request)
    if err: return err
    ref_id = request.path_params["ref_id"]
    body = await request.json()
    new_status = body.get("verification_status")
    rid = body.get("round_id")
    if new_status not in ("approved", "rejected"):
        return JSONResponse(
            {"error": "verification_status must be approved or rejected"},
            status_code=400)
    if not rid:
        return JSONResponse({"error": "round_id required"}, status_code=400)
    r, err404 = _round_or_404(rid)
    if err404: return err404
    forbid = _require_round_reviewer_or_403(r, username, role)
    if forbid: return forbid
    if r["status"] == "closed":
        return JSONResponse({"error": "round closed"}, status_code=409)
    eng = get_engine()
    with eng.connect() as conn:
        ref_row = conn.execute(text(
            "SELECT r.id, c.document_version_id "
            "FROM std_reference r "
            "JOIN std_clause c ON c.id = r.source_clause_id "
            "WHERE r.id=:i"
        ), {"i": ref_id}).first()
    if ref_row is None:
        return JSONResponse({"error": "reference not found"}, status_code=404)
    if str(ref_row[1]) != str(r["document_version_id"]):
        return JSONResponse({"error": "reference not in round"}, status_code=404)
    with eng.begin() as conn:
        conn.execute(text("""
            UPDATE std_reference
               SET verification_status=:s,
                   verified_by=:u, verified_at=now()
             WHERE id=:i
        """), {"s": new_status, "u": username, "i": ref_id})
        row = conn.execute(text(
            "SELECT verification_status, verified_by, verified_at "
            "FROM std_reference WHERE id=:i"
        ), {"i": ref_id}).first()
    return JSONResponse({"ref_id": ref_id,
                         "verification_status": row[0],
                         "verified_by": row[1],
                         "verified_at": row[2].isoformat() if row[2] else None})


async def list_clause_references(request: Request):
    """GET /api/std/clauses/{clause_id}/references — list refs sourced from clause.

    Used by Wave 4 ReviewSubTab to render ReferenceAuditCard entries.
    """
    username, role, err = _auth_or_401(request)
    if err: return err
    clause_id = request.path_params["clause_id"]
    eng = get_engine()
    with eng.connect() as conn:
        rows = conn.execute(text(
            "SELECT id, target_kind, citation_text, verification_status, "
            "verified_by, verified_at "
            "FROM std_reference WHERE source_clause_id=:c "
            "ORDER BY created_at ASC"
        ), {"c": clause_id}).mappings().all()
    return JSONResponse({"references": [
        {"id": str(r["id"]),
         "target_kind": r["target_kind"],
         "citation_text": r["citation_text"],
         "verification_status": r["verification_status"],
         "verified_by": r["verified_by"],
         "verified_at": r["verified_at"].isoformat() if r["verified_at"] else None}
        for r in rows]})


# ---------------------------------------------------------------------------
# Wave 5: Publishing handlers
# ---------------------------------------------------------------------------


async def publish_version_handler(request: Request):
    username, role, err = _auth_or_401(request)
    if err: return err
    forbid = _require_admin_or_403(role)
    if forbid: return forbid
    version_id = request.path_params["version_id"]
    try:
        out = _publish_repo.publish_version(
            version_id=version_id, by_user=username
        )
    except LookupError:
        return JSONResponse({"error": "version not found"}, status_code=404)
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=409)
    return JSONResponse(out, status_code=201)


async def publish_fork_handler(request: Request):
    username, role, err = _auth_or_401(request)
    if err: return err
    forbid = _require_admin_or_403(role)
    if forbid: return forbid
    body = await request.json()
    src = body.get("source_version_id")
    label = body.get("new_label")
    if not src or not label:
        return JSONResponse(
            {"error": "source_version_id and new_label required"},
            status_code=400,
        )
    try:
        new_vid = _publish_repo.fork_version(
            source_version_id=src, new_label=label, by_user=username,
        )
    except LookupError:
        return JSONResponse({"error": "source version not found"}, status_code=404)
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=409)
    return JSONResponse(
        {"new_version_id": new_vid,
         "source_version_id": src,
         "status": "draft"},
        status_code=201,
    )


async def publish_list_versions_handler(request: Request):
    username, role, err = _auth_or_401(request)
    if err: return err
    doc_id = request.query_params.get("document_id")
    rows = _publish_repo.list_published_versions(document_id=doc_id)
    return JSONResponse({"versions": [
        {"id": str(r["id"]),
         "document_id": str(r["document_id"]),
         "version_label": r["version_label"],
         "released_at": r["released_at"].isoformat() if r.get("released_at") else None,
         "released_by": r.get("released_by"),
         "supersedes_version_id": str(r["supersedes_version_id"])
            if r.get("supersedes_version_id") else None}
        for r in rows
    ]})


async def publish_timeline_handler(request: Request):
    username, role, err = _auth_or_401(request)
    if err: return err
    version_id = request.path_params["version_id"]
    rows = _publish_repo.get_publish_timeline(version_id=version_id)
    return JSONResponse({"events": [
        {"id": str(r["id"]),
         "event_type": r["event_type"],
         "actor_user_id": r["actor_user_id"],
         "occurred_at": r["occurred_at"].isoformat() if r["occurred_at"] else None,
         "notes": r.get("notes")}
        for r in rows
    ]})


async def get_version_handler(request: Request):
    """GET /api/std/versions/{version_id} — return version metadata.

    Wave 5 UX hotfix: PublishSubTab needs the current status to decide
    whether the version is publishable (approved) or forkable (released).
    """
    username, role, err = _auth_or_401(request)
    if err: return err
    version_id = request.path_params["version_id"]
    eng = get_engine()
    with eng.connect() as conn:
        row = conn.execute(text(
            "SELECT id, document_id, version_label, status, "
            "       semver_major, semver_minor, semver_patch, "
            "       released_at, supersedes_version_id, "
            "       created_at, updated_at, created_by, updated_by "
            "FROM std_document_version WHERE id=:i"
        ), {"i": version_id}).mappings().first()
    if row is None:
        return JSONResponse({"error": "version not found"}, status_code=404)
    return JSONResponse({
        "id": str(row["id"]),
        "document_id": str(row["document_id"]),
        "version_label": row["version_label"],
        "status": row["status"],
        "semver_major": row["semver_major"],
        "semver_minor": row["semver_minor"],
        "semver_patch": row["semver_patch"],
        "released_at": row["released_at"].isoformat() if row["released_at"] else None,
        "supersedes_version_id": str(row["supersedes_version_id"])
            if row["supersedes_version_id"] else None,
        "created_at": row["created_at"].isoformat() if row["created_at"] else None,
        "updated_at": row["updated_at"].isoformat() if row["updated_at"] else None,
        "created_by": row["created_by"],
        "updated_by": row["updated_by"],
    })


# ---------------------------------------------------------------------------
# Wave 5: Derivation handlers
# ---------------------------------------------------------------------------


async def derive_strategies_handler(request: Request):
    username, role, err = _auth_or_401(request)
    if err: return err
    return JSONResponse({"strategies": _derive_runner.get_strategy_status()})


async def derive_links_handler(request: Request):
    username, role, err = _auth_or_401(request)
    if err: return err
    p = request.query_params
    vid = p.get("version_id")
    if not vid:
        return JSONResponse({"error": "version_id query param required"},
                            status_code=400)
    rows = _link_repo.list_links_by_version(
        version_id=vid,
        derivation_strategy=p.get("strategy"),
        status=p.get("status"),
    )
    return JSONResponse({"links": [
        {"id": str(r["id"]),
         "source_kind": r["source_kind"],
         "source_id": str(r["source_id"]),
         "source_version_id": str(r["source_version_id"]),
         "target_kind": r["target_kind"],
         "target_table": r["target_table"],
         "target_id": r["target_id"],
         "derivation_strategy": r["derivation_strategy"],
         "status": r["status"],
         "stale_reason": r.get("stale_reason"),
         "generated_at": r["generated_at"].isoformat() if r.get("generated_at") else None}
        for r in rows
    ]})


async def derive_rerun_handler(request: Request):
    username, role, err = _auth_or_401(request)
    if err: return err
    forbid = _require_admin_or_403(role)
    if forbid: return forbid
    vid = request.path_params["version_id"]
    eng = get_engine()
    with eng.connect() as c:
        row = c.execute(text(
            "SELECT status FROM std_document_version WHERE id=:i"
        ), {"i": vid}).first()
    if row is None:
        return JSONResponse({"error": "version not found"}, status_code=404)
    if row[0] != "released":
        return JSONResponse(
            {"error": "version must be released to re-derive",
             "current_status": row[0]},
            status_code=409,
        )
    body = await request.json() if (await request.body()) else {}
    strategies = body.get("strategies")
    results = _derive_runner.dispatch(
        version_id=vid, by_user=username, strategies=strategies,
    )
    return JSONResponse({"results": results})


async def derive_status_handler(request: Request):
    username, role, err = _auth_or_401(request)
    if err: return err
    vid = request.path_params["version_id"]
    eng = get_engine()
    with eng.connect() as c:
        rows = c.execute(text(
            "SELECT derivation_strategy, status, count(*) "
            "FROM std_derived_link WHERE source_version_id=:v "
            "GROUP BY derivation_strategy, status"
        ), {"v": vid}).fetchall()
    by_strategy: dict[str, dict[str, int]] = {}
    for strategy, status, n in rows:
        by_strategy.setdefault(strategy, {"active": 0, "stale": 0,
                                          "failed": 0, "pending": 0,
                                          "overridden": 0, "superseded": 0})
        by_strategy[strategy][status] = n
    return JSONResponse({"strategies": by_strategy})


async def derive_rollback_handler(request: Request):
    """POST /api/std/derive/rollback/{version_id} — flip every active link
    from this version to 'superseded' and stale every downstream row that
    carries derived_status. Manual rows untouched. Admin only."""
    username, role, err = _auth_or_401(request)
    if err: return err
    forbid = _require_admin_or_403(role)
    if forbid: return forbid
    vid = request.path_params["version_id"]
    eng = get_engine()
    with eng.connect() as c:
        row = c.execute(text(
            "SELECT id FROM std_document_version WHERE id=:i"
        ), {"i": vid}).first()
    if row is None:
        return JSONResponse({"error": "version not found"}, status_code=404)
    body = await request.json() if (await request.body()) else {}
    reason = body.get("reason") or f"manual rollback by {username}"
    summary = _link_repo.rollback_version(
        version_id=vid, by_user=username, reason=reason,
    )
    return JSONResponse({"version_id": vid, "by_strategy": summary})


async def derive_impact_handler(request: Request):
    """GET /api/std/impact/{kind}/{source_id}?include_stale=0 — return all
    derivations descending from the given source. kind is one of:
    clause | data_element | term | value_domain."""
    username, role, err = _auth_or_401(request)
    if err: return err
    kind = request.path_params["kind"]
    source_id = request.path_params["source_id"]
    if kind not in ("clause", "data_element", "term", "value_domain"):
        return JSONResponse(
            {"error": "kind must be clause | data_element | term | value_domain"},
            status_code=400,
        )
    include_stale = request.query_params.get("include_stale", "0") == "1"
    rows = _link_repo.impact_graph(
        source_kind=kind, source_id=source_id,
        include_stale=include_stale,
    )
    return JSONResponse({"source_kind": kind, "source_id": source_id,
                         "impacts": [
        {"link_id": str(r["link_id"]),
         "derivation_strategy": r["derivation_strategy"],
         "target_kind": r["target_kind"],
         "target_table": r["target_table"],
         "target_id": r["target_id"],
         "status": r["status"],
         "source_kind_resolved": r["source_kind"],
         "source_id_resolved": str(r["source_id"]),
         "generated_at": r["generated_at"].isoformat() if r.get("generated_at") else None}
        for r in rows
    ]})


# ---------------------------------------------------------------------------
# Wave 8: data-model snapshot read endpoints (write-side is the to_data_model
# strategy, exposed via existing /api/std/derive/rerun/{vid}).
# ---------------------------------------------------------------------------


def _data_model_version_or_404(vid: str):
    """Verify the version exists. Returns (None) on success, JSONResponse on 404."""
    eng = get_engine()
    with eng.connect() as c:
        row = c.execute(text(
            "SELECT id FROM std_document_version WHERE id=:i"
        ), {"i": vid}).first()
    if row is None:
        return JSONResponse({"error": "version not found"}, status_code=404)
    return None


def _active_snapshot_or_404(vid: str):
    """Return the latest active snapshot row for a version, or a 404 JSONResponse."""
    eng = get_engine()
    with eng.connect() as c:
        row = c.execute(text(
            "SELECT id, document_version_id, generated_at, generated_by, "
            "       cdm_json, ldm_json, pdm_json, ddl_postgresql, "
            "       entity_count, attribute_count, constraint_count, "
            "       derived_status, source_tag "
            "FROM std_data_model_snapshot "
            "WHERE document_version_id=:v AND derived_status='active' "
            "ORDER BY generated_at DESC LIMIT 1"
        ), {"v": vid}).mappings().first()
    if row is None:
        return JSONResponse(
            {"error": "no active data-model snapshot for this version; "
                      "trigger one via /api/std/derive/rerun/{vid}"},
            status_code=404,
        )
    return dict(row)


async def data_model_get_handler(request: Request):
    """GET /api/std/data-model/{vid}?layer=cdm|ldm|pdm|ddl

    Returns the latest active snapshot's full payload, or just one layer
    if `layer=` is supplied. 404 if no active snapshot exists yet.
    """
    _, _, err = _auth_or_401(request)
    if err: return err
    vid = request.path_params["version_id"]
    not_found = _data_model_version_or_404(vid)
    if not_found: return not_found

    snap = _active_snapshot_or_404(vid)
    if isinstance(snap, JSONResponse): return snap

    layer = request.query_params.get("layer")
    if layer:
        if layer == "cdm":
            return JSONResponse({"layer": "CDM", "data": snap["cdm_json"]})
        if layer == "ldm":
            return JSONResponse({"layer": "LDM", "data": snap["ldm_json"]})
        if layer == "pdm":
            return JSONResponse({"layer": "PDM", "data": snap["pdm_json"]})
        if layer == "ddl":
            return JSONResponse({"layer": "DDL",
                                 "data": snap["ddl_postgresql"]})
        return JSONResponse(
            {"error": "layer must be cdm | ldm | pdm | ddl"},
            status_code=400,
        )

    return JSONResponse({
        "snapshot_id": str(snap["id"]),
        "version_id": str(snap["document_version_id"]),
        "generated_at": snap["generated_at"].isoformat()
                        if snap.get("generated_at") else None,
        "generated_by": snap["generated_by"],
        "derived_status": snap["derived_status"],
        "source_tag": snap["source_tag"],
        "stats": {
            "entity_count": snap["entity_count"],
            "attribute_count": snap["attribute_count"],
            "constraint_count": snap["constraint_count"],
        },
        "cdm": snap["cdm_json"],
        "ldm": snap["ldm_json"],
        "pdm": snap["pdm_json"],
        "ddl_postgresql": snap["ddl_postgresql"],
    })


async def data_model_ddl_handler(request: Request):
    """GET /api/std/data-model/{vid}/ddl — returns the rendered DDL as
    text/plain so a browser will save it as a .sql file."""
    _, _, err = _auth_or_401(request)
    if err: return err
    vid = request.path_params["version_id"]
    not_found = _data_model_version_or_404(vid)
    if not_found: return not_found

    snap = _active_snapshot_or_404(vid)
    if isinstance(snap, JSONResponse): return snap

    return PlainTextResponse(
        snap["ddl_postgresql"],
        headers={
            "Content-Disposition":
                f'attachment; filename="data_model_{vid[:8]}.sql"',
        },
    )


async def data_model_xmi_handler(request: Request):
    """GET /api/std/data-model/{vid}/xmi - returns EA-compatible XMI XML."""
    _, _, err = _auth_or_401(request)
    if err: return err
    vid = request.path_params["version_id"]
    not_found = _data_model_version_or_404(vid)
    if not_found: return not_found

    snap = _active_snapshot_or_404(vid)
    if isinstance(snap, JSONResponse): return snap

    try:
        xmi = export_pdm_to_ea_xmi(
            snap["pdm_json"],
            model_name=f"Standards Platform Data Model {vid[:8]}",
            package_name=f"Data Model {vid[:8]}",
        )
    except Exception as e:
        logger.exception("failed to export data-model XMI")
        return JSONResponse({"error": f"failed to export XMI: {e}"},
                            status_code=500)

    return Response(
        xmi,
        media_type="application/xml",
        headers={
            "Content-Disposition":
                f'attachment; filename="data_model_{vid[:8]}.xml"',
        },
    )


async def data_model_snapshots_handler(request: Request):
    """GET /api/std/data-model/{vid}/snapshots — list all snapshots (active
    + stale + manual) for a version, newest first. Useful for diffing
    re-derive history."""
    _, _, err = _auth_or_401(request)
    if err: return err
    vid = request.path_params["version_id"]
    not_found = _data_model_version_or_404(vid)
    if not_found: return not_found

    eng = get_engine()
    with eng.connect() as c:
        rows = c.execute(text(
            "SELECT id, generated_at, generated_by, derived_status, "
            "       entity_count, attribute_count, constraint_count, "
            "       source_tag, std_derived_link_id "
            "FROM std_data_model_snapshot "
            "WHERE document_version_id=:v "
            "ORDER BY generated_at DESC"
        ), {"v": vid}).mappings().all()

    return JSONResponse({"version_id": vid, "snapshots": [
        {
            "snapshot_id": str(r["id"]),
            "generated_at": r["generated_at"].isoformat()
                            if r.get("generated_at") else None,
            "generated_by": r["generated_by"],
            "derived_status": r["derived_status"],
            "source_tag": r["source_tag"],
            "std_derived_link_id": str(r["std_derived_link_id"])
                                    if r.get("std_derived_link_id") else None,
            "stats": {
                "entity_count": r["entity_count"],
                "attribute_count": r["attribute_count"],
                "constraint_count": r["constraint_count"],
            },
        }
        for r in rows
    ]})


standards_routes = [
    Route("/api/std/documents", endpoint=list_documents, methods=["GET"]),
    Route("/api/std/documents", endpoint=upload_document, methods=["POST"]),
    Route("/api/std/documents/{doc_id}", endpoint=get_document, methods=["GET"]),
    Route("/api/std/documents/{doc_id}/versions", endpoint=list_versions, methods=["GET"]),
    Route("/api/std/versions/{version_id}/clauses", endpoint=list_clauses, methods=["GET"]),
    Route("/api/std/versions/{version_id}/data-elements", endpoint=list_data_elements, methods=["GET"]),
    Route("/api/std/clauses/{clause_id}/elements",
          endpoint=list_clause_elements, methods=["GET"]),
    Route("/api/std/versions/{version_id}/terms", endpoint=list_terms, methods=["GET"]),
    Route("/api/std/versions/{version_id}/value-domains", endpoint=list_value_domains, methods=["GET"]),
    Route("/api/std/versions/{version_id}/similar", endpoint=list_similar, methods=["GET"]),
    Route("/api/std/web/fetch", endpoint=web_fetch_route, methods=["POST"]),
    Route("/api/std/web/manual", endpoint=web_manual_route, methods=["POST"]),
    Route("/api/std/outbox/status", endpoint=outbox_status, methods=["GET"]),
    Route("/api/std/outbox/events", endpoint=list_outbox_events, methods=["GET"]),
    Route("/api/std/outbox/events/retry",
          endpoint=retry_outbox_events, methods=["POST"]),
    Route("/api/std/outbox/events/{event_id}/retry",
          endpoint=retry_outbox_event, methods=["POST"]),
    Route("/api/std/clauses/{clause_id}/lock",
          endpoint=lock_clause, methods=["POST"]),
    Route("/api/std/clauses/{clause_id}/heartbeat",
          endpoint=heartbeat_clause, methods=["POST"]),
    Route("/api/std/clauses/{clause_id}/lock/release",
          endpoint=release_clause_lock, methods=["POST"]),
    Route("/api/std/clauses/{clause_id}",
          endpoint=save_clause_route, methods=["PUT"]),
    Route("/api/std/clauses/{clause_id}/lock/break",
          endpoint=break_clause_lock, methods=["POST"]),
    Route("/api/std/citation/search",
          endpoint=citation_search, methods=["POST"]),
    Route("/api/std/citation/insert",
          endpoint=citation_insert, methods=["POST"]),
    Route("/api/std/reviews/rounds",
          endpoint=review_round_start, methods=["POST"]),
    Route("/api/std/reviews/rounds",
          endpoint=review_round_list, methods=["GET"]),
    Route("/api/std/reviews/rounds/{round_id}/close-precheck",
          endpoint=review_round_close_precheck, methods=["GET"]),
    Route("/api/std/reviews/rounds/{round_id}/close",
          endpoint=review_round_close, methods=["POST"]),
    Route("/api/std/reviews/rounds/{round_id}/comments",
          endpoint=review_comment_list, methods=["GET"]),
    Route("/api/std/reviews/rounds/{round_id}/comments",
          endpoint=review_comment_post, methods=["POST"]),
    Route("/api/std/reviews/comments/{comment_id}/resolve",
          endpoint=review_comment_resolve, methods=["POST"]),
    Route("/api/std/reviews/references/{ref_id}/status",
          endpoint=review_reference_patch_status, methods=["PATCH"]),
    Route("/api/std/clauses/{clause_id}/references",
          endpoint=list_clause_references, methods=["GET"]),
    # Wave 5: publishing
    Route("/api/std/publish/versions/{version_id}",
          endpoint=publish_version_handler, methods=["POST"]),
    Route("/api/std/publish/fork",
          endpoint=publish_fork_handler, methods=["POST"]),
    Route("/api/std/publish/versions",
          endpoint=publish_list_versions_handler, methods=["GET"]),
    Route("/api/std/publish/timeline/{version_id}",
          endpoint=publish_timeline_handler, methods=["GET"]),
    Route("/api/std/versions/{version_id}",
          endpoint=get_version_handler, methods=["GET"]),
    # Wave 5: derivation
    Route("/api/std/derive/strategies",
          endpoint=derive_strategies_handler, methods=["GET"]),
    Route("/api/std/derive/links",
          endpoint=derive_links_handler, methods=["GET"]),
    Route("/api/std/derive/rerun/{version_id}",
          endpoint=derive_rerun_handler, methods=["POST"]),
    Route("/api/std/derive/status/{version_id}",
          endpoint=derive_status_handler, methods=["GET"]),
    # Wave 7: rollback + impact graph
    Route("/api/std/derive/rollback/{version_id}",
          endpoint=derive_rollback_handler, methods=["POST"]),
    Route("/api/std/impact/{kind}/{source_id}",
          endpoint=derive_impact_handler, methods=["GET"]),
    # Wave 8: data-model snapshot read endpoints
    Route("/api/std/data-model/{version_id}",
          endpoint=data_model_get_handler, methods=["GET"]),
    Route("/api/std/data-model/{version_id}/ddl",
          endpoint=data_model_ddl_handler, methods=["GET"]),
    Route("/api/std/data-model/{version_id}/xmi",
          endpoint=data_model_xmi_handler, methods=["GET"]),
    Route("/api/std/data-model/{version_id}/snapshots",
          endpoint=data_model_snapshots_handler, methods=["GET"]),
]


def get_standards_routes():
    return standards_routes
