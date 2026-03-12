import os
import re
import uuid
import pandas as pd
import geopandas as gpd
from sqlalchemy import text
from .db_engine import get_engine
from .gis_processors import _generate_output_path, _resolve_path
from .user_context import current_user_id, current_user_role

import urllib.parse

# --- System table name constants (prefixed to avoid collisions in shared DB) ---
TABLE_PREFIX = "agent_"
T_APP_USERS = f"{TABLE_PREFIX}app_users"
T_USER_MEMORIES = f"{TABLE_PREFIX}user_memories"
T_TOKEN_USAGE = f"{TABLE_PREFIX}token_usage"
T_TABLE_OWNERSHIP = f"{TABLE_PREFIX}table_ownership"
T_SHARE_LINKS = f"{TABLE_PREFIX}share_links"
T_AUDIT_LOG = f"{TABLE_PREFIX}audit_log"
T_ANALYSIS_TEMPLATES = f"{TABLE_PREFIX}analysis_templates"
T_SEMANTIC_REGISTRY = f"{TABLE_PREFIX}semantic_registry"
T_SEMANTIC_SOURCES = f"{TABLE_PREFIX}semantic_sources"
T_TEAMS = f"{TABLE_PREFIX}teams"
T_TEAM_MEMBERS = f"{TABLE_PREFIX}team_members"

def get_db_connection_url():
    """Constructs database URL from environment variables."""
    user = os.environ.get("POSTGRES_USER")
    password = os.environ.get("POSTGRES_PASSWORD")
    host = os.environ.get("POSTGRES_HOST", "localhost")
    port = os.environ.get("POSTGRES_PORT", "5432")
    db = os.environ.get("POSTGRES_DATABASE")

    if not all([user, password, db]):
        return None

    password = urllib.parse.quote_plus(password)
    return f"postgresql://{user}:{password}@{host}:{port}/{db}"

def get_async_db_url():
    """Async database URL for DatabaseSessionService (asyncpg driver)."""
    sync_url = get_db_connection_url()
    if not sync_url:
        return None
    return sync_url.replace("postgresql://", "postgresql+asyncpg://", 1)


def _inject_user_context(conn):
    """Inject user identity and role into PostgreSQL session for RLS.

    Sets two session-level GUC variables:
    - app.current_user: the username string
    - app.current_user_role: admin/analyst/viewer

    Both are transaction-local (reset when transaction ends).
    """
    uid = current_user_id.get()
    role = current_user_role.get()
    if uid and uid != "anonymous":
        conn.execute(text("SELECT set_config('app.current_user', :uid, true)"), {"uid": uid})
        conn.execute(text("SELECT set_config('app.current_user_role', :role, true)"), {"role": role})
    else:
        conn.execute(text("SELECT set_config('app.current_user', 'anonymous', true)"))
        conn.execute(text("SELECT set_config('app.current_user_role', 'viewer', true)"))


