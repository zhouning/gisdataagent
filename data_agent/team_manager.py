"""
Team Collaboration for GIS Data Agent.
Manages team creation, membership, and team-scoped resource sharing.
Data stored in PostgreSQL (agent_teams + agent_team_members tables).
"""
from sqlalchemy import text

from .db_engine import get_engine
from .database_tools import (
    _inject_user_context, T_TEAMS, T_TEAM_MEMBERS,
    T_TABLE_OWNERSHIP, T_ANALYSIS_TEMPLATES, T_USER_MEMORIES,
)
from .user_context import current_user_id, current_user_role
from .audit_logger import record_audit, ACTION_TEAM_CREATE, ACTION_TEAM_INVITE, ACTION_TEAM_REMOVE, ACTION_TEAM_DELETE

VALID_TEAM_ROLES = ("owner", "admin", "member", "viewer")


def ensure_teams_table():
    """Create agent_teams + agent_team_members if not exists. Called at startup."""
    engine = get_engine()
    if not engine:
        print("[Team] WARNING: Database not configured. Team system disabled.")
        return
    try:
        with engine.connect() as conn:
            conn.execute(text(f"""
                CREATE TABLE IF NOT EXISTS {T_TEAMS} (
                    id SERIAL PRIMARY KEY,
                    team_name VARCHAR(100) NOT NULL UNIQUE,
                    owner_username VARCHAR(100) NOT NULL,
                    description TEXT DEFAULT '',
                    max_members INT DEFAULT 10,
                    created_at TIMESTAMP DEFAULT NOW()
                )
            """))
            conn.execute(text(
                f"CREATE INDEX IF NOT EXISTS idx_agent_teams_owner ON {T_TEAMS} (owner_username)"
            ))
            conn.execute(text(f"""
                CREATE TABLE IF NOT EXISTS {T_TEAM_MEMBERS} (
                    id SERIAL PRIMARY KEY,
                    team_id INT NOT NULL REFERENCES {T_TEAMS}(id) ON DELETE CASCADE,
                    username VARCHAR(100) NOT NULL,
                    team_role VARCHAR(30) NOT NULL DEFAULT 'member',
                    joined_at TIMESTAMP DEFAULT NOW(),
                    UNIQUE(team_id, username)
                )
            """))
            conn.execute(text(
                f"CREATE INDEX IF NOT EXISTS idx_agent_team_members_user ON {T_TEAM_MEMBERS} (username)"
            ))
            conn.execute(text(
                f"CREATE INDEX IF NOT EXISTS idx_agent_team_members_team ON {T_TEAM_MEMBERS} (team_id)"
            ))
            conn.commit()
        print("[Team] Teams tables ready.")
    except Exception as e:
        print(f"[Team] Error initializing teams tables: {e}")


def _get_team_id(conn, team_name: str):
    """Internal: resolve team_name → team_id. Returns (team_id, owner) or (None, None)."""
    row = conn.execute(
        text(f"SELECT id, owner_username FROM {T_TEAMS} WHERE team_name = :n"),
        {"n": team_name},
    ).fetchone()
    if row:
        return row[0], row[1]
    return None, None


def _get_member_role(conn, team_id: int, username: str):
    """Internal: get user's role in a team, or None."""
    row = conn.execute(
        text(f"SELECT team_role FROM {T_TEAM_MEMBERS} WHERE team_id = :tid AND username = :u"),
        {"tid": team_id, "u": username},
    ).fetchone()
    return row[0] if row else None


def _is_team_admin(conn, team_id: int, username: str, owner_username: str):
    """Internal: check if user is team owner or team admin."""
    if username == owner_username:
        return True
    role = _get_member_role(conn, team_id, username)
    return role in ("owner", "admin")


