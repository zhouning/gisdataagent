from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from data_agent.governed_rag import (
    GovernedDocumentPin,
    GovernedRAGError,
    search_governed_knowledge_base,
)
from data_agent.knowledge_base import (
    GOVERNED_CHUNK_SCHEMA,
    GOVERNED_DOCUMENT_SCHEMA,
    _sha256_text,
)

TENANT = "tenant-a"
SUBJECT = "analyst-a"
KB_ID = 7
DOC_ID = 11
CONTENT = "Versioned planning policy excerpt."
CHUNK = "planning policy excerpt"
DOCUMENT_DIGEST = _sha256_text(CONTENT)
DOCUMENT_VERSION = f"sha256-{DOCUMENT_DIGEST}"
CHUNK_DIGEST = _sha256_text(CHUNK)
RESOURCE_ID = f"kb:{KB_ID}/documents/{DOC_ID}"
LOCATOR = f"{RESOURCE_ID}/chunks/0"


def _pin(digest: str = DOCUMENT_DIGEST) -> GovernedDocumentPin:
    return GovernedDocumentPin(
        resource_id=RESOURCE_ID,
        version=f"sha256-{digest}",
        content_sha256=digest,
    )


def _document_metadata() -> dict[str, str]:
    return {
        "schema": GOVERNED_DOCUMENT_SCHEMA,
        "tenant_id": TENANT,
        "owner_subject_id": SUBJECT,
        "content_sha256": DOCUMENT_DIGEST,
        "version_key": DOCUMENT_VERSION,
        "filename": "policy.txt",
        "content_type": "text/plain",
    }


def _chunk_metadata(**overrides: str) -> dict[str, str]:
    metadata = {
        "schema": GOVERNED_CHUNK_SCHEMA,
        "tenant_id": TENANT,
        "document_resource_id": RESOURCE_ID,
        "document_version": DOCUMENT_VERSION,
        "document_content_sha256": DOCUMENT_DIGEST,
        "chunk_content_sha256": CHUNK_DIGEST,
        "locator": LOCATOR,
    }
    metadata.update(overrides)
    return metadata


def _engine_with_rows(document_rows, chunk_rows):
    engine = MagicMock()
    conn = MagicMock()
    engine.connect.return_value.__enter__.return_value = conn
    engine.connect.return_value.__exit__.return_value = False
    document_result = MagicMock()
    document_result.fetchall.return_value = document_rows
    chunk_result = MagicMock()
    chunk_result.fetchall.return_value = chunk_rows
    conn.execute.side_effect = [document_result, chunk_result]
    return engine, conn


def _valid_document_row(metadata=None):
    return (
        DOC_ID,
        KB_ID,
        "policy.txt",
        "text/plain",
        CONTENT,
        _document_metadata() if metadata is None else metadata,
        SUBJECT,
    )


def _valid_chunk_row(metadata=None):
    return (
        19,
        CHUNK,
        [1.0, 0.0],
        DOC_ID,
        KB_ID,
        0,
        _chunk_metadata() if metadata is None else metadata,
    )


def test_governed_rag_returns_verified_stable_locator(monkeypatch) -> None:
    engine, conn = _engine_with_rows(
        [_valid_document_row()],
        [_valid_chunk_row()],
    )
    monkeypatch.setattr("data_agent.governed_rag.get_engine", lambda: engine)
    monkeypatch.setattr(
        "data_agent.governed_rag._get_embeddings",
        lambda texts: [[1.0, 0.0]],
    )

    hits = search_governed_knowledge_base(
        query="planning policy",
        tenant_id=TENANT,
        subject_id=SUBJECT,
        knowledge_base_ids=(KB_ID,),
        document_pins=(_pin(),),
        top_k=1,
    )

    assert len(hits) == 1
    assert hits[0].document_resource_id == RESOURCE_ID
    assert hits[0].document_version == DOCUMENT_VERSION
    assert hits[0].chunk_content_sha256 == CHUNK_DIGEST
    assert hits[0].locator == LOCATOR
    document_params = conn.execute.call_args_list[0].args[1]
    assert document_params["tenant_id"] == TENANT
    assert document_params["subject_id"] == SUBJECT


def test_governed_rag_rejects_cross_user_or_cross_tenant_documents(monkeypatch) -> None:
    engine, _ = _engine_with_rows([], [])
    embedded = False

    def embed(_texts):
        nonlocal embedded
        embedded = True
        return [[1.0, 0.0]]

    monkeypatch.setattr("data_agent.governed_rag.get_engine", lambda: engine)
    monkeypatch.setattr("data_agent.governed_rag._get_embeddings", embed)

    with pytest.raises(GovernedRAGError, match="inaccessible, cross-tenant, or unversioned"):
        search_governed_knowledge_base(
            query="policy",
            tenant_id=TENANT,
            subject_id="other-user",
            knowledge_base_ids=(KB_ID,),
            document_pins=(_pin(),),
            top_k=1,
        )
    assert embedded is False


def test_governed_rag_rejects_legacy_unversioned_documents(monkeypatch) -> None:
    engine, _ = _engine_with_rows([_valid_document_row({})], [])
    monkeypatch.setattr("data_agent.governed_rag.get_engine", lambda: engine)

    with pytest.raises(GovernedRAGError, match="governance metadata"):
        search_governed_knowledge_base(
            query="policy",
            tenant_id=TENANT,
            subject_id=SUBJECT,
            knowledge_base_ids=(KB_ID,),
            document_pins=(_pin(),),
            top_k=1,
        )


