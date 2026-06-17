---
type: "MMFE Field"
title: "收录时间"
description: "SLSJ field in synthetic_eco_redline."
tags: ["field", "eco_redline", "required"]
timestamp: "2026-06-17T08:28:31.856176+00:00"
layer_role: "synthetic_eco_redline"
field_name: "SLSJ"
standard_role: "eco_redline"
standard_field: "SLSJ"
alignment_decision: "accept"
---

# Field Semantics

| Property | Value |
| --- | --- |
| Layer | [synthetic_eco_redline](/layers/synthetic_eco_redline.md) |
| Field name | `SLSJ` |
| Alias | 收录时间 |
| Standard field | `SLSJ` |
| Standard role | `eco_redline` |
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
  "pattern": "^[0-9]{8}$"
}
```

# Alignment Evidence

```json
[
  {
    "basis": "exact_role_contract",
    "detail": "SLSJ matched standard field SLSJ",
    "type": "matcher"
  },
  {
    "detail": "SLSJ exists in standard field catalog",
    "lifecycle_status": "active",
    "standard_version": "0.2-demo-release",
    "type": "standard_catalog"
  },
  {
    "alias_zh": "收录时间",
    "detail": "source alias 收录时间 matches standard alias 收录时间",
    "type": "field_alias"
  },
  {
    "detail": "eco_redline.SLSJ requirement=required",
    "requirement": "required",
    "role_alias_zh": "生态保护红线",
    "standard_role": "eco_redline",
    "type": "role_contract"
  },
  {
    "detail": "SLSJ has standard field rule",
    "rule": {
      "pattern": "^[0-9]{8}$"
    },
    "type": "field_rule"
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
