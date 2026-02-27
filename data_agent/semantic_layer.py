"""
Spatial Semantic Layer — maps business concepts to spatial data objects.

Provides:
- Static YAML catalog of GIS domain knowledge (column domains, regions, operations)
- DB-backed per-table/column semantic annotations (auto-discovered + user-curated)
- Synonym matching resolver for prompt enrichment
- ADK tool functions for CRUD operations on semantic metadata

The core value: agents no longer guess that 'zmj' = area or 'dlmc' = land use type.
Instead, a [语义上下文] block is injected into the prompt with pre-resolved mappings.
"""
import os
import json
import yaml
from typing import Optional

from sqlalchemy import create_engine, text

from .database_tools import (
    get_db_connection_url, _inject_user_context,
    T_TABLE_OWNERSHIP,
)
from .user_context import current_user_id, current_user_role

# --- Table name constants ---
T_SEMANTIC_REGISTRY = "agent_semantic_registry"
T_SEMANTIC_SOURCES = "agent_semantic_sources"

# ---------------------------------------------------------------------------
# YAML Catalog Loading (cached, same pattern as prompts/__init__.py)
# ---------------------------------------------------------------------------
_catalog_cache: Optional[dict] = None
_CATALOG_PATH = os.path.join(os.path.dirname(__file__), "semantic_catalog.yaml")


def _load_catalog() -> dict:
    """Load and cache the static semantic catalog."""
    global _catalog_cache
    if _catalog_cache is None:
        with open(_CATALOG_PATH, encoding="utf-8") as f:
            _catalog_cache = yaml.safe_load(f)
    return _catalog_cache


# ---------------------------------------------------------------------------
# DB Table Initialization
# ---------------------------------------------------------------------------

def ensure_semantic_tables():
    """Create semantic registry tables if they don't exist. Called at startup."""
    db_url = get_db_connection_url()
    if not db_url:
        return

    migration_path = os.path.join(
        os.path.dirname(__file__), "migrations", "009_create_semantic_registry.sql"
    )
    try:
        with open(migration_path, encoding="utf-8") as f:
            sql = f.read()

        engine = create_engine(db_url)
        with engine.connect() as conn:
            # Execute each statement separately (multi-statement)
            for stmt in sql.split(";"):
                stmt = stmt.strip()
                if stmt and not stmt.startswith("--"):
                    conn.execute(text(stmt))
            conn.commit()
        print("[Semantic] Registry ready.")
    except Exception as e:
        print(f"[Semantic] Error initializing tables: {e}")


# ---------------------------------------------------------------------------
# Synonym Matching (simple, no ML)
# ---------------------------------------------------------------------------

def _match_aliases(user_text: str, aliases: list) -> float:
    """Match user text against a list of aliases. Returns confidence 0-1."""
    user_lower = user_text.lower()
    for alias in aliases:
        alias_lower = alias.lower()
        # Exact word match
        if alias_lower == user_lower:
            return 1.0
        # Substring match (user text contains alias)
        if len(alias_lower) >= 2 and alias_lower in user_lower:
            return 0.7
    return 0.0


# ---------------------------------------------------------------------------
# Core Resolution
# ---------------------------------------------------------------------------

