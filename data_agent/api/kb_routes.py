"""
Knowledge Base API routes — KB CRUD, document management, semantic search, GraphRAG.

Extracted from frontend_api.py (S-4 refactoring).
"""
from starlette.requests import Request
from starlette.responses import JSONResponse

from ..governed_external_access import (
    GovernedExternalAccessForbidden,
    GovernedExternalAccessService,
    GovernedExternalAccessUnavailable,
)
from ..governed_query_security import (
    GovernedQuerySecurityError,
    resolve_governed_query_security_ports,
)
from ..user_context import current_tenant_id
from .helpers import _get_user_from_request, _set_user_context


def _external_access() -> GovernedExternalAccessService:
    return GovernedExternalAccessService()


async def kb_list(request: Request):
    """GET /api/kb — list user's knowledge bases."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)
    from ..knowledge_base import list_knowledge_bases
    kbs = list_knowledge_bases(include_shared=True)
    return JSONResponse({"knowledge_bases": kbs})


async def kb_create(request: Request):
    """POST /api/kb — create a knowledge base."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON body"}, status_code=400)
    name = (body.get("name") or "").strip()
    if not name:
        return JSONResponse({"error": "name is required"}, status_code=400)
    from ..knowledge_base import create_knowledge_base
    kb_id = create_knowledge_base(
        name=name,
        description=(body.get("description") or "").strip(),
        is_shared=body.get("is_shared", False),
    )
    if kb_id is None:
        return JSONResponse(
            {"error": "Failed to create (duplicate name or limit reached)"},
            status_code=409,
        )
    return JSONResponse({"id": kb_id, "name": name}, status_code=201)


async def kb_detail(request: Request):
    """GET /api/kb/{id} — knowledge base detail with documents."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)
    kb_id = int(request.path_params.get("id", 0))
    from ..knowledge_base import get_knowledge_base, list_documents
    kb = get_knowledge_base(kb_id)
    if not kb:
        return JSONResponse({"error": "Knowledge base not found"}, status_code=404)
    docs = list_documents(kb_id)
    kb["documents"] = docs
    return JSONResponse(kb)


async def kb_delete(request: Request):
    """DELETE /api/kb/{id} — delete a knowledge base."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)
    kb_id = int(request.path_params.get("id", 0))
    from ..knowledge_base import delete_knowledge_base
    ok = delete_knowledge_base(kb_id)
    if not ok:
        return JSONResponse({"error": "Not found or not owned by you"}, status_code=404)
    return JSONResponse({"ok": True})


async def kb_doc_upload(request: Request):
    """POST /api/kb/{id}/documents — upload a document."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)
    kb_id = int(request.path_params.get("id", 0))
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON body"}, status_code=400)
    text_content = (body.get("text") or "").strip()
    filename = (body.get("filename") or "document.txt").strip()
    if not text_content:
        return JSONResponse({"error": "text is required"}, status_code=400)
    from ..knowledge_base import add_document
    doc_id = add_document(
        kb_id,
        filename,
        text_content,
        content_type=body.get("content_type"),
    )
    if doc_id is None:
        return JSONResponse({"error": "Failed to add document"}, status_code=400)
    return JSONResponse({"doc_id": doc_id, "filename": filename}, status_code=201)


async def kb_doc_delete(request: Request):
    """DELETE /api/kb/{id}/documents/{doc_id} — delete a document."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)
    kb_id = int(request.path_params.get("id", 0))
    doc_id = int(request.path_params.get("doc_id", 0))
    from ..knowledge_base import delete_document
    ok = delete_document(doc_id, kb_id)
    if not ok:
        return JSONResponse({"error": "Not found or not owned by you"}, status_code=404)
    return JSONResponse({"ok": True})


