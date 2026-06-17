# Objectives

* [调整成本最小化](adjustment_cost_proxy.md) - 用调整面积、硬约束触碰和规划冲突构造的工程测试成本代理指标。
* [行政区负担均衡](admin_fairness_cv.md) - 方案面积在行政单元间分布的变异系数，越低代表越均衡。
* [空间紧凑性最大化](compactness_score.md) - 基于 4*pi*area/perimeter^2 的面积加权紧凑度近似指标。
* [空间连片度提升最大化](contiguity_gain.md) - 来自 WorldModel/MPC 摘要的连片度变化信号。
* [建设承载能力最大化](development_area_m2.md) - 在合法可行空间内可承载的项目或建设调整面积。
* [生态保护红线触碰最小化](eco_overlap_m2.md) - 候选方案与生态保护红线的正面积叠置，应优先为 0。
* [耕地补充最大化](farmland_gain_m2.md) - 候选方案或推演变化带来的耕地补充面积。
* [耕地损失最小化](farmland_loss_m2.md) - 候选方案或推演变化造成的耕地面积减少。
* [永久基本农田占用最小化](pbf_overlap_m2.md) - 候选方案与永久基本农田保护范围的正面积叠置，应优先为 0。
* [用途管制冲突最小化](planning_conflict_m2.md) - 候选方案与规划分区或用途管制规则不一致的面积。
* [人工复核负荷最小化](review_load_count.md) - 候选方案触发需人工复核的规则命中数量。
* [方案稳健性最大化](robustness_score.md) - 基于硬约束风险、复核负荷和 WorldModel episode 稳定性的稳健性近似指标。
* [坡度适宜性改善最大化](slope_improvement_pct.md) - 来自 WorldModel/MPC 摘要的坡度改善信号；负坡度变化按改善处理。
