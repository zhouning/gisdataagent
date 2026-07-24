#!/usr/bin/env python3
"""Build the preregistered Chicago historical zoning cohort."""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE_DIR = (
    ROOT
    / "benchmarks/gwm_bench_candidates/chicago_zoning_longitudinal_panel/evidence"
)
DEFAULT_INPUT = EVIDENCE_DIR / "chicago_elms_2023_2024_zoning_cohort_raw.json"
DEFAULT_OUTPUT = EVIDENCE_DIR / "historical_cohort_preregistration.json"
DEFAULT_GEOCODER_REQUEST_OUTPUT = (
    EVIDENCE_DIR / "historical_cohort_geocoder_request_v2.json"
)
LATEST_OUTCOME_CATALOG_DATE = datetime(2026, 7, 21, tzinfo=timezone.utc)
SELECTION_START = datetime(2023, 1, 1, tzinfo=timezone.utc)
SELECTION_END = datetime(2025, 1, 1, tzinfo=timezone.utc)
MAX_PUBLICATION_LAG_DAYS = 90
MIN_COMPLETE_POST_PUBLICATION_MONTHS = 12
TITLE_PATTERN = re.compile(
    r"^Zoning Reclassification Map Nos?\..+ at (?P<address>.+) "
    r"- App No\. (?P<application_number>[0-9]+T1)$"
)
SINGLE_ADDRESS_PATTERN = re.compile(r"^[0-9]+ [NSEW] .+")
SEED_RECORD_NUMBERS = {
    "O2024-0012247",
    "O2024-0012334",
    "O2024-0012532",
}


def build_historical_zoning_cohort(
    source_path: Path = DEFAULT_INPUT,
) -> dict[str, Any]:
    """Select a reproducible cohort before outcome or model inspection."""

    source_bytes = source_path.read_bytes()
    source = json.loads(source_bytes)
    rows = source.get("data")
    rows = rows if isinstance(rows, list) else []
    exclusions: Counter[str] = Counter()
    events: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, Mapping):
            exclusions["row_not_object"] += 1
            continue
        reason, event = _screen_row(row)
        if reason:
            exclusions[reason] += 1
        elif event is not None:
            events.append(event)

    events.sort(key=lambda event: (event["final_action_date"], event["record_number"]))
    selected_ids = {event["record_number"] for event in events}
    payload = {
        "schema": "gwm.chicago_historical_zoning_cohort_preregistration.v1",
        "cohort_id": "chicago_single_address_t1_zoning_2023_2024_v1",
        "frozen_on": "2026-07-24",
        "source": {
            "publisher": "Office of the City Clerk, City of Chicago",
            "endpoint": "https://api.chicityclerkelms.chicago.gov/matter",
            "artifact_path": str(source_path.relative_to(ROOT)),
            "artifact_sha256": hashlib.sha256(source_bytes).hexdigest(),
            "artifact_bytes": len(source_bytes),
            "response_meta": source.get("meta"),
            "query": {
                "filter": (
                    "finalActionDate ge 2023-01-01T00:00:00Z and "
                    "finalActionDate lt 2025-01-01T00:00:00Z and "
                    "status eq '90-Final' and attachments/any(a: "
                    "a/attachmentType eq 'Exhibits')"
                ),
                "search": "Zoning Reclassification",
                "top": 500,
                "skip": 0,
                "sort": "finalActionDate desc",
            },
            "authority_status": "verified_official",
            "access_boundary": "none",
            "license_status": "review",
        },
        "selection_protocol": {
            "selection_window": {
                "start_inclusive": SELECTION_START.isoformat(),
                "end_exclusive": SELECTION_END.isoformat(),
            },
            "required_matter_category": "ZONING RECLASSIFICATIONS",
            "required_type": "Ordinance",
            "required_status": "90-Final",
            "required_sub_status": "Passed",
            "required_record_prefix": "O",
            "required_application_suffix": "T1",
            "single_address_only": True,
            "single_address_excludes": [
                "numeric ranges",
                "slash-separated addresses",
                "comma-separated addresses",
                "addresses joined by 'and'",
            ],
            "maximum_publication_lag_days": MAX_PUBLICATION_LAG_DAYS,
            "minimum_complete_post_publication_months": (
                MIN_COMPLETE_POST_PUBLICATION_MONTHS
            ),
            "latest_outcome_catalog_date": (
                LATEST_OUTCOME_CATALOG_DATE.date().isoformat()
            ),
            "selection_blind_to_outcome_rows": True,
            "selection_blind_to_effect_estimates": True,
        },
        "screening": {
            "source_row_count": len(rows),
            "selected_event_count": len(events),
            "excluded_row_count": sum(exclusions.values()),
            "exclusion_counts": dict(sorted(exclusions.items())),
            "seed_record_numbers": sorted(SEED_RECORD_NUMBERS),
            "all_seed_records_retained": SEED_RECORD_NUMBERS <= selected_ids,
        },
        "events": events,
        "readiness": {
            "metadata_cohort_preregistered": bool(events),
            "zoning_map_crosswalk_ready": False,
            "official_point_address_crosswalk_ready": False,
            "official_tract_crosswalk_ready": False,
            "legal_treatment_geometry_ready": False,
            "effective_onset_ready": False,
            "outcome_panel_ready": False,
            "positivity_diagnostics_ready": False,
            "causal_estimation_ready": False,
        },
        "claim_boundary": {
            "metadata_screen_not_treatment_geometry": True,
            "metadata_screen_not_longitudinal_panel": True,
            "cohort_size_not_positivity_evidence": True,
            "cohort_preregistration_not_causal_identification": True,
        },
    }
    payload["cohort_digest"] = _canonical_digest(payload)
    return payload


