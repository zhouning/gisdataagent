"""
Spatial Semantic Layer — maps business concepts to spatial data objects.

Provides:
- Static YAML catalog of GIS domain knowledge (column domains, regions, operations)
- DB-backed per-table/column semantic annotations (auto-discovered + user-curated)
- DB-backed custom domain registry (user-defined hierarchies)
- Synonym matching resolver with fuzzy matching for prompt enrichment
- SQL filter generation from resolved semantic context
- Column equivalence auto-discovery
- ADK tool functions for CRUD operations on semantic metadata

The core value: agents no longer guess that 'zmj' = area or 'dlmc' = land use type.
Instead, a [语义上下文] block is injected into the prompt with pre-resolved mappings.
"""
import os
import json
import time
import yaml
from difflib import SequenceMatcher
from typing import Optional

from sqlalchemy import text

from .db_engine import get_engine
from .database_tools import (
    _inject_user_context,
    T_TABLE_OWNERSHIP,
)
from .user_context import current_user_id, current_user_role

# --- Table name constants ---
T_SEMANTIC_REGISTRY = "agent_semantic_registry"
T_SEMANTIC_SOURCES = "agent_semantic_sources"
T_SEMANTIC_DOMAINS = "agent_semantic_domains"

# ---------------------------------------------------------------------------
# YAML Catalog Loading (cached, same pattern as prompts/__init__.py)
# ---------------------------------------------------------------------------
_catalog_cache: Optional[dict] = None
_CATALOG_PATH = os.path.join(os.path.dirname(__file__), "semantic_catalog.yaml")


def _load_catalog() -> dict:
    """Load and cache the static semantic catalog."""
    global _catalog_cache
    if _catalog_cache is None:
        try:
            with open(_CATALOG_PATH, encoding="utf-8") as f:
                _catalog_cache = yaml.safe_load(f)
        except Exception as e:
            print(f"[Semantic] WARNING: Failed to load catalog ({e}). Using empty defaults.")
            _catalog_cache = {
                "domains": {},
                "region_groups": {},
                "spatial_operations": {},
                "metric_templates": {},
            }
    return _catalog_cache


# ---------------------------------------------------------------------------
# DB Query Cache (TTL-based, avoids querying semantic tables on every message)
# ---------------------------------------------------------------------------
_CACHE_TTL = 300  # 5 minutes

_sources_cache: Optional[list] = None
_sources_cache_time: float = 0

_registry_cache: dict = {}  # table_name → (rows, timestamp)


def _get_cached_sources(conn) -> list:
    """Get all semantic sources with 5-minute TTL cache (Redis → memory → DB)."""
    global _sources_cache, _sources_cache_time

    # 1. Check memory cache
    if _sources_cache is not None and (time.time() - _sources_cache_time < _CACHE_TTL):
        try:
            from .observability import record_cache_op
            record_cache_op("semantic_sources", "hit")
        except Exception:
            pass
        return _sources_cache

    # 2. Check Redis cache
    try:
        from .redis_client import get_redis_sync
        r = get_redis_sync()
        if r:
            cached = r.get("semantic:sources")
            if cached:
                import json as _json
                rows = _json.loads(cached)
                _sources_cache = [tuple(row) for row in rows]
                _sources_cache_time = time.time()
                try:
                    from .observability import record_cache_op
                    record_cache_op("semantic_sources", "hit_redis")
                except Exception:
                    pass
                return _sources_cache
    except Exception:
        pass

    try:
        from .observability import record_cache_op
        record_cache_op("semantic_sources", "miss")
    except Exception:
        pass

    # 3. Query DB
    has_sources = conn.execute(text(
        "SELECT EXISTS (SELECT 1 FROM information_schema.tables "
        f"WHERE table_schema = 'public' AND table_name = '{T_SEMANTIC_SOURCES}')"
    )).scalar()

    if not has_sources:
        _sources_cache = []
        _sources_cache_time = time.time()
        return _sources_cache

    rows = conn.execute(text(f"""
        SELECT table_name, display_name, description,
               geometry_type, srid, synonyms
        FROM {T_SEMANTIC_SOURCES}
    """)).fetchall()

    _sources_cache = rows
    _sources_cache_time = time.time()

    # 4. Write to Redis
    try:
        from .redis_client import get_redis_sync
        r = get_redis_sync()
        if r:
            import json as _json
            r.setex("semantic:sources", _CACHE_TTL, _json.dumps([list(row) for row in rows]))
    except Exception:
        pass

    return rows


def _get_cached_registry(conn, table_names: list) -> list:
    """Get semantic registry entries for given tables, with per-table TTL cache."""
    now = time.time()
    uncached = []
    cached_rows = []

    for tbl in table_names:
        entry = _registry_cache.get(tbl)
        if entry and (now - entry[1] < _CACHE_TTL):
            cached_rows.extend(entry[0])
        else:
            uncached.append(tbl)

    if uncached:
        bind_params = {f"t{i}": t for i, t in enumerate(uncached)}
        placeholders = ", ".join(f":t{i}" for i in range(len(uncached)))
        rows = conn.execute(text(f"""
            SELECT table_name, column_name, semantic_domain,
                   aliases, unit, description, is_geometry
            FROM {T_SEMANTIC_REGISTRY}
            WHERE table_name IN ({placeholders})
        """), bind_params).fetchall()

        # Group by table for caching
        by_table: dict = {t: [] for t in uncached}
        for row in rows:
            by_table.setdefault(row[0], []).append(row)
        for tbl, tbl_rows in by_table.items():
            _registry_cache[tbl] = (tbl_rows, now)

        cached_rows.extend(rows)

    return cached_rows


