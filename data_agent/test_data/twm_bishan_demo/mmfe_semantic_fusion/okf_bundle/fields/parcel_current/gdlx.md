---
type: "MMFE Field"
title: "耕地类型"
description: "GDLX field in parcel_current."
tags: ["field", "parcel_current", "recommended"]
timestamp: "2026-06-17T08:28:31.856176+00:00"
layer_role: "parcel_current"
field_name: "GDLX"
standard_role: "parcel_current"
standard_field: "GDLX"
alignment_decision: "accept"
---

# Field Semantics

| Property | Value |
| --- | --- |
| Layer | [parcel_current](/layers/parcel_current.md) |
| Field name | `GDLX` |
| Alias | 耕地类型 |
| Standard field | `GDLX` |
| Standard role | `parcel_current` |
| Object type | `parcel` |
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
    "detail": "GDLX matched standard field GDLX",
    "type": "matcher"
  },
  {
    "detail": "GDLX exists in standard field catalog",
    "lifecycle_status": "active",
    "standard_version": "0.2-demo-release",
    "type": "standard_catalog"
  },
  {
    "alias_zh": "耕地类型",
    "detail": "source alias 耕地类型 matches standard alias 耕地类型",
    "type": "field_alias"
  },
  {
    "detail": "parcel_current.GDLX requirement=recommended",
    "requirement": "recommended",
    "role_alias_zh": "现状地类图斑",
    "standard_role": "parcel_current",
    "type": "role_contract"
  },
  {
    "detail": "defined by NR_ONE_MAP_TWM_CORE_2026",
    "standard_id": "NR_ONE_MAP_TWM_CORE_2026",
    "standard_tables": [
      {
        "module": "统一调查监测",
        "table_alias_zh": "地类图斑",
        "table_code": "DLTB"
      }
    ],
    "standard_version": "2026-06-16-draft",
    "type": "standard_reference"
  }
]
```
