---
type: "MMFE AI Chunk"
title: "fusion:optimization"
description: "AI retrieval chunk from an MMFE semantic product."
tags: ["ai-chunk", "retrieval", "mmfe"]
timestamp: "2026-06-17T08:28:31.856176+00:00"
chunk_id: "fusion:optimization"
---

# Text

多目标优化含 13 个目标和 7 个方案；合法可行方案 2 个，硬约束阻断 5 个。

# Metadata

```json
{
  "method": "hard_constraint_filter_then_normalized_weighted_score_and_non_dominated_sorting",
  "objective_count": 13,
  "scenario_count": 7,
  "legal_feasible_scenario_count": 2,
  "blocked_scenario_count": 5,
  "comparison_scope": "legal_feasible_space",
  "non_dominated_scenarios": [
    {
      "scenario_id": "SCN-BALANCED",
      "scenario_name_zh": "均衡治理方案",
      "hard_constraint_status": "legal_feasible",
      "optimization_scope": "legal_feasible_space",
      "hard_constraint_violation_m2": 0.0,
      "weighted_score": 0.769724
    },
    {
      "scenario_id": "SCN-BASELINE-CURRENT",
      "scenario_name_zh": "现状基线",
      "hard_constraint_status": "legal_feasible",
      "optimization_scope": "legal_feasible_space",
      "hard_constraint_violation_m2": 0.0,
      "weighted_score": 0.786667
    }
  ],
  "ranked_scenarios": [
    {
      "rank": 1,
      "scenario_id": "SCN-BASELINE-CURRENT",
      "scenario_name_zh": "现状基线",
      "hard_constraint_status": "legal_feasible",
      "optimization_scope": "legal_feasible_space",
      "hard_constraint_violation_m2": 0.0,
      "weighted_score": 0.786667
    },
    {
      "rank": 2,
      "scenario_id": "SCN-BALANCED",
      "scenario_name_zh": "均衡治理方案",
      "hard_constraint_status": "legal_feasible",
      "optimization_scope": "legal_feasible_space",
      "hard_constraint_violation_m2": 0.0,
      "weighted_score": 0.769724
    }
  ],
  "feasibility_distribution": {
    "legal_feasible": 2,
    "blocked_by_hard_constraint": 5
  },
  "hard_constraint_policy_zh": "永久基本农田和生态保护红线作为法定硬约束先过滤；超过工程容差的方案仅保留为压力测试或复核样本，不进入合法可推荐空间的 Pareto 排序。",
  "objectives": [
    {
      "objective_id": "pbf_overlap_m2",
      "objective_name_zh": "永久基本农田占用最小化",
      "category": "hard_constraint",
      "direction": "min",
      "unit": "m2",
      "weight": 1.0,
      "hard_constraint": true,
      "description_zh": "候选方案与永久基本农田保护范围的正面积叠置，应优先为 0。"
    },
    {
      "objective_id": "eco_overlap_m2",
      "objective_name_zh": "生态保护红线触碰最小化",
      "category": "hard_constraint",
      "direction": "min",
      "unit": "m2",
      "weight": 1.0,
      "hard_constraint": true,
      "description_zh": "候选方案与生态保护红线的正面积叠置，应优先为 0。"
    },
    {
      "objective_id": "planning_conflict_m2",
      "objective_name_zh": "用途管制冲突最小化",
      "category": "planning_consistency",
      "direction": "min",
      "unit": "m2",
      "weight": 0.8,
      "hard_constraint": false,
      "description_zh": "候选方案与规划分区或用途管制规则不一致的面积。"
    },
    {
      "objective_id": "farmland_loss_m2",
      "objective_name_zh": "耕地损失最小化",
      "category": "resource_protection",
      "direction": "min",
      "unit": "m2",
      "weight": 0.9,
      "hard_constraint": false,
      "description_zh": "候选方案或推演变化造成的耕地面积减少。"
    },
    {
      "objective_id": "farmland_gain_m2",
      "objective_name_zh": "耕地补充最大化",
      "category": "resource_protection",
      "direction": "max",
      "unit": "m2",
      "weight": 0.55,
      "hard_constraint": false,
      "description_zh": "候选方案或推演变化带来的耕地补充面积。"
    },
    {
      "objective_id": "development_area_m2",
      "objective_name_zh": "建设承载能力最大化",
      "category": "development",
      "direction": "max",
      "unit": "m2",
      "weight": 0.45,
      "hard_constraint": false,
      "description_zh": "在合法可行空间内可承载的项目或建设调整面积。"
    },
    {
      "objective_id": "compactness_score",
      "objective_name_zh": "空间紧凑性最大化",
      "category": "spatial_form",
      "direction": "max",
      "unit": "score",
      "weight": 0.5,
      "hard_constraint": false,
      "description_zh": "基于 4*pi*area/perimeter^2 的面积加权紧凑度近似指标。"
    },
    {
      "objective_id": "adjustment_cost_proxy",
      "objective_name_zh": "调整成本最小化",
      "category": "cost",
      "direction": "min",
      "unit": "proxy",
      "weight": 0.55,
      "hard_constraint": false,
      "description_zh": "用调整面积、硬约束触碰和规划冲突构造的工程测试成本代理指标。"
    },
    {
      "objective_id": "admin_fairness_cv",
      "objective_name_zh": "行政区负担均衡",
      "category": "fairness",
      "direction": "min",
      "unit": "cv",
      "weight": 0.35,
      "hard_constraint": false,
      "description_zh": "方案面积在行政单元间分布的变异系数，越低代表越均衡。"
    },
    {
      "objective_id": "robustness_score",
      "objective_name_zh": "方案稳健性最大化",
      "category": "uncertainty",
      "direction": "max",
      "unit": "score",
      "weight": 0.45,
      "hard_constraint": false,
      "description_zh": "基于硬约束风险、复核负荷和 WorldModel episode 稳定性的稳健性近似指标。"
    },
    {
      "objective_id": "review_load_count",
      "objective_name_zh": "人工复核负荷最小化",
      "category": "governance",
      "direction": "min",
      "unit": "count",
      "weight": 0.35,
      "hard_constraint": false,
      "description_zh": "候选方案触发需人工复核的规则命中数量。"
    },
    {
      "objective_id": "slope_improvement_pct",
      "objective_name_zh": "坡度适宜性改善最大化",
      "category": "dynamic_projection",
      "direction": "max",
      "unit": "pct",
      "weight": 0.3,
      "hard_constraint": false,
      "description_zh": "来自 WorldModel/MPC 摘要的坡度改善信号；负坡度变化按改善处理。"
    },
    {
      "objective_id": "contiguity_gain",
      "objective_name_zh": "空间连片度提升最大化",
      "category": "dynamic_projection",
      "direction": "max",
      "unit": "score",
      "weight": 0.3,
      "hard_constraint": false,
      "description_zh": "来自 WorldModel/MPC 摘要的连片度变化信号。"
    }
  ],
  "hard_constraint_objectives": [
    "pbf_overlap_m2",
    "eco_overlap_m2"
  ]
}
```
