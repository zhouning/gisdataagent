---
type: "MMFE Rule"
title: "城镇开发边界内外审查"
description: "flag construction projects outside urban boundary for review"
tags: ["rule", "medium", "mmfe"]
timestamp: "2026-06-17T08:28:31.856176+00:00"
rule_id: "TWM-URBAN-001"
severity: "medium"
---

# Rule

| Property | Value |
| --- | --- |
| Rule ID | `TWM-URBAN-001` |
| Name | 城镇开发边界内外审查 |
| Severity | `medium` |
| Target layer | [synthetic_projects](/layers/synthetic_projects.md) |
| Target standard role | `project` |
| Constraint layer | [synthetic_urban_boundary](/layers/synthetic_urban_boundary.md) |
| Constraint standard role | `urban_boundary` |

# Logic

```text
flag construction projects outside urban boundary for review
```
