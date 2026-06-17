---
type: "MMFE Field"
title: "耕地种植属性名称"
description: "GDZZSXMC field in synthetic_pbf."
tags: ["field", "pbf", "recommended"]
timestamp: "2026-06-17T08:28:31.856176+00:00"
layer_role: "synthetic_pbf"
field_name: "GDZZSXMC"
standard_role: "pbf"
standard_field: "GDZZSXMC"
alignment_decision: "accept"
---

# Field Semantics

| Property | Value |
| --- | --- |
| Layer | [synthetic_pbf](/layers/synthetic_pbf.md) |
| Field name | `GDZZSXMC` |
| Alias | 耕地种植属性名称 |
| Standard field | `GDZZSXMC` |
| Standard role | `pbf` |
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
    "detail": "GDZZSXMC matched standard field GDZZSXMC",
    "type": "matcher"
  },
  {
    "detail": "GDZZSXMC exists in standard field catalog",
    "lifecycle_status": "active",
    "standard_version": "0.2-demo-release",
    "type": "standard_catalog"
  },
  {
    "alias_zh": "耕地种植属性名称",
    "detail": "source alias 耕地种植属性名称 matches standard alias 耕地种植属性名称",
    "type": "field_alias"
  },
  {
    "detail": "pbf.GDZZSXMC requirement=recommended",
    "requirement": "recommended",
    "role_alias_zh": "永久基本农田",
    "standard_role": "pbf",
    "type": "role_contract"
  },
  {
    "detail": "defined by NR_ONE_MAP_TWM_CORE_2026",
    "standard_id": "NR_ONE_MAP_TWM_CORE_2026",
    "standard_tables": [
      {
        "module": "底线安全",
        "table_alias_zh": "永久基本农田保护图斑",
        "table_code": "YJJBNTTB"
      },
      {
        "module": "统一规划",
        "table_alias_zh": "永久基本农田",
        "table_code": "YJJBNT"
      }
    ],
    "standard_version": "2026-06-16-draft",
    "type": "standard_reference"
  }
]
```
