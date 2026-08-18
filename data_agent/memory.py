"""
Spatial Memory System for per-user persistent preferences, regions, and analysis history.
Stores memories in PostgreSQL (user_memories table) with JSONB values.
"""
import json
import logging
import os
import re
from sqlalchemy import text

from .db_engine import get_engine
from .database_tools import _inject_user_context, T_USER_MEMORIES
from .i18n import t
from .user_context import current_user_id

VALID_MEMORY_TYPES = ("region", "viz_preference", "analysis_result", "custom", "analysis_perspective", "auto_extract")

AUTO_EXTRACT_QUOTA = 100  # max auto_extract memories per user

logger = logging.getLogger("data_agent.memory")


def ensure_memory_table():
    """Create user_memories table if not exists. Called at startup alongside ensure_users_table()."""
    engine = get_engine()
    if not engine:
        print("[Memory] WARNING: Database not configured. Memory system disabled.")
        return

    try:
        with engine.connect() as conn:
            conn.execute(text(f"""
                CREATE TABLE IF NOT EXISTS {T_USER_MEMORIES} (
                    id SERIAL PRIMARY KEY,
                    username VARCHAR(100) NOT NULL,
                    memory_type VARCHAR(30) NOT NULL,
                    memory_key VARCHAR(200) NOT NULL,
                    memory_value JSONB NOT NULL,
                    description TEXT DEFAULT '',
                    created_at TIMESTAMP DEFAULT NOW(),
                    updated_at TIMESTAMP DEFAULT NOW(),
                    UNIQUE(username, memory_type, memory_key)
                )
            """))
            conn.execute(text(
                f"CREATE INDEX IF NOT EXISTS idx_user_memories_user ON {T_USER_MEMORIES} (username)"
            ))
            conn.execute(text(
                f"CREATE INDEX IF NOT EXISTS idx_user_memories_type ON {T_USER_MEMORIES} (username, memory_type)"
            ))
            conn.commit()
        print("[Memory] Memory table ready.")
    except Exception as e:
        print(f"[Memory] Error initializing memory table: {e}")


def save_memory(memory_type: str, key: str, value: str, description: str = "") -> dict:
    """
    保存或更新一条用户空间记忆。

    Args:
        memory_type: 记忆类型，可选: region（常用区域）, viz_preference（可视化偏好）, analysis_result（分析结果）, custom（自定义）
        key: 记忆名称，如 "华东区域"、"默认配色方案"
        value: JSON 格式的记忆内容。例如: '{"districts": ["上海市", "江苏省"]}'
        description: 可选的说明文字
    Returns:
        操作结果 dict
    """
    if memory_type not in VALID_MEMORY_TYPES:
        return {"status": "error", "message": t(
            "memory.invalid_type", memory_type=memory_type, types=", ".join(VALID_MEMORY_TYPES)
        )}

    try:
        parsed_value = json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return {"status": "error", "message": t("memory.invalid_json")}

    engine = get_engine()
    if not engine:
        return {"status": "error", "message": t("memory.db_save_unavailable")}

    username = current_user_id.get()
    try:
        with engine.connect() as conn:
            _inject_user_context(conn)
            conn.execute(text(f"""
                INSERT INTO {T_USER_MEMORIES} (username, memory_type, memory_key, memory_value, description)
                VALUES (:u, :t, :k, :v, :d)
                ON CONFLICT (username, memory_type, memory_key)
                DO UPDATE SET memory_value = :v, description = :d, updated_at = NOW()
            """), {"u": username, "t": memory_type, "k": key,
                   "v": json.dumps(parsed_value, ensure_ascii=False), "d": description})
            conn.commit()
        return {"status": "success", "message": t(
            "memory.saved", memory_type=memory_type, key=key
        )}
    except Exception as e:
        return {"status": "error", "message": t("memory.save_failed", error=e)}


