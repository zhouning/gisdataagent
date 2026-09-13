from data_agent.uwm.spatial_scope_registry import build_spatial_scope_registry


def test_registry_builds_stable_hierarchy_without_legal_boundary_claim():
    features = [{"type": "Feature", "properties": {"province": "重庆市", "city": "重庆市", "county": "长寿区", "township": "邻封镇"}, "geometry": {"type": "Polygon", "coordinates": [[[107.1, 29.7], [107.2, 29.7], [107.2, 29.8], [107.1, 29.7]]]}}]
    product = build_spatial_scope_registry(features=features, crs="EPSG:4326", source_dataset_id="local", source_manifest={"limitations": ["official vintage not verified"]})
    unit = product["spatial_units"][0]
    assert unit["unit_id"].startswith("derived-admin-")
    assert unit["hierarchy_level"] == "township_or_street"
    assert unit["parent_id"].startswith("derived-county-")
    assert product["claim_boundary"]["local_geometry_not_verified_current_legal_boundary"] is True
    assert product["fabricated_value_count"] == 0


def test_registry_records_invalid_coordinate_range_without_repairing():
    features = [{"type": "Feature", "properties": {"province": "重庆市", "city": "重庆市", "county": "测试区", "township": "测试镇"}, "geometry": {"type": "Polygon", "coordinates": [[[999, 29], [999, 30], [998, 29], [999, 29]]]}}]
    product = build_spatial_scope_registry(features=features, crs="EPSG:4326", source_dataset_id="local", source_manifest={})
    assert product["diagnostics"]["invalid_coordinate_range_count"] == 1
    assert product["spatial_units"][0]["geometry_status"] == "invalid_coordinate_range"
