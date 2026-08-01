from __future__ import annotations

from scripts import assess_geotransport_stage13_confluence_evidence as assess


def test_stage13_public_evidence_assessment_refuses_metadata_only_validation():
    report = assess.assess()

    assert report["all_gates_passed"] is True
    assert len(report["gates"]) == 6
    assert report["status"] == (
        "no_independent_open_machine_readable_confluence_validation_"
        "dataset_identified_in_bounded_search"
    )
    assert report["relevant_experimental_thesis"]["has_fulltext"] is False
    assert report["open_confluence_angle_publication"][
        "machine_readable_numeric_dataset"
    ] is False
    assert report["admission_requirements"]["admitted_dataset"] is None
    assert report["claim_boundary"][
        "public_confluence_validation_completed"
    ] is False
    assert report["claim_boundary"]["candidate_operator_admitted"] is False


def test_stage13_public_evidence_snapshot_is_identity_frozen():
    report = assess.assess()

    assert all(
        value["identity_matches"] for value in report["artifacts"].values()
    )
    assert report["evidence_scope"]["workspace_or_private_data_sent"] is False
    assert report["evidence_scope"]["search_is_exhaustive"] is False
