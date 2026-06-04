from data_agent.major_project_kg_resolver import resolve_major_project_kg_hints


def test_missing_stage_query_marks_breakpoint_and_project_table():
    result = resolve_major_project_kg_hints("列出存在审批流程断点的重大项目")

    assert result["matched_entities"] == ["重大项目"]
    assert result["missing_stage_filter"] is True
    assert "MISSING_STAGE" in result["required_edges"]
    assert "mp_project_list" in result["candidate_tables"]
    assert result["graph_backend"] == "postgres_projection"


def test_spatial_overlay_query_adds_relation_confidence_and_parcel_tables():
    result = resolve_major_project_kg_hints("统计通过空间叠加补全关联的项目数量")

    assert result["spatial_overlap_threshold"] == 0.3
    assert "OCCUPIES_PARCEL" in result["required_edges"]
    assert "SPATIALLY_OVERLAPS" in result["required_edges"]
    assert "mp_relation_confidence" in result["candidate_tables"]
    assert "mp_parcel" in result["candidate_tables"]
    assert (
        "mp_relation_confidence.target_id -> mp_parcel.parcel_id"
        in result["join_paths"]
    )


def test_pre_review_without_conversion_query_sets_lifecycle_stage():
    result = resolve_major_project_kg_hints("查询已完成用地预审但未完成农转征的项目")

    assert result["lifecycle_stage"] == "pre_review_without_conversion"
    assert "HAS_PRE_REVIEW" in result["required_edges"]
    assert "HAS_CONVERSION" in result["required_edges"]
    assert "mp_pre_review" in result["candidate_tables"]
    assert "mp_conversion_expropriation" in result["candidate_tables"]
    assert "mp_project_list.project_id -> mp_pre_review.project_id" in result["join_paths"]
    assert (
        "mp_project_list.project_id -> mp_conversion_expropriation.project_id"
        in result["join_paths"]
    )


def test_supply_query_dedupes_edges_and_tables_while_preserving_join_order():
    result = resolve_major_project_kg_hints("查询重大项目供地和土地供应的供地信息")

    assert result["required_edges"].count("HAS_LAND_SUPPLY") == 1
    assert result["candidate_tables"].count("mp_land_supply") == 1
    assert result["candidate_tables"][:2] == ["mp_project_list", "mp_land_supply"]
    assert "mp_project_list.project_id -> mp_land_supply.project_id" in result["join_paths"]