def create_team(team_name: str, description: str = "") -> dict:
    """
    创建一个新的协作团队。当前用户成为团队所有者。

    Args:
        team_name: 团队名称（唯一），2-50个字符
        description: 团队描述（可选）
    Returns:
        操作结果 dict
    """
    if not team_name or len(team_name.strip()) < 2 or len(team_name.strip()) > 50:
        return {"status": "error", "message": "团队名称需要2-50个字符"}

    username = current_user_id.get()
    role = current_user_role.get("analyst")
    if role == "viewer":
        return {"status": "error", "message": "查看者角色无权创建团队"}

    engine = get_engine()
    if not engine:
        return {"status": "error", "message": "数据库未配置"}

    team_name = team_name.strip()
    try:
        with engine.connect() as conn:
            _inject_user_context(conn)
            # Create team
            conn.execute(
                text(f"INSERT INTO {T_TEAMS} (team_name, owner_username, description) VALUES (:n, :u, :d)"),
                {"n": team_name, "u": username, "d": description},
            )
            # Get new team id
            tid = conn.execute(
                text(f"SELECT id FROM {T_TEAMS} WHERE team_name = :n"),
                {"n": team_name},
            ).fetchone()[0]
            # Auto-join owner
            conn.execute(
                text(f"INSERT INTO {T_TEAM_MEMBERS} (team_id, username, team_role) VALUES (:tid, :u, 'owner')"),
                {"tid": tid, "u": username},
            )
            conn.commit()
        record_audit(username, ACTION_TEAM_CREATE, "success", details={"team_name": team_name})
        return {"status": "success", "message": f"团队「{team_name}」创建成功，你是团队所有者", "team_name": team_name}
    except Exception as e:
        if "unique" in str(e).lower() or "duplicate" in str(e).lower():
            return {"status": "error", "message": f"团队名称「{team_name}」已存在"}
        return {"status": "error", "message": f"创建团队失败: {e}"}


def list_my_teams() -> dict:
    """
    列出当前用户所属的所有团队（包括创建的和加入的）。

    Returns:
        包含团队列表的 dict
    """
    username = current_user_id.get()
    engine = get_engine()
    if not engine:
        return {"status": "error", "message": "数据库未配置"}

    try:
        with engine.connect() as conn:
            _inject_user_context(conn)
            rows = conn.execute(text(f"""
                SELECT t.team_name, t.owner_username, t.description, tm.team_role,
                       (SELECT COUNT(*) FROM {T_TEAM_MEMBERS} WHERE team_id = t.id) AS member_count
                FROM {T_TEAMS} t
                JOIN {T_TEAM_MEMBERS} tm ON t.id = tm.team_id
                WHERE tm.username = :u
                ORDER BY t.created_at DESC
            """), {"u": username}).fetchall()

            teams = []
            for r in rows:
                teams.append({
                    "team_name": r[0],
                    "owner": r[1],
                    "description": r[2],
                    "my_role": r[3],
                    "member_count": r[4],
                    "is_owner": r[1] == username,
                })
            return {"status": "success", "teams": teams, "count": len(teams)}
    except Exception as e:
        return {"status": "error", "message": f"查询团队列表失败: {e}"}


def invite_to_team(team_name: str, username: str, role: str = "member") -> dict:
    """
    邀请用户加入团队。仅团队所有者或管理员可操作。

    Args:
        team_name: 团队名称
        username: 被邀请用户的用户名
        role: 分配角色，可选: admin（管理员）, member（成员）, viewer（查看者）
    Returns:
        操作结果 dict
    """
    if role not in ("admin", "member", "viewer"):
        return {"status": "error", "message": f"无效角色 '{role}'，可选: admin, member, viewer"}

    current_user = current_user_id.get()
    engine = get_engine()
    if not engine:
        return {"status": "error", "message": "数据库未配置"}

    try:
        with engine.connect() as conn:
            _inject_user_context(conn)
            team_id, owner = _get_team_id(conn, team_name)
            if team_id is None:
                return {"status": "error", "message": f"团队「{team_name}」不存在"}

            if not _is_team_admin(conn, team_id, current_user, owner):
                return {"status": "error", "message": "只有团队所有者或管理员可以邀请成员"}

            # Check max members
            count = conn.execute(
                text(f"SELECT COUNT(*) FROM {T_TEAM_MEMBERS} WHERE team_id = :tid"),
                {"tid": team_id},
            ).fetchone()[0]
            max_members = conn.execute(
                text(f"SELECT max_members FROM {T_TEAMS} WHERE id = :tid"),
                {"tid": team_id},
            ).fetchone()[0]
            if count >= max_members:
                return {"status": "error", "message": f"团队已达上限（{max_members}人）"}

            conn.execute(
                text(f"INSERT INTO {T_TEAM_MEMBERS} (team_id, username, team_role) VALUES (:tid, :u, :r)"),
                {"tid": team_id, "u": username, "r": role},
            )
            conn.commit()
        record_audit(current_user, ACTION_TEAM_INVITE, "success",
                     details={"team_name": team_name, "invited_user": username, "role": role})
        return {"status": "success", "message": f"已邀请 {username} 加入团队「{team_name}」，角色: {role}"}
    except Exception as e:
        if "unique" in str(e).lower() or "duplicate" in str(e).lower():
            return {"status": "error", "message": f"{username} 已是团队成员"}
        return {"status": "error", "message": f"邀请失败: {e}"}


