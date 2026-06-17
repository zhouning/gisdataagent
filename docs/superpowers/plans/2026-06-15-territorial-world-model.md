# 国土空间世界模型实施计划

- **日期**：2026-06-15
- **设计文档**：`docs/superpowers/specs/2026-06-15-territorial-world-model-design.md`
- **数据需求**：`docs/superpowers/specs/2026-06-15-territorial-world-model-data-requirements.md`
- **目标**：阶段性调整为先构建 paper 验证底座和评估框架；待动态推演、多目标优化和方案比选相关 paper 通过验证后，再推进完整 TWM MVP。

## 当前阶段决策

2026-06-16 复盘后，TWM 暂不直接进入完整产品化实现。当前怀疑点是合理的：如果动态推演和多目标优化没有通过更多 paper 的实验验证，贸然推进 TWM 只会把系统做成“规则筛查 + 演示优化”的壳，无法证明其作为世界模型的核心价值。

当前阶段定位调整为：

```text
TWM validation scaffold
```

也就是：

1. 保留已经准备好的三套 TWM 数据包、标准契约、MMFE 证据链、硬约束规则和优化夹具；
2. 不急于实现完整 `territory_world_model` 产品模块、前端和 API；
3. 优先服务后续 paper 验证：动态推演、多目标优化、WorldModel/MPC/DRL/启发式方法比较；
4. 用统一的 `S_t`、硬约束、指标体系、Pareto 比选和审计口径评价不同方法；
5. 只有当关键 paper 证明方法具备稳定性、泛化性和业务可解释性后，再恢复系统级实现。

恢复 TWM 产品化推进的前置条件：

- 动态推演优于 Markov、CA、启发式或简单规则 baseline；
- 多目标优化能在法定硬约束下稳定产生有意义的 Pareto 解；
- 结果能跨区域泛化，不只在 demo 数据上成立；
- 指标改善能被自然资源治理业务解释；
- 模型输出能完整接入证据链和人工复核闭环。

## 总体节奏

在阶段决策调整前，原计划是先做可演示闭环：

```text
MMFE semantic product / data asset
        ↓
TWM layer binding
        ↓
state S_t
        ↓
policy rule evaluation
        ↓
rule hits + evidence chain + risk layer
        ↓
human review
```

现在该闭环暂不作为产品实现起点，而作为 paper 验证底座的固定数据契约。当前已有数据足够支撑验证框架：建议以璧山 DLTB 坡度增强数据、跨乡镇评测包和村规划标准样例包作为统一实验输入，以合成永久基本农田、生态红线、行政单元、年度变化和优化夹具补齐方法比较闭环。所有合成数据必须带 `synthetic=true` 和 `not_for_production=true` 元数据。

## Phase -1：演示数据准备

目标：在进入核心实现前准备稳定、可重复生成的 TWM demo 数据包。

输入建议：

- `parcel_current`: `/Users/zhouning/Downloads/bishan/DLTB_with_slope.gpkg`
- `scenario_candidate`: `/Users/zhouning/farmland_mpc_runs/bishan/mpc_output/optimized.shp`
- `world_model_summary`: `/Users/zhouning/farmland_mpc_runs/bishan/mpc_output/mpc_summary.json`

生成内容：

- `synthetic_pbf.geojson`
- `synthetic_eco_redline.geojson`
- `synthetic_admin_units.geojson`
- `synthetic_annual_change.geojson`
- `synthetic_projects.geojson`
- `dataset_manifest.json`

实现位置建议：

- `scripts/generate_twm_demo_data.py`
- 或后续 `data_agent/territory_world_model/synthetic.py`

验收：

- 生成过程可重复。
- 每个合成图层包含 `synthetic`, `synthetic_method`, `source_dataset`, `not_for_production`。
- demo 数据能触发至少一条 PBF 规则和一条生态红线规则。

当前状态：已完成，可以作为后续 Phase 0-2 开发基线使用。现有三类数据包分工如下：

| 数据包 | 路径 | 用途 |
|---|---|---|
| 快速开发包 | `data_agent/test_data/twm_bishan_demo/` | 单样区端到端回归、前端预览、真实 Sentinel-2 影像证据 |
| 多行政评测包 | `data_agent/test_data/twm_bishan_multi_admin_eval/` | 跨乡镇汇总、边界项目、MMFE 压测、真实 Sentinel-2 影像证据 |
| 标准结构样例包 | `data_agent/test_data/twm_one_map_village_standard_sample/` | 自然资源一张图/村规划汇交字段兼容性、标准契约 QA |

后续开发不得把合成管控线、审批、执法数据解释为生产权威数据。真实权威数据进入时，应通过角色绑定、字段映射、标准平台派生物和 QA gate 替换输入资产，不重写 TWM 核心逻辑。

## Phase 0：Schema 与核心契约

目标：把 `twm_*` 表族和 Python 契约建立起来，不做复杂业务逻辑。

改动：

