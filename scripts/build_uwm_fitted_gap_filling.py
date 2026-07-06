#!/usr/bin/env python3
"""Build UWM fitted gap-filling artifacts from audited local/proxy inputs."""

from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime, timezone
from pathlib import Path

from data_agent.uwm.fitted_gap_filling import write_fitted_gap_filling_snapshot


DEFAULT_GHSL_ROWS = (
    "data/uwm_public_proxy/chongqing_central/ghsl_admin_alignment/"
    "ghsl_admin_zonal_proxy.csv"
)
DEFAULT_DISTRICT_ROWS = (
    "data/uwm_public_proxy/chongqing_central/chongqing_district_population_2021/"
    "chongqing_district_population_district_rows.csv"
)
DEFAULT_UNICOM_ROWS = (
    "data/uwm_public_proxy/chongqing_central/local_planning_zip_audit_2026_07_05/"
    "chongqing_unicom_commuting_od_rows.csv"
)
DEFAULT_OUTPUT_DIR = "data/uwm_public_proxy/chongqing_central/fitted_gap_filling_2026_07_05"


def main() -> int:
    parser = argparse.ArgumentParser(description="Build UWM fitted gap-filling artifacts.")
    parser.add_argument("--ghsl-rows", default=DEFAULT_GHSL_ROWS)
    parser.add_argument("--district-rows", default=DEFAULT_DISTRICT_ROWS)
    parser.add_argument("--unicom-rows", default=DEFAULT_UNICOM_ROWS)
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--created-at", default="")
    args = parser.parse_args()

    ghsl_path = Path(args.ghsl_rows)
    district_path = Path(args.district_rows)
    unicom_path = Path(args.unicom_rows)
    created_at = args.created_at or datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )
    manifest = write_fitted_gap_filling_snapshot(
        output_dir=Path(args.output_dir),
        ghsl_rows=_read_csv_rows(ghsl_path),
        district_rows=_read_csv_rows(district_path),
        unicom_records=_read_csv_rows(unicom_path),
        source_ref=json.dumps(
            {
                "ghsl_rows": str(ghsl_path),
                "district_rows": str(district_path),
                "unicom_rows": str(unicom_path),
            },
            ensure_ascii=False,
        ),
        created_at=created_at,
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


def _read_csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


if __name__ == "__main__":
    raise SystemExit(main())
