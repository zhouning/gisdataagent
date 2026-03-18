"""
User Tool Engines — execution backends for declarative tool templates.

Each engine takes (config, params) and returns a string result.
`build_function_tool()` dynamically wraps a tool definition as an ADK FunctionTool.
"""
import inspect
import json
import logging
from typing import Optional

from google.adk.tools import FunctionTool

log = logging.getLogger("data_agent.user_tool_engines")

# ---------------------------------------------------------------------------
# Type mapping for dynamic signatures
# ---------------------------------------------------------------------------

_TYPE_MAP = {"string": str, "number": float, "integer": int, "boolean": bool}

# ---------------------------------------------------------------------------
# HTTP Call Engine
# ---------------------------------------------------------------------------

_HTTP_RESPONSE_MAX = 1024 * 1024  # 1 MB
_HTTP_TIMEOUT = 10  # seconds


def execute_http_call(config: dict, params: dict) -> str:
    """Execute an HTTP call template. Returns response text or error."""
    import httpx

    method = (config.get("method") or "GET").upper()
    url_template = config.get("url", "")
    headers = config.get("headers") or {}
    body_template = config.get("body_template", "")
    extract_path = config.get("extract_path", "")

    # Interpolate params into URL and body
    try:
        url = url_template.format_map(params)
    except (KeyError, ValueError) as e:
        return json.dumps({"status": "error", "message": f"URL template error: {e}"}, ensure_ascii=False)

    body = None
    if body_template:
        try:
            body = body_template.format_map(params)
        except (KeyError, ValueError) as e:
            return json.dumps({"status": "error", "message": f"Body template error: {e}"}, ensure_ascii=False)

    try:
        with httpx.Client(timeout=_HTTP_TIMEOUT) as client:
            if method in ("POST", "PUT", "PATCH") and body:
                resp = client.request(method, url, headers=headers, content=body,
                                      headers_extra={"Content-Type": "application/json"})
            else:
                resp = client.request(method, url, headers=headers, params=params if method == "GET" else None)

            resp.raise_for_status()
            text_body = resp.text[:_HTTP_RESPONSE_MAX]

            # Extract nested path if specified
            if extract_path:
                data = resp.json()
                for key in extract_path.split("."):
                    if isinstance(data, dict):
                        data = data.get(key)
                    elif isinstance(data, list) and key.isdigit():
                        data = data[int(key)]
                    else:
                        break
                return json.dumps({"status": "success", "data": data}, ensure_ascii=False, default=str)

            return json.dumps({"status": "success", "data": text_body}, ensure_ascii=False)
    except httpx.TimeoutException:
        return json.dumps({"status": "error", "message": "HTTP request timed out"}, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"status": "error", "message": str(e)}, ensure_ascii=False)


# ---------------------------------------------------------------------------
# SQL Query Engine
# ---------------------------------------------------------------------------

def execute_sql_query(config: dict, params: dict) -> str:
    """Execute a parameterized SQL query. Returns JSON result."""
    from sqlalchemy import text as sa_text
    from .db_engine import get_engine
    from .user_context import current_user_id, current_user_role

    query = config.get("query", "")
    readonly = config.get("readonly", True)

    engine = get_engine()
    if not engine:
        return json.dumps({"status": "error", "message": "Database not configured"}, ensure_ascii=False)

    try:
        with engine.connect() as conn:
            # Inject user context for RLS
            uid = current_user_id.get()
            role = current_user_role.get()
            if uid and uid != "anonymous":
                conn.execute(sa_text("SELECT set_config('app.current_user', :uid, true)"), {"uid": uid})
                conn.execute(sa_text("SELECT set_config('app.current_user_role', :role, true)"), {"role": role})

            if readonly:
                conn.execute(sa_text("SET TRANSACTION READ ONLY"))

            result = conn.execute(sa_text(query), params)

            if result.returns_rows:
                columns = list(result.keys())
                rows = [dict(zip(columns, row)) for row in result.fetchmany(500)]
                return json.dumps({
                    "status": "success",
                    "columns": columns,
                    "row_count": len(rows),
                    "data": rows,
                }, ensure_ascii=False, default=str)
            else:
                conn.commit()
                return json.dumps({
                    "status": "success",
                    "message": f"Query executed, {result.rowcount} rows affected",
                }, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"status": "error", "message": str(e)}, ensure_ascii=False)


