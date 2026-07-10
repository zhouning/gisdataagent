from data_agent.uwm.traditional_livability_s7_fulu_adapter import (
    inspect_fulu_s7_planning_sources,
)


def test_inspect_fulu_s7_planning_sources_reports_missing_required_source(tmp_path):
    manifest = inspect_fulu_s7_planning_sources(tmp_path)

    assert manifest["schema"] == "uwm.traditional_livability.s7_fulu_planning_inputs.v1"
    assert manifest["ready"] is False
    assert manifest["blockers"] == [
        "missing_required_source:fulu_heping:GHFW",
        "missing_required_source:fulu_heping:JQDLTB",
        "missing_required_source:fulu_heping:TDGHDL",
        "missing_required_source:fulu_banzhu:GHFW",
        "missing_required_source:fulu_banzhu:JQDLTB",
        "missing_required_source:fulu_banzhu:TDGHDL",
    ]
