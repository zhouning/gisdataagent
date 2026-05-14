"""Thin CRUD helpers over std_* tables. Raw SQL, returns plain dicts."""
from __future__ import annotations

import uuid
from typing import Optional

from sqlalchemy import text

from ..db_engine import get_engine
from ..observability import get_logger

logger = get_logger("standards_platform.repository")


def create_document(*, doc_code: str, title: str, source_type: str,
                    owner_user_id: str, raw_file_path: str,
                    source_url: Optional[str] = None,
                    language: str = "zh-CN",
                    tags: Optional[list[str]] = None) -> str:
    doc_id = str(uuid.uuid4())
    eng = get_engine()
    with eng.connect() as conn:
        conn.execute(text("""
            INSERT INTO std_document
                (id, doc_code, title, source_type, source_url, language,
                 owner_user_id, raw_file_path, tags, created_by, updated_by)
            VALUES (:id, :code, :title, :st, :url, :lang,
                    :owner, :path, :tags, :owner, :owner)
        """), {"id": doc_id, "code": doc_code, "title": title, "st": source_type,
                "url": source_url, "lang": language, "owner": owner_user_id,
                "path": raw_file_path, "tags": tags or []})
        conn.commit()
    return doc_id


def create_version(*, document_id: str, version_label: str,
                   created_by: str, semver_major: int = 1,
                   semver_minor: int = 0, semver_patch: int = 0) -> str:
    ver_id = str(uuid.uuid4())
    eng = get_engine()
    with eng.connect() as conn:
        conn.execute(text("""
            INSERT INTO std_document_version
                (id, document_id, version_label, semver_major,
                 semver_minor, semver_patch, status, created_by, updated_by)
            VALUES (:id, :doc, :lbl, :ma, :mi, :pa, 'draft', :u, :u)
        """), {"id": ver_id, "doc": document_id, "lbl": version_label,
                "ma": semver_major, "mi": semver_minor, "pa": semver_patch,
                "u": created_by})
        conn.commit()
    return ver_id


def set_current_version(document_id: str, version_id: str) -> None:
    eng = get_engine()
    with eng.connect() as conn:
        conn.execute(text(
            "UPDATE std_document SET current_version_id=:v, updated_at=now() WHERE id=:d"
        ), {"v": version_id, "d": document_id})
        conn.commit()


def _stringify_uuids(d: dict) -> dict:
    """Convert UUID values to str for consistent API returns."""
    from uuid import UUID
    return {k: str(v) if isinstance(v, UUID) else v for k, v in d.items()}


def get_document(document_id: str) -> Optional[dict]:
    eng = get_engine()
    if eng is None:
        return None
    with eng.connect() as conn:
        row = conn.execute(text(
            "SELECT * FROM std_document WHERE id = :i"
        ), {"i": document_id}).mappings().first()
        return _stringify_uuids(dict(row)) if row else None


def list_documents(*, owner_user_id: Optional[str] = None,
                   status: Optional[str] = None,
                   limit: int = 100) -> list[dict]:
    eng = get_engine()
    with eng.connect() as conn:
        clauses = []
        params: dict = {"lim": limit}
        if owner_user_id is not None:
            clauses.append("owner_user_id = :o")
            params["o"] = owner_user_id
        if status is not None:
            clauses.append("status = :s")
            params["s"] = status
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        rows = conn.execute(text(
            f"SELECT * FROM std_document {where} ORDER BY created_at DESC LIMIT :lim"
        ), params).mappings().all()
        return [_stringify_uuids(dict(r)) for r in rows]


def update_document_status(document_id: str, status: str,
                           *, last_error: Optional[dict] = None) -> None:
    eng = get_engine()
    with eng.connect() as conn:
        if last_error is not None:
            import json
            conn.execute(text("""
                UPDATE std_document SET status=:s, last_error_log=CAST(:e AS jsonb),
                       updated_at=now() WHERE id=:i
            """), {"s": status, "e": json.dumps(last_error, ensure_ascii=False),
                    "i": document_id})
        else:
            conn.execute(text(
                "UPDATE std_document SET status=:s, updated_at=now() WHERE id=:i"
            ), {"s": status, "i": document_id})
        conn.commit()
