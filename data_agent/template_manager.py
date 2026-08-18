"""
Template Manager — Save, browse, and apply reusable GIS analysis templates.

PRD F6: Users save analysis workflows (tool_execution_log) as templates,
browse/share them, and apply to new data via plan injection.
"""
import json
from typing import Optional, List, Dict

from sqlalchemy import text

from .db_engine import get_engine
from .database_tools import _inject_user_context, T_ANALYSIS_TEMPLATES
from .code_exporter import NON_EXPORTABLE_TOOLS, _PATH_ARG_NAMES
from .user_context import current_user_id
from .i18n import t as translate


def ensure_templates_table():
    """Create analysis_templates table if not exists. Called at startup."""
    engine = get_engine()
    if not engine:
        print("[Templates] WARNING: Database not configured. Template system disabled.")
        return

    try:
        with engine.connect() as conn:
            conn.execute(text(f"""
                CREATE TABLE IF NOT EXISTS {T_ANALYSIS_TEMPLATES} (
                    id SERIAL PRIMARY KEY,
                    template_name VARCHAR(200) NOT NULL,
                    description TEXT DEFAULT '',
                    owner_username VARCHAR(100) NOT NULL,
                    is_shared BOOLEAN DEFAULT FALSE,
                    pipeline_type VARCHAR(30) NOT NULL,
                    intent VARCHAR(30) NOT NULL,
                    tool_sequence JSONB NOT NULL,
                    source_query TEXT DEFAULT '',
                    use_count INT DEFAULT 0,
                    created_at TIMESTAMP DEFAULT NOW(),
                    updated_at TIMESTAMP DEFAULT NOW(),
                    UNIQUE(owner_username, template_name)
                )
            """))
            conn.execute(text(
                f"CREATE INDEX IF NOT EXISTS idx_templates_owner "
                f"ON {T_ANALYSIS_TEMPLATES} (owner_username)"
            ))
            conn.execute(text(
                f"CREATE INDEX IF NOT EXISTS idx_templates_shared "
                f"ON {T_ANALYSIS_TEMPLATES} (is_shared, created_at DESC)"
            ))
            conn.commit()
        print("[Templates] Analysis templates table ready.")
    except Exception as e:
        print(f"[Templates] Error initializing templates table: {e}")


def _filter_tool_sequence(tool_log: List[Dict]) -> List[Dict]:
    """Filter out error steps and NON_EXPORTABLE_TOOLS from a tool log."""
    return [
        record for record in tool_log
        if not record.get("is_error")
        and record.get("tool_name") not in NON_EXPORTABLE_TOOLS
    ]


def save_as_template(
    template_name: str,
    description: str,
    tool_sequence: List[Dict],
    pipeline_type: str,
    intent: str,
    source_query: str = "",
) -> dict:
    """
    保存当前分析流程为可复用模板。

    Args:
        template_name: 模板名称（必填，最多200字符）。
        description: 模板描述（可选）。
        tool_sequence: 工具执行日志（由系统自动传入）。
        pipeline_type: 管线类型（optimization/governance/general/planner）。
        intent: 意图类型（GENERAL/GOVERNANCE/OPTIMIZATION）。
        source_query: 原始用户查询文本。

    Returns:
        操作结果 dict。
    """
    if not template_name or not template_name.strip():
        return {"status": "error", "message": translate("template.name_empty")}

    template_name = template_name.strip()[:200]

    filtered = _filter_tool_sequence(tool_sequence or [])
    if not filtered:
        return {"status": "error", "message": translate("template.no_steps")}

    engine = get_engine()
    if not engine:
        return {"status": "error", "message": translate("template.db_unavailable")}

    username = current_user_id.get()
    try:
        with engine.connect() as conn:
            _inject_user_context(conn)
            conn.execute(text(f"""
                INSERT INTO {T_ANALYSIS_TEMPLATES}
                    (template_name, description, owner_username, pipeline_type,
                     intent, tool_sequence, source_query)
                VALUES (:name, :desc, :owner, :pipe, :intent,
                        CAST(:seq AS jsonb), :query)
                ON CONFLICT (owner_username, template_name) DO UPDATE SET
                    description = EXCLUDED.description,
                    pipeline_type = EXCLUDED.pipeline_type,
                    intent = EXCLUDED.intent,
                    tool_sequence = EXCLUDED.tool_sequence,
                    source_query = EXCLUDED.source_query,
                    updated_at = NOW()
            """), {
                "name": template_name,
                "desc": description or "",
                "owner": username,
                "pipe": pipeline_type,
                "intent": intent,
                "seq": json.dumps(filtered, ensure_ascii=False),
                "query": source_query[:1000] if source_query else "",
            })
            conn.commit()

        return {
            "status": "success",
            "message": translate(
                "template.saved", name=template_name, count=len(filtered)
            ),
        }
    except Exception as e:
        return {"status": "error", "message": translate("template.save_failed", error=e)}


