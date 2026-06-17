---
type: "MMFE Field"
title: "图斑编号"
description: "TBBH field in parcel_current."
tags: ["field", "parcel_current", "required"]
timestamp: "2026-06-17T08:28:31.856176+00:00"
layer_role: "parcel_current"
field_name: "TBBH"
standard_role: "parcel_current"
standard_field: "TBBH"
alignment_decision: "accept"
---

# Field Semantics

| Property | Value |
| --- | --- |
| Layer | [parcel_current](/layers/parcel_current.md) |
| Field name | `TBBH` |
| Alias | 图斑编号 |
| Standard field | `TBBH` |
| Standard role | `parcel_current` |
| Object type | `parcel` |
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
    "detail": "TBBH matched standard field TBBH",
    "type": "matcher"
  },
  {
    "detail": "TBBH exists in standard field catalog",
    "lifecycle_status": "active",
    "standard_version": "0.2-demo-release",
    "type": "standard_catalog"
  },
  {
    "alias_zh": "图斑编号",
    "detail": "source alias 图斑编号 matches standard alias 图斑编号",
    "type": "field_alias"
  },
  {
    "detail": "parcel_current.TBBH requirement=required",
    "requirement": "required",
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