def invalidate_semantic_cache(table_name: str = None):
    """Clear semantic query caches (memory + Redis). Called after writes."""
    global _sources_cache, _sources_cache_time
    _sources_cache = None
    _sources_cache_time = 0
    if table_name:
        _registry_cache.pop(table_name, None)
    else:
        _registry_cache.clear()
    # Clear Redis cache
    try:
        from .redis_client import get_redis_sync
        r = get_redis_sync()
        if r:
            r.delete("semantic:sources")
            if table_name:
                r.delete(f"semantic:registry:{table_name}")
            else:
                # Delete all registry keys
                for key in r.scan_iter("semantic:registry:*"):
                    r.delete(key)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# DB Table Initialization
# ---------------------------------------------------------------------------

def ensure_semantic_tables():
    """Create semantic registry tables if they don't exist. Called at startup."""
    engine = get_engine()
    if not engine:
        return

    migrations_dir = os.path.join(os.path.dirname(__file__), "migrations")
    migration_files = [
        "009_create_semantic_registry.sql",
        "010_create_semantic_domains.sql",
        "011_create_semantic_metrics.sql",
    ]

    try:
        with engine.connect() as conn:
            for mig_file in migration_files:
                mig_path = os.path.join(migrations_dir, mig_file)
                if not os.path.exists(mig_path):
                    continue
                with open(mig_path, encoding="utf-8") as f:
                    sql = f.read()
                for stmt in sql.split(";"):
                    stmt = stmt.strip()
                    # Strip leading comment lines to get to actual SQL
                    lines = [l for l in stmt.splitlines() if not l.strip().startswith("--")]
                    clean = "\n".join(lines).strip()
                    if clean:
                        conn.execute(text(stmt))
            conn.commit()
        print("[Semantic] Registry ready.")
    except Exception as e:
        print(f"[Semantic] Error initializing tables: {e}")


# ---------------------------------------------------------------------------
# Synonym Matching (simple, no ML)
# ---------------------------------------------------------------------------

def _match_aliases(user_text: str, aliases: list, fuzzy: bool = True) -> float:
    """Match user text against a list of aliases. Returns confidence 0-1.

    Supports exact, substring, and fuzzy (SequenceMatcher) matching.
    """
    user_lower = user_text.lower()
    best_score = 0.0
    for alias in aliases:
        alias_lower = alias.lower()
        # Exact word match
        if alias_lower == user_lower:
            return 1.0
        # Substring match (user text contains alias)
        if len(alias_lower) >= 2 and alias_lower in user_lower:
            best_score = max(best_score, 0.7)
            continue
        # Fuzzy match via SequenceMatcher (for typos / partial matches)
        if fuzzy and len(alias_lower) >= 3:
            ratio = SequenceMatcher(None, alias_lower, user_lower).ratio()
            if ratio >= 0.75:
                best_score = max(best_score, ratio * 0.6)  # cap fuzzy at 0.6
    return best_score


def _match_hierarchy(user_text: str, domain_info: dict) -> Optional[dict]:
    """Match user text against domain hierarchy tree.

    Supports 3-level hierarchy: parent → child → sub_child.
    Returns dict with matched category info, or None if no match.
    """
    hierarchy = domain_info.get("hierarchy")
    if not hierarchy:
        return None

    user_lower = user_text.lower()

    # Check each parent category
    for parent_name, parent_info in hierarchy.items():
        parent_aliases = parent_info.get("aliases", [])
        children = parent_info.get("children", {})

        # Check sub-children first (most specific match)
        for child_name, child_info in children.items():
            for sub_name, sub_info in child_info.get("sub_children", {}).items():
                sub_aliases = sub_info.get("aliases", [])
                if _match_aliases(user_text, sub_aliases + [sub_name]) > 0:
                    return {
                        "level": "sub_child",
                        "parent": parent_name,
                        "child": child_name,
                        "name": sub_name,
                        "code_prefix": sub_info.get("code_prefix", ""),
                        "aliases": sub_aliases,
                    }

        # Check child categories (mid-level match)
        for child_name, child_info in children.items():
            child_aliases = child_info.get("aliases", [])
            if _match_aliases(user_text, child_aliases + [child_name]) > 0:
                return {
                    "level": "child",
                    "parent": parent_name,
                    "name": child_name,
                    "code_prefix": child_info.get("code_prefix", ""),
                    "aliases": child_aliases,
                }

        # Then check parent category (broader match → returns all children)
        if _match_aliases(user_text, parent_aliases + [parent_name]) > 0:
            child_entries = []
            for child_name, child_info in children.items():
                child_entries.append({
                    "name": child_name,
                    "code_prefix": child_info.get("code_prefix", ""),
                })
            return {
                "level": "parent",
                "parent": parent_name,
                "name": parent_name,
                "children": child_entries,
            }

    return None


