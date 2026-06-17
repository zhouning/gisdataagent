---
type: "MMFE Field"
title: "要素代码"
description: "YSDM field in synthetic_projects."
tags: ["field", "project", "required"]
timestamp: "2026-06-17T08:28:31.856176+00:00"
layer_role: "synthetic_projects"
field_name: "YSDM"
standard_role: "project"
standard_field: "YSDM"
alignment_decision: "accept"
---

# Field Semantics

| Property | Value |
| --- | --- |
| Layer | [synthetic_projects](/layers/synthetic_projects.md) |
| Field name | `YSDM` |
| Alias | 要素代码 |
| Standard field | `YSDM` |
| Standard role | `project` |
| Object type | `project` |
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
    "detail": "YSDM matched standard field YSDM",
    "type": "matcher"
  },
  {
    "detail": "YSDM exists in standard field catalog",
    "lifecycle_status": "active",
    "standard_version": "0.2-demo-release",
    "type": "standard_catalog"
  },
  {
    "alias_zh": "要素代码",
    "detail": "source alias 要素代码 matches standard alias 要素代码",
    "type": "field_alias"
  },
  {
    "detail": "project.YSDM requirement=required",
    "requirement": "required",
    "role_alias_zh": "建设项目空间范围",
    "standard_role": "project",
    "type": "role_contract"
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
