from __future__ import annotations

import json

import pytest

from data_agent.standards_platform.evaluation.schema import (
    DerivationEvalItem,
    DerivationEvalSet,
)


def test_item_identity_includes_canonical_match():
    a = DerivationEvalItem(
        strategy="to_value_semantics",
        source_key="data_element:cq_dltb.dlbm",
        target_kind="semantic_hint",
        target_key="cq_dltb.dlbm:value_enum",
        match={"values": ["0101", "0102"], "hint_kind": "value_enum"},
    )
    b = DerivationEvalItem(
        strategy="to_value_semantics",
        source_key="data_element:cq_dltb.dlbm",
        target_kind="semantic_hint",
        target_key="cq_dltb.dlbm:value_enum",
        match={"hint_kind": "value_enum", "values": ["0101", "0102"]},
    )

    assert a.identity == b.identity
    assert json.loads(a.identity[-1]) == {
        "hint_kind": "value_enum",
        "values": ["0101", "0102"],
    }


def test_eval_set_rejects_duplicate_identity():
    item = {
        "strategy": "to_semantic_hint",
        "source_key": "data_element:cq_dltb.dlbm",
        "target_kind": "semantic_hint",
        "target_key": "cq_dltb.dlbm:other",
    }

    with pytest.raises(ValueError, match="duplicate"):
        DerivationEvalSet.from_mapping({"items": [item, item]})


def test_eval_set_requires_core_fields():
    with pytest.raises(ValueError, match="strategy"):
        DerivationEvalSet.from_mapping({
            "items": [{
                "source_key": "data_element:cq_dltb.dlbm",
                "target_kind": "semantic_hint",
                "target_key": "cq_dltb.dlbm:other",
            }]
        })
