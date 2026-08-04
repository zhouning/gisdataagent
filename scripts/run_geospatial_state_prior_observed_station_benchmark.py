"""Run the frozen-default P1 benchmark on the observed-station candidate."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from data_agent.uwm.geospatial_state_prior_benchmark import (
    build_uwm_geospatial_state_prior_benchmark,
    validate_uwm_geospatial_state_prior_benchmark,
)

ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = ROOT / "data/uwm_public_proxy/chongqing_central"
DEFAULT_DATASET = (
    DATA_ROOT
    / "geospatial_state_prior_observed_station_dataset_2018_10_18_23"
    / "uwm_geospatial_state_prior_dataset.json"
)
DEFAULT_OUTPUT = (
    DATA_ROOT
    / "geospatial_state_prior_observed_station_benchmark_2018_10_18_23"
    / "uwm_geospatial_state_prior_benchmark.json"
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--created-at", required=True)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    benchmark = build_uwm_geospatial_state_prior_benchmark(
        dataset=_read_json(args.dataset),
        benchmark_id="chongqing-observed-station-state-prior-p1-2018-10-18-23",
        created_at=args.created_at,
    )
    validation = validate_uwm_geospatial_state_prior_benchmark(benchmark)
    if not validation["valid"]:
        raise ValueError("invalid_observed_station_benchmark:" + ";".join(validation["errors"]))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(benchmark, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "output": str(args.output),
                "geospatial_state_prior_benchmark_ready": benchmark[
                    "geospatial_state_prior_benchmark_ready"
                ],
                "remaining_gates": benchmark["remaining_gates"],
                "supported_claim": benchmark["supported_claim"],
                "claim_boundary": benchmark["claim_boundary"],
                "aggregate_results": benchmark["aggregate_results"],
            },
            ensure_ascii=False,
        )
    )


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    main()
