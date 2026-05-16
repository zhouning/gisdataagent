"""Standards Platform REST routes (P0). Auth via _get_user_from_request +
_set_user_context, role gates inline."""
from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path

from sqlalchemy import text
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from ..db_engine import get_engine
from ..observability import get_logger
from ..standards_platform import repository, outbox
from ..standards_platform.ingestion.uploader import ingest_upload
from ..standards_platform.ingestion.web_fetcher import fetch as web_fetch, save_manual, NotAllowed
from ..standards_platform.analysis.deduper import find_similar_clauses
from . import helpers as _helpers
from .helpers import _set_user_context, _require_admin

logger = get_logger("api.standards_routes")

_EDITOR_ROLES = {"admin", "analyst", "standard_editor"}
_REVIEWER_ROLES = {"admin", "analyst", "standard_editor", "standard_reviewer"}

from ..standards_platform.drafting import editor_session as _editor


def _require_editor_or_403(role: str | None) -> JSONResponse | None:
    if role not in _EDITOR_ROLES:
        return JSONResponse({"error": "Forbidden — editor role required"},
                            status_code=403)
    return None


def _auth_or_401(request: Request):
    u = _helpers._get_user_from_request(request)
    if not u:
        return None, None, JSONResponse({"error": "Unauthorized"}, status_code=401)
    username, role = _set_user_context(u)
    return username, role, None


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
    eng = get_engine()
    with eng.connect() as conn:
        rows = conn.execute(text(
            "SELECT status, COUNT(*) AS n FROM std_outbox GROUP BY status"
        )).mappings().all()
    return JSONResponse({"counts": {r["status"]: r["n"] for r in rows}})


async def lock_clause(request: Request):
    username, role, err = _auth_or_401(request)
    if err: return err
    forbid = _require_editor_or_403(role)
    if forbid: return forbid
    cid = request.path_params["clause_id"]
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
]


def get_standards_routes():
    return standards_routes