def recall_memories(memory_type: str = "", keyword: str = "") -> dict:
    """
    搜索用户的空间记忆。可按类型过滤，也可按关键词模糊搜索。

    Args:
        memory_type: 可选，按类型过滤: region, viz_preference, analysis_result, custom。留空返回所有类型。
        keyword: 可选，按关键词模糊搜索记忆名称和描述
    Returns:
        匹配的记忆列表
    """
    engine = get_engine()
    if not engine:
        return {"status": "error", "message": t("memory.db_unavailable")}

    username = current_user_id.get()
    try:
        with engine.connect() as conn:
            _inject_user_context(conn)
            conditions = ["username = :u"]
            params = {"u": username}

            if memory_type and memory_type in VALID_MEMORY_TYPES:
                conditions.append("memory_type = :t")
                params["t"] = memory_type

            if keyword:
                conditions.append("(memory_key ILIKE :kw OR description ILIKE :kw)")
                params["kw"] = f"%{keyword}%"

            where = " AND ".join(conditions)
            rows = conn.execute(text(
                f"SELECT id, memory_type, memory_key, memory_value, description, updated_at "
                f"FROM {T_USER_MEMORIES} WHERE {where} ORDER BY updated_at DESC LIMIT 20"
            ), params).fetchall()

            memories = []
            for r in rows:
                memories.append({
                    "id": r[0], "type": r[1], "key": r[2],
                    "value": r[3] if isinstance(r[3], dict) else json.loads(r[3]) if r[3] else {},
                    "description": r[4],
                    "updated_at": str(r[5]),
                })

            return {
                "status": "success",
                "memories": memories,
                "message": t("memory.found", count=len(memories)) if memories else t("memory.not_found"),
            }
    except Exception as e:
        return {"status": "error", "message": t("memory.recall_failed", error=e)}


def list_memories() -> dict:
    """
    列出当前用户的所有空间记忆，按最近更新排序。
    Returns:
        记忆列表，包含id、类型、名称和描述
    """
    return recall_memories()


def delete_memory(memory_id: str) -> dict:
    """
    删除指定的空间记忆。仅允许删除当前用户自己的记忆。

    Args:
        memory_id: 要删除的记忆ID（数字）
    Returns:
        删除结果
    """
    engine = get_engine()
    if not engine:
        return {"status": "error", "message": t("memory.db_unavailable")}

    username = current_user_id.get()
    try:
        mid = int(memory_id)
    except (ValueError, TypeError):
        return {"status": "error", "message": t("memory.id_invalid")}

    try:
        with engine.connect() as conn:
            _inject_user_context(conn)
            result = conn.execute(text(
                f"DELETE FROM {T_USER_MEMORIES} WHERE id = :id AND username = :u"
            ), {"id": mid, "u": username})
            conn.commit()
            if result.rowcount > 0:
                return {"status": "success", "message": t("memory.deleted", id=mid)}
            else:
                return {"status": "error", "message": t("memory.id_not_found", id=mid)}
    except Exception as e:
        return {"status": "error", "message": t("memory.delete_failed", error=e)}


# --- Internal helpers (not registered as ADK tools) ---

def get_user_preferences() -> dict:
    """
    Fetch the current user's visualization preferences for prompt injection.
    Returns a merged dict like {"basemap": "CartoDB dark_matter", "color_scheme": "YlGnBu"}
    or empty dict if no preferences saved.
    """
    engine = get_engine()
    if not engine:
        return {}

    username = current_user_id.get()
    try:
        with engine.connect() as conn:
            _inject_user_context(conn)
            rows = conn.execute(text(
                f"SELECT memory_value FROM {T_USER_MEMORIES} "
                "WHERE username = :u AND memory_type = 'viz_preference' "
                "ORDER BY updated_at DESC LIMIT 10"
            ), {"u": username}).fetchall()

            merged = {}
            for r in reversed(rows):  # oldest first so newest overwrites
                val = r[0] if isinstance(r[0], dict) else json.loads(r[0]) if r[0] else {}
                merged.update(val)
            return merged
    except Exception:
        return {}


