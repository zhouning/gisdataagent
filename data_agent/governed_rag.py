"""Fail-closed retrieval over tenant-bound, immutable knowledge-base documents."""

from __future__ import annotations

import json
import re
from typing import Any

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import text

from .database_tools import T_KB_CHUNKS, T_KB_DOCUMENTS, T_KNOWLEDGE_BASES
from .db_engine import get_engine
from .knowledge_base import (
    GOVERNED_CHUNK_SCHEMA,
    GOVERNED_DOCUMENT_SCHEMA,
    _get_embeddings,
    _sha256_text,
    governed_chunk_locator,
    governed_document_resource_id,
)

_DOCUMENT_RESOURCE_RE = re.compile(r"^kb:([1-9][0-9]*)/documents/([1-9][0-9]*)$")


class GovernedRAGError(ValueError):
    """A governed retrieval cannot prove authorization or immutable evidence."""


class GovernedRAGUnavailableError(GovernedRAGError):
    """The governed retrieval authority is unavailable."""


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class GovernedDocumentPin(_StrictModel):
    resource_id: str = Field(
        min_length=1,
        max_length=200,
        pattern=r"^kb:[1-9][0-9]*/documents/[1-9][0-9]*$",
    )
    version: str = Field(pattern=r"^sha256-[0-9a-f]{64}$")
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @model_validator(mode="after")
    def _version_matches_digest(self) -> GovernedDocumentPin:
        if self.version != f"sha256-{self.content_sha256}":
            raise ValueError("document version must be derived from content_sha256")
        return self

    @property
    def kb_id(self) -> int:
        match = _DOCUMENT_RESOURCE_RE.fullmatch(self.resource_id)
        assert match is not None
        return int(match.group(1))

    @property
    def doc_id(self) -> int:
        match = _DOCUMENT_RESOURCE_RE.fullmatch(self.resource_id)
        assert match is not None
        return int(match.group(2))


class GovernedRAGHit(_StrictModel):
    chunk_id: int = Field(gt=0)
    knowledge_base_id: int = Field(gt=0)
    document_id: int = Field(gt=0)
    document_resource_id: str
    document_version: str = Field(pattern=r"^sha256-[0-9a-f]{64}$")
    document_content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    chunk_index: int = Field(ge=0)
    content: str = Field(min_length=1)
    chunk_content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    locator: str = Field(min_length=1, max_length=1_024)
    filename: str = Field(min_length=1, max_length=500)
    content_type: str = Field(min_length=1, max_length=100)
    score: float = Field(ge=-1.0, le=1.0)


def _metadata_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except ValueError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _validate_document_row(
    row: tuple[Any, ...],
    pin: GovernedDocumentPin,
    tenant_id: str,
) -> dict[str, Any]:
    doc_id, kb_id, filename, content_type, raw_text, metadata, owner = row
    resource_id = governed_document_resource_id(int(kb_id), int(doc_id))
    document_metadata = _metadata_dict(metadata)
    actual_digest = _sha256_text(str(raw_text or ""))
    required = {
        "schema": GOVERNED_DOCUMENT_SCHEMA,
        "tenant_id": tenant_id,
        "owner_subject_id": str(owner),
        "content_sha256": actual_digest,
        "version_key": f"sha256-{actual_digest}",
        "filename": str(filename),
        "content_type": str(content_type),
    }
    if resource_id != pin.resource_id:
        raise GovernedRAGError("resolved document identity does not match its pin")
    if any(document_metadata.get(key) != value for key, value in required.items()):
        raise GovernedRAGError(
            f"document {resource_id} has incomplete or changed governance metadata"
        )
    if actual_digest != pin.content_sha256 or pin.version != required["version_key"]:
        raise GovernedRAGError(
            f"document {resource_id} content does not match the requested immutable version"
        )
    return {
        "doc_id": int(doc_id),
        "kb_id": int(kb_id),
        "filename": str(filename),
        "content_type": str(content_type),
        "resource_id": resource_id,
        "version": pin.version,
        "content_sha256": pin.content_sha256,
    }


def _validate_chunk_row(
    row: tuple[Any, ...],
    document: dict[str, Any],
    tenant_id: str,
) -> tuple[list[float], dict[str, Any]]:
    chunk_id, content, embedding, doc_id, kb_id, chunk_index, metadata = row
    if int(doc_id) != document["doc_id"] or int(kb_id) != document["kb_id"]:
        raise GovernedRAGError("chunk identity is not bound to its pinned document")
    content = str(content or "")
    chunk_digest = _sha256_text(content)
    locator = governed_chunk_locator(int(kb_id), int(doc_id), int(chunk_index))
    chunk_metadata = _metadata_dict(metadata)
    required = {
        "schema": GOVERNED_CHUNK_SCHEMA,
        "tenant_id": tenant_id,
        "document_resource_id": document["resource_id"],
        "document_version": document["version"],
        "document_content_sha256": document["content_sha256"],
        "chunk_content_sha256": chunk_digest,
        "locator": locator,
    }
    if not content or any(chunk_metadata.get(key) != value for key, value in required.items()):
        raise GovernedRAGError(
            f"chunk {chunk_id} has incomplete or changed governance evidence"
        )
    if not isinstance(embedding, (list, tuple)) or not embedding:
        raise GovernedRAGError(f"chunk {chunk_id} has no governed embedding")
    try:
        vector = [float(value) for value in embedding]
    except (TypeError, ValueError) as exc:
        raise GovernedRAGError(f"chunk {chunk_id} has an invalid embedding") from exc
    return vector, {
        "chunk_id": int(chunk_id),
        "knowledge_base_id": int(kb_id),
        "document_id": int(doc_id),
        "document_resource_id": document["resource_id"],
        "document_version": document["version"],
        "document_content_sha256": document["content_sha256"],
        "chunk_index": int(chunk_index),
        "content": content,
        "chunk_content_sha256": chunk_digest,
        "locator": locator,
        "filename": document["filename"],
        "content_type": document["content_type"],
    }


