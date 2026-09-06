"""Metadata-driven source selection for the Abu Dhabi left-chat NL2SQL routes.

The left chat accepts ordinary natural-language questions.  Explicit ``@``
mentions remain the highest-precedence route, while this module resolves an
unprefixed question from the currently published semantic artifacts.  It does
not contain benchmark questions, SQL, or expected values; only published
labels, aliases, table bindings, and metric-contract vocabulary are used.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from .abu_dhabi_artifact_registry import current_artifact_path

SourceKey = Literal["liveability", "makani"]
Disposition = Literal["route", "clarify", "none"]

_SOURCE_KEYS: tuple[SourceKey, ...] = ("liveability", "makani")
_GENERIC_TERMS = {
    "data",
    "dataset",
    "table",
    "record",
    "records",
    "count",
    "number",
    "how many",
    "统计",
    "数量",
    "多少",
    "数据",
    "记录",
    "表",
    "字段",
    "结果",
    "平均",
    "总数",
    "值",
    "the",
    "and",
    "of",
    "by",
}
_TOKEN_RE = re.compile(r"[a-z0-9]+(?:[_-][a-z0-9]+)*|[\u3400-\u9fff]{2,}|[\u0600-\u06ff]{2,}", re.I)


@dataclass(frozen=True)
class SourceRouteDecision:
    disposition: Disposition
    source_key: SourceKey | None
    confidence: float
    margin: float
    evidence: tuple[str, ...]
    reason: str


def _normalize(value: str) -> str:
    text = str(value or "").casefold().replace("_", " ").replace("-", " ")
    return re.sub(r"\s+", " ", text).strip()


def _add_terms(target: set[str], value: Any) -> None:
    if isinstance(value, str):
        normalized = _normalize(value)
        if normalized and normalized not in _GENERIC_TERMS:
            target.add(normalized)
    elif isinstance(value, (list, tuple, set)):
        for item in value:
            _add_terms(target, item)
    elif isinstance(value, dict):
        for item in value.values():
            _add_terms(target, item)


def _is_usable_term(term: str) -> bool:
    if not term or term in _GENERIC_TERMS:
        return False
    # Avoid letting single-character labels or generic English stop words
    # decide a database.  CJK/Arabic labels need at least two code points;
    # ASCII labels need a meaningful token length.
    if re.fullmatch(r"[\u3400-\u9fff\u0600-\u06ff]+", term):
        return len(term) >= 2
    return len(re.sub(r"[^a-z0-9]", "", term)) >= 4


def _load_source_terms(source_key: SourceKey) -> tuple[str, ...]:
    semantic_path = current_artifact_path(source_key, "semantic")
    payload = json.loads(Path(semantic_path).read_text(encoding="utf-8"))
    terms: set[str] = set()
    binding = payload.get("source_binding") or {}
    _add_terms(terms, binding.get("database_name"))
    _add_terms(terms, binding.get("allowed_schemas"))

    # Published business assets are the primary source-selection evidence.
    for asset in payload.get("semantic_assets") or []:
        if not isinstance(asset, dict):
            continue
        for key in (
            "asset_id",
            "labels",
            "aliases",
            "retrieval_terms",
            "description",
            "physical_tables",
            "semantic_entity",
        ):
            _add_terms(terms, asset.get(key))
        for field in asset.get("fields") or []:
            if isinstance(field, dict):
                for key in ("semantic_field", "physical_field", "labels", "aliases", "description"):
                    _add_terms(terms, field.get(key))

    # Table bindings cover technical resources not represented as a business
    # asset and keep the router useful as new sources are registered.
    for binding_item in payload.get("table_bindings") or []:
        if not isinstance(binding_item, dict):
            continue
        for key in (
            "physical_table",
            "semantic_entity",
            "labels",
            "aliases",
            "semantic_candidate_label",
            "semantic_candidate_aliases",
        ):
            _add_terms(terms, binding_item.get(key))

    # A complete contract match is strong evidence, but the router still
    # works for simple questions that do not contain every contract dimension.
    for contract in payload.get("metric_contracts") or []:
        if not isinstance(contract, dict):
            continue
        match = contract.get("match") or {}
        _add_terms(terms, match.get("specificity_terms"))
        _add_terms(terms, (match.get("required_term_groups") or {}).get("zh"))
        _add_terms(terms, (match.get("required_term_groups") or {}).get("en"))
        _add_terms(terms, (match.get("required_term_groups") or {}).get("ar"))
    return tuple(
        sorted(
            (term for term in terms if _is_usable_term(term)),
            key=lambda item: (-len(item), item),
        )
    )


@lru_cache(maxsize=4)
def _cached_source_terms(source_key: SourceKey, artifact_path: str) -> tuple[str, ...]:
    # artifact_path participates in the cache key so a newly published bundle
    # invalidates the old vocabulary without a process restart.
    del artifact_path
    return _load_source_terms(source_key)


def _source_terms(source_key: SourceKey) -> tuple[str, ...]:
    path = str(current_artifact_path(source_key, "semantic"))
    return _cached_source_terms(source_key, path)


def _score(question: str, terms: tuple[str, ...]) -> tuple[float, tuple[str, ...]]:
    normalized = _normalize(question)
    tokens = set(_TOKEN_RE.findall(normalized))
    matched: list[tuple[float, str]] = []
    for term in terms:
        # Match both the complete phrase and tokenized variants.  The latter
        # handles a user writing ``udm_building`` while the artifact uses a
        # spaced display label.
        if term in normalized or term.replace(" ", "_") in normalized:
            compact = re.sub(r"\s+", "", term)
            weight = min(12.0, max(1.0, len(compact) / 2.0))
            if term in tokens:
                weight += 1.0
            matched.append((weight, term))
    matched.sort(reverse=True)
    selected: list[str] = []
    score = 0.0
    for weight, term in matched:
        # Multiple descriptions often repeat the same concept.  Limit their
        # contribution so one artifact cannot win by verbosity alone.
        if any(term == item or term in item or item in term for item in selected):
            continue
        selected.append(term)
        score += weight
        if len(selected) >= 8:
            break
    return score, tuple(selected)


def resolve_abu_dhabi_source(question: str) -> SourceRouteDecision:
    """Resolve an unprefixed question against published source semantics."""

    text = str(question or "").strip()
    if not text:
        return SourceRouteDecision("none", None, 0.0, 0.0, (), "empty_question")

    scored: list[tuple[SourceKey, float, tuple[str, ...]]] = []
    for source_key in _SOURCE_KEYS:
        try:
            score, evidence = _score(text, _source_terms(source_key))
        except Exception:
            # Artifact validation remains the execution boundary.  Failure to
            # load vocabulary must not make the general app crash.
            score, evidence = 0.0, ()
        scored.append((source_key, score, evidence))
    scored.sort(key=lambda item: item[1], reverse=True)
    best_key, best_score, best_evidence = scored[0]
    second_score = scored[1][1] if len(scored) > 1 else 0.0
    margin = best_score - second_score
    # A three-character business label (for example ``建筑物``) is sufficient
    # evidence when it appears in only one published source.  Generic
    # two-character labels are intentionally kept below this threshold.
    if best_score < 1.25:
        return SourceRouteDecision(
            "none", None, best_score, margin, best_evidence,
            "no_unique_source_evidence",
        )
    # A close tie means the question contains concepts present in both
    # published semantic layers.  Ask for a source instead of guessing.
    if second_score >= 1.0 and margin < max(1.5, best_score * 0.2):
        return SourceRouteDecision(
            "clarify", None, best_score, margin,
            tuple(dict.fromkeys(best_evidence + scored[1][2]))[:8],
            "multiple_registered_sources_match",
        )
    return SourceRouteDecision(
        "route", best_key, best_score, margin, best_evidence,
        "unique_published_semantic_source_match",
    )


def clear_source_router_cache() -> None:
    """Clear cached vocabulary after an artifact publication in tests/tools."""

    _cached_source_terms.cache_clear()


__all__ = [
    "SourceRouteDecision",
    "clear_source_router_cache",
    "resolve_abu_dhabi_source",
]
