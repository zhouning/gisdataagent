---
type: "MMFE Field"
title: "县级行政区代码"
description: "XJXZQDM field in synthetic_eco_redline."
tags: ["field", "eco_redline", "required"]
timestamp: "2026-06-17T08:28:31.856176+00:00"
layer_role: "synthetic_eco_redline"
field_name: "XJXZQDM"
standard_role: "eco_redline"
standard_field: "XJXZQDM"
twm_semantic_key: "admin_code"
alignment_decision: "accept"
---

# Field Semantics

| Property | Value |
| --- | --- |
| Layer | [synthetic_eco_redline](/layers/synthetic_eco_redline.md) |
| Field name | `XJXZQDM` |
| Alias | 县级行政区代码 |
| Standard field | `XJXZQDM` |
| Standard role | `eco_redline` |
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
    "detail": "XJXZQDM matched standard field XJXZQDM",
    "type": "matcher"
  },
  {
    "detail": "XJXZQDM exists in standard field catalog",
    "lifecycle_status": "active",
    "standard_version": "0.2-demo-release",
    "type": "standard_catalog"
  },
  {
    "alias_zh": "县级行政区代码",
    "detail": "source alias 县级行政区代码 matches standard alias 县级行政区代码",
    "type": "field_alias"
  },
  {
    "detail": "eco_redline.XJXZQDM requirement=required",
    "requirement": "required",
    "role_alias_zh": "生态保护红线",
    "standard_role": "eco_redline",
    "type": "role_contract"
  },
  {
    "detail": "XJXZQDM binds TWM semantic key admin_code",
    "semantic_key": "admin_code",
    "type": "twm_binding"
  },
  {
    "detail": "defined by NR_ONE_MAP_TWM_CORE_2026",
    "standard_id": "NR_ONE_MAP_TWM_CORE_2026",
    "standard_tables": [
      {
        "module": "统一调查监测",
        "table_alias_zh": "生态保护红线",
        "table_code": "STBHHX"
      },
      {
        "module": "统一规划",
        "table_alias_zh": "生态保护红线",
        "table_code": "STBHHX"
      }
    ],
    "standard_version": "2026-06-16-draft",
    "type": "standard_reference"
  }
]
```