def get_recent_analysis_results(limit: int = 5) -> list:
    """
    Fetch user's recent analysis_result memories for context injection.
    Returns list of dicts with key, description, value.
    """
    engine = get_engine()
    if not engine:
        return []

    username = current_user_id.get()
    try:
        with engine.connect() as conn:
            _inject_user_context(conn)
            rows = conn.execute(text(
                f"SELECT memory_key, description, memory_value FROM {T_USER_MEMORIES} "
                "WHERE username = :u AND memory_type = 'analysis_result' "
                "ORDER BY updated_at DESC LIMIT :lim"
            ), {"u": username, "lim": limit}).fetchall()

            results = []
            for r in rows:
                val = r[2] if isinstance(r[2], dict) else json.loads(r[2]) if r[2] else {}
                results.append({"key": r[0], "description": r[1], "value": val})
            return results
    except Exception:
        return []


def get_analysis_perspective() -> str:
    """Fetch the current user's analysis perspective text for prompt injection.

    Returns the perspective string, or empty string if none set.
    """
    engine = get_engine()
    if not engine:
        return ""

    username = current_user_id.get()
    try:
        with engine.connect() as conn:
            _inject_user_context(conn)
            row = conn.execute(text(
                f"SELECT memory_value FROM {T_USER_MEMORIES} "
                "WHERE username = :u AND memory_type = 'analysis_perspective' "
                "ORDER BY updated_at DESC LIMIT 1"
            ), {"u": username}).fetchone()

            if row:
                val = row[0] if isinstance(row[0], dict) else json.loads(row[0]) if row[0] else {}
                return val.get("perspective", "")
            return ""
    except Exception:
        return ""


def _memory_extract_model_name() -> str:
    """Return the configured model used by Memory ETL fact extraction."""
    explicit = os.environ.get("MEMORY_EXTRACT_MODEL", "").strip()
    if explicit:
        return explicit
    try:
        from .model_config import get_config_manager
        return get_config_manager().get_tier_model("fast")
    except Exception:
        return os.environ.get("MODEL_FAST", "gemini-2.0-flash")


def _strip_json_fences(raw: str) -> str:
    text_value = str(raw or "").strip()
    if text_value.startswith("```"):
        text_value = text_value.split("\n", 1)[-1] if "\n" in text_value else text_value[3:]
        if text_value.endswith("```"):
            text_value = text_value[:-3].strip()
    if not text_value.startswith("["):
        start = text_value.find("[")
        end = text_value.rfind("]")
        if start >= 0 and end > start:
            text_value = text_value[start:end + 1]
    return text_value.strip()


def _parse_fact_json(raw: str) -> list[dict]:
    try:
        facts = json.loads(_strip_json_fences(raw))
    except Exception:
        return []
    if not isinstance(facts, list):
        return []

    valid = []
    for fact in facts[:5]:
        if not isinstance(fact, dict):
            continue
        key = str(fact.get("key", "")).strip()
        value = fact.get("value", "")
        if not key or value in ("", None):
            continue
        category = str(fact.get("category", "data_characteristic")).strip()
        if category not in {"data_characteristic", "analysis_conclusion", "user_preference"}:
            category = "data_characteristic"
        valid.append({"key": key[:80], "value": str(value), "category": category})
    return valid


