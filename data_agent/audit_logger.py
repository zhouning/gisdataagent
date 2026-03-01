"""
Audit Logging for GIS Data Agent.
Records high-value user events in PostgreSQL (agent_audit_log table).
Non-fatal: never raises exceptions to the caller.
"""
import json
import os
from typing import Optional

from sqlalchemy import text

from .db_engine import get_engine
from .database_tools import T_AUDIT_LOG
from .user_context import current_user_id, current_user_role

# --- Action constants ---
ACTION_LOGIN_SUCCESS = "login_success"
ACTION_LOGIN_FAILURE = "login_failure"
ACTION_USER_REGISTER = "user_register"
ACTION_SESSION_START = "session_start"
ACTION_FILE_UPLOAD = "file_upload"
ACTION_PIPELINE_COMPLETE = "pipeline_complete"
ACTION_REPORT_EXPORT = "report_export"
ACTION_SHARE_CREATE = "share_create"
ACTION_FILE_DELETE = "file_delete"
ACTION_TABLE_SHARE = "table_share"
ACTION_RBAC_DENIED = "rbac_denied"
ACTION_CODE_EXPORT = "code_export"
ACTION_TEMPLATE_CREATE = "template_create"
ACTION_TEMPLATE_APPLY = "template_apply"
ACTION_TEMPLATE_DELETE = "template_delete"
ACTION_WECOM_MESSAGE = "wecom_message"
ACTION_TEAM_CREATE = "team_create"
ACTION_TEAM_INVITE = "team_invite"
ACTION_TEAM_REMOVE = "team_remove"
ACTION_TEAM_DELETE = "team_delete"

# Chinese labels for admin viewer
ACTION_LABELS = {
    ACTION_LOGIN_SUCCESS: "登录成功",
    ACTION_LOGIN_FAILURE: "登录失败",
    ACTION_USER_REGISTER: "用户注册",
    ACTION_SESSION_START: "会话开始",
    ACTION_FILE_UPLOAD: "文件上传",
    ACTION_PIPELINE_COMPLETE: "分析完成",
    ACTION_REPORT_EXPORT: "报告导出",
    ACTION_SHARE_CREATE: "创建分享",
    ACTION_FILE_DELETE: "文件删除",
    ACTION_TABLE_SHARE: "共享数据表",
    ACTION_RBAC_DENIED: "权限拒绝",
    ACTION_CODE_EXPORT: "脚本导出",
    ACTION_TEMPLATE_CREATE: "创建模板",
    ACTION_TEMPLATE_APPLY: "应用模板",
    ACTION_TEMPLATE_DELETE: "删除模板",
    ACTION_WECOM_MESSAGE: "企业微信消息",
    ACTION_TEAM_CREATE: "创建团队",
    ACTION_TEAM_INVITE: "邀请成员",
    ACTION_TEAM_REMOVE: "移除成员",
    ACTION_TEAM_DELETE: "删除团队",
}


def ensure_audit_table():
    """Create audit_log table if not exists. Called at startup."""
    engine = get_engine()
    if not engine:
        print("[Audit] WARNING: Database not configured. Audit logging disabled.")
        return

    try:
        with engine.connect() as conn:
            conn.execute(text(f"""
                CREATE TABLE IF NOT EXISTS {T_AUDIT_LOG} (
                    id BIGSERIAL PRIMARY KEY,
                    username VARCHAR(100) NOT NULL,
                    action VARCHAR(50) NOT NULL,
                    status VARCHAR(20) NOT NULL DEFAULT 'success',
                    ip_address VARCHAR(45),
                    details JSONB DEFAULT '{{}}',
                    created_at TIMESTAMP DEFAULT NOW()
                )
            """))
            conn.execute(text(
                f"CREATE INDEX IF NOT EXISTS idx_audit_log_user_date "
                f"ON {T_AUDIT_LOG} (username, created_at DESC)"
            ))
            conn.execute(text(
                f"CREATE INDEX IF NOT EXISTS idx_audit_log_action "
                f"ON {T_AUDIT_LOG} (action, created_at DESC)"
            ))
            conn.execute(text(
                f"CREATE INDEX IF NOT EXISTS idx_audit_log_date "
                f"ON {T_AUDIT_LOG} (created_at DESC)"
            ))
            conn.commit()

        # Run retention cleanup at startup
        deleted = cleanup_old_audit_logs()
        if deleted > 0:
            print(f"[Audit] Cleaned up {deleted} old audit log entries.")
        print("[Audit] Audit log table ready.")
    except Exception as e:
        print(f"[Audit] Error initializing audit table: {e}")