# ---------------------------------------------------------------------------
# File Transform Engine
# ---------------------------------------------------------------------------

def execute_file_transform(config: dict, params: dict) -> str:
    """Execute a file transform pipeline. Returns output path."""
    import geopandas as gpd
    import pandas as pd
    from .gis_processors import _resolve_path, _generate_output_path

    file_path = params.get("file_path", "")
    if not file_path:
        return json.dumps({"status": "error", "message": "file_path parameter required"}, ensure_ascii=False)

    resolved = _resolve_path(file_path)
    operations = config.get("operations", [])
    output_format = config.get("output_format", "geojson")

    try:
        # Load data
        ext = resolved.rsplit(".", 1)[-1].lower() if "." in resolved else ""
        if ext in ("shp", "geojson", "gpkg"):
            gdf = gpd.read_file(resolved)
        elif ext in ("csv", "xlsx", "xls"):
            gdf = pd.read_csv(resolved) if ext == "csv" else pd.read_excel(resolved)
        else:
            gdf = gpd.read_file(resolved)

        # Apply operations
        for op in operations:
            op_name = op.get("op", "")
            if op_name == "filter":
                col = op.get("column", "")
                cond = op.get("condition", "==")
                val = op.get("value")
                if col and col in gdf.columns:
                    if cond == ">":
                        gdf = gdf[gdf[col] > float(val)]
                    elif cond == "<":
                        gdf = gdf[gdf[col] < float(val)]
                    elif cond == ">=":
                        gdf = gdf[gdf[col] >= float(val)]
                    elif cond == "<=":
                        gdf = gdf[gdf[col] <= float(val)]
                    elif cond == "!=":
                        gdf = gdf[gdf[col] != val]
                    else:
                        gdf = gdf[gdf[col] == val]
            elif op_name == "reproject":
                target_crs = op.get("target_crs", "EPSG:4326")
                if hasattr(gdf, "to_crs"):
                    gdf = gdf.to_crs(target_crs)
            elif op_name == "buffer":
                distance = float(op.get("distance", 0))
                if hasattr(gdf, "geometry"):
                    gdf = gdf.copy()
                    gdf["geometry"] = gdf.geometry.buffer(distance)
            elif op_name == "dissolve":
                by = op.get("by")
                if hasattr(gdf, "dissolve"):
                    gdf = gdf.dissolve(by=by) if by else gdf.dissolve()
            elif op_name == "clip":
                clip_path = _resolve_path(op.get("clip_path", ""))
                if clip_path and hasattr(gdf, "clip"):
                    mask = gpd.read_file(clip_path)
                    gdf = gpd.clip(gdf, mask)
            elif op_name == "select_columns":
                cols = op.get("columns", [])
                keep = [c for c in cols if c in gdf.columns]
                if hasattr(gdf, "geometry") and "geometry" in gdf.columns:
                    keep = list(dict.fromkeys(keep + ["geometry"]))
                gdf = gdf[keep]
            elif op_name == "rename_columns":
                mapping = op.get("mapping", {})
                gdf = gdf.rename(columns=mapping)

        # Write output
        out_path = _generate_output_path("user_tool", output_format)
        if output_format == "csv":
            if hasattr(gdf, "to_csv"):
                gdf.to_csv(out_path, index=False)
            else:
                gdf.to_csv(out_path, index=False)
        elif output_format in ("geojson", "gpkg", "shp"):
            gdf.to_file(out_path, driver={
                "geojson": "GeoJSON", "gpkg": "GPKG", "shp": "ESRI Shapefile",
            }.get(output_format, "GeoJSON"))
        else:
            gdf.to_file(out_path)

        return json.dumps({
            "status": "success",
            "path": out_path,
            "row_count": len(gdf),
        }, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"status": "error", "message": str(e)}, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Chain Engine
# ---------------------------------------------------------------------------

