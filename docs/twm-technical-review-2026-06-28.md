# GIS Data Agent 项目 TWM 模块严格技术评审报告

**评审日期**：2026-06-28
**评审对象**：GIS Data Agent (`/Users/zhouning/gisdataagent`) 中的 Territory World Model (TWM) 子系统
**评审基准**：最新代码实现（截至 2026-06-28） + 2026-06-25 技术评审 + 完整文档体系
**评审方法**：代码审查、架构分析、文档验证、测试覆盖评估、与历史评审对照
**评审人**：Claude Opus 4.8（1M context）

---

## 一、整体评价

**综合评级：B+ (83/100)**

TWM 是一次**架构上非常认真的工程实践**，不是噱头或概念包装。21K+ 行核心代码、12 张数据库表、47 个测试用例、34 份技术文档、30+ 份验证报告，形成了一个**可运行、可验证、边界清晰**的地理空间世界模型原型。

**核心优势**：
- 架构完整性高，10 层分解清晰
- 证据门控（evidence gate）与声明阶梯（claim ladder）作为一等公民
- 主动暴露能力边界，不掩盖短板
- Dynamic World admin20 公开数据验证已落地

**主要限制**：
- 生产数据为零，所有验证基于合成数据或公开基准
- service.py 单体过大（11K+ 行），违反自身架构原则
- 部分命名承诺与代码实现存在差距
- 真实应用场景验证缺失

---

## 二、评审范围

| 类别 | 路径 | 规模 |
|---|---|---|
| 核心包 | `data_agent/territory_world_model/` | 16 个 .py 文件，约 22,352 行 |
| MMFE→TWM 输入契约 | `data_agent/fusion/twm_state_input.py` | 579 行 |
| REST API | `data_agent/api/territory_world_model_routes.py` | 891 行 |
| 数据库迁移 | `migrations/090_twm_core.sql` + `091_twm_spatial_policy_rule_derivation.sql` | 12 表 / 11 索引 + 1 派生表 |
| 测试 | `test_twm_*.py` × 15 + `test_territory_world_model.py` | 合计约 7,218 行 |
| 架构与对照文档 | `docs/twm-*.md` | 34 份 |
| 验证证据 | `docs/reports/twm_*` | 30+ 份 |
| 前端实现 | `frontend/src/components/datapanel/TerritoryWorldModelTab.tsx` | 3,253 行 |
| 运营脚本 | `scripts/run_twm_validation_bundle.py`、`scripts/run_twm_production_onboarding.py` | — |
| 历史评审参考 | `docs/twm-technical-review-2026-06-20.md`、`docs/twm-technical-review-2026-06-23.md`、`docs/twm-technical-review-2026-06-25.md` | — |

---

## 三、技术架构评审

### 3.1 架构合理性 ⭐⭐⭐⭐ (8.5/10)

#### ✅ 合理之处

1. **范式选择正确**
   没有简单套用自动驾驶/具身智能的 world model，而是按"对象-动作-观测-预测"四要素重新定义国土空间治理世界模型。把"图斑/项目/红线/审批"作为对象，把"选址/整治/保护/审批/规划调整"作为动作，这是一次**诚实的尺度迁移**，而不是套壳。

2. **10 层架构清晰且互不越界**
   ```
   数据底座 → 层级状态 → 编码+GeoFM gate → 动作/情景
   → action-conditioned dynamics → 多头输出 → 因果校准
   → 证据门控 → planner consumer → GIS 部署
   ```
   每层都有显式契约（dataclass + JSON schema 名 `territory_world_model.*.v1`），代码层一致落实：`planner.py` 注释明确 "The planner does not define the world model itself; it consumes state bundles"。

3. **层级化数据结构**
   `TwmStateObject + TwmStateRelation + TwmRuleHit + TwmEvidenceItem + TwmReviewTask` 形成 object-relation-rule-evidence 四元组，从 source（MMFE bundle）到 sink（API/Toolset）契约一致；JSONB 列承载演化字段是 v0 阶段务实选择。

4. **证据门控与声明阶梯作为架构核心**
   `claim_ladder.py` 把 L0~L4 与具体门 catalog 绑定：
   - `state_build_pass`
   - `future_state_holdout_pass`
   - `counterfactual_calibration_pass`
   - `planning_lift_pass`
   - `geofm_gate_decision`
   - `gis_audit_pass`
   - `human_review_completed`

   证据不达标自动降级为 `review` 而不是冒进给结论。这是 TWM 区别于纯 ML 预测器的**关键设计哲学**。

