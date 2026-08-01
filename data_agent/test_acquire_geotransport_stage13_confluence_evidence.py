from __future__ import annotations

import pytest

from scripts import acquire_geotransport_stage13_confluence_evidence as acquire


def test_stage13_acquisition_plan_is_bounded_and_sends_no_workspace_data():
    plan = acquire.compile_plan()

    assert plan["mode"] == "plan"
    assert plan["request_boundary"] == {
        "allowed_hosts": [
            "api.crossref.org",
            "api.github.com",
            "api.openalex.org",
            "zenodo.org",
        ],
        "object_count": 4,
        "maximum_total_bytes": 300_000,
        "planned_maximum_bytes": 300_000,
        "workspace_or_private_data_sent": False,
    }
    assert all(
        str(value["url"]).startswith("https://")
        for value in plan["requests"]
    )
    assert plan["claim_boundary"][
        "literature_metadata_is_hydraulic_observation"
    ] is False
    assert plan["claim_boundary"][
        "law_defined_by_public_search_result"
    ] is False
    assert plan["claim_boundary"]["operator_admitted"] is False


def test_stage13_acquisition_values_mode_changes_claim_only():
    plan = acquire.compile_plan(values_mode=True)

    assert plan["mode"] == "values"
    assert plan["claim_boundary"]["source_values_acquired"] is True
    assert plan["claim_boundary"]["calibration_authorized"] is False


def test_stage13_acquisition_rejects_unapproved_host():
    with pytest.raises(
        ValueError, match="stage13_confluence_evidence_url_outside_allowlist"
    ):
        acquire._validate_url("https://example.com/private")