def resolve_semantic_context(user_text: str) -> dict:
    """
    [Semantic Tool] Resolve user text against semantic registry and static catalog.

    Matches user natural language against:
    - Table source synonyms (DB-backed)
    - Column aliases (DB + static catalog)
    - Region groups (static)
    - Spatial operations (static)
    - Metric templates (static)

    Args:
        user_text: The user's natural language query.

    Returns:
        Dict with matched sources, columns, spatial_ops, region_filter, metric_hints.
    """
    catalog = _load_catalog()
    result = {
        "sources": [],
        "matched_columns": {},
        "spatial_ops": [],
        "region_filter": None,
        "metric_hints": [],
    }

    # --- 1. Match table sources from DB ---
    db_url = get_db_connection_url()
    if db_url:
        try:
            engine = create_engine(db_url)
            with engine.connect() as conn:
                _inject_user_context(conn)

                # Check if semantic_sources table exists
                has_sources = conn.execute(text(
                    "SELECT EXISTS (SELECT 1 FROM information_schema.tables "
                    f"WHERE table_schema = 'public' AND table_name = '{T_SEMANTIC_SOURCES}')"
                )).scalar()

                if has_sources:
                    rows = conn.execute(text(f"""
                        SELECT table_name, display_name, description,
                               geometry_type, srid, synonyms
                        FROM {T_SEMANTIC_SOURCES}
                    """)).fetchall()

                    for row in rows:
                        tbl, disp, desc, geom_type, srid, syns = row
                        syn_list = syns if isinstance(syns, list) else json.loads(syns or "[]")
                        # Also match against table_name and display_name
                        all_aliases = syn_list + [tbl, disp] if disp else syn_list + [tbl]
                        score = _match_aliases(user_text, all_aliases)
                        if score > 0:
                            result["sources"].append({
                                "table_name": tbl,
                                "display_name": disp or tbl,
                                "description": desc or "",
                                "geometry_type": geom_type,
                                "srid": srid,
                                "confidence": score,
                            })

                    # --- 2. Match column annotations from DB ---
                    matched_tables = [s["table_name"] for s in result["sources"]]
                    if matched_tables:
                        placeholders = ", ".join(f"'{t}'" for t in matched_tables)
                        col_rows = conn.execute(text(f"""
                            SELECT table_name, column_name, semantic_domain,
                                   aliases, unit, description, is_geometry
                            FROM {T_SEMANTIC_REGISTRY}
                            WHERE table_name IN ({placeholders})
                        """)).fetchall()

                        for crow in col_rows:
                            tbl, col, domain, aliases_raw, unit, cdesc, is_geom = crow
                            alias_list = aliases_raw if isinstance(aliases_raw, list) else json.loads(aliases_raw or "[]")
                            col_score = _match_aliases(user_text, alias_list)
                            if col_score > 0 or is_geom:
                                if tbl not in result["matched_columns"]:
                                    result["matched_columns"][tbl] = []
                                result["matched_columns"][tbl].append({
                                    "column_name": col,
                                    "semantic_domain": domain,
                                    "aliases": alias_list,
                                    "unit": unit,
                                    "description": cdesc or "",
                                    "is_geometry": is_geom,
                                    "confidence": col_score,
                                })
        except Exception:
            pass  # non-fatal, fall through to static catalog

    # --- 3. Static catalog: match column domains for unresolved terms ---
    domains = catalog.get("domains", {})
    for domain_name, domain_info in domains.items():
        aliases = domain_info.get("common_aliases", [])
        score = _match_aliases(user_text, aliases)
        if score >= 0.5:
            # Add as a hint (not tied to a specific table)
            result["matched_columns"].setdefault("_static_hints", []).append({
                "semantic_domain": domain_name,
                "description": domain_info.get("description", ""),
                "typical_unit": domain_info.get("typical_unit", ""),
                "confidence": score * 0.5,  # lower weight for static
            })

    # --- 4. Match region groups ---
    region_groups = catalog.get("region_groups", {})
    for region_name, region_info in region_groups.items():
        aliases = region_info.get("aliases", [])
        if _match_aliases(user_text, aliases) > 0:
            result["region_filter"] = {
                "name": region_name,
                "provinces": region_info.get("provinces", []),
            }
            break

    # --- 5. Match spatial operations ---
    spatial_ops = catalog.get("spatial_operations", {})
    for op_name, op_info in spatial_ops.items():
        aliases = op_info.get("aliases", [])
        if _match_aliases(user_text, aliases) > 0:
            result["spatial_ops"].append({
                "operation": op_name,
                "tool_name": op_info.get("tool_name", ""),
            })

    # --- 6. Match metric templates ---
    metric_templates = catalog.get("metric_templates", {})
    for metric_name, metric_info in metric_templates.items():
        synonyms = metric_info.get("synonyms", [])
        if _match_aliases(user_text, synonyms) > 0:
            result["metric_hints"].append({
                "metric": metric_name,
                "description": metric_info.get("description", ""),
                "pattern": metric_info.get("pattern", ""),
                "unit": metric_info.get("unit", ""),
            })

    return result


