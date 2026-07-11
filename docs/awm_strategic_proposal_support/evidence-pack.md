# AWM 战略技术方案证据包

生成日期：2026-07-11

仓库版本：887e94fad6f695cbfde0ad4b4b95b527e1c50225

## 1. 证据分级规则

| 等级 | 含义 |
|---|---|
| verified | 当前源码或当前项目文档可直接核验 |
| inferred | 由多个现有基础合理推导，但尚无 AWM 实现 |
| legacy-doc-only | 仅来自既有战略文档，用于结构或表达参考 |
| needs-owner-input | 真实落地所需，但当前没有数据或业务确认 |

## 2. 主要事实

| ID | 事实 | 来源 | 等级 | 支撑章节 |
|---|---|---|---|---|
| E-01 | TWM 已定义项目、状态对象、关系、规则、证据、行动、forecast、rollout 和 validation 等结构 | data_agent/territory_world_model/models.py | verified | 6、7、附录 A |
| E-02 | TWM planner 存在 forecast、plan、beam_search 和 counterfactual_rollout 接口 | data_agent/territory_world_model/planner.py | verified | 6.9、7.1 |
| E-03 | TWM 存在 claim ladder 评估基础 | data_agent/territory_world_model/claim_ladder.py | verified | 6.11、7.1 |
| E-04 | UWM 存在 renderer、simulator 和 evidence-gated planner 模块 | data_agent/uwm/renderer.py；simulator.py；planner.py | verified | 6、7.1 |
| E-05 | UWM geospatial kernel 存在 contracts、state_graph、transition、spatial propagation、counterfactual rollout、evidence gate 和 validation 模块 | data_agent/uwm/geospatial_kernel/ | verified | 6、7.1 |
| E-06 | 当前 geospatial kernel 明确限制经验政策效果声明 | data_agent/uwm/geospatial_kernel/contracts.py；evidence_gate.py | verified | 6.10、6.11、7.4 |
| E-07 | TWM 战略技术方案采用问题、边界、业务场景、架构、现状、落地条件、风险、价值、试点、合作和管理意义结构 | docs/twm-natural-resource-ministry-strategic-technical-proposal.md | legacy-doc-only | 文档整体结构 |
| E-08 | UWM 战略技术方案采用相同主结构，并严格区分 proxy/simulator 与真实 policy outcome | docs/uwm-urban-livability-strategic-technical-proposal.md | legacy-doc-only | 文档整体结构、7、9 |
| E-09 | AWM 已完成应用版图、严格定义和 AWM-CropWater 旗舰原型建议 | docs/agricultural-world-model-application-landscape-and-flagship-design-2026-07-11.md | verified | 1、3、5、6、11 |
| E-10 | Paper13 当前是研究设计和复现准备仓库，首版边界是 passive future-aware optimization | /Users/zhouning/paper13-future-aware-farmland-planning/README.md | verified | 7.3 |
| E-11 | 当前没有 AWM 专业数据、renderer、belief-state estimator、simulator、planner benchmark 或实验结果 | 用户说明；项目文件盘点 | verified | 1、7、8、9、14 |
| E-12 | 分层田块—农场—灌区/县域 AWM 可从现有 kernel 设计演化 | E-01 至 E-06 与 AWM 场景分析综合 | inferred | 3、5、6、10 |
| E-13 | 灌区—田块作物水分管理具有清晰动作、反馈、空间网络和多目标结果，适合作为首个原型 | AWM 场景分析 | inferred | 1、5.1、11、12 |
| E-14 | 真实落地需要田块、渠系、气象、墒情、动作日志、产量和约束数据 | AWM 理论需求推导 | needs-owner-input | 8、附录 B |
| E-15 | 真实动作效果需要试验、准实验或可审计历史 action-outcome 数据 | 地理世界模型证据边界与 AWM 理论推导 | inferred | 6.10、8.3、9.2 |

## 3. 当前缺失输入

- 试点区域和作物；
- 权威田块与渠系数据；
- 真实灌溉动作日志；
- 墒情、作物状态和产量 outcome；
- 可执行水权、配额、工程容量和农艺规则；
- 业务部门的目标权重和复核流程；
- 可用于历史回放或受控验证的完整生长季数据。

这些缺失输入已在正文中作为试点条件或声明边界表达，没有被假定为现有事实。
