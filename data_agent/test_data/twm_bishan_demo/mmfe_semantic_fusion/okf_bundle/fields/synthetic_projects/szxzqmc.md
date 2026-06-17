---
type: "MMFE Field"
title: "所在行政区名称"
description: "SZXZQMC field in synthetic_projects."
tags: ["field", "project", "required"]
timestamp: "2026-06-17T08:28:31.856176+00:00"
layer_role: "synthetic_projects"
field_name: "SZXZQMC"
standard_role: "project"
standard_field: "SZXZQMC"
twm_semantic_key: "admin_name"
alignment_decision: "accept"
---

# Field Semantics

| Property | Value |
| --- | --- |
| Layer | [synthetic_projects](/layers/synthetic_projects.md) |
| Field name | `SZXZQMC` |
| Alias | 所在行政区名称 |
| Standard field | `SZXZQMC` |
| Standard role | `project` |
| Object type | `project` |
| Requirement | `required` |
| Semantic key | `admin_name` |
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
    "detail": "SZXZQMC matched standard field SZXZQMC",
    "type": "matcher"
  },
  {
    "detail": "SZXZQMC exists in standard field catalog",
    "lifecycle_status": "active",
    "standard_version": "0.2-demo-release",
    "type": "standard_catalog"
  },
  {
    "alias_zh": "所在行政区名称",
    "detail": "source alias 所在行政区名称 matches standard alias 所在行政区名称",
    "type": "field_alias"
  },
  {
    "detail": "project.SZXZQMC requirement=required",
    "requirement": "required",
    "role_alias_zh": "建设项目空间范围",
    "standard_role": "project",
    "type": "role_contract"
  },
  {
    "detail": "SZXZQMC binds TWM semantic key admin_name",
    "semantic_key": "admin_name",
    "type": "twm_binding"
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