def _match_equivalences(matched_columns: dict, catalog: dict) -> list:
    """Find column equivalences for matched columns.

    Returns list of equivalence mappings that apply.
    """
    equivalences = catalog.get("equivalences", [])
    if not equivalences:
        return []

    # Collect all matched column names across all tables
    all_cols = set()
    for tbl, cols in matched_columns.items():
        if tbl == "_static_hints":
            continue
        for c in cols:
            all_cols.add(c.get("column_name", "").lower())

    matched_equivs = []
    for eq in equivalences:
        eq_cols = [c.lower() for c in eq.get("columns", [])]
        if any(c in all_cols for c in eq_cols):
            matched_equivs.append(eq)

    return matched_equivs


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
    - User-defined custom domains (DB-backed)

    Args:
        user_text: The user's natural language query.

    Returns:
        Dict with matched sources, columns, spatial_ops, region_filter,
        metric_hints, hierarchy_matches, equivalences, and sql_filters.
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
    engine = get_engine()
    if engine:
        try:
            with engine.connect() as conn:
                _inject_user_context(conn)

                rows = _get_cached_sources(conn)

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
                        col_rows = _get_cached_registry(conn, matched_tables)

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

        # --- 3b. Hierarchy matching for this domain ---
        hierarchy_match = _match_hierarchy(user_text, domain_info)
        if hierarchy_match:
            result.setdefault("hierarchy_matches", []).append({
                "domain": domain_name,
                **hierarchy_match,
            })

    # --- 4. Match column equivalences ---
    equiv_matches = _match_equivalences(result["matched_columns"], catalog)
    if equiv_matches:
        result["equivalences"] = equiv_matches

    # --- 5. Match region groups ---
    region_groups = catalog.get("region_groups", {})
    for region_name, region_info in region_groups.items():
        aliases = region_info.get("aliases", [])
        if _match_aliases(user_text, aliases) > 0:
            result["region_filter"] = {
                "name": region_name,
                "provinces": region_info.get("provinces", []),
            }
            break

    # --- 6. Match spatial operations ---
    spatial_ops = catalog.get("spatial_operations", {})
    for op_name, op_info in spatial_ops.items():
        aliases = op_info.get("aliases", [])
        if _match_aliases(user_text, aliases) > 0:
            result["spatial_ops"].append({
                "operation": op_name,
                "tool_name": op_info.get("tool_name", ""),
            })

    # --- 7. Match metric templates ---
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

    # --- 8. Match user-defined custom domains from DB ---
    if engine:
        try:
            with engine.connect() as conn:
                _inject_user_context(conn)
                try:
                    dom_rows = conn.execute(text(f"""
                        SELECT domain_name, parent_category, children, aliases
                        FROM {T_SEMANTIC_DOMAINS}
                    """)).fetchall()

                    for row in dom_rows:
                        dname, parent_cat, children_raw, aliases_arr = row
                        children_list = children_raw if isinstance(children_raw, list) else json.loads(children_raw or "[]")
                        aliases_list = list(aliases_arr) if aliases_arr else []

                        # Check parent-level match
                        all_aliases = aliases_list + ([parent_cat] if parent_cat else [])
                        if _match_aliases(user_text, all_aliases) > 0:
                            child_entries = []
                            for child in children_list:
                                child_entries.append({
                                    "name": child.get("name", ""),
                                    "code_prefix": child.get("code_prefix", ""),
                                })
                            result.setdefault("hierarchy_matches", []).append({
                                "domain": dname,
                                "level": "parent",
                                "parent": parent_cat or dname,
                                "name": parent_cat or dname,
                                "children": child_entries,
                                "source": "custom",
                            })
                            continue

                        # Check child-level matches
                        for child in children_list:
                            child_aliases = child.get("aliases", [])
                            if _match_aliases(user_text, child_aliases + [child.get("name", "")]) > 0:
                                result.setdefault("hierarchy_matches", []).append({
                                    "domain": dname,
                                    "level": "child",
                                    "parent": parent_cat or dname,
                                    "name": child.get("name", ""),
                                    "code_prefix": child.get("code_prefix", ""),
                                    "source": "custom",
                                })
                                break
                except Exception:
                    pass  # table may not exist yet
        except Exception:
            pass

    # --- 9. Generate SQL filters from resolved context ---
    filter_result = generate_semantic_filters(result)
    result["sql_filters"] = filter_result.get("sql_filters", [])
    result["region_sql"] = filter_result.get("region_sql", "")

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

    # Hierarchy matches
    for h in resolved.get("hierarchy_matches", []):
        source_tag = " [自定义域]" if h.get("source") == "custom" else ""
        if h["level"] == "sub_child":
            parts.append(
                f"分类筛选: {h['name']} (编码前缀 {h.get('code_prefix', '')}*, "
                f"属于 {h.get('child', '')} → {h['parent']}){source_tag}"
            )
        elif h["level"] == "child":
            parts.append(
                f"分类筛选: {h['name']} (编码前缀 {h.get('code_prefix', '')}*, "
                f"属于 {h['parent']}){source_tag}"
            )
        elif h["level"] == "parent":
            children_str = ", ".join(
                f"{c['name']}[{c.get('code_prefix', '')}*]" for c in h.get("children", [])
            )
            parts.append(f"分类筛选: {h['name']} (包含 {children_str}){source_tag}")

    # Column equivalences
    for eq in resolved.get("equivalences", []):
        cols = " ↔ ".join(eq["columns"])
        parts.append(f"等价列: {cols} ({eq['description']})")

    # SQL filter hints (from generate_semantic_filters)
    sql_filters = resolved.get("sql_filters", [])
    region_sql = resolved.get("region_sql", "")
    if sql_filters or region_sql:
        parts.append("SQL筛选提示:")
        for sf in sql_filters:
            parts.append(f"  WHERE {sf['sql']}  -- {sf['description']}")
        if region_sql:
            parts.append(f"  WHERE {region_sql}  -- 区域筛选")

    # Static domain hints with confidence
    static_hints = resolved.get("matched_columns", {}).get("_static_hints", [])
    for hint in static_hints:
        conf = hint.get("confidence", 0)
        conf_tag = "[高置信]" if conf >= 0.4 else "[低置信]"
        parts.append(
            f"域提示 {conf_tag}: {hint['semantic_domain']} — "
            f"{hint.get('description', '')}"
        )

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
    engine = get_engine()
    if not engine:
        return {"status": "error", "message": "Database not configured"}

    catalog = _load_catalog()
    domains = catalog.get("domains", {})

    try:
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
            invalidate_semantic_cache(table_name)
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
    engine = get_engine()
    if not engine:
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
        invalidate_semantic_cache(table_name)
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
    engine = get_engine()
    if not engine:
        return {"status": "error", "message": "Database not configured"}

    try:
        syns = json.loads(synonyms_json)
        analyses = json.loads(suggested_analyses_json)
    except json.JSONDecodeError:
        return {"status": "error", "message": "Invalid JSON in synonyms or analyses"}

    owner = current_user_id.get() or "anonymous"

    try:
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
        invalidate_semantic_cache(table_name)
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
    engine = get_engine()
    if not engine:
        return {"status": "error", "message": "Database not configured"}

    try:
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
    engine = get_engine()
    if not engine:
        return {"status": "error", "message": "Database not configured"}

    try:
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


