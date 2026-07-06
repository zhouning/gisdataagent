from data_agent.uwm.local_planning_zip_audit import (
    build_baidu_search_index_proxy,
    build_local_planning_zip_audit_report,
    build_unicom_commuting_proxy,
)


def test_build_unicom_commuting_proxy_keeps_real_od_but_flags_missing_grid_geometry():
    proxy = build_unicom_commuting_proxy(
        records=[
            {"居住格网": 10, "工作格网": 0, "职住格网是否重合": 0, "性别": 1, "年龄": 13, "扩样前人口": 1, "扩样后人口": 11.5},
            {"居住格网": 10, "工作格网": 10, "职住格网是否重合": 1, "性别": 2, "年龄": 8, "扩样前人口": 2, "扩样后人口": 23.0},
            {"居住格网": 20, "工作格网": 30, "职住格网是否重合": 0, "性别": 1, "年龄": 8, "扩样前人口": 3, "扩样后人口": 34.5},
        ],
        source_ref="sample.csv",
        created_at="2026-07-05T00:00:00Z",
    )

    assert proxy["dataset_id"] == "chongqing_unicom_commuting_2023_local"
    assert proxy["synthetic_flags"] == [{"dataset_id": "chongqing_unicom_commuting_2023_local", "status": "real"}]
    assert proxy["record_counts"] == {
        "rows": 3,
        "unique_home_grids": 2,
        "unique_work_grids": 3,
        "same_home_work_rows": 1,
        "work_grid_zero_rows": 1,
    }
    assert proxy["summary"]["expanded_population_sum"] == 69.0
    assert proxy["summary"]["top_home_grids"][0]["grid_id"] == "10"
    assert "grid_geometry_dictionary_missing" in proxy["limitations"]
    assert proxy["empirical_superiority_claim"] is False


def test_build_baidu_search_index_proxy_is_activity_flow_not_mobility_observation():
    proxy = build_baidu_search_index_proxy(
        records=[
            {"ODJSMC": "重庆", "DDJSMC": "成都", "PCSSCS": 10, "YDSSCS": 90, "SSZS": 100},
            {"ODJSMC": "成都", "DDJSMC": "重庆", "PCSSCS": 2, "YDSSCS": 3, "SSZS": 5},
        ],
        source_ref="sample.gdb:layer",
        created_at="2026-07-05T00:00:00Z",
    )

    assert proxy["dataset_id"] == "baidu_search_index_2023_local"
    assert proxy["record_counts"] == {"flows": 2, "origin_cities": 2, "destination_cities": 2}
    assert proxy["summary"]["total_search_index"] == 105.0
    assert proxy["summary"]["top_total_flows"][0] == {
        "origin": "重庆",
        "destination": "成都",
        "search_index": 100.0,
    }
    assert "search_interest_not_observed_trip_or_policy_outcome" in proxy["limitations"]
    assert proxy["empirical_superiority_claim"] is False


def test_build_local_planning_zip_audit_report_surfaces_newly_recognized_assets():
    report = build_local_planning_zip_audit_report(
        created_at="2026-07-05T00:00:00Z",
        source_zip="/tmp/planning.zip",
        source_root="/tmp/extracted",
        file_inventory={"csv": 1, "xlsx": 14, "xls": 5, "shp": 31, "tif": 2},
        vector_profiles=[
            {"asset_id": "gaode_poi_2024", "feature_count": 1194351, "status": "already_manifested_now_profiled"},
            {"asset_id": "chongqing_historic_districts_local", "feature_count": 20, "status": "newly_recognized"},
        ],
        tabular_profiles=[
            {"asset_id": "chongqing_unicom_commuting_2023_local", "row_count": 2120, "status": "newly_recognized"},
        ],
        raster_profiles=[
            {"asset_id": "chongqing_clcd_2020", "pixel_count": 280208478, "status": "already_manifested_now_profiled"},
        ],
    )

    assert report["schema"] == "uwm.local_planning_zip_audit.v1"
    assert report["root_cause"]["missed_population_data"] == "coarse_directory_level_audit_without_table_or_layer_profiling"
    assert report["inventory_counts"]["csv"] == 1
    assert "chongqing_unicom_commuting_2023_local" in report["newly_recognized_asset_ids"]
    assert "chongqing_historic_districts_local" in report["newly_recognized_asset_ids"]
    assert "gaode_poi_2024" in report["already_manifested_but_now_profiled_asset_ids"]