def list_templates(keyword: str = "") -> dict:
    """
    浏览分析模板（自己的 + 共享的）。

    Args:
        keyword: 可选搜索关键词，匹配模板名称或描述。

    Returns:
        模板列表 dict。
    """
    engine = get_engine()
    if not engine:
        return {"status": "error", "message": translate("template.db_unavailable")}

    username = current_user_id.get()
    try:
        with engine.connect() as conn:
            _inject_user_context(conn)

            where = "(owner_username = :u OR is_shared = TRUE)"
            params = {"u": username, "lim": 50}

            if keyword and keyword.strip():
                where += " AND (template_name ILIKE :kw OR description ILIKE :kw)"
                params["kw"] = f"%{keyword.strip()}%"

            rows = conn.execute(text(f"""
                SELECT id, template_name, description, owner_username,
                       is_shared, pipeline_type, intent, use_count, created_at
                FROM {T_ANALYSIS_TEMPLATES}
                WHERE {where}
                ORDER BY
                    CASE WHEN owner_username = :u THEN 0 ELSE 1 END,
                    updated_at DESC
                LIMIT :lim
            """), params).fetchall()

        if not rows:
            msg = (
                translate("template.no_templates")
                if not keyword
                else translate("template.no_match", keyword=keyword)
            )
            return {"status": "success", "message": msg, "templates": []}

        pipeline_keys = {
            "optimization": "template.pipeline_optimization",
            "governance": "template.pipeline_governance",
            "general": "template.pipeline_general",
            "planner": "template.pipeline_planner",
        }

        templates = []
        lines = []
        for r in rows:
            is_own = r[3] == username
            t = {
                "id": r[0], "name": r[1], "description": r[2],
                "owner": r[3], "is_own": is_own,
                "is_shared": r[4], "pipeline_type": r[5],
                "intent": r[6], "use_count": r[7],
            }
            templates.append(t)

            tag = (
                translate("template.tag_own")
                if is_own
                else translate("template.tag_shared_owner", owner=r[3])
            )
            pipe = translate(pipeline_keys.get(r[5], "template.pipeline_unknown"), value=r[5])
            desc_short = f" — {r[2][:60]}" if r[2] else ""
            lines.append(translate(
                "template.list_item", id=r[0], name=r[1], tag=tag,
                pipeline=pipe, uses=r[7], description=desc_short,
            ))

        msg = translate("template.list_found", count=len(templates)) + "\n" + "\n".join(lines)
        return {"status": "success", "message": msg, "templates": templates}

    except Exception as e:
        return {"status": "error", "message": translate("template.list_failed", error=e)}


def get_template(template_id: int) -> Optional[dict]:
    """
    Fetch a full template by ID (internal use).

    Returns:
        Template dict with tool_sequence, or None if not found / no access.
    """
    engine = get_engine()
    if not engine:
        return None

    username = current_user_id.get()
    try:
        with engine.connect() as conn:
            _inject_user_context(conn)
            row = conn.execute(text(f"""
                SELECT id, template_name, description, owner_username,
                       is_shared, pipeline_type, intent, tool_sequence,
                       source_query, use_count
                FROM {T_ANALYSIS_TEMPLATES}
                WHERE id = :id AND (owner_username = :u OR is_shared = TRUE)
            """), {"id": template_id, "u": username}).fetchone()

        if not row:
            return None

        seq = row[7] if isinstance(row[7], list) else json.loads(row[7] or "[]")
        return {
            "id": row[0], "name": row[1], "description": row[2],
            "owner": row[3], "is_shared": row[4],
            "pipeline_type": row[5], "intent": row[6],
            "tool_sequence": seq, "source_query": row[8],
            "use_count": row[9],
        }
    except Exception:
        return None


