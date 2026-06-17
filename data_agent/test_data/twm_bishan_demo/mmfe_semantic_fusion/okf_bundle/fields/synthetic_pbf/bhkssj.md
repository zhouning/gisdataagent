---
type: "MMFE Field"
title: "保护开始时间"
description: "BHKSSJ field in synthetic_pbf."
tags: ["field", "pbf", "required"]
timestamp: "2026-06-17T08:28:31.856176+00:00"
layer_role: "synthetic_pbf"
field_name: "BHKSSJ"
standard_role: "pbf"
standard_field: "BHKSSJ"
alignment_decision: "accept"
---

# Field Semantics

| Property | Value |
| --- | --- |
| Layer | [synthetic_pbf](/layers/synthetic_pbf.md) |
| Field name | `BHKSSJ` |
| Alias | 保护开始时间 |
| Standard field | `BHKSSJ` |
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
| Value domain | `` |
| Value domain status | `` |

# Domain Or Rule

```json
{
  "pattern": "^[0-9]{8}$"
}
```

# Alignment Evidence

```json
[
  {
    "basis": "exact_role_contract",
    "detail": "BHKSSJ matched standard field BHKSSJ",
    "type": "matcher"
  },
  {
    "detail": "BHKSSJ exists in standard field catalog",
    "lifecycle_status": "active",
    "standard_version": "0.2-demo-release",
    "type": "standard_catalog"
  },
  {
    "alias_zh": "保护开始时间",
    "detail": "source alias 保护开始时间 matches standard alias 保护开始时间",
    "type": "field_alias"
  },
  {
    "detail": "pbf.BHKSSJ requirement=required",
    "requirement": "required",
    "role_alias_zh": "永久基本农田",
    "standard_role": "pbf",
    "type": "role_contract"
  },
  {
    "detail": "BHKSSJ has standard field rule",
    "rule": {
      "pattern": "^[0-9]{8}$"
    },
    "type": "field_rule"
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
