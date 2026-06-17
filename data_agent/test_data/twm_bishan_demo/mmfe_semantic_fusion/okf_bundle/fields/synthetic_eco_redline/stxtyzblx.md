---
type: "MMFE Field"
title: "生态系统因子斑类型"
description: "STXTYZBLX field in synthetic_eco_redline."
tags: ["field", "eco_redline", "recommended"]
timestamp: "2026-06-17T08:28:31.856176+00:00"
layer_role: "synthetic_eco_redline"
field_name: "STXTYZBLX"
standard_role: "eco_redline"
standard_field: "STXTYZBLX"
alignment_decision: "accept"
---

# Field Semantics

| Property | Value |
| --- | --- |
| Layer | [synthetic_eco_redline](/layers/synthetic_eco_redline.md) |
| Field name | `STXTYZBLX` |
| Alias | 生态系统因子斑类型 |
| Standard field | `STXTYZBLX` |
| Standard role | `eco_redline` |
| Object type | `control_boundary` |
| Requirement | `recommended` |
| Semantic key | `` |
| Lifecycle status | `active` |
| Standard version | `0.2-demo-release` |
| Match type | `standard_field_catalog` |
| Confidence | 0.97 |
| Alignment score | 0.8305 |
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
    "detail": "STXTYZBLX matched standard field STXTYZBLX",
    "type": "matcher"
  },
  {
    "detail": "STXTYZBLX exists in standard field catalog",
    "lifecycle_status": "active",
    "standard_version": "0.2-demo-release",
    "type": "standard_catalog"
  },
  {
    "alias_zh": "生态系统因子斑类型",
    "detail": "source alias 生态系统因子斑类型 matches standard alias 生态系统因子斑类型",
    "type": "field_alias"
  },
  {
    "detail": "eco_redline.STXTYZBLX requirement=recommended",
    "requirement": "recommended",
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
