"""
Lite Mode — minimal deployment without PostGIS (v22.0).

Enables `gis-agent init` quick start with DuckDB backend,
General Pipeline only, and minimal dependencies.

Usage:
    DB_BACKEND=duckdb gis-agent init     # create local DB + sample data
    DB_BACKEND=duckdb chainlit run ...    # run with DuckDB backend
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from .observability import get_logger

logger = get_logger("lite_mode")


def is_lite_mode() -> bool:
    """Check if running in Lite mode (DuckDB backend)."""
    return os.environ.get("DB_BACKEND", "postgres").lower() == "duckdb"


def init_lite_database(db_path: str = None) -> dict:
    """Initialize a local DuckDB database with schema and sample data.

    Creates tables matching the core agent_* schema for offline use.
    Returns status dict.
    """
    try:
        from .duckdb_adapter import DuckDBAdapter
    except ImportError:
        return {"status": "error", "message": "duckdb package not installed. Run: pip install duckdb"}

    db_path = db_path or os.path.join(os.path.dirname(__file__), "local.duckdb")

    adapter = DuckDBAdapter(db_path)

    # Create core tables
    tables_created = []

    # Users
    adapter.execute("""
        CREATE TABLE IF NOT EXISTS agent_users (
            id INTEGER PRIMARY KEY,
            username VARCHAR UNIQUE NOT NULL,
            password_hash VARCHAR,
            role VARCHAR DEFAULT 'analyst',
            email VARCHAR,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    tables_created.append("agent_users")

    # Data assets
    adapter.execute("""
        CREATE TABLE IF NOT EXISTS agent_data_assets (
            id INTEGER PRIMARY KEY,
            asset_name VARCHAR NOT NULL,
            display_name VARCHAR,
            owner_username VARCHAR DEFAULT 'admin',
            technical_metadata JSON DEFAULT '{}',
            business_metadata JSON DEFAULT '{}',
            operational_metadata JSON DEFAULT '{}',
            lineage_metadata JSON DEFAULT '{}',
            external_system VARCHAR,
            external_id VARCHAR,
            external_url VARCHAR,
            is_shared BOOLEAN DEFAULT false,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    tables_created.append("agent_data_assets")

    # Audit log
    adapter.execute("""
        CREATE TABLE IF NOT EXISTS agent_audit_log (
            id INTEGER PRIMARY KEY,
            username VARCHAR,
            action VARCHAR,
            status VARCHAR,
            details JSON DEFAULT '{}',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    tables_created.append("agent_audit_log")

    # Feedback
    adapter.execute("""
        CREATE TABLE IF NOT EXISTS agent_feedback (
            id INTEGER PRIMARY KEY,
            username VARCHAR,
            query_text VARCHAR,
            vote INTEGER,
            pipeline_type VARCHAR,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    tables_created.append("agent_feedback")

    # Seed default admin user
    existing = adapter.execute("SELECT COUNT(*) FROM agent_users WHERE username = 'admin'")
    if existing[0][0] == 0:
        adapter.execute("""
            INSERT INTO agent_users (id, username, role)
            VALUES (1, 'admin', 'admin')
        """)
        logger.info("Seeded default admin user")

    # Seed sample data asset
    existing = adapter.execute("SELECT COUNT(*) FROM agent_data_assets")
    if existing[0][0] == 0:
        adapter.execute("""
            INSERT INTO agent_data_assets (id, asset_name, display_name, owner_username,
                                           business_metadata)
            VALUES (1, 'sample_parcels', '示例地块数据', 'admin',
                    '{"description": "Lite 模式示例数据", "keywords": ["示例", "地块"]}')
        """)
        logger.info("Seeded sample data asset")

    adapter.close()

    result = {
        "status": "ok",
        "db_path": db_path,
        "tables_created": tables_created,
        "message": f"Lite 数据库初始化完成: {db_path}",
    }
    logger.info("Lite database initialized: %s (%d tables)", db_path, len(tables_created))
    return result


def get_lite_status() -> dict:
    """Get current Lite mode status and database info."""
    if not is_lite_mode():
        return {"lite_mode": False, "message": "运行在 PostgreSQL 模式"}

    db_path = os.path.join(os.path.dirname(__file__), "local.duckdb")
    exists = os.path.exists(db_path)

    info = {
        "lite_mode": True,
        "db_backend": "duckdb",
        "db_path": db_path,
        "db_exists": exists,
    }

    if exists:
        try:
            from .duckdb_adapter import DuckDBAdapter
            adapter = DuckDBAdapter(db_path)
            info["tables"] = adapter.list_tables()
            info["table_count"] = len(info["tables"])
            adapter.close()
        except Exception as e:
            info["error"] = str(e)

    return info