- 新增 migration `089_twm_core.sql`
  - `twm_project`
  - `twm_layer_binding`
  - `twm_state_version`
  - `twm_state_object`
  - `twm_state_relation`
  - `twm_rule_set`
  - `twm_policy_rule`
  - `twm_rule_hit`
  - `twm_evidence_item`
  - `twm_review_task`
  - `twm_scenario`
  - `twm_scenario_metric`
- 新增包 `data_agent/territory_world_model/`
  - `models.py`
  - `repository.py`
  - `rule_dsl.py`

验收：

- migration 可重复执行。
- repository 可创建 project、layer binding、rule set、rule。
- DSL parser 能校验合法/非法 rule body。

建议测试：

```bash
.venv/bin/python -m pytest data_agent/test_twm_models.py data_agent/test_twm_repository.py data_agent/test_twm_rule_dsl.py -q
```

## Phase 1：状态构建 MVP

目标：从普通 GIS 文件或 MMFE `.semantic.json` 构建 `S_t`。

改动：

- `semantic_loader.py`
  - 读取 MMFE manifest。
  - 解析 `business_output.path`、`semantic_mappings`、`quality`、`lineage`。
- `state_builder.py`
  - 将 parcel/control_line/planning_zone/project 等绑定图层转为 `twm_state_object`。
  - 计算最小关系集：`intersects`、`within`、`contains`。
  - 写入 `twm_state_version` build summary。

验收：

- 给定 parcel + pbf 两个小 GeoJSON，能生成对象、关系和状态摘要。
- 所有对象保留 source asset/path 与 source feature ID。
- quality summary 能反映 MMFE manifest 中的质量警告。

建议测试：

```bash
PROJ_DATA=/Users/zhouning/miniconda3/envs/farmland-mpc/share/proj .venv/bin/python -m pytest data_agent/test_twm_state_builder.py -q
```

## Phase 2：规则执行与证据链

目标：实现首批硬约束规则并生成可审计证据。

改动：

- `rule_evaluator.py`
  - 支持对象过滤。
  - 支持 `intersects`、`within`、overlap area、overlap ratio。
  - 支持阈值条件 `gt/gte/lt/lte/eq/in/exists`。
- `evidence.py`
  - 生成 `source_feature`、`rule_clause`、`spatial_calc`、`semantic_mapping` 证据。
- 内置 seed 规则：
  - `TWM-FARM-001`
  - `TWM-ECO-001`

验收：

- 永久基本农田触碰可生成 `twm_rule_hit`。
- 生态红线触碰可生成 `twm_rule_hit`。
- 每个 hit 至少包含 source/rule/spatial 三类证据。
- `review_policy=always_review` 会创建 `twm_review_task`。

建议测试：

```bash
PROJ_DATA=/Users/zhouning/miniconda3/envs/farmland-mpc/share/proj .venv/bin/python -m pytest data_agent/test_twm_rule_evaluator.py data_agent/test_twm_evidence.py -q
```

## Phase 3：REST API

目标：把核心闭环暴露给前端和外部调用。

改动：

- 新增 `data_agent/api/territory_world_model_routes.py`
- 在 `data_agent/frontend_api.py` 挂载路由
- API：
  - `GET/POST /api/twm/projects`
  - `GET /api/twm/projects/{id}`
  - `GET/POST /api/twm/projects/{id}/layer-bindings`
  - `POST /api/twm/projects/{id}/build-state`
  - `GET /api/twm/states/{id}`
  - `POST /api/twm/states/{id}/evaluate-rules`
  - `GET /api/twm/states/{id}/rule-hits`
  - `GET /api/twm/rule-hits/{id}`
  - `PATCH /api/twm/rule-hits/{id}/review`
  - `GET /api/twm/states/{id}/risk-layer`

验收：

- 鉴权沿用现有 cookie/JWT。
- 普通用户只能看自己的项目，admin 可看全部。
- rule hit review 能写入复核结论并更新 hit 状态。

建议测试：

```bash
PROJ_DATA=/Users/zhouning/miniconda3/envs/farmland-mpc/share/proj .venv/bin/python -m pytest data_agent/test_twm_api.py -q
```

## Phase 4：ADK Toolset

目标：让 Agent 能调用 TWM 闭环。

改动：

- 新增 `data_agent/toolsets/territory_world_model_tools.py`
- 注册到 toolset 发现/能力目录中
- 工具：
  - `twm_create_project`
  - `twm_bind_layer`
  - `twm_build_state`
  - `twm_evaluate_rules`
  - `twm_explain_rule_hit`
  - `twm_review_hit`
  - `twm_generate_audit_report`

验收：

- 工具返回 JSON，包含项目、状态、命中和证据路径。
- 工具说明中明确“风险识别/复核辅助，不替代审批结论”。

建议测试：

```bash
.venv/bin/python -m pytest data_agent/test_twm_toolset.py -q
```

## Phase 5：前端 MVP

目标：在 DataPanel 中完成业务可操作界面。

改动：

- 新增 `frontend/src/components/datapanel/TerritoryWorldModelTab.tsx`
- 修改 `frontend/src/components/DataPanel.tsx`
- UI 区块：
  - 项目与输入绑定
  - 状态构建
  - 规则校验
  - 命中清单
  - 证据抽屉
  - 人工复核

验收：

