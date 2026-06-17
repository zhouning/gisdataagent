---
type: "MMFE Field"
title: "稳定利用耕地标识"
description: "WDGD field in synthetic_pbf."
tags: ["field", "pbf", "required"]
timestamp: "2026-06-17T08:28:31.856176+00:00"
layer_role: "synthetic_pbf"
field_name: "WDGD"
standard_role: "pbf"
standard_field: "WDGD"
alignment_decision: "accept"
---

# Field Semantics

| Property | Value |
| --- | --- |
| Layer | [synthetic_pbf](/layers/synthetic_pbf.md) |
| Field name | `WDGD` |
| Alias | 稳定利用耕地标识 |
| Standard field | `WDGD` |
| Standard role | `pbf` |
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
| Value domain | `yes_no_code` |
| Value domain status | `loaded` |

# Domain Or Rule

```json
{
  "domain": "yes_no_code"
}
```

# Alignment Evidence

```json
[
  {
    "basis": "exact_role_contract",
    "detail": "WDGD matched standard field WDGD",
    "type": "matcher"
  },
  {
    "detail": "WDGD exists in standard field catalog",
    "lifecycle_status": "active",
    "standard_version": "0.2-demo-release",
    "type": "standard_catalog"
  },
  {
    "alias_zh": "稳定利用耕地标识",
    "detail": "source alias 稳定利用耕地标识 matches standard alias 稳定利用耕地标识",
    "type": "field_alias"
  },
  {
    "detail": "pbf.WDGD requirement=required",
    "requirement": "required",
    "role_alias_zh": "永久基本农田",
    "standard_role": "pbf",
    "type": "role_contract"
  },
  {
    "detail": "WDGD uses value domain yes_no_code",
    "domain": "yes_no_code",
    "domain_item_count": 2,
    "domain_known": true,
    "type": "value_domain"
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
