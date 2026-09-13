#!/usr/bin/env python3
"""Build a bounded official-geocoder request for unresolved Chicago permits."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.build_gwm_chicago_permit_tract_month_panel import (
    DEFAULT_MISSING_COORDINATE_SUPPLEMENT,
    DEFAULT_TRACT_SHAPEFILE,
    RAW_DIR,
    _assign_rows_to_tracts,
    _canonical_digest,
    _load_cook_tracts,
    _load_missing_coordinate_supplement,
    _load_raw_parts,
    _source_tract_geoid,
)


EVIDENCE_DIR = (
    ROOT
    / "benchmarks/gwm_bench_candidates/chicago_zoning_longitudinal_panel/evidence"
)
DEFAULT_REQUEST_OUTPUT = (
    EVIDENCE_DIR
    / "chicago_building_permits_unresolved_address_geocoder_request.json"
)
DEFAULT_DIAGNOSTIC_OUTPUT = (
    EVIDENCE_DIR
    / "chicago_building_permits_spatial_missingness_diagnostic.json"
)


def build_unresolved_permit_geocoder_request() -> tuple[dict[str, Any], dict[str, Any]]:
    """Return a deduplicated request and a hash-bound missingness diagnostic."""

    raw_rows, _, _ = _load_raw_parts(RAW_DIR)
    supplement, supplement_validation = _load_missing_coordinate_supplement(
        DEFAULT_MISSING_COORDINATE_SUPPLEMENT,
        raw_rows=raw_rows,
    )
    tract_geoids, tract_geometries, _ = _load_cook_tracts(
        DEFAULT_TRACT_SHAPEFILE
    )
    assignment = _assign_rows_to_tracts(
        rows=raw_rows,
        tract_geoids=tract_geoids,
        tract_geometries=tract_geometries,
        city_tracts=set(tract_geoids),
        missing_coordinate_rows=supplement,
    )
    unresolved_ids = {
        str(row["id"]) for row in assignment["unresolved_rows"]
    }
    if len(unresolved_ids) != 116:
        raise ValueError(f"unexpected_unresolved_row_count:{len(unresolved_ids)}")

    raw_by_id = {str(row["id"]): row for row in raw_rows}
    address_rows: dict[str, list[str]] = defaultdict(list)
    for row_id in sorted(unresolved_ids):
        supplemental_row = supplement[row_id]
        address = _address(supplemental_row)
        if not address:
            raise ValueError(f"unresolved_permit_address_missing:{row_id}")
        address_rows[address].append(row_id)
    if len(address_rows) != 47:
        raise ValueError(f"unexpected_unique_address_count:{len(address_rows)}")

    records = []
    address_manifest = []
    for object_id, address in enumerate(sorted(address_rows), start=1):
        row_ids = sorted(address_rows[address])
        records.append(
            {
                "attributes": {
                    "OBJECTID": object_id,
                    "Address": address,
                }
            }
        )
        address_manifest.append(
            {
                "object_id": object_id,
                "address": address,
                "row_count": len(row_ids),
                "permit_ids": row_ids,
                "permit_numbers": [
                    str(raw_by_id[row_id]["permit_"]) for row_id in row_ids
                ],
            }
        )

    request = {"records": records}
    initial_unresolved = [
        row
        for row in raw_rows
        if (
            row.get("latitude") in (None, "")
            or row.get("longitude") in (None, "")
        )
        and _source_tract_geoid(row.get("census_tract"), set(tract_geoids))
        is None
    ]
    unresolved_raw = [raw_by_id[row_id] for row_id in sorted(unresolved_ids)]
    diagnostic = {
        "schema": "gwm.chicago_permit_spatial_missingness_diagnostic.v1",
        "observed_on": "2026-07-24",
        "source": {
            "publisher": "City of Chicago Department of Buildings",
            "dataset_id": "ydr8-5enu",
            "window_start_inclusive": "2023-01-01",
            "window_end_exclusive": "2026-07-01",
        },
        "recovery_ladder": {
            "raw_row_count": len(raw_rows),
            "initial_unresolved_without_valid_wgs84_or_2020_tract": len(
                initial_unresolved
            ),
            "missing_wgs84_supplement_row_count": supplement_validation[
                "row_count"
            ],
            "state_plane_candidate_count": assignment["summary"][
                "state_plane_candidate_count"
            ],
            "state_plane_recovered_initially_unresolved_count": (
                len(initial_unresolved) - len(unresolved_ids)
            ),
            "remaining_unresolved_row_count": len(unresolved_ids),
            "remaining_unique_public_project_address_count": len(address_rows),
            "remaining_rows_with_pin_count": sum(
                supplement[row_id].get("pin_list") not in (None, "")
                for row_id in unresolved_ids
            ),
        },
        "missingness_structure": {
            "initial_unresolved_permit_type_counts": dict(
                sorted(Counter(str(row.get("permit_type")) for row in initial_unresolved).items())
            ),
            "remaining_unresolved_permit_type_counts": dict(
                sorted(Counter(str(row.get("permit_type")) for row in unresolved_raw).items())
            ),
            "remaining_unresolved_work_type_counts": dict(
                sorted(Counter(str(row.get("work_type")) for row in unresolved_raw).items())
            ),
            "express_program_missingness_concentrated": True,
            "missingness_assumed_random": False,
        },
        "geocoder_contract": {
            "publisher": "City of Chicago",
            "service": "AddressPoints GeocodeServer",
            "endpoint": (
                "https://gisapps.chicago.gov/arcgis/rest/services/"
                "AddressPoints/GeocodeServer/geocodeAddresses"
            ),
            "input_field": "Address",
            "output_crs": "EPSG:4326",
            "request_record_count": len(records),
            "request_digest": _canonical_digest(request),
            "admission_rule": (
                "unique score-100 PointAddress result with finite point that "
                "uniquely intersects one official TIGER 2020 tract"
            ),
        },
        "address_manifest": address_manifest,
        "artifacts": {
            "missing_coordinate_supplement": _artifact(
                DEFAULT_MISSING_COORDINATE_SUPPLEMENT
            ),
            "missing_coordinate_supplement_capture": _artifact(
                Path(f"{DEFAULT_MISSING_COORDINATE_SUPPLEMENT}.capture.json")
            ),
        },
        "readiness": {
            "state_plane_recovery_ready": True,
            "bounded_address_geocoder_request_ready": True,
            "address_geocoder_response_ready": False,
            "complete_spatial_assignment_ready": False,
            "causal_estimation_ready": False,
        },
        "claim_boundary": {
            "address_string_not_spatial_assignment": True,
            "legacy_tract_code_not_2020_geometry": True,
            "missingness_not_assumed_random": True,
            "geocoder_request_not_geocoder_result": True,
            "spatial_recovery_not_causal_identification": True,
            "gwm_k0_validated": False,
        },
    }
    diagnostic["diagnostic_digest"] = _canonical_digest(diagnostic)
    return request, diagnostic


def _address(row: dict[str, Any]) -> str:
    values = (
        row.get("street_number"),
        row.get("street_direction"),
        row.get("street_name"),
    )
    return " ".join(str(value).strip() for value in values if value not in (None, ""))


def _artifact(path: Path) -> dict[str, Any]:
    payload = path.read_bytes()
    return {
        "path": str(path.relative_to(ROOT)),
        "bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--request-output", type=Path, default=DEFAULT_REQUEST_OUTPUT
    )
    parser.add_argument(
        "--diagnostic-output", type=Path, default=DEFAULT_DIAGNOSTIC_OUTPUT
    )
    args = parser.parse_args()
    request, diagnostic = build_unresolved_permit_geocoder_request()
    args.request_output.parent.mkdir(parents=True, exist_ok=True)
    args.request_output.write_text(
        json.dumps(request, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    args.diagnostic_output.parent.mkdir(parents=True, exist_ok=True)
    args.diagnostic_output.write_text(
        json.dumps(diagnostic, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(args.request_output)
    print(args.diagnostic_output)
    print(diagnostic["diagnostic_digest"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
