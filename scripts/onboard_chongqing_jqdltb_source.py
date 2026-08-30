#!/usr/bin/env python3
"""Evaluate and register the real Chongqing JQDLTB source bundle."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from data_agent.standards_platform.application.source_onboarding import (  # noqa: E402
    evaluate_vector_source_onboarding,
    register_source_onboarding_evidence,
)

DEFAULT_PROTOCOL = (
    REPO_ROOT
    / "benchmarks/standard_mapping_chongqing_v0_1/source_onboarding_protocol.json"
)
DEFAULT_OUTPUT = (
    REPO_ROOT
    / "benchmarks/standard_mapping_chongqing_v0_1/source_onboarding_report.json"
)
DEFAULT_DATASET_ROOT = (
    REPO_ROOT
    / ".tmp/twm_standard_1128/自然资源一张图数据库标准1128/"
    "规划院提供数据样例及Demo系统功能演示建议/01数据样例"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", type=Path, default=DEFAULT_PROTOCOL)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--dataset-root",
        type=Path,
        default=Path(
            os.environ.get(
                "GDA_CHONGQING_STANDARD_MAPPING_DATA_ROOT",
                DEFAULT_DATASET_ROOT,
            )
        ).expanduser(),
    )
    parser.add_argument(
        "--register-existing",
        type=Path,
        help="Register an existing report without reading the source dataset.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.register_existing:
        report_path = args.register_existing.resolve(strict=True)
        report = json.loads(report_path.read_text(encoding="utf-8"))
        receipt = register_source_onboarding_evidence(
            report=report,
            evidence_path=report_path,
        )
        print(json.dumps(receipt, ensure_ascii=False, indent=2))
        return 0

    protocol = json.loads(args.protocol.read_text(encoding="utf-8"))
    report = evaluate_vector_source_onboarding(
        protocol=protocol,
        dataset_root=args.dataset_root,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "source_quality_verdict": report["quality"]["source_quality_verdict"],
                "records_scanned": report["evaluation_policy"]["records_scanned"],
                "standardization_status": report["standardization"]["status"],
                "promotion_ready": report["promotion"]["ready"],
                "blockers": report["promotion"]["blockers"],
                "output": str(args.output),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