def record_audit(
    username: str,
    action: str,
    status: str = "success",
    ip_address: Optional[str] = None,
    details: Optional[dict] = None,
) -> None:
    """
    Record a single audit event. Non-fatal on failure.

    Args:
        username: User performing the action.
        action: One of the ACTION_* constants.
        status: 'success', 'failure', or 'denied'.
        ip_address: Client IP if available.
        details: Action-specific metadata dict (stored as JSONB).
    """
    engine = get_engine()
    if not engine:
        return

    try:
        with engine.connect() as conn:
            conn.execute(text(f"""
                INSERT INTO {T_AUDIT_LOG}
                    (username, action, status, ip_address, details)
                VALUES (:u, :a, :s, :ip, CAST(:d AS jsonb))
            """), {
                "u": username,
                "a": action,
                "s": status,
                "ip": ip_address,
                "d": json.dumps(details or {}, ensure_ascii=False),
            })
            conn.commit()
    except Exception as e:
        print(f"[Audit] Failed to record: {e}")


def get_user_audit_log(username: str, days: int = 30, limit: int = 200) -> list:
    """
    Get recent audit events for a specific user.

    Returns:
        List of dicts with action, status, details, created_at.
    """
    engine = get_engine()
    if not engine:
        return []

    try:
        with engine.connect() as conn:
            rows = conn.execute(text(f"""
                SELECT username, action, status, ip_address, details, created_at
                FROM {T_AUDIT_LOG}
                WHERE username = :u
                  AND created_at >= NOW() - make_interval(days => :d)
                ORDER BY created_at DESC
                LIMIT :lim
            """), {"u": username, "d": days, "lim": limit}).fetchall()
            return [
                {
                    "username": r[0], "action": r[1], "status": r[2],
                    "ip_address": r[3],
                    "details": r[4] if isinstance(r[4], dict) else json.loads(r[4] or "{}"),
                    "created_at": r[5].isoformat() if r[5] else None,
                }
                for r in rows
            ]
    except Exception:
        return []


def get_audit_stats(days: int = 30) -> dict:
    """
    Get aggregate audit statistics for the admin dashboard.

    Returns:
        Dict with total_events, active_users, events_by_action, events_by_status, daily_counts.
    """
    engine = get_engine()
    if not engine:
        return {
            "total_events": 0, "active_users": 0,
            "events_by_action": {}, "events_by_status": {},
            "daily_counts": [],
        }

    try:
        with engine.connect() as conn:
            # Total events and active users
            row = conn.execute(text(f"""
                SELECT COUNT(*) AS total, COUNT(DISTINCT username) AS users
                FROM {T_AUDIT_LOG}
                WHERE created_at >= NOW() - make_interval(days => :d)
            """), {"d": days}).fetchone()
            total_events = row[0]
            active_users = row[1]

            # Events by action
            action_rows = conn.execute(text(f"""
                SELECT action, COUNT(*) AS cnt
                FROM {T_AUDIT_LOG}
                WHERE created_at >= NOW() - make_interval(days => :d)
                GROUP BY action ORDER BY cnt DESC
            """), {"d": days}).fetchall()
            events_by_action = {r[0]: r[1] for r in action_rows}

            # Events by status
            status_rows = conn.execute(text(f"""
                SELECT status, COUNT(*) AS cnt
                FROM {T_AUDIT_LOG}
                WHERE created_at >= NOW() - make_interval(days => :d)
                GROUP BY status ORDER BY cnt DESC
            """), {"d": days}).fetchall()
            events_by_status = {r[0]: r[1] for r in status_rows}

            # Daily counts (last 7 days)
            daily_rows = conn.execute(text(f"""
                SELECT DATE(created_at) AS day, COUNT(*) AS cnt
                FROM {T_AUDIT_LOG}
                WHERE created_at >= NOW() - make_interval(days => 7)
                GROUP BY day ORDER BY day DESC
            """)).fetchall()
            daily_counts = [
                {"date": r[0].isoformat() if r[0] else None, "count": r[1]}
                for r in daily_rows
            ]

            return {
                "total_events": total_events,
                "active_users": active_users,
                "events_by_action": events_by_action,
                "events_by_status": events_by_status,
                "daily_counts": daily_counts,
            }
    except Exception:
        return {
            "total_events": 0, "active_users": 0,
            "events_by_action": {}, "events_by_status": {},
            "daily_counts": [],
        }


