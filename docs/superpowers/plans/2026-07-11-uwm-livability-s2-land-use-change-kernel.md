# UWM 城市宜居性 S2 用地性质变更 Kernel 实施计划

> **执行要求：** 使用隔离 worktree，严格按 TDD 执行；每项任务先运行失败测试，再做最小实现并运行回归。不得清理或覆盖主工作树已有修改。

**目标：** 基于和平村、斑竹村真实规划地块和规划资源，建立可复用的 parcel/cross-scale geospatial world model kernel，并实现 S2 用地性质变更的三阶段反事实推演、API、交互界面和真实数据验证。

**架构：** 通用 kernel 负责异构状态图、动作验证、受约束状态转移、证据分层空间传播、反事实 rollout 和 claim boundary；S2 适配层负责福禄镇真实数据快照与业务编排；API 和前端只负责鉴权、输入、展示和审计，不重新计算或提升结论。

**技术栈：** Python、pytest、GeoPandas/Shapely/PyProj、FastAPI 风格路由、React/TypeScript、现有地图事件与 engine GeoJSON 机制。

**设计依据：** `docs/superpowers/specs/2026-07-11-uwm-livability-s2-land-use-change-kernel-design.md`

---

## Task 1：建立 Geospatial Kernel 基础契约

**Files:**
- Create: `data_agent/uwm/geospatial_kernel/__init__.py`
- Create: `data_agent/uwm/geospatial_kernel/contracts.py`
- Create: `data_agent/uwm/geospatial_kernel/validation.py`
- Create: `data_agent/test_uwm_geospatial_kernel_contracts.py`

- [ ] **Step 1：写失败契约测试**

覆盖节点类型、关系类型、状态阶段、证据等级、效果等级、最高 claim level 和 schema version。测试必须拒绝：未知节点/边类型、当前与规划用途混淆、缺 evidence refs、客户端可信 actor、`learned_calibrated` 无校准证据、超过 `bounded_action_conditioned_spatial_scenario` 的结论。

- [ ] **Step 2：运行 RED**

运行：

```bash
pytest -q data_agent/test_uwm_geospatial_kernel_contracts.py
```

预期因模块不存在而失败。

- [ ] **Step 3：实现最小不可变契约**

定义纯数据常量和校验函数，不引入业务村庄、HTTP 或 React 概念。节点至少支持 `parcel`、`planning_resource`、`facility`、`village_context`、`admin_context`；状态阶段固定为 `t0_current`、`t1_post_change`、`t2_neighborhood_adaptation`。

- [ ] **Step 4：运行 GREEN**

运行 focused test，确认零失败。

- [ ] **Step 5：提交任务变更**

```bash
git add data_agent/uwm/geospatial_kernel data_agent/test_uwm_geospatial_kernel_contracts.py
git commit -m "feat: define geospatial world model contracts"
```

## Task 2：实现异构状态图与确定性摘要

**Files:**
- Create: `data_agent/uwm/geospatial_kernel/state_graph.py`
- Create: `data_agent/test_uwm_geospatial_state_graph.py`

- [ ] **Step 1：写失败图测试**

构造小型 parcel/resource/facility/village/admin fixture，要求：节点 ID 唯一、边端点存在、当前/规划/候选用途分离、原始字段保留、图节点和边 canonical 排序、输入重排后 snapshot digest 不变、重复或悬空边失败。

- [ ] **Step 2：运行 RED**

```bash
pytest -q data_agent/test_uwm_geospatial_state_graph.py
```

- [ ] **Step 3：实现图构建与 canonical digest**

实现不可变输入复制、稳定排序、canonical JSON 和 SHA-256。图对象只保存结构与证据，不包含传播业务逻辑。

- [ ] **Step 4：运行 GREEN 与契约回归**

```bash
pytest -q data_agent/test_uwm_geospatial_state_graph.py data_agent/test_uwm_geospatial_kernel_contracts.py
```

- [ ] **Step 5：提交任务变更**

```bash
git add data_agent/uwm/geospatial_kernel/state_graph.py data_agent/test_uwm_geospatial_state_graph.py
git commit -m "feat: build deterministic heterogeneous state graphs"
```

## Task 3：实现受控土地用途动作与转换矩阵

**Files:**
- Create: `data_agent/uwm/geospatial_kernel/land_use_action.py`
- Create: `data_agent/uwm/geospatial_kernel/transition_matrix.py`
- Create: `data_agent/test_uwm_geospatial_land_use_action.py`