# ---------------------------------------------------------------------------
# Query Expansion & SQL Filter Generation
# ---------------------------------------------------------------------------

def expand_hierarchy(domain: str, term: str) -> list:
    """Expand a term through the hierarchy of a domain.

    Works for any domain that has a hierarchy (LAND_USE in static catalog,
    or user-defined domains from agent_semantic_domains).

    Args:
        domain: The domain name (e.g. "LAND_USE").
        term: The term to expand (e.g. "农用地" → all children code prefixes).

    Returns:
        List of dicts with name and code_prefix for matched hierarchy entries.
    """
    results = []

    # 1. Check static catalog hierarchy
    catalog = _load_catalog()
    domains = catalog.get("domains", {})
    domain_info = domains.get(domain, {})
    hierarchy = domain_info.get("hierarchy", {})

    for parent_name, parent_info in hierarchy.items():
        children = parent_info.get("children", {})
        parent_aliases = parent_info.get("aliases", [])

        # Check if term matches a specific sub-child (most specific)
        for child_name, child_info in children.items():
            for sub_name, sub_info in child_info.get("sub_children", {}).items():
                sub_aliases = sub_info.get("aliases", [])
                if _match_aliases(term, sub_aliases + [sub_name], fuzzy=False) > 0:
                    results.append({
                        "name": sub_name,
                        "code_prefix": sub_info.get("code_prefix", ""),
                    })
                    return results  # sub-child match is terminal

        # Check if term matches a specific child
        for child_name, child_info in children.items():
            child_aliases = child_info.get("aliases", [])
            if _match_aliases(term, child_aliases + [child_name], fuzzy=False) > 0:
                # If child has sub_children, return those for finer granularity
                sub_children = child_info.get("sub_children", {})
                if sub_children:
                    for sub_name, sub_info in sub_children.items():
                        results.append({
                            "name": sub_name,
                            "code_prefix": sub_info.get("code_prefix", ""),
                        })
                else:
                    results.append({
                        "name": child_name,
                        "code_prefix": child_info.get("code_prefix", ""),
                    })
                return results

        # Check if term matches parent → expand all children
        if _match_aliases(term, parent_aliases + [parent_name], fuzzy=False) > 0:
            for child_name, child_info in children.items():
                results.append({
                    "name": child_name,
                    "code_prefix": child_info.get("code_prefix", ""),
                })
            return results

    # 2. Check user-defined domains from DB
    engine = get_engine()
    if engine:
        try:
            with engine.connect() as conn:
                _inject_user_context(conn)
                rows = conn.execute(text(f"""
                    SELECT domain_name, parent_category, children, aliases
                    FROM {T_SEMANTIC_DOMAINS}
                    WHERE domain_name = :domain
                """), {"domain": domain}).fetchall()

                for row in rows:
                    _, parent_cat, children_json, aliases_arr = row
                    children_list = children_json if isinstance(children_json, list) else json.loads(children_json or "[]")
                    aliases_list = list(aliases_arr) if aliases_arr else []

                    # Check if term matches parent category
                    if parent_cat and _match_aliases(term, [parent_cat] + aliases_list, fuzzy=False) > 0:
                        for child in children_list:
                            results.append({
                                "name": child.get("name", ""),
                                "code_prefix": child.get("code_prefix", ""),
                            })
                        return results

                    # Check individual children
                    for child in children_list:
                        child_aliases = child.get("aliases", [])
                        if _match_aliases(term, child_aliases + [child.get("name", "")], fuzzy=False) > 0:
                            results.append({
                                "name": child.get("name", ""),
                                "code_prefix": child.get("code_prefix", ""),
                            })
                            return results
        except Exception:
            pass

    return results