def query_audit_log(
    days: int = 7,
    action_filter: str = None,
    username_filter: str = None,
) -> dict:
    """
    查询审计日志（仅管理员可用）。

    Args:
        days: 查询最近N天的日志（默认7天，最大90天）。
        action_filter: 按操作类型筛选（可选，如 'login_success', 'pipeline_complete'）。
        username_filter: 按用户名筛选（可选）。

    Returns:
        审计日志记录列表或权限拒绝消息。
    """
    role = current_user_role.get()
    if role != "admin":
        return {"status": "error", "message": "权限不足：仅管理员可查询审计日志。"}

    engine = get_engine()
    if not engine:
        return {"status": "error", "message": "数据库未配置。"}

    days = min(max(days, 1), 90)

    try:
        with engine.connect() as conn:
            where_clauses = ["created_at >= NOW() - make_interval(days => :d)"]
            params = {"d": days, "lim": 100}

            if action_filter:
                where_clauses.append("action = :af")
                params["af"] = action_filter
            if username_filter:
                where_clauses.append("username = :uf")
                params["uf"] = username_filter

            where_sql = " AND ".join(where_clauses)
            rows = conn.execute(text(f"""
                SELECT username, action, status, details, created_at
                FROM {T_AUDIT_LOG}
                WHERE {where_sql}
                ORDER BY created_at DESC
                LIMIT :lim
            """), params).fetchall()

            if not rows:
                return {"status": "success", "message": "未找到符合条件的审计日志。"}

            lines = []
            for r in rows:
                ts = r[4].strftime("%m-%d %H:%M") if r[4] else "?"
                label = ACTION_LABELS.get(r[1], r[1])
                detail_dict = r[3] if isinstance(r[3], dict) else json.loads(r[3] or "{}")
                detail_str = ", ".join(f"{k}={v}" for k, v in detail_dict.items()) if detail_dict else ""
                status_mark = "✓" if r[2] == "success" else ("✗" if r[2] == "failure" else "⊘")
                lines.append(f"[{ts}] {r[0]} | {label} {status_mark} | {detail_str}")

            return {
                "status": "success",
                "message": f"最近 {days} 天审计日志（{len(rows)} 条）：\n" + "\n".join(lines),
            }
    except Exception as e:
        return {"status": "error", "message": f"查询失败: {e}"}


def cleanup_old_audit_logs() -> int:
    """
    Delete audit log entries older than AUDIT_LOG_RETENTION_DAYS.
    Called at startup by ensure_audit_table().

    Returns:
        Number of deleted rows.
    """
    retention_days = int(os.environ.get("AUDIT_LOG_RETENTION_DAYS", 90))
    engine = get_engine()
    if not engine:
        return 0

    try:
        with engine.connect() as conn:
            result = conn.execute(text(f"""
                DELETE FROM {T_AUDIT_LOG}
                WHERE created_at < NOW() - make_interval(days => :d)
            """), {"d": retention_days})
            conn.commit()
            return result.rowcount
    except Exception:
        return 0