- [ ] **Step 1：写失败动作测试**

覆盖 `no_change` 和 `change_land_use_class`。要求源用途、地块 ID、快照摘要和字典版本严格一致；未知地类、无变化伪动作、摘要过期、客户端 actor、矩阵版本不符均失败。没有权威规则时状态为 `unresolved`，不得默认 `allowed`。

- [ ] **Step 2：运行 RED**

```bash
pytest -q data_agent/test_uwm_geospatial_land_use_action.py
```

- [ ] **Step 3：实现 fail-closed 动作验证**

实现 `allowed`、`conditionally_allowed`、`prohibited`、`unresolved` 四态矩阵。`allowed` 仅表示可进入技术 rollout；条件和 unresolved 强制 `human_review_required=true`。actor 作为服务层注入字段，kernel 拒绝未经绑定的可信身份声明。

- [ ] **Step 4：运行 GREEN 与契约回归**

运行 Task 1–3 tests。

- [ ] **Step 5：提交任务变更**

```bash
git add data_agent/uwm/geospatial_kernel/land_use_action.py data_agent/uwm/geospatial_kernel/transition_matrix.py data_agent/test_uwm_geospatial_land_use_action.py
git commit -m "feat: validate bounded land use actions"
```

## Task 4：实现直接状态转移

**Files:**
- Create: `data_agent/uwm/geospatial_kernel/direct_transition.py`
- Create: `data_agent/test_uwm_geospatial_direct_transition.py`

- [ ] **Step 1：写失败转移测试**

要求 `t0` 保持不可变；`no_change` 生成语义一致的 `t1`；干预只改变目标 parcel 的 candidate/effective land-use state 和直接关系；不允许人口、价格、容量、交通、建设完成或综合宜居分自动变化；输出记录 changed fields 和证据来源。

- [ ] **Step 2：运行 RED**

```bash
pytest -q data_agent/test_uwm_geospatial_direct_transition.py
```

- [ ] **Step 3：实现约束转移函数**

只接收通过验证的动作和 `t0` 图，生成新的 `t1` 图及 `direct_state_delta`；禁止原位修改。

- [ ] **Step 4：运行 GREEN 与前序回归**

运行 Task 1–4 tests。

- [ ] **Step 5：提交任务变更**

```bash
git add data_agent/uwm/geospatial_kernel/direct_transition.py data_agent/test_uwm_geospatial_direct_transition.py
git commit -m "feat: apply constrained parcel state transitions"
```

## Task 5：实现空间消息和有限多跳传播 Kernel

**Files:**
- Create: `data_agent/uwm/geospatial_kernel/spatial_message.py`
- Create: `data_agent/uwm/geospatial_kernel/spatial_propagation.py`
- Create: `data_agent/test_uwm_geospatial_spatial_propagation.py`

- [ ] **Step 1：写失败传播测试**

使用含邻接、距离、规划资源、设施、村域和行政节点的小图，要求：

- 第 0 跳仅目标地块。
- 第 1 跳仅相邻、300 米内、关联资源和设施。
- 第 2 跳只做村域及直接邻域聚合。
- 行政层只生成摘要并停止。
- 300 米外无局部消息。
- 循环路径和重复证据不累计。
- 距离带为 `proxy_distance_band`。
- 每条消息包含 raw evidence、normalization basis、support level、uncertainty、claim level 和 kernel version。
- 不产生统一宜居分、政策概率或 learned claim。

- [ ] **Step 2：运行 RED**

```bash
pytest -q data_agent/test_uwm_geospatial_spatial_propagation.py
```

- [ ] **Step 3：实现关系分派器和停止条件**

按关系类型生成分解证据：共享边界比例、距离带、相交比例、相容状态、面积结构变化、破碎化代理、受影响邻居数和未映射对象数。排序字段命名为 `review_priority`，不得命名为影响概率或收益分。

- [ ] **Step 4：运行 GREEN 与 kernel 回归**

运行全部 `test_uwm_geospatial_*`。

- [ ] **Step 5：提交任务变更**

```bash
git add data_agent/uwm/geospatial_kernel/spatial_message.py data_agent/uwm/geospatial_kernel/spatial_propagation.py data_agent/test_uwm_geospatial_spatial_propagation.py
git commit -m "feat: propagate evidence bounded spatial messages"
```

## Task 6：实现反事实 Rollout 与证据门控

