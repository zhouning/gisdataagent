"""
Plugin Registry — dynamic DataPanel tab plugins (v14.3).

Allows users and developers to register custom DataPanel tabs via plugin manifests.
Plugins are loaded dynamically at runtime.
"""
import json
import logging
from typing import Optional

from sqlalchemy import text
from .db_engine import get_engine

logger = logging.getLogger("data_agent.plugin_registry")

T_PLUGINS = "agent_plugins"


def ensure_plugins_table():
    """Create plugins table if not exists."""
    engine = get_engine()
    if not engine:
        return
    try:
        with engine.connect() as conn:
            conn.execute(text(f"""
                CREATE TABLE IF NOT EXISTS {T_PLUGINS} (
                    id SERIAL PRIMARY KEY,
                    plugin_id VARCHAR(100) UNIQUE NOT NULL,
                    plugin_name VARCHAR(200) NOT NULL,
                    description TEXT DEFAULT '',
                    version VARCHAR(20) DEFAULT '1.0.0',
                    tab_label VARCHAR(30) NOT NULL,
                    entry_url VARCHAR(500) DEFAULT '',
                    icon VARCHAR(50) DEFAULT '',
                    config JSONB DEFAULT '{{}}'::jsonb,
                    enabled BOOLEAN DEFAULT TRUE,
                    owner_username VARCHAR(100),
                    is_shared BOOLEAN DEFAULT FALSE,
                    installed_at TIMESTAMP DEFAULT NOW()
                )
            """))
            conn.commit()
    except Exception as e:
        logger.warning("Failed to ensure plugins table: %s", e)


def register_plugin(plugin_id: str, plugin_name: str, tab_label: str,
                     description: str = "", entry_url: str = "",
                     owner_username: str = None) -> dict:
    """Register a new DataPanel tab plugin."""
    engine = get_engine()
    if not engine:
        return {"status": "error", "message": "Database not available"}
    try:
        with engine.connect() as conn:
            conn.execute(text(f"""
                INSERT INTO {T_PLUGINS}
                    (plugin_id, plugin_name, tab_label, description, entry_url, owner_username)
                VALUES (:pid, :name, :label, :desc, :url, :owner)
                ON CONFLICT (plugin_id) DO UPDATE SET
                    plugin_name = EXCLUDED.plugin_name,
                    tab_label = EXCLUDED.tab_label,
                    description = EXCLUDED.description,
                    entry_url = EXCLUDED.entry_url
            """), {
                "pid": plugin_id, "name": plugin_name, "label": tab_label,
                "desc": description, "url": entry_url, "owner": owner_username,
            })
            conn.commit()
        return {"status": "ok", "plugin_id": plugin_id}
    except Exception as e:
        return {"status": "error", "message": str(e)}


def list_plugins(include_disabled: bool = False) -> list[dict]:
    """List registered plugins."""
    engine = get_engine()
    if not engine:
        return []
    try:
        q = f"SELECT plugin_id, plugin_name, description, version, tab_label, entry_url, enabled, owner_username FROM {T_PLUGINS}"
        if not include_disabled:
            q += " WHERE enabled = TRUE"
        q += " ORDER BY installed_at"
        with engine.connect() as conn:
            rows = conn.execute(text(q)).fetchall()
        return [
            {
                "plugin_id": r[0], "plugin_name": r[1], "description": r[2],
                "version": r[3], "tab_label": r[4], "entry_url": r[5],
                "enabled": bool(r[6]), "owner_username": r[7],
            }
            for r in rows
        ]
    except Exception:
        return []


def uninstall_plugin(plugin_id: str) -> bool:
    """Remove a plugin."""
    engine = get_engine()
    if not engine:
        return False
    try:
        with engine.connect() as conn:
            result = conn.execute(text(
                f"DELETE FROM {T_PLUGINS} WHERE plugin_id = :pid"
            ), {"pid": plugin_id})
            conn.commit()
        return result.rowcount > 0
    except Exception:
        return False
