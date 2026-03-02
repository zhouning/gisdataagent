"""Backward-compatible re-export.

The canonical evaluation agent now lives in ``data_agent.evals.agent``
(required by ADK's module resolution convention).  This shim re-exports
``root_agent`` so existing imports still work.
"""

from data_agent.evals.agent import root_agent  # noqa: F401