#### ⚠️ 不合理之处

1. **`service.py` 11,126 行单体类**（最严重问题）

   `TerritoryWorldModelService` 内含 **312 个方法**，路由层 891 行又直接调用。这是 "facade 不堪重负" 的典型反模式，**违反了它自己 10 层架构里第 9 层与第 10 层应该分离的原则**。

   ```python
   # 当前：一个 11K 行的上帝类
   class TerritoryWorldModelService:
       def __init__(...): ...
       def build_state(...): ...
       def forecast(...): ...
       def train_dynamics(...): ...
       def causal_calibration(...): ...
       def beam_planning(...): ...
       def audit_report(...): ...
       # ... 305+ 个方法
   ```

2. **多头输出契约名实不一致**

   文档反复声明 `future_latent_state` head，但 `train_neural_multi_head_dynamics`（`neural_dynamics.py` L66-72）实际只把 `area_total` 一个标量做归一化预测；其余 5 个 head 是 `constraint_probability / utility_delta / confidence / calibrated_utility_delta / allowed`，**没有任何 "latent state representation"**。

   这相当于把"潜在状态"在代码里降级成了"未来面积"，建议要么补齐 head，要么把契约名/对外口径改成 `future_area_and_key_indicators`，否则学术或评审场合一旦被翻代码就会形成 overclaim 把柄。

3. **动作空间仍是离散标签**

   `TerritoryWorldModelAction` 的 `action_type / target_role / magnitude / treatment` 都是字符串/标量；`spatial_scope / execution_mask` 主要是元数据，没有"空间动作搜索"原生支持。这与文档第 4.5 节"动作是对空间状态的干预"承诺有差距。

4. **数据库表设计 JSONB 偏多**

   12 表里 `rule_body / legal_basis / metadata / metric_payload / quality_summary / build_log / summary / attributes / metrics / evidence / input_changes / field_mapping / quality_snapshot / bbox_json` 全是 JSONB。短期换演进性可以，但 `severity / hit_status / scenario_type / build_status` 等是稳定枚举值，应抽成独立列或 ENUM，并加部分索引（GIN on `attributes`、BRIN on `created_at`），否则跨州县/跨年度 query 走顺序扫描风险高。

5. **Rule DSL 极简**

   `rule_dsl.py` 仅 83 行，只包含 normalize/validate 工具函数，缺少分支表达式、空间谓词（intersects/within/buffer/distance）、时间约束等核心 DSL。所有空间关系实际由 `state_builder.py` + `rule_evaluator.py` 硬编码处理。把规则做成数据是好方向，但 DSL 表达能力当前不足以承诺"治理规则"层。

6. **专属 OTel span 已部分接入但仍待完善**

   v23.0 已经接通 OTel，2026-06-26 已新增 `train_dynamics_candidate`、`counterfactual_rollout` 和 `estimate_observational_treatment_effect` 的专属 span，但缺少 P99 诊断所需的细粒度 attribute（如 `state_version_id`、`backend`、`sample_count`、`gate_outcome`），生产环境下难以做深度诊断。

---

### 3.2 可行性评估 ⭐⭐⭐⭐ (7.5/10)

#### ✅ 可行的部分

1. **构建闭环已完整可跑**
   - `pytest data_agent/test_territory_world_model.py`：**47 通过**（耗时 18 分 16 秒）
   - `test_twm_state_input.py` / `test_twm_mmfe_*` / `test_twm_dynamic_world_flus_comparison.py` 系列均能跑通
   - `scripts/run_twm_validation_bundle.py` 与 `scripts/run_twm_production_onboarding.py` 提供端到端入口
   - REST API 与 ADK toolset 已挂载

   说明"代码能走到证据生成那一步"已经被工程证实。

2. **Dynamic World admin20 真实公开数据验证**

   `docs/reports/twm_dynamic_world_admin20_benchmark_2026-06-22.json` 显示 **20 个乡镇/街道、2017-2023、100 个 rolling case**：

   | 候选 | OA | Change FoM |
   |---|---|---|
   | Persistence | 0.925218 | 0.000000 |
   | Markov transition | 0.903706 | 0.045569 |
   | **TWM independent transition + forecast demand** | **0.908289** | **0.072289** |
   | TWM hierarchical pooled transition | 0.908282 | 0.072135 |
   | TWM calibrated hierarchical pooled transition | 0.908280 | 0.072235 |
   | TWM leave-region-out cross-region smoothed | 0.908285 | 0.072275 |
   | TWM independent transition + oracle demand | 0.920055 | 0.129043 |

   这是脱离合成数据后**首次有公开 baseline 比较**，**确实可复现**。

