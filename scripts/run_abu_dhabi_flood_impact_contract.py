#!/usr/bin/env python3
"""Validate the synthetic flood-impact metric contract and write its receipt."""

from __future__ import annotations

import argparse
import json
import os
import tempfile
from pathlib import Path

from data_agent.uwm.abu_dhabi_flood import (
    ExposureImpactUnit,
    FloodImpactAssessmentPolicy,
    FloodImpactAssessmentWindow,
    InundationImpactUnit,
    build_flood_impact_receipt,
    verify_flood_impact_receipt,
)

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RECEIPT = Path(
    "docs/customer/abu_dhabi_liveability_site_validation/technical_validation/"
    "flood_impact_synthetic_contract_receipt.json"
)


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_RECEIPT)
    return parser.parse_args()


def _repository_path(path: Path) -> Path:
    return path if path.is_absolute() else REPOSITORY_ROOT / path


def _window() -> FloodImpactAssessmentWindow:
    return FloodImpactAssessmentWindow(
        run_id="abu-dhabi-flood-impact-synthetic-contract",
        window_start_seconds=0.0,
        window_end_seconds=3600.0,
        crs="EPSG:32640",
        overlay_method="synthetic_partition_fixture",
        hydraulic_result_reference_id="fixture:hydraulic-result",
        exposure_snapshot_reference_id="fixture:exposure-snapshot",
        inundation_units=(
            InundationImpactUnit(
                "unit-a", 0.35, 1200.0, 5000.0, "fixture:hydraulic-unit-a"
            ),
            InundationImpactUnit(
                "unit-b", 0.80, 1800.0, 3000.0, "fixture:hydraulic-unit-b"
            ),
            InundationImpactUnit(
                "unit-c", 0.05, 600.0, 2000.0, "fixture:hydraulic-unit-c"
            ),
        ),
        exposure_units=(
            ExposureImpactUnit(
                "unit-a", 1000.0, 2, 1500.0, 40, "fixture:exposure-unit-a"
            ),
            ExposureImpactUnit(
                "unit-b", 600.0, 1, 800.0, 20, "fixture:exposure-unit-b"
            ),
            ExposureImpactUnit(
                "unit-c", 400.0, 1, 500.0, 15, "fixture:exposure-unit-c"
            ),
        ),
    )


def main() -> None:
    args = _arguments()
    output = _repository_path(args.output)
    os.chdir(REPOSITORY_ROOT)
    receipt = build_flood_impact_receipt(
        _window(), FloodImpactAssessmentPolicy()
    )
    verify_flood_impact_receipt(receipt)
    output.parent.mkdir(parents=True, exist_ok=True)
    encoded = (
        json.dumps(
            receipt,
            indent=2,
            sort_keys=True,
            ensure_ascii=True,
            allow_nan=False,
        )
        + "\n"
    ).encode("ascii")
    with tempfile.NamedTemporaryFile(dir=output.parent, delete=False) as handle:
        handle.write(encoded)
        temporary = Path(handle.name)
    os.replace(temporary, output)
    print(
        json.dumps(
            {"output": str(output), "receipt_sha256": receipt["receipt_sha256"]}
        )
    )


if __name__ == "__main__":
    main()
