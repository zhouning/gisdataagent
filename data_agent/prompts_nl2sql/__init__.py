"""Per-family prompt namespace for NL2SQL evaluation.

Layout:
    prompts_nl2sql/
        common/         # family-invariant domain facts (referenced, not loaded directly)
        gemini/         # Gemini-2.5-Flash instruction style
        deepseek/       # DeepSeek-V4-Flash instruction style
        qwen/           # (planned) Qwen instruction style

Public API:
    load_system_instruction(family) -> str
    load_grounding_template(family) -> str | None  (None means caller falls back to legacy)
    load_few_shots(family) -> list[dict] | None
"""
from __future__ import annotations

from pathlib import Path

_BASE = Path(__file__).resolve().parent
_FALLBACK_FAMILY = "gemini"


def _read_or_none(path: Path) -> str | None:
    if not path.exists():
        return None
    return path.read_text(encoding="utf-8")


def load_system_instruction(family: str) -> str:
    """Load the per-family system instruction string.

    Falls back to Gemini if the requested family directory is missing or has
    no system_instruction.md, so unknown families don't break the agent build.
    """
    text = _read_or_none(_BASE / family / "system_instruction.md")
    if text is None:
        text = _read_or_none(_BASE / _FALLBACK_FAMILY / "system_instruction.md")
    if text is None:
        raise RuntimeError(
            f"No system instruction found for family={family!r} or fallback "
            f"{_FALLBACK_FAMILY!r}. Expected file at "
            f"{_BASE / family / 'system_instruction.md'}"
        )
    return text


def load_grounding_template(family: str) -> str | None:
    """Load per-family grounding template (used by nl2sql_grounding).

    Returns None if no per-family override exists; caller should use the
    legacy in-code template builder.
    """
    return _read_or_none(_BASE / family / "grounding_template.md")


def load_few_shots(family: str) -> str | None:
    """Load per-family few-shot YAML config. Returns raw text or None."""
    return _read_or_none(_BASE / family / "few_shots.yaml")
