"""Build UWM external observed holdout suite from real OpenAQ and TAP benchmarks."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from data_agent.uwm.external_observed_holdout import (
    build_uwm_external_observed_holdout_suite,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OPENAQ_TEMPORAL_BENCHMARK_PATH = (
    REPO_ROOT
    / "data/uwm_public_proxy/chongqing_central/openaq_temporal_benchmark_2018_10/uwm_openaq_observed_temporal_benchmark.json"
)
DEFAULT_TAP_GRIDDED_TEMPORAL_BENCHMARK_PATH = (
    REPO_ROOT
    / "data/uwm_public_proxy/chongqing_central/tap_pm25_observed_gridded_2026_07_06/tap_gridded_temporal_benchmark.json"
)
DEFAULT_OUTPUT_DIR = (
    REPO_ROOT
    / "data/uwm_public_proxy/chongqing_central/external_observed_holdout_suite_2026_07_06"
)
DEFAULT_OUTPUT_PATH = DEFAULT_OUTPUT_DIR / "uwm_external_observed_holdout_suite.json"
DEFAULT_MANIFEST_PATH = DEFAULT_OUTPUT_DIR / "snapshot_manifest.json"


def build_external_observed_holdout_suite(
    *,
    openaq_temporal_benchmark_path: str | Path = DEFAULT_OPENAQ_TEMPORAL_BENCHMARK_PATH,
    tap_gridded_temporal_benchmark_path: str
    | Path = DEFAULT_TAP_GRIDDED_TEMPORAL_BENCHMARK_PATH,
    output_dir: str | Path = DEFAULT_OUTPUT_DIR,
    suite_id: str = "uwm-external-observed-holdout-suite-2026-07-06",
    created_at: str = "2026-07-06T13:25:00Z",
) -> dict[str, Any]:
    """Write the external observed holdout suite and snapshot manifest."""

    openaq_path = Path(openaq_temporal_benchmark_path)
    tap_path = Path(tap_gridded_temporal_benchmark_path)
    if not openaq_path.exists():
        raise FileNotFoundError(f"OpenAQ temporal benchmark not found: {openaq_path}")
    if not tap_path.exists():
        raise FileNotFoundError(f"TAP temporal benchmark not found: {tap_path}")
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)
    suite = build_uwm_external_observed_holdout_suite(
        openaq_temporal_benchmark_path=openaq_path,
        tap_gridded_temporal_benchmark_path=tap_path,
        suite_id=suite_id,
        created_at=created_at,
    )
    suite_path = out / DEFAULT_OUTPUT_PATH.name
    manifest_path = out / DEFAULT_MANIFEST_PATH.name
    with suite_path.open("w", encoding="utf-8") as handle:
        json.dump(suite, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    manifest = {
        "schema": "uwm.external_observed_holdout_suite_snapshot_manifest.v1",
        "created_at": created_at,
        "outputs": {
            "external_observed_holdout_suite": str(suite_path.relative_to(REPO_ROOT)),
        },
        "source_artifacts": suite["source_artifacts"],
        "source_dataset_ids": suite["source_dataset_ids"],
        "external_observed_holdout_ready": suite["external_observed_holdout_ready"],
        "external_observed_state_prediction_superiority_claim": suite[
            "external_observed_state_prediction_superiority_claim"
        ],
        "observed_policy_outcome_superiority_claim": suite[
            "observed_policy_outcome_superiority_claim"
        ],
        "limitations": suite["limitations"],
    }
    with manifest_path.open("w", encoding="utf-8") as handle:
        json.dump(manifest, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    return {
        "suite_path": str(suite_path),
        "manifest_path": str(manifest_path),
        "suite": suite,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--openaq-temporal-benchmark-path",
        default=str(DEFAULT_OPENAQ_TEMPORAL_BENCHMARK_PATH),
    )
    parser.add_argument(
        "--tap-gridded-temporal-benchmark-path",
        default=str(DEFAULT_TAP_GRIDDED_TEMPORAL_BENCHMARK_PATH),
    )
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument(
        "--suite-id",
        default="uwm-external-observed-holdout-suite-2026-07-06",
    )
    parser.add_argument("--created-at", default="2026-07-06T13:25:00Z")
    args = parser.parse_args()
    result = build_external_observed_holdout_suite(
        openaq_temporal_benchmark_path=args.openaq_temporal_benchmark_path,
        tap_gridded_temporal_benchmark_path=args.tap_gridded_temporal_benchmark_path,
        output_dir=args.output_dir,
        suite_id=args.suite_id,
        created_at=args.created_at,
    )
    suite = result["suite"]
    print(
        json.dumps(
            {
                "path": str(Path(result["suite_path"]).relative_to(REPO_ROOT)),
                "manifest_path": str(Path(result["manifest_path"]).relative_to(REPO_ROOT)),
                "external_observed_holdout_ready": suite[
                    "external_observed_holdout_ready"
                ],
                "external_observed_state_prediction_superiority_claim": suite[
                    "external_observed_state_prediction_superiority_claim"
                ],
                "observed_policy_outcome_superiority_claim": suite[
                    "observed_policy_outcome_superiority_claim"
                ],
                "claim_level": suite["claim_boundary"]["max_claim_level"],
                "remaining_gates": suite["remaining_gates"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
