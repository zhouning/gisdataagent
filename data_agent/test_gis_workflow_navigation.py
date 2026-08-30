"""Workspace discovery contract for the user-visible GIS workflow."""

from data_agent.navigation_registry import get_effective_navigation


def test_gis_workflow_is_discoverable_in_general_analysis(monkeypatch) -> None:
    monkeypatch.setattr("data_agent.navigation_registry._policies", lambda *_: {})
    navigation = get_effective_navigation("analyst", "tenant-a")
    analysis = next(group for group in navigation["groups"] if group["key"] == "analysis")
    general = next(
        section for section in analysis["sections"] if section["key"] == "general"
    )

    item = next(entry for entry in general["items"] if entry["tab_key"] == "gis_workflow")
    assert item["label"] == "空间工作流"
    assert item["icon"] == "git-branch"
