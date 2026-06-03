from __future__ import annotations

from data_agent.standards_platform.evaluation.schema import DerivationEvalSet
from data_agent.standards_platform.evaluation.scorer import score_eval_sets
from data_agent.standards_platform.evaluation.report import render_markdown


def test_render_markdown_includes_thresholds_and_strategy_table():
    gold = DerivationEvalSet.from_mapping({"dataset_id": "gold-v1", "items": [
        {
            "strategy": "to_semantic_hint",
            "source_key": "a",
            "target_kind": "semantic_hint",
            "target_key": "a",
        },
    ]})
    report = score_eval_sets(gold, gold, min_precision=0.85, min_recall=0.75)

    md = render_markdown(report)

    assert "gold-v1" in md
    assert "PASS" in md
    assert "to_semantic_hint" in md
    assert "0.85" in md
    assert "0.75" in md


def test_render_markdown_lists_false_positive_and_false_negative():
    gold = DerivationEvalSet.from_mapping({"items": [{
        "strategy": "to_qc_rule",
        "source_key": "gold-source",
        "target_kind": "qc_rule",
        "target_key": "gold-target",
    }]})
    pred = DerivationEvalSet.from_mapping({"items": [{
        "strategy": "to_qc_rule",
        "source_key": "pred-source",
        "target_kind": "qc_rule",
        "target_key": "pred-target",
    }]})
    report = score_eval_sets(gold, pred)

    md = render_markdown(report)

    assert "FAIL" in md
    assert "False Positives" in md
    assert "pred-target" in md
    assert "False Negatives" in md
    assert "gold-target" in md
