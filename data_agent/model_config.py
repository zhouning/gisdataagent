"""
Admin Model Configuration Manager (v23.0).

DB-backed persistent storage for model tier assignments and router model.
Falls back to environment variables when DB is unavailable.

Usage:
    from data_agent.model_config import get_config_manager

    mgr = get_config_manager()
    model = mgr.get_tier_model("fast")       # → "gemini-2.0-flash"
    mgr.set_tier_model("fast", "gemma-4-31b-it", "admin")
"""
from __future__ import annotations

import logging
import os
from typing import Optional

from sqlalchemy import text

logger = logging.getLogger("data_agent.model_config")

_ENV_DEFAULTS = {
    "tier_fast": ("MODEL_FAST", "gemini-2.0-flash"),
    "tier_standard": ("MODEL_STANDARD", "gemini-2.5-flash"),
    "tier_premium": ("MODEL_PREMIUM", "gemini-2.5-pro"),
    "router_model": ("ROUTER_MODEL", "gemini-2.0-flash"),
    "embedding_model": ("EMBEDDING_MODEL", "text-embedding-004"),
    "cost_guard_warn": ("COST_GUARD_WARN", "50000"),
    "cost_guard_abort": ("COST_GUARD_ABORT", "200000"),
    "cost_guard_usd_abort": ("COST_GUARD_USD_ABORT", "0"),
}


class ModelConfigManager:
    """Manages persistent model configuration with DB + env fallback."""

    def __init__(self):
        self._cache: dict[str, str] = {}
        self._loaded = False

    def _get_engine(self):
        try:
            from .db_engine import get_engine
            return get_engine()
        except Exception:
            return None

    def _ensure_table(self, engine):
        try:
            with engine.connect() as conn:
                conn.execute(text("""
                    CREATE TABLE IF NOT EXISTS agent_model_config (
                        config_key VARCHAR(50) PRIMARY KEY,
                        config_value VARCHAR(200) NOT NULL,
                        updated_by VARCHAR(100),
                        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                    )
                """))
                conn.commit()
        except Exception as e:
            logger.debug("Could not ensure model_config table: %s", e)

    def load(self) -> None:
        """Load config from DB, fallback to env vars."""
        # Start with env var defaults
        for key, (env_var, default) in _ENV_DEFAULTS.items():
            self._cache[key] = os.environ.get(env_var, default)

        # Override with DB values if available
        engine = self._get_engine()
        if engine:
            try:
                self._ensure_table(engine)
                with engine.connect() as conn:
                    rows = conn.execute(text(
                        "SELECT config_key, config_value FROM agent_model_config"
                    )).fetchall()
                    for row in rows:
                        self._cache[row[0]] = row[1]
                    if rows:
                        logger.info("Loaded %d model config entries from DB", len(rows))
            except Exception as e:
                logger.debug("DB model config load failed (using env defaults): %s", e)

        self._loaded = True

    def _ensure_loaded(self):
        if not self._loaded:
            self.load()

    def get_tier_model(self, tier: str) -> str:
        """Get model name for a tier (fast/standard/premium)."""
        self._ensure_loaded()
        return self._cache.get(f"tier_{tier}", _ENV_DEFAULTS.get(
            f"tier_{tier}", ("", "gemini-2.5-flash"))[1])

    def get_router_model(self) -> str:
        """Get the intent router model name."""
        self._ensure_loaded()
        return self._cache.get("router_model", "gemini-2.0-flash")

    def set_tier_model(self, tier: str, model_name: str, updated_by: str) -> bool:
        """Set model for a tier. Persists to DB + updates cache."""
        key = f"tier_{tier}"
        self._cache[key] = model_name
        return self._persist(key, model_name, updated_by)

    def set_router_model(self, model_name: str, updated_by: str) -> bool:
        """Set the intent router model. Persists to DB + updates cache."""
        self._cache["router_model"] = model_name
        return self._persist("router_model", model_name, updated_by)

    def get(self, key: str) -> Optional[str]:
        """Generic config getter."""
        self._ensure_loaded()
        return self._cache.get(key)

    def get_embedding_model(self) -> str:
        """Get the active embedding model name."""
        self._ensure_loaded()
        return self._cache.get("embedding_model", "text-embedding-004")

    def set_embedding_model(self, model_name: str, updated_by: str) -> bool:
        """Set the embedding model. Persists to DB + updates cache."""
        self._cache["embedding_model"] = model_name
        return self._persist("embedding_model", model_name, updated_by)

    def get_cost_guard_config(self) -> dict:
        """Return CostGuard thresholds as typed values."""
        self._ensure_loaded()
        return {
            "warn_threshold": int(self._cache.get("cost_guard_warn", "50000")),
            "abort_threshold": int(self._cache.get("cost_guard_abort", "200000")),
            "usd_abort": float(self._cache.get("cost_guard_usd_abort", "0")),
        }

    def set_cost_guard(self, key: str, value: str, updated_by: str) -> bool:
        """Set a CostGuard config value. key must be one of warn/abort/usd_abort."""
        valid = {"warn": "cost_guard_warn", "abort": "cost_guard_abort", "usd_abort": "cost_guard_usd_abort"}
        config_key = valid.get(key)
        if not config_key:
            return False
        self._cache[config_key] = value
        return self._persist(config_key, value, updated_by)

    def _persist(self, key: str, value: str, updated_by: str) -> bool:
        engine = self._get_engine()
        if not engine:
            return False
        try:
            self._ensure_table(engine)
            with engine.connect() as conn:
                conn.execute(text("""
                    INSERT INTO agent_model_config (config_key, config_value, updated_by, updated_at)
                    VALUES (:k, :v, :u, CURRENT_TIMESTAMP)
                    ON CONFLICT (config_key) DO UPDATE
                    SET config_value = :v, updated_by = :u, updated_at = CURRENT_TIMESTAMP
                """), {"k": key, "v": value, "u": updated_by})
                conn.commit()
            logger.info("Model config updated: %s = %s (by %s)", key, value, updated_by)
            return True
        except Exception as e:
            logger.warning("Failed to persist model config: %s", e)
            return False

    def get_full_config(self) -> dict:
        """Return full config for API exposure."""
        self._ensure_loaded()
        from .model_gateway import ModelRegistry
        from .embedding_gateway import EmbeddingRegistry
        ModelRegistry._ensure_initialized()
        available = ModelRegistry.list_models()
        available_embeddings = EmbeddingRegistry.list_models()
        return {
            "tiers": {
                "fast": {"model": self.get_tier_model("fast")},
                "standard": {"model": self.get_tier_model("standard")},
                "premium": {"model": self.get_tier_model("premium")},
            },
            "router_model": self.get_router_model(),
            "embedding_model": self.get_embedding_model(),
            "available_models": available,
            "available_embedding_models": available_embeddings,
        }


# Singleton
_manager: Optional[ModelConfigManager] = None


def get_config_manager() -> ModelConfigManager:
    """Get the singleton ModelConfigManager."""
    global _manager
    if _manager is None:
        _manager = ModelConfigManager()
    return _manager