def remove_from_team(team_name: str, username: str) -> dict:
    """
    从团队中移除成员。仅团队所有者或管理员可操作，不能移除所有者。

    Args:
        team_name: 团队名称
        username: 要移除的用户名
    Returns:
        操作结果 dict
    """
    current_user = current_user_id.get()
    engine = get_engine()
    if not engine:
        return {"status": "error", "message": "数据库未配置"}

    try:
        with engine.connect() as conn:
            _inject_user_context(conn)
            team_id, owner = _get_team_id(conn, team_name)
            if team_id is None:
                return {"status": "error", "message": f"团队「{team_name}」不存在"}

            if username == owner:
                return {"status": "error", "message": "不能移除团队所有者"}

            if not _is_team_admin(conn, team_id, current_user, owner):
                return {"status": "error", "message": "只有团队所有者或管理员可以移除成员"}

            result = conn.execute(
                text(f"DELETE FROM {T_TEAM_MEMBERS} WHERE team_id = :tid AND username = :u"),
                {"tid": team_id, "u": username},
            )
            conn.commit()
            if result.rowcount == 0:
                return {"status": "error", "message": f"{username} 不是团队成员"}
        record_audit(current_user, ACTION_TEAM_REMOVE, "success",
                     details={"team_name": team_name, "removed_user": username})
        return {"status": "success", "message": f"已将 {username} 从团队「{team_name}」移除"}
    except Exception as e:
        return {"status": "error", "message": f"移除成员失败: {e}"}


def list_team_members(team_name: str) -> dict:
    """
    查看团队成员列表。必须是团队成员才能查看。

    Args:
        team_name: 团队名称
    Returns:
        成员列表 dict
    """
    current_user = current_user_id.get()
    engine = get_engine()
    if not engine:
        return {"status": "error", "message": "数据库未配置"}

    try:
        with engine.connect() as conn:
            _inject_user_context(conn)
            team_id, owner = _get_team_id(conn, team_name)
            if team_id is None:
                return {"status": "error", "message": f"团队「{team_name}」不存在"}

            # Check membership
            my_role = _get_member_role(conn, team_id, current_user)
            sys_role = current_user_role.get("analyst")
            if my_role is None and sys_role != "admin":
                return {"status": "error", "message": "你不是该团队成员"}

            rows = conn.execute(text(f"""
                SELECT username, team_role, joined_at
                FROM {T_TEAM_MEMBERS}
                WHERE team_id = :tid
                ORDER BY
                    CASE team_role WHEN 'owner' THEN 0 WHEN 'admin' THEN 1 WHEN 'member' THEN 2 ELSE 3 END,
                    joined_at
            """), {"tid": team_id}).fetchall()

            members = [{"username": r[0], "role": r[1], "joined_at": str(r[2])} for r in rows]
            return {"status": "success", "team_name": team_name, "members": members, "count": len(members)}
    except Exception as e:
        return {"status": "error", "message": f"查询成员列表失败: {e}"}


