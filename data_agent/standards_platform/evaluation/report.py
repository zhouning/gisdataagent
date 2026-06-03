"""Human-readable reports for derivation evaluation."""
from __future__ import annotations

from .schema import DerivationEvalItem
from .scorer import DerivationEvalReport, MetricSummary


def _fmt(value: float) -> str:
    return f"{value:.3f}"


def _metric_row(name: str, metric: MetricSummary) -> str:
    return (
        f"| {name} | {metric.true_positive} | {metric.false_positive} | "
        f"{metric.false_negative} | {_fmt(metric.precision)} | "
        f"{_fmt(metric.recall)} | {_fmt(metric.f1)} |"
    )


def _item_line(item: DerivationEvalItem) -> str:
    match = item.identity[-1]
    return (
        f"- `{item.strategy}` `{item.target_kind}` `{item.target_key}` "
        f"from `{item.source_key}` match `{match}`"
    )


def render_markdown(report: DerivationEvalReport, *, max_examples: int = 10) -> str:
    """Render a compact Markdown report for CI logs and human review."""
    status = "PASS" if report.passed else "FAIL"
    lines = [
        "# Standards Derivation Evaluation",
        "",
        f"Status: **{status}**",
        f"Gold dataset: `{report.gold_dataset_id}`",
        f"Prediction dataset: `{report.prediction_dataset_id}`",
        (
            "Thresholds: "
            f"precision >= {report.min_precision:.2f}, "
            f"recall >= {report.min_recall:.2f}"
        ),
        "",
        "## Metrics",
        "",
        "| Scope | TP | FP | FN | Precision | Recall | F1 |",
        "|---|---:|---:|---:|---:|---:|---:|",
        _metric_row("overall", report.overall),
    ]

    for strategy in sorted(report.by_strategy):
        lines.append(_metric_row(strategy, report.by_strategy[strategy]))

    lines.extend(["", "## False Positives"])
    if report.false_positives:
        for item in report.false_positives[:max_examples]:
            lines.append(_item_line(item))
    else:
        lines.append("- none")

    lines.extend(["", "## False Negatives"])
    if report.false_negatives:
        for item in report.false_negatives[:max_examples]:
            lines.append(_item_line(item))
    else:
        lines.append("- none")

    return "\n".join(lines) + "\n"


def report_to_mapping(report: DerivationEvalReport) -> dict:
    """Return a JSON-serializable report mapping."""
    return {
        "passed": report.passed,
        "gold_dataset_id": report.gold_dataset_id,
        "prediction_dataset_id": report.prediction_dataset_id,
        "thresholds": {
            "min_precision": report.min_precision,
            "min_recall": report.min_recall,
        },
        "overall": _summary_to_mapping(report.overall),
        "by_strategy": {
            strategy: _summary_to_mapping(summary)
            for strategy, summary in sorted(report.by_strategy.items())
        },
        "false_positives": [
            item.to_mapping() for item in report.false_positives
        ],
        "false_negatives": [
            item.to_mapping() for item in report.false_negatives
        ],
    }


def _summary_to_mapping(summary: MetricSummary) -> dict:
    return {
        "true_positive": summary.true_positive,
        "false_positive": summary.false_positive,
        "false_negative": summary.false_negative,
        "precision": summary.precision,
        "recall": summary.recall,
        "f1": summary.f1,
    }
