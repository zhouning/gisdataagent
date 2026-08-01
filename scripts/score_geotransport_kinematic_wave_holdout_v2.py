#!/usr/bin/env python3
"""Score the sealed two-system v2 kinematic-wave holdout exactly once."""

from __future__ import annotations

import argparse
from contextlib import contextmanager
import json
from pathlib import Path
from typing import Any, Iterator

if __package__:
    import scripts.score_geotransport_kinematic_wave_holdout_v1 as base
    from scripts.freeze_geotransport_kinematic_wave_holdout_v2 import (
        HOUR_COUNT,
        OUTCOME_SCHEMA,
        ROLLOUT_SCHEMA,
        SCORE_SCHEMA,
        SCHEMA as PROTOCOL_SCHEMA,
        START,
    )
else:
    import score_geotransport_kinematic_wave_holdout_v1 as base
    from freeze_geotransport_kinematic_wave_holdout_v2 import (
        HOUR_COUNT,
        OUTCOME_SCHEMA,
        ROLLOUT_SCHEMA,
        SCORE_SCHEMA,
        SCHEMA as PROTOCOL_SCHEMA,
        START,
    )


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PROTOCOL = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/kinematic_wave_holdout_v2_protocol.json"
)
DEFAULT_ROLLOUT = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/kinematic_wave_holdout_v2_rollout_report.json"
)
DEFAULT_OUTCOMES = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/kinematic_wave_holdout_v2_outcomes_report.json"
)
DEFAULT_REPORT = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/kinematic_wave_holdout_v2_score.json"
)
SCHEMA = SCORE_SCHEMA


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol", type=Path, default=DEFAULT_PROTOCOL)
    parser.add_argument("--rollout", type=Path, default=DEFAULT_ROLLOUT)
    parser.add_argument("--outcomes", type=Path, default=DEFAULT_OUTCOMES)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    return parser.parse_args()


@contextmanager
def _v2_context() -> Iterator[None]:
    replacements = {
        "START": START,
        "HOUR_COUNT": HOUR_COUNT,
        "PROTOCOL_SCHEMA": PROTOCOL_SCHEMA,
        "ROLLOUT_SCHEMA": ROLLOUT_SCHEMA,
        "OUTCOME_SCHEMA": OUTCOME_SCHEMA,
        "SCHEMA": SCHEMA,
    }
    original = {name: getattr(base, name) for name in replacements}
    for name, value in replacements.items():
        setattr(base, name, value)
    try:
        yield
    finally:
        for name, value in original.items():
            setattr(base, name, value)


def compile_score(
    *,
    protocol_path: Path = DEFAULT_PROTOCOL,
    rollout_path: Path = DEFAULT_ROLLOUT,
    outcomes_path: Path = DEFAULT_OUTCOMES,
) -> dict[str, Any]:
    with _v2_context():
        report = base.compile_score(
            protocol_path=protocol_path,
            rollout_path=rollout_path,
            outcomes_path=outcomes_path,
        )
    report["v1_erratum_boundary"] = {
        "v1_gate_changed": False,
        "v2_uses_unseen_candidate_window": True,
        "v2_cfl_reporting_limit": "configured_CFL_plus_two_binary64_ULPs",
        "operator_flux_state_or_timestep_changed": False,
    }
    return report


def main() -> int:
    args = parse_args()
    if args.report.exists():
        raise ValueError("kinematic_holdout_v2_score_already_exists")
    report = compile_score(
        protocol_path=args.protocol,
        rollout_path=args.rollout,
        outcomes_path=args.outcomes,
    )
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(args.report)
    for system_id in base.SYSTEM_IDS:
        metrics = report["systems"][system_id]["metrics"]
        print(
            f"{system_id}_kinematic_rmse_m3s="
            f"{metrics['kinematic_wave']['rmse_m3s']}"
        )
        print(
            f"{system_id}_persistence_rmse_m3s="
            f"{metrics['observed_persistence']['rmse_m3s']}"
        )
    print(
        "prospective_holdout_gate_passed="
        f"{report['multi_system_gates']['prospective_holdout_gate_passed']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
