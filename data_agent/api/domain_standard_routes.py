"""XMI Domain Standards REST routes.

Endpoints:
  GET  /api/xmi/status          — compiled artifact status
  GET  /api/xmi/modules         — list modules from global index
  GET  /api/xmi/classes         — list classes for a module (?module_id=X)
  GET  /api/xmi/class/{class_id:path} — full class detail + associations
  GET  /api/xmi/graph           — ReactFlow graph for a module (?module_id=X)
  POST /api/xmi/compile         — trigger corpus compilation
"""

import json
import logging
import os

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from .helpers import _get_user_from_request, _set_user_context

logger = logging.getLogger("data_agent.api.domain_standard_routes")

COMPILED_DIR = os.path.normpath(
    os.path.join(os.path.dirname(__file__), "..", "standards", "compiled")
)
_INDEX_PATH = os.path.join(COMPILED_DIR, "indexes", "xmi_global_index.yaml")


def _load_global_index() -> dict | None:
    if not os.path.exists(_INDEX_PATH):
        return None
    import yaml
    with open(_INDEX_PATH, encoding="utf-8") as f:
        return yaml.safe_load(f)


async def xmi_status(request: Request):
    """GET /api/xmi/status"""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)
    try:
        index = _load_global_index()
        if index is None:
            return JSONResponse({"compiled": False})
        return JSONResponse({
            "compiled": True,
            "module_count": index.get("module_count", 0),
            "class_count": index.get("class_count", 0),
            "association_count": index.get("association_count", 0),
            "last_compiled": index.get("generated_at"),
            "source_root": index.get("source_root"),
        })
    except Exception as e:
        logger.exception("xmi_status failed")
        return JSONResponse({"error": str(e)}, status_code=500)


async def xmi_modules(request: Request):
    """GET /api/xmi/modules"""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)
    try:
        index = _load_global_index()
        if index is None:
            return JSONResponse({"error": "XMI corpus not compiled"}, status_code=404)
        modules = [
            {
                "module_id": m.get("module_id"),
                "module_id_raw": m.get("module_id_raw"),
                "module_name": m.get("module_name"),
                "class_count": m.get("class_count", 0),
                "association_count": m.get("association_count", 0),
                "source_file": m.get("source_file"),
                "unresolved_ref_count": m.get("unresolved_ref_count", 0),
            }
            for m in index.get("modules", [])
        ]
        return JSONResponse({"modules": modules})
    except Exception as e:
        logger.exception("xmi_modules failed")
        return JSONResponse({"error": str(e)}, status_code=500)


async def xmi_classes(request: Request):
    """GET /api/xmi/classes?module_id=X"""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)
    module_id = request.query_params.get("module_id", "")
    if not module_id:
        return JSONResponse({"error": "module_id query param required"}, status_code=400)
    try:
        normalized_dir = os.path.join(COMPILED_DIR, "xmi_normalized")
        if not os.path.isdir(normalized_dir):
            return JSONResponse({"error": "XMI corpus not compiled"}, status_code=404)

        # Scan normalized JSON files for matching module_id
        for fname in os.listdir(normalized_dir):
            if not fname.endswith(".json"):
                continue
            fpath = os.path.join(normalized_dir, fname)
            with open(fpath, encoding="utf-8") as f:
                doc = json.load(f)
            if doc.get("module_id") == module_id:
                classes = [
                    {
                        "class_id": c.get("class_id"),
                        "class_id_raw": c.get("class_id_raw"),
                        "class_name": c.get("class_name"),
                        "package_path": c.get("package_path"),
                        "attribute_count": len(c.get("attributes", [])),
                        "super_class_id": c.get("super_class_id"),
                        "super_class_id_raw": c.get("super_class_id_raw"),
                    }
                    for c in doc.get("classes", [])
                ]
                return JSONResponse({
                    "module_id": module_id,
                    "module_name": doc.get("module_name"),
                    "classes": classes,
                })
        return JSONResponse({"error": f"Module '{module_id}' not found"}, status_code=404)
    except Exception as e:
        logger.exception("xmi_classes failed")
        return JSONResponse({"error": str(e)}, status_code=500)


async def xmi_class_detail(request: Request):
    """GET /api/xmi/class/{class_id:path}"""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)
    class_id = request.path_params.get("class_id", "")
    if not class_id:
        return JSONResponse({"error": "class_id required"}, status_code=400)
    try:
        index = _load_global_index()
        if index is None:
            return JSONResponse({"error": "XMI corpus not compiled"}, status_code=404)

        class_entry = index.get("class_index", {}).get(class_id)
        if not class_entry:
            return JSONResponse({"error": f"Class '{class_id}' not found"}, status_code=404)

        module_id = class_entry["module_id"]
        normalized_dir = os.path.join(COMPILED_DIR, "xmi_normalized")
        target_class = None
        referencing_associations = []

        for fname in os.listdir(normalized_dir):
            if not fname.endswith(".json"):
                continue
            fpath = os.path.join(normalized_dir, fname)
            with open(fpath, encoding="utf-8") as f:
                doc = json.load(f)

            if doc.get("module_id") == module_id and target_class is None:
                for c in doc.get("classes", []):
                    if c.get("class_id") == class_id:
                        target_class = c
                        break

            # Collect associations referencing this class_id from any module
            for assoc in doc.get("associations", []):
                for end in assoc.get("ends", []):
                    if end.get("type_global_ref") == class_id or end.get("type_ref") == class_id:
                        referencing_associations.append(assoc)
                        break

        if target_class is None:
            return JSONResponse({"error": f"Class '{class_id}' not found in normalized data"}, status_code=404)

        result = dict(target_class)
        result["referencing_associations"] = referencing_associations
        return JSONResponse(result)
    except Exception as e:
        logger.exception("xmi_class_detail failed")
        return JSONResponse({"error": str(e)}, status_code=500)


