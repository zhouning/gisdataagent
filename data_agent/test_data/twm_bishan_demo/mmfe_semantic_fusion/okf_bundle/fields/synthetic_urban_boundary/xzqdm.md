---
type: "MMFE Field"
title: "行政区代码"
description: "XZQDM field in synthetic_urban_boundary."
tags: ["field", "urban_boundary", "required"]
timestamp: "2026-06-17T08:28:31.856176+00:00"
layer_role: "synthetic_urban_boundary"
field_name: "XZQDM"
standard_role: "urban_boundary"
standard_field: "XZQDM"
twm_semantic_key: "admin_code"
alignment_decision: "accept"
---

# Field Semantics

| Property | Value |
| --- | --- |
| Layer | [synthetic_urban_boundary](/layers/synthetic_urban_boundary.md) |
| Field name | `XZQDM` |
| Alias | 行政区代码 |
| Standard field | `XZQDM` |
| Standard role | `urban_boundary` |
| Object type | `control_boundary` |
| Requirement | `required` |
| Semantic key | `admin_code` |
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
    "detail": "XZQDM matched standard field XZQDM",
    "type": "matcher"
  },
  {
    "detail": "XZQDM exists in standard field catalog",
    "lifecycle_status": "active",
    "standard_version": "0.2-demo-release",
    "type": "standard_catalog"
  },
  {
    "alias_zh": "行政区代码",
    "detail": "source alias 行政区代码 matches standard alias 行政区代码",
    "type": "field_alias"
  },
  {
    "detail": "urban_boundary.XZQDM requirement=required",
    "requirement": "required",
    "role_alias_zh": "城镇开发边界",
    "standard_role": "urban_boundary",
    "type": "role_contract"
  },
  {
    "detail": "XZQDM binds TWM semantic key admin_code",
    "semantic_key": "admin_code",
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
