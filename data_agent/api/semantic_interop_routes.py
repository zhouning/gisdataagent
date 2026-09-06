"""Authenticated UI endpoints for standards-based ontology/semantic exchange.

The runtime JSON artifacts remain the execution authority.  Uploads are staged
as non-executable drafts; this endpoint never replaces a published artifact or
grants query execution authority to an external document.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import secrets
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from ..abu_dhabi_artifact_registry import (
    current_artifact_manifest,
    current_artifact_path,
    registered_source_keys,
)
from ..semantic_interop import (
    InteropError,
    export_ontology_to_jsonld,
    export_ontology_to_turtle,
    export_semantic_layer_to_jsonld,
    export_semantic_layer_to_ossie_yaml,
    export_semantic_layer_to_turtle,
    export_semantic_layer_to_yaml,
    import_ontology_from_jsonld,
    import_ontology_from_turtle,
    import_semantic_layer_from_jsonld,
    import_semantic_layer_from_ossie_yaml,
    import_semantic_layer_from_turtle,
)
from .helpers import _get_user_from_request, _set_user_context

_ROOT = Path(__file__).resolve().parents[2]
_IMPORT_ROOT = Path(
    os.environ.get(
        "GDA_SEMANTIC_INTEROP_IMPORT_ROOT",
        str(_ROOT / ".files" / "semantic_interop_imports"),
    )
)
_KIND_VALUES = {"ontology", "semantic-layer"}
_FORMAT_VALUES = {"turtle", "json-ld", "ossie-yaml", "yaml", "json"}


def _available_sources() -> list[dict[str, Any]]:
    """Return source scopes with a checksum-verified current artifact bundle."""
    result: list[dict[str, Any]] = []
    for scope in registered_source_keys():
        try:
            manifest = current_artifact_manifest(scope)
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        source = manifest.get("source") or {}
        database_name = str(source.get("database_name") or scope)
        label = {
            "liveability": "Liveability",
            "makani": "Makani",
        }.get(scope, database_name)
        result.append({
            "key": scope,
            "label": label,
            "source_id": source.get("source_id"),
            "database_name": database_name,
            "bundle_id": manifest.get("bundle_id"),
        })
    return result


def _auth(request: Request):
    user = _get_user_from_request(request)
    if not user:
        return None, JSONResponse({"error": "Unauthorized"}, status_code=401)
    username, role = _set_user_context(user)
    return (username, role), None


def _can_import(role: str | None, kind: str) -> bool:
    allowed = {"admin", "standard_editor"} if kind == "ontology" else {"admin", "analyst"}
    return str(role or "").casefold() in allowed


def _source_scope(value: str) -> str:
    value = str(value or "").strip().casefold()
    if value not in set(registered_source_keys()):
        raise ValueError("source is not registered in the current artifact registry")
    return value


def _kind(value: str) -> str:
    value = str(value or "").strip().casefold()
    if value not in _KIND_VALUES:
        raise ValueError("kind must be ontology or semantic-layer")
    return value


def _format(value: str) -> str:
    value = str(value or "").strip().casefold()
    if value not in _FORMAT_VALUES:
        raise ValueError("unsupported interchange format")
    return value


def _artifact(scope: str, kind: str) -> Path:
    role = "ontology" if kind == "ontology" else "semantic"
    return current_artifact_path(scope, role)


def _media_and_suffix(fmt: str) -> tuple[str, str]:
    return {
        "turtle": ("text/turtle; charset=utf-8", "ttl"),
        "json-ld": ("application/ld+json; charset=utf-8", "jsonld"),
        "ossie-yaml": ("application/yaml; charset=utf-8", "ossie.yaml"),
        "yaml": ("application/yaml; charset=utf-8", "yaml"),
        "json": ("application/json; charset=utf-8", "json"),
    }[fmt]


def _export(source: Path, kind: str, fmt: str) -> str:
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise InteropError("published runtime artifact is not valid JSON") from exc
    if not isinstance(payload, dict):
        raise InteropError("published runtime artifact must be a JSON object")
    expected_schema = (
        "gda.ontology-runtime-overlay.v1"
        if kind == "ontology"
        else "gda.multilingual-virtual-semantic-layer.v1"
    )
    if payload.get("schema") != expected_schema:
        raise InteropError(f"published runtime artifact schema is invalid for {kind}")
    if kind == "ontology":
        if fmt == "turtle":
            return export_ontology_to_turtle(payload)
        if fmt == "json-ld":
            return export_ontology_to_jsonld(payload)
        if fmt == "json":
            return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
        raise ValueError("ontology supports turtle, json-ld and json export")
    if fmt == "turtle":
        return export_semantic_layer_to_turtle(payload)
    if fmt == "json-ld":
        return export_semantic_layer_to_jsonld(payload)
    if fmt == "ossie-yaml":
        return export_semantic_layer_to_ossie_yaml(payload)
    if fmt == "yaml":
        return export_semantic_layer_to_yaml(payload)
    if fmt == "json":
        return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    raise ValueError("unsupported semantic-layer export format")


async def standards_export(request: Request):
    _, error = _auth(request)
    if error:
        return error
    try:
        scope = _source_scope(request.path_params.get("source"))
        kind = _kind(request.path_params.get("kind"))
        fmt = _format(request.path_params.get("format"))
        if kind == "ontology" and fmt not in {"turtle", "json-ld", "json"}:
            raise ValueError("ontology supports turtle, json-ld and json export")
        source = _artifact(scope, kind)
        content = await asyncio.to_thread(_export, source, kind, fmt)
        media_type, suffix = _media_and_suffix(fmt)
        filename = f"{scope}-{kind}.{suffix}"
        return Response(
            content=content,
            media_type=media_type,
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
                "X-GDA-Source": scope,
                "X-GDA-Interop-Mode": "standards-projection",
            },
        )
    except (OSError, ValueError, InteropError) as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    except Exception:
        return JSONResponse({"error": "standards export unavailable"}, status_code=503)


async def interop_sources(request: Request):
    """GET /api/semantic/interop/sources — source catalog for interchange UI."""
    _, error = _auth(request)
    if error:
        return error
    return JSONResponse({"items": _available_sources()})


def _parse_import_payload(raw: str, kind: str, fmt: str, mode: str) -> dict[str, Any]:
    if kind == "ontology":
        if fmt == "turtle":
            return import_ontology_from_turtle(raw, mode=mode)
        if fmt == "json-ld":
            return import_ontology_from_jsonld(raw, mode=mode)
        if fmt == "json":
            payload = json.loads(raw)
            if not isinstance(payload, dict):
                raise InteropError("runtime JSON must be an object")
            if payload.get("schema") != "gda.ontology-runtime-overlay.v1":
                raise InteropError("ontology runtime JSON schema is invalid")
            return payload
        raise InteropError("ontology import supports turtle, json-ld and json")
    if fmt == "ossie-yaml":
        return import_semantic_layer_from_ossie_yaml(raw, mode=mode)
    if fmt == "turtle":
        return import_semantic_layer_from_turtle(raw, mode=mode)
    if fmt == "json-ld":
        return import_semantic_layer_from_jsonld(raw, mode=mode)
    if fmt == "yaml":
        payload = yaml.safe_load(raw)
        if not isinstance(payload, dict):
            raise InteropError("runtime YAML must be an object")
        if payload.get("schema") != "gda.multilingual-virtual-semantic-layer.v1":
            raise InteropError("semantic-layer runtime YAML schema is invalid")
        return payload
    if fmt == "json":
        payload = json.loads(raw)
        if not isinstance(payload, dict):
            raise InteropError("runtime JSON must be an object")
        if payload.get("schema") != "gda.multilingual-virtual-semantic-layer.v1":
            raise InteropError("semantic-layer runtime JSON schema is invalid")
        return payload
    raise InteropError("unsupported import format")


def _demote_import_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Ensure staged imports can never retain production execution authority."""
    result = json.loads(json.dumps(payload, ensure_ascii=False))
    runtime_role = result.setdefault("runtime_role", {})
    if isinstance(runtime_role, dict):
        runtime_role["execution_authority"] = False
        runtime_role["activation_status"] = "staged_non_executable"
    for key in ("semantic_assets", "concepts"):
        items = result.get(key)
        if not isinstance(items, list):
            continue
        for item in items:
            if isinstance(item, dict):
                item["execution_eligible"] = False
                item["retrieval_eligible"] = False
                item["review_status"] = "imported_projection"
    result["status"] = "projection_only_import_requires_review"
    return result


