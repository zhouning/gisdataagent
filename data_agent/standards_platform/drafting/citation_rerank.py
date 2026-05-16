"""LLM rerank for citation candidates.

Uses the project's llm_client.generate_text wrapper (which routes through
model_gateway internally) to send a Chinese prompt asking the model to
score each candidate on relevance to the query, then re-sorts.
"""
from __future__ import annotations

import json
import re
from typing import Any

from ...observability import get_logger
from .citation_sources import Candidate

logger = get_logger("standards_platform.drafting.citation_rerank")

_PROMPT_TEMPLATE = """你是一个数据标准检索助手。给定一段查询和一组候选片段，
为每个候选给出 0-1 之间的相关度分数。返回 JSON 数组
[{{"index": <int>, "confidence": <float>, "reason": <string>}}]，
按 confidence 降序。只输出 JSON。

查询: {query}

候选:
{cands}
"""


def _format_candidates(candidates: list[Candidate]) -> str:
    lines: list[str] = []
    for i, c in enumerate(candidates):
        snippet = (c["snippet"] or "")[:200].replace("\n", " ")
        lines.append(f"[{i}] kind={c['kind']} snippet=\"{snippet}\"")
    return "\n".join(lines)


def _parse_json_array(raw: str) -> list[dict[str, Any]] | None:
    """Strip code fences and parse the first JSON array in the string."""
    cleaned = re.sub(r"^```(?:json)?\s*", "", raw.strip())
    cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        data = json.loads(cleaned)
        if isinstance(data, list):
            return data
    except json.JSONDecodeError:
        pass
    # Fallback: find the first [...] block
    m = re.search(r"\[.*\]", cleaned, re.DOTALL)
    if m:
        try:
            data = json.loads(m.group(0))
            if isinstance(data, list):
                return data
        except json.JSONDecodeError:
            return None
    return None


def rerank(query: str, candidates: list[Candidate], *,
           top_k: int = 20) -> list[Candidate]:
    """LLM rerank. On any failure, fall back to base_score sort."""
    if not candidates:
        return []
    try:
        from ...llm_client import generate_text
    except ImportError:
        logger.warning("llm_client unavailable; falling back to base_score")
        return sorted(candidates, key=lambda c: c["base_score"],
                      reverse=True)[:top_k]
    prompt = _PROMPT_TEMPLATE.format(
        query=query, cands=_format_candidates(candidates))
    try:
        raw = generate_text(prompt, tier="fast", timeout_ms=20_000)
    except Exception as e:
        logger.warning("llm rerank failed: %s; falling back", e)
        return sorted(candidates, key=lambda c: c["base_score"],
                      reverse=True)[:top_k]
    parsed = _parse_json_array(raw)
    if not parsed:
        logger.warning("llm rerank returned unparseable: %r", raw[:200])
        return sorted(candidates, key=lambda c: c["base_score"],
                      reverse=True)[:top_k]
    # Build output by index, attach confidence, drop indexes that don't
    # exist in the original list.
    seen_indexes: set[int] = set()
    out: list[Candidate] = []
    for entry in parsed:
        try:
            i = int(entry["index"])
            if i < 0 or i >= len(candidates) or i in seen_indexes:
                continue
            seen_indexes.add(i)
            conf = float(entry.get("confidence", candidates[i]["base_score"]))
        except (KeyError, ValueError, TypeError):
            continue
        cand = dict(candidates[i])  # shallow copy
        cand["extra"] = {**cand.get("extra", {}), "confidence": conf,
                         "rerank_reason": entry.get("reason", "")}
        out.append(cand)  # type: ignore[arg-type]
    # Append any candidates the LLM didn't score, ordered by base_score
    missing = [(i, c) for i, c in enumerate(candidates)
               if i not in seen_indexes]
    missing.sort(key=lambda t: t[1]["base_score"], reverse=True)
    for _, c in missing:
        copy = dict(c)
        copy["extra"] = {**copy.get("extra", {}),
                         "confidence": copy["base_score"]}
        out.append(copy)  # type: ignore[arg-type]
    return out[:top_k]
