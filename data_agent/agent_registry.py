"""
Agent Registry — service discovery and health tracking for multi-agent systems (v14.1).

Enables agents to register their capabilities, discover peers, and maintain
heartbeat-based liveness. PostgreSQL-backed for persistence across restarts.
"""
import json
import time
import logging
from typing import Optional

from sqlalchemy import text
from .db_engine import get_engine

logger = logging.getLogger("data_agent.agent_registry")

T_AGENT_REGISTRY = "agent_registry"


def ensure_registry_table():
    """Create agent registry table if not exists."""
    engine = get_engine()
    if not engine:
        return
    try:
        with engine.connect() as conn:
            conn.execute(text(f"""
                CREATE TABLE IF NOT EXISTS {T_AGENT_REGISTRY} (
                    id SERIAL PRIMARY KEY,
                    agent_id VARCHAR(100) UNIQUE NOT NULL,
                    agent_name VARCHAR(200) NOT NULL,
                    agent_url VARCHAR(500) DEFAULT '',
                    capabilities JSONB DEFAULT '[]'::jsonb,
                    status VARCHAR(20) DEFAULT 'online',
                    metadata JSONB DEFAULT '{{}}'::jsonb,
                    last_heartbeat TIMESTAMP DEFAULT NOW(),
                    registered_at TIMESTAMP DEFAULT NOW()
                )
            """))
            conn.commit()
    except Exception as e:
        logger.warning("Failed to ensure agent registry table: %s", e)


def register_agent(agent_id: str, agent_name: str, agent_url: str = "",
                   capabilities: list[str] = None, metadata: dict = None) -> dict:
    """Register or update an agent in the registry."""
    engine = get_engine()
    if not engine:
        return {"status": "error", "message": "Database not available"}
    try:
        with engine.connect() as conn:
            conn.execute(text(f"""
                INSERT INTO {T_AGENT_REGISTRY} (agent_id, agent_name, agent_url, capabilities, metadata, last_heartbeat)
                VALUES (:aid, :name, :url, :caps::jsonb, :meta::jsonb, NOW())
                ON CONFLICT (agent_id) DO UPDATE SET
                    agent_name = EXCLUDED.agent_name,
                    agent_url = EXCLUDED.agent_url,
                    capabilities = EXCLUDED.capabilities,
                    metadata = EXCLUDED.metadata,
                    status = 'online',
                    last_heartbeat = NOW()
            """), {
                "aid": agent_id,
                "name": agent_name,
                "url": agent_url,
                "caps": json.dumps(capabilities or []),
                "meta": json.dumps(metadata or {}),
            })
            conn.commit()
        return {"status": "ok", "agent_id": agent_id}
    except Exception as e:
        return {"status": "error", "message": str(e)}


def deregister_agent(agent_id: str) -> bool:
    """Remove an agent from the registry."""
    engine = get_engine()
    if not engine:
        return False
    try:
        with engine.connect() as conn:
            result = conn.execute(text(
                f"DELETE FROM {T_AGENT_REGISTRY} WHERE agent_id = :aid"
            ), {"aid": agent_id})
            conn.commit()
        return result.rowcount > 0
    except Exception:
        return False


def heartbeat(agent_id: str) -> bool:
    """Update heartbeat timestamp for an agent."""
    engine = get_engine()
    if not engine:
        return False
    try:
        with engine.connect() as conn:
            result = conn.execute(text(
                f"UPDATE {T_AGENT_REGISTRY} SET last_heartbeat = NOW(), status = 'online' "
                f"WHERE agent_id = :aid"
            ), {"aid": agent_id})
            conn.commit()
        return result.rowcount > 0
    except Exception:
        return False


def discover_agents(capability: str = None) -> list[dict]:
    """Discover registered agents, optionally filtered by capability."""
    engine = get_engine()
    if not engine:
        return []
    try:
        if capability:
            q = (f"SELECT agent_id, agent_name, agent_url, capabilities, status, "
                 f"metadata, last_heartbeat FROM {T_AGENT_REGISTRY} "
                 f"WHERE capabilities @> :cap::jsonb AND status = 'online' "
                 f"ORDER BY last_heartbeat DESC")
            params = {"cap": json.dumps([capability])}
        else:
            q = (f"SELECT agent_id, agent_name, agent_url, capabilities, status, "
                 f"metadata, last_heartbeat FROM {T_AGENT_REGISTRY} "
                 f"ORDER BY last_heartbeat DESC")
            params = {}
        with engine.connect() as conn:
            rows = conn.execute(text(q), params).fetchall()
        return [
            {
                "agent_id": r[0], "agent_name": r[1], "agent_url": r[2],
                "capabilities": r[3] if isinstance(r[3], list) else json.loads(r[3] or "[]"),
                "status": r[4],
                "metadata": r[5] if isinstance(r[5], dict) else json.loads(r[5] or "{}"),
                "last_heartbeat": str(r[6]),
            }
            for r in rows
        ]
    except Exception as e:
        logger.warning("Agent discovery failed: %s", e)
        return []


def mark_stale_agents(timeout_seconds: int = 300):
    """Mark agents that haven't sent heartbeat within timeout as 'offline'."""
    engine = get_engine()
    if not engine:
        return 0
    try:
        with engine.connect() as conn:
            result = conn.execute(text(
                f"UPDATE {T_AGENT_REGISTRY} SET status = 'offline' "
                f"WHERE status = 'online' AND last_heartbeat < NOW() - INTERVAL ':t seconds'"
            ), {"t": timeout_seconds})
            conn.commit()
        return result.rowcount
    except Exception:
        return 0


async def invoke_remote_agent(agent_url: str, message_text: str,
                              caller_id: str = "local") -> dict:
    """Invoke a remote agent's A2A execute endpoint (bidirectional RPC)."""
    import httpx
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                f"{agent_url.rstrip('/')}/api/a2a/execute",
                json={"message": message_text, "caller_id": caller_id},
                headers={"Content-Type": "application/json"},
            )
            resp.raise_for_status()
            return resp.json()
    except httpx.TimeoutException:
        return {"status": "error", "message": "Remote agent timed out"}
    except Exception as e:
        return {"status": "error", "message": str(e)}