def generate_semantic_filters(semantic_context: dict) -> dict:
    """Generate SQL WHERE clause fragments from resolved semantic context.

    Converts hierarchy matches and region filters into ready-to-use SQL.

    Args:
        semantic_context: Output from resolve_semantic_context().

    Returns:
        Dict with sql_filters list and region_sql.
    """
    filters = []
    region_sql = ""

    # 1. Hierarchy matches → code prefix filters
    for h in semantic_context.get("hierarchy_matches", []):
        if h["level"] == "sub_child":
            prefix = h.get("code_prefix", "")
            if prefix:
                filters.append({
                    "description": f"筛选{h['name']} (编码 {prefix}*, 属于 {h.get('child', '')} → {h['parent']})",
                    "sql": f"dlbm LIKE '{prefix}%'",
                    "column_hint": "dlbm",
                })
        elif h["level"] == "child":
            prefix = h.get("code_prefix", "")
            if prefix:
                filters.append({
                    "description": f"筛选{h['name']} (编码 {prefix}*)",
                    "sql": f"dlbm LIKE '{prefix}%'",
                    "column_hint": "dlbm",
                })
        elif h["level"] == "parent":
            children = h.get("children", [])
            prefixes = [c["code_prefix"] for c in children if c.get("code_prefix")]
            if prefixes:
                conditions = " OR ".join(f"dlbm LIKE '{p}%'" for p in prefixes)
                names = ", ".join(c["name"] for c in children)
                filters.append({
                    "description": f"筛选{h['name']}（含 {names}）",
                    "sql": f"({conditions})",
                    "column_hint": "dlbm",
                })

    # 2. Region filter → province list SQL
    region = semantic_context.get("region_filter")
    if region:
        provinces = region.get("provinces", [])
        if provinces:
            escaped = ", ".join(f"'{p}'" for p in provinces)
            region_sql = f"xzqmc IN ({escaped})"

    return {
        "sql_filters": filters,
        "region_sql": region_sql,
    }


# ---------------------------------------------------------------------------
# Hierarchy Browsing (ADK Tool)
# ---------------------------------------------------------------------------

def browse_hierarchy(domain: str = "LAND_USE") -> dict:
    """
    [Semantic Tool] Browse the full hierarchy tree of a semantic domain.

    Returns the complete classification tree for a domain, including all levels
    (parent → child → sub_child). Useful for understanding what categories are
    available before constructing queries.

    Args:
        domain: Domain name (e.g. "LAND_USE"). Defaults to LAND_USE.

    Returns:
        Dict with hierarchy tree and formatted text display.
    """
    catalog = _load_catalog()
    domains = catalog.get("domains", {})
    domain_info = domains.get(domain)

    if not domain_info:
        return {
            "status": "not_found",
            "message": f"Domain '{domain}' not found. Available: {', '.join(domains.keys())}",
            "tree": {},
        }

    hierarchy = domain_info.get("hierarchy")
    if not hierarchy:
        return {
            "status": "no_hierarchy",
            "message": f"Domain '{domain}' ({domain_info.get('description', '')}) has no hierarchy.",
            "tree": {},
        }

    tree = {}
    lines = [f"# {domain} — {domain_info.get('description', '')}"]

    for parent_name, parent_info in hierarchy.items():
        children = parent_info.get("children", {})
        parent_entry = {"aliases": parent_info.get("aliases", []), "children": {}}
        lines.append(f"\n## {parent_name}")

        for child_name, child_info in children.items():
            code = child_info.get("code_prefix", "")
            child_entry = {
                "code_prefix": code,
                "aliases": child_info.get("aliases", []),
            }
            lines.append(f"  - {child_name} [{code}*]")

            sub_children = child_info.get("sub_children", {})
            if sub_children:
                child_entry["sub_children"] = {}
                for sub_name, sub_info in sub_children.items():
                    sub_code = sub_info.get("code_prefix", "")
                    child_entry["sub_children"][sub_name] = {
                        "code_prefix": sub_code,
                        "aliases": sub_info.get("aliases", []),
                    }
                    lines.append(f"      - {sub_name} [{sub_code}*]")

            parent_entry["children"][child_name] = child_entry

        tree[parent_name] = parent_entry

    return {
        "status": "ok",
        "domain": domain,
        "description": domain_info.get("description", ""),
        "tree": tree,
        "display": "\n".join(lines),
    }


# ---------------------------------------------------------------------------
# Custom Domain Registration (ADK Tool)
# ---------------------------------------------------------------------------

