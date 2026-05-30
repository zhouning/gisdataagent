"""Derivation runner — strategy registry + dispatch.

Wave 5 ships only `to_semantic_hint`; remaining strategies are placeholders
returning 'coming_soon' from get_strategy_status().
"""
from __future__ import annotations

from typing import Optional

from .strategies.defect_taxonomy import DefectTaxonomyStrategy
from .strategies.qc_rule import QcRuleStrategy
from .strategies.semantic_hint import SemanticHintStrategy
from .strategies.synonym import SynonymStrategy
from .strategies.value_domain import ValueDomainStrategy
from .strategy_base import DerivationStrategy


_REGISTRY: dict[str, Optional[DerivationStrategy]] = {
    "to_semantic_hint": SemanticHintStrategy(),
    "to_synonym": SynonymStrategy(),
    "to_value_semantics": ValueDomainStrategy(),
    "to_qc_rule": QcRuleStrategy(),
    "to_defect_code": DefectTaxonomyStrategy(),
    "to_data_model": None,
}

# Friendly descriptions for UI
_DESCRIPTIONS: dict[str, str] = {
    "to_semantic_hint": "派生标准 data_element 到 agent_semantic_hints (column-scope hint)",
    "to_synonym": "派生标准 data_element/term 名称别名到 agent_semantic_sources.derived_synonyms",
    "to_value_semantics": "派生标准值域 (enumeration/range/pattern) 到 agent_semantic_hints",
    "to_qc_rule": "派生标准 data_element 到 agent_quality_rules (mandatory→completeness, value_domain→field_check)",
    "to_defect_code": "派生标准 data_element 到 agent_defect_code_bindings (mandatory→MIS-001, enum/range→NRM-003, pattern→NRM-002)",
    "to_data_model": "(P3) 派生 CDM/LDM/PDM 三层模型",
}


def get_strategy_status() -> list[dict]:
    """Return [{name, status: 'active'|'coming_soon', description}]."""
    out = []
    for name, strategy in _REGISTRY.items():
        out.append({
            "name": name,
            "status": "active" if strategy is not None else "coming_soon",
            "description": _DESCRIPTIONS.get(name, ""),
        })
    return out


def dispatch(*, version_id: str, by_user: str = "system",
             strategies: Optional[list[str]] = None) -> dict:
    """Run all (or named) active strategies.

    Per spec §6.4 乐观发布: each strategy is wrapped in try/except so a
    single failure does NOT block other strategies.

    Returns: {strategy_name: {ok, new, staled, failed, failures (10), error?}}.
    """
    active = {n: s for n, s in _REGISTRY.items() if s is not None}
    if strategies:
        active = {n: s for n, s in active.items() if n in strategies}

    results: dict = {}
    for name, strategy in active.items():
        try:
            r = strategy.run(version_id=version_id, by_user=by_user)
            results[name] = {
                "ok": True,
                "new": len(r.new_links),
                "staled": len(r.staled_links),
                "failed": len(r.failed),
                "failures": r.failed[:10],
            }
        except Exception as e:
            results[name] = {"ok": False, "error": str(e)}
    return results
