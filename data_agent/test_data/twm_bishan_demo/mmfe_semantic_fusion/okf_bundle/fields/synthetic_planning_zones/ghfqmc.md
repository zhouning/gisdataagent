---
type: "MMFE Field"
title: "规划分区名称"
description: "GHFQMC field in synthetic_planning_zones."
tags: ["field", "planning_zone", "required"]
timestamp: "2026-06-17T08:28:31.856176+00:00"
layer_role: "synthetic_planning_zones"
field_name: "GHFQMC"
standard_role: "planning_zone"
standard_field: "GHFQMC"
twm_semantic_key: "zone_name"
alignment_decision: "accept"
---

# Field Semantics

| Property | Value |
| --- | --- |
| Layer | [synthetic_planning_zones](/layers/synthetic_planning_zones.md) |
| Field name | `GHFQMC` |
| Alias | 规划分区名称 |
| Standard field | `GHFQMC` |
| Standard role | `planning_zone` |
| Object type | `planning_zone` |
| Requirement | `required` |
| Semantic key | `zone_name` |
| Lifecycle status | `active` |
| Standard version | `0.2-demo-release` |
| Match type | `standard_field_catalog` |
| Confidence | 0.99 |
| Alignment score | 0.8435 |
| Alignment decision | `accept` |
| Requires review | `False` |
| Value domain | `` |
| Value domain status | `` |

# Domain Or Rule

```json
{}
```

# Alignment Evidence

```json
[
  {
    "basis": "exact_role_contract",
    "detail": "GHFQMC matched standard field GHFQMC",
    "type": "matcher"
  },
  {
    "detail": "GHFQMC exists in standard field catalog",
    "lifecycle_status": "active",
    "standard_version": "0.2-demo-release",
    "type": "standard_catalog"
  },
  {
    "alias_zh": "规划分区名称",
    "detail": "source alias 规划分区名称 matches standard alias 规划分区名称",
    "type": "field_alias"
  },
  {
    "detail": "planning_zone.GHFQMC requirement=required",
    "requirement": "required",
    "role_alias_zh": "国土空间用途管制分区",
    "standard_role": "planning_zone",
    "type": "role_contract"
  },
  {
    "detail": "GHFQMC binds TWM semantic key zone_name",
    "semantic_key": "zone_name",
    "type": "twm_binding"
  },
  {
    "detail": "defined by NR_ONE_MAP_TWM_CORE_2026",
    "standard_id": "NR_ONE_MAP_TWM_CORE_2026",
    "standard_tables": [
      {
        "module": "统一规划",
        "table_alias_zh": "城镇开发边界规划分区",
        "table_code": "CZKFBJ"
      }
    ],
    "standard_version": "2026-06-16-draft",
    "type": "standard_reference"
  }
]
```
