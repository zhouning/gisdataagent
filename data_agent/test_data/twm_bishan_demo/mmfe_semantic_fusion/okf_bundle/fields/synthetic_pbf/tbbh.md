---
type: "MMFE Field"
title: "图斑编号"
description: "TBBH field in synthetic_pbf."
tags: ["field", "pbf", "required"]
timestamp: "2026-06-17T08:28:31.856176+00:00"
layer_role: "synthetic_pbf"
field_name: "TBBH"
standard_role: "pbf"
standard_field: "TBBH"
twm_semantic_key: "source_parcel_id"
alignment_decision: "accept"
---

# Field Semantics

| Property | Value |
| --- | --- |
| Layer | [synthetic_pbf](/layers/synthetic_pbf.md) |
| Field name | `TBBH` |
| Alias | 图斑编号 |
| Standard field | `TBBH` |
| Standard role | `pbf` |
| Object type | `control_boundary` |
| Requirement | `required` |
| Semantic key | `source_parcel_id` |
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
    "detail": "pbf.TBBH requirement=required",
    "requirement": "required",
    "role_alias_zh": "永久基本农田",
    "standard_role": "pbf",
    "type": "role_contract"
  },
  {
    "detail": "TBBH binds TWM semantic key source_parcel_id",
    "semantic_key": "source_parcel_id",
    "type": "twm_binding"
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