def query_database(sql_query: str) -> dict:
    """
    [Database Tool] Executes a SQL query against the configured PostgreSQL/PostGIS database.

    Args:
        sql_query: The SQL statement to execute. SELECT statements return data.

    Returns:
        Dict with status, message, and path to results (CSV/SHP).
    """
    engine = get_engine()
    if not engine:
        return {"status": "error", "message": "Database credentials not configured in .env"}

    # Security: Block non-query statements to prevent data modification
    sql_lower = sql_query.strip().lower()
    if not (sql_lower.startswith("select") or sql_lower.startswith("with")):
        return {"status": "error", "message": "Only SELECT or WITH queries are allowed for security reasons."}

    try:
        with engine.connect() as conn:
            # Enforce read-only transaction at the database level
            conn.execute(text("SET TRANSACTION READ ONLY"))
            
            # Inject user context for RLS (Row-Level Security)
            _inject_user_context(conn)

            # Execute query to get cursor/result proxy (executes only ONCE)
            result_proxy = conn.execute(text(sql_query))
            keys = list(result_proxy.keys())
            rows = result_proxy.fetchall()

            # Check if any column looks like geometry
            geom_col = next((k for k in keys if k.lower() in ['geometry', 'geom', 'shape']), None)

            if geom_col:
                df = pd.DataFrame(rows, columns=keys)
                if not df.empty:
                    from shapely import wkb
                    def parse_geom(g):
                        if g is None: return None
                        if isinstance(g, str): return wkb.loads(g, hex=True)
                        if isinstance(g, (bytes, memoryview)): return wkb.loads(bytes(g))
                        return g
                    df[geom_col] = df[geom_col].apply(parse_geom)
                    gdf = gpd.GeoDataFrame(df, geometry=geom_col)

                    # Try to detect SRID from PostGIS metadata
                    try:
                        # Extract table name from SQL (handles "FROM table" and "FROM schema.table")
                        import re
                        tbl_match = re.search(r'\bFROM\s+(?:"?(\w+)"?\.)?"?(\w+)"?', sql_query, re.IGNORECASE)
                        detected_table = tbl_match.group(2) if tbl_match else ""
                        srid_res = conn.execute(text(
                            "SELECT srid FROM geometry_columns WHERE f_table_name = :t"
                        ), {"t": detected_table}).fetchone()
                        if srid_res and srid_res[0]:
                            gdf.set_crs(epsg=srid_res[0], inplace=True)
                        else:
                            # Fallback: query SRID from first geometry in the result
                            srid_row = conn.execute(text(
                                f"SELECT ST_SRID({geom_col}) FROM ({sql_query}) _q WHERE {geom_col} IS NOT NULL LIMIT 1"
                            )).fetchone()
                            if srid_row and srid_row[0] and srid_row[0] != 0:
                                gdf.set_crs(epsg=srid_row[0], inplace=True)
                    except Exception:
                        pass

                    out_path = _generate_output_path("query_result", "shp")
                    gdf.to_file(out_path, encoding='utf-8')
                else:
                    # Save as CSV if empty to avoid Shapefile writer error
                    out_path = _generate_output_path("query_result", "csv")
                    df.to_csv(out_path, index=False)
                    
                return {
                    "status": "success",
                    "output_path": out_path,
                    "rows": len(df),
                    "message": f"Spatial query returned {len(df)} rows. Saved to {out_path}"
                }
            else:
                df = pd.DataFrame(rows, columns=keys)
                out_path = _generate_output_path("query_result", "csv")
                df.to_csv(out_path, index=False)
                return {
                    "status": "success",
                    "output_path": out_path,
                    "rows": len(df),
                    "message": f"Query returned {len(df)} rows. Saved to {out_path}"
                }

    except Exception as e:
        err = str(e)
        recovery = ""
        if "relation" in err and "does not exist" in err:
            recovery = "请先调用 list_tables 查看可用表名"
        elif "column" in err and "does not exist" in err:
            recovery = "请先调用 describe_table 查看表的字段结构"
        elif "permission denied" in err.lower() or "access" in err.lower():
            recovery = "当前用户无权访问该表，请联系管理员"
        elif "syntax error" in err.lower():
            recovery = "SQL语法错误，请检查查询语句"
        return {"status": "error", "message": err,
                **({"recovery": recovery} if recovery else {})}


