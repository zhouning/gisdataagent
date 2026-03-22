"""
Data Distribution — request/approval, packaging, reviews, access tracking (v15.0).

Manages the data sharing lifecycle: request → approve/reject → package → deliver.
Tracks asset access for popularity/heat analytics and user reviews for quality feedback.
"""

import json
import logging
import os
import uuid
import zipfile
from datetime import datetime, timezone

from sqlalchemy import text

from .db_engine import get_engine

logger = logging.getLogger(__name__)

T_DATA_REQUESTS = "agent_data_requests"
T_ASSET_REVIEWS = "agent_asset_reviews"
T_ACCESS_LOG = "agent_asset_access_log"
T_DATA_CATALOG = "agent_data_catalog"

VALID_REQUEST_STATUS = {"pending", "approved", "rejected"}


# ---------------------------------------------------------------------------
# Data Requests (申请审批)
# ---------------------------------------------------------------------------

def create_data_request(asset_id: int, requester: str, reason: str = "") -> dict:
    engine = get_engine()
    if not engine:
        return {"status": "error", "message": "数据库不可用"}
    try:
        with engine.connect() as conn:
            conn.execute(text(f"""
                INSERT INTO {T_DATA_REQUESTS} (asset_id, requester, reason)
                VALUES (:a, :r, :re)
            """), {"a": asset_id, "r": requester, "re": reason})
            conn.commit()
            rid = conn.execute(text(
                f"SELECT id FROM {T_DATA_REQUESTS} WHERE asset_id = :a AND requester = :r ORDER BY id DESC LIMIT 1"
            ), {"a": asset_id, "r": requester}).scalar()
        return {"status": "ok", "id": rid}
    except Exception as e:
        return {"status": "error", "message": str(e)}


def list_data_requests(username: str, role: str = "analyst") -> list:
    engine = get_engine()
    if not engine:
        return []
    try:
        with engine.connect() as conn:
            if role == "admin":
                rows = conn.execute(text(
                    f"SELECT * FROM {T_DATA_REQUESTS} ORDER BY created_at DESC LIMIT 100"
                )).fetchall()
            else:
                rows = conn.execute(text(
                    f"SELECT * FROM {T_DATA_REQUESTS} WHERE requester = :u ORDER BY created_at DESC LIMIT 50"
                ), {"u": username}).fetchall()
        return [dict(r._mapping) for r in rows]
    except Exception:
        return []


