import json

from data_agent.uwm.chongqing_district_population import (
    CHONGQING_DISTRICT_POPULATION_SCHEMA,
    build_chongqing_district_population_mmfe_state_input,
    build_chongqing_district_population_proxy,
    write_chongqing_district_population_snapshot,
)


def _records():
    return [
        {
            "行政区划代码": 500000,
            "区划名称": "重庆市",
            "数据来源": "重庆市统计年鉴2022",
            "年份": 2021,
            "户籍总人口(万人)": 3414.66,
            "常住人口": 3212.43,
            "城镇化率": 70.32,
        },
        {
            "行政区划代码": 500103,
            "区划名称": "渝中区",
            "数据来源": "重庆市统计年鉴2022",
            "年份": 2021,
            "户籍总人口(万人)": 49.10,
            "常住人口": 58.83,
            "城镇化率": 100.00,
        },
        {
            "行政区划代码": 500106,
            "区划名称": "沙坪坝区",
            "数据来源": "重庆市统计年鉴2022",
            "年份": 2021,
            "户籍总人口(万人)": 93.42,
            "常住人口": 148.34,
            "城镇化率": 97.00,
        },
    ]


def test_build_chongqing_district_population_proxy_separates_city_total_from_district_rows():
    proxy = build_chongqing_district_population_proxy(
        records=_records(),
        source_ref="local.xlsx",
        created_at="2026-07-05T18:00:00Z",
    )

    assert proxy["schema"] == CHONGQING_DISTRICT_POPULATION_SCHEMA
    assert proxy["dataset_id"] == "chongqing_district_population_stats_2021_local"
    assert proxy["record_counts"] == {"raw_rows": 3, "district_rows": 2, "city_total_rows": 1}
    assert proxy["city_total"]["resident_population_10k"] == 3212.43
    assert proxy["summary"]["district_resident_population_10k_sum"] == 207.17
    assert proxy["district_rows"][0]["district_name"] == "渝中区"
    assert proxy["district_rows"][1]["resident_population_10k"] == 148.34
    assert proxy["synthetic_flags"] == [
        {"dataset_id": "chongqing_district_population_stats_2021_local", "status": "real"}
    ]
    assert proxy["claim_boundary"]["max_claim_level"] == "fragile"
    assert "district_level_not_township_or_grid_population" in proxy["limitations"]


def test_build_chongqing_district_population_mmfe_state_input_preserves_population_role():
    proxy = build_chongqing_district_population_proxy(
        records=_records(),
        source_ref="local.xlsx",
        created_at="2026-07-05T18:00:00Z",
    )

    payload = build_chongqing_district_population_mmfe_state_input(
        proxy,
        timestamp="2026-07-05T18:05:00Z",
    )

    assert payload["schema"] == "mmfe.uwm_state_input.v1"
    assert payload["urban_spatial_unit"]["unit_type"] == "district_admin_unit"
    assert payload["state_components"]["population_vulnerability"]["source_dataset_ids"] == [
        "chongqing_district_population_stats_2021_local"
    ]
    assert payload["graph_summary"]["relation_type_distribution"]["district_has_resident_population"] == 2
    assert payload["source_proxy"]["empirical_superiority_claim"] is False


def test_write_chongqing_district_population_snapshot_persists_proxy_csv_and_manifest(tmp_path):
    manifest = write_chongqing_district_population_snapshot(
        output_dir=tmp_path,
        records=_records(),
        source_ref="local.xlsx",
        created_at="2026-07-05T18:00:00Z",
    )

    assert manifest["schema"] == "uwm.public_proxy_snapshot_manifest.v1"
    assert manifest["dataset_id"] == "chongqing_district_population_stats_2021_local_snapshot"
    assert manifest["record_counts"]["district_rows"] == 2
    assert (tmp_path / "chongqing_district_population_proxy.json").exists()
    assert (tmp_path / "chongqing_district_population_district_rows.csv").exists()
    assert json.loads((tmp_path / "snapshot_manifest.json").read_text(encoding="utf-8")) == manifest
