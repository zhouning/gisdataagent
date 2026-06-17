---
type: "MMFE AI Chunk"
title: "fusion:semantic-relations"
description: "AI retrieval chunk from an MMFE semantic product."
tags: ["ai-chunk", "retrieval", "mmfe"]
timestamp: "2026-06-17T08:28:31.856176+00:00"
chunk_id: "fusion:semantic-relations"
---

# Text

空间/多模态语义关系共 728 条，其中需规则复核关系 225 条。关系类型覆盖项目-图斑、项目-永久基本农田、项目-生态红线、项目-用途管制分区、项目-城镇开发边界、项目-遥感瓦片和年度变化-图斑。

# Metadata

```json
{
  "semantic_relation_count": 728,
  "relation_type_distribution": {
    "annual_change_of_parcel": 78,
    "project_overlaps_ecological_redline": 28,
    "project_overlaps_parcel": 354,
    "project_overlaps_permanent_basic_farmland": 39,
    "project_overlaps_planning_zone": 151,
    "project_observed_by_remote_sensing_tile": 71,
    "project_overlaps_urban_development_boundary": 7
  },
  "target_role_distribution": {
    "parcel_current": 432,
    "eco_redline": 28,
    "pbf": 39,
    "planning_zone": 151,
    "remote_sensing_evidence": 71,
    "urban_boundary": 7
  },
  "twm_usage_distribution": {
    "dynamic_state_transition": 78,
    "hard_constraint_eco_overlap": 28,
    "state_builder_project_parcel_impact": 354,
    "hard_constraint_pbf_overlap": 39,
    "planning_consistency_assessment": 151,
    "multimodal_observation_evidence": 71,
    "urban_boundary_consistency": 7
  },
  "rule_review_relation_count": 225,
  "top_rule_review_examples": [
    {
      "relation_id": "PROJECT_OVERLAPS_ECO_REDLINE-000000",
      "semantic_relation_type": "project_overlaps_ecological_redline",
      "source_object_id": "PRJ-DEMO-0002",
      "target_object_id": "ECO-DEMO-00002",
      "metric_value": 70959.658,
      "rule_id": "TWM-ECO-001"
    },
    {
      "relation_id": "PROJECT_OVERLAPS_ECO_REDLINE-000001",
      "semantic_relation_type": "project_overlaps_ecological_redline",
      "source_object_id": "PRJ-DEMO-0003",
      "target_object_id": "ECO-DEMO-00003",
      "metric_value": 86799.143,
      "rule_id": "TWM-ECO-001"
    },
    {
      "relation_id": "PROJECT_OVERLAPS_ECO_REDLINE-000002",
      "semantic_relation_type": "project_overlaps_ecological_redline",
      "source_object_id": "PRJ-DEMO-0007",
      "target_object_id": "ECO-DEMO-00007",
      "metric_value": 13348.526,
      "rule_id": "TWM-ECO-001"
    },
    {
      "relation_id": "PROJECT_OVERLAPS_ECO_REDLINE-000003",
      "semantic_relation_type": "project_overlaps_ecological_redline",
      "source_object_id": "PRJ-DEMO-0010",
      "target_object_id": "ECO-DEMO-00000",
      "metric_value": 180552.326,
      "rule_id": "TWM-ECO-001"
    },
    {
      "relation_id": "PROJECT_OVERLAPS_ECO_REDLINE-000004",
      "semantic_relation_type": "project_overlaps_ecological_redline",
      "source_object_id": "PRJ-DEMO-0011",
      "target_object_id": "ECO-DEMO-00001",
      "metric_value": 101134.823,
      "rule_id": "TWM-ECO-001"
    },
    {
      "relation_id": "PROJECT_OVERLAPS_ECO_REDLINE-000005",
      "semantic_relation_type": "project_overlaps_ecological_redline",
      "source_object_id": "PRJ-DEMO-0015",
      "target_object_id": "ECO-DEMO-00005",
      "metric_value": 26408.214,
      "rule_id": "TWM-ECO-001"
    },
    {
      "relation_id": "PROJECT_OVERLAPS_ECO_REDLINE-000006",
      "semantic_relation_type": "project_overlaps_ecological_redline",
      "source_object_id": "PRJ-DEMO-0016",
      "target_object_id": "ECO-DEMO-00003",
      "metric_value": 1356.383,
      "rule_id": "TWM-ECO-001"
    },
    {
      "relation_id": "PROJECT_OVERLAPS_ECO_REDLINE-000007",
      "semantic_relation_type": "project_overlaps_ecological_redline",
      "source_object_id": "PRJ-DEMO-0018",
      "target_object_id": "ECO-DEMO-00008",
      "metric_value": 7576.663,
      "rule_id": "TWM-ECO-001"
    }
  ]
}
```
