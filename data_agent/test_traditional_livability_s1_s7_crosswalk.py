from copy import deepcopy

from data_agent.uwm.traditional_livability_facility_dictionary import compute_canonical_content_digest
from data_agent.uwm.traditional_livability_s1_s7_crosswalk import (
    SCHEMA,
    validate_s1_s7_crosswalk,
)


def _row(s1_id, s7_id):
    return {
        "s1_geography_id": s1_id,
        "s1_geography_name": "璧山区",
        "s7_planning_area_id": s7_id,
        "s7_planning_area_name": s7_id,
        "relationship_type": "planning_area_within_admin",
        "source_reference": "Fulu planning source",
    }


def _crosswalk(rows=None):
    payload = {
        "schema": SCHEMA,
        "crosswalk_id": "bishan-fulu-v1",
        "source_metadata": {
            "issuing_organisation": "Local planning source",
            "source_reference": "Fulu village planning packages",
            "effective_date": "2026-07-11",
            "version": "v1",
        },
        "rows": rows or [_row("500120", "fulu_heping"), _row("500120", "fulu_banzhu")],
    }
    payload["content_digest"] = compute_canonical_content_digest(
        {key: value for key, value in payload.items() if key != "content_digest"}
    )
    return payload


def test_crosswalk_requires_every_requested_s7_area():
    result = validate_s1_s7_crosswalk(
        _crosswalk([_row("500120", "fulu_heping")]),
        s1_geography_id="500120",
        requested_s7_area_ids=["fulu_heping", "fulu_banzhu"],
    )
    assert result["status"] == "invalid"
    assert "s7_area_crosswalk_missing:fulu_banzhu" in result["blockers"]


def test_valid_crosswalk_returns_requested_rows_in_request_order():
    source = _crosswalk()
    before = deepcopy(source)
    result = validate_s1_s7_crosswalk(
        source,
        s1_geography_id="500120",
        requested_s7_area_ids=["fulu_banzhu", "fulu_heping"],
    )
    assert result["status"] == "valid"
    assert [row["s7_planning_area_id"] for row in result["matched_rows"]] == ["fulu_banzhu", "fulu_heping"]
    assert source == before


def test_duplicate_or_digest_tampered_crosswalk_fails_closed():
    duplicate = _crosswalk([_row("500120", "fulu_heping"), _row("500120", "fulu_heping")])
    result = validate_s1_s7_crosswalk(
        duplicate, s1_geography_id="500120", requested_s7_area_ids=["fulu_heping"]
    )
    assert "crosswalk_pair_duplicate:500120:fulu_heping" in result["blockers"]
    tampered = _crosswalk()
    tampered["rows"][0]["s1_geography_name"] = "tampered"
    result = validate_s1_s7_crosswalk(
        tampered, s1_geography_id="500120", requested_s7_area_ids=["fulu_heping"]
    )
    assert "crosswalk_content_digest_invalid" in result["blockers"]
