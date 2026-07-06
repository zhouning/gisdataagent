# UWM 上海市权威数据需求证据包

## 输入证据

| 证据 | 路径 | 用途 |
|---|---|---|
| UWM 战略技术说明 | `docs/uwm-urban-livability-strategic-technical-proposal.md` | UWM 定位、业务场景、工程进展、风险边界和试点路线 |
| UWM-Livability 设计备忘录 | `docs/uwm-livability-track2-design-2026-07-04.md` | 城市宜居性问题、UWM 与传统宜居性评价差异、数据基础策略 |
| Renderer / Simulator / Planner 理论架构 | `docs/uwm-renderer-simulator-planner-theory-2026-07-04.md` | `UwmCanonicalObservation`、`UwmRolloutTrace`、`UwmPlanPackage` 的世界模型纪律 |
| UWM 数据基础总览 | `docs/reports/uwm_data_foundation_summary_2026-07-05.md` | 当前 manifest、真实/代理/拟合/半合成/合成数据分类、核心缺口 |
| UWM 数据基础 manifest | `docs/reports/uwm_data_foundation_manifest.md` / `.csv` | 数据角色、来源类型、claim boundary、可用性 |
| UWM 宜居性业务理论 | `docs/reports/uwm_livability_business_theory_2026-07-05.md` | 环境健康、服务可达、空间公平、城市形态/活动耦合和规划约束 |
| Graph-MDP / Model-Based RL scaffold | `docs/reports/uwm_model_based_rl_inspiration_implementation_2026-07-05.md` | Graph-MDP、known-effect rollout、offline value/world model 和 planner 边界 |
| DRL Urban Planning 适配说明 | `docs/reports/uwm_drl_urban_planning_deep_dive_and_adaptation_2026-07-05.md` | 城市规划 RL 思路可迁移部分和不可迁移边界 |
| UWM 代码模块 | `data_agent/uwm/` | 当前 UWM contracts、renderer、simulator、planner、evaluation 等工程实现 |
| UWM 测试 | `data_agent/test_uwm_*.py` | 当前工程契约、数据接入、renderer、simulator、planner、benchmark 验证 |

## 关键事实

1. 当前 UWM 已经形成 `data foundation / MMFE state input -> renderer -> scene state -> simulator -> evidence-gated planner -> evaluation` 的可运行链条。
2. 当前 UWM 已有 `UwmCanonicalObservation.v1`、`UwmRolloutTrace.v1`、`UwmPlanPackage.v1` 等契约，但契约可运行不等于真实政策效果有效。
3. 当前最强事实性证明是 OpenAQ 600 条真实小时观测 temporal holdout 上，UWM online temporal state update 显著优于传统静态 baseline suite。
4. 当前 Graph-MDP / known-effect planning benchmark 能说明模型式图搜索在 proxy / simulator replay 场景中优于静态启发式，不能说明真实政策 outcome 优越性。
5. 当前数据基础 manifest 已覆盖多类角色，但 claim ceiling 仍为 `fragile`，主要 blocker 包括真实政策 intervention outcome、场景一致 station-calibrated air-quality holdout、权威人口/脆弱性、真实 travel-time / OD 和因果识别。
6. 上海市申请权威数据的目的，应是把 UWM 从公开代理和 known-effect replay 推进到真实城市业务验证，而不是获取全量城市数据训练通用大模型。

## 不确定项

- 上海市具体源系统、字段名、权限边界、保密等级和数据共享流程需要上海市数据主管和业务主管确认。
- 本文中的 action_type 枚举为 UWM 接入建议，不替代上海市正式业务分类、项目分类和审批分类。
- 原始几何、人口、出行、环境监测和项目明细是否跨环境交付，必须由数据安全主管和数据所有部门确认；建议默认不跨环境导出。
- 真实政策 outcome 的可用指标需与上海试点主题共同确定，例如热风险、污染暴露、服务可达、投诉率、设施使用量、更新项目完成后监测等。

## 可声明边界

可以声明：

- UWM 需要上海市权威数据，是为了在授权环境中开展城市宜居治理的状态诊断、干预推演、方案比选和证据审计。
- 第一轮申请可以只要求脱敏清单、字段字典、规模画像、内网引用和汇总统计。
- 对真实政策效果的声明必须经过 holdout、历史回放、负控、对照组和因果证据门控。

不能声明：

- UWM 已经在上海真实政策 outcome 上优于传统方法。
- 公开代理数据、合成数据或重庆 proxy 场景结果可以直接替代上海真实权威数据。
- 获取个人轨迹、通信明细、健康个体数据或其他敏感明细是 UWM 的默认前提。
- UWM 输出可以替代上海市相关部门的业务审查、规划决策或项目审批。
