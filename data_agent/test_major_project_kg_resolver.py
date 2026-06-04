from data_agent.major_project_kg_resolver import resolve_major_project_kg_hints


def test_missing_stage_query_marks_breakpoint_and_project_table():
    result = resolve_major_project_kg_hints("列出存在审批流程断点的重大项目")

    assert result["matched_entities"] == ["重大项目"]
    assert result["missing_stage_filter"] is True
    assert result["missing_stage"] is None
    assert "MISSING_STAGE" in result["required_edges"]
    assert "mp_project_list" in result["candidate_tables"]
    assert result["graph_backend"] == "postgres_projection"


def test_missing_specific_stage_does_not_add_positive_stage_hints():
    result = resolve_major_project_kg_hints("找出知识图谱中缺少用地预审阶段的重大项目。")

    assert result["missing_stage_filter"] is True
    assert result["missing_stage"] == "pre_review"
    assert "MISSING_STAGE" in result["required_edges"]
    assert "HAS_PRE_REVIEW" not in result["required_edges"]
    assert "mp_pre_review" not in result["candidate_tables"]


def test_missing_land_supply_stage_does_not_add_positive_supply_hints():
    result = resolve_major_project_kg_hints("找出缺少土地供应阶段的重大项目")

    assert result["missing_stage_filter"] is True
    assert result["missing_stage"] == "land_supply"
    assert "MISSING_STAGE" in result["required_edges"]
    assert "HAS_LAND_SUPPLY" not in result["required_edges"]
    assert "mp_land_supply" not in result["candidate_tables"]


def test_spatial_overlay_query_adds_relation_confidence_and_parcel_tables():
    result = resolve_major_project_kg_hints("统计通过空间叠加补全关联的项目数量")

    assert result["spatial_overlap_threshold"] == 0.3
    assert "OCCUPIES_PARCEL" in result["required_edges"]
    assert "SPATIALLY_OVERLAPS" in result["required_edges"]
    assert "mp_relation_confidence" in result["candidate_tables"]
    assert "mp_parcel" in result["candidate_tables"]
    assert (
        "mp_project_list.project_id -> mp_relation_confidence.project_id"
        in result["join_paths"]
    )
    assert (
        "mp_relation_confidence.target_id -> mp_parcel.parcel_id"
        in result["join_paths"]
    )


def test_pre_review_without_conversion_query_sets_lifecycle_stage():
    result = resolve_major_project_kg_hints("查询已完成用地预审但没有完成农转征的项目")

    assert result["lifecycle_stage"] == "pre_review_without_conversion"
    assert "HAS_PRE_REVIEW" in result["required_edges"]
    assert "HAS_CONVERSION" in result["required_edges"]
    assert "mp_pre_review" in result["candidate_tables"]
    assert "mp_conversion_expropriation" in result["candidate_tables"]
    assert (
        "mp_project_list.project_id -> mp_pre_review.project_id"
        in result["join_paths"]
    )
    assert (
        "mp_project_list.project_id -> mp_conversion_expropriation.project_id"
        in result["join_paths"]
    )


def test_supply_query_dedupes_edges_and_tables_while_preserving_join_order():
    result = resolve_major_project_kg_hints("查询重大项目供地和土地供应的供地信息")

    assert result["required_edges"].count("HAS_LAND_SUPPLY") == 1
    assert result["candidate_tables"].count("mp_land_supply") == 1
    assert result["candidate_tables"][:2] == ["mp_project_list", "mp_land_supply"]
    assert (
        "mp_project_list.project_id -> mp_land_supply.project_id"
        in result["join_paths"]
    )


def test_occupancy_confidence_benchmark_adds_relation_and_parcel_hints():
    result = resolve_major_project_kg_hints(
        "列出占用耕地且关系置信度大于0.9的重大项目名称和地块面积。"
    )

    assert "OCCUPIES_PARCEL" in result["required_edges"]
    assert "mp_relation_confidence" in result["candidate_tables"]
    assert "mp_parcel" in result["candidate_tables"]
    assert result["relation_confidence_filter"] is True
    assert result["min_relation_confidence"] == 0.9
    assert (
        "mp_project_list.project_id -> mp_relation_confidence.project_id"
        in result["join_paths"]
    )
    assert (
        "mp_relation_confidence.target_id -> mp_parcel.parcel_id"
        in result["join_paths"]
    )


def test_semantic_stage_tables_do_not_create_unasked_lifecycle_edges():
    semantic = {
        "sources": [
            {"table_name": "mp_project_list"},
            {"table_name": "mp_pre_review"},
            {"table_name": "mp_conversion_expropriation"},
            {"table_name": "mp_land_supply"},
        ],
    }

    result = resolve_major_project_kg_hints(
        "\u5217\u51fa\u5360\u7528\u8015\u5730\u4e14\u5173\u7cfb\u7f6e\u4fe1\u5ea6\u5927\u4e8e0.9\u7684\u91cd\u5927\u9879\u76ee\u540d\u79f0\u548c\u5730\u5757\u9762\u79ef\u3002",
        semantic=semantic,
    )

    assert "OCCUPIES_PARCEL" in result["required_edges"]
    assert "HAS_PRE_REVIEW" not in result["required_edges"]
    assert "HAS_CONVERSION" not in result["required_edges"]
    assert "HAS_LAND_SUPPLY" not in result["required_edges"]


def test_semantic_sources_and_matched_tables_feed_major_project_candidates():
    semantic = {
        "sources": {
            "mp_parcel": {"display_name": "地块"},
            "not_major_project": {"display_name": "其他"},
        },
        "matched_tables": [
            "mp_relation_confidence",
            {"table_name": "mp_land_supply"},
            123,
        ],
        "candidate_tables": [{"table_name": "mp_pre_review"}, ["bad-shape"]],
    }

    result = resolve_major_project_kg_hints("查看语义命中的重大项目", semantic=semantic)

    assert result["candidate_tables"] == [
        "mp_project_list",
        "mp_parcel",
        "mp_relation_confidence",
        "mp_land_supply",
        "mp_pre_review",
    ]
    assert (
        "mp_project_list.project_id -> mp_relation_confidence.project_id"
        in result["join_paths"]
    )
    assert (
        "mp_relation_confidence.target_id -> mp_parcel.parcel_id"
        in result["join_paths"]
    )
