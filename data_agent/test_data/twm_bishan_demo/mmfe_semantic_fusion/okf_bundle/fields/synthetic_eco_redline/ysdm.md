---
type: "MMFE Field"
title: "要素代码"
description: "YSDM field in synthetic_eco_redline."
tags: ["field", "eco_redline", "required"]
timestamp: "2026-06-17T08:28:31.856176+00:00"
layer_role: "synthetic_eco_redline"
field_name: "YSDM"
standard_role: "eco_redline"
standard_field: "YSDM"
alignment_decision: "accept"
---

# Field Semantics

| Property | Value |
| --- | --- |
| Layer | [synthetic_eco_redline](/layers/synthetic_eco_redline.md) |
| Field name | `YSDM` |
| Alias | 要素代码 |
| Standard field | `YSDM` |
| Standard role | `eco_redline` |
| Object type | `control_boundary` |
| Requirement | `required` |
| Semantic key | `` |
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
    "detail": "YSDM matched standard field YSDM",
    "type": "matcher"
  },
  {
    "detail": "YSDM exists in standard field catalog",
    "lifecycle_status": "active",
    "standard_version": "0.2-demo-release",
    "type": "standard_catalog"
  },
  {
    "alias_zh": "要素代码",
    "detail": "source alias 要素代码 matches standard alias 要素代码",
    "type": "field_alias"
  },
  {
    "detail": "eco_redline.YSDM requirement=required",
    "requirement": "required",
    "role_alias_zh": "生态保护红线",
    "standard_role": "eco_redline",
    "type": "role_contract"
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
