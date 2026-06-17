---
type: "MMFE Field"
title: "行政区名称"
description: "XZQMC field in synthetic_urban_boundary."
tags: ["field", "urban_boundary", "required"]
timestamp: "2026-06-17T08:28:31.856176+00:00"
layer_role: "synthetic_urban_boundary"
field_name: "XZQMC"
standard_role: "urban_boundary"
standard_field: "XZQMC"
twm_semantic_key: "admin_name"
alignment_decision: "accept"
---

# Field Semantics

| Property | Value |
| --- | --- |
| Layer | [synthetic_urban_boundary](/layers/synthetic_urban_boundary.md) |
| Field name | `XZQMC` |
| Alias | 行政区名称 |
| Standard field | `XZQMC` |
| Standard role | `urban_boundary` |
| Object type | `control_boundary` |
| Requirement | `required` |
| Semantic key | `admin_name` |
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
    "detail": "XZQMC matched standard field XZQMC",
    "type": "matcher"
  },
  {
    "detail": "XZQMC exists in standard field catalog",
    "lifecycle_status": "active",
    "standard_version": "0.2-demo-release",
    "type": "standard_catalog"
  },
  {
    "alias_zh": "行政区名称",
    "detail": "source alias 行政区名称 matches standard alias 行政区名称",
    "type": "field_alias"
  },
  {
    "detail": "urban_boundary.XZQMC requirement=required",
    "requirement": "required",
    "role_alias_zh": "城镇开发边界",
    "standard_role": "urban_boundary",
    "type": "role_contract"
  },
  {
    "detail": "XZQMC binds TWM semantic key admin_name",
    "semantic_key": "admin_name",
    "type": "twm_binding"
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