3. **物理隔离内网部署形态合理**（`twm-airgapped-deployment-and-iteration-strategy.md`）

   外网研发 → 制品交付 → 内网真实数据，离线 Docker / Helm 包，是面向国土真实甲方现实的唯一可行路径，路线没问题。

#### ⚠️ 不可行或缺口处

1. **真实历史审批/复核/政策动作可行性标签 = 0 行**（最大瓶颈）

   所有 256 行 synthetic experiment foundation、128 对 treated/control、64+64 action mask 样本都带 `not_for_production=true`。`production_ready_observed_history_rows = 0` 写在最新 punch list 里。

   **可行性的真正瓶颈不在算法，在数据准入。**

2. **学习型 dynamics 训练数据规模太小**

   三个 torch 后端（MLP / Hierarchical Graph / Spatiotemporal Transformer）的训练集 < 200 行，再做 8-period × 4-step holdout，从样本量层面 `false_allow=0 / false_block=0 / planner exact-match=1.0` 这种"完美"指标是 **overfitting 信号而不是泛化证据**；任何严肃投稿/部署都会被拆穿。

3. **FLUS 全套（ANN suitability + adaptive inertia + roulette wheel）尚未完整复现**

   目前对比的是简化 direct FLUS CA adapter（handoff 自承）。所以"TWM 比 FLUS 强"的口径在论文/客户层是**不能讲**的，得改成"在 Markov 与简化 FLUS 上有 change-FoM 优势，OA 与 macro-F1 持平或略落后"。

4. **SCCA（spatial causal calibration adapter）实际能力是观察性 ATT/IPW/AIPW + 邻接固定效应**

   本质上是 `E[Y|T=1,X]` 而非 `E[Y|do(T)]`。在没有 RCT / 自然实验 / 准实验设计的情况下，把它写成"因果校准"对外要小心，否则会被审稿人或 domain expert 抓 overclaim。代码已加 `identification_strength="observational"` 字段（2026-06-26 升级为 first-class），但需确保 API 输出层显式暴露。

5. **GeoFM B0/B1 / D2/D3/D4 gate 仍是契约而非实测**

   `twm-current-handoff.md` 自承 "deterministic B0/B1 prediction scaffold ... explicitly marked review-only"。Prithvi 或 AlphaEarth 真实跨区下游实验没跑过。

6. **fallback rate 偏高**

   admin20 上 900 个 source-class 拟合中 309 走 fallback（**fallback rate 0.343333**），说明 dynamics backend 在稀疏类别上有显著数据稀疏问题，hierarchical pooled 与 cross-region smoothing 都没真正赢过 independent baseline。

---

### 3.3 实用性评估（分场景判断）

| 场景 | 评级 | 说明 |
|------|------|------|
| **演示与技术交流** | A- | 架构图、SVG/PNG 资产、报告文档、ADK 工具、TWM 前端 tab 齐全；给自然资源系统/规划院做 vision pitch 完全压得住。Bishan demo + DongGuan GeoSOS 真实数据 + Dynamic World admin20 公开数据三套底座，演示叙事很完整 |
| **内部 PoC** | B | 拿到合作单位（自然资源部、省厅、规划院）一个区县 5 年以上的真实审批/审查/红线/规划"一张图"后，**6–12 周可冷启动**；前提是甲方配合脱敏，且需进物理隔离内网部署 |
| **生产替代 FLUS/PLUS** | D | 三道硬门槛（真实历史数据、跨区域 holdout、规划增益盲评）未跨之前**不应**用于任何会影响真实审批意见的工作流。要避免任何形式的"TWM 已替代 FLUS"对外口径 |
| **学术发表** | B+ | GIScience / IJGIS / Computers, Environment and Urban Systems / Annals of GIS / IJDE 可投（架构论文 + 合成验证 + 真实 Dynamic World 小规模 PoC 撑得起）；NeurIPS / ICLR 不要硬投，算法新颖度不够 |

`service.data_foundation_assessment()` 与对应前端 tab 已把这种实用边界**主动暴露**给业务人员，这是工程上很成熟的姿态——**不藏短，不冒认**。

