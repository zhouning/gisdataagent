---
type: "MMFE Field"
title: "面积"
description: "MJ field in synthetic_planning_zones."
tags: ["field", "planning_zone", "required"]
timestamp: "2026-06-17T08:28:31.856176+00:00"
layer_role: "synthetic_planning_zones"
field_name: "MJ"
standard_role: "planning_zone"
standard_field: "MJ"
twm_semantic_key: "area_m2"
alignment_decision: "accept"
---

# Field Semantics

| Property | Value |
| --- | --- |
| Layer | [synthetic_planning_zones](/layers/synthetic_planning_zones.md) |
| Field name | `MJ` |
| Alias | 面积 |
| Standard field | `MJ` |
| Standard role | `planning_zone` |
| Object type | `planning_zone` |
| Requirement | `required` |
| Semantic key | `area_m2` |
| Lifecycle status | `active` |
| Standard version | `0.2-demo-release` |
| Match type | `standard_field_catalog` |
| Confidence | 0.99 |
| Alignment score | 0.8935 |
| Alignment decision | `accept` |
| Requires review | `False` |
| Value domain | `` |
| Value domain status | `` |

# Domain Or Rule

```json
{
  "min_exclusive": 0,
  "type": "number",
  "unit": "m2"
}
```

# Alignment Evidence

```json
[
  {
    "basis": "exact_role_contract",
    "detail": "MJ matched standard field MJ",
    "type": "matcher"
  },
  {
    "detail": "MJ exists in standard field catalog",
    "lifecycle_status": "active",
    "standard_version": "0.2-demo-release",
    "type": "standard_catalog"
  },
  {
    "alias_zh": "面积",
    "detail": "source alias 面积 matches standard alias 面积",
    "type": "field_alias"
  },
  {
    "detail": "planning_zone.MJ requirement=required",
    "requirement": "required",
    "role_alias_zh": "国土空间用途管制分区",
    "standard_role": "planning_zone",
    "type": "role_contract"
  },
  {
    "detail": "MJ binds TWM semantic key area_m2",
    "semantic_key": "area_m2",
    "type": "twm_binding"
  },
  {
    "detail": "MJ has standard field rule",
    "rule": {
      "min_exclusive": 0,
      "type": "number",
      "unit": "m2"
    },
    "type": "field_rule"
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