- 用户可从界面创建项目、绑定图层、构建状态、执行规则。
- 风险图层可进入地图 pending update。
- 长文本和表格在窄屏不溢出。

建议检查：

```bash
npm --prefix frontend run build
```

## Phase 6：标准平台派生规则

目标：把“数据标准全生命周期智能化管理”真正接入 TWM 规则体系。

改动：

- 新增 `data_agent/standards_platform/derivation/strategies/spatial_policy_rule.py`
- 在 `derivation/runner.py` 注册 `to_spatial_policy_rule`
- 扩展 `std_derived_link.target_kind` 使用约定：`spatial_policy_rule`
- 前端 DeriveSubTab 展示该策略状态

验收：

- 标准发布后可派生 draft `twm_policy_rule`。
- 派生规则默认 `enabled=false`。
- 重新派生会 stale 旧规则链接，不删除历史。

建议测试：

```bash
.venv/bin/python -m pytest data_agent/standards_platform/tests/test_spatial_policy_rule_strategy.py -q
```

## Phase 7：审计报告与数据目录血缘

目标：补齐自然资源治理场景需要的可交付物。

改动：

- `presentation.py`
  - 风险图层 GeoJSON/FlatGeobuf 输出
  - 命中摘要
  - 审计报告 JSON/Markdown
- 注册输出到 `agent_data_assets`
- 写入 `agent_asset_lineage`

验收：

- 审计报告可追溯输入资产、规则版本、状态版本、命中清单和复核记录。
- data catalog 中能看到风险图层来源于哪些输入图层和规则集。

## Phase 8：方案对比

目标：从单一风险筛查扩展到多方案比较。

改动：

- `twm_scenario`、`twm_scenario_metric` 实际使用
- 支持人工上传/绘制方案变更
- 对每个方案重新 evaluate rules
- 输出约束违背率、耕地面积变化、生态红线触碰面积等指标

验收：

- baseline 与至少两个候选方案可横向比较。
- 每个方案都有独立规则命中和证据链。

## Phase 9：接入 Paper9 WorldModel v2.1

目标：在合法可行空间内进行候选方案搜索和比选。

改动：

- `world_model_adapter.py`
  - 调用 `get_world_model_v21_service().run_plan`
  - 将 TWM hard constraints 转为 Paper9 可用 mask/参数或前后处理
  - 将 Paper9 输出转为 `twm_scenario`
- `twm_evidence_item(model_output)`
  - 记录 prepared_dir、ensemble_dir、参数、summary、artifacts

验收：

- Paper9 候选方案能作为 TWM scenario 显示。
- 候选方案必须通过 TWM 规则重检。
- 违反硬约束的候选方案被标记为 infeasible，不作为推荐结论。

## 建议 PR 切片

1. **PR 1：TWM schema + repository + DSL**
2. **PR 2：semantic loader + state builder**
3. **PR 3：rule evaluator + evidence + seed rules**
4. **PR 4：REST API + API tests**
5. **PR 5：ADK toolset**
6. **PR 6：frontend MVP**
7. **PR 7：standards derivation to spatial policy rule**
8. **PR 8：audit report + catalog lineage**
9. **PR 9：scenario comparison**
10. **PR 10：WorldModel v2.1 scenario adapter**

## 当前建议的下一步

进入开发时仍建议先从 **Phase 0 + Phase 1** 建立 `S_t` 状态合同，但当前数据基础已经补齐到可以同时为 Phase 8/9 的多目标方案比选做回归夹具。也就是说，早期开发不要只停留在“图层绑定 + 规则筛查”，需要从一开始保留通往“硬约束过滤 -> 动态推演 -> 多目标优化 -> 方案比选 -> 审计解释”的数据接口。

- Phase 0/1 定义状态表征层，是路线说明的基础。
- 不会牵动前端和 Paper9，风险低。
- 做完后可以用测试数据快速验证 `MMFE -> S_t` 是否成立。
- 后续规则、证据、API、优化器和 WorldModel adapter 都能围绕稳定的 state contract 增量开发。

建议 Phase 0/1 的测试优先覆盖三组数据：

1. `twm_bishan_demo`：验证最短端到端闭环；
2. `twm_bishan_multi_admin_eval`：验证跨行政区和较大数据量；
3. `twm_one_map_village_standard_sample`：验证真实标准结构字段和标准契约派生物。

这三组数据现在均包含 `optimization/` 目录，可作为 Phase 8/9 的固定验收夹具：

- `objective_catalog.csv`：13 个多目标优化指标；
- `scenario_feasibility.csv`：硬约束过滤后的合法可行空间；
- `scenario_metrics.csv`：方案-目标指标矩阵；
- `pareto_summary.json`：只在 `legal_feasible_space` 内排序的 Pareto 摘要；
- `scenario_constraint_violations.csv`：被阻断方案的压力测试和复核依据。

后续实现 Phase 8/9 时，验收重点应包括：硬约束阻断方案不能进入推荐排名；WorldModel 参考方案必须重新经过 TWM 规则和硬约束检查；所有优化结论必须能回溯到目标版本、规则版本、状态版本、候选动作和证据索引。
