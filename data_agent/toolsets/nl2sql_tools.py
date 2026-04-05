"""NL2SQL Toolset — Schema-aware natural language to SQL with safety guards."""

import json
import re
from typing import Optional

import geopandas as gpd
import pandas as pd


def discover_database_schema(table_pattern: str = "") -> str:
    """发现数据库中的表结构（表名、列名、列类型、中文描述）。

    从 INFORMATION_SCHEMA 和 pg_description 中提取表结构信息，
    供 LLM 理解数据库 schema 后构造正确的 SQL 查询。

    Args:
        table_pattern: 可选，表名模式（SQL LIKE 语法），如 "xiangzhen" 或 "%admin%"。
                       留空则返回所有表。

    Returns:
        JSON 字符串，包含表列表及每个表的列信息。

    Example:
        >>> discover_database_schema("xiangzhen")
        {
          "tables": [
            {
              "table_name": "xiangzhen",
              "description": "全国乡镇级行政区划",
              "columns": [
                {"name": "province", "type": "text", "description": "省份"},
                {"name": "city", "type": "text", "description": "地级市"},
                {"name": "county", "type": "text", "description": "区县"},
                {"name": "township", "type": "text", "description": "乡镇/街道"},
                {"name": "geometry", "type": "geometry", "description": "边界几何"}
              ]
            }
          ]
        }
    """
    try:
        from ..db_engine import get_engine
        from ..database_tools import _inject_user_context
        from sqlalchemy import text

        engine = get_engine()
        with engine.connect() as conn:
            _inject_user_context(conn)

            # Query INFORMATION_SCHEMA for table and column metadata
            # Use quote_ident() to properly handle reserved words (e.g. "User")
            # and mixed-case table names from Chainlit's data layer.
            schema_query = """
                SELECT
                    t.table_name,
                    obj_description((quote_ident(t.table_schema) || '.' || quote_ident(t.table_name))::regclass, 'pg_class') as table_description,
                    c.column_name,
                    c.data_type,
                    c.udt_name,
                    col_description((quote_ident(t.table_schema) || '.' || quote_ident(t.table_name))::regclass, c.ordinal_position) as column_description
                FROM information_schema.tables t
                JOIN information_schema.columns c
                    ON t.table_name = c.table_name
                    AND t.table_schema = c.table_schema
                WHERE t.table_schema = 'public'
                  AND t.table_type = 'BASE TABLE'
            """
            if table_pattern:
                schema_query += f" AND t.table_name LIKE '{table_pattern}'"
            schema_query += " ORDER BY t.table_name, c.ordinal_position"

            df = pd.read_sql(text(schema_query), conn)

        if df.empty:
            return json.dumps(
                {"tables": [], "message": "未找到匹配的表"},
                ensure_ascii=False,
            )

        # Group by table
        tables = []
        for table_name, group in df.groupby("table_name"):
            table_desc = group.iloc[0]["table_description"] or ""
            columns = []
            for _, row in group.iterrows():
                col_type = row["data_type"]
                if col_type == "USER-DEFINED":
                    col_type = row["udt_name"]  # e.g., "geometry"
                columns.append({
                    "name": row["column_name"],
                    "type": col_type,
                    "description": row["column_description"] or "",
                })
            tables.append({
                "table_name": table_name,
                "description": table_desc,
                "columns": columns,
            })

        return json.dumps(
            {
                "tables": tables,
                "count": len(tables),
                "message": f"发现 {len(tables)} 个表",
            },
            ensure_ascii=False,
        )

    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)