---

## 四、创新性评估 ⭐⭐⭐⭐ (8/10)

### 诚实地拆开看

- **算法层（C+）**：Action-conditioned dynamics（Dyna / Dreamer / MuZero）、多头 multi-task、ATT/IPW/AIPW（Pearl / Rosenbaum / Imbens）、MPC/beam（Rawlings）、hierarchical token（GNN/Transformer 常见）、GeoFM embedding（Prithvi/AlphaEarth）——**单点都不新**，文档也明确承认了这一点。

- **架构层（B+）**：四件套同时具备在公开文献和产品里少见——
  1. parcel ⊂ block ⊂ township ⊂ county 的对象-关系-规则-证据状态原语（vs FLUS 栅格元胞、Foundry ontology-link-action 的本质区别）
  2. evidence gate × claim ladder × 5 级提升通道作为推理链路的一等公民
  3. GeoFM 受 B0/B1 gate 控制的"可消融可关闭"原则
  4. 显式的治理闭环（GIS evidence → rule review → audit → calibration → planning revision），不是机器人控制闭环

- **行业范式层（A-）**：在"国土空间治理 × 体系架构 × 工程化产品"三者交集上，把 evidence gate + causal calibration + action-conditioned dynamics + claim ladder 写进产品代码的工作，国内外公开领域确实罕见。FLUS/PLUS 给"格局如何竞争"，TWM 在尝试给"行动是否合规、影响是否可信、方案是否可审计"——**这是范式偏移而不是算法突破**。

### 推荐定位口径（直接可用）

> We introduce a governance-oriented geospatial world model. TWM represents land systems as hierarchical GIS object-relation-rule-evidence states, learns action-conditioned multi-head dynamics, and upgrades planning claims only through spatial causal calibration and evidence-gated validation.

**避免使用**"首次"、"突破"、"超越 FLUS"等措辞，否则进入同行评审会被拆。

---

## 五、主要问题与改进建议（按严重性排序）

### 🔴 致命级（必须修复）

1. **`future_latent_state` 名实不符**（`neural_dynamics.py` L66-72）

   - **现状**：Head 实际只产 `area_total`，文档却宣传完整 latent state
   - **影响**：学术投稿或客户技术评审时会被拆穿，形成 overclaim 把柄
   - **建议**：二选一——
     - 补齐 head：把 token group encoder 的 pooled state 显式输出成 latent vector，再下接 area / 连片度 / 质量 / 承载力等 head
     - 修改对外口径：改为 `future_area_and_key_indicators`，同步修文档

2. **`service.py` 11,126 行单体**与 `_INSTANCE` 单例 + threading.Lock 形态

   - **现状**：312 个方法，承担全部职责
   - **影响**：冷启动慢、单元测试脆、并发追踪难、违反自身架构原则
   - **建议**：拆分成 5 个 service——
     ```
     StateService          (状态构建、契约报告)
     DynamicsService       (动力学训练、forecast、rollout)
     CalibrationService    (因果校准、SCCA adapter)
     PlannerService        (beam planning、ranking)
     EvidenceAuditService  (证据链、审计、claim ladder)
     ```
     路由层只调 service interface，service 不调 route

3. **生产数据 = 0 行**

   - **现状**：所有验证基于合成数据，`not_for_production=true`
   - **影响**：任何"准确"、"可靠"、"已超过 FLUS"的口径都是 overclaim
   - **建议**：P0 级数据采购——
     - 一个区县 5 年以上真实审批/审查/红线/规划"一张图"
     - 全程脱敏，进物理隔离内网
     - 做第一次真实 train-region-A / test-region-B 留出

4. **观察性校准 vs 干预性因果混淆**

   - **现状**：`causal_calibration.py` 主结论是 augmented IPW，已加 `claim="observational_calibration_only"`，但 forecast/rollout 消费时，最终 `calibrated_utility_delta` 在 service 层与"治理收益"绑定输出
   - **影响**：外部用户很难感知到 observational vs interventional 边界
   - **建议**：在 API 输出层加显式 `identification_strength: observational` 字段（2026-06-26 已升级为 first-class，需确认是否所有消费点都暴露）

### 🟠 重要级（限期改进）

