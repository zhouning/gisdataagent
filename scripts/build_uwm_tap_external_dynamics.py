"""Build UWM TAP external spatiotemporal dynamics artifacts."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from data_agent.uwm.tap_external_dynamics import build_tap_external_dynamics_report


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TAP_ROOT = Path("/Users/zhouning/Downloads/tap_uwm")
DEFAULT_OUTPUT_DIR = REPO_ROOT / "data/uwm_public_proxy/chongqing_central/tap_pm25_external_dynamics_2026_07_06"


def main() -> None:
    parser = argparse.ArgumentParser(description="Build UWM TAP external spatiotemporal dynamics artifacts.")
    parser.add_argument("--tap-root", default=str(DEFAULT_TAP_ROOT))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--max-grid-series-per-period", type=int, default=5000)
    parser.add_argument("--neighbor-count", type=int, default=4)
    args = parser.parse_args()

    tap_root = Path(args.tap_root)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    report = build_tap_external_dynamics_report(
        tap_root=tap_root,
        model_id="uwm-tap-external-spatiotemporal-dynamics-chongqing-2018-2024",
        created_at="2026-07-06T02:00:00Z",
        train_days=3,
        max_grid_series_per_period=args.max_grid_series_per_period,
        neighbor_count=args.neighbor_count,
    )
    manifest = {
        "schema": "uwm.public_proxy_snapshot_manifest.v1",
        "dataset_id": "tap_pm25_external_spatiotemporal_dynamics_chongqing_2018_2024",
        "source_dataset_ids": report["source_dataset_ids"],
        "source_root": str(tap_root),
        "created_at": "2026-07-06T02:10:00Z",
        "files": {
            "tap_external_dynamics_report": "tap_external_dynamics_report.json",
        },
        "sampling_config": report["sampling_config"],
        "training_summary": report["training_summary"],
        "overall_results": report["overall_results"],
        "supported_claim": report["supported_claim"],
        "claim_boundary": report["claim_boundary"],
        "limitations": report["limitations"],
        "empirical_superiority_claim": False,
        "observed_policy_outcome_superiority_claim": False,
    }

    _write_json(output_dir / "tap_external_dynamics_report.json", report)
    _write_json(output_dir / "snapshot_manifest.json", manifest)
    print(
        json.dumps(
            {
                "output_dir": str(output_dir.relative_to(REPO_ROOT) if output_dir.is_relative_to(REPO_ROOT) else output_dir),
                "training_summary": report["training_summary"],
                "overall_results": report["overall_results"],
                "supported_claim": report["supported_claim"],
                "claim_boundary": report["claim_boundary"],
                "empirical_superiority_claim": False,
                "observed_policy_outcome_superiority_claim": False,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def _write_json(path: Path, payload: dict) -> None:
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


if __name__ == "__main__":
    main()
