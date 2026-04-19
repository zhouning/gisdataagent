"""Mention Parser — detect and extract leading @handle from user messages."""
import re
from typing import Optional

_MENTION_RE = re.compile(r"^\s*@([\w\-]+)\s*(.*)", re.DOTALL)


def parse_mention(text: str) -> Optional[dict]:
    """Parse a leading @handle from message text.

    Returns {"handle": str, "remaining": str} or None if no leading mention.
    Only the first token after @ is treated as routing syntax.
    """
    m = _MENTION_RE.match(text)
    if not m:
        return None
    return {
        "handle": m.group(1),
        "remaining": m.group(2).strip(),
    }


def resolve_mention(parsed: Optional[dict], registry: list[dict]) -> Optional[dict]:
    """Resolve a parsed mention against the registry.

    Returns the matching target dict or None.
    """
    if not parsed:
        return None
    from .mention_registry import lookup
    return lookup(registry, parsed["handle"])