def _import_payload(raw: str, kind: str, fmt: str, mode: str) -> dict[str, Any]:
    return _demote_import_payload(_parse_import_payload(raw, kind, fmt, mode))


def _validate_source_binding(payload: dict[str, Any], scope: str | None) -> None:
    """Reject a runtime document explicitly bound to a different published source."""
    if not scope:
        return
    binding = payload.get("source_binding") or payload.get("source_evidence") or {}
    if not isinstance(binding, dict):
        raise InteropError("source binding must be an object")
    if not binding:
        return
    manifest = current_artifact_manifest(scope)
    expected = manifest.get("source") or {}
    expected_db = str(expected.get("database_name") or "")
    actual_db = str(binding.get("database_name") or "")
    if expected_db and actual_db and expected_db != actual_db:
        raise InteropError(
            "source binding mismatch: "
            f"document targets {actual_db!r}, selected source is {expected_db!r}"
        )
    for key in ("discovery_fingerprint", "profile_fingerprint"):
        actual = str(binding.get(key) or "")
        current = str(expected.get(key) or "")
        if actual and current and actual != current:
            raise InteropError(f"source {key} does not match the current published artifact")


def _summary(payload: dict[str, Any], kind: str) -> dict[str, Any]:
    if kind == "ontology":
        concepts = payload.get("concepts") or []
        return {
            "concept_count": len(concepts),
            "relation_count": len(payload.get("relations") or payload.get("relationships") or []),
        }
    assets = payload.get("semantic_assets") or []
    return {
        "dataset_count": len(assets),
        "table_binding_count": len(payload.get("table_bindings") or []),
        "field_count": sum(
            len(item.get("fields") or []) for item in assets if isinstance(item, dict)
        ),
        "relationship_count": len(payload.get("relationships") or payload.get("relations") or []),
        "metric_count": len(payload.get("metric_contracts") or []),
    }


