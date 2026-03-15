"""
Standardized tool response helpers.

All ADK tool functions should return JSON strings with a consistent structure:
  {"status": "ok"|"error", "message": "...", "files": [...], ...extra_data}

This module provides helper functions to build these responses uniformly.
"""
import json
from typing import Any


def tool_success(message: str, files: list = None, **data) -> str:
    """Build a success response JSON string.

    Args:
        message: Human-readable summary of what the tool did.
        files: List of output file paths (for artifact detection).
        **data: Additional result data to include.

    Returns:
        JSON string with status="ok".
    """
    resp = {"status": "ok", "message": message}
    if files:
        resp["files"] = files
    resp.update(data)
    return json.dumps(resp, default=str, ensure_ascii=False)


def tool_error(message: str, **data) -> str:
    """Build an error response JSON string.

    Args:
        message: Human-readable error description.
        **data: Additional error context.

    Returns:
        JSON string with status="error".
    """
    resp = {"status": "error", "message": message}
    resp.update(data)
    return json.dumps(resp, default=str, ensure_ascii=False)