async def xmi_graph(request: Request):
    """GET /api/xmi/graph?module_id=X — ReactFlow graph for a module."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)
    module_id = request.query_params.get("module_id", "")
    if not module_id:
        return JSONResponse({"error": "module_id query param required"}, status_code=400)
    try:
        kg_dir = os.path.join(COMPILED_DIR, "kg")
        nodes_path = os.path.join(kg_dir, "domain_model_nodes.json")
        edges_path = os.path.join(kg_dir, "domain_model_edges.json")

        if not os.path.exists(nodes_path) or not os.path.exists(edges_path):
            return JSONResponse({"error": "KG artifacts not found — run compile first"}, status_code=404)

        with open(nodes_path, encoding="utf-8") as f:
            all_nodes = json.load(f)
        with open(edges_path, encoding="utf-8") as f:
            all_edges = json.load(f)

        # Filter nodes belonging to this module
        module_node = next((n for n in all_nodes if n["id"] == module_id and n["type"] == "module"), None)
        class_nodes = [n for n in all_nodes if n.get("module_id") == module_id and n["type"] == "class"]
        class_ids = {n["id"] for n in class_nodes}

        rf_nodes = []
        rf_edges = []

        # Module node centered above classes
        col_count = 4
        h_spacing = 280
        v_spacing = 200
        total_width = (min(len(class_nodes), col_count) - 1) * h_spacing
        module_x = total_width / 2 if class_nodes else 0

        if module_node:
            rf_nodes.append({
                "id": module_id,
                "type": "umlModule",
                "position": {"x": module_x, "y": 0},
                "data": {
                    "label": module_node.get("name", module_id),
                    "classCount": len(class_nodes),
                },
            })

        for idx, cn in enumerate(class_nodes):
            col = idx % col_count
            row = idx // col_count
            rf_nodes.append({
                "id": cn["id"],
                "type": "umlClass",
                "position": {"x": col * h_spacing, "y": (row + 1) * v_spacing},
                "data": {
                    "label": cn.get("name", cn["id"]),
                    "attributes": [],
                },
            })

        # Edges: inheritance and association between classes in this module
        for edge in all_edges:
            src = edge.get("source", "")
            tgt = edge.get("target", "")
            etype = edge.get("type", "")

            if etype == "inherits_from" and src in class_ids and tgt in class_ids:
                rf_edges.append({
                    "id": f"e-{src}-{tgt}-inherits",
                    "source": src,
                    "target": tgt,
                    "type": "inherits",
                    "animated": False,
                    "label": "inherits",
                })
            elif etype == "associates_with" and src in class_ids and tgt in class_ids:
                rf_edges.append({
                    "id": f"e-{src}-{tgt}-assoc",
                    "source": src,
                    "target": tgt,
                    "type": "associates",
                    "animated": False,
                    "label": edge.get("association_name", ""),
                })

        return JSONResponse({"nodes": rf_nodes, "edges": rf_edges})
    except Exception as e:
        logger.exception("xmi_graph failed")
        return JSONResponse({"error": str(e)}, status_code=500)


async def xmi_compile(request: Request):
    """POST /api/xmi/compile — compile XMI corpus from source_dir."""
    user = _get_user_from_request(request)
    if not user:
        return JSONResponse({"error": "Unauthorized"}, status_code=401)
    _set_user_context(user)
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Invalid JSON body"}, status_code=400)

    source_dir = body.get("source_dir", "")
    if not source_dir:
        return JSONResponse({"error": "source_dir required"}, status_code=400)
    if not os.path.isdir(source_dir):
        return JSONResponse({"error": f"source_dir not found: {source_dir}"}, status_code=400)

    try:
        from ..standards.xmi_compiler import compile_xmi_corpus
        result = compile_xmi_corpus(source_dir, COMPILED_DIR)
        return JSONResponse(result)
    except Exception as e:
        logger.exception("xmi_compile failed")
        return JSONResponse({"error": str(e)}, status_code=500)


def get_domain_standard_routes() -> list:
    return [
        Route("/api/xmi/status", endpoint=xmi_status, methods=["GET"]),
        Route("/api/xmi/modules", endpoint=xmi_modules, methods=["GET"]),
        Route("/api/xmi/classes", endpoint=xmi_classes, methods=["GET"]),
        Route("/api/xmi/class/{class_id:path}", endpoint=xmi_class_detail, methods=["GET"]),
        Route("/api/xmi/graph", endpoint=xmi_graph, methods=["GET"]),
        Route("/api/xmi/compile", endpoint=xmi_compile, methods=["POST"]),
    ]
