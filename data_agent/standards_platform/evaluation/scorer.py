"""Exact-match scoring for Standards Platform derivation eval sets."""
from __future__ import annotations

from dataclasses import dataclass, field

from .schema import DerivationEvalItem, DerivationEvalSet


@dataclass(frozen=True)
class MetricSummary:
    true_positive: int
    false_positive: int
    false_negative: int

    @property
    def precision(self) -> float:
        denom = self.true_positive + self.false_positive
        if denom == 0:
            return 1.0
        return self.true_positive / denom

    @property
    def recall(self) -> float:
        denom = self.true_positive + self.false_negative
        if denom == 0:
            return 1.0
        return self.true_positive / denom

    @property
    def f1(self) -> float:
        denom = self.precision + self.recall
        if denom == 0:
            return 0.0
        return 2 * self.precision * self.recall / denom


@dataclass(frozen=True)
class DerivationEvalReport:
    gold_dataset_id: str
    prediction_dataset_id: str
    min_precision: float
    min_recall: float
    overall: MetricSummary
    by_strategy: dict[str, MetricSummary]
    false_positives: tuple[DerivationEvalItem, ...] = field(default_factory=tuple)
    false_negatives: tuple[DerivationEvalItem, ...] = field(default_factory=tuple)

    @property
    def passed(self) -> bool:
        return (
            self.overall.precision >= self.min_precision
            and self.overall.recall >= self.min_recall
        )


def _score_identities(gold_ids: set, pred_ids: set) -> MetricSummary:
    true_positive = len(gold_ids & pred_ids)
    false_positive = len(pred_ids - gold_ids)
    false_negative = len(gold_ids - pred_ids)
    return MetricSummary(
        true_positive=true_positive,
        false_positive=false_positive,
        false_negative=false_negative,
    )


def _by_identity(items: tuple[DerivationEvalItem, ...]) -> dict[tuple, DerivationEvalItem]:
    return {item.identity: item for item in items}


def score_eval_sets(
    gold: DerivationEvalSet,
    prediction: DerivationEvalSet,
    *,
    min_precision: float = 0.85,
    min_recall: float = 0.75,
) -> DerivationEvalReport:
    """Score predictions against a gold set using exact item identity."""
    if not 0 <= min_precision <= 1:
        raise ValueError("min_precision must be between 0 and 1")
    if not 0 <= min_recall <= 1:
        raise ValueError("min_recall must be between 0 and 1")

    gold_by_id = _by_identity(gold.items)
    pred_by_id = _by_identity(prediction.items)
    gold_ids = set(gold_by_id)
    pred_ids = set(pred_by_id)

    strategies = sorted({
        *(item.strategy for item in gold.items),
        *(item.strategy for item in prediction.items),
    })
    by_strategy: dict[str, MetricSummary] = {}
    for strategy in strategies:
        strategy_gold = {
            item.identity for item in gold.items if item.strategy == strategy
        }
        strategy_pred = {
            item.identity for item in prediction.items if item.strategy == strategy
        }
        by_strategy[strategy] = _score_identities(strategy_gold, strategy_pred)

    false_positive_items = tuple(
        pred_by_id[item_id] for item_id in sorted(pred_ids - gold_ids)
    )
    false_negative_items = tuple(
        gold_by_id[item_id] for item_id in sorted(gold_ids - pred_ids)
    )

    return DerivationEvalReport(
        gold_dataset_id=gold.dataset_id,
        prediction_dataset_id=prediction.dataset_id,
        min_precision=min_precision,
        min_recall=min_recall,
        overall=_score_identities(gold_ids, pred_ids),
        by_strategy=by_strategy,
        false_positives=false_positive_items,
        false_negatives=false_negative_items,
    )