async def kb_search(request: Request):
    """POST /api/kb/search — retrieve explicitly pinned immutable documents."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    username, role = _set_user_context(user)
    tenant_id = current_tenant_id.get().strip()
    if not tenant_id:
        return JSONResponse(
            {"error": "tenant context is required", "code": "tenant_required"},
            status_code=403,
        )
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON body"}, status_code=400)
    query = (body.get("query") or "").strip()
    if not query:
        return JSONResponse({"error": "query is required"}, status_code=400)
    if len(query) > 4_000:
        return JSONResponse(
            {"error": "query must not exceed 4000 characters"}, status_code=400
        )
    try:
        top_k = int(body.get("top_k", 5))
    except (TypeError, ValueError):
        return JSONResponse({"error": "top_k must be an integer"}, status_code=400)
    if not 1 <= top_k <= 20:
        return JSONResponse(
            {"error": "top_k must be between 1 and 20"}, status_code=400
        )
    raw_kb_ids = body.get("kb_ids")
    if not isinstance(raw_kb_ids, list) or not raw_kb_ids:
        return JSONResponse({"error": "kb_ids are required"}, status_code=400)
    try:
        kb_ids = tuple(int(value) for value in raw_kb_ids)
    except (TypeError, ValueError):
        return JSONResponse(
            {"error": "kb_ids must contain positive integers"}, status_code=400
        )
    if (
        len(kb_ids) > 20
        or any(value <= 0 for value in kb_ids)
        or len(kb_ids) != len(set(kb_ids))
    ):
        return JSONResponse(
            {"error": "kb_ids must contain at most 20 unique positive integers"},
            status_code=400,
        )
    raw_pins = body.get("document_pins")
    if not isinstance(raw_pins, list) or not raw_pins:
        return JSONResponse(
            {
                "error": "document_pins are required for governed retrieval",
                "code": "immutable_document_pins_required",
            },
            status_code=400,
        )

    from pydantic import ValidationError

    from ..governed_rag import (
        GovernedDocumentPin,
        GovernedRAGError,
        GovernedRAGUnavailableError,
        search_governed_knowledge_base,
    )

    try:
        pins = tuple(GovernedDocumentPin.model_validate(value) for value in raw_pins)
    except (TypeError, ValidationError, ValueError):
        return JSONResponse(
            {"error": "document_pins are invalid"}, status_code=400
        )
    pin_identities = {(pin.kb_id, pin.doc_id) for pin in pins}
    if (
        len(pins) > 20
        or len(pin_identities) != len(pins)
        or any(pin.kb_id not in kb_ids for pin in pins)
    ):
        return JSONResponse(
            {
                "error": (
                    "document_pins must contain at most 20 unique documents "
                    "from kb_ids"
                )
            },
            status_code=400,
        )
    request_payload = {
        "query": query,
        "knowledge_base_ids": list(kb_ids),
        "document_pins": [pin.model_dump(mode="json") for pin in pins],
        "top_k": top_k,
    }
    try:
        security_ports = resolve_governed_query_security_ports(tenant_id)
        hits = _external_access().execute(
            tenant_id=tenant_id,
            actor_subject=f"human:{username}",
            roles=(role,),
            channel="rag",
            adapter_id="gda.rag.immutable-document.v1",
            access_mode="retrieve",
            resource_refs=tuple(
                f"{pin.resource_id}@{pin.version}" for pin in pins
            ),
            request_payload=request_payload,
            action="rag.document.retrieve",
            operation=lambda: search_governed_knowledge_base(
                query=query,
                tenant_id=tenant_id,
                subject_id=username,
                knowledge_base_ids=kb_ids,
                document_pins=pins,
                top_k=top_k,
            ),
            security_reader=security_ports[0] if security_ports else None,
        )
    except GovernedExternalAccessForbidden:
        return JSONResponse(
            {"error": "governed retrieval is forbidden", "code": "spr_denied"},
            status_code=403,
        )
    except (GovernedExternalAccessUnavailable, GovernedQuerySecurityError):
        return JSONResponse(
            {
                "error": "governed retrieval security is unavailable",
                "code": "security_unavailable",
            },
            status_code=503,
        )
    except GovernedRAGUnavailableError:
        return JSONResponse(
            {"error": "governed retrieval is unavailable"}, status_code=503
        )
    except GovernedRAGError:
        return JSONResponse(
            {
                "error": "governed retrieval evidence could not be verified",
                "code": "evidence_not_verified",
            },
            status_code=409,
        )
    results = [hit.model_dump(mode="json") for hit in hits]
    return JSONResponse({"results": results, "count": len(results)})


async def kb_build_graph(request: Request):
    """POST /api/kb/{id}/build-graph — extract knowledge graph from documents."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)
    kb_id = int(request.path_params.get("id", 0))
    from ..knowledge_base import build_kb_graph
    result = build_kb_graph(kb_id)
    return JSONResponse(result)


async def kb_graph(request: Request):
    """GET /api/kb/{id}/graph — retrieve knowledge graph structure."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)
    kb_id = int(request.path_params.get("id", 0))
    from ..knowledge_base import get_kb_graph
    graph = get_kb_graph(kb_id)
    return JSONResponse(graph)


async def kb_graph_search(request: Request):
    """Reject legacy GraphRAG until it can prove immutable document scope."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON body"}, status_code=400)
    query = (body.get("query") or "").strip()
    if not query:
        return JSONResponse({"error": "query is required"}, status_code=400)
    return JSONResponse(
        {
            "error": (
                "legacy GraphRAG is not admitted; use /api/kb/search with "
                "immutable document_pins"
            ),
            "code": "legacy_graph_rag_not_admitted",
        },
        status_code=409,
    )


async def kb_entities(request: Request):
    """GET /api/kb/{id}/entities — list entities in knowledge graph."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)
    kb_id = int(request.path_params.get("id", 0))
    from ..knowledge_base import get_kb_entities
    entities = get_kb_entities(kb_id)
    return JSONResponse({"entities": entities})