def test_governed_rag_recomputes_document_digest(monkeypatch) -> None:
    engine, _ = _engine_with_rows([_valid_document_row()], [])
    monkeypatch.setattr("data_agent.governed_rag.get_engine", lambda: engine)

    with pytest.raises(GovernedRAGError, match="requested immutable version"):
        search_governed_knowledge_base(
            query="policy",
            tenant_id=TENANT,
            subject_id=SUBJECT,
            knowledge_base_ids=(KB_ID,),
            document_pins=(_pin("b" * 64),),
            top_k=1,
        )


def test_governed_rag_recomputes_chunk_digest(monkeypatch) -> None:
    changed = _chunk_metadata(chunk_content_sha256="c" * 64)
    engine, _ = _engine_with_rows(
        [_valid_document_row()],
        [_valid_chunk_row(changed)],
    )
    monkeypatch.setattr("data_agent.governed_rag.get_engine", lambda: engine)

    with pytest.raises(GovernedRAGError, match="chunk 19"):
        search_governed_knowledge_base(
            query="policy",
            tenant_id=TENANT,
            subject_id=SUBJECT,
            knowledge_base_ids=(KB_ID,),
            document_pins=(_pin(),),
            top_k=1,
        )


def test_governed_rag_requires_explicit_tenant_before_database_access(monkeypatch) -> None:
    accessed = False

    def engine():
        nonlocal accessed
        accessed = True
        return MagicMock()

    monkeypatch.setattr("data_agent.governed_rag.get_engine", engine)
    with pytest.raises(GovernedRAGError, match="tenant, subject, and query"):
        search_governed_knowledge_base(
            query="policy",
            tenant_id="",
            subject_id=SUBJECT,
            knowledge_base_ids=(KB_ID,),
            document_pins=(_pin(),),
            top_k=1,
        )
    assert accessed is False


def test_legacy_numeric_kb_resolution_checks_access_and_does_not_fall_back(monkeypatch) -> None:
    from data_agent import knowledge_base

    engine = MagicMock()
    conn = MagicMock()
    engine.connect.return_value.__enter__.return_value = conn
    engine.connect.return_value.__exit__.return_value = False
    inaccessible = MagicMock()
    inaccessible.fetchone.return_value = None
    conn.execute.return_value = inaccessible
    monkeypatch.setattr(knowledge_base, "get_engine", lambda: engine)
    monkeypatch.setattr(knowledge_base, "_get_embeddings", lambda texts: [[1.0, 0.0]])
    token = knowledge_base.current_user_id.set("other-user")
    try:
        assert knowledge_base.search_kb("policy", kb_id=KB_ID) == []
    finally:
        knowledge_base.current_user_id.reset(token)
    assert conn.execute.call_count == 1


def test_multi_kb_compatibility_search_applies_access_filter(monkeypatch) -> None:
    from data_agent import knowledge_base

    engine = MagicMock()
    conn = MagicMock()
    engine.connect.return_value.__enter__.return_value = conn
    engine.connect.return_value.__exit__.return_value = False
    chunks = MagicMock()
    chunks.fetchall.return_value = [
        (19, CHUNK, [1.0, 0.0], DOC_ID, 0, {}),
    ]
    conn.execute.return_value = chunks
    monkeypatch.setattr(knowledge_base, "get_engine", lambda: engine)
    monkeypatch.setattr(knowledge_base, "_get_embeddings", lambda texts: [[1.0, 0.0]])
    token = knowledge_base.current_user_id.set(SUBJECT)
    try:
        results = knowledge_base.search_knowledge_base(
            "policy",
            kb_ids=[KB_ID],
            top_k=1,
        )
    finally:
        knowledge_base.current_user_id.reset(token)

    assert results[0]["chunk_id"] == 19
    statement = str(conn.execute.call_args.args[0])
    assert "owner_username = :u OR kb.is_shared = TRUE" in statement
    assert conn.execute.call_args.args[1]["kb_ids"] == [KB_ID]


def test_add_document_persists_governed_document_and_chunk_metadata(monkeypatch) -> None:
    from data_agent import knowledge_base

    engine = MagicMock()
    conn = MagicMock()
    engine.connect.return_value.__enter__.return_value = conn
    engine.connect.return_value.__exit__.return_value = False
    ownership = MagicMock()
    ownership.fetchone.return_value = (KB_ID, 0)
    inserted_document = MagicMock()
    inserted_document.scalar.return_value = DOC_ID
    conn.execute.side_effect = [ownership, inserted_document, MagicMock(), MagicMock()]
    monkeypatch.setattr(knowledge_base, "get_engine", lambda: engine)
    monkeypatch.setattr(knowledge_base, "_get_embeddings", lambda chunks: [[1.0, 0.0]])
    user_token = knowledge_base.current_user_id.set(SUBJECT)
    tenant_token = knowledge_base.current_tenant_id.set(TENANT)
    try:
        doc_id = knowledge_base.add_document(
            KB_ID,
            "policy.txt",
            CONTENT,
            content_type="text/plain",
        )
    finally:
        knowledge_base.current_user_id.reset(user_token)
        knowledge_base.current_tenant_id.reset(tenant_token)

    assert doc_id == DOC_ID
    document_metadata = json.loads(conn.execute.call_args_list[1].args[1]["metadata"])
    chunk_metadata = json.loads(conn.execute.call_args_list[2].args[1]["metadata"])
    assert document_metadata["tenant_id"] == TENANT
    assert document_metadata["content_sha256"] == DOCUMENT_DIGEST
    assert document_metadata["version_key"] == DOCUMENT_VERSION
    assert chunk_metadata["document_resource_id"] == RESOURCE_ID
    assert chunk_metadata["locator"] == LOCATOR
    assert chunk_metadata["chunk_content_sha256"] == DOCUMENT_DIGEST
