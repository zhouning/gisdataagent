"""LLM-based strategy routing (DEPRECATED — use rule-based scoring instead).

The actual implementation lives in execution.py (same module globals as
_auto_select_strategy) for mock.patch compatibility. This module re-exports
for backward compatibility.
"""
# Re-export from execution where the function co-locates with its callers
from .execution import _llm_select_strategy

__all__ = ["_llm_select_strategy"]
