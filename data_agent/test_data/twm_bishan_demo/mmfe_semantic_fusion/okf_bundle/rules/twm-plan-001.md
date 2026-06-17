---
type: "MMFE Rule"
title: "用途管制分区一致性审查"
description: "compare project_type with dominant plan_zone_type"
tags: ["rule", "medium", "mmfe"]
timestamp: "2026-06-17T08:28:31.856176+00:00"
rule_id: "TWM-PLAN-001"
severity: "medium"
---

# Rule

| Property | Value |
| --- | --- |
| Rule ID | `TWM-PLAN-001` |
| Name | 用途管制分区一致性审查 |
| Severity | `medium` |
| Target layer | [synthetic_projects](/layers/synthetic_projects.md) |
| Target standard role | `project` |
| Constraint layer | [synthetic_planning_zones](/layers/synthetic_planning_zones.md) |
| Constraint standard role | `planning_zone` |

# Logic

```text
compare project_type with dominant plan_zone_type
```