def delete_template(template_id: int) -> dict:
    """
    删除一个分析模板（仅模板拥有者可操作）。

    Args:
        template_id: 要删除的模板 ID。

    Returns:
        操作结果 dict。
    """
    if not isinstance(template_id, int) or template_id <= 0:
        return {"status": "error", "message": translate("template.invalid_id")}

    engine = get_engine()
    if not engine:
        return {"status": "error", "message": translate("template.db_unavailable")}

    username = current_user_id.get()
    try:
        with engine.connect() as conn:
            _inject_user_context(conn)
            result = conn.execute(text(f"""
                DELETE FROM {T_ANALYSIS_TEMPLATES}
                WHERE id = :id AND owner_username = :u
            """), {"id": template_id, "u": username})
            conn.commit()

        if result.rowcount == 0:
            return {"status": "error", "message": translate("template.delete_denied")}

        return {"status": "success", "message": translate("template.deleted", id=template_id)}
    except Exception as e:
        return {"status": "error", "message": translate("template.delete_failed", error=e)}


def share_template(template_id: int) -> dict:
    """
    将一个模板设为共享，使其他用户也可以浏览和使用。

    Args:
        template_id: 要共享的模板 ID（仅拥有者可操作）。

    Returns:
        操作结果 dict。
    """
    if not isinstance(template_id, int) or template_id <= 0:
        return {"status": "error", "message": translate("template.invalid_id")}

    engine = get_engine()
    if not engine:
        return {"status": "error", "message": translate("template.db_unavailable")}

    username = current_user_id.get()
    try:
        with engine.connect() as conn:
            _inject_user_context(conn)
            result = conn.execute(text(f"""
                UPDATE {T_ANALYSIS_TEMPLATES}
                SET is_shared = TRUE, updated_at = NOW()
                WHERE id = :id AND owner_username = :u
            """), {"id": template_id, "u": username})
            conn.commit()

        if result.rowcount == 0:
            return {"status": "error", "message": translate("template.share_denied")}

        return {"status": "success", "message": translate("template.shared", id=template_id)}
    except Exception as e:
        return {"status": "error", "message": translate("template.share_failed", error=e)}


def generate_plan_from_template(template: dict) -> str:
    """
    Convert a template's tool_sequence into a [分析方案] text block.
    File path arguments are omitted so the LLM adapts to user's actual files.
    """
    name = template.get("name", "")
    description = template.get("description", "")
    source_query = template.get("source_query", "")
    tool_sequence = template.get("tool_sequence", [])

    lines = [translate("template.plan_title", name=name)]
    if description:
        lines.append(translate("template.plan_description", description=description))
    if source_query:
        lines.append(translate("template.plan_source", query=source_query[:200]))

    lines.append("")
    lines.append(translate("template.plan_goal"))
    lines.append("")
    lines.append(translate("template.plan_steps"))

    for i, record in enumerate(tool_sequence, 1):
        tool_name = record.get("tool_name", "unknown")
        agent_name = record.get("agent_name", "")
        args = record.get("args", {})

        # Build param hints (omit file paths — LLM adapts those)
        param_parts = []
        for k, v in args.items():
            if k in _PATH_ARG_NAMES:
                continue
            if isinstance(v, str) and (
                "/" in v or "\\" in v
                or v.endswith((".shp", ".csv", ".tif", ".geojson", ".gpkg"))
            ):
                continue
            # Truncate long values
            val_str = str(v)
            if len(val_str) > 60:
                val_str = val_str[:57] + "..."
            param_parts.append(f"{k}={val_str}")

        step_line = translate("template.plan_step", idx=i, tool_name=tool_name)
        if param_parts:
            step_line += translate("template.plan_step_params", params=", ".join(param_parts))
        if agent_name:
            step_line += translate("template.plan_step_agent", agent=agent_name)

        lines.append(step_line)

    lines.append("")
    lines.append(translate("template.plan_notes"))

    return "\n".join(lines)


def _increment_use_count(template_id: int) -> None:
    """Bump use_count by 1 for a template. Non-fatal."""
    engine = get_engine()
    if not engine:
        return

    try:
        with engine.connect() as conn:
            conn.execute(text(f"""
                UPDATE {T_ANALYSIS_TEMPLATES}
                SET use_count = use_count + 1, updated_at = NOW()
                WHERE id = :id
            """), {"id": template_id})
            conn.commit()
    except Exception:
        pass