def execute_safe_sql(
    sql: str,
    output_format: str = "json",
    max_rows: int = 1000,
) -> str:
    """执行只读 SQL 查询（带安全检查）。

    仅允许 SELECT 查询，禁止 INSERT/UPDATE/DELETE/DROP 等写操作。
    自动限制返回行数，防止内存溢出。

    Args:
        sql: SQL 查询语句（仅支持 SELECT）。
        output_format: 输出格式，可选 "json"（默认）或 "geojson"（如果有几何列）。
        max_rows: 最大返回行数，默认 1000。

    Returns:
        JSON 字符串，包含查询结果或错误信息。

    Example:
        >>> execute_safe_sql("SELECT * FROM xiangzhen WHERE county='松江区' LIMIT 10")
        {
          "status": "ok",
          "rows": 10,
          "data": [...]
        }
    """
    try:
        # Safety check: only allow SELECT
        sql_upper = sql.strip().upper()
        forbidden = ["INSERT", "UPDATE", "DELETE", "DROP", "CREATE", "ALTER", "TRUNCATE", "GRANT", "REVOKE"]
        if any(kw in sql_upper for kw in forbidden):
            return json.dumps(
                {"error": "安全检查失败：仅允许 SELECT 查询"},
                ensure_ascii=False,
            )

        if not sql_upper.startswith("SELECT"):
            return json.dumps(
                {"error": "安全检查失败：SQL 必须以 SELECT 开头"},
                ensure_ascii=False,
            )

        import re
        # 剥除 LLM 擅自注入的 LIMIT 限制（特别是针对地理空间全量渲染）
        if output_format == "geojson":
            sql = re.sub(r'(?i)\s+LIMIT\s+\d+\s*;?\s*$', '', sql)
        else:
            # For JSON, ensure we have a limit to avoid OOM
            if "LIMIT" not in sql_upper:
                sql = f"{sql.rstrip(';')} LIMIT {max_rows}"

        from ..db_engine import get_engine
        from ..database_tools import _inject_user_context

        engine = get_engine()
        with engine.connect() as conn:
            _inject_user_context(conn)

            # Try to read as GeoDataFrame first (if geometry column exists)
            if output_format == "geojson":
                for geom_col in ["geometry", "geom", "the_geom", "shape"]:
                    try:
                        gdf = gpd.read_postgis(sql, conn, geom_col=geom_col)
                        if not gdf.empty:
                            # Save to file and return path
                            from ..user_context import current_user_id
                            import os
                            import uuid

                            uid = current_user_id.get("admin")
                            upload_dir = os.path.join(
                                os.path.dirname(os.path.dirname(__file__)),
                                "uploads",
                                uid,
                            )
                            os.makedirs(upload_dir, exist_ok=True)
                            fname = f"query_result_{uuid.uuid4().hex[:8]}.geojson"
                            fpath = os.path.join(upload_dir, fname)
                            gdf.to_file(fpath, driver="GeoJSON")

                            return json.dumps({
                                "status": "ok",
                                "rows": len(gdf),
                                "geojson_path": fpath,
                                "geojson_filename": fname,
                                "bounds": gdf.total_bounds.tolist(),
                            }, ensure_ascii=False)
                    except Exception:
                        continue

            # Fallback to regular DataFrame
            df = pd.read_sql(sql, conn)

            return json.dumps({
                "status": "ok",
                "rows": len(df),
                "columns": df.columns.tolist(),
                "data": df.head(100).to_dict(orient="records"),  # Only return first 100 for display
                "message": f"查询成功，返回 {len(df)} 行" + (f"（仅显示前 100 行）" if len(df) > 100 else ""),
            }, ensure_ascii=False, default=str)

    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)