def list_tables() -> dict:
    """[Database Tool] Lists tables the current user can access (owned + shared).
    Uses the table_ownership registry with RLS to auto-filter by user access."""
    engine = get_engine()
    if not engine:
        return {"status": "error", "message": "Database credentials not configured in .env"}

    try:
        with engine.connect() as conn:
            _inject_user_context(conn)

            # Check if table_ownership exists
            has_registry = conn.execute(text(
                "SELECT EXISTS (SELECT 1 FROM information_schema.tables "
                f"WHERE table_schema = 'public' AND table_name = '{T_TABLE_OWNERSHIP}')"
            )).scalar()

            if has_registry:
                # Query table_ownership (RLS auto-filters: user sees own + shared + admin sees all)
                rows = conn.execute(text(f"""
                    SELECT t.table_name, t.is_shared, t.owner_username,
                           CASE WHEN gc.f_table_name IS NOT NULL THEN TRUE ELSE FALSE END AS is_spatial
                    FROM {T_TABLE_OWNERSHIP} t
                    LEFT JOIN geometry_columns gc
                        ON gc.f_table_name = t.table_name AND gc.f_table_schema = 'public'
                    ORDER BY t.table_name
                """)).fetchall()

                annotated = []
                for r in rows:
                    name, shared, owner, spatial = r
                    label = name
                    if spatial:
                        label += " (Spatial)"
                    if shared:
                        label += " [Shared]"
                    annotated.append(label)
            else:
                # Fallback: no registry yet, show all tables (pre-migration behavior)
                rows = conn.execute(text(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema = 'public' ORDER BY table_name"
                )).fetchall()
                spatial_rows = conn.execute(text(
                    "SELECT f_table_name FROM geometry_columns WHERE f_table_schema = 'public'"
                )).fetchall()
                spatial_set = {r[0] for r in spatial_rows}
                annotated = []
                for r in rows:
                    label = r[0]
                    if r[0] in spatial_set:
                        label += " (Spatial)"
                    annotated.append(label)

            return {
                "status": "success",
                "tables": annotated,
                "message": f"Found {len(annotated)} accessible tables:\n" +
                           "\n".join(f"- {t}" for t in annotated),
            }
    except Exception as e:
        return {"status": "error", "message": str(e)}


def describe_table(table_name: str) -> dict:
    """[Database Tool] Returns columns and data types for a table the user can access."""
    if not re.match(r'^[a-zA-Z0-9_]+$', table_name):
        return {"status": "error", "message": "Invalid table name format."}

    engine = get_engine()
    if not engine:
        return {"status": "error", "message": "Database credentials not configured in .env"}

    # System tables that don't require ownership check
    system_tables = {
        'spatial_ref_sys', 'geometry_columns', 'geography_columns',
        T_APP_USERS, T_USER_MEMORIES, T_TOKEN_USAGE, T_TABLE_OWNERSHIP, T_SHARE_LINKS,
    }

    try:
        engine = get_engine()
        with engine.connect() as conn:
            _inject_user_context(conn)

            # Check table access via table_ownership (RLS auto-filters)
            if table_name not in system_tables:
                has_registry = conn.execute(text(
                    "SELECT EXISTS (SELECT 1 FROM information_schema.tables "
                    f"WHERE table_schema = 'public' AND table_name = '{T_TABLE_OWNERSHIP}')"
                )).scalar()

                if has_registry:
                    access = conn.execute(text(
                        f"SELECT COUNT(*) FROM {T_TABLE_OWNERSHIP} WHERE table_name = :t"
                    ), {"t": table_name}).scalar()
                    if access == 0:
                        return {"status": "error",
                                "message": f"Table '{table_name}' not found or access denied."}

            # Describe the table
            result = conn.execute(text(
                "SELECT column_name, data_type FROM information_schema.columns "
                "WHERE table_name = :t ORDER BY ordinal_position"
            ), {"t": table_name}).fetchall()

            if not result:
                return {"status": "error", "message": f"Table '{table_name}' not found."}

            cols_info = [{"column_name": r[0], "data_type": r[1]} for r in result]

            # Auto-register semantic annotations on first encounter
            try:
                from .semantic_layer import auto_register_table
                auto_register_table(table_name, current_user_id.get() or "anonymous")
            except Exception:
                pass  # non-fatal

            return {
                "status": "success",
                "columns": cols_info,
                "message": f"Table '{table_name}' has columns:\n" +
                           "\n".join(f"- {c['column_name']} ({c['data_type']})" for c in cols_info),
            }
    except Exception as e:
        return {"status": "error", "message": str(e)}