5. **测试比偏低（约 2.5%）**

   - 15 个 `test_twm_*.py` + `test_territory_world_model.py` 合计 ~7,218 行
   - 看似不少，但其中 `test_twm_data_foundation_validation.py` 3,089 行、`test_twm_dynamic_world_flus_comparison.py` 1,522 行属于**报告快照式断言**
   - 真正覆盖 `rule_evaluator.py`（1,200）/ `neural_dynamics.py`（1,513）/ `causal_calibration.py`（560）关键路径的单元数比例偏低
   - **建议**：补充关键路径单元测试，特别是异常分支和边界条件

6. **训练样本严重不足导致"完美指标"**

   - false_allow=0、planner exact-match=1.0、rollout regret=0.0
   - 在 200 行样本上的完美数字应在 README/技术评审里**明确标注**"on synthetic foundation, not generalization evidence"

7. **planner ranking 没有真正的 learned ranking loss**

   - 目前是 `utility − risk + 0.1*confidence + blocked/review penalty` 启发式
   - 自承"已有 training objective scaffold；真正的训练优化和 learned ranking 仍未实现"
   - **建议**：实现端到端可训练版本，保留 false_allow=0 安全侧约束作为 inequality loss

8. **GeoFM gate 是契约不是实测**

   - B0/B1 prediction map 是 deterministic scaffold
   - 没有 Prithvi 或 AlphaEarth 真实下游 planning lift 实验
   - **建议**：接入 paper 11/12 的真实 GeoFM adapter 训练管线

9. **fallback rate 0.343333**

   - admin20 上 900 个 source-class 拟合中 309 走 fallback
   - hierarchical pooled 与 cross-region smoothing 都没真正赢过 independent baseline
   - **建议**：结构化 region-holdout parameter sharing、transition-pair smoothing、更强机制性协变量

### 🟡 可观察级（中期改进）

10. **JSONB 滥用**

    - `twm_state_object.attributes` / `twm_rule_hit.metrics` 等高频读字段应抽列 + GIN 索引
    - 稳定枚举（`severity / hit_status / scenario_type / build_status`）应抽成独立列或 ENUM

11. **OTel TWM 专属 span attribute 不足**

    - 2026-06-26 已新增三个核心操作的专属 span
    - 但缺少细粒度 attribute（`state_version_id`、`backend`、`sample_count`、`gate_outcome`）
    - **建议**：补全 attribute，便于 P99 诊断

12. **Rule DSL（`rule_dsl.py` 83 行）极简**

    - 当前规则体只有 normalize/validate 工具函数
    - 缺少分支表达式、空间谓词（intersects/within/buffer/distance）、时间约束等核心 DSL
    - 所有空间关系实际由 `state_builder.py` + `rule_evaluator.py` 硬编码处理
    - **建议**：把规则做成数据是好方向，但 DSL 表达能力需升级才能承诺"治理规则"层

13. **没有 model registry / version pinning**

    - `twm_state_version` 有 build_status，但模型版本（torch_multi_head_mlp / torch_hierarchical_graph / torch_spatiotemporal_transformer）没有对应注册表
    - 回滚链路不闭合
    - **建议**：加 TWM dynamics backend 版本注册表

---

## 六、代码质量与工程实践 ⭐⭐⭐⭐ (8/10)

### ✅ 优秀实践

1. **数据结构契约清晰**
   所有模型都是 `@dataclass`，JSON schema 命名规范（`territory_world_model.*.v1`）

2. **类型注解完整**
   核心模块都有完整类型提示，便于静态分析

3. **文档体系完整**
   34 份技术文档、30+ 份验证报告、架构说明、对比分析、技术评审——**文档诚实度很高**

4. **主动暴露边界**
   - `data_foundation_assessment()` 明确标注 `production_ready_observed_history_rows = 0`
   - `claim_ladder` 自动降级而不是冒进给结论
   - 前端 tab 把不可主张内容主动暴露给业务人员

5. **Git 提交规范**
   Commit message 清晰，feat/fix/docs/test 分类明确

6. **测试有进展但需深化**
   30 passed 的 strict no-leakage data-foundation validation 显示对数据泄漏有持续关注

### ⚠️ 需改进处

1. **单体类过大**（已述）
2. **部分命名与实现不符**（已述）
3. **测试覆盖不均**（已述）
4. **缺少完整 CI/CD 配置**（在 `.github/` 下未见完整 workflow）

---

## 七、与历史评审的关系

