"""
Agent Messaging — inter-agent communication bus (v11.0.5, Design Pattern Ch17).

Provides a lightweight publish/subscribe message bus for internal agent
communication, bridging ADK transfer_to_agent with structured messaging.

v15.4: PostgreSQL persistence via migration 037_agent_messages.sql,
       delivery tracking, replay, and cleanup.
"""
import json
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
    """Publish/subscribe message bus with optional PostgreSQL persistence (v15.4)."""

    def __init__(self):
        self._subscribers: dict[str, list[Callable]] = {}
        self._message_log: list[AgentMessage] = []
        self._max_log_size = 1000
        self._persist = False
        self._table_ready = False
        self._ensure_persistence()

    def _ensure_persistence(self):
        """Check if the persistence table is available. Falls back to in-memory."""
        if self._table_ready:
            return
        try:
            from .db_engine import get_engine
            engine = get_engine()
            if engine:
                from sqlalchemy import text
                with engine.connect() as conn:
                    conn.execute(text(
                        "SELECT 1 FROM agent_messages LIMIT 0"
                    ))
                self._persist = True
                self._table_ready = True
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

        # Track whether at least one subscriber received the message
        delivered = False

        # Deliver to specific agent
        if msg.to_agent and msg.to_agent != "*" and msg.to_agent in self._subscribers:
            for cb in self._subscribers[msg.to_agent]:
                try:
                    cb(msg)
                    delivered = True
                except Exception as e:
                    logger.warning("Message delivery failed for %s: %s", msg.to_agent, e)

        # Broadcast (to_agent == "*")
        if msg.to_agent == "*":
            for name, callbacks in self._subscribers.items():
                if name != msg.from_agent:
                    for cb in callbacks:
                        try:
                            cb(msg)
                            delivered = True
                        except Exception as e:
                            logger.warning("Broadcast delivery failed for %s: %s", name, e)

        # Persist to DB
        if self._persist:
            self._persist_message(msg, delivered=delivered)

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

    # ------------------------------------------------------------------
    # Persistence helpers
    # ------------------------------------------------------------------

    def _persist_message(self, msg: AgentMessage, delivered: bool = False):
        """Save message to PostgreSQL for audit trail and delivery guarantee."""
        try:
            from .db_engine import get_engine
            from sqlalchemy import text
            engine = get_engine()
            if not engine:
                return
            with engine.connect() as conn:
                conn.execute(text(
                    "INSERT INTO agent_messages "
                    "(message_id, from_agent, to_agent, message_type, payload, "
                    "correlation_id, delivered) "
                    "VALUES (:mid, :from, :to, :mtype, :payload::jsonb, :cid, :delivered)"
                ), {
                    "mid": msg.message_id,
                    "from": msg.from_agent,
                    "to": msg.to_agent,
                    "mtype": msg.message_type,
                    "payload": json.dumps(msg.payload, ensure_ascii=False, default=str),
                    "cid": msg.correlation_id,
                    "delivered": delivered,
                })
                conn.commit()
        except Exception as e:
            logger.debug("Message persistence failed: %s", e)

    def mark_delivered(self, message_id: str):
        """Mark a persisted message as delivered."""
        try:
            from .db_engine import get_engine
            from sqlalchemy import text
            engine = get_engine()
            if not engine:
                return
            with engine.connect() as conn:
                conn.execute(
                    text("UPDATE agent_messages SET delivered = TRUE "
                         "WHERE message_id = :mid"),
                    {"mid": message_id},
                )
                conn.commit()
        except Exception as e:
            logger.debug("mark_delivered failed: %s", e)

    def get_undelivered(self, agent_name: str, limit: int = 100) -> list[dict]:
        """Return undelivered messages for *agent_name*, oldest first."""
        try:
            from .db_engine import get_engine
            from sqlalchemy import text
            engine = get_engine()
            if not engine:
                return []
            with engine.connect() as conn:
                rows = conn.execute(
                    text(
                        "SELECT message_id, from_agent, to_agent, message_type, "
                        "payload, correlation_id, created_at "
                        "FROM agent_messages "
                        "WHERE to_agent = :name AND delivered = FALSE "
                        "ORDER BY created_at "
                        "LIMIT :lim"
                    ),
                    {"name": agent_name, "lim": limit},
                ).fetchall()
                return [
                    {
                        "message_id": r.message_id,
                        "from_agent": r.from_agent,
                        "to_agent": r.to_agent,
                        "message_type": r.message_type,
                        "payload": r.payload,
                        "correlation_id": r.correlation_id,
                        "created_at": str(r.created_at),
                    }
                    for r in rows
                ]
        except Exception as e:
            logger.debug("get_undelivered failed: %s", e)
            return []

    def replay_undelivered(self, agent_name: str) -> int:
        """Fetch undelivered messages for *agent_name*, dispatch to subscribers,
        and mark each as delivered.  Returns the number replayed."""
        rows = self.get_undelivered(agent_name)
        if not rows:
            return 0

        replayed = 0
        for row in rows:
            payload = row["payload"]
            if isinstance(payload, str):
                try:
                    payload = json.loads(payload)
                except (json.JSONDecodeError, TypeError):
                    payload = {}

            msg = AgentMessage(
                message_id=row["message_id"],
                from_agent=row["from_agent"],
                to_agent=row["to_agent"],
                message_type=row["message_type"],
                payload=payload if isinstance(payload, dict) else {},
                correlation_id=row["correlation_id"],
            )

            delivered = False
            if agent_name in self._subscribers:
                for cb in self._subscribers[agent_name]:
                    try:
                        cb(msg)
                        delivered = True
                    except Exception as e:
                        logger.warning("Replay delivery failed for %s: %s", agent_name, e)

            if delivered:
                self.mark_delivered(row["message_id"])
                replayed += 1

        return replayed

    def cleanup_old_messages(self, days: int = 30) -> int:
        """Delete messages older than *days*. Returns number of rows removed."""
        try:
            from .db_engine import get_engine
            from sqlalchemy import text
            engine = get_engine()
            if not engine:
                return 0
            with engine.connect() as conn:
                result = conn.execute(
                    text(
                        "DELETE FROM agent_messages "
                        "WHERE created_at < NOW() - MAKE_INTERVAL(days => :days)"
                    ),
                    {"days": days},
                )
                conn.commit()
                return result.rowcount
        except Exception as e:
            logger.debug("cleanup_old_messages failed: %s", e)
            return 0


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
