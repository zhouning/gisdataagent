"""
User-Defined Tools — DB-driven declarative tool templates (v1.0).

Users create custom tools via declarative templates (http_call, sql_query,
file_transform, chain) or Python sandbox (Phase 2). Tools are stored in
PostgreSQL and dynamically wrapped as ADK FunctionTool instances.

All DB operations are non-fatal (never raise to caller).
"""
import re
import json
from datetime import datetime
from typing import Optional

from sqlalchemy import text

from .db_engine import get_engine
from .database_tools import T_USER_TOOLS
from .user_context import current_user_id

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TOOL_NAME_MAX_LENGTH = 100
TOOL_NAME_PATTERN = re.compile(r'^[\w\u4e00-\u9fff\-]+$')
MAX_TOOLS_PER_USER = 50
VALID_PARAM_TYPES = {"string", "number", "integer", "boolean"}
VALID_TEMPLATE_TYPES = {"http_call", "sql_query", "file_transform", "chain", "python_sandbox"}
DESCRIPTION_MAX_LENGTH = 2000
MAX_PARAMETERS = 20
MAX_CHAIN_STEPS = 5

# SQL keywords forbidden in readonly sql_query templates
_SQL_DDL_KEYWORDS = {
    "DROP", "ALTER", "TRUNCATE", "CREATE", "GRANT", "REVOKE",
}
_SQL_DML_KEYWORDS = {"INSERT", "UPDATE", "DELETE"}
SQL_QUERY_MAX_LENGTH = 5000


# ---------------------------------------------------------------------------
# Table initialization
# ---------------------------------------------------------------------------

