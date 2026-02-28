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
        return {"status": "error", "message": "模板名称不能为空。"}

    template_name = template_name.strip()[:200]

    filtered = _filter_tool_sequence(tool_sequence or [])
    if not filtered:
        return {"status": "error", "message": "当前分析流程中没有可保存的有效工具调用。"}

    engine = get_engine()
    if not engine:
        return {"status": "error", "message": "数据库未配置，无法保存模板。"}

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
            "message": f"模板「{template_name}」已保存（{len(filtered)} 个步骤）。",
        }
    except Exception as e:
        return {"status": "error", "message": f"保存模板失败: {e}"}


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
        return {"status": "error", "message": "数据库未配置。"}

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
            msg = "暂无可用模板。" if not keyword else f"未找到匹配「{keyword}」的模板。"
            return {"status": "success", "message": msg, "templates": []}

        PIPE_CN = {
            "optimization": "空间优化", "governance": "数据治理",
            "general": "通用分析", "planner": "动态规划",
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

            tag = "[我的]" if is_own else f"[共享·{r[3]}]"
            pipe = PIPE_CN.get(r[5], r[5])
            desc_short = f" — {r[2][:60]}" if r[2] else ""
            lines.append(f"  {r[0]}. **{r[1]}** {tag} | {pipe} | 使用 {r[7]} 次{desc_short}")

        msg = f"找到 {len(templates)} 个模板：\n" + "\n".join(lines)
        return {"status": "success", "message": msg, "templates": templates}

    except Exception as e:
        return {"status": "error", "message": f"查询模板失败: {e}"}


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
        return {"status": "error", "message": "无效的模板 ID。"}

    engine = get_engine()
    if not engine:
        return {"status": "error", "message": "数据库未配置。"}

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
            return {"status": "error", "message": "模板不存在或您无权删除。"}

        return {"status": "success", "message": f"模板 #{template_id} 已删除。"}
    except Exception as e:
        return {"status": "error", "message": f"删除失败: {e}"}


def share_template(template_id: int) -> dict:
    """
    将一个模板设为共享，使其他用户也可以浏览和使用。

    Args:
        template_id: 要共享的模板 ID（仅拥有者可操作）。

    Returns:
        操作结果 dict。
    """
    if not isinstance(template_id, int) or template_id <= 0:
        return {"status": "error", "message": "无效的模板 ID。"}

    engine = get_engine()
    if not engine:
        return {"status": "error", "message": "数据库未配置。"}

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
            return {"status": "error", "message": "模板不存在或您无权操作。"}

        return {"status": "success", "message": f"模板 #{template_id} 已设为共享。"}
    except Exception as e:
        return {"status": "error", "message": f"共享失败: {e}"}


def generate_plan_from_template(template: dict) -> str:
    """
    Convert a template's tool_sequence into a [分析方案] text block.
    File path arguments are omitted so the LLM adapts to user's actual files.
    """
    name = template.get("name", "")
    description = template.get("description", "")
    source_query = template.get("source_query", "")
    tool_sequence = template.get("tool_sequence", [])

    lines = [
        f"（基于模板「{name}」）",
    ]
    if description:
        lines.append(f"模板说明: {description}")
    if source_query:
        lines.append(f"原始任务: {source_query[:200]}")

    lines.append("")
    lines.append("**分析目标**: 按以下模板步骤执行分析，根据当前数据适配参数。")
    lines.append("")
    lines.append("**执行步骤**:")

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

        step_line = f"{i}. 调用 `{tool_name}`"
        if param_parts:
            step_line += f"（参数: {', '.join(param_parts)}）"
        if agent_name:
            step_line += f" [via {agent_name}]"

        lines.append(step_line)

    lines.append("")
    lines.append("**注意事项**: 请根据用户当前上传的数据文件自动适配文件路径和列名参数。")

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
