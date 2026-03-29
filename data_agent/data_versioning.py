"""
Data Versioning — version management, incremental updates, notifications (v15.0).

Tracks asset versions with snapshots, supports diff-based incremental updates,
and notifies related users when assets are updated.
"""

import json
import logging
import os
import shutil
import uuid

from sqlalchemy import text

from .db_engine import get_engine

logger = logging.getLogger(__name__)

T_DATA_CATALOG = "agent_data_catalog"
T_ASSET_VERSIONS = "agent_asset_versions"
T_UPDATE_NOTIFICATIONS = "agent_update_notifications"


# ---------------------------------------------------------------------------
# Version Management
# ---------------------------------------------------------------------------

def create_version_snapshot(asset_id: int, username: str, change_summary: str = "") -> dict:
    """Create a version snapshot of a data asset before update."""
    engine = get_engine()
    if not engine:
        return {"status": "error", "message": "数据库不可用"}
    try:
        with engine.connect() as conn:
            row = conn.execute(text(
                f"SELECT asset_name, local_path, version, feature_count, file_size_bytes "
                f"FROM {T_DATA_CATALOG} WHERE id = :id"
            ), {"id": asset_id}).fetchone()
            if not row:
                return {"status": "error", "message": "资产未找到"}

            asset = row._mapping
            current_version = asset.get("version", 1) or 1
            local_path = asset.get("local_path", "")

            # Create snapshot copy
            snapshot_path = ""
            if local_path and os.path.exists(local_path):
                snap_dir = os.path.join(os.path.dirname(local_path), ".versions")
                os.makedirs(snap_dir, exist_ok=True)
                ext = os.path.splitext(local_path)[1]
                snap_name = f"{os.path.splitext(os.path.basename(local_path))[0]}_v{current_version}{ext}"
                snapshot_path = os.path.join(snap_dir, snap_name)
                shutil.copy2(local_path, snapshot_path)

            # Record version
            conn.execute(text(f"""
                INSERT INTO {T_ASSET_VERSIONS}
                (asset_id, version, snapshot_path, file_size_bytes, feature_count, change_summary, created_by)
                VALUES (:a, :v, :sp, :fs, :fc, :cs, :cb)
            """), {
                "a": asset_id, "v": current_version, "sp": snapshot_path,
                "fs": asset.get("file_size_bytes", 0) or 0,
                "fc": asset.get("feature_count", 0) or 0,
                "cs": change_summary, "cb": username,
            })

            # Bump version
            new_version = current_version + 1
            conn.execute(text(f"""
                UPDATE {T_DATA_CATALOG}
                SET version = :v, version_note = :vn, updated_at = NOW()
                WHERE id = :id
            """), {"v": new_version, "vn": change_summary, "id": asset_id})
            conn.commit()

        return {
            "status": "ok", "asset_id": asset_id,
            "old_version": current_version, "new_version": new_version,
            "snapshot_path": snapshot_path,
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


def list_versions(asset_id: int) -> list:
    """List all version snapshots for an asset."""
    engine = get_engine()
    if not engine:
        return []
    try:
        with engine.connect() as conn:
            rows = conn.execute(text(f"""
                SELECT * FROM {T_ASSET_VERSIONS}
                WHERE asset_id = :a ORDER BY version DESC
            """), {"a": asset_id}).fetchall()
        return [dict(r._mapping) for r in rows]
    except Exception:
        return []


def rollback_version(asset_id: int, target_version: int, username: str) -> dict:
    """Rollback an asset to a previous version snapshot."""
    engine = get_engine()
    if not engine:
        return {"status": "error", "message": "数据库不可用"}
    try:
        with engine.connect() as conn:
            # Find target snapshot
            row = conn.execute(text(f"""
                SELECT snapshot_path FROM {T_ASSET_VERSIONS}
                WHERE asset_id = :a AND version = :v
            """), {"a": asset_id, "v": target_version}).fetchone()
            if not row or not row._mapping.get("snapshot_path"):
                return {"status": "error", "message": f"版本 {target_version} 快照不存在"}

            snap_path = row._mapping["snapshot_path"]
            if not os.path.exists(snap_path):
                return {"status": "error", "message": f"快照文件已丢失: {snap_path}"}

            # Get current path
            current = conn.execute(text(
                f"SELECT local_path, version FROM {T_DATA_CATALOG} WHERE id = :id"
            ), {"id": asset_id}).fetchone()
            if not current:
                return {"status": "error", "message": "资产未找到"}

            current_path = current._mapping.get("local_path", "")
            current_version = current._mapping.get("version", 1)

            # Snapshot current before rollback
            if current_path and os.path.exists(current_path):
                snap_dir = os.path.join(os.path.dirname(current_path), ".versions")
                os.makedirs(snap_dir, exist_ok=True)
                ext = os.path.splitext(current_path)[1]
                backup = os.path.join(snap_dir, f"{os.path.splitext(os.path.basename(current_path))[0]}_v{current_version}{ext}")
                shutil.copy2(current_path, backup)

            # Restore snapshot
            shutil.copy2(snap_path, current_path)

            # Update version
            conn.execute(text(f"""
                UPDATE {T_DATA_CATALOG}
                SET version = :v, version_note = :vn, updated_at = NOW()
                WHERE id = :id
            """), {"v": target_version, "vn": f"Rolled back from v{current_version}", "id": asset_id})
            conn.commit()

        return {"status": "ok", "asset_id": asset_id, "rolled_back_to": target_version}
    except Exception as e:
        return {"status": "error", "message": str(e)}


# ---------------------------------------------------------------------------
# Update Notifications
# ---------------------------------------------------------------------------

def notify_asset_update(asset_id: int, asset_name: str, update_type: str = "version",
                        message: str = "", related_users: list = None) -> dict:
    """Create a notification for asset update."""
    engine = get_engine()
    if not engine:
        return {"status": "error", "message": "数据库不可用"}
    try:
        with engine.connect() as conn:
            conn.execute(text(f"""
                INSERT INTO {T_UPDATE_NOTIFICATIONS}
                (asset_id, asset_name, update_type, message, notified_users)
                VALUES (:a, :n, :t, :m, :u)
            """), {
                "a": asset_id, "n": asset_name, "t": update_type,
                "m": message, "u": json.dumps(related_users or []),
            })
            conn.commit()
        return {"status": "ok"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


def get_notifications(username: str, unread_only: bool = True, limit: int = 20) -> list:
    """Get notifications for a user."""
    engine = get_engine()
    if not engine:
        return []
    try:
        with engine.connect() as conn:
            where = "WHERE notified_users @> :u::jsonb"
            if unread_only:
                where += " AND is_read = false"
            rows = conn.execute(text(f"""
                SELECT * FROM {T_UPDATE_NOTIFICATIONS}
                {where} ORDER BY created_at DESC LIMIT :lim
            """), {"u": json.dumps([username]), "lim": limit}).fetchall()
        return [dict(r._mapping) for r in rows]
    except Exception:
        return []


def mark_notification_read(notification_id: int) -> dict:
    engine = get_engine()
    if not engine:
        return {"status": "error", "message": "数据库不可用"}
    try:
        with engine.connect() as conn:
            conn.execute(text(f"""
                UPDATE {T_UPDATE_NOTIFICATIONS} SET is_read = true WHERE id = :id
            """), {"id": notification_id})
            conn.commit()
        return {"status": "ok"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


# ---------------------------------------------------------------------------
# Incremental Update
# ---------------------------------------------------------------------------

def compare_datasets(old_path: str, new_path: str) -> dict:
    """Compare two datasets and return diff summary (added/removed/changed features)."""
    try:
        import geopandas as gpd
        old_gdf = gpd.read_file(old_path)
        new_gdf = gpd.read_file(new_path)

        old_count = len(old_gdf)
        new_count = len(new_gdf)
        added = max(0, new_count - old_count)
        removed = max(0, old_count - new_count)

        # Column comparison
        old_cols = set(old_gdf.columns)
        new_cols = set(new_gdf.columns)
        added_cols = list(new_cols - old_cols)
        removed_cols = list(old_cols - new_cols)

        # CRS comparison
        crs_changed = str(old_gdf.crs) != str(new_gdf.crs) if old_gdf.crs and new_gdf.crs else False

        return {
            "status": "ok",
            "old_features": old_count, "new_features": new_count,
            "features_added": added, "features_removed": removed,
            "columns_added": added_cols, "columns_removed": removed_cols,
            "crs_changed": crs_changed,
            "old_crs": str(old_gdf.crs), "new_crs": str(new_gdf.crs),
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}