def register_semantic_domain(
    domain_name: str,
    parent_category: str = "",
    children_json: str = "[]",
    aliases_json: str = "[]",
    unit: str = "",
    description: str = "",
) -> dict:
    """
    [Semantic Tool] Register a custom semantic domain with optional hierarchy.

    Allows users to define business-specific domain categories at runtime,
    without modifying the static YAML catalog.

    Args:
        domain_name: Unique domain identifier (e.g. "SOIL_TYPE", "CROP_VARIETY").
        parent_category: Name of the parent category (e.g. "土壤类型").
        children_json: JSON array of child entries, each with name, code_prefix, aliases.
            Example: '[{"name":"黑土","code_prefix":"S01","aliases":["黑土","black soil"]}]'
        aliases_json: JSON array of alias strings for the domain itself.
        unit: Default unit (e.g. "pH", "mg/kg").
        description: Human-readable description.

    Returns:
        Dict with status and message.
    """
    engine = get_engine()
    if not engine:
        return {"status": "error", "message": "Database not configured"}

    try:
        children = json.loads(children_json)
        aliases = json.loads(aliases_json)
        if not isinstance(children, list) or not isinstance(aliases, list):
            return {"status": "error", "message": "children_json and aliases_json must be JSON arrays"}
    except json.JSONDecodeError as e:
        return {"status": "error", "message": f"Invalid JSON: {e}"}

    owner = current_user_id.get() or "anonymous"

    try:
        with engine.connect() as conn:
            _inject_user_context(conn)
            conn.execute(text(f"""
                INSERT INTO {T_SEMANTIC_DOMAINS}
                    (domain_name, parent_category, children, aliases,
                     unit, description, owner_username, updated_at)
                VALUES (:name, :parent, CAST(:children AS jsonb), :aliases,
                        :unit, :desc, :owner, NOW())
                ON CONFLICT (domain_name, owner_username) DO UPDATE SET
                    parent_category = :parent,
                    children = CAST(:children AS jsonb),
                    aliases = :aliases,
                    unit = :unit,
                    description = :desc,
                    updated_at = NOW()
            """), {
                "name": domain_name, "parent": parent_category,
                "children": json.dumps(children), "aliases": aliases,
                "unit": unit, "desc": description, "owner": owner,
            })
            conn.commit()

        invalidate_semantic_cache()
        return {
            "status": "success",
            "message": f"已注册自定义语义域 '{domain_name}'"
                       + (f"，含 {len(children)} 个子类" if children else ""),
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


# ---------------------------------------------------------------------------
# Column Equivalence Auto-Discovery (ADK Tool)
# ---------------------------------------------------------------------------

def discover_column_equivalences(table_name: str) -> dict:
    """
    [Semantic Tool] Auto-discover code↔name column equivalences in a table.

    Scans column names for common patterns like *_dm/*_mc, *_code/*_name,
    *编码/*名称 pairs and registers them as equivalences.

    Args:
        table_name: The database table to scan.

    Returns:
        Dict with discovered equivalences and status.
    """
    engine = get_engine()
    if not engine:
        return {"status": "error", "message": "Database not configured"}

    # Patterns for code↔name detection
    CODE_SUFFIXES = ["dm", "bm", "code", "id", "编码", "代码"]
    NAME_SUFFIXES = ["mc", "name", "名称", "名"]

    try:
        with engine.connect() as conn:
            _inject_user_context(conn)

            columns = conn.execute(text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = :t ORDER BY ordinal_position"
            ), {"t": table_name}).fetchall()

            if not columns:
                return {"status": "error", "message": f"Table '{table_name}' not found"}

            col_names = [row[0] for row in columns]
            discovered = []

            # Find pairs where columns share a prefix but differ in suffix
            for code_col in col_names:
                code_lower = code_col.lower()
                matched_suffix = None
                prefix = ""

                for suffix in CODE_SUFFIXES:
                    if code_lower.endswith(suffix):
                        prefix = code_lower[:-len(suffix)]
                        matched_suffix = suffix
                        break

                if not prefix or not matched_suffix:
                    continue

                # Look for matching name column
                for name_col in col_names:
                    name_lower = name_col.lower()
                    for name_suffix in NAME_SUFFIXES:
                        if name_lower == prefix + name_suffix:
                            discovered.append({
                                "columns": [code_col, name_col],
                                "relationship": "code_name",
                                "description": f"{code_col} ↔ {name_col}",
                            })
                            break

            if not discovered:
                return {
                    "status": "success",
                    "equivalences": [],
                    "message": f"表 '{table_name}' 中未发现编码↔名称等价列对。",
                }

            return {
                "status": "success",
                "equivalences": discovered,
                "message": f"在表 '{table_name}' 中发现 {len(discovered)} 对等价列:\n"
                           + "\n".join(f"- {e['columns'][0]} ↔ {e['columns'][1]}" for e in discovered),
            }
    except Exception as e:
        return {"status": "error", "message": str(e)}


# ---------------------------------------------------------------------------
# Semantic Model Export (ADK Tool)
# ---------------------------------------------------------------------------

