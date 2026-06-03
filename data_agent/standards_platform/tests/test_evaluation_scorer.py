from __future__ import annotations

from data_agent.standards_platform.evaluation.schema import DerivationEvalSet
from data_agent.standards_platform.evaluation.scorer import score_eval_sets


def test_scores_overall_and_by_strategy():
    gold = DerivationEvalSet.from_mapping({"items": [
        {
            "strategy": "to_semantic_hint",
            "source_key": "a",
            "target_kind": "semantic_hint",
            "target_key": "a",
        },
        {
            "strategy": "to_qc_rule",
            "source_key": "b",
            "target_kind": "qc_rule",
            "target_key": "b",
        },
    ]})
    pred = DerivationEvalSet.from_mapping({"items": [
        {
            "strategy": "to_semantic_hint",
            "source_key": "a",
            "target_kind": "semantic_hint",
            "target_key": "a",
        },
        {
            "strategy": "to_qc_rule",
            "source_key": "c",
            "target_kind": "qc_rule",
            "target_key": "c",
        },
    ]})

    report = score_eval_sets(
        gold,
        pred,
        min_precision=0.85,
        min_recall=0.75,
    )

    assert report.overall.true_positive == 1
    assert report.overall.false_positive == 1
    assert report.overall.false_negative == 1
    assert report.overall.precision == 0.5
    assert report.overall.recall == 0.5
    assert report.by_strategy["to_semantic_hint"].precision == 1.0
    assert report.by_strategy["to_qc_rule"].recall == 0.0
    assert report.passed is False
    assert len(report.false_positives) == 1
    assert len(report.false_negatives) == 1


def test_empty_gold_and_prediction_passes_as_noop():
    empty = DerivationEvalSet.from_mapping({"items": []})
    report = score_eval_sets(empty, empty)

    assert report.overall.precision == 1.0
    assert report.overall.recall == 1.0
    assert report.overall.f1 == 1.0
    assert report.passed is True


def test_empty_gold_with_predictions_counts_false_positives():
    gold = DerivationEvalSet.from_mapping({"items": []})
    pred = DerivationEvalSet.from_mapping({"items": [{
        "strategy": "to_data_model",
        "source_key": "version:v1",
        "target_kind": "data_model",
        "target_key": "snapshot",
    }]})

    report = score_eval_sets(gold, pred)

    assert report.overall.true_positive == 0
    assert report.overall.false_positive == 1
    assert report.overall.false_negative == 0
    assert report.overall.precision == 0.0
    assert report.overall.recall == 1.0
    assert report.overall.f1 == 0.0