def build_geocoder_request(cohort: Mapping[str, Any]) -> dict[str, Any]:
    """Build one bounded ArcGIS batch-geocoder request for the frozen cohort."""

    events = cohort.get("events")
    events = events if isinstance(events, list) else []
    return {
        "records": [
            {
                "attributes": {
                    "OBJECTID": index,
                    "Address": event["address"],
                    "record_number": event["record_number"],
                }
            }
            for index, event in enumerate(events, start=1)
            if isinstance(event, Mapping)
        ]
    }


def _screen_row(row: Mapping[str, Any]) -> tuple[str | None, dict[str, Any] | None]:
    if row.get("matterCategory") != "ZONING RECLASSIFICATIONS":
        return "matter_category_not_zoning_reclassification", None
    if row.get("type") != "Ordinance":
        return "matter_type_not_ordinance", None
    if row.get("status") != "90-Final":
        return "status_not_final", None
    if row.get("subStatus") != "Passed":
        return "sub_status_not_passed", None
    record_number = str(row.get("recordNumber") or "")
    if not record_number.startswith("O"):
        return "record_number_not_final_ordinance", None
    final_action = _parse_datetime(row.get("finalActionDate"))
    publication = _parse_datetime(row.get("lastPublicationDate"))
    if final_action is None or not (SELECTION_START <= final_action < SELECTION_END):
        return "final_action_outside_window_or_missing", None
    if publication is None:
        return "publication_timestamp_missing", None
    title = str(row.get("title") or "")
    match = TITLE_PATTERN.match(title)
    if match is None:
        return "title_not_single_map_t1_application", None
    publication_lag_days = (publication - final_action).total_seconds() / 86400
    if not 0 <= publication_lag_days <= MAX_PUBLICATION_LAG_DAYS:
        return "publication_lag_outside_0_90_days", None
    address = match.group("address")
    if not _is_single_address(address):
        return "address_not_single_site", None
    complete_months = _complete_months_after(publication, LATEST_OUTCOME_CATALOG_DATE)
    if complete_months < MIN_COMPLETE_POST_PUBLICATION_MONTHS:
        return "insufficient_complete_post_publication_months", None
    return None, {
        "record_number": record_number,
        "matter_id": row.get("matterId"),
        "title": title,
        "address": address,
        "application_number": match.group("application_number"),
        "file_year": row.get("fileYear"),
        "introduction_date": row.get("introductionDate"),
        "final_action_date": row.get("finalActionDate"),
        "last_publication_date": row.get("lastPublicationDate"),
        "publication_lag_days": round(publication_lag_days, 6),
        "complete_post_publication_months": complete_months,
        "status": row.get("status"),
        "sub_status": row.get("subStatus"),
        "matter_category": row.get("matterCategory"),
        "type": row.get("type"),
    }


def _is_single_address(address: str) -> bool:
    lowered = address.lower()
    return bool(
        SINGLE_ADDRESS_PATTERN.match(address)
        and "-" not in address
        and "/" not in address
        and "," not in address
        and " and " not in lowered
    )


def _parse_datetime(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _complete_months_after(start: datetime, end: datetime) -> int:
    first_year = start.year + (1 if start.month == 12 else 0)
    first_month = 1 if start.month == 12 else start.month + 1
    last_year = end.year if end.day == 1 else end.year
    last_month = end.month - 1
    if last_month == 0:
        last_year -= 1
        last_month = 12
    return max(0, (last_year - first_year) * 12 + last_month - first_month + 1)


def _canonical_digest(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--geocoder-request-output",
        type=Path,
        default=DEFAULT_GEOCODER_REQUEST_OUTPUT,
    )
    args = parser.parse_args()
    cohort = build_historical_zoning_cohort(args.input)
    geocoder_request = build_geocoder_request(cohort)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(cohort, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    args.geocoder_request_output.parent.mkdir(parents=True, exist_ok=True)
    args.geocoder_request_output.write_text(
        json.dumps(
            geocoder_request,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    print(args.output)
    print(args.geocoder_request_output)
    return 0 if cohort["screening"]["selected_event_count"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
