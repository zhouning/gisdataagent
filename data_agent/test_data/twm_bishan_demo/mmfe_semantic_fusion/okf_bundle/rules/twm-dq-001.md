---
type: "MMFE Rule"
title: "空间数据质量门槛"
description: "invalid geometries must be zero and rule input features must pass qa_use_for_rules"
tags: ["rule", "blocking", "mmfe"]
timestamp: "2026-06-17T08:28:31.856176+00:00"
rule_id: "TWM-DQ-001"
severity: "blocking"
---

# Rule

| Property | Value |
| --- | --- |
| Rule ID | `TWM-DQ-001` |
| Name | 空间数据质量门槛 |
| Severity | `blocking` |
| Target layer | `all_vector_layers` |
| Target standard role | `all_vector_layers` |
| Constraint layer |  |
| Constraint standard role | `` |

# Logic

```text
invalid geometries must be zero and rule input features must pass qa_use_for_rules
```
