---
type: "MMFE Field"
title: "永久基本农田面积"
description: "YJJBNTMJ field in synthetic_pbf."
tags: ["field", "pbf", "required"]
timestamp: "2026-06-17T08:28:31.856176+00:00"
layer_role: "synthetic_pbf"
field_name: "YJJBNTMJ"
standard_role: "pbf"
standard_field: "YJJBNTMJ"
twm_semantic_key: "area_m2"
alignment_decision: "accept"
---

# Field Semantics

| Property | Value |
| --- | --- |
| Layer | [synthetic_pbf](/layers/synthetic_pbf.md) |
| Field name | `YJJBNTMJ` |
| Alias | 永久基本农田面积 |
| Standard field | `YJJBNTMJ` |
| Standard role | `pbf` |
| Object type | `control_boundary` |
| Requirement | `required` |
| Semantic key | `area_m2` |
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
  "min_exclusive": 0,
  "type": "number",
  "unit": "m2"
}
```

# Alignment Evidence

```json
[
  {
    "basis": "exact_role_contract",
    "detail": "YJJBNTMJ matched standard field YJJBNTMJ",
    "type": "matcher"
  },
  {
    "detail": "YJJBNTMJ exists in standard field catalog",
    "lifecycle_status": "active",
    "standard_version": "0.2-demo-release",
    "type": "standard_catalog"
  },
  {
    "alias_zh": "永久基本农田面积",
    "detail": "source alias 永久基本农田面积 matches standard alias 永久基本农田面积",
    "type": "field_alias"
  },
  {
    "detail": "pbf.YJJBNTMJ requirement=required",
    "requirement": "required",
    "role_alias_zh": "永久基本农田",
    "standard_role": "pbf",
    "type": "role_contract"
  },
  {
    "detail": "YJJBNTMJ binds TWM semantic key area_m2",
    "semantic_key": "area_m2",
    "type": "twm_binding"
  },
  {
    "detail": "YJJBNTMJ has standard field rule",
    "rule": {
      "min_exclusive": 0,
      "type": "number",
      "unit": "m2"
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