# ---------------------------------------------------------------------------
# Context Prompt Builder
# ---------------------------------------------------------------------------

def build_context_prompt(resolved: dict) -> str:
    """Build [语义上下文] block for injection into the LLM prompt.

    Args:
        resolved: Output from resolve_semantic_context().

    Returns:
        Formatted context block string, or empty string if nothing matched.
    """
    parts = []

    # Source tables
    for src in resolved.get("sources", []):
        tbl = src["table_name"]
        disp = src.get("display_name", tbl)
        geom = src.get("geometry_type", "")
        srid = src.get("srid", "")
        desc = src.get("description", "")

        header = f"表 {tbl}"
        if disp and disp != tbl:
            header += f" ({disp})"
        if geom:
            header += f" [{geom}]"
        if srid:
            header += f" SRID={srid}"
        if desc:
            header += f" — {desc}"

        # Column mappings for this table
        cols = resolved.get("matched_columns", {}).get(tbl, [])
        col_strs = []
        for c in cols:
            s = c["column_name"]
            if c.get("description"):
                s += f"({c['description']}"
                if c.get("unit"):
                    s += f"/{c['unit']}"
                s += ")"
            elif c.get("semantic_domain"):
                s += f"({c['semantic_domain']}"
                if c.get("unit"):
                    s += f"/{c['unit']}"
                s += ")"
            if c.get("is_geometry"):
                s += " [GEOM]"
            col_strs.append(s)

        if col_strs:
            header += "\n  字段: " + ", ".join(col_strs)
        parts.append(header)

    # Region filter
    region = resolved.get("region_filter")
    if region:
        parts.append(f"区域过滤: {region['name']} → {', '.join(region['provinces'][:5])}")

    # Spatial operations
    for op in resolved.get("spatial_ops", []):
        parts.append(f"建议工具: {op['tool_name']} ({op['operation']})")

    # Metric hints
    for m in resolved.get("metric_hints", []):
        parts.append(f"指标模板: {m['description']} → {m['pattern']}")

    if not parts:
        return ""

    return "[语义上下文]\n" + "\n".join(parts) + \
           "\n\n优先使用以上语义映射，减少对 describe_table 的依赖。"


# ---------------------------------------------------------------------------
# Auto-Registration (called from describe_table on first encounter)
# ---------------------------------------------------------------------------