def export_semantic_model(format: str = "json") -> dict:
    """
    [Semantic Tool] Export the full semantic model (catalog + DB annotations) for review.

    Combines static YAML catalog with user-registered annotations and custom domains.

    Args:
        format: Output format — "json" or "summary".

    Returns:
        Dict with the exported model and formatted message.
    """
    catalog = _load_catalog()
    engine = get_engine()

    model = {
        "static_catalog": {
            "domains": list(catalog.get("domains", {}).keys()),
            "region_groups": list(catalog.get("region_groups", {}).keys()),
            "spatial_operations": list(catalog.get("spatial_operations", {}).keys()),
            "equivalences_count": len(catalog.get("equivalences", [])),
        },
        "db_sources": [],
        "db_annotations_count": 0,
        "custom_domains": [],
    }

    if engine:
        try:
            with engine.connect() as conn:
                _inject_user_context(conn)

                # Sources
                try:
                    src_rows = conn.execute(text(f"""
                        SELECT table_name, display_name, geometry_type, srid
                        FROM {T_SEMANTIC_SOURCES}
                        ORDER BY table_name
                    """)).fetchall()
                    model["db_sources"] = [
                        {"table": r[0], "display": r[1] or r[0],
                         "geom": r[2], "srid": r[3]}
                        for r in src_rows
                    ]
                except Exception:
                    pass

                # Annotation count
                try:
                    cnt = conn.execute(text(
                        f"SELECT COUNT(*) FROM {T_SEMANTIC_REGISTRY}"
                    )).scalar()
                    model["db_annotations_count"] = cnt or 0
                except Exception:
                    pass

                # Custom domains
                try:
                    dom_rows = conn.execute(text(f"""
                        SELECT domain_name, parent_category, children, description
                        FROM {T_SEMANTIC_DOMAINS}
                        ORDER BY domain_name
                    """)).fetchall()
                    for row in dom_rows:
                        children = row[2] if isinstance(row[2], list) else json.loads(row[2] or "[]")
                        model["custom_domains"].append({
                            "domain": row[0],
                            "parent": row[1] or "",
                            "children_count": len(children),
                            "description": row[3] or "",
                        })
                except Exception:
                    pass
        except Exception:
            pass

    # Build summary message
    lines = [
        "语义模型概览:",
        f"  静态域: {len(model['static_catalog']['domains'])} 个 "
        f"({', '.join(model['static_catalog']['domains'][:5])}...)",
        f"  区域组: {len(model['static_catalog']['region_groups'])} 个",
        f"  空间操作: {len(model['static_catalog']['spatial_operations'])} 个",
        f"  等价列规则: {model['static_catalog']['equivalences_count']} 组",
        f"  DB数据源: {len(model['db_sources'])} 个",
        f"  DB列注解: {model['db_annotations_count']} 条",
        f"  自定义域: {len(model['custom_domains'])} 个",
    ]

    if model["custom_domains"]:
        lines.append("  自定义域列表:")
        for d in model["custom_domains"]:
            lines.append(f"    - {d['domain']}: {d['description']} ({d['children_count']} 子类)")

    return {
        "status": "success",
        "model": model,
        "message": "\n".join(lines),
    }


# ---------------------------------------------------------------------------
# Semantic Metrics (v12.2) — business metric definitions
# ---------------------------------------------------------------------------

T_SEMANTIC_METRICS = "agent_semantic_metrics"


def register_metric(metric_name: str, definition: str, domain: str = "",
                    description: str = "", unit: str = "", aliases: str = "") -> dict:
    """
    [Semantic Tool] Register a business metric definition.

    Args:
        metric_name: Metric name (e.g. "植被覆盖率").
        definition: SQL expression or formula (e.g. "SUM(CASE WHEN ndvi > 0.3 THEN area ELSE 0 END) / SUM(area) * 100").
        domain: Related semantic domain (e.g. "LAND_USE").
        description: Human-readable description.
        unit: Unit of measurement (e.g. "%", "m²").
        aliases: Comma-separated alternative names.

    Returns:
        Dict with status and metric id.
    """
    engine = get_engine()
    if not engine:
        return {"status": "error", "message": "Database not configured"}

    owner = current_user_id.get() or "system"
    try:
        with engine.connect() as conn:
            result = conn.execute(text(f"""
                INSERT INTO {T_SEMANTIC_METRICS}
                    (metric_name, definition, domain, description, unit, aliases, owner_username)
                VALUES (:name, :def, :domain, :desc, :unit, :aliases, :owner)
                ON CONFLICT (metric_name, owner_username)
                DO UPDATE SET definition = EXCLUDED.definition,
                    domain = EXCLUDED.domain, description = EXCLUDED.description,
                    unit = EXCLUDED.unit, aliases = EXCLUDED.aliases
                RETURNING id
            """), {
                "name": metric_name.strip(), "def": definition.strip(),
                "domain": domain, "desc": description, "unit": unit,
                "aliases": aliases, "owner": owner,
            })
            row = result.fetchone()
            conn.commit()
            return {"status": "success", "id": row[0], "metric_name": metric_name}
    except Exception as e:
        return {"status": "error", "message": str(e)}


