"""Build the fail-closed diagnostic for the observed-station P1 no-go."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from data_agent.uwm.geospatial_kernel.state_prior_p1_failure_diagnostic import (
    build_state_prior_p1_failure_diagnostic,
    validate_state_prior_p1_failure_diagnostic,
)

ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = ROOT / "data/uwm_public_proxy/chongqing_central"
DEFAULT_DATASET = (
    DATA_ROOT
    / "geospatial_state_prior_observed_station_dataset_2018_10_18_23"
    / "uwm_geospatial_state_prior_dataset.json"
)
DEFAULT_BENCHMARK = (
    DATA_ROOT
    / "geospatial_state_prior_observed_station_benchmark_2018_10_18_23"
    / "uwm_geospatial_state_prior_benchmark.json"
)
DEFAULT_OUTPUT = (
    DATA_ROOT
    / "geospatial_state_prior_p1_failure_diagnostic_2018_10_18_23"
    / "uwm_geospatial_state_prior_p1_failure_diagnostic.json"
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--created-at", required=True)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--benchmark", type=Path, default=DEFAULT_BENCHMARK)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    diagnostic = build_state_prior_p1_failure_diagnostic(
        diagnostic_id="chongqing-observed-station-p1-failure-2018-10-18-23",
        created_at=args.created_at,
        dataset=_read_json(args.dataset),
        benchmark=_read_json(args.benchmark),
    )
    validation = validate_state_prior_p1_failure_diagnostic(diagnostic)
    if not validation["valid"]:
        raise ValueError(
            "invalid_state_prior_p1_failure_diagnostic:" + ";".join(validation["errors"])
        )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(diagnostic, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "output": str(args.output),
                "diagnostic_sha256": diagnostic["diagnostic_sha256"],
                "diagnostic_summary": diagnostic["diagnostic_summary"],
                "p2_admission_permitted": diagnostic["p2_admission_permitted"],
                "supported_claim": diagnostic["supported_claim"],
            },
            ensure_ascii=False,
        )
    )


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()