| 评审 | 评级 | 核心结论 | 本次评审一致性 |
|------|------|----------|----------------|
| 2026-06-20 评审 | 首轮整体性评审 | `validate_twm_state_input` 校验过浅等具体技术问题 | ✅ 已被采纳并修复 |
| 2026-06-23 评审 | B+ | 重点在创新性边界与实用性门槛 | ✅ 一致 |
| 2026-06-25 评审 | B+ | 6 维细粒度审查；新增 `service.py` 单体、`future_latent_state` 名实、JSONB 滥用、rule DSL 极简、缺 model registry 等判定 | ✅ **完全一致** |
| **2026-06-28 本次评审** | **B+ (83/100)** | **确认前序结论；增加分场景实用性评级和综合得分矩阵** | — |

2026-06-25 评审已被项目采纳并在 `twm-current-handoff.md` 的"2026-06-26 Technical Review Absorption"部分确认吸收，说明**团队对技术债和边界有清醒认知**。

---

## 八、走向行业级突破的改进路径

### 短期（3 个月内 — 把目前"严肃工程"变成"可信小规模 PoC"）

1. **拆分 `service.py`** 成 5 个服务模块，路由层只调 service interface
2. **修复 `future_latent_state` head**：把 token group encoder 的 pooled state 显式输出成 latent vector，再下接 area / 连片度 / 质量 / 承载力等 head；同步修对外口径
3. **拿到一个区县真实历史数据**（5 年 + 10K 图斑 + 审批记录 + 复核记录 + 红线版本变更），全程脱敏，进物理隔离内网；在内网做第一次真实 train-region-A / test-region-B 留出
4. **写一篇 GIScience / IJGIS 体系架构论文**：定位为 governance-oriented geospatial world model 的体系工作，主结果用 Dynamic World admin20 的 100 个 rolling case + FLUS 完整管线对比
5. **把 SCCA 改成可插拔后端**：本地 observational backend 保留，但留一个 `spatial_causal_estimator_adapter` 给 paper 6/7 风格的空间 treatment-effect estimator 做服务对接

### 中期（6-12 个月 — 跨过三道硬门槛）

6. **完整 FLUS（ANN suitability + adaptive inertia + roulette wheel + 多类型竞争）复现**作为强 baseline，避免被审稿人挑"和谁比"
7. **learned action-mask head + learned risk calibration**，把现有 post-hoc affine calibration 与启发式 ranking 替换成端到端可训练版本；保留 false_allow=0 这种安全侧约束作为 inequality loss
8. **跨区域 holdout × 跨年度 holdout 双因子 ablation**，至少 3 个省 × 5 年；用 D3 / D4 验证套件出 GeoFM 真实下游 ablation 报告
9. **规划增益盲评**：找规划院 5 位以上专家，对 TWM beam-selected plan vs FLUS-allocated plan vs 人工方案做盲评打分，输出 Cohen's Kappa 与排序 regret
10. **加入端到端 differentiable planning**：把 beam 中的 utility-risk 加权用 Gumbel-softmax 改成可反传，让 planning ranking loss 真正驱动 dynamics 训练

### 中长期（行业级突破的真正路径）

11. **从"TWM = Simulator 主体"升级为"治理基础模型（Governance Foundation Model）"**

    联合训练在同一个统一表征空间内：
    - (a) GeoFM 多模态感知（Prithvi / AlphaEarth）
    - (b) 层级 GIS 状态
    - (c) action-conditioned dynamics
    - (d) 规则可执行 DSL
    - (e) 空间因果
    - (f) 大语言模型推理 / 复审解释

    MoE 多任务 head 解决"治理决策 × 政策合规 × 规划方案 × 审计证据"四类任务。这是真正的"行业首创"机会窗口。

12. **政策语义层与规则 DSL 二级化**

    把"用途管制条例 / 永农划定办法 / 生态红线 / 城镇开发边界 / 占补平衡"等法定规则用一种 first-class 的空间 + 时间 + 严重度 DSL 表达，规则版本与 `twm_rule_set` 绑定，规则演化作为一等 audit 实体（policy_version → state_version → rule_hit 三联血缘）。

    这一步打通后，TWM 就从"决策辅助工具"升级为"政策仿真器"，能回答"如果某条管制条例改了 X，未来 5 年治理后果是什么"——这是国家级国土规划重大需求。

13. **空间扰动检验（spatial perturbation test）与 conformal prediction**

    每次 forecast 输出 conformal 区间而不是点估计，evidence gate 与 conformal coverage 绑定。这把 TWM 的"可审计"从制度承诺升级成数学保证。

