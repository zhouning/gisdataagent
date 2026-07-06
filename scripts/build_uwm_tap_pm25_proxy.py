"""Build UWM TAP observed gridded PM2.5 proxy and benchmark artifacts."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from data_agent.uwm.tap_pm25_proxy import build_tap_pm25_proxy
from data_agent.uwm.tap_temporal_benchmark import build_tap_gridded_temporal_benchmark


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TAP_ROOT = Path("/Users/zhouning/Downloads/tap_uwm")
DEFAULT_OUTPUT_DIR = REPO_ROOT / "data/uwm_public_proxy/chongqing_central/tap_pm25_observed_gridded_2026_07_06"


def main() -> None:
    parser = argparse.ArgumentParser(description="Build UWM TAP PM2.5 observed gridded artifacts.")
    parser.add_argument("--tap-root", default=str(DEFAULT_TAP_ROOT))
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--max-grid-series-per-period", type=int, default=5000)
    args = parser.parse_args()

    tap_root = Path(args.tap_root)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    proxy = build_tap_pm25_proxy(
        tap_root=tap_root,
        proxy_id="uwm-tap-pm25-observed-gridded-chongqing-2018-2024",
        created_at="2026-07-06T00:00:00Z",
    )
    benchmark = build_tap_gridded_temporal_benchmark(
        tap_root=tap_root,
        benchmark_id="uwm-tap-gridded-temporal-benchmark-chongqing-2018-2024",
        created_at="2026-07-06T00:30:00Z",
        train_days=3,
        max_grid_series_per_period=args.max_grid_series_per_period,
    )
    manifest = {
        "schema": "uwm.public_proxy_snapshot_manifest.v1",
        "dataset_id": "tap_pm25_observed_gridded_chongqing_2018_2024",
        "source_dataset_ids": proxy["source_dataset_ids"],
        "source_root": str(tap_root),
        "created_at": "2026-07-06T00:35:00Z",
        "files": {
            "tap_pm25_proxy": "tap_pm25_proxy.json",
            "tap_gridded_temporal_benchmark": "tap_gridded_temporal_benchmark.json",
        },
        "record_counts": proxy["record_counts"],
        "coverage": proxy["coverage"],
        "proxy_summary": proxy["summary"],
        "benchmark_summary": benchmark["overall_results"],
        "claim_boundary": benchmark["claim_boundary"],
        "limitations": sorted(set(proxy["limitations"] + benchmark["limitations"])),
        "empirical_superiority_claim": False,
        "observed_policy_outcome_superiority_claim": False,
    }

    _write_json(output_dir / "tap_pm25_proxy.json", proxy)
    _write_json(output_dir / "tap_gridded_temporal_benchmark.json", benchmark)
    _write_json(output_dir / "snapshot_manifest.json", manifest)
    print(
        json.dumps(
            {
                "output_dir": str(output_dir.relative_to(REPO_ROOT) if output_dir.is_relative_to(REPO_ROOT) else output_dir),
                "record_counts": proxy["record_counts"],
                "benchmark_summary": benchmark["overall_results"],
                "claim_boundary": benchmark["claim_boundary"],
                "empirical_superiority_claim": False,
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
