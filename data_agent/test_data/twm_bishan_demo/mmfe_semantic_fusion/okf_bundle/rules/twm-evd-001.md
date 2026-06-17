---
type: "MMFE Rule"
title: "多模态证据完整性审查"
description: "each project should have text evidence and at least one remote sensing tile relation"
tags: ["rule", "medium", "mmfe"]
timestamp: "2026-06-17T08:28:31.856176+00:00"
rule_id: "TWM-EVD-001"
severity: "medium"
---

# Rule

| Property | Value |
| --- | --- |
| Rule ID | `TWM-EVD-001` |
| Name | 多模态证据完整性审查 |
| Severity | `medium` |
| Target layer | [synthetic_projects](/layers/synthetic_projects.md) |
| Target standard role | `project` |
| Constraint layer | `multimodal_evidence_index` |
| Constraint standard role | `multimodal_evidence_index` |

# Logic

```text
each project should have text evidence and at least one remote sensing tile relation
```