def _call_memory_extract_model(prompt: str) -> str:
    """Call the configured extraction model and return raw text."""
    model_name = _memory_extract_model_name()
    from .model_gateway import ModelRegistry, create_model

    ModelRegistry._ensure_initialized()
    info = ModelRegistry.get_model_info(model_name)
    backend = info.get("backend")

    if backend == "gemini" or model_name.startswith("gemini"):
        from google import genai as genai_client

        client = genai_client.Client()
        response = client.models.generate_content(
            model=model_name,
            contents=prompt,
        )
        return (response.text or "").strip()

    adk_model = create_model(model_name)
    completion_kwargs = {
        "model": getattr(adk_model, "model", None) or info.get("model_id", model_name),
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.0,
        "max_tokens": 768,
    }

    additional_args = getattr(adk_model, "_additional_args", {}) or {}
    extra_body = additional_args.get("extra_body") or info.get("extra_body")
    if extra_body:
        completion_kwargs["extra_body"] = extra_body
    timeout_cap = float(os.environ.get("MEMORY_EXTRACT_TIMEOUT", "90"))
    timeout = additional_args.get("timeout") or info.get("request_timeout")
    completion_kwargs["timeout"] = min(float(timeout), timeout_cap) if timeout else timeout_cap

    import litellm

    response = litellm.completion(**completion_kwargs)
    message = response.choices[0].message
    if isinstance(message, dict):
        return (message.get("content") or "").strip()
    return (getattr(message, "content", "") or "").strip()


def _first_metric_line(text_value: str) -> str:
    metric_re = re.compile(
        r"^\s*([^:\n：]{2,32}(?:数量|总长度|面积|结果|奖励|收益|Reward|Blocks|Parcels)[^:\n：]*)[：:]\s*([^\n]{1,80})",
        re.IGNORECASE,
    )
    for line in text_value.splitlines():
        match = metric_re.search(line.strip())
        if match and re.search(r"\d", match.group(2)):
            return f"{match.group(1).strip()}：{match.group(2).strip()}"
    return ""


def _extract_world_model_fact(text_value: str) -> dict | None:
    lower_text = text_value.lower()
    if not any(token in lower_text for token in ("worldmodel", "world model", "世界模型", "mpc")):
        return None

    dataset = ""
    if "dongxing" in lower_text or "东兴" in text_value:
        dataset = "Dongxing"
    elif "bishan" in lower_text or "璧山" in text_value:
        dataset = "Bishan"

    fields = []
    for label in ("N Blocks", "N Parcels", "Steps Run", "Swaps Completed", "Total Reward"):
        match = re.search(rf"{re.escape(label)}\s*[：:]\s*([^\n]+)", text_value, re.IGNORECASE)
        if match:
            fields.append(f"{label}={match.group(1).strip()}")
    if not fields:
        return None
    prefix = f"{dataset} " if dataset else ""
    return {
        "key": f"{prefix}MPC规划",
        "value": "; ".join(fields[:5]),
        "category": "analysis_conclusion",
    }


def _extract_nl2sql_fact(text_value: str) -> dict | None:
    if not any(token in text_value for token in ("NL2SQL", "NL2Semantic2SQL", "执行 SQL", "ST_", "候选表")):
        return None
    metric = _first_metric_line(text_value)
    if not metric:
        return None
    return {
        "key": "空间SQL结果",
        "value": metric,
        "category": "analysis_conclusion",
    }


def _extract_facts_rule_based(report_text: str, user_query: str) -> list[dict]:
    """Deterministic fallback for structured GIS tool outputs."""
    text_value = f"{user_query}\n{report_text}"
    facts: list[dict] = []
    for fact in (_extract_nl2sql_fact(text_value), _extract_world_model_fact(text_value)):
        if fact:
            facts.append(fact)
    if facts:
        return facts[:5]

    metric = _first_metric_line(report_text)
    if metric and len(report_text) > 120:
        return [{
            "key": "分析结论",
            "value": metric,
            "category": "analysis_conclusion",
        }]
    return []