def search_governed_knowledge_base(
    *,
    query: str,
    tenant_id: str,
    subject_id: str,
    knowledge_base_ids: tuple[int, ...],
    document_pins: tuple[GovernedDocumentPin, ...],
    top_k: int,
) -> tuple[GovernedRAGHit, ...]:
    """Search only explicitly pinned documents whose current bytes still verify."""
    tenant_id = tenant_id.strip()
    subject_id = subject_id.strip()
    query = query.strip()
    if not tenant_id or not subject_id or not query:
        raise GovernedRAGError("tenant, subject, and query are required")
    if not document_pins:
        raise GovernedRAGError("at least one immutable document pin is required")
    selected_kbs = set(knowledge_base_ids)
    if not selected_kbs or any(pin.kb_id not in selected_kbs for pin in document_pins):
        raise GovernedRAGError("document pins must belong to the selected knowledge bases")
    pin_by_identity = {(pin.kb_id, pin.doc_id): pin for pin in document_pins}
    if len(pin_by_identity) != len(document_pins):
        raise GovernedRAGError("document pins must be unique")

    engine = get_engine()
    if not engine:
        raise GovernedRAGUnavailableError("knowledge-base database is unavailable")
    try:
        with engine.connect() as conn:
            document_rows = conn.execute(text(f"""
                SELECT d.id, d.kb_id, d.filename, d.content_type, d.raw_text,
                       d.metadata, kb.owner_username
                FROM {T_KB_DOCUMENTS} d
                JOIN {T_KNOWLEDGE_BASES} kb ON kb.id = d.kb_id
                WHERE d.id = ANY(:doc_ids)
                  AND d.kb_id = ANY(:kb_ids)
                  AND d.metadata->>'tenant_id' = :tenant_id
                  AND (kb.owner_username = :subject_id OR kb.is_shared = TRUE)
                ORDER BY d.kb_id, d.id
            """), {
                "doc_ids": [pin.doc_id for pin in document_pins],
                "kb_ids": sorted(selected_kbs),
                "tenant_id": tenant_id,
                "subject_id": subject_id,
            }).fetchall()
            if len(document_rows) != len(document_pins):
                raise GovernedRAGError(
                    "one or more pinned documents are inaccessible, cross-tenant, or unversioned"
                )
            documents: dict[int, dict[str, Any]] = {}
            for row in document_rows:
                identity = (int(row[1]), int(row[0]))
                pin = pin_by_identity.get(identity)
                if pin is None or int(row[0]) in documents:
                    raise GovernedRAGError("document authority returned an unexpected identity")
                documents[int(row[0])] = _validate_document_row(row, pin, tenant_id)

            chunk_rows = conn.execute(text(f"""
                SELECT c.id, c.content, c.embedding, c.doc_id, c.kb_id,
                       c.chunk_index, c.metadata
                FROM {T_KB_CHUNKS} c
                WHERE c.doc_id = ANY(:doc_ids)
                  AND c.kb_id = ANY(:kb_ids)
                ORDER BY c.doc_id, c.chunk_index
            """), {
                "doc_ids": sorted(documents),
                "kb_ids": sorted(selected_kbs),
            }).fetchall()
    except GovernedRAGError:
        raise
    except Exception as exc:
        raise GovernedRAGUnavailableError(
            "governed knowledge-base authority failed"
        ) from exc
    if not chunk_rows:
        raise GovernedRAGError("pinned documents have no governed searchable chunks")

    candidates: list[tuple[list[float], dict[str, Any]]] = []
    seen_chunks: set[tuple[int, int]] = set()
    for row in chunk_rows:
        document = documents.get(int(row[3]))
        if document is None:
            raise GovernedRAGError("chunk is not bound to a pinned document")
        identity = (int(row[3]), int(row[5]))
        if identity in seen_chunks:
            raise GovernedRAGError("pinned document contains duplicate chunk locators")
        seen_chunks.add(identity)
        candidates.append(_validate_chunk_row(row, document, tenant_id))

    query_embeddings = _get_embeddings([query])
    if len(query_embeddings) != 1 or not query_embeddings[0]:
        raise GovernedRAGUnavailableError("query embedding evidence is unavailable")
    query_vector = np.asarray(query_embeddings[0], dtype=np.float32)
    query_norm = float(np.linalg.norm(query_vector))
    if query_norm == 0:
        raise GovernedRAGError("query embedding has zero magnitude")

    scored: list[GovernedRAGHit] = []
    for vector, payload in candidates:
        candidate = np.asarray(vector, dtype=np.float32)
        if candidate.shape != query_vector.shape:
            raise GovernedRAGError("chunk embedding dimension does not match query embedding")
        candidate_norm = float(np.linalg.norm(candidate))
        if candidate_norm == 0:
            raise GovernedRAGError("chunk embedding has zero magnitude")
        score = float(np.dot(query_vector, candidate) / (query_norm * candidate_norm))
        scored.append(GovernedRAGHit(**payload, score=round(score, 6)))
    scored.sort(key=lambda item: (-item.score, item.document_id, item.chunk_index))
    return tuple(scored[:top_k])
