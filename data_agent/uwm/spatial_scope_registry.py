from __future__ import annotations

import hashlib
import json


HISTORICAL_NAMES = {"开县", "梁平县", "荣昌县", "潼南县", "武隆县"}


def _coordinates(geometry):
    def walk(value):
        if isinstance(value, list) and len(value) >= 2 and all(isinstance(item, (int, float)) for item in value[:2]):
            yield float(value[0]), float(value[1]); return
        if isinstance(value, list):
            for item in value: yield from walk(item)
    yield from walk((geometry or {}).get("coordinates") or [])


def _identifier(prefix, values):
    text = "|".join(str(value or "").strip() for value in values)
    return prefix + hashlib.sha256(text.encode()).hexdigest()[:20]


def build_spatial_scope_registry(*, features, crs, source_dataset_id, source_manifest):
    units = []; seen_labels = {}; missing_name_count = invalid_coordinate_range_count = empty_geometry_count = unsupported_geometry_type_count = 0; historical = set(); all_points = []
    for index, feature in enumerate(features):
        properties = feature.get("properties") or {}; province = str(properties.get("province") or "").strip(); city = str(properties.get("city") or "").strip(); county = str(properties.get("county") or "").strip(); township = str(properties.get("township") or "").strip()
        if not all((province, city, county, township)): missing_name_count += 1
        if county in HISTORICAL_NAMES: historical.add(county)
        label = (province, city, county, township); seen_labels[label] = seen_labels.get(label, 0) + 1
        geometry = feature.get("geometry") or {}; geometry_type = geometry.get("type"); points = list(_coordinates(geometry)); all_points.extend(points)
        if not points: empty_geometry_count += 1; geometry_status = "empty_geometry"; bounds = None
        elif geometry_type not in {"Polygon", "MultiPolygon"}: unsupported_geometry_type_count += 1; geometry_status = "unsupported_geometry_type"; bounds = [min(x for x, _ in points), min(y for _, y in points), max(x for x, _ in points), max(y for _, y in points)]
        elif str(crs).upper() == "EPSG:4326" and any(not (-180 <= x <= 180 and -90 <= y <= 90) for x, y in points): invalid_coordinate_range_count += 1; geometry_status = "invalid_coordinate_range"; bounds = [min(x for x, _ in points), min(y for _, y in points), max(x for x, _ in points), max(y for _, y in points)]
        else: geometry_status = "present_not_topology_validated"; bounds = [min(x for x, _ in points), min(y for _, y in points), max(x for x, _ in points), max(y for _, y in points)]
        units.append({"unit_id": _identifier("derived-admin-", (*label, index)), "parent_id": _identifier("derived-county-", (province, city, county)), "province": province or None, "city": city or None, "county": county or None, "township": township or None, "hierarchy_level": "township_or_street", "geometry_type": geometry_type, "geometry_status": geometry_status, "crs": crs, "bounds": bounds, "source_dataset_id": source_dataset_id, "source_feature_index": index, "evidence_status": "fragile"})
    valid_points = [(x, y) for x, y in all_points if str(crs).upper() != "EPSG:4326" or (-180 <= x <= 180 and -90 <= y <= 90)]
    dataset_bounds = [min(x for x, _ in valid_points), min(y for _, y in valid_points), max(x for x, _ in valid_points), max(y for _, y in valid_points)] if valid_points else None
    diagnostics = {"missing_hierarchy_name_count": missing_name_count, "duplicate_hierarchy_label_count": sum(count - 1 for count in seen_labels.values() if count > 1), "empty_geometry_count": empty_geometry_count, "unsupported_geometry_type_count": unsupported_geometry_type_count, "invalid_coordinate_range_count": invalid_coordinate_range_count, "historical_county_names": sorted(historical), "topology_validated": False, "official_vintage_verified": False, "source_license_verified": False}
    digest = {"source_dataset_id": source_dataset_id, "units": units}; bundle_id = "spatial-scope-" + hashlib.sha256(json.dumps(digest, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()[:20]
    return {"schema": "uwm.spatial_scope_admin_registry.v1", "bundle_id": bundle_id, "summary": {"spatial_unit_count": len(units), "county_name_count": len({unit["county"] for unit in units if unit["county"]}), "fragile_unit_count": len(units), "topology_validated_unit_count": 0}, "spatial_units": units, "scope_registry": {"source_dataset_id": source_dataset_id, "crs": crs, "derived_dataset_bounds": dataset_bounds, "source_manifest_bounds": source_manifest.get("source_bounds"), "hierarchy_levels": ["municipality", "county_name", "township_or_street"], "downstream_roles": ["traditional_gis_scope", "uwm_renderer_identity", "uwm_graph_node_identity", "evidence_join_key"], "kernel_adjacency_requirement": "independently_verified_adjacency_required"}, "diagnostics": diagnostics, "data_contracts": {"authoritative_upgrade": {"required_fields": ["official_admin_code", "official_name", "legal_geometry", "effective_date", "source_authority", "source_license", "crs", "topology_validation", "historical_crosswalk"]}}, "source_manifest": source_manifest, "claim_boundary": {"max_claim_level": "fragile_spatial_scope_admin_unit_registry_and_uwm_identity_readiness", "local_geometry_not_verified_current_legal_boundary": True, "derived_identity_not_authoritative_admin_code": True, "extent_not_jurisdiction": True, "county_name_aggregation_not_official_county_geometry": True, "geometry_presence_not_topology_validity": True, "registry_compatibility_not_downstream_empirical_validity": True}, "fabricated_value_count": 0}
