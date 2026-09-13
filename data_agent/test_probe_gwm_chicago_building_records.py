import hashlib
import json

from scripts.probe_gwm_chicago_building_records import (
    DEFAULT_OUTPUT,
    PERMIT_COLUMNS,
    ROOT,
    _canonical_digest,
    _parse_html,
)


def _checked_probe() -> dict:
    return json.loads(DEFAULT_OUTPUT.read_text(encoding="utf-8"))


def test_checked_building_records_probe_is_hash_bound_and_reproducible():
    probe = _checked_probe()
    checked_digest = probe.pop("probe_digest")

    assert _canonical_digest(probe) == checked_digest
    assert probe["selection"]["eligible_event_count"] == 17
    assert probe["selection"]["queried_event_count"] == 17
    assert len(probe["observations"]) == 17
    for artifact in probe["artifacts"].values():
        path = ROOT / artifact["path"]
        payload = path.read_bytes()
        assert len(payload) == artifact["bytes"]
        assert hashlib.sha256(payload).hexdigest() == artifact["sha256"]


def test_official_address_histories_are_real_rows_but_not_a_tract_panel():
    probe = _checked_probe()
    summary = probe["summary"]
    readiness = probe["readiness"]

    assert summary == {
        "address_history_with_permits_count": 16,
        "address_history_with_post_publication_permits_count": 11,
        "current_permit_schema_verified_count": 16,
        "exact_input_address_count": 17,
        "permit_row_count": 70,
        "post_publication_permit_row_count": 18,
        "successful_http_result_count": 17,
        "zero_permit_address_history_count": 1,
    }
    assert readiness["official_current_address_level_schema_verified"] is True
    assert readiness["official_bounded_address_level_rows_verified"] is True
    assert readiness["official_zero_permit_address_results_verified"] is True
    assert readiness["tract_month_outcome_panel_ready"] is False
    assert readiness["untreated_control_outcomes_ready"] is False
    assert readiness["causal_estimation_ready"] is False

    permits = [
        permit
        for observation in probe["observations"]
        for permit in observation["permits"]
    ]
    assert len(permits) == 70
    assert sum(not permit["description_of_work"] for permit in permits) == 1
    assert any(permit["permit_number"] == "101063756" for permit in permits)
    assert any(permit["permit_number"] == "101058154" for permit in permits)
    zero_history = [
        observation["record_number"]
        for observation in probe["observations"]
        if observation["permit_summary"]["permit_count"] == 0
    ]
    assert zero_history == ["O2024-0010948"]


def test_raw_nonempty_pages_expose_the_same_current_permit_columns():
    probe = _checked_probe()
    nonempty_page_count = 0
    for observation in probe["observations"]:
        parser = _parse_html((ROOT / observation["raw_artifact"]["path"]).read_bytes())
        permit_table = parser.tables.get("resultstable_permits")
        if not permit_table:
            continue
        nonempty_page_count += 1
        assert tuple(permit_table["headers"]) == PERMIT_COLUMNS

    assert nonempty_page_count == 16
