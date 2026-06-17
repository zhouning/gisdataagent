---
type: "MMFE Field"
title: "数据年份"
description: "SJNF field in parcel_current."
tags: ["field", "parcel_current", "required"]
timestamp: "2026-06-17T08:28:31.856176+00:00"
layer_role: "parcel_current"
field_name: "SJNF"
standard_role: "parcel_current"
standard_field: "SJNF"
twm_semantic_key: "temporal_key"
alignment_decision: "accept"
---

# Field Semantics

| Property | Value |
| --- | --- |
| Layer | [parcel_current](/layers/parcel_current.md) |
| Field name | `SJNF` |
| Alias | 数据年份 |
| Standard field | `SJNF` |
| Standard role | `parcel_current` |
| Object type | `parcel` |
| Requirement | `required` |
| Semantic key | `temporal_key` |
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
  "pattern": "^[0-9]{4}$"
}
```

# Alignment Evidence

```json
[
  {
    "basis": "exact_role_contract",
    "detail": "SJNF matched standard field SJNF",
    "type": "matcher"
  },
  {
    "detail": "SJNF exists in standard field catalog",
    "lifecycle_status": "active",
    "standard_version": "0.2-demo-release",
    "type": "standard_catalog"
  },
  {
    "alias_zh": "数据年份",
    "detail": "source alias 数据年份 matches standard alias 数据年份",
    "type": "field_alias"
  },
  {
    "detail": "parcel_current.SJNF requirement=required",
    "requirement": "required",
    "role_alias_zh": "现状地类图斑",
    "standard_role": "parcel_current",
    "type": "role_contract"
  },
  {
    "detail": "SJNF binds TWM semantic key temporal_key",
    "semantic_key": "temporal_key",
    "type": "twm_binding"
  },
  {
    "detail": "SJNF has standard field rule",
    "rule": {
      "pattern": "^[0-9]{4}$"
    },
    "type": "field_rule"
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