def register_table_ownership(table_name: str, owner_username: str,
                             is_shared: bool = False, description: str = "") -> dict:
    """Register a newly imported table in the ownership registry."""
    engine = get_engine()
    if not engine:
        return {"status": "error", "message": "Database not configured"}

    try:
        with engine.connect() as conn:
            _inject_user_context(conn)
            conn.execute(text(f"""
                INSERT INTO {T_TABLE_OWNERSHIP} (table_name, owner_username, is_shared, description)
                VALUES (:t, :u, :s, :d)
                ON CONFLICT (table_name) DO UPDATE
                SET owner_username = :u, is_shared = :s, description = :d
            """), {"t": table_name, "u": owner_username, "s": is_shared, "d": description})
            conn.commit()
        return {"status": "success", "message": f"Registered table '{table_name}' owned by '{owner_username}'"}
    except Exception as e:
        return {"status": "error", "message": str(e)}
    finally:
        # Cross-register in data catalog (non-fatal)
        try:
            from .data_catalog import register_postgis_asset
            register_postgis_asset(table_name, owner=owner_username, description=description)
        except Exception:
            pass


def share_table(table_name: str) -> dict:
    """[Admin Tool] Mark a table as shared so all users can access it."""
    if current_user_role.get() != 'admin':
        return {"status": "error", "message": "Only admin can share tables."}

    engine = get_engine()
    if not engine:
        return {"status": "error", "message": "Database not configured"}

    try:
        with engine.connect() as conn:
            _inject_user_context(conn)
            result = conn.execute(text(
                f"UPDATE {T_TABLE_OWNERSHIP} SET is_shared = TRUE WHERE table_name = :t"
            ), {"t": table_name})
            conn.commit()
            if result.rowcount > 0:
                try:
                    from .audit_logger import record_audit, ACTION_TABLE_SHARE
                    record_audit(current_user_id.get(), ACTION_TABLE_SHARE,
                                 details={"table_name": table_name})
                except Exception:
                    pass
                return {"status": "success", "message": f"Table '{table_name}' is now shared."}
            return {"status": "error", "message": f"Table '{table_name}' not found in registry."}
    except Exception as e:
        return {"status": "error", "message": str(e)}