**Files:**
- Create: `data_agent/uwm/geospatial_kernel/evidence_gate.py`
- Create: `data_agent/uwm/geospatial_kernel/counterfactual_rollout.py`
- Create: `data_agent/test_uwm_geospatial_counterfactual_rollout.py`

- [ ] **Step 1：写失败 rollout 测试**

要求 baseline 和 intervention 共享同一 `t0` digest；分别生成 `t1`、`t2`；可选 alternative 必须来自受控矩阵；同输入和版本重跑结果摘要一致。响应必须包含 direct/spillover delta、constraints、potential conflicts、opportunities、unavailable effects、uncertainty、review requirement 和 capped claim boundary。

- [ ] **Step 2：运行 RED**

```bash
pytest -q data_agent/test_uwm_geospatial_counterfactual_rollout.py
```

- [ ] **Step 3：实现纯 kernel orchestration**

证据门控必须将人口、价格、容量、交通、施工周期、审批概率和因果政策效果标记为 `unavailable_prediction`。不得因结果字段存在而把 unsupported head 视为 ready。

- [ ] **Step 4：运行 GREEN 与完整 kernel 回归**

```bash
pytest -q data_agent/test_uwm_geospatial_*.py
```

- [ ] **Step 5：提交任务变更**

```bash
git add data_agent/uwm/geospatial_kernel/evidence_gate.py data_agent/uwm/geospatial_kernel/counterfactual_rollout.py data_agent/test_uwm_geospatial_counterfactual_rollout.py
git commit -m "feat: run bounded geospatial counterfactuals"
```

## Task 7：构建福禄镇 S2 真实数据适配器

**Files:**
- Create: `data_agent/uwm/livability_s2/__init__.py`
- Create: `data_agent/uwm/livability_s2/fulu_adapter.py`
- Create: `data_agent/uwm/livability_s2/state_builder.py`
- Create: `data_agent/test_uwm_livability_s2_fulu_adapter.py`

- [ ] **Step 1：写失败真实适配测试**

复用 S4/S6 数据入口，不新建任意 Downloads 路径解析器。要求和平村、斑竹村真实 current/planned land-use 记录可追溯，规划资源稳定 ID 与 S6 一致，源行重排后 ID 和 digest 稳定，原始编码保留，未映射对象保留，几何和 CRS blocker 显式返回。

- [ ] **Step 2：运行 RED**

```bash
pytest -q data_agent/test_uwm_livability_s2_fulu_adapter.py
```

- [ ] **Step 3：实现数据适配和图构建输入**

复用 `traditional_livability_s6_fulu_adapter.py` 的权威源检查、稳定身份和规划资源语义；如需抽取共享纯函数，保持 S4/S6 行为与 schema 向后兼容。使用目标区域投影 CRS 计算面积、周长、邻接、共享边界和距离关系。

- [ ] **Step 4：运行 GREEN 与 S4/S6 回归**

```bash
pytest -q data_agent/test_uwm_livability_s2_fulu_adapter.py data_agent/test_traditional_livability_s4_project.py data_agent/test_traditional_livability_s6_fulu_adapter.py
```

- [ ] **Step 5：提交任务变更**

```bash
git add data_agent/uwm/livability_s2 data_agent/test_uwm_livability_s2_fulu_adapter.py data_agent/uwm/traditional_livability_s6_fulu_adapter.py
git commit -m "feat: adapt Fulu parcels for S2 world modeling"
```

## Task 8：生成版本化 S2 数据产品

**Files:**
- Create: `data_agent/uwm/livability_s2/product.py`
- Create: `scripts/build_uwm_livability_s2_fulu.py`
- Create: `data_agent/test_build_uwm_livability_s2_fulu.py`
- Generate under existing repository data convention: `data/uwm/.../livability_s2_fulu_*`

- [ ] **Step 1：写失败产品测试**

要求产品包含 parcels、planning resources、facilities、graph nodes/edges、land-use dictionary、transition matrix、evidence manifest 和 build report。验证 canonical SHA-256、源摘要、字段映射、CRS、要素/几何统计、未映射统计、关系计数、距离带和 complete/incomplete inventory 声明。

- [ ] **Step 2：运行 RED**

```bash
pytest -q data_agent/test_build_uwm_livability_s2_fulu.py
```

- [ ] **Step 3：实现产品构建器和 CLI**

输出路径遵循仓库已有 `data/uwm_public_proxy` 或相邻产品约定；先审计 `.gitignore` 和 Docker build context，再决定快照是否纳入版本控制。禁止生成合成地块。

