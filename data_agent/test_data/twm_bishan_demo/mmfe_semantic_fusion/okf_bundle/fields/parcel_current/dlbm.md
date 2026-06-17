---
type: "MMFE Field"
title: "地类编码"
description: "DLBM field in parcel_current."
tags: ["field", "parcel_current", "required"]
timestamp: "2026-06-17T08:28:31.856176+00:00"
layer_role: "parcel_current"
field_name: "DLBM"
standard_role: "parcel_current"
standard_field: "DLBM"
twm_semantic_key: "land_use_code"
alignment_decision: "accept"
---

# Field Semantics

| Property | Value |
| --- | --- |
| Layer | [parcel_current](/layers/parcel_current.md) |
| Field name | `DLBM` |
| Alias | 地类编码 |
| Standard field | `DLBM` |
| Standard role | `parcel_current` |
| Object type | `parcel` |
| Requirement | `required` |
| Semantic key | `land_use_code` |
| Lifecycle status | `active` |
| Standard version | `0.2-demo-release` |
| Match type | `standard_field_catalog` |
| Confidence | 0.99 |
| Alignment score | 0.8935 |
| Alignment decision | `accept` |
| Requires review | `False` |
| Value domain | `gb_t_21010_2017_land_use_code` |
| Value domain status | `loaded` |

# Domain Or Rule

```json
{
  "domain": "gb_t_21010_2017_land_use_code"
}
```

# Alignment Evidence

```json
[
  {
    "basis": "exact_role_contract",
    "detail": "DLBM matched standard field DLBM",
    "type": "matcher"
  },
  {
    "detail": "DLBM exists in standard field catalog",
    "lifecycle_status": "active",
    "standard_version": "0.2-demo-release",
    "type": "standard_catalog"
  },
  {
    "alias_zh": "地类编码",
    "detail": "source alias 地类编码 matches standard alias 地类编码",
    "type": "field_alias"
  },
  {
    "detail": "parcel_current.DLBM requirement=required",
    "requirement": "required",
    "role_alias_zh": "现状地类图斑",
    "standard_role": "parcel_current",
    "type": "role_contract"
  },
  {
    "detail": "DLBM binds TWM semantic key land_use_code",
    "semantic_key": "land_use_code",
    "type": "twm_binding"
  },
  {
    "detail": "DLBM uses value domain gb_t_21010_2017_land_use_code",
    "domain": "gb_t_21010_2017_land_use_code",
    "domain_item_count": 23,
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