def approve_request(request_id: int, approver: str) -> dict:
    engine = get_engine()
    if not engine:
        return {"status": "error", "message": "数据库不可用"}
    try:
        with engine.connect() as conn:
            result = conn.execute(text(f"""
                UPDATE {T_DATA_REQUESTS}
                SET status = 'approved', approver = :ap, approved_at = NOW()
                WHERE id = :id AND status = 'pending'
            """), {"id": request_id, "ap": approver})
            conn.commit()
            if result.rowcount == 0:
                return {"status": "error", "message": "申请未找到或已处理"}
        return {"status": "ok"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


def reject_request(request_id: int, approver: str, reason: str = "") -> dict:
    engine = get_engine()
    if not engine:
        return {"status": "error", "message": "数据库不可用"}
    try:
        with engine.connect() as conn:
            result = conn.execute(text(f"""
                UPDATE {T_DATA_REQUESTS}
                SET status = 'rejected', approver = :ap, reject_reason = :rr, approved_at = NOW()
                WHERE id = :id AND status = 'pending'
            """), {"id": request_id, "ap": approver, "rr": reason})
            conn.commit()
            if result.rowcount == 0:
                return {"status": "error", "message": "申请未找到或已处理"}
        return {"status": "ok"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


# ---------------------------------------------------------------------------
# Asset Packaging (分发包打包)
# ---------------------------------------------------------------------------

def package_assets(asset_ids: list, username: str = "") -> dict:
    """Package multiple data assets into a ZIP file for download."""
    engine = get_engine()
    if not engine:
        return {"status": "error", "message": "数据库不可用"}
    try:
        from .user_context import get_user_upload_dir
        upload_dir = get_user_upload_dir()
        os.makedirs(upload_dir, exist_ok=True)
        zip_name = f"data_package_{uuid.uuid4().hex[:8]}.zip"
        zip_path = os.path.join(upload_dir, zip_name)

        files_added = []
        with engine.connect() as conn:
            for aid in asset_ids:
                row = conn.execute(text(
                    f"SELECT asset_name, local_path FROM {T_DATA_CATALOG} WHERE id = :id"
                ), {"id": aid}).fetchone()
                if row and row._mapping.get("local_path"):
                    fpath = row._mapping["local_path"]
                    if os.path.exists(fpath):
                        files_added.append((fpath, row._mapping["asset_name"]))

        if not files_added:
            return {"status": "error", "message": "未找到可打包的文件"}

        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
            for fpath, aname in files_added:
                arcname = os.path.basename(fpath)
                zf.write(fpath, arcname)

        return {
            "status": "ok",
            "zip_path": zip_path,
            "zip_name": zip_name,
            "file_count": len(files_added),
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


# ---------------------------------------------------------------------------
# Asset Reviews (用户评价)
# ---------------------------------------------------------------------------

def add_review(asset_id: int, username: str, rating: int, comment: str = "") -> dict:
    if rating < 1 or rating > 5:
        return {"status": "error", "message": "评分必须在 1-5 之间"}
    engine = get_engine()
    if not engine:
        return {"status": "error", "message": "数据库不可用"}
    try:
        with engine.connect() as conn:
            conn.execute(text(f"""
                INSERT INTO {T_ASSET_REVIEWS} (asset_id, username, rating, comment)
                VALUES (:a, :u, :r, :c)
                ON CONFLICT (asset_id, username)
                DO UPDATE SET rating = :r, comment = :c, created_at = NOW()
            """), {"a": asset_id, "u": username, "r": rating, "c": comment})
            conn.commit()
        return {"status": "ok"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


def get_reviews(asset_id: int) -> list:
    engine = get_engine()
    if not engine:
        return []
    try:
        with engine.connect() as conn:
            rows = conn.execute(text(f"""
                SELECT * FROM {T_ASSET_REVIEWS}
                WHERE asset_id = :a ORDER BY created_at DESC LIMIT 50
            """), {"a": asset_id}).fetchall()
        return [dict(r._mapping) for r in rows]
    except Exception:
        return []


def get_asset_rating(asset_id: int) -> dict:
    engine = get_engine()
    if not engine:
        return {"avg_rating": 0, "count": 0}
    try:
        with engine.connect() as conn:
            row = conn.execute(text(f"""
                SELECT AVG(rating) as avg_r, COUNT(*) as cnt
                FROM {T_ASSET_REVIEWS} WHERE asset_id = :a
            """), {"a": asset_id}).fetchone()
        if row:
            return {"avg_rating": round(float(row._mapping["avg_r"] or 0), 1),
                    "count": int(row._mapping["cnt"])}
        return {"avg_rating": 0, "count": 0}
    except Exception:
        return {"avg_rating": 0, "count": 0}


# ---------------------------------------------------------------------------
# Access Tracking (热度统计)
# ---------------------------------------------------------------------------

def log_access(asset_id: int, username: str, access_type: str = "view"):
    engine = get_engine()
    if not engine:
        return
    try:
        with engine.connect() as conn:
            conn.execute(text(f"""
                INSERT INTO {T_ACCESS_LOG} (asset_id, username, access_type)
                VALUES (:a, :u, :t)
            """), {"a": asset_id, "u": username, "t": access_type})
            conn.commit()
    except Exception:
        pass


def get_access_stats(asset_id: int = None, days: int = 30) -> dict:
    engine = get_engine()
    if not engine:
        return {"status": "error", "message": "数据库不可用"}
    try:
        with engine.connect() as conn:
            if asset_id:
                row = conn.execute(text(f"""
                    SELECT COUNT(*) as total,
                           COUNT(DISTINCT username) as unique_users
                    FROM {T_ACCESS_LOG}
                    WHERE asset_id = :a AND created_at >= NOW() - INTERVAL '{int(days)} days'
                """), {"a": asset_id}).fetchone()
                return {
                    "asset_id": asset_id,
                    "total_accesses": int(row._mapping["total"]),
                    "unique_users": int(row._mapping["unique_users"]),
                    "period_days": days,
                }
            else:
                rows = conn.execute(text(f"""
                    SELECT access_type, COUNT(*) as cnt
                    FROM {T_ACCESS_LOG}
                    WHERE created_at >= NOW() - INTERVAL '{int(days)} days'
                    GROUP BY access_type
                """)).fetchall()
                return {
                    "by_type": {r._mapping["access_type"]: int(r._mapping["cnt"]) for r in rows},
                    "period_days": days,
                }
    except Exception as e:
        return {"status": "error", "message": str(e)}


def get_hot_assets(limit: int = 10) -> list:
    engine = get_engine()
    if not engine:
        return []
    try:
        with engine.connect() as conn:
            rows = conn.execute(text(f"""
                SELECT al.asset_id, dc.asset_name, COUNT(*) as access_count,
                       COUNT(DISTINCT al.username) as unique_users
                FROM {T_ACCESS_LOG} al
                LEFT JOIN {T_DATA_CATALOG} dc ON al.asset_id = dc.id
                WHERE al.created_at >= NOW() - INTERVAL '30 days'
                GROUP BY al.asset_id, dc.asset_name
                ORDER BY access_count DESC
                LIMIT :lim
            """), {"lim": limit}).fetchall()
        return [dict(r._mapping) for r in rows]
    except Exception:
        return []
