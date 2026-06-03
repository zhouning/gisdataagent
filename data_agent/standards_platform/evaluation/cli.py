"""Offline CLI for Standards Platform derivation evaluation."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from ...db_engine import get_engine
from .extractor import extract_prediction_set
from .report import render_markdown, report_to_mapping
from .schema import DerivationEvalSet
from .scorer import score_eval_sets


def run_evaluation(
    *,
    engine,
    version_id: str,
    gold_path: str | Path,
    json_report_path: str | Path | None = None,
    markdown_report_path: str | Path | None = None,
    min_precision: float = 0.85,
    min_recall: float = 0.75,
) -> int:
    """Run one derivation evaluation and optionally write reports.

    Returns process-style exit code: 0 when thresholds pass, 1 otherwise.
    """
    gold = DerivationEvalSet.from_json_file(gold_path)
    predictions = extract_prediction_set(engine, version_id=version_id)
    report = score_eval_sets(
        gold,
        predictions,
        min_precision=min_precision,
        min_recall=min_recall,
    )

    if json_report_path is not None:
        Path(json_report_path).write_text(
            json.dumps(report_to_mapping(report), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    if markdown_report_path is not None:
        Path(markdown_report_path).write_text(
            render_markdown(report),
            encoding="utf-8",
        )

    return 0 if report.passed else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Evaluate Standards Platform derivation quality.",
    )
    parser.add_argument("--version-id", required=True)
    parser.add_argument("--gold", required=True, help="Gold eval-set JSON path")
    parser.add_argument("--json-report")
    parser.add_argument("--markdown-report")
    parser.add_argument("--min-precision", type=float, default=0.85)
    parser.add_argument("--min-recall", type=float, default=0.75)
    args = parser.parse_args(argv)

    engine = get_engine()
    if engine is None:
        raise RuntimeError("DB engine unavailable")

    return run_evaluation(
        engine=engine,
        version_id=args.version_id,
        gold_path=args.gold,
        json_report_path=args.json_report,
        markdown_report_path=args.markdown_report,
        min_precision=args.min_precision,
        min_recall=args.min_recall,
    )


if __name__ == "__main__":
    raise SystemExit(main())