async def standards_import(request: Request):
    auth, error = _auth(request)
    if error:
        return error
    username, role = auth
    try:
        form = await request.form()
        kind = _kind(form.get("kind"))
        if not _can_import(role, kind):
            return JSONResponse(
                {"error": "semantic standards import requires the object editor role"},
                status_code=403,
            )
        fmt = _format(form.get("format"))
        scope = str(form.get("source") or "").strip().casefold() or None
        if scope is not None:
            scope = _source_scope(scope)
        mode = str(form.get("mode") or "projection-only").strip().casefold()
        if mode not in {"strict", "lossless-extension", "projection-only"}:
            raise ValueError("mode must be strict, lossless-extension or projection-only")
        upload = form.get("file")
        if upload is None or not hasattr(upload, "read"):
            raise ValueError("file is required")
        data = await upload.read()
        if len(data) > 150 * 1024 * 1024:
            raise ValueError("import file exceeds 150 MiB limit")
        raw = data.decode("utf-8")
        payload = await asyncio.to_thread(_import_payload, raw, kind, fmt, mode)
        _validate_source_binding(payload, scope)
        # Every UI import is a staged draft, even if the uploaded document has
        # a GDA extension. Activation still requires source binding, review and
        # publication through the semantic/ontology governance workflows.
        stage_id = f"{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}-{secrets.token_hex(6)}"
        _IMPORT_ROOT.mkdir(parents=True, exist_ok=True)
        runtime_path = _IMPORT_ROOT / f"{stage_id}.{kind.replace('-', '_')}.json"
        manifest_path = _IMPORT_ROOT / f"{stage_id}.manifest.json"
        runtime_path.write_text(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
        try:
            runtime_reference = str(runtime_path.relative_to(_ROOT))
        except ValueError:
            # Tests and isolated deployments may intentionally use a temporary
            # staging root outside the repository; do not leak that path.
            runtime_reference = runtime_path.name
        manifest = {
            "schema": "gda.semantic-interop-import-draft.v1",
            "stage_id": stage_id,
            "kind": kind,
            "source": scope,
            "format": fmt,
            "mode": mode,
            "status": "staged_non_executable",
            "execution_authority": False,
            "received_sha256": hashlib.sha256(data).hexdigest(),
            "runtime_sha256": hashlib.sha256(runtime_path.read_bytes()).hexdigest(),
            "created_at": datetime.now(UTC).isoformat(),
            "created_by": username,
            "summary": _summary(payload, kind),
            "runtime_path": runtime_reference,
        }
        manifest_path.write_text(
            json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
        return JSONResponse({"status": "staged_non_executable", "stage": manifest}, status_code=201)
    except (
        UnicodeDecodeError,
        OSError,
        ValueError,
        InteropError,
        yaml.YAMLError,
        json.JSONDecodeError,
    ) as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    except Exception:
        return JSONResponse({"error": "standards import unavailable"}, status_code=503)


async def staged_imports(request: Request):
    auth, error = _auth(request)
    if error:
        return error
    username, role = auth
    if not _IMPORT_ROOT.exists():
        return JSONResponse({"items": []})
    items = []
    for path in sorted(_IMPORT_ROOT.glob("*.manifest.json"), reverse=True)[:100]:
        try:
            item = json.loads(path.read_text(encoding="utf-8"))
            if item.get("created_by") == username or str(role).casefold() == "admin":
                items.append(item)
        except (OSError, ValueError):
            continue
    return JSONResponse({"items": items})


def get_semantic_interop_routes() -> list[Route]:
    return [
        Route("/api/semantic/interop/sources", interop_sources, methods=["GET"]),
        Route(
            "/api/semantic/interop/export/{kind}/{source}/{format}",
            standards_export,
            methods=["GET"],
        ),
        Route("/api/semantic/interop/import", standards_import, methods=["POST"]),
        Route("/api/semantic/interop/imports", staged_imports, methods=["GET"]),
    ]


__all__ = ["get_semantic_interop_routes"]
