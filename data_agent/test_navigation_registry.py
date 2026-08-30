"""Regression tests for governed workspace navigation."""

from unittest.mock import patch

from data_agent import navigation_registry as registry


def _items(payload):
    return [
        item
        for group in payload["groups"]
        for section in group["sections"]
        for item in section["items"]
    ]


def test_default_navigation_is_complete_and_unique():
    items = registry._registry_items()
    assert len(items) == 73
    assert len({item["tab_key"] for item in items}) == len(items)
    assert "abu_dhabi_nl2sql" not in {item["tab_key"] for item in items}
    offline_ingest = next(
        item for item in items if item["tab_key"] == "offline_ingest"
    )
    assert offline_ingest["section_key"] == "ingest"
    irrigation_demo = next(
        item for item in items if item["tab_key"] == "irrigation_demo"
    )
    assert irrigation_demo["section_key"] == "world_models"
    abu_dhabi_flood = next(
        item for item in items if item["tab_key"] == "abu_dhabi_flood_world_model"
    )
    assert abu_dhabi_flood["section_key"] == "world_models"

    with patch.object(registry, "_policies", return_value={}):
        payload = registry.get_effective_navigation()

    grouped = _items(payload)
    assert len(grouped) == len(items)
    assert [group["key"] for group in payload["groups"]] == [
        "data", "semantic", "analysis", "ops", "extensions"
    ]
    assert all(item["visible"] for item in grouped)


def test_policy_resolution_updates_visibility_and_location_metadata():
    def policies(scope_type, _scope_key):
        if scope_type == "global":
            return {
                "ontology": {"visible": False},
                "charts": {
                    "visible": True,
                    "group_key": "analysis",
                    "section_key": "domain",
                    "sort_order": 4,
                },
            }
        return {}

    with patch.object(registry, "_policies", side_effect=policies):
        admin_items = registry.get_admin_navigation()["items"]

    ontology = next(item for item in admin_items if item["tab_key"] == "ontology")
    charts = next(item for item in admin_items if item["tab_key"] == "charts")
    assert ontology["visible"] is False
    assert charts["group_label"] == "分析与模型"
    assert charts["section_label"] == "领域专题"
    assert charts["group_sort_order"] == 30
    assert charts["section_sort_order"] == 20
    assert charts["sort_order"] == 4


def test_navigation_policy_requires_group_and_section_together():
    with patch.object(registry, "get_engine", return_value=object()):
        try:
            registry.save_navigation_policies(
                [{"tab_key": "ontology", "group_key": "analysis"}],
                "admin",
            )
        except ValueError as exc:
            assert "provided together" in str(exc)
        else:
            raise AssertionError("expected group/section validation error")
