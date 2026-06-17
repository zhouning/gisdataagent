---
type: "MMFE Rule"
title: "生态保护红线触碰审查"
description: "flag if project_eco_rel.overlap_area_m2 > 1"
tags: ["rule", "critical", "mmfe"]
timestamp: "2026-06-17T08:28:31.856176+00:00"
rule_id: "TWM-ECO-001"
severity: "critical"
---

# Rule

| Property | Value |
| --- | --- |
| Rule ID | `TWM-ECO-001` |
| Name | 生态保护红线触碰审查 |
| Severity | `critical` |
| Target layer | [synthetic_projects](/layers/synthetic_projects.md) |
| Target standard role | `project` |
| Constraint layer | [synthetic_eco_redline](/layers/synthetic_eco_redline.md) |
| Constraint standard role | `eco_redline` |

# Logic

```text
flag if project_eco_rel.overlap_area_m2 > 1
```
