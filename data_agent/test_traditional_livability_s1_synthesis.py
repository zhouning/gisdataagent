from data_agent.uwm.traditional_livability_s1_synthesis import (
    synthesize_s1_dimensions,
)


def _dimension(status):
    return {"status": status, "observed_value": 1.0, "blockers": []}


def _matrix():
    return {
        "status": "valid",
        "matrix_id": "liv-matrix-v1",
        "outcomes": [
            {"fp_status": "meets", "fpp_status": "meets", "combined_status": "meets"},
            {"fp_status": "meets", "fpp_status": "does_not_meet", "combined_status": "partially_meets"},
            {"fp_status": "does_not_meet", "fpp_status": "meets", "combined_status": "partially_meets"},
            {"fp_status": "does_not_meet", "fpp_status": "does_not_meet", "combined_status": "does_not_meet"},
        ],
        "content_digest": "sha256:matrix",
    }


def test_valid_matrix_synthesizes_declared_pair_only():
    result = synthesize_s1_dimensions(
        fp=_dimension("meets"), fpp=_dimension("does_not_meet"), matrix=_matrix()
    )
    assert result["status"] == "partially_meets"
    assert result["matrix_id"] == "liv-matrix-v1"


def test_dual_dimensions_require_validated_matrix():
    result = synthesize_s1_dimensions(
        fp=_dimension("meets"),
        fpp=_dimension("does_not_meet"),
        matrix={"status": "unavailable", "outcomes": []},
    )
    assert result["status"] == "unresolved"
    assert "authoritative_synthesis_matrix_missing" in result["blockers"]


def test_unresolved_dimension_prevents_combined_claim():
    result = synthesize_s1_dimensions(
        fp=_dimension("unresolved"), fpp=_dimension("meets"), matrix=_matrix()
    )
    assert result["status"] == "unresolved"
    assert "dimension_unresolved:FP" in result["blockers"]