def auto_register_table(table_name: str, owner_username: str) -> dict:
    """Auto-register semantic annotations for a table by matching column names
    against the static catalog domains.

    Called from describe_table() when table not yet in registry. Scans column
    names, detects geometry columns + SRID, and populates both
    agent_semantic_registry and agent_semantic_sources.

    Args:
        table_name: The PostgreSQL table name.
        owner_username: The owner to associate with annotations.

    Returns:
        Dict with status and count of annotations created.
    """
    db_url = get_db_connection_url()
    if not db_url:
        return {"status": "error", "message": "Database not configured"}

    catalog = _load_catalog()
    domains = catalog.get("domains", {})

    try:
        engine = create_engine(db_url)
        with engine.connect() as conn:
            _inject_user_context(conn)

            # Check if already registered
            exists = conn.execute(text(
                f"SELECT COUNT(*) FROM {T_SEMANTIC_SOURCES} WHERE table_name = :t"
            ), {"t": table_name}).scalar()
            if exists > 0:
                return {"status": "skipped", "message": f"Table '{table_name}' already registered"}

            # Get column info
            columns = conn.execute(text(
                "SELECT column_name, data_type FROM information_schema.columns "
                "WHERE table_name = :t ORDER BY ordinal_position"
            ), {"t": table_name}).fetchall()

            if not columns:
                return {"status": "error", "message": f"Table '{table_name}' not found"}

            # Detect geometry info
            geom_info = conn.execute(text(
                "SELECT type, srid FROM geometry_columns "
                "WHERE f_table_schema = 'public' AND f_table_name = :t LIMIT 1"
            ), {"t": table_name}).fetchone()

            geometry_type = geom_info[0] if geom_info else None
            srid = geom_info[1] if geom_info else None

            # Register table-level metadata
            conn.execute(text(f"""
                INSERT INTO {T_SEMANTIC_SOURCES}
                    (table_name, display_name, geometry_type, srid, owner_username)
                VALUES (:t, :t, :gt, :srid, :owner)
                ON CONFLICT (table_name) DO NOTHING
            """), {"t": table_name, "gt": geometry_type, "srid": srid, "owner": owner_username})

            # Match each column against catalog domains
            annotations = 0
            for col_name, data_type in columns:
                col_lower = col_name.lower()
                matched_domain = None
                matched_aliases = []

                for domain_name, domain_info in domains.items():
                    aliases = domain_info.get("common_aliases", [])
                    for alias in aliases:
                        if alias.lower() == col_lower or col_lower == alias.lower():
                            matched_domain = domain_name
                            matched_aliases = aliases[:5]  # keep top 5
                            break
                    if matched_domain:
                        break

                # Detect geometry column
                is_geom = data_type in (
                    "USER-DEFINED",  # PostGIS geometry type
                    "geometry",
                )

                if matched_domain or is_geom:
                    unit = ""
                    desc = ""
                    if matched_domain:
                        d_info = domains[matched_domain]
                        unit = d_info.get("typical_unit", "")
                        desc = d_info.get("description", "")

                    conn.execute(text(f"""
                        INSERT INTO {T_SEMANTIC_REGISTRY}
                            (table_name, column_name, semantic_domain, aliases,
                             unit, description, is_geometry, owner_username)
                        VALUES (:t, :col, :domain, CAST(:aliases AS jsonb),
                                :unit, :desc, :is_geom, :owner)
                        ON CONFLICT (table_name, column_name) DO NOTHING
                    """), {
                        "t": table_name, "col": col_name,
                        "domain": matched_domain, "aliases": json.dumps(matched_aliases),
                        "unit": unit, "desc": desc,
                        "is_geom": is_geom, "owner": owner_username,
                    })
                    annotations += 1

            conn.commit()
            return {
                "status": "success",
                "message": f"Auto-registered {annotations} annotations for '{table_name}'",
                "annotations": annotations,
            }
    except Exception as e:
        return {"status": "error", "message": str(e)}


# ---------------------------------------------------------------------------
# ADK Tool Functions (CRUD)
# ---------------------------------------------------------------------------

