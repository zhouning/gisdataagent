---
type: "MMFE Field"
title: "规划分区代码"
description: "GHFQDM field in synthetic_planning_zones."
tags: ["field", "planning_zone", "required"]
timestamp: "2026-06-17T08:28:31.856176+00:00"
layer_role: "synthetic_planning_zones"
field_name: "GHFQDM"
standard_role: "planning_zone"
standard_field: "GHFQDM"
twm_semantic_key: "zone_code"
alignment_decision: "accept"
---

# Field Semantics

| Property | Value |
| --- | --- |
| Layer | [synthetic_planning_zones](/layers/synthetic_planning_zones.md) |
| Field name | `GHFQDM` |
| Alias | 规划分区代码 |
| Standard field | `GHFQDM` |
| Standard role | `planning_zone` |
| Object type | `planning_zone` |
| Requirement | `required` |
| Semantic key | `zone_code` |
| Lifecycle status | `active` |
| Standard version | `0.2-demo-release` |
| Match type | `standard_field_catalog` |
| Confidence | 0.99 |
| Alignment score | 0.8935 |
| Alignment decision | `accept` |
| Requires review | `False` |
| Value domain | `planning_space_partition_code` |
| Value domain status | `loaded` |

# Domain Or Rule

```json
{
  "domain": "planning_space_partition_code"
}
```

# Alignment Evidence

```json
[
  {
    "basis": "exact_role_contract",
    "detail": "GHFQDM matched standard field GHFQDM",
    "type": "matcher"
  },
  {
    "detail": "GHFQDM exists in standard field catalog",
    "lifecycle_status": "active",
    "standard_version": "0.2-demo-release",
    "type": "standard_catalog"
  },
  {
    "alias_zh": "规划分区代码",
    "detail": "source alias 规划分区代码 matches standard alias 规划分区代码",
    "type": "field_alias"
  },
  {
    "detail": "planning_zone.GHFQDM requirement=required",
    "requirement": "required",
    "role_alias_zh": "国土空间用途管制分区",
    "standard_role": "planning_zone",
    "type": "role_contract"
  },
  {
    "detail": "GHFQDM binds TWM semantic key zone_code",
    "semantic_key": "zone_code",
    "type": "twm_binding"
  },
  {
    "detail": "GHFQDM uses value domain planning_space_partition_code",
    "domain": "planning_space_partition_code",
    "domain_item_count": 5,
    "domain_known": true,
    "type": "value_domain"
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
