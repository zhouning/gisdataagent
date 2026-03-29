"""
Knowledge Base API routes — KB CRUD, document management, semantic search, GraphRAG.

Extracted from frontend_api.py (S-4 refactoring).
"""
from starlette.requests import Request
from starlette.responses import JSONResponse

from .helpers import _get_user_from_request, _set_user_context


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
        return JSONResponse({"error": "Failed to create (duplicate name or limit reached)"}, status_code=409)
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
    doc_id = add_document(kb_id, filename, text_content, content_type=body.get("content_type"))
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
    """POST /api/kb/search — semantic search across knowledge bases."""
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
    top_k = body.get("top_k", 5)
    kb_ids = body.get("kb_ids")
    from ..knowledge_base import search_knowledge_base
    results = search_knowledge_base(query, kb_ids=kb_ids, top_k=top_k)
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
    """POST /api/kb/{id}/graph-search — entity/relation search."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)
    kb_id = int(request.path_params.get("id", 0))
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON body"}, status_code=400)
    query = (body.get("query") or "").strip()
    if not query:
        return JSONResponse({"error": "query is required"}, status_code=400)
    from ..knowledge_base import graph_rag_search
    results = graph_rag_search(kb_id, query)
    return JSONResponse({"results": results})


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
