"""
Agent Messaging — inter-agent communication bus (v11.0.5, Design Pattern Ch17).

Provides a lightweight publish/subscribe message bus for internal agent
communication, bridging ADK transfer_to_agent with structured messaging.
"""
import time
import uuid
from dataclasses import dataclass, field
from typing import Callable, Optional

try:
    from .observability import get_logger
    logger = get_logger("agent_messaging")
except Exception:
    import logging
    logger = logging.getLogger("agent_messaging")


@dataclass
class AgentMessage:
    """A message exchanged between agents."""
    message_id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    from_agent: str = ""
    to_agent: str = ""
    message_type: str = "notification"  # request | response | notification
    payload: dict = field(default_factory=dict)
    correlation_id: str = ""
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "message_id": self.message_id,
            "from_agent": self.from_agent,
            "to_agent": self.to_agent,
            "message_type": self.message_type,
            "payload": self.payload,
            "correlation_id": self.correlation_id,
            "timestamp": self.timestamp,
        }


class AgentMessageBus:
    """Publish/subscribe message bus with optional PostgreSQL persistence (v14.1)."""

    def __init__(self):
        self._subscribers: dict[str, list[Callable]] = {}
        self._message_log: list[AgentMessage] = []
        self._max_log_size = 1000
        self._persist = False
        self._ensure_persistence()

    def _ensure_persistence(self):
        """Try to create the persistence table. Falls back to in-memory."""
        try:
            from .db_engine import get_engine
            engine = get_engine()
            if engine:
                from sqlalchemy import text
                with engine.connect() as conn:
                    conn.execute(text("""
                        CREATE TABLE IF NOT EXISTS agent_messages (
                            id SERIAL PRIMARY KEY,
                            message_id VARCHAR(20) NOT NULL,
                            from_agent VARCHAR(100),
                            to_agent VARCHAR(100),
                            message_type VARCHAR(30) DEFAULT 'notification',
                            payload JSONB DEFAULT '{}',
                            correlation_id VARCHAR(100) DEFAULT '',
                            delivered BOOLEAN DEFAULT FALSE,
                            created_at TIMESTAMP DEFAULT NOW()
                        )
                    """))
                    conn.commit()
                self._persist = True
        except Exception:
            pass  # In-memory fallback

    def subscribe(self, agent_name: str, callback: Callable[[AgentMessage], None]):
        """Register a callback for messages sent to agent_name."""
        if agent_name not in self._subscribers:
            self._subscribers[agent_name] = []
        self._subscribers[agent_name].append(callback)

    def unsubscribe(self, agent_name: str):
        """Remove all subscriptions for an agent."""
        self._subscribers.pop(agent_name, None)

    def publish(self, msg: AgentMessage):
        """Send a message to the target agent(s). Persists to DB if available."""
        self._message_log.append(msg)
        if len(self._message_log) > self._max_log_size:
            self._message_log = self._message_log[-500:]  # trim

        # Persist to DB
        if self._persist:
            self._persist_message(msg)

        # Deliver to specific agent
        if msg.to_agent and msg.to_agent in self._subscribers:
            for cb in self._subscribers[msg.to_agent]:
                try:
                    cb(msg)
                except Exception as e:
                    logger.warning("Message delivery failed for %s: %s", msg.to_agent, e)

        # Broadcast (to_agent == "*")
        if msg.to_agent == "*":
            for name, callbacks in self._subscribers.items():
                if name != msg.from_agent:
                    for cb in callbacks:
                        try:
                            cb(msg)
                        except Exception as e:
                            logger.warning("Broadcast delivery failed for %s: %s", name, e)

    def get_message_log(self, agent_name: str = None, limit: int = 50) -> list[dict]:
        """Get recent messages, optionally filtered by agent."""
        msgs = self._message_log
        if agent_name:
            msgs = [m for m in msgs if m.from_agent == agent_name or m.to_agent == agent_name]
        return [m.to_dict() for m in msgs[-limit:]]

    def clear(self):
        """Clear all subscriptions and message log."""
        self._subscribers.clear()
        self._message_log.clear()

    def _persist_message(self, msg: AgentMessage):
        """Save message to PostgreSQL for audit trail and delivery guarantee."""
        try:
            import json
            from .db_engine import get_engine
            from sqlalchemy import text
            engine = get_engine()
            if not engine:
                return
            with engine.connect() as conn:
                conn.execute(text(
                    "INSERT INTO agent_messages (message_id, from_agent, to_agent, "
                    "message_type, payload, correlation_id) "
                    "VALUES (:mid, :from, :to, :mtype, :payload::jsonb, :cid)"
                ), {
                    "mid": msg.message_id, "from": msg.from_agent,
                    "to": msg.to_agent, "mtype": msg.message_type,
                    "payload": json.dumps(msg.payload, ensure_ascii=False, default=str),
                    "cid": msg.correlation_id,
                })
                conn.commit()
        except Exception as e:
            logger.debug("Message persistence failed: %s", e)


# Singleton
_bus: Optional[AgentMessageBus] = None


def get_message_bus() -> AgentMessageBus:
    global _bus
    if _bus is None:
        _bus = AgentMessageBus()
    return _bus


def reset_message_bus():
    global _bus
    _bus = None