def import_to_postgis(file_path: str, table_name: str = "",
                      srid: int = 0, if_exists: str = "fail") -> dict:
    """
    [Database Tool] Import a spatial data file into PostGIS as a new table.

    Supports Shapefile (.shp), GeoJSON, GeoPackage (.gpkg), KML, CSV/Excel
    (with coordinate columns). The imported table is registered in the ownership
    registry so only the importing user can access it.

    Args:
        file_path: Path to the spatial file to import.
        table_name: Target table name (auto-generated from filename if empty).
            Must contain only letters, digits, and underscores.
        srid: Target coordinate reference system EPSG code.
            0 = keep original CRS. Common values: 4326 (WGS84), 4490 (CGCS2000).
        if_exists: What to do if the table already exists.
            "fail" (default) = raise error, "replace" = drop and recreate,
            "append" = add rows to existing table.

    Returns:
        Dict with status, table_name, rows, srid, columns, and message.
    """
    engine = get_engine()
    if not engine:
        return {"status": "error", "message": "数据库未配置，无法导入。"}

    # Validate if_exists
    if if_exists not in ("fail", "replace", "append"):
        return {"status": "error",
                "message": f"if_exists 参数无效: '{if_exists}'。可选值: fail, replace, append"}

    # Sanitize or auto-generate table name
    if table_name:
        table_name = table_name.strip().lower()
        if not re.match(r'^[a-z][a-z0-9_]{0,62}$', table_name):
            return {"status": "error",
                    "message": f"表名 '{table_name}' 格式无效。"
                               "必须以字母开头，仅包含小写字母、数字和下划线，最长63字符。"}
    else:
        # Auto-generate from filename
        basename = os.path.splitext(os.path.basename(file_path))[0]
        safe_name = re.sub(r'[^a-z0-9]', '_', basename.lower()).strip('_')
        if not safe_name or not safe_name[0].isalpha():
            safe_name = "t_" + safe_name
        table_name = f"{safe_name}_{uuid.uuid4().hex[:6]}"[:63]

    # Load spatial data
    try:
        from .utils import _load_spatial_data
        resolved = _resolve_path(file_path)
        gdf = _load_spatial_data(resolved)
    except Exception as e:
        return {"status": "error", "message": f"读取文件失败: {e}"}

    if gdf.empty:
        return {"status": "error", "message": "文件不包含任何要素数据。"}

    # Handle SRID / CRS
    original_srid = 0
    if gdf.crs:
        try:
            original_srid = gdf.crs.to_epsg() or 0
        except Exception:
            pass

    if srid > 0 and srid != original_srid:
        try:
            gdf = gdf.to_crs(epsg=srid)
        except Exception as e:
            return {"status": "error", "message": f"坐标转换失败 (EPSG:{srid}): {e}"}
    else:
        srid = original_srid

    # Write to PostGIS
    try:
        with engine.connect() as conn:
            _inject_user_context(conn)
            gdf.to_postgis(table_name, conn, if_exists=if_exists, index=False)
            conn.commit()
    except Exception as e:
        msg = str(e)
        if "already exists" in msg.lower():
            return {"status": "error",
                    "message": f"表 '{table_name}' 已存在。使用 if_exists='replace' 覆盖或 'append' 追加。"}
        return {"status": "error", "message": f"写入 PostGIS 失败: {e}"}

    # Register ownership (cross-registers in data catalog)
    username = current_user_id.get() or "anonymous"
    register_table_ownership(
        table_name, username,
        description=f"Imported from {os.path.basename(file_path)}"
    )

    columns = [c for c in gdf.columns if c != "geometry"]
    return {
        "status": "success",
        "table_name": table_name,
        "rows": len(gdf),
        "srid": srid,
        "columns": columns,
        "message": f"成功导入 {len(gdf)} 条要素到表 '{table_name}' (EPSG:{srid})。"
                   f"包含 {len(columns)} 个属性列: {', '.join(columns[:10])}"
                   + (f"... 等共{len(columns)}列" if len(columns) > 10 else ""),
    }


def ensure_table_ownership_table():
    """Create table_ownership table if not exists. Called at startup."""
    engine = get_engine()
    if not engine:
        return

    try:
        with engine.connect() as conn:
            conn.execute(text(f"""
                CREATE TABLE IF NOT EXISTS {T_TABLE_OWNERSHIP} (
                    id SERIAL PRIMARY KEY,
                    table_name VARCHAR(200) UNIQUE NOT NULL,
                    owner_username VARCHAR(100) NOT NULL,
                    is_shared BOOLEAN DEFAULT FALSE,
                    description TEXT DEFAULT '',
                    created_at TIMESTAMP DEFAULT NOW()
                )
            """))
            conn.execute(text(
                f"CREATE INDEX IF NOT EXISTS idx_table_ownership_owner ON {T_TABLE_OWNERSHIP} (owner_username)"
            ))
            conn.execute(text(
                f"CREATE INDEX IF NOT EXISTS idx_table_ownership_shared ON {T_TABLE_OWNERSHIP} (is_shared)"
            ))
            conn.commit()

            # Check if agent_user is superuser/bypassrls (RLS would be ineffective)
            try:
                row = conn.execute(text(
                    "SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user"
                )).fetchone()
                if row and (row[0] or row[1]):
                    print("[DB] WARNING: Current database role is SUPERUSER or BYPASSRLS. "
                          "RLS policies will NOT be enforced! "
                          "Run: ALTER ROLE agent_user NOSUPERUSER NOBYPASSRLS;")
            except Exception:
                pass  # pg_roles may not be accessible

        print("[DB] Table ownership registry ready.")
    except Exception as e:
        print(f"[DB] Error initializing table_ownership: {e}")