def resolve_metric(user_text: str) -> dict:
    """
    [Semantic Tool] Resolve a natural language metric reference to its SQL definition.

    Args:
        user_text: User's natural language (e.g. "植被覆盖率" or "建筑密度").

    Returns:
        Dict with matched metric definition or empty if no match.
    """
    engine = get_engine()
    if not engine:
        return {"status": "error", "message": "Database not configured"}

    try:
        with engine.connect() as conn:
            rows = conn.execute(text(f"""
                SELECT id, metric_name, definition, domain, description, unit, aliases
                FROM {T_SEMANTIC_METRICS}
                ORDER BY metric_name
            """)).fetchall()

        if not rows:
            return {"status": "success", "matched": False, "message": "No metrics registered"}

        user_lower = user_text.lower()
        best_match = None
        best_score = 0.0

        for r in rows:
            name = r[1] or ""
            aliases_str = r[6] or ""
            all_names = [name] + [a.strip() for a in aliases_str.split(",") if a.strip()]

            for candidate in all_names:
                # Exact match
                if user_lower == candidate.lower():
                    best_match = r
                    best_score = 1.0
                    break
                # Substring match
                if candidate.lower() in user_lower or user_lower in candidate.lower():
                    score = 0.8
                    if score > best_score:
                        best_match = r
                        best_score = score
                # Fuzzy match
                from difflib import SequenceMatcher
                ratio = SequenceMatcher(None, user_lower, candidate.lower()).ratio()
                if ratio > best_score and ratio >= 0.5:
                    best_match = r
                    best_score = ratio

            if best_score >= 1.0:
                break

        if best_match and best_score >= 0.5:
            return {
                "status": "success", "matched": True,
                "metric": {
                    "id": best_match[0], "name": best_match[1],
                    "definition": best_match[2], "domain": best_match[3],
                    "description": best_match[4], "unit": best_match[5],
                },
                "confidence": round(best_score, 2),
                "message": f"度量 '{best_match[1]}' 的定义: {best_match[2]}",
            }
        return {"status": "success", "matched": False, "message": f"No metric matching '{user_text}'"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


def list_metrics(domain: str = None) -> dict:
    """
    [Semantic Tool] List registered business metrics.

    Args:
        domain: Optional domain filter (e.g. "LAND_USE").

    Returns:
        Dict with list of metrics.
    """
    engine = get_engine()
    if not engine:
        return {"status": "error", "message": "Database not configured"}

    try:
        with engine.connect() as conn:
            if domain:
                rows = conn.execute(text(f"""
                    SELECT id, metric_name, definition, domain, description, unit
                    FROM {T_SEMANTIC_METRICS} WHERE domain = :domain
                    ORDER BY metric_name
                """), {"domain": domain}).fetchall()
            else:
                rows = conn.execute(text(f"""
                    SELECT id, metric_name, definition, domain, description, unit
                    FROM {T_SEMANTIC_METRICS} ORDER BY metric_name
                """)).fetchall()

        metrics = [{
            "id": r[0], "name": r[1], "definition": r[2],
            "domain": r[3], "description": r[4], "unit": r[5],
        } for r in rows]

        return {"status": "success", "count": len(metrics), "metrics": metrics}
    except Exception as e:
        return {"status": "error", "message": str(e)}


def seed_builtin_metrics() -> int:
    """Insert built-in metric definitions if they don't exist. Returns count inserted."""
    engine = get_engine()
    if not engine:
        return 0

    _BUILTIN_METRICS = [
        {
            "metric_name": "植被覆盖率",
            "definition": "SUM(CASE WHEN ndvi > 0.3 THEN area ELSE 0 END) / SUM(area) * 100",
            "domain": "LAND_USE",
            "description": "NDVI > 0.3 的面积占总面积的百分比",
            "unit": "%",
            "aliases": "vegetation coverage,绿化率,植被指数覆盖",
        },
        {
            "metric_name": "建筑密度",
            "definition": "SUM(building_area) / total_area * 100",
            "domain": "LAND_USE",
            "description": "建筑占地面积与用地面积之比",
            "unit": "%",
            "aliases": "building density,建筑覆盖率",
        },
        {
            "metric_name": "碎片化指数",
            "definition": "1 - (max_patch_area / total_area)",
            "domain": "LAND_USE",
            "description": "最大斑块面积占比的补数，值越大碎片化越严重",
            "unit": "",
            "aliases": "fragmentation index,景观碎片化,斑块碎片度",
        },
        {
            "metric_name": "人口密度",
            "definition": "population / area_km2",
            "domain": "POPULATION",
            "description": "每平方公里人口数",
            "unit": "人/km²",
            "aliases": "population density,人口集中度",
        },
        {
            "metric_name": "坡度均值",
            "definition": "AVG(slope_degrees)",
            "domain": "SLOPE",
            "description": "区域内坡度的算术平均值",
            "unit": "°",
            "aliases": "mean slope,平均坡度",
        },
    ]

    inserted = 0
    try:
        with engine.connect() as conn:
            for m in _BUILTIN_METRICS:
                existing = conn.execute(text(
                    f"SELECT 1 FROM {T_SEMANTIC_METRICS} "
                    f"WHERE metric_name = :name AND owner_username = 'system'"
                ), {"name": m["metric_name"]}).fetchone()
                if existing:
                    continue
                conn.execute(text(f"""
                    INSERT INTO {T_SEMANTIC_METRICS}
                        (metric_name, definition, domain, description, unit, aliases, owner_username)
                    VALUES (:name, :def, :domain, :desc, :unit, :aliases, 'system')
                """), {
                    "name": m["metric_name"], "def": m["definition"],
                    "domain": m["domain"], "desc": m["description"],
                    "unit": m["unit"], "aliases": m["aliases"],
                })
                inserted += 1
            conn.commit()
    except Exception as e:
        logger.warning("[Semantic] Failed to seed metrics: %s", e)
    return inserted
