---
type: "MMFE Rule"
title: "规则命中项目审批一致性审查"
description: "high or critical rule hits require in_review, returned, supplement_required, or conditional approval"
tags: ["rule", "high", "mmfe"]
timestamp: "2026-06-17T08:28:31.856176+00:00"
rule_id: "TWM-GOV-001"
severity: "high"
---

# Rule

| Property | Value |
| --- | --- |
| Rule ID | `TWM-GOV-001` |
| Name | 规则命中项目审批一致性审查 |
| Severity | `high` |
| Target layer | `approval_records` |
| Target standard role | `approval_records` |
| Constraint layer | `rule_evaluation` |
| Constraint standard role | `rule_evaluation` |

# Logic

```text
high or critical rule hits require in_review, returned, supplement_required, or conditional approval
```
