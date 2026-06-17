---
type: "MMFE AI Chunk"
title: "fusion:rules"
description: "AI retrieval chunk from an MMFE semantic product."
tags: ["ai-chunk", "retrieval", "mmfe"]
timestamp: "2026-06-17T08:28:31.856176+00:00"
chunk_id: "fusion:rules"
---

# Text

TWM 规则评估共 240 条，需要复核 92 条，critical/high 命中 62 条。

# Metadata

```json
{
  "rule_eval_count": 240,
  "pass_count": 148,
  "hit_requires_review_count": 92,
  "critical_or_high_hit_count": 62,
  "status_distribution": {
    "hit_requires_review": 92,
    "pass": 148
  },
  "severity_distribution": {
    "high": 34,
    "info": 148,
    "medium": 30,
    "critical": 28
  },
  "rule_distribution": {
    "TWM-FARM-001": 60,
    "TWM-ECO-001": 60,
    "TWM-PLAN-001": 60,
    "TWM-URBAN-001": 60
  },
  "top_review_examples": [
    {
      "project_id": "PRJ-DEMO-0000",
      "rule_id": "TWM-FARM-001",
      "rule_name_zh": "永久基本农田占用审查",
      "severity": "high",
      "basis": "永久基本农田占用审查 metric=91110.995 m2; project_area=91142.908 m2"
    },
    {
      "project_id": "PRJ-DEMO-0001",
      "rule_id": "TWM-FARM-001",
      "rule_name_zh": "永久基本农田占用审查",
      "severity": "high",
      "basis": "永久基本农田占用审查 metric=66329.99 m2; project_area=167224.705 m2"
    },
    {
      "project_id": "PRJ-DEMO-0002",
      "rule_id": "TWM-ECO-001",
      "rule_name_zh": "生态保护红线触碰审查",
      "severity": "critical",
      "basis": "生态保护红线触碰审查 metric=70959.658 m2; project_area=163116.304 m2"
    },
    {
      "project_id": "PRJ-DEMO-0003",
      "rule_id": "TWM-FARM-001",
      "rule_name_zh": "永久基本农田占用审查",
      "severity": "high",
      "basis": "永久基本农田占用审查 metric=10178.367 m2; project_area=86799.143 m2"
    },
    {
      "project_id": "PRJ-DEMO-0003",
      "rule_id": "TWM-ECO-001",
      "rule_name_zh": "生态保护红线触碰审查",
      "severity": "critical",
      "basis": "生态保护红线触碰审查 metric=86799.143 m2; project_area=86799.143 m2"
    }
  ]
}
```
