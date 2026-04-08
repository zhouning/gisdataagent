"""
Context Manager — backward compatibility shim (v19.0).

Delegates to context_engine.py. Existing callers that import from
context_manager continue to work unchanged.

Legacy signature: ContextManager().prepare(task_type, step, user_context)
New signature:    ContextEngine().prepare(query, task_type, user_context, token_budget)

The shim detects which signature is used and adapts.
"""
from .context_engine import (  # noqa: F401 — re-export for callers
    ContextBlock,
    ContextProvider,
    ContextEngine,
    get_context_engine,
)
from .observability import get_logger

logger = get_logger("context_manager")


# Legacy alias
SemanticProvider = None  # No longer needed; SemanticLayerProvider is auto-registered


class ContextManager:
    """Backward-compatible wrapper over ContextEngine.

    Supports both legacy (task_type, step, user_context) and
    new (query, task_type, user_context, token_budget) call conventions.
    """

    def __init__(self, max_tokens: int = 100_000):
        self._engine = get_context_engine()
        self._engine.max_tokens = max_tokens
        self.providers = self._engine.providers

    def register_provider(self, name, provider):
        """Legacy: register_provider(name, provider)."""
        provider.name = name
        self._engine.register_provider(provider)

    def prepare(self, *args, **kwargs):
        """Accept both old and new signatures.

        Old: prepare(task_type: str, step: str, user_context: dict)
        New: prepare(query: str, task_type: str, user_context: dict, token_budget: int)
        """
        if len(args) >= 3 and isinstance(args[2], dict):
            # Legacy: (task_type, step, user_context)
            task_type, _step, user_context = args[0], args[1], args[2]
            query = user_context.get("query", "")
            return self._engine.prepare(query, task_type, user_context)
        # New signature — pass through
        return self._engine.prepare(*args, **kwargs)

    def format_context(self, blocks):
        return self._engine.format_context(blocks)
