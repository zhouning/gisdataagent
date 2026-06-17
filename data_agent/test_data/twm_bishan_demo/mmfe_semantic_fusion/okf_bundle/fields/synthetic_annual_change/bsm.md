---
type: "MMFE Field"
title: "标识码"
description: "BSM field in synthetic_annual_change."
tags: ["field", "parcel_current", "required"]
timestamp: "2026-06-17T08:28:31.856176+00:00"
layer_role: "synthetic_annual_change"
field_name: "BSM"
standard_role: "parcel_current"
standard_field: "BSM"
twm_semantic_key: "object_id"
alignment_decision: "accept"
---

# Field Semantics

| Property | Value |
| --- | --- |
| Layer | [synthetic_annual_change](/layers/synthetic_annual_change.md) |
| Field name | `BSM` |
| Alias | 标识码 |
| Standard field | `BSM` |
| Standard role | `parcel_current` |
| Object type | `parcel` |
| Requirement | `required` |
| Semantic key | `object_id` |
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
    "detail": "BSM matched standard field BSM",
    "type": "matcher"
  },
  {
    "detail": "BSM exists in standard field catalog",
    "lifecycle_status": "active",
    "standard_version": "0.2-demo-release",
    "type": "standard_catalog"
  },
  {
    "alias_zh": "标识码",
    "detail": "source alias 标识码 matches standard alias 标识码",
    "type": "field_alias"
  },
  {
    "detail": "parcel_current.BSM requirement=required",
    "requirement": "required",
    "role_alias_zh": "现状地类图斑",
    "standard_role": "parcel_current",
    "type": "role_contract"
  },
  {
    "detail": "BSM binds TWM semantic key object_id",
    "semantic_key": "object_id",
    "type": "twm_binding"
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
