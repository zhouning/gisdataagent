import json

import pandas as pd
import pytest

from data_agent import abu_dhabi_nl2sql_map_presentation as presentation
from data_agent.query_result_contract import tabular_result_contract


def _semantic_layer() -> dict:
    return {
        "metric_contracts": [
            {
                "contract_id": "FACILITY_COUNT_BY_DISTRICT",
                "review_status": "reviewed_candidate",
                "tables": ["public.districts", "public.facilities"],
                "dimensions": [
                    {
                        "table": "public.districts",
                        "field": "district_name",
                        "alias": "district_name",
                    }
                ],
                "metrics": [{"aggregate": "count", "field": "*", "alias": "facility_count"}],
            }
        ],
        "table_bindings": [
            {
                "physical_table": "public.districts",
                "execution_eligible": True,
                "fields": [
                    {"physical_field": "district_name", "business_role": "dimension"},
                    {"physical_field": "municipality", "business_role": "dimension"},
                    {"physical_field": "geom", "business_role": "geometry"},
                ],
            }
        ],
        "semantic_assets": [
            {
                "physical_tables": ["public.districts"],
                "labels": {"zh": "行政区", "en": "district", "ar": "منطقة"},
            },
            {
                "physical_tables": ["public.facilities"],
                "labels": {"zh": "宜居设施", "en": "liveability facilities", "ar": "مرافق جودة الحياة"},
            },
        ],
        "row_scope_policies": [
            {
                "policy_id": "ACTIVE_DISTRICTS",
                "review_status": "reviewed",
                "applies_to_tables": ["public.districts"],
                "required_predicate": {
                    "table": "public.districts",
                    "field": "is_active",
                    "operator": "is_true",
                },
                "explicit_override_terms": {"zh": ["包括未启用区域"]},
            }
        ],
    }


def _report(metric_frame: pd.DataFrame) -> dict:
    return {
        "status": "ok",
        "query": {
            "sql": (
                "SELECT d.district_name AS district_name, d.municipality, COUNT(*) AS facility_count "
                "FROM public.districts AS d GROUP BY d.district_name, d.municipality"
            ),
            "semantic_metric_contract": {"contract_id": "FACILITY_COUNT_BY_DISTRICT"},
        },
        "result": tabular_result_contract(metric_frame),
    }


@pytest.mark.asyncio
async def test_reviewed_metric_map_handoff_builds_choropleth(monkeypatch, tmp_path):
    semantic_path = tmp_path / "semantic.json"
    semantic_path.write_text(json.dumps(_semantic_layer()), encoding="utf-8")
    metrics = pd.DataFrame(
        [
            {"district_name": "Alpha", "municipality": "North", "facility_count": 3},
            {"district_name": "Beta", "municipality": "South", "facility_count": 9},
        ]
    )
    geometries = pd.DataFrame(
        [
            {
                "district_name": "Alpha",
                "municipality": "North",
                "geometry_json": json.dumps(
                    {"type": "Polygon", "coordinates": [[[54.0, 24.0], [54.1, 24.0], [54.0, 24.0]]]}
                ),
            },
            {
                "district_name": "Beta",
                "municipality": "South",
                "geometry_json": json.dumps(
                    {"type": "Polygon", "coordinates": [[[54.1, 24.1], [54.2, 24.1], [54.1, 24.1]]]}
                ),
            },
        ]
    )
    calls = []
    monkeypatch.setattr(
        presentation,
        "get_virtual_source",
        lambda source_id, owner: {
            "id": source_id,
            "source_name": "registered-source",
            "source_type": "database",
            "query_config": {"allowed_schemas": ["public"]},
        },
    )

    async def query(source, **kwargs):
        calls.append(kwargs["extra_params"]["sql"])
        return metrics if len(calls) == 1 else geometries

    monkeypatch.setattr(presentation, "query_virtual_source", query)

    map_update, diagnostic = await presentation.build_governed_nl2sql_map_update(
        report=_report(metrics),
        question="在地图上按行政区展示宜居设施数量，并按数量分级设色。",
        semantic_layer_path=semantic_path,
        source_id=12,
        owner="operator",
        language="zh",
    )

    assert diagnostic == {
        "status": "ready",
        "contract_id": "FACILITY_COUNT_BY_DISTRICT",
        "feature_count": 2,
        "unmapped_result_rows": 0,
    }
    assert map_update is not None
    layer = map_update["layers"][0]
    assert layer["type"] == "choropleth"
    assert layer["value_column"] == "facility_count"
    assert layer["legend_title"] == "按行政区分级设色的宜居设施数量"
    assert [item["properties"]["district_name"] for item in layer["geojsonData"]["features"]] == ["Alpha", "Beta"]
    assert [item["properties"]["municipality"] for item in layer["geojsonData"]["features"]] == ["North", "South"]
    assert 'gda_map."is_active" IS TRUE' in calls[1]


@pytest.mark.asyncio
async def test_map_handoff_blocks_changed_metric_snapshot(monkeypatch, tmp_path):
    semantic_path = tmp_path / "semantic.json"
    semantic_path.write_text(json.dumps(_semantic_layer()), encoding="utf-8")
    reported = pd.DataFrame([{"district_name": "Alpha", "facility_count": 3}])
    changed = pd.DataFrame([{"district_name": "Alpha", "facility_count": 4}])
    monkeypatch.setattr(
        presentation,
        "get_virtual_source",
        lambda *_: {"source_type": "database", "query_config": {"allowed_schemas": ["public"]}},
    )

    async def query(*_args, **_kwargs):
        return changed

    monkeypatch.setattr(presentation, "query_virtual_source", query)

    map_update, diagnostic = await presentation.build_governed_nl2sql_map_update(
        report=_report(reported),
        question="Show this on a map by district.",
        semantic_layer_path=semantic_path,
        source_id=12,
        owner="operator",
        language="en",
    )

    assert map_update is None
    assert diagnostic == {"status": "metric_snapshot_changed"}


@pytest.mark.asyncio
async def test_map_handoff_does_not_run_without_a_map_request(monkeypatch, tmp_path):
    semantic_path = tmp_path / "semantic.json"
    semantic_path.write_text(json.dumps(_semantic_layer()), encoding="utf-8")

    monkeypatch.setattr(
        presentation,
        "get_virtual_source",
        lambda *_: pytest.fail("map source should not be opened"),
    )
    map_update, diagnostic = await presentation.build_governed_nl2sql_map_update(
        report=_report(pd.DataFrame([{"district_name": "Alpha", "facility_count": 3}])),
        question="Count facilities by district.",
        semantic_layer_path=semantic_path,
        source_id=12,
        owner="operator",
        language="en",
    )

    assert map_update is None
    assert diagnostic == {"status": "not_requested"}