def execute_spatial_query(
    table_name: str,
    filters: str = "",
    geometry_column: str = "geometry",
    limit: int = 100000,
) -> str:
    """执行空间数据查询并返回 GeoJSON（安全的参数化查询，无 SQL 注入风险）。

    适用于任何包含空间列的表。自动处理 WHERE 条件、坐标转换、GeoJSON 导出。

    Args:
        table_name: 表名，如 "xiangzhen"、"poi_data"。
        filters: 过滤条件 JSON 字符串，如 '{"city": "上海市", "county": "松江区"}'。
                 支持模糊匹配（自动加 LIKE '%value%'）。留空则返回前 limit 条。
        geometry_column: 几何列名，默认 "geometry"。
        limit: 最大返回行数，默认 100000。

    Returns:
        JSON 字符串，包含 geojson_path（保存的文件路径）和 map_config（地图配置）。

    Example:
        >>> execute_spatial_query("xiangzhen", '{"county": "松江区", "township": "方松"}')
        {"status": "ok", "geojson_path": "...", "features": 1, "map_config": {...}}
    """
    try:
        from ..db_engine import get_engine
        from ..database_tools import _inject_user_context
        from ..user_context import current_user_id
        import uuid

        # Parse filters from JSON string
        filter_dict = {}
        if filters and filters.strip():
            try:
                filter_dict = json.loads(filters)
            except json.JSONDecodeError:
                return json.dumps({"error": f"filters 格式错误，应为 JSON 字符串: {filters}"}, ensure_ascii=False)
        import os

        # Validate table name (防止 SQL 注入)
        if not re.match(r'^[a-zA-Z0-9_]+$', table_name):
            return json.dumps({"error": "Invalid table name"}, ensure_ascii=False)

        engine = get_engine()

        # Build WHERE clause with parameterized queries
        where_parts = []
        params = {}
        if filter_dict:
            for i, (col, val) in enumerate(filter_dict.items()):
                # Validate column name
                if not re.match(r'^[a-zA-Z0-9_]+$', col):
                    continue
                param_name = f"p{i}"
                # Use LIKE for fuzzy matching
                where_parts.append(f'"{col}" LIKE :{param_name}')
                params[param_name] = f"%{val}%"

        where_clause = " AND ".join(where_parts) if where_parts else "1=1"
        sql = f'SELECT * FROM "{table_name}" WHERE {where_clause} LIMIT {int(limit)}'

        with engine.connect() as conn:
            _inject_user_context(conn)
            # Try common geometry column names
            gdf = None
            for geom_col in [geometry_column, 'geom', 'the_geom', 'shape']:
                try:
                    gdf = gpd.read_postgis(sql, conn, geom_col=geom_col, params=params)
                    if not gdf.empty:
                        break
                except Exception:
                    continue

            if gdf is None or gdf.empty:
                return json.dumps({
                    "status": "ok",
                    "message": "查询成功但无数据",
                    "features": 0,
                }, ensure_ascii=False)

            # Ensure WGS84
            if gdf.crs and gdf.crs.to_epsg() != 4326:
                gdf = gdf.to_crs(epsg=4326)

            # Save GeoJSON
            uid = current_user_id.get("admin")
            upload_dir = os.path.join(
                os.path.dirname(os.path.dirname(__file__)),
                "uploads", uid
            )
            os.makedirs(upload_dir, exist_ok=True)
            fname = f"query_{table_name}_{uuid.uuid4().hex[:8]}.geojson"
            fpath = os.path.join(upload_dir, fname)
            gdf.to_file(fpath, driver="GeoJSON")

            # Build map config
            bounds = gdf.total_bounds
            center_lat = (bounds[1] + bounds[3]) / 2
            center_lng = (bounds[0] + bounds[2]) / 2

            map_config = {
                "layers": [{
                    "type": "geojson",
                    "geojson": fname,
                    "name": f"{table_name} 查询结果",
                    "style": {"color": "#3388ff", "weight": 2, "fillOpacity": 0.3},
                }],
                "center": [center_lat, center_lng],
                "zoom": 12,
            }

            return json.dumps({
                "status": "ok",
                "message": f"查询成功，返回 {len(gdf)} 个要素",
                "features": len(gdf),
                "geojson_path": fpath,
                "map_config": map_config,
            }, ensure_ascii=False)

    except Exception as e:
        return json.dumps({"error": str(e)}, ensure_ascii=False)


# Register tools
from google.adk.tools import FunctionTool
from google.adk.tools.base_toolset import BaseToolset

_NL2SQL_FUNCS = [
    discover_database_schema,
    execute_safe_sql,
    execute_spatial_query,
]


class NL2SQLToolset(BaseToolset):
    """Schema-aware NL2SQL tools for dynamic database exploration."""

    async def get_tools(self, readonly_context=None):
        all_tools = [FunctionTool(f) for f in _NL2SQL_FUNCS]
        if self.tool_filter is None:
            return all_tools
        return [t for t in all_tools if self._is_tool_selected(t, readonly_context)]
