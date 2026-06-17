---
type: "MMFE Field"
title: "城镇开发面积"
description: "CZKFMJ field in synthetic_urban_boundary."
tags: ["field", "urban_boundary", "required"]
timestamp: "2026-06-17T08:28:31.856176+00:00"
layer_role: "synthetic_urban_boundary"
field_name: "CZKFMJ"
standard_role: "urban_boundary"
standard_field: "CZKFMJ"
alignment_decision: "accept"
---

# Field Semantics

| Property | Value |
| --- | --- |
| Layer | [synthetic_urban_boundary](/layers/synthetic_urban_boundary.md) |
| Field name | `CZKFMJ` |
| Alias | 城镇开发面积 |
| Standard field | `CZKFMJ` |
| Standard role | `urban_boundary` |
| Object type | `control_boundary` |
| Requirement | `required` |
| Semantic key | `` |
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
    "detail": "CZKFMJ matched standard field CZKFMJ",
    "type": "matcher"
  },
  {
    "detail": "CZKFMJ exists in standard field catalog",
    "lifecycle_status": "active",
    "standard_version": "0.2-demo-release",
    "type": "standard_catalog"
  },
  {
    "alias_zh": "城镇开发面积",
    "detail": "source alias 城镇开发面积 matches standard alias 城镇开发面积",
    "type": "field_alias"
  },
  {
    "detail": "urban_boundary.CZKFMJ requirement=required",
    "requirement": "required",
    "role_alias_zh": "城镇开发边界",
    "standard_role": "urban_boundary",
    "type": "role_contract"
  },
  {
    "detail": "CZKFMJ has standard field rule",
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
        "module": "统一调查监测",
        "table_alias_zh": "城镇开发边界",
        "table_code": "CZKFBJ"
      },
      {
        "module": "统一规划",
        "table_alias_zh": "城镇开发边界",
        "table_code": "CZKFBJ"
      }
    ],
    "standard_version": "2026-06-16-draft",
    "type": "standard_reference"
  }
]
```
