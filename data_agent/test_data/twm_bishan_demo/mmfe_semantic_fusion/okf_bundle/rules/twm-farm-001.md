---
type: "MMFE Rule"
title: "永久基本农田占用审查"
description: "flag if project_pbf_rel.overlap_area_m2 > 1"
tags: ["rule", "high", "mmfe"]
timestamp: "2026-06-17T08:28:31.856176+00:00"
rule_id: "TWM-FARM-001"
severity: "high"
---

# Rule

| Property | Value |
| --- | --- |
| Rule ID | `TWM-FARM-001` |
| Name | 永久基本农田占用审查 |
| Severity | `high` |
| Target layer | [synthetic_projects](/layers/synthetic_projects.md) |
| Target standard role | `project` |
| Constraint layer | [synthetic_pbf](/layers/synthetic_pbf.md) |
| Constraint standard role | `pbf` |

# Logic

```text
flag if project_pbf_rel.overlap_area_m2 > 1
```
