---
type: "MMFE Field"
title: "申请日期"
description: "SQRQ field in synthetic_projects."
tags: ["field", "project", "recommended"]
timestamp: "2026-06-17T08:28:31.856176+00:00"
layer_role: "synthetic_projects"
field_name: "SQRQ"
standard_role: "project"
standard_field: "SQRQ"
alignment_decision: "accept"
---

# Field Semantics

| Property | Value |
| --- | --- |
| Layer | [synthetic_projects](/layers/synthetic_projects.md) |
| Field name | `SQRQ` |
| Alias | 申请日期 |
| Standard field | `SQRQ` |
| Standard role | `project` |
| Object type | `project` |
| Requirement | `recommended` |
| Semantic key | `` |
| Lifecycle status | `active` |
| Standard version | `0.2-demo-release` |
| Match type | `standard_field_catalog` |
| Confidence | 0.98 |
| Alignment score | 0.887 |
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
    "detail": "SQRQ matched standard field SQRQ",
    "type": "matcher"
  },
  {
    "detail": "SQRQ exists in standard field catalog",
    "lifecycle_status": "active",
    "standard_version": "0.2-demo-release",
    "type": "standard_catalog"
  },
  {
    "alias_zh": "申请日期",
    "detail": "source alias 申请日期 matches standard alias 申请日期",
    "type": "field_alias"
  },
  {
    "detail": "project.SQRQ requirement=recommended",
    "requirement": "recommended",
    "role_alias_zh": "建设项目空间范围",
    "standard_role": "project",
    "type": "role_contract"
  },
  {
    "detail": "SQRQ has standard field rule",
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