def ensure_user_tools_table():
    """Create user tools table if not exists. Called at startup."""
    engine = get_engine()
    if not engine:
        print("[UserTools] WARNING: Database not configured. User tools disabled.")
        return
    try:
        with engine.connect() as conn:
            conn.execute(text(f"""
                CREATE TABLE IF NOT EXISTS {T_USER_TOOLS} (
                    id SERIAL PRIMARY KEY,
                    owner_username VARCHAR(100) NOT NULL,
                    tool_name VARCHAR(100) NOT NULL,
                    description TEXT DEFAULT '',
                    parameters JSONB DEFAULT '[]',
                    template_type VARCHAR(30) NOT NULL,
                    template_config JSONB DEFAULT '{{}}',
                    python_code TEXT,
                    is_shared BOOLEAN DEFAULT FALSE,
                    enabled BOOLEAN DEFAULT TRUE,
                    timeout_seconds INTEGER DEFAULT 30,
                    created_at TIMESTAMP DEFAULT NOW(),
                    updated_at TIMESTAMP DEFAULT NOW(),
                    UNIQUE(owner_username, tool_name)
                )
            """))
            conn.execute(text(f"""
                CREATE INDEX IF NOT EXISTS idx_ut_owner
                ON {T_USER_TOOLS}(owner_username)
            """))
            conn.execute(text(f"""
                CREATE INDEX IF NOT EXISTS idx_ut_shared
                ON {T_USER_TOOLS}(is_shared) WHERE is_shared = TRUE
            """))
            conn.execute(text(f"""
                CREATE INDEX IF NOT EXISTS idx_ut_enabled
                ON {T_USER_TOOLS}(enabled) WHERE enabled = TRUE
            """))
            # v14.0: rating + clone columns
            for col in ("rating_sum INTEGER DEFAULT 0",
                        "rating_count INTEGER DEFAULT 0",
                        "clone_count INTEGER DEFAULT 0"):
                conn.execute(text(
                    f"ALTER TABLE {T_USER_TOOLS} ADD COLUMN IF NOT EXISTS {col}"
                ))
            # v14.1: version, tags, usage
            for col in ("version INTEGER DEFAULT 1",
                        "category VARCHAR(50) DEFAULT ''",
                        "tags TEXT[] DEFAULT '{}'::text[]",
                        "use_count INTEGER DEFAULT 0"):
                conn.execute(text(
                    f"ALTER TABLE {T_USER_TOOLS} ADD COLUMN IF NOT EXISTS {col}"
                ))
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS agent_tool_versions (
                    id SERIAL PRIMARY KEY,
                    tool_id INTEGER NOT NULL,
                    version INTEGER NOT NULL,
                    description TEXT DEFAULT '',
                    parameters JSONB DEFAULT '[]',
                    template_config JSONB DEFAULT '{}',
                    created_at TIMESTAMP DEFAULT NOW(),
                    UNIQUE(tool_id, version)
                )
            """))
            conn.commit()
    except Exception as e:
        print(f"[UserTools] Failed to ensure table: {e}")


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_tool_name(name: str) -> Optional[str]:
    """Validate tool name. Returns error message or None."""
    if not name or not name.strip():
        return "tool_name is required"
    if len(name) > TOOL_NAME_MAX_LENGTH:
        return f"tool_name exceeds {TOOL_NAME_MAX_LENGTH} characters"
    if not TOOL_NAME_PATTERN.match(name):
        return "tool_name must be alphanumeric, Chinese, or hyphen characters"
    return None


def validate_parameters(params: list) -> Optional[str]:
    """Validate parameter definitions. Returns error message or None."""
    if not isinstance(params, list):
        return "parameters must be a list"
    if len(params) > MAX_PARAMETERS:
        return f"too many parameters (max {MAX_PARAMETERS})"
    seen_names = set()
    for i, p in enumerate(params):
        if not isinstance(p, dict):
            return f"parameter[{i}] must be an object"
        name = p.get("name", "")
        if not name or not isinstance(name, str):
            return f"parameter[{i}].name is required"
        if not re.match(r'^[a-zA-Z_]\w*$', name):
            return f"parameter[{i}].name '{name}' must be a valid identifier"
        if name in seen_names:
            return f"duplicate parameter name: '{name}'"
        seen_names.add(name)
        ptype = p.get("type", "string")
        if ptype not in VALID_PARAM_TYPES:
            return f"parameter[{i}].type '{ptype}' invalid. Valid: {sorted(VALID_PARAM_TYPES)}"
        if "description" not in p:
            return f"parameter[{i}].description is required"
    return None


def validate_template_config(template_type: str, config: dict) -> Optional[str]:
    """Validate template config by type. Returns error message or None."""
    if template_type not in VALID_TEMPLATE_TYPES:
        return f"template_type '{template_type}' invalid. Valid: {sorted(VALID_TEMPLATE_TYPES)}"
    if not isinstance(config, dict):
        return "template_config must be an object"

    if template_type == "http_call":
        return _validate_http_call(config)
    elif template_type == "sql_query":
        return _validate_sql_query(config)
    elif template_type == "file_transform":
        return _validate_file_transform(config)
    elif template_type == "chain":
        return _validate_chain(config)
    elif template_type == "python_sandbox":
        return _validate_python_sandbox(config)
    return None


def _validate_http_call(config: dict) -> Optional[str]:
    method = (config.get("method") or "").upper()
    if method not in {"GET", "POST", "PUT", "DELETE", "PATCH"}:
        return "http_call.method must be GET/POST/PUT/DELETE/PATCH"
    url = config.get("url", "")
    if not url:
        return "http_call.url is required"
    if not url.startswith("https://"):
        return "http_call.url must start with https://"
    # Block SSRF: no localhost / private IPs
    import urllib.parse
    host = urllib.parse.urlparse(url).hostname or ""
    if host in ("localhost", "127.0.0.1", "0.0.0.0") or host.startswith("192.168.") or host.startswith("10."):
        return "http_call.url must not target localhost or private networks"
    if config.get("headers") and not isinstance(config["headers"], dict):
        return "http_call.headers must be an object"
    return None


def _validate_sql_query(config: dict) -> Optional[str]:
    query = config.get("query", "")
    if not query:
        return "sql_query.query is required"
    if len(query) > SQL_QUERY_MAX_LENGTH:
        return f"sql_query.query exceeds {SQL_QUERY_MAX_LENGTH} characters"
    upper = query.upper()
    for kw in _SQL_DDL_KEYWORDS:
        if kw in upper:
            return f"sql_query.query contains forbidden DDL keyword: {kw}"
    readonly = config.get("readonly", True)
    if readonly:
        for kw in _SQL_DML_KEYWORDS:
            if kw in upper:
                return f"sql_query.query contains DML keyword '{kw}' but readonly=true"
    return None


def _validate_file_transform(config: dict) -> Optional[str]:
    ops = config.get("operations")
    if not ops or not isinstance(ops, list):
        return "file_transform.operations must be a non-empty list"
    allowed_ops = {"filter", "reproject", "buffer", "dissolve", "clip", "select_columns", "rename_columns"}
    for i, op in enumerate(ops):
        if not isinstance(op, dict):
            return f"file_transform.operations[{i}] must be an object"
        op_name = op.get("op", "")
        if op_name not in allowed_ops:
            return f"file_transform.operations[{i}].op '{op_name}' invalid. Valid: {sorted(allowed_ops)}"
    return None


def _validate_chain(config: dict) -> Optional[str]:
    steps = config.get("steps")
    if not steps or not isinstance(steps, list):
        return "chain.steps must be a non-empty list"
    if len(steps) > MAX_CHAIN_STEPS:
        return f"chain.steps exceeds max {MAX_CHAIN_STEPS}"
    for i, step in enumerate(steps):
        if not isinstance(step, dict):
            return f"chain.steps[{i}] must be an object"
        if not step.get("tool_name"):
            return f"chain.steps[{i}].tool_name is required"
    return None


# ---------------------------------------------------------------------------
# Python sandbox validation (Phase 2)
# ---------------------------------------------------------------------------

_ALLOWED_IMPORTS = {
    "json", "math", "re", "datetime", "collections", "csv", "os.path",
    "statistics", "itertools", "functools", "string", "hashlib", "uuid",
    "decimal", "fractions", "operator", "copy", "textwrap",
}

_FORBIDDEN_NAMES = {
    "exec", "eval", "compile", "__import__", "globals", "locals",
    "getattr", "setattr", "delattr", "open", "input",
    "breakpoint", "exit", "quit",
}

_FORBIDDEN_ATTRS = {
    "__builtins__", "__class__", "__subclasses__", "__bases__",
    "__code__", "__globals__", "__dict__",
}

PYTHON_CODE_MAX_LENGTH = 5000


def validate_python_code(code: str) -> Optional[str]:
    """Validate user Python code via AST analysis. Returns error or None."""
    import ast

    if not code or not code.strip():
        return "python_code is required for python_sandbox"
    if len(code) > PYTHON_CODE_MAX_LENGTH:
        return f"python_code exceeds {PYTHON_CODE_MAX_LENGTH} characters"

    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return f"Python syntax error: {e}"

    # Walk AST to check for forbidden constructs
    for node in ast.walk(tree):
        # Forbidden function calls
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name) and func.id in _FORBIDDEN_NAMES:
                return f"Forbidden function: {func.id}()"
            if isinstance(func, ast.Attribute) and func.attr in _FORBIDDEN_NAMES:
                return f"Forbidden method: .{func.attr}()"

        # Forbidden attribute access
        if isinstance(node, ast.Attribute):
            if node.attr in _FORBIDDEN_ATTRS:
                return f"Forbidden attribute access: .{node.attr}"

        # Check imports
        if isinstance(node, ast.Import):
            for alias in node.names:
                mod_root = alias.name.split(".")[0]
                if mod_root not in _ALLOWED_IMPORTS and alias.name not in _ALLOWED_IMPORTS:
                    return f"Forbidden import: {alias.name}. Allowed: {sorted(_ALLOWED_IMPORTS)}"
        if isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            mod_root = mod.split(".")[0]
            if mod_root not in _ALLOWED_IMPORTS and mod not in _ALLOWED_IMPORTS:
                return f"Forbidden import from: {mod}. Allowed: {sorted(_ALLOWED_IMPORTS)}"

    # Must define a function named tool_function
    func_names = [n.name for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]
    if "tool_function" not in func_names:
        return "Code must define a function named 'tool_function'"

    return None


def _validate_python_sandbox(config: dict) -> Optional[str]:
    """Validate python_sandbox template config."""
    # Config is minimal for python_sandbox — the code is in python_code field
    return None


# ---------------------------------------------------------------------------
# CRUD operations
# ---------------------------------------------------------------------------

def create_user_tool(
    tool_name: str,
    description: str,
    parameters: list,
    template_type: str,
    template_config: dict,
    is_shared: bool = False,
    timeout_seconds: int = 30,
) -> Optional[int]:
    """Create a user tool. Returns tool id or None on failure."""
    engine = get_engine()
    if not engine:
        return None
    try:
        username = current_user_id.get()
        # Check per-user limit
        with engine.connect() as conn:
            count = conn.execute(text(f"""
                SELECT COUNT(*) FROM {T_USER_TOOLS}
                WHERE owner_username = :owner
            """), {"owner": username}).scalar()
            if count and count >= MAX_TOOLS_PER_USER:
                print(f"[UserTools] User {username} reached tool limit ({MAX_TOOLS_PER_USER})")
                return None

            row = conn.execute(text(f"""
                INSERT INTO {T_USER_TOOLS}
                    (owner_username, tool_name, description, parameters,
                     template_type, template_config, is_shared, timeout_seconds)
                VALUES (:owner, :name, :desc, :params,
                        :ttype, :tconfig, :shared, :timeout)
                RETURNING id
            """), {
                "owner": username,
                "name": tool_name,
                "desc": description or "",
                "params": json.dumps(parameters, ensure_ascii=False),
                "ttype": template_type,
                "tconfig": json.dumps(template_config, ensure_ascii=False),
                "shared": is_shared,
                "timeout": min(max(timeout_seconds, 5), 60),
            }).fetchone()
            conn.commit()
            return row[0] if row else None
    except Exception as e:
        print(f"[UserTools] Failed to create: {e}")
        return None


def list_user_tools(include_shared: bool = True) -> list[dict]:
    """List tools owned by current user + optionally shared tools."""
    engine = get_engine()
    if not engine:
        return []
    try:
        username = current_user_id.get()
        if include_shared:
            sql = f"""
                SELECT id, owner_username, tool_name, description, parameters,
                       template_type, template_config, python_code,
                       is_shared, enabled, timeout_seconds, created_at, updated_at,
                       rating_sum, rating_count, clone_count,
                       version, category, tags, use_count
                FROM {T_USER_TOOLS}
                WHERE (owner_username = :owner OR is_shared = TRUE)
                  AND enabled = TRUE
                ORDER BY created_at DESC
            """
        else:
            sql = f"""
                SELECT id, owner_username, tool_name, description, parameters,
                       template_type, template_config, python_code,
                       is_shared, enabled, timeout_seconds, created_at, updated_at,
                       rating_sum, rating_count, clone_count,
                       version, category, tags, use_count
                FROM {T_USER_TOOLS}
                WHERE owner_username = :owner
                ORDER BY created_at DESC
            """
        with engine.connect() as conn:
            rows = conn.execute(text(sql), {"owner": username}).fetchall()
        return [_row_to_dict(r) for r in rows]
    except Exception as e:
        print(f"[UserTools] Failed to list: {e}")
        return []


def get_user_tool(tool_id: int) -> Optional[dict]:
    """Get a single tool by id. Returns None if not found or not accessible."""
    engine = get_engine()
    if not engine:
        return None
    try:
        username = current_user_id.get()
        with engine.connect() as conn:
            row = conn.execute(text(f"""
                SELECT id, owner_username, tool_name, description, parameters,
                       template_type, template_config, python_code,
                       is_shared, enabled, timeout_seconds, created_at, updated_at,
                       rating_sum, rating_count, clone_count,
                       version, category, tags, use_count
                FROM {T_USER_TOOLS}
                WHERE id = :id AND (owner_username = :owner OR is_shared = TRUE)
            """), {"id": tool_id, "owner": username}).fetchone()
        return _row_to_dict(row) if row else None
    except Exception as e:
        print(f"[UserTools] Failed to get: {e}")
        return None


def update_user_tool(tool_id: int, **fields) -> bool:
    """Update specified fields of a tool. Owner-only."""
    engine = get_engine()
    if not engine:
        return False

    allowed = {
        "tool_name", "description", "parameters", "template_type",
        "template_config", "is_shared", "enabled", "timeout_seconds",
    }
    updates = {k: v for k, v in fields.items() if k in allowed}
    if not updates:
        return False

    # JSON-encode JSONB fields
    if "parameters" in updates:
        updates["parameters"] = json.dumps(updates["parameters"], ensure_ascii=False)
    if "template_config" in updates:
        updates["template_config"] = json.dumps(updates["template_config"], ensure_ascii=False)

    try:
        username = current_user_id.get()
        set_clauses = ", ".join(f"{k} = :{k}" for k in updates)
        set_clauses += ", updated_at = NOW()"
        updates["id"] = tool_id
        updates["owner"] = username
        with engine.connect() as conn:
            result = conn.execute(text(f"""
                UPDATE {T_USER_TOOLS}
                SET {set_clauses}
                WHERE id = :id AND owner_username = :owner
            """), updates)
            conn.commit()
            return result.rowcount > 0
    except Exception as e:
        print(f"[UserTools] Failed to update: {e}")
        return False


def delete_user_tool(tool_id: int) -> bool:
    """Delete a tool. Owner-only."""
    engine = get_engine()
    if not engine:
        return False
    try:
        username = current_user_id.get()
        with engine.connect() as conn:
            result = conn.execute(text(f"""
                DELETE FROM {T_USER_TOOLS}
                WHERE id = :id AND owner_username = :owner
            """), {"id": tool_id, "owner": username})
            conn.commit()
            return result.rowcount > 0
    except Exception as e:
        print(f"[UserTools] Failed to delete: {e}")
        return False


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _row_to_dict(row) -> dict:
    """Convert a SQLAlchemy row to a dict."""
    if row is None:
        return {}
    params = row[4]
    if isinstance(params, str):
        params = json.loads(params)
    tconfig = row[6]
    if isinstance(tconfig, str):
        tconfig = json.loads(tconfig)
    return {
        "id": row[0],
        "owner_username": row[1],
        "tool_name": row[2],
        "description": row[3],
        "parameters": params if isinstance(params, list) else [],
        "template_type": row[5],
        "template_config": tconfig if isinstance(tconfig, dict) else {},
        "python_code": row[7],
        "is_shared": row[8],
        "enabled": row[9],
        "timeout_seconds": row[10],
        "created_at": row[11].isoformat() if isinstance(row[11], datetime) else str(row[11]),
        "updated_at": row[12].isoformat() if isinstance(row[12], datetime) else str(row[12]),
        "rating_sum": row[13] if len(row) > 13 else 0,
        "rating_count": row[14] if len(row) > 14 else 0,
        "clone_count": row[15] if len(row) > 15 else 0,
        "version": row[16] if len(row) > 16 else 1,
        "category": row[17] if len(row) > 17 else "",
        "tags": list(row[18]) if len(row) > 18 and row[18] else [],
        "use_count": row[19] if len(row) > 19 else 0,
    }


# ---------------------------------------------------------------------------
# Version Management & Usage Tracking (v14.1)
# ---------------------------------------------------------------------------

def increment_tool_use_count(tool_id: int):
    """Increment the use_count for a tool (called on each invocation)."""
    engine = get_engine()
    if not engine:
        return
    try:
        with engine.connect() as conn:
            conn.execute(text(
                f"UPDATE {T_USER_TOOLS} SET use_count = COALESCE(use_count, 0) + 1 WHERE id = :id"
            ), {"id": tool_id})
            conn.commit()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Rating & Clone (v14.0)
# ---------------------------------------------------------------------------

def rate_tool(tool_id: int, score: int) -> bool:
    """Rate a shared user tool (1-5). Adds to running average."""
    if score < 1 or score > 5:
        return False
    engine = get_engine()
    if not engine:
        return False
    try:
        with engine.connect() as conn:
            result = conn.execute(text(
                f"UPDATE {T_USER_TOOLS} "
                f"SET rating_sum = COALESCE(rating_sum, 0) + :score, "
                f"rating_count = COALESCE(rating_count, 0) + 1 "
                f"WHERE id = :id AND is_shared = TRUE"
            ), {"id": tool_id, "score": score})
            conn.commit()
        return result.rowcount > 0
    except Exception:
        return False


def clone_tool(tool_id: int, new_owner: str, new_name: str = None) -> Optional[int]:
    """Clone a shared user tool to a new owner. Returns new tool ID or None."""
    source = get_user_tool(tool_id)
    if not source or not source.get("is_shared"):
        return None
    name = new_name or f"{source['tool_name']}_copy"
    new_id = create_user_tool(
        tool_name=name,
        description=source.get("description", ""),
        parameters=source.get("parameters", []),
        template_type=source["template_type"],
        template_config=source.get("template_config", {}),
        is_shared=False,
    )
    if new_id is not None:
        engine = get_engine()
        if engine:
            try:
                with engine.connect() as conn:
                    conn.execute(text(
                        f"UPDATE {T_USER_TOOLS} SET clone_count = COALESCE(clone_count, 0) + 1 "
                        f"WHERE id = :id"
                    ), {"id": tool_id})
                    conn.commit()
            except Exception:
                pass
    return new_id
