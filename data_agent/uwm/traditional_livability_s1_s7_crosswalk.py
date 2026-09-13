from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping

from data_agent.uwm.traditional_livability_facility_dictionary import compute_canonical_content_digest


SCHEMA = "uwm.traditional_livability.s1_s7_geography_crosswalk.v1"
_SOURCE_FIELDS = {"issuing_organisation", "source_reference", "effective_date", "version"}


def _text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value or None


def validate_s1_s7_crosswalk(
    payload: Mapping[str, Any], *, s1_geography_id: str, requested_s7_area_ids: list[str]
) -> dict[str, Any]:
    source = deepcopy(dict(payload)) if isinstance(payload, Mapping) else {}
    blockers = []
    if source.get("schema") != SCHEMA:
        blockers.append("crosswalk_schema_invalid")
    if _text(source.get("crosswalk_id")) is None:
        blockers.append("crosswalk_id_required")
    metadata = source.get("source_metadata")
    if not isinstance(metadata, Mapping) or any(_text(metadata.get(field)) is None for field in _SOURCE_FIELDS):
        blockers.append("crosswalk_source_metadata_invalid")
    supplied_digest = _text(source.get("content_digest"))
    expected_digest = compute_canonical_content_digest(
        {key: value for key, value in source.items() if key != "content_digest"}
    ) if source else None
    if supplied_digest is None or supplied_digest != expected_digest:
        blockers.append("crosswalk_content_digest_invalid")
    rows = source.get("rows")
    if not isinstance(rows, list):
        blockers.append("crosswalk_rows_invalid")
        rows = []
    index = {}
    for row in rows:
        if not isinstance(row, Mapping):
            blockers.append("crosswalk_row_invalid")
            continue
        s1_id = _text(row.get("s1_geography_id"))
        s7_id = _text(row.get("s7_planning_area_id"))
        if s1_id is None or s7_id is None:
            blockers.append("crosswalk_row_ids_required")
            continue
        if row.get("relationship_type") != "planning_area_within_admin":
            blockers.append(f"crosswalk_relationship_invalid:{s1_id}:{s7_id}")
        if _text(row.get("source_reference")) is None:
            blockers.append(f"crosswalk_source_reference_required:{s1_id}:{s7_id}")
        pair = (s1_id, s7_id)
        if pair in index:
            blockers.append(f"crosswalk_pair_duplicate:{s1_id}:{s7_id}")
        else:
            index[pair] = deepcopy(dict(row))
    requested = [str(area_id) for area_id in requested_s7_area_ids]
    matched = []
    for area_id in requested:
        row = index.get((str(s1_geography_id), area_id))
        if row is None:
            blockers.append(f"s7_area_crosswalk_missing:{area_id}")
        else:
            matched.append(row)
    return {
        "schema": SCHEMA,
        "crosswalk_id": source.get("crosswalk_id"),
        "content_digest": supplied_digest,
        "status": "valid" if not blockers else "invalid",
        "s1_geography_id": str(s1_geography_id),
        "requested_s7_area_ids": requested,
        "matched_rows": matched,
        "blockers": list(dict.fromkeys(blockers)),
    }