def execute_chain(config: dict, params: dict, tool_lookup: dict) -> str:
    """Execute a chain of tool steps sequentially."""
    steps = config.get("steps", [])
    prev_result = None

    for i, step in enumerate(steps):
        tool_name = step.get("tool_name", "")
        param_map = step.get("param_map", {})

        # Resolve param_map: $input.X → from original params, $prev.X → from previous result
        resolved_params = {}
        for k, v in param_map.items():
            if isinstance(v, str) and v.startswith("$input."):
                key = v[len("$input."):]
                resolved_params[k] = params.get(key, "")
            elif isinstance(v, str) and v.startswith("$prev."):
                key = v[len("$prev."):]
                if isinstance(prev_result, dict):
                    resolved_params[k] = prev_result.get(key, "")
                else:
                    resolved_params[k] = str(prev_result) if prev_result else ""
            else:
                resolved_params[k] = v

        # Look up and execute the referenced tool
        tool_def = tool_lookup.get(tool_name)
        if not tool_def:
            return json.dumps({
                "status": "error",
                "message": f"chain step[{i}]: tool '{tool_name}' not found",
            }, ensure_ascii=False)

        result_str = _dispatch_engine(tool_def, resolved_params)
        try:
            prev_result = json.loads(result_str)
        except (json.JSONDecodeError, TypeError):
            prev_result = {"result": result_str}

    return json.dumps(prev_result, ensure_ascii=False, default=str) if prev_result else "{}"


# ---------------------------------------------------------------------------
# Engine dispatcher
# ---------------------------------------------------------------------------

def _dispatch_engine(tool_def: dict, params: dict) -> str:
    """Dispatch to the appropriate engine based on template_type."""
    ttype = tool_def.get("template_type", "")
    config = tool_def.get("template_config", {})

    if ttype == "http_call":
        return execute_http_call(config, params)
    elif ttype == "sql_query":
        return execute_sql_query(config, params)
    elif ttype == "file_transform":
        return execute_file_transform(config, params)
    elif ttype == "chain":
        # Build tool lookup for chain resolution
        from .user_tools import list_user_tools
        all_tools = list_user_tools(include_shared=True)
        lookup = {t["tool_name"]: t for t in all_tools}
        return execute_chain(config, params, lookup)
    else:
        return json.dumps({"status": "error", "message": f"Unknown template_type: {ttype}"}, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Dynamic FunctionTool builder
# ---------------------------------------------------------------------------

def build_function_tool(tool_def: dict) -> Optional[FunctionTool]:
    """Build an ADK FunctionTool from a user tool definition.

    Dynamically constructs a callable with the correct __name__, __doc__,
    __annotations__, and __signature__ so ADK can extract parameter schemas.
    """
    try:
        tool_name = tool_def["tool_name"]
        description = tool_def.get("description", "")
        params_def = tool_def.get("parameters", [])

        # Build annotations
        annotations = {}
        for p in params_def:
            annotations[p["name"]] = _TYPE_MAP.get(p.get("type", "string"), str)
        annotations["return"] = str

        # Capture tool_def in closure
        _tool_def = tool_def

        def _executor(**kwargs) -> str:
            return _dispatch_engine(_tool_def, kwargs)

        # Set function metadata for ADK introspection
        _executor.__name__ = tool_name
        _executor.__qualname__ = tool_name
        # Build docstring with Args section for ADK
        doc_lines = [description or tool_name]
        if params_def:
            doc_lines.append("")
            doc_lines.append("Args:")
            for p in params_def:
                req = " (required)" if p.get("required", True) else ""
                default = f" Default: {p['default']}" if "default" in p else ""
                doc_lines.append(f"    {p['name']}: {p.get('description', '')}{req}{default}")
        _executor.__doc__ = "\n".join(doc_lines)
        _executor.__annotations__ = annotations

        # Build parameter signature dynamically
        sig_params = []
        for p in params_def:
            default = p.get("default", inspect.Parameter.empty)
            if not p.get("required", True) and default is inspect.Parameter.empty:
                default = None
            sig_params.append(inspect.Parameter(
                p["name"],
                inspect.Parameter.KEYWORD_ONLY,
                default=default,
                annotation=_TYPE_MAP.get(p.get("type", "string"), str),
            ))
        _executor.__signature__ = inspect.Signature(sig_params, return_annotation=str)

        return FunctionTool(_executor)
    except Exception as e:
        log.warning(f"[UserTools] Failed to build FunctionTool for '{tool_def.get('tool_name', '?')}': {e}")
        return None
