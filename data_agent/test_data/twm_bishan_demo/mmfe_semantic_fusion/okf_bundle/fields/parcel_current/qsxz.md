---
type: "MMFE Field"
title: "权属性质"
description: "QSXZ field in parcel_current."
tags: ["field", "parcel_current", "required"]
timestamp: "2026-06-17T08:28:31.856176+00:00"
layer_role: "parcel_current"
field_name: "QSXZ"
standard_role: "parcel_current"
standard_field: "QSXZ"
alignment_decision: "accept"
---

# Field Semantics

| Property | Value |
| --- | --- |
| Layer | [parcel_current](/layers/parcel_current.md) |
| Field name | `QSXZ` |
| Alias | 权属性质 |
| Standard field | `QSXZ` |
| Standard role | `parcel_current` |
| Object type | `parcel` |
| Requirement | `required` |
| Semantic key | `` |
| Lifecycle status | `active` |
| Standard version | `0.2-demo-release` |
| Match type | `standard_field_catalog` |
| Confidence | 0.99 |
| Alignment score | 0.8935 |
| Alignment decision | `accept` |
| Requires review | `False` |
| Value domain | `ownership_nature_code` |
| Value domain status | `loaded` |

# Domain Or Rule

```json
{
  "domain": "ownership_nature_code"
}
```

# Alignment Evidence

```json
[
  {
    "basis": "exact_role_contract",
    "detail": "QSXZ matched standard field QSXZ",
    "type": "matcher"
  },
  {
    "detail": "QSXZ exists in standard field catalog",
    "lifecycle_status": "active",
    "standard_version": "0.2-demo-release",
    "type": "standard_catalog"
  },
  {
    "alias_zh": "权属性质",
    "detail": "source alias 权属性质 matches standard alias 权属性质",
    "type": "field_alias"
  },
  {
    "detail": "parcel_current.QSXZ requirement=required",
    "requirement": "required",
    "role_alias_zh": "现状地类图斑",
    "standard_role": "parcel_current",
    "type": "role_contract"
  },
  {
    "detail": "QSXZ uses value domain ownership_nature_code",
    "domain": "ownership_nature_code",
    "domain_item_count": 10,
    "domain_known": true,
    "type": "value_domain"
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
