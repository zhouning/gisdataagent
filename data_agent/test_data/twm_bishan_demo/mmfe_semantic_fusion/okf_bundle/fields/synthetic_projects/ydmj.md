---
type: "MMFE Field"
title: "用地面积"
description: "YDMJ field in synthetic_projects."
tags: ["field", "project", "required"]
timestamp: "2026-06-17T08:28:31.856176+00:00"
layer_role: "synthetic_projects"
field_name: "YDMJ"
standard_role: "project"
standard_field: "YDMJ"
twm_semantic_key: "area_m2"
alignment_decision: "accept"
---

# Field Semantics

| Property | Value |
| --- | --- |
| Layer | [synthetic_projects](/layers/synthetic_projects.md) |
| Field name | `YDMJ` |
| Alias | 用地面积 |
| Standard field | `YDMJ` |
| Standard role | `project` |
| Object type | `project` |
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
    "detail": "YDMJ matched standard field YDMJ",
    "type": "matcher"
  },
  {
    "detail": "YDMJ exists in standard field catalog",
    "lifecycle_status": "active",
    "standard_version": "0.2-demo-release",
    "type": "standard_catalog"
  },
  {
    "alias_zh": "用地面积",
    "detail": "source alias 用地面积 matches standard alias 用地面积",
    "type": "field_alias"
  },
  {
    "detail": "project.YDMJ requirement=required",
    "requirement": "required",
    "role_alias_zh": "建设项目空间范围",
    "standard_role": "project",
    "type": "role_contract"
  },
  {
    "detail": "YDMJ binds TWM semantic key area_m2",
    "semantic_key": "area_m2",
    "type": "twm_binding"
  },
  {
    "detail": "YDMJ has standard field rule",
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
        "module": "用途管制",
        "table_alias_zh": "项目占地范围",
        "table_code": "XS_XMKJFW"
      },
      {
        "module": "用途管制",
        "table_alias_zh": "临时用地项目占地范围",
        "table_code": "LSYD_XMZDFW"
      }
    ],
    "standard_version": "2026-06-16-draft",
    "type": "standard_reference"
  }
]
```
