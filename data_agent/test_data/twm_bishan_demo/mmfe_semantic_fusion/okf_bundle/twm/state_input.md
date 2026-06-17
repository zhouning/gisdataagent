---
type: "TWM State Input"
title: "TWM state input"
description: "Downstream state-builder input derived from an MMFE semantic product."
tags: ["twm", "state-builder", "mmfe", "semantic-relations"]
timestamp: "2026-06-17T08:28:31.856176+00:00"
schema: "mmfe.twm_state_input.v1"
product_id: "sfp-twm-dc2a707aabda0c01"
not_for_production: true
---

# State Input Summary

| Property | Value |
| --- | --- |
| Schema | `mmfe.twm_state_input.v1` |
| Product ID | `sfp-twm-dc2a707aabda0c01` |
| State builder policy | `load_semantic_product_then_dereference_raw_sources` |
| Role count | 9 |
| Relation count | 728 |
| Relation type count | 7 |
| Objective binding count | 13 |
| Not for production | `True` |

# Production Policy

该状态输入用于验证 MMFE 到 TWM 的数据契约。几何和属性事实仍以源数据为准，语义角色、字段绑定、关系、规则、证据和优化目标以 MMFE 语义融合成果为准；进入生产时必须替换为真实权威自然资源数据。

# State Components

| Component | Relations | Objectives | Rules |
| --- | ---: | --- | --- |
| `project_parcel_impacts` | 354 | `farmland_loss_m2` |  |
| `hard_constraints` | 67 | `eco_overlap_m2`, `pbf_overlap_m2` | `TWM-ECO-001`, `TWM-FARM-001` |
| `planning_consistency` | 158 | `development_area_m2`, `planning_conflict_m2` | `TWM-PLAN-001`, `TWM-URBAN-001` |
| `remote_sensing_evidence` | 71 | `robustness_score` | `TWM-EVD-001` |
| `dynamic_transitions` | 78 | `farmland_gain_m2` |  |

# Semantic Relation Registry

| Relation Type | Count | TWM Usage | Objectives | Rules |
| --- | ---: | --- | --- | --- |
| `annual_change_of_parcel` | 78 | `dynamic_state_transition` | `farmland_gain_m2` |  |
| `project_observed_by_remote_sensing_tile` | 71 | `multimodal_observation_evidence` | `robustness_score` | `TWM-EVD-001` |
| `project_overlaps_ecological_redline` | 28 | `hard_constraint_eco_overlap` | `eco_overlap_m2` | `TWM-ECO-001` |
| `project_overlaps_parcel` | 354 | `state_builder_project_parcel_impact` | `farmland_loss_m2` |  |
| `project_overlaps_permanent_basic_farmland` | 39 | `hard_constraint_pbf_overlap` | `pbf_overlap_m2` | `TWM-FARM-001` |
| `project_overlaps_planning_zone` | 151 | `planning_consistency_assessment` | `planning_conflict_m2` | `TWM-PLAN-001` |
| `project_overlaps_urban_development_boundary` | 7 | `urban_boundary_consistency` | `development_area_m2` | `TWM-URBAN-001` |

# Optimization Bindings

| Objective | Hard Constraint | Relations | Relation Types |
| --- | --- | ---: | --- |
| `pbf_overlap_m2` | `True` | 39 | `project_overlaps_permanent_basic_farmland` |
| `eco_overlap_m2` | `True` | 28 | `project_overlaps_ecological_redline` |
| `planning_conflict_m2` | `False` | 151 | `project_overlaps_planning_zone` |
| `farmland_loss_m2` | `False` | 354 | `project_overlaps_parcel` |
| `farmland_gain_m2` | `False` | 78 | `annual_change_of_parcel` |
| `development_area_m2` | `False` | 7 | `project_overlaps_urban_development_boundary` |
| `compactness_score` | `False` | 0 |  |
| `adjustment_cost_proxy` | `False` | 0 |  |
| `admin_fairness_cv` | `False` | 0 |  |
| `robustness_score` | `False` | 71 | `project_observed_by_remote_sensing_tile` |
| `review_load_count` | `False` | 0 |  |
| `slope_improvement_pct` | `False` | 0 |  |
| `contiguity_gain` | `False` | 0 |  |

# Warnings

* TWM validation scaffold: not for production use.
* TWM state input is a validation scaffold and is not for production decisions.