def register_semantic_annotation(
    table_name: str,
    column_name: str,
    semantic_domain: str,
    aliases_json: str = "[]",
    unit: str = "",
    description: str = "",
) -> dict:
    """
    [Semantic Tool] Register or update a column-level semantic annotation.

    Allows users or agents to manually annotate what a column means.

    Args:
        table_name: The database table name.
        column_name: The column to annotate.
        semantic_domain: Domain category (e.g. AREA, SLOPE, LAND_USE).
        aliases_json: JSON array of alias strings (e.g. '["面积", "area", "zmj"]').
        unit: Unit of measurement (e.g. "m²", "度").
        description: Human-readable description.

    Returns:
        Dict with status and message.
    """
    db_url = get_db_connection_url()
    if not db_url:
        return {"status": "error", "message": "Database not configured"}

    try:
        # Validate JSON
        aliases = json.loads(aliases_json)
        if not isinstance(aliases, list):
            return {"status": "error", "message": "aliases_json must be a JSON array"}
    except json.JSONDecodeError:
        return {"status": "error", "message": "Invalid JSON in aliases_json"}

    owner = current_user_id.get() or "anonymous"

    try:
        engine = create_engine(db_url)
        with engine.connect() as conn:
            _inject_user_context(conn)
            conn.execute(text(f"""
                INSERT INTO {T_SEMANTIC_REGISTRY}
                    (table_name, column_name, semantic_domain, aliases,
                     unit, description, owner_username, updated_at)
                VALUES (:t, :col, :domain, CAST(:aliases AS jsonb),
                        :unit, :desc, :owner, NOW())
                ON CONFLICT (table_name, column_name) DO UPDATE SET
                    semantic_domain = :domain,
                    aliases = CAST(:aliases AS jsonb),
                    unit = :unit,
                    description = :desc,
                    updated_at = NOW()
            """), {
                "t": table_name, "col": column_name,
                "domain": semantic_domain, "aliases": json.dumps(aliases),
                "unit": unit, "desc": description, "owner": owner,
            })
            conn.commit()
        return {"status": "success",
                "message": f"Annotation saved: {table_name}.{column_name} → {semantic_domain}"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


def register_source_metadata(
    table_name: str,
    display_name: str = "",
    description: str = "",
    synonyms_json: str = "[]",
    suggested_analyses_json: str = "[]",
) -> dict:
    """
    [Semantic Tool] Register or update table-level semantic metadata.

    Allows users or agents to describe what a table represents, add synonyms
    for natural language matching, and suggest analysis types.

    Args:
        table_name: The database table name.
        display_name: Human-friendly name (e.g. "和平村地块数据").
        description: Description of the table contents.
        synonyms_json: JSON array of synonym strings (e.g. '["和平村", "heping"]').
        suggested_analyses_json: JSON array of analysis types (e.g. '["clustering", "choropleth"]').

    Returns:
        Dict with status and message.
    """
    db_url = get_db_connection_url()
    if not db_url:
        return {"status": "error", "message": "Database not configured"}

    try:
        syns = json.loads(synonyms_json)
        analyses = json.loads(suggested_analyses_json)
    except json.JSONDecodeError:
        return {"status": "error", "message": "Invalid JSON in synonyms or analyses"}

    owner = current_user_id.get() or "anonymous"

    try:
        engine = create_engine(db_url)
        with engine.connect() as conn:
            _inject_user_context(conn)
            conn.execute(text(f"""
                INSERT INTO {T_SEMANTIC_SOURCES}
                    (table_name, display_name, description, synonyms,
                     suggested_analyses, owner_username, updated_at)
                VALUES (:t, :disp, :desc, CAST(:syns AS jsonb),
                        CAST(:analyses AS jsonb), :owner, NOW())
                ON CONFLICT (table_name) DO UPDATE SET
                    display_name = :disp,
                    description = :desc,
                    synonyms = CAST(:syns AS jsonb),
                    suggested_analyses = CAST(:analyses AS jsonb),
                    updated_at = NOW()
            """), {
                "t": table_name, "disp": display_name, "desc": description,
                "syns": json.dumps(syns), "analyses": json.dumps(analyses),
                "owner": owner,
            })
            conn.commit()
        return {"status": "success",
                "message": f"Source metadata saved for '{table_name}'"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


def describe_table_semantic(table_name: str) -> dict:
    """
    [Semantic Tool] Enhanced describe_table with semantic annotations merged.

    Returns column schema enriched with domain labels, aliases, and units
    from the semantic registry.

    Args:
        table_name: The database table name.

    Returns:
        Dict with columns (enriched), source metadata, and formatted message.
    """
    db_url = get_db_connection_url()
    if not db_url:
        return {"status": "error", "message": "Database not configured"}

    try:
        engine = create_engine(db_url)
        with engine.connect() as conn:
            _inject_user_context(conn)

            # Get raw columns
            columns = conn.execute(text(
                "SELECT column_name, data_type FROM information_schema.columns "
                "WHERE table_name = :t ORDER BY ordinal_position"
            ), {"t": table_name}).fetchall()

            if not columns:
                return {"status": "error", "message": f"Table '{table_name}' not found"}

            # Get semantic annotations
            annotations = {}
            try:
                ann_rows = conn.execute(text(f"""
                    SELECT column_name, semantic_domain, aliases, unit, description, is_geometry
                    FROM {T_SEMANTIC_REGISTRY}
                    WHERE table_name = :t
                """), {"t": table_name}).fetchall()
                for row in ann_rows:
                    col, domain, aliases_raw, unit, desc, is_geom = row
                    alias_list = aliases_raw if isinstance(aliases_raw, list) else json.loads(aliases_raw or "[]")
                    annotations[col] = {
                        "semantic_domain": domain,
                        "aliases": alias_list,
                        "unit": unit or "",
                        "description": desc or "",
                        "is_geometry": is_geom,
                    }
            except Exception:
                pass  # table may not exist yet

            # Get source metadata
            source_meta = None
            try:
                src_row = conn.execute(text(f"""
                    SELECT display_name, description, geometry_type, srid,
                           synonyms, suggested_analyses
                    FROM {T_SEMANTIC_SOURCES}
                    WHERE table_name = :t
                """), {"t": table_name}).fetchone()
                if src_row:
                    source_meta = {
                        "display_name": src_row[0] or "",
                        "description": src_row[1] or "",
                        "geometry_type": src_row[2],
                        "srid": src_row[3],
                        "synonyms": src_row[4] if isinstance(src_row[4], list) else json.loads(src_row[4] or "[]"),
                        "suggested_analyses": src_row[5] if isinstance(src_row[5], list) else json.loads(src_row[5] or "[]"),
                    }
            except Exception:
                pass

            # Merge columns with annotations
            enriched = []
            for col_name, data_type in columns:
                entry = {"column_name": col_name, "data_type": data_type}
                if col_name in annotations:
                    entry.update(annotations[col_name])
                enriched.append(entry)

            # Build message
            lines = [f"表 '{table_name}'"]
            if source_meta:
                if source_meta["display_name"]:
                    lines[0] += f" ({source_meta['display_name']})"
                if source_meta["geometry_type"]:
                    lines[0] += f" [{source_meta['geometry_type']}]"
                if source_meta["srid"]:
                    lines[0] += f" SRID={source_meta['srid']}"
                if source_meta["description"]:
                    lines.append(f"描述: {source_meta['description']}")

            lines.append("字段列表:")
            for e in enriched:
                label = f"- {e['column_name']} ({e['data_type']})"
                if e.get("semantic_domain"):
                    label += f" → {e['semantic_domain']}"
                if e.get("description"):
                    label += f" [{e['description']}]"
                if e.get("unit"):
                    label += f" ({e['unit']})"
                if e.get("is_geometry"):
                    label += " 🌍"
                lines.append(label)

            return {
                "status": "success",
                "columns": enriched,
                "source_metadata": source_meta,
                "message": "\n".join(lines),
            }
    except Exception as e:
        return {"status": "error", "message": str(e)}


def list_semantic_sources() -> dict:
    """
    [Semantic Tool] List all registered semantic sources (table-level metadata).

    Returns:
        Dict with sources list and formatted message.
    """
    db_url = get_db_connection_url()
    if not db_url:
        return {"status": "error", "message": "Database not configured"}

    try:
        engine = create_engine(db_url)
        with engine.connect() as conn:
            _inject_user_context(conn)

            rows = conn.execute(text(f"""
                SELECT table_name, display_name, description,
                       geometry_type, srid, synonyms, suggested_analyses
                FROM {T_SEMANTIC_SOURCES}
                ORDER BY table_name
            """)).fetchall()

            sources = []
            lines = []
            for row in rows:
                tbl, disp, desc, gt, srid, syns, analyses = row
                syn_list = syns if isinstance(syns, list) else json.loads(syns or "[]")
                ana_list = analyses if isinstance(analyses, list) else json.loads(analyses or "[]")
                sources.append({
                    "table_name": tbl,
                    "display_name": disp or tbl,
                    "description": desc or "",
                    "geometry_type": gt,
                    "srid": srid,
                    "synonyms": syn_list,
                    "suggested_analyses": ana_list,
                })
                label = f"- {tbl}"
                if disp and disp != tbl:
                    label += f" ({disp})"
                if gt:
                    label += f" [{gt}]"
                if desc:
                    label += f" — {desc}"
                lines.append(label)

            return {
                "status": "success",
                "sources": sources,
                "message": f"已注册 {len(sources)} 个语义数据源:\n" + "\n".join(lines)
                           if sources else "暂无已注册的语义数据源。",
            }
    except Exception as e:
        return {"status": "error", "message": str(e)}