def list_team_resources(team_name: str, resource_type: str = "all") -> dict:
    """
    查看团队成员共享的资源（数据表、模板、记忆）。

    Args:
        team_name: 团队名称
        resource_type: 资源类型，可选: tables（数据表）, templates（分析模板）, memories（记忆）, all（全部）
    Returns:
        资源列表 dict
    """
    valid_types = ("tables", "templates", "memories", "all")
    if resource_type not in valid_types:
        return {"status": "error", "message": f"无效资源类型，可选: {', '.join(valid_types)}"}

    current_user = current_user_id.get()
    engine = get_engine()
    if not engine:
        return {"status": "error", "message": "数据库未配置"}

    try:
        with engine.connect() as conn:
            _inject_user_context(conn)
            team_id, owner = _get_team_id(conn, team_name)
            if team_id is None:
                return {"status": "error", "message": f"团队「{team_name}」不存在"}

            my_role = _get_member_role(conn, team_id, current_user)
            sys_role = current_user_role.get("analyst")
            if my_role is None and sys_role != "admin":
                return {"status": "error", "message": "你不是该团队成员"}

            # Get all team member usernames
            member_rows = conn.execute(
                text(f"SELECT username FROM {T_TEAM_MEMBERS} WHERE team_id = :tid"),
                {"tid": team_id},
            ).fetchall()
            team_usernames = [r[0] for r in member_rows]

            resources = {}

            if resource_type in ("tables", "all"):
                try:
                    table_rows = conn.execute(text(f"""
                        SELECT table_name, owner_username, is_shared, description
                        FROM {T_TABLE_OWNERSHIP}
                        WHERE owner_username = ANY(:users)
                        ORDER BY table_name
                    """), {"users": team_usernames}).fetchall()
                    resources["tables"] = [
                        {"table_name": r[0], "owner": r[1], "is_shared": r[2], "description": r[3]}
                        for r in table_rows
                    ]
                except Exception:
                    resources["tables"] = []

            if resource_type in ("templates", "all"):
                try:
                    tpl_rows = conn.execute(text(f"""
                        SELECT id, template_name, owner_username, pipeline_type, description
                        FROM {T_ANALYSIS_TEMPLATES}
                        WHERE owner_username = ANY(:users)
                        ORDER BY updated_at DESC
                    """), {"users": team_usernames}).fetchall()
                    resources["templates"] = [
                        {"id": r[0], "name": r[1], "owner": r[2], "pipeline": r[3], "description": r[4]}
                        for r in tpl_rows
                    ]
                except Exception:
                    resources["templates"] = []

            if resource_type in ("memories", "all"):
                try:
                    mem_rows = conn.execute(text(f"""
                        SELECT username, memory_type, memory_key, description
                        FROM {T_USER_MEMORIES}
                        WHERE username = ANY(:users) AND memory_type != 'analysis_result'
                        ORDER BY username, memory_type
                    """), {"users": team_usernames}).fetchall()
                    resources["memories"] = [
                        {"owner": r[0], "type": r[1], "key": r[2], "description": r[3]}
                        for r in mem_rows
                    ]
                except Exception:
                    resources["memories"] = []

            return {"status": "success", "team_name": team_name, "resources": resources}
    except Exception as e:
        return {"status": "error", "message": f"查询团队资源失败: {e}"}


def leave_team(team_name: str) -> dict:
    """
    退出团队。团队所有者不能退出（需转让或删除团队）。

    Args:
        team_name: 团队名称
    Returns:
        操作结果 dict
    """
    current_user = current_user_id.get()
    engine = get_engine()
    if not engine:
        return {"status": "error", "message": "数据库未配置"}

    try:
        with engine.connect() as conn:
            _inject_user_context(conn)
            team_id, owner = _get_team_id(conn, team_name)
            if team_id is None:
                return {"status": "error", "message": f"团队「{team_name}」不存在"}

            if current_user == owner:
                return {"status": "error", "message": "团队所有者不能退出团队，请先转让所有权或删除团队"}

            result = conn.execute(
                text(f"DELETE FROM {T_TEAM_MEMBERS} WHERE team_id = :tid AND username = :u"),
                {"tid": team_id, "u": current_user},
            )
            conn.commit()
            if result.rowcount == 0:
                return {"status": "error", "message": "你不是该团队成员"}
        return {"status": "success", "message": f"已退出团队「{team_name}」"}
    except Exception as e:
        return {"status": "error", "message": f"退出团队失败: {e}"}


def delete_team(team_name: str) -> dict:
    """
    删除团队。仅团队所有者可操作，CASCADE删除所有成员记录。

    Args:
        team_name: 团队名称
    Returns:
        操作结果 dict
    """
    current_user = current_user_id.get()
    engine = get_engine()
    if not engine:
        return {"status": "error", "message": "数据库未配置"}

    try:
        with engine.connect() as conn:
            _inject_user_context(conn)
            team_id, owner = _get_team_id(conn, team_name)
            if team_id is None:
                return {"status": "error", "message": f"团队「{team_name}」不存在"}

            sys_role = current_user_role.get("analyst")
            if current_user != owner and sys_role != "admin":
                return {"status": "error", "message": "只有团队所有者或系统管理员可以删除团队"}

            conn.execute(text(f"DELETE FROM {T_TEAMS} WHERE id = :tid"), {"tid": team_id})
            conn.commit()
        record_audit(current_user, ACTION_TEAM_DELETE, "success", details={"team_name": team_name})
        return {"status": "success", "message": f"团队「{team_name}」已删除"}
    except Exception as e:
        return {"status": "error", "message": f"删除团队失败: {e}"}
