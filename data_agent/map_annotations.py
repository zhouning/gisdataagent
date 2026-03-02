"""
Map Annotations — Collaborative spatial commenting system.
Users can place pin annotations on the map with title, comment, and color.
Annotations are visible to the user and their team members.
"""
from sqlalchemy import text

from .db_engine import get_engine
from .database_tools import _inject_user_context, TABLE_PREFIX
from .user_context import current_user_id

T_MAP_ANNOTATIONS = f"{TABLE_PREFIX}map_annotations"


def ensure_annotations_table():
    """Create map_annotations table if not exists. Called at startup."""
    engine = get_engine()
    if not engine:
        return
    try:
        with engine.connect() as conn:
            conn.execute(text(f"""
                CREATE TABLE IF NOT EXISTS {T_MAP_ANNOTATIONS} (
                    id SERIAL PRIMARY KEY,
                    username VARCHAR(100) NOT NULL,
                    team_id INT DEFAULT NULL,
                    title VARCHAR(200) DEFAULT '',
                    comment TEXT DEFAULT '',
                    lng DOUBLE PRECISION NOT NULL,
                    lat DOUBLE PRECISION NOT NULL,
                    color VARCHAR(20) DEFAULT '#e63946',
                    is_resolved BOOLEAN DEFAULT FALSE,
                    created_at TIMESTAMP DEFAULT NOW()
                )
            """))
            conn.execute(text(
                f"CREATE INDEX IF NOT EXISTS idx_{T_MAP_ANNOTATIONS}_user "
                f"ON {T_MAP_ANNOTATIONS} (username)"
            ))
            conn.execute(text(
                f"CREATE INDEX IF NOT EXISTS idx_{T_MAP_ANNOTATIONS}_team "
                f"ON {T_MAP_ANNOTATIONS} (team_id) WHERE team_id IS NOT NULL"
            ))
            conn.commit()
    except Exception as e:
        print(f"[MapAnnotations] Error initializing table: {e}")


def create_annotation(username: str, lng: float, lat: float,
                      title: str = "", comment: str = "",
                      color: str = "#e63946", team_id: int = None) -> dict:
    """Create a new map annotation."""
    engine = get_engine()
    if not engine:
        return {"status": "error", "message": "数据库未配置"}

    try:
        with engine.connect() as conn:
            _inject_user_context(conn)
            row = conn.execute(text(f"""
                INSERT INTO {T_MAP_ANNOTATIONS} (username, team_id, title, comment, lng, lat, color)
                VALUES (:u, :t, :title, :comment, :lng, :lat, :color)
                RETURNING id, created_at
            """), {
                "u": username, "t": team_id, "title": title[:200],
                "comment": comment[:2000], "lng": lng, "lat": lat, "color": color[:20],
            }).fetchone()
            conn.commit()
            return {
                "status": "success",
                "annotation": {
                    "id": row[0],
                    "username": username,
                    "title": title,
                    "comment": comment,
                    "lng": lng,
                    "lat": lat,
                    "color": color,
                    "is_resolved": False,
                    "created_at": row[1].isoformat() if row[1] else None,
                },
            }
    except Exception as e:
        return {"status": "error", "message": f"创建标注失败: {e}"}


def list_annotations(username: str, team_id: int = None) -> dict:
    """List annotations visible to the user (own + team)."""
    engine = get_engine()
    if not engine:
        return {"annotations": [], "count": 0}

    try:
        with engine.connect() as conn:
            _inject_user_context(conn)
            if team_id:
                rows = conn.execute(text(f"""
                    SELECT id, username, team_id, title, comment, lng, lat,
                           color, is_resolved, created_at
                    FROM {T_MAP_ANNOTATIONS}
                    WHERE username = :u OR team_id = :t
                    ORDER BY created_at DESC
                    LIMIT 200
                """), {"u": username, "t": team_id}).fetchall()
            else:
                rows = conn.execute(text(f"""
                    SELECT id, username, team_id, title, comment, lng, lat,
                           color, is_resolved, created_at
                    FROM {T_MAP_ANNOTATIONS}
                    WHERE username = :u
                    ORDER BY created_at DESC
                    LIMIT 200
                """), {"u": username}).fetchall()

            annotations = []
            for r in rows:
                annotations.append({
                    "id": r[0],
                    "username": r[1],
                    "team_id": r[2],
                    "title": r[3] or "",
                    "comment": r[4] or "",
                    "lng": r[5],
                    "lat": r[6],
                    "color": r[7] or "#e63946",
                    "is_resolved": r[8],
                    "created_at": r[9].isoformat() if r[9] else None,
                })
            return {"annotations": annotations, "count": len(annotations)}
    except Exception as e:
        return {"annotations": [], "count": 0, "error": str(e)}


def update_annotation(annotation_id: int, username: str,
                      is_resolved: bool = None, title: str = None,
                      comment: str = None, color: str = None) -> dict:
    """Update an annotation (owner only)."""
    engine = get_engine()
    if not engine:
        return {"status": "error", "message": "数据库未配置"}

    updates = []
    params: dict = {"id": annotation_id, "u": username}

    if is_resolved is not None:
        updates.append("is_resolved = :resolved")
        params["resolved"] = is_resolved
    if title is not None:
        updates.append("title = :title")
        params["title"] = title[:200]
    if comment is not None:
        updates.append("comment = :comment")
        params["comment"] = comment[:2000]
    if color is not None:
        updates.append("color = :color")
        params["color"] = color[:20]

    if not updates:
        return {"status": "error", "message": "无更新字段"}

    try:
        with engine.connect() as conn:
            _inject_user_context(conn)
            result = conn.execute(text(f"""
                UPDATE {T_MAP_ANNOTATIONS}
                SET {', '.join(updates)}
                WHERE id = :id AND username = :u
            """), params)
            conn.commit()
            if result.rowcount == 0:
                return {"status": "error", "message": "标注不存在或无权限"}
            return {"status": "success", "message": "标注已更新"}
    except Exception as e:
        return {"status": "error", "message": f"更新失败: {e}"}


def delete_annotation(annotation_id: int, username: str) -> dict:
    """Delete an annotation (owner only)."""
    engine = get_engine()
    if not engine:
        return {"status": "error", "message": "数据库未配置"}

    try:
        with engine.connect() as conn:
            _inject_user_context(conn)
            result = conn.execute(text(f"""
                DELETE FROM {T_MAP_ANNOTATIONS}
                WHERE id = :id AND username = :u
            """), {"id": annotation_id, "u": username})
            conn.commit()
            if result.rowcount == 0:
                return {"status": "error", "message": "标注不存在或无权限"}
            return {"status": "success", "message": "标注已删除"}
    except Exception as e:
        return {"status": "error", "message": f"删除失败: {e}"}
