# AWM 战略技术方案生成审计

日期：2026-07-11

## 1. 参考文档

- docs/twm-natural-resource-ministry-strategic-technical-proposal.md
- docs/uwm-urban-livability-strategic-technical-proposal.md

两份参考方案均采用 14 个主体章节，覆盖摘要、行业问题、第一性原理、差异比较、业务场景、技术架构、当前基础、落地条件、风险控制、战略价值、试点路线、外部合作、公司管理意义和结语，并通过附录提供模块、指标和对外表述。

## 2. AWM 方案采用的结构策略

AWM 方案复用了上述总体结构，但没有机械复制“当前已验证能力”内容。由于用户明确说明当前没有 AWM 实验数据，第 7 章改为：

1. 已存在的可复用工程基础；
2. 当前仍未完成的 AWM 专业能力；
3. Paper13 与耕地研究的证据边界；
4. 当前最大允许声明和禁止声明。

这一调整避免把 TWM/UWM 的代码和实验结果错误归属于 AWM。

## 3. 主要证据风险及处理

| 风险 | 处理 |
|---|---|
| 将 AWM 目标架构写成当前实现 | 所有 AWM 专业模块标记为“待建设”或“目标设计” |
| 将过程模型情景差异写成因果效果 | 明确区分 observed、simulated、learned、expert prior 和 causally identified |
| 将 Paper13 被动未来感知规划写成动作条件世界模型 | 保留其 passive future-aware optimization 边界 |
| 将 TWM/UWM kernel 可复用性写成 AWM 已完成 | 统一表述为“可复用基础” |
| 在无数据情况下提供准确率或收益数字 | 未写入任何 AWM 实验数值 |
| 将 planner 等同于 world model | 明确 planner 只能消费 simulator rollout |
| 忽略农业物理和安全约束 | 加入水量守恒、渠系容量、水权、农艺和安全 hard mask |
| 忽略空间干扰 | 加入上下游、病虫害、径流和地下水传播 |

## 4. 图表审计

生成两幅目标架构图：

- diagrams/awm_data_state_foundation.png
- diagrams/awm_target_architecture.png

可编辑源文件：

- diagrams/render_awm_diagrams.py
- diagrams/awm_data_state_foundation.dot
- diagrams/awm_target_architecture.dot

由于本机未安装 Graphviz，PNG 由 Matplotlib 脚本生成。DOT 文件保留为可迁移的图结构草稿。两幅图均在标题和图注中标明“目标架构”，不暗示现状实现。

## 5. 结构与术语检查

- 主章节编号连续：1 至 14；
- 附录编号连续：A 至 E；
- AWM、TWM、UWM、Renderer、Simulator、Planner、Evidence Gate 等术语保持一致；
- AWM-CropWater 统一表示首个旗舰原型；
- observation、belief state、action、external scenario 和 outcome 分开表达；
- 无 TODO、TBD 或未解释占位符；
- 无 AWM 已验证指标或未标注的完成性主张。

## 6. 尚待业务方确认

- 首个试点究竟由农业农村部门、水利/灌区管理方还是企业农场牵头；
- 试点区域、主要作物和灌溉制度；
- 可获得的真实动作日志和 outcome 粒度；
- 产量、节水、公平、成本和生态目标的优先级；
- 是否允许开展影子运行或小范围受控试点；
- 对外发布和数据安全口径。