- [ ] **Step 4：运行 GREEN 并构建真实快照**

运行产品测试和构建脚本，记录实际数量、摘要和 blockers。

- [ ] **Step 5：提交任务变更**

仅提交源代码和按仓库约定允许版本化的产品清单；不得提交无必要的大型临时文件。

## Task 9：实现 S2 场景服务

**Files:**
- Create: `data_agent/uwm/livability_s2/scenario_service.py`
- Create: `data_agent/test_uwm_livability_s2_scenario.py`

- [ ] **Step 1：写失败业务测试**

覆盖 catalog、parcel detail、validate action 和 rollout。要求服务端 actor 注入、快照摘要校验、转换矩阵版本校验、真实 parcel lookup、baseline/intervention/alternative orchestration、运行 ID 稳定审计字段和所有 unavailable effects。

- [ ] **Step 2：运行 RED**

```bash
pytest -q data_agent/test_uwm_livability_s2_scenario.py
```

- [ ] **Step 3：实现薄业务编排**

业务层不得复制 kernel 转移或传播逻辑；只加载验证后的产品、绑定身份、调用 kernel 并整理应用输出。第一版运行历史可采用现有进程内/文件快照模式，但必须明确持久性边界，不伪称生产审计数据库。

- [ ] **Step 4：运行 GREEN 与 kernel 回归**

运行 S2 scenario 和全部 geospatial kernel tests。

- [ ] **Step 5：提交任务变更**

```bash
git add data_agent/uwm/livability_s2/scenario_service.py data_agent/test_uwm_livability_s2_scenario.py
git commit -m "feat: orchestrate S2 land use scenarios"
```

## Task 10：暴露独立 S2 API

**Files:**
- Create: `data_agent/api/uwm_livability_s2_routes.py`
- Modify: relevant application route registry discovered during implementation
- Create: `data_agent/test_uwm_livability_s2_routes.py`

- [ ] **Step 1：写失败路由测试**

要求注册：

```text
GET  /api/uwm/livability/s2/catalog
GET  /api/uwm/livability/s2/parcels
GET  /api/uwm/livability/s2/parcels/{parcel_id}
POST /api/uwm/livability/s2/validate-action
POST /api/uwm/livability/s2/rollout
GET  /api/uwm/livability/s2/runs/{run_id}
```

测试鉴权、actor 覆盖、400 输入错误、404 地块/运行不存在、409 快照冲突、503 产品缺失或摘要损坏、有效请求 200，以及响应 claim boundary 不可提升。

- [ ] **Step 2：运行 RED**

```bash
pytest -q data_agent/test_uwm_livability_s2_routes.py
```

- [ ] **Step 3：实现薄 API**

沿用现有认证和异常映射模式，耗时加载/rollout 使用 `asyncio.to_thread`。API 不访问 Downloads 原始源，不复制数据构建逻辑，不接受客户端可信 actor。

- [ ] **Step 4：运行 GREEN 与路由回归**

```bash
pytest -q data_agent/test_uwm_livability_s2_routes.py data_agent/test_uwm_traditional_livability_routes.py data_agent/test_uwm_livability_decision_routes.py
```

- [ ] **Step 5：提交任务变更**

提交独立路由、注册点和测试。

## Task 11：实现 UWM S2 交互面板

**Files:**
- Create: `frontend/src/components/datapanel/UwmLivabilityS2Panel.tsx`
- Modify: UWM livability parent tab discovered during implementation
- Modify: map integration component only where required
- Create or modify: focused frontend contract test

- [ ] **Step 1：写失败前端契约测试**

要求界面存在“S2 用地性质变更推演”、村庄、真实地块、当前用途、规划用途、目标用途、转换状态、行动理由、快照信息、人工确认、t0/t1/t2、基线/干预差异、直接变化、空间传播、村域聚合、不可预测效果、不确定性和证据链。

禁止字符串或行为：审批通过、确定改善、政策成功率、房价增幅、容量增量、步行圈、统一宜居性得分、客户端硬编码 actor。

- [ ] **Step 2：运行 RED**

运行 focused frontend contract test，预期面板和注册缺失。

- [ ] **Step 3：实现三栏交互**

左侧配置动作，中部通过现有 engine GeoJSON/map event 机制展示目标地块、邻接、距离带、资源、设施和传播边，右侧按证据等级展示结果。地图不自行推导影响；只消费 API 返回图层和状态。

