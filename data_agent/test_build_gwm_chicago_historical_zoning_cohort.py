import hashlib
import json

from scripts.build_gwm_chicago_historical_zoning_cohort import (
    DEFAULT_GEOCODER_REQUEST_OUTPUT,
    DEFAULT_INPUT,
    DEFAULT_OUTPUT,
    ROOT,
    SEED_RECORD_NUMBERS,
    build_geocoder_request,
    build_historical_zoning_cohort,
)


def test_preregistered_cohort_is_complete_reproducible_and_fail_closed():
    cohort = build_historical_zoning_cohort()

    assert cohort["screening"]["source_row_count"] == 290
    assert cohort["screening"]["selected_event_count"] == 23
    assert cohort["screening"]["excluded_row_count"] == 267
    assert sum(cohort["screening"]["exclusion_counts"].values()) == 267
    assert cohort["screening"]["all_seed_records_retained"] is True
    assert SEED_RECORD_NUMBERS <= {
        event["record_number"] for event in cohort["events"]
    }
    assert len({event["record_number"] for event in cohort["events"]}) == 23
    assert all(event["file_year"] == 2024 for event in cohort["events"])
    assert all(
        0 <= event["publication_lag_days"] <= 90
        and event["complete_post_publication_months"] >= 12
        for event in cohort["events"]
    )
    assert cohort["readiness"]["metadata_cohort_preregistered"] is True
    assert cohort["readiness"]["zoning_map_crosswalk_ready"] is False
    assert cohort["readiness"]["outcome_panel_ready"] is False
    assert cohort["readiness"]["causal_estimation_ready"] is False


def test_checked_cohort_and_source_hash_match_current_inputs():
    cohort = build_historical_zoning_cohort()
    checked = json.loads(DEFAULT_OUTPUT.read_text(encoding="utf-8"))
    source_bytes = DEFAULT_INPUT.read_bytes()

    assert checked == cohort
    assert cohort["source"]["artifact_path"] == str(DEFAULT_INPUT.relative_to(ROOT))
    assert cohort["source"]["artifact_bytes"] == len(source_bytes)
    assert cohort["source"]["artifact_sha256"] == hashlib.sha256(
        source_bytes
    ).hexdigest()
    assert len(cohort["cohort_digest"]) == 64


def test_batch_geocoder_request_is_bounded_and_event_aligned():
    cohort = build_historical_zoning_cohort()
    request = build_geocoder_request(cohort)
    checked = json.loads(
        DEFAULT_GEOCODER_REQUEST_OUTPUT.read_text(encoding="utf-8")
    )

    assert checked == request
    assert len(request["records"]) == 23
    assert [
        record["attributes"]["record_number"] for record in request["records"]
    ] == [event["record_number"] for event in cohort["events"]]
    assert [record["attributes"]["Address"] for record in request["records"]] == [
        event["address"] for event in cohort["events"]
    ]
