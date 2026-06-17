---
type: "TWM State Input Contract"
title: "TWM state input contract"
description: "Consumption contract for TWM state building from MMFE semantic products."
tags: ["twm", "state-builder", "mmfe", "contract"]
timestamp: "2026-06-17T08:28:31.856176+00:00"
recommended_twm_input: "semantic_fusion_product"
---

# Consumption Policy

| Property | Value |
| --- | --- |
| Recommended TWM input | `semantic_fusion_product` |
| Raw data usage | `source_of_truth_geometry_and_attributes` |
| Semantic product usage | `role_binding_quality_lineage_evidence_and_ai_grounding` |
| State builder policy | `load_semantic_product_then_dereference_raw_sources` |

后续 TWM 不应只直接读取原始数据文件。原始数据仍作为几何和属性事实源，但状态构建、规则解释、证据链、AI 检索和优化输入应优先读取 MMFE 语义融合成果。

# Role Bindings

| Role | Standard Role | Object Type | Source | TWM Binding |
| --- | --- | --- | --- | --- |
| [admin_units](/layers/admin_units.md) | `admin_unit` | `admin_unit` | `admin_units.geojson` |  |
| [parcel_current](/layers/parcel_current.md) | `parcel_current` | `parcel` | `parcel_current.geojson` | object_id=BSM, land_use_code=DLBM, land_use_name=DLMC, admin_code=QSDWDM, admin_name=QSDWMC, area_m2=TBMJ, temporal_key=SJNF |
| [synthetic_annual_change](/layers/synthetic_annual_change.md) | `parcel_current` | `parcel` | `synthetic_annual_change.geojson` | object_id=BSM |
| [synthetic_eco_redline](/layers/synthetic_eco_redline.md) | `eco_redline` | `control_boundary` | `synthetic_eco_redline.geojson` | object_id=BSM, admin_code=XJXZQDM, admin_name=XJXZQMC, area_m2=MJ, name=MC, area_km2=QYMJ |
| [synthetic_pbf](/layers/synthetic_pbf.md) | `pbf` | `control_boundary` | `synthetic_pbf.geojson` | admin_code=XZQDM, admin_name=XZQMC, object_id=YJJBNTTBBH, source_parcel_id=TBBH, land_use_code=DLBM, area_m2=YJJBNTMJ |
| [synthetic_planning_zones](/layers/synthetic_planning_zones.md) | `planning_zone` | `planning_zone` | `synthetic_planning_zones.geojson` | object_id=BSM, admin_code=XZQDM, admin_name=XZQMC, zone_code=GHFQDM, zone_name=GHFQMC, area_m2=MJ |
| [synthetic_projects](/layers/synthetic_projects.md) | `project` | `project` | `synthetic_projects.geojson` | object_id=XMDM, case_id=AJBH, project_name=project_name, admin_code=SZXZQDM, admin_name=SZXZQMC, area_m2=YDMJ |
| [synthetic_remote_sensing_tiles](/layers/synthetic_remote_sensing_tiles.md) | `remote_sensing_evidence` | `remote_sensing_evidence` | `synthetic_remote_sensing_tiles.geojson` |  |
| [synthetic_urban_boundary](/layers/synthetic_urban_boundary.md) | `urban_boundary` | `control_boundary` | `synthetic_urban_boundary.geojson` | object_id=BSM, admin_code=XZQDM, admin_name=XZQMC, zone_code=GHFQDM, zone_name=GHFQMC, area_m2=MJ |