- [ ] **Step 4：运行 GREEN 与前端构建**

运行 frontend contract tests 和现有前端 build。不得修改当前 `WorldModelV11Tab.tsx` 中与 S2 无关的既存工作；若注册点有并发改动，做最小兼容合并。

- [ ] **Step 5：提交任务变更**

提交 S2 面板、最小注册修改和契约测试。

## Task 12：完成真实数据双村验收与验证报告

**Files:**
- Create: `scripts/verify_uwm_livability_s2_fulu.py`
- Create: `data_agent/test_verify_uwm_livability_s2_fulu.py`
- Create: `docs/reports/uwm_livability_s2_fulu_verification_2026-07-11.md`

- [ ] **Step 1：写失败验收测试**

和平村、斑竹村分别自动选择：有邻接地块的真实 parcel、关联规划资源的 parcel、转换状态 unresolved 的 parcel；若权威矩阵存在条件转换，再增加该案例。测试要求同快照重跑 digest 一致、传播路径可追溯、未映射对象保留、300 米停止、行政摘要停止和 unsupported effects 全部关闭。

- [ ] **Step 2：运行 RED**

```bash
pytest -q data_agent/test_verify_uwm_livability_s2_fulu.py
```

- [ ] **Step 3：实现验证脚本并运行真实案例**

报告记录真实 parcel/resource 数量、节点/边数量、距离关系、转换状态、每阶段差异、消息证据、运行时间、摘要、blockers、claim boundary 和不实现项。失败案例必须保留为 blocker，不能通过降低断言掩盖。

- [ ] **Step 4：运行最终验证**

按由窄到宽顺序运行：

```bash
pytest -q data_agent/test_uwm_geospatial_*.py
pytest -q data_agent/test_uwm_livability_s2_*.py data_agent/test_build_uwm_livability_s2_fulu.py data_agent/test_verify_uwm_livability_s2_fulu.py
pytest -q data_agent/test_uwm_traditional_livability_*.py data_agent/test_traditional_livability_s4*.py data_agent/test_traditional_livability_s6*.py
```

随后运行前端契约测试与 production build。若完整项目测试可在合理时间内运行，再执行完整 pytest；只报告实际运行结果。

- [ ] **Step 5：审查结论边界**

全文搜索并人工检查 API、前端、报告中不存在未经限定的审批、因果、覆盖率、容量、人口、房价、步行可达性或宜居性提升结论。

- [ ] **Step 6：提交验证变更**

```bash
git add scripts/verify_uwm_livability_s2_fulu.py data_agent/test_verify_uwm_livability_s2_fulu.py docs/reports/uwm_livability_s2_fulu_verification_2026-07-11.md
git commit -m "test: verify Fulu S2 world model scenarios"
```

## Task 13：双阶段代码审查与主分支集成

- [ ] **Step 1：规格符合性审查**

逐条核对书面规格和完成标准，重点检查 kernel 是否真正独立、是否存在应用层重算、是否把 bounded proxy 伪装成 learned effect、是否遗漏 unavailable heads。

- [ ] **Step 2：代码质量审查**

检查确定性、不可变状态、空间复杂度、几何异常、内存边界、错误映射、前端状态竞态、重复逻辑和向后兼容。

- [ ] **Step 3：修复审查问题并重新验证**

每项修复先增加或更新失败测试，再修改实现。重新运行受影响测试和最终验证集合。

- [ ] **Step 4：安全集成**

确认主工作树既有未提交文件没有被覆盖；将隔离 worktree 的 S2 commits 集成到 `feat/v12-extensible-platform`。解决冲突时保留主工作树已有 Paper58/TWM 工作，只做 S2 所需最小适配。

- [ ] **Step 5：集成后验证**

在主分支重新运行 S2 backend tests、相关传统宜居性回归、前端契约和 build，并生成最终 `git status --short` 供审计。

---

## 实施约束

- 不修改或重定义现有行政单元 `spatial_spillover_kernel.py` 的业务语义。
- 不把静态 GIS 差异重复包装成第二个传统页面。
- 不引入未经证据校准的统一权重或综合影响分。
- 不将 50/150/300 米距离带描述为步行圈或法定范围。
- 不从行政单元代理指标反推地块政策效果。
- 不因缺数据而生成默认人口、容量、价格、交通或审批结果。
- 不清理、reset 或覆盖主工作树现有未提交修改。
- 每个任务结束后保持 focused tests 通过；最终结论只基于实际运行证据。

