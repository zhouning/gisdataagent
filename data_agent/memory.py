"""
Spatial Memory System for per-user persistent preferences, regions, and analysis history.
Stores memories in PostgreSQL (user_memories table) with JSONB values.
"""
import json
from sqlalchemy import text

from .db_engine import get_engine
from .database_tools import _inject_user_context, T_USER_MEMORIES
from .user_context import current_user_id

VALID_MEMORY_TYPES = ("region", "viz_preference", "analysis_result", "custom", "analysis_perspective")


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
        return {"status": "error", "message": f"无效的记忆类型 '{memory_type}'，可选: {', '.join(VALID_MEMORY_TYPES)}"}

    try:
        parsed_value = json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return {"status": "error", "message": "value 必须是合法的 JSON 字符串"}

    engine = get_engine()
    if not engine:
        return {"status": "error", "message": "数据库未配置，无法保存记忆"}

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
        return {"status": "success", "message": f"已保存记忆: [{memory_type}] {key}"}
    except Exception as e:
        return {"status": "error", "message": f"保存记忆失败: {e}"}


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
        return {"status": "error", "message": "数据库未配置"}

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
                "message": f"找到 {len(memories)} 条记忆" if memories else "未找到匹配的记忆",
            }
    except Exception as e:
        return {"status": "error", "message": f"检索记忆失败: {e}"}


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
        return {"status": "error", "message": "数据库未配置"}

    username = current_user_id.get()
    try:
        mid = int(memory_id)
    except (ValueError, TypeError):
        return {"status": "error", "message": "memory_id 必须是数字"}

    try:
        with engine.connect() as conn:
            _inject_user_context(conn)
            result = conn.execute(text(
                f"DELETE FROM {T_USER_MEMORIES} WHERE id = :id AND username = :u"
            ), {"id": mid, "u": username})
            conn.commit()
            if result.rowcount > 0:
                return {"status": "success", "message": f"已删除记忆 (ID={mid})"}
            else:
                return {"status": "error", "message": f"未找到 ID={mid} 的记忆（可能不存在或不属于当前用户）"}
    except Exception as e:
        return {"status": "error", "message": f"删除记忆失败: {e}"}


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