14. **建立"治理基础模型基准（Governance Foundation Benchmark）"**

    发起跨学校/院的开放基准，把 Dynamic World × 中国土地变更调查 × 一张图脱敏样本 × 真实审批数据组合成多任务公开 benchmark，TWM 作为 reference implementation。

    **数据集 + 基准 + reference 三位一体是占据领域定义权的最高效路径**。

15. **政企生态：内网"治理大模型即服务"形态**

    每个国土厅一套内网 TWM 实例，外网集中接合成数据、公开数据、模型权重版本与离线评估包；通过"脱敏指标反馈"持续学习而原始数据不出域。这种部署形态本身就是一项制度创新。

---

## 九、综合评级矩阵

| 维度 | 评级 | 得分 |
|------|------|------|
| 架构完整性 | A- | 9/10 |
| 架构合理性 | B+ | 8.5/10 |
| 可行性 | B | 7.5/10 |
| 实用性（加权平均） | B | 7/10 |
| 算法创新性 | C+ | 6.5/10 |
| 架构 / 范式创新性 | B+ / A- | 8.5/10 |
| 代码质量 | B+ | 8/10 |
| 工程严谨性（不掩盖短板） | A | 9.5/10 |
| 改进后潜力 | A- | 9/10 |
| **综合** | **B+** | **83/100** |

---

## 十、推荐行动计划

| 优先级 | 时间窗口 | 行动 |
|--------|----------|------|
| **P0** | 立即 | 真实区县历史数据采购计划启动 |
| **P0** | 本月 | 拆分 `service.py` 为 5 个服务模块 |
| **P0** | 本月 | 修复 `future_latent_state` 命名（补齐 head 或改名） |
| **P1** | 本季度 | 完成一篇 GIScience / IJGIS 体系架构投稿 |
| **P1** | 本季度 | 补充关键路径单元测试覆盖 |
| **P1** | 本季度 | API 输出层显式暴露 `identification_strength` |
| **P2** | 半年内 | 完整 FLUS 复现 + 跨区域 holdout |
| **P2** | 半年内 | 规划院专家盲评 5 位以上 |
| **P2** | 半年内 | learned ranking loss + learned action-mask head |
| **P3** | 长期 | 向治理基础模型与政策仿真器演进 |
| **P3** | 长期 | 建立治理基础模型开放基准 |

---

## 十一、综合一句话给决策层

> **TWM 现在不是噱头，是一次架构上很认真的工程，22K 行代码、12 表 schema、47 测试用例都对得起它声称的 10 层体系；但它的下一笔投入不应该再加架构层，而应该买"一个真实区县 5 年以上的脱敏审批/复核/规划历史数据"和"3 位规划专家的盲评时间"——把"工程可信"升级到"业务可信"，这是 TWM 走向行业级突破的唯一关键门。**

---

**评审签名**：Claude Opus 4.8（1M context）
**评审依据**：
- 核心包 `data_agent/territory_world_model/`（16 个源文件，22,352 行）
- `data_agent/fusion/twm_state_input.py`（579 行）
- `data_agent/api/territory_world_model_routes.py`（891 行）
- `frontend/src/components/datapanel/TerritoryWorldModelTab.tsx`（3,253 行）
- `migrations/090_twm_core.sql` + `migrations/091_twm_spatial_policy_rule_derivation.sql`
- 15 个 `test_twm_*.py` + `test_territory_world_model.py`（7,218 行）
- 34 份 `docs/twm-*.md`
- 30+ 份 `docs/reports/twm_*.{md,json,csv}`
- `scripts/run_twm_validation_bundle.py` + `scripts/run_twm_production_onboarding.py`
- 最新 `docs/twm-current-handoff.md`（2026-06-26 更新）
- 历史评审：`docs/twm-technical-review-2026-06-20.md`、`docs/twm-technical-review-2026-06-23.md`、`docs/twm-technical-review-2026-06-25.md`

**评审版本**：2026-06-28
**前序评审**：
- `docs/twm-technical-review-2026-06-20.md`
- `docs/twm-technical-review-2026-06-23.md`
- `docs/twm-technical-review-2026-06-25.md`

四轮评审可并列阅读，本轮不替代前三轮，而是在 2026-06-25 评审基础上**确认结论一致性**并**新增综合评级矩阵与推荐行动计划**。