def extract_facts_from_conversation(report_text: str, user_query: str) -> list[dict]:
    """Extract key facts from conversation output.

    Args:
        report_text: Pipeline output text (report/summary).
        user_query: Original user query text.
    Returns:
        List of dicts with keys: key, value, category. Empty list on failure.
    """
    if not report_text or len(report_text) < 50:
        return []

    fallback_facts = _extract_facts_rule_based(report_text, user_query)
    llm_first = os.environ.get("MEMORY_EXTRACT_LLM_FIRST", "").strip().lower() in {"1", "true", "yes", "on"}
    if fallback_facts and not llm_first:
        return fallback_facts

    try:
        prompt = (
            "从以下对话中提取关键发现（数据特征、分析结论、用户偏好），返回 JSON 数组。\n"
            '每个元素包含: {"key": "短标识符(10字以内)", "value": "结构化发现内容", '
            '"category": "data_characteristic|analysis_conclusion|user_preference"}\n'
            "最多返回5条最重要的发现。如果没有值得记录的发现，返回空数组 []。\n"
            "仅返回 JSON 数组，不要包含其他文字。\n\n"
            f"用户问题: {user_query[:500]}\n"
            f"分析结果: {report_text[:3000]}"
        )
        llm_facts = _parse_fact_json(_call_memory_extract_model(prompt))
        return llm_facts or fallback_facts
    except Exception as exc:
        logger.debug("[MemoryETL] LLM extraction failed; using fallback: %s", exc)
        return fallback_facts


def save_auto_extract_memories(facts: list[dict]) -> dict:
    """Save extracted facts as auto_extract memories with dedup and quota.

    Args:
        facts: List of dicts from extract_facts_from_conversation().
    Returns:
        Result dict with status and count of saved memories.
    """
    if not facts:
        return {"status": "success", "saved": 0}

    engine = get_engine()
    if not engine:
        return {"status": "error", "message": t("memory.db_unavailable")}

    username = current_user_id.get()
    try:
        saved = 0
        with engine.connect() as conn:
            _inject_user_context(conn)
            for fact in facts[:5]:
                key = str(fact.get("key", ""))[:200]
                value = json.dumps({
                    "finding": fact.get("value", ""),
                    "category": fact.get("category", "data_characteristic"),
                }, ensure_ascii=False)
                conn.execute(text(f"""
                    INSERT INTO {T_USER_MEMORIES} (username, memory_type, memory_key, memory_value, description)
                    VALUES (:u, 'auto_extract', :k, :v, :d)
                    ON CONFLICT (username, memory_type, memory_key)
                    DO UPDATE SET memory_value = :v, description = :d, updated_at = NOW()
                """), {"u": username, "k": key, "v": value,
                       "d": fact.get("category", "auto")})
                saved += 1

            # Enforce per-user quota: keep newest AUTO_EXTRACT_QUOTA, delete rest
            conn.execute(text(f"""
                DELETE FROM {T_USER_MEMORIES}
                WHERE id IN (
                    SELECT id FROM {T_USER_MEMORIES}
                    WHERE username = :u AND memory_type = 'auto_extract'
                    ORDER BY updated_at DESC
                    OFFSET :quota
                )
            """), {"u": username, "quota": AUTO_EXTRACT_QUOTA})
            conn.commit()
        return {"status": "success", "saved": saved}
    except Exception as e:
        return {"status": "error", "message": t("memory.auto_save_failed", error=e)}


def list_auto_extract_memories() -> dict:
    """List all auto_extract memories for the current user.

    Returns:
        Dict with status and memories list.
    """
    engine = get_engine()
    if not engine:
        return {"status": "error", "message": t("memory.db_unavailable")}

    username = current_user_id.get()
    try:
        with engine.connect() as conn:
            _inject_user_context(conn)
            rows = conn.execute(text(
                f"SELECT id, memory_key, memory_value, description, updated_at "
                f"FROM {T_USER_MEMORIES} "
                "WHERE username = :u AND memory_type = 'auto_extract' "
                "ORDER BY updated_at DESC LIMIT :lim"
            ), {"u": username, "lim": AUTO_EXTRACT_QUOTA}).fetchall()

            memories = []
            for r in rows:
                memories.append({
                    "id": r[0],
                    "key": r[1],
                    "value": r[2] if isinstance(r[2], dict) else json.loads(r[2]) if r[2] else {},
                    "description": r[3],
                    "updated_at": str(r[4]),
                })
            return {"status": "success", "memories": memories}
    except Exception as e:
        return {"status": "error", "message": t("memory.auto_recall_failed", error=e)}
