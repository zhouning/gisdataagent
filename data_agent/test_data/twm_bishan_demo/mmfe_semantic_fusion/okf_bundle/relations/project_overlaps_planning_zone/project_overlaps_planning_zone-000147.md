---
type: "MMFE Semantic Relation"
title: "落入用途管制分区: PRJ-DEMO-0059 -> PLAN-DEMO-003"
description: "建设项目与用途管制分区存在空间叠置，可用于规划一致性、冲突面积和方案解释。"
tags: ["relation", "planning_zone", "planning_consistency_assessment"]
timestamp: "2026-06-17T08:28:31.856176+00:00"
relation_id: "PROJECT_OVERLAPS_PLANNING_ZONE-000147"
semantic_relation_type: "project_overlaps_planning_zone"
source_object_type: "project"
target_object_type: "planning_zone"
rule_id: "TWM-PLAN-001"
objective_id: "planning_conflict_m2"
---

# Semantic Relation

| Property | Value |
| --- | --- |
| Relation ID | `PROJECT_OVERLAPS_PLANNING_ZONE-000147` |
| Relation type | `project_overlaps_planning_zone` |
| Predicate | 落入用途管制分区 |
| Source object | `project` / `PRJ-DEMO-0059` |
| Target object | `planning_zone` / `PLAN-DEMO-003` |
| Target standard role | `planning_zone` |
| TWM usage | `planning_consistency_assessment` |
| Metric | `overlap_area_m2` = 46.886 |
| Overlap area m2 | 46.886 |
| Left overlap ratio | 0.005986 |
| Right overlap ratio | 1.1e-05 |
| Confidence | 0.99 |
| Semantic strength | `weak` |
| Requires rule review | `True` |
| Rule | `TWM-PLAN-001` |
| Objective | `planning_conflict_m2` |
| Evidence source | `relations/project_planning_rel.csv` |

# Business Meaning

建设项目与用途管制分区存在空间叠置，可用于规划一致性、冲突面积和方案解释。
