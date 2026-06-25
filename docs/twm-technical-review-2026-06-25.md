# TWM 模块严格技术评审（2026-06-25）

**评审对象**：GIS Data Agent (D:\adk) 中的 Territory World Model（TWM）子系统
**评审日期**：2026-06-25
**评审人**：Claude Opus 4.8（1M context）
**评审方法**：阅读核心代码 + 数据库迁移 + 全部 TWM 文档 + 测试代码 + 验证报告 + 最新 handoff

## 评审范围

| 类别 | 路径 | 规模 |
|---|---|---|
| 核心包 | `data_agent/territory_world_model/` | 16 个 .py，约 13.0 K 行 |
| MMFE→TWM 输入契约 | `data_agent/fusion/twm_state_input.py` | 579 行 |
| REST API | `data_agent/api/territory_world_model_routes.py` | 871 行 |
| 数据库迁移 | `migrations/090_twm_core.sql` + `091_twm_spatial_policy_rule_derivation.sql` | 12 表 / 11 索引 + 1 派生表 |
| 测试 | `test_twm_*.py` × 14 + `test_territory_world_model.py` | 合计约 11 K 行 |
| 架构与对照文档 | `docs/twm-*.md` | 34 份 |
| 验证证据 | `docs/reports/twm_*` | 30+ 份 |
| 运营脚本 | `scripts/run_twm_validation_bundle.py`、`scripts/run_twm_production_onboarding.py` | — |
| 上轮评审参考 | `docs/twm-technical-review-2026-06-20.md`、`docs/twm-technical-review-2026-06-23.md` | — |

下面按用户提的 6 个维度给出严格意见。所有论断都有具体文件/行为或测得指标支撑。

---

## 一、架构合理性（B+ / 较好但存在结构性偏紧）

### 合理处

1. **范式选择正确**。TWM 没有把自动驾驶/具身的 world model 直接套到 GIS，而是按"agent 关心对象 / action 范围 / observation 形态 / prediction horizon"四要素重新定义（见 `docs/twm-scale-and-novelty-analysis.md`、`docs/twm-vs-geosos-flus-comparison.md`）。把"图斑 / 项目 / 红线 / 审批"作为 agent 关注对象，把"选址 / 整治 / 保护 / 审批 / 规划调整"作为 action，是一次诚实的尺度迁移，而不是套壳。
2. **10 层分解清晰且互不越界**。数据底座 → 层级状态 → 编码 + GeoFM gate → 动作/情景 → action-conditioned dynamics → 多头输出 → 因果校准 → 证据门控 → planner consumer → GIS 部署。每层都有显式契约（dataclass + JSON schema 名 `territory_world_model.*.v1`），没有混淆 simulator 与 planner 的边界。这条原则在代码层一致落实：`planner.py` 注释明确 "The planner does not define the world model itself; it consumes state bundles"。
3. **数据结构层级化**。`TwmStateObject + TwmStateRelation + TwmRuleHit + TwmEvidenceItem + TwmReviewTask` 形成 object-relation-rule-evidence 四元组，从 source（MMFE bundle）到 sink（API/Toolset）契约一致；JSONB 列承载演化字段（`rule_body`、`legal_basis`、`metric_payload`）是 v0 阶段务实选择。
4. **声明阶梯（claim ladder）和证据门控（evidence gate）作为一等公民**。`claim_ladder.py` 把 L0~L4 与具体门 catalog 绑定（`state_build_pass`、`future_state_holdout_pass`、`counterfactual_calibration_pass`、`planning_lift_pass`、`geofm_gate_decision`、`gis_audit_pass`、`human_review_completed`），证据不达标自动降级为 `review` 而不是冒进给结论。这是 TWM 区别于纯 ML 预测器的关键设计。

### 不合理或偏紧处

1. **`service.py` 10,797 行单体类**。`TerritoryWorldModelService` 内含 30+ 个 `_*_state_stage`、`_*_forecast_gate`、`_causal_records_from_state_objects`、`_temporal_transition_examples_from_state_snapshots` 等私有方法，路由层 871 行又直接调用。这是 "facade 不堪重负" 的典型反模式，违反了它自己 10 层架构里第 9 层与第 10 层应该分离的原则。
2. **多头输出契约名实不一致**。文档反复声明 `future_latent_state` head，但 `train_neural_multi_head_dynamics`（neural_dynamics.py L66-72）实际只把 `area_total` 一个标量做归一化预测；其余 5 个 head 是 `constraint_probability / utility_delta / confidence / calibrated_utility_delta / allowed`，没有任何 "latent state representation"。这相当于把 "潜在状态" 在代码里降级成了 "未来面积"，建议要么补齐 head，要么把契约名/对外口径改成 `future_area_and_key_indicators`，否则学术或评审场合一旦被翻代码就会形成 overclaim 把柄。
3. **动作空间仍是离散标签**。`TerritoryWorldModelAction` 的 `action_type / target_role / magnitude / treatment` 都是字符串/标量；`spatial_scope / execution_mask` 主要是元数据，没有"空间动作搜索"原生支持。这与文档第 4.5 节"动作是对空间状态的干预"承诺有差距。
4. **数据库表设计 JSONB 偏多**。12 表里 `rule_body / legal_basis / metadata / metric_payload / quality_summary / build_log / summary / attributes / metrics / evidence / input_changes / field_mapping / quality_snapshot / bbox_json` 全是 JSONB。短期换演进性可以，但 `severity / hit_status / scenario_type / build_status` 等是稳定枚举值，应抽成独立列或 ENUM，并加部分索引（GIN on `attributes`、BRIN on `created_at`），否则跨州县/跨年度 query 走顺序扫描风险高。
5. **没有专属 OTel span**。v23.0 已经接通 OTel，但 TWM 三个耗时操作（`train_dynamics_candidate`、`counterfactual_rollout`、`estimate_observational_treatment_effect`）没有看到专属 span 与 attribute（如 `state_version_id`、`backend`、`sample_count`、`gate_outcome`），生产环境下难以做 P99 诊断。

---

## 二、可行性（B / 框架可行，但落地路径有硬约束未拆解）

### 可行的部分

1. **构建闭环已完整可跑**。`pytest data_agent/test_territory_world_model.py` 47 通过（耗时 18 分钟），`test_twm_state_input.py` / `test_twm_mmfe_*` / `test_twm_dynamic_world_flus_comparison.py` 系列均能跑通；`scripts/run_twm_validation_bundle.py` 与 `scripts/run_twm_production_onboarding.py` 提供了端到端入口；REST API 与 ADK toolset 也已挂载。说明 "代码能走到证据生成那一步" 已经被工程证实。
2. **Dynamic World admin20 已是真实公开数据**。`docs/reports/twm_dynamic_world_admin20_benchmark_2026-06-22.json` 显示 20 个乡镇/街道、2017–2023、100 个 rolling case，**TWM 独立 transition 的 Change FoM = 0.072289 vs Markov 0.045569 vs Persistence 0**。这是脱离合成数据后首次有公开 baseline 比较，**确实可复现**，可行性得分提升。
3. **物理隔离内网部署形态合理**（`twm-airgapped-deployment-and-iteration-strategy.md`）。外网研发 → 制品交付 → 内网真实数据，离线 Docker / Helm 包，是面向国土真实甲方现实的唯一可行路径，路线没问题。

### 不可行或缺口处

1. **真实历史审批/复核/政策动作可行性标签 = 0 行**。所有 256 行 synthetic experiment foundation、128 对 treated/control、64+64 action mask 样本都带 `not_for_production=true`。`production_ready_observed_history_rows = 0` 写在最新 punch list 里。可行性的真正瓶颈不在算法，在**数据准入**。
2. **学习型 dynamics 训练数据规模太小**。三个 torch 后端（MLP / Hierarchical Graph / Spatiotemporal Transformer）的训练集 < 200 行，再做 8-period × 4-step holdout，从样本量层面 `false_allow=0 / false_block=0 / planner exact-match=1.0` 这种"完美"指标是 overfitting 信号而不是泛化证据；任何严肃投稿/部署都会被拆穿。
3. **FLUS 全套（ANN suitability + adaptive inertia + roulette wheel）尚未完整复现**，目前对比的是简化 direct FLUS CA adapter（handoff 自承）。所以 "TWM 比 FLUS 强" 的口径在论文/客户层是**不能讲**的，得改成 "在 Markov 与简化 FLUS 上有 change-FoM 优势，OA 与 macro-F1 持平或略落后"。
4. **SCCA（spatial causal calibration adapter）实际能力是观察性 ATT/IPW/AIPW + 邻接固定效应**，本质上是 `E[Y|T=1,X]` 而非 `E[Y|do(T)]`。在没有 RCT / 自然实验 / 准实验设计的情况下，把它写成 "因果校准" 对外要小心，否则会被审稿人或 domain expert 抓 overclaim。
5. **GeoFM B0/B1 / D2/D3/D4 gate 仍是契约而非实测**。`twm-current-handoff.md` 自承 "deterministic B0/B1 prediction scaffold ... explicitly marked review-only"。Prithvi 或 AlphaEarth 真实跨区下游实验没跑过。

---

## 三、实用性（演示 A- / 内部 PoC B / 生产 D，分层判断）

实用维度需要分场景：

1. **演示与技术交流（A-）**：架构图、SVG / PNG 资产、报告文档、ADK 工具、TWM 前端 tab 齐全，给自然资源系统 / 规划院做 vision pitch 完全压得住。已有 Bishan demo + Dongguan GeoSOS 真实数据 + Dynamic World admin20 公开数据三套底座，演示叙事很完整。
2. **内部 PoC（B）**：拿到合作单位（自然资源部、省厅、规划院）一个区县 5 年以上的真实审批/审查/红线/规划"一张图"后，**6–12 周可冷启动**。前提是甲方配合脱敏，且需要进物理隔离内网部署。
3. **生产替代 FLUS / PLUS（D）**：三道硬门槛（真实历史数据、跨区域 holdout、规划增益盲评）未跨之前**不应**用于任何会影响真实审批意见的工作流。要避免任何形式的 "TWM 已替代 FLUS" 对外口径。
4. **学术发表**：GIScience / IJGIS / Computers, Environment and Urban Systems / Annals of GIS / IJDE 可投（架构论文 + 合成验证 + 真实 Dynamic World 小规模 PoC 撑得起）；NeurIPS / ICLR 不要硬投，算法新颖度不够。

`service.data_foundation_assessment()` 与对应前端 tab 已把这种实用边界**主动暴露**给业务人员，这是工程上很成熟的姿态——不藏短，不冒认。

---

## 四、创新性（C+ 算法 / B+ 架构 / A- 行业范式 — 真创新有限但真实）

诚实地拆开看：

- **算法层（C+）**：Action-conditioned dynamics（Dyna / Dreamer / MuZero）、多头 multi-task、ATT/IPW/AIPW（Pearl / Rosenbaum / Imbens）、MPC/beam（Rawlings）、hierarchical token（GNN/Transformer 常见）、GeoFM embedding（Prithvi/AlphaEarth）——**单点都不新**，文档也明确承认了这一点。
- **架构层（B+）**：四件套同时具备在公开文献和产品里少见——
  1. parcel ⊂ block ⊂ township ⊂ county 的对象-关系-规则-证据状态原语（vs FLUS 栅格元胞、Foundry ontology-link-action 的本质区别）；
  2. evidence gate × claim ladder × 5 级提升通道作为推理链路的一等公民；
  3. GeoFM 受 B0/B1 gate 控制的 "可消融可关闭" 原则；
  4. 显式的治理闭环（GIS evidence → rule review → audit → calibration → planning revision），不是机器人控制闭环。
- **行业范式层（A-）**：在 "国土空间治理 × 体系架构 × 工程化产品" 三者交集上，把 evidence gate + causal calibration + action-conditioned dynamics + claim ladder 写进产品代码的工作，国内外公开领域确实罕见。FLUS/PLUS 给 "格局如何竞争"，TWM 在尝试给 "行动是否合规、影响是否可信、方案是否可审计"——这是范式偏移而不是算法突破。

定位口径建议（直接可用）：

> We introduce a governance-oriented geospatial world model. TWM represents land systems as hierarchical GIS object-relation-rule-evidence states, learns action-conditioned multi-head dynamics, and upgrades planning claims only through spatial causal calibration and evidence-gated validation.

避免使用 "首次"、"突破"、"超越 FLUS" 等措辞，否则进入同行评审会被拆。

---

## 五、问题与不足（按严重性排序）

### 🟥 致命 / 必修

1. **`future_latent_state` 名实不符**（neural_dynamics.py L66-72）。Head 实际只产 area_total，文档却宣传完整 latent state。投稿/对甲方汇报前必须二选一：补齐 head 或修改对外口径。
2. **生产数据 = 0 行**；synthetic 全部带 `not_for_production`。任何 "准确"、"可靠"、"已超过 FLUS" 的口径在当前数据底座下都是 overclaim。
3. **`service.py` 10,797 行单体**与 `_INSTANCE` 单例 + threading.Lock 形态。冷启动、单元测试、并发追踪都偏脆。
4. **观察性校准 vs 干预性因果混淆**。`causal_calibration.py` 主结论是 augmented IPW，已加 `"claim": "observational_calibration_only"`，但 forecast 与 rollout 消费时，最终 `calibrated_utility_delta` 在 service 层与 "治理收益" 绑定输出，外部用户很难感知到边界。应在 API 输出层加显式 `identification_strength: observational` 字段。

### 🟧 重要 / 限期改

5. **测试比偏低（约 2.5%）**。15 个 test_twm_*.py + test_territory_world_model.py 合计 ~11K 行，看似不少，但其中 `test_twm_data_foundation_validation.py` 3089 行、`test_twm_dynamic_world_flus_comparison.py` 1522 行属于报告快照式断言，真正覆盖 `rule_evaluator.py`（1200）/ `neural_dynamics.py`（1513）/ `causal_calibration.py`（560）关键路径的单元数比例偏低。
6. **训练样本严重不足导致 "完美指标"**（false_allow=0、planner exact-match=1.0、rollout regret=0.0）。在 200 行样本上的完美数字应在 README/技术评审里明确标注 "on synthetic foundation, not generalization evidence"。
7. **planner ranking 没有真正的 learned ranking loss**，目前是 `utility − risk + 0.1*confidence + blocked/review penalty` 启发式，自承 "已有 training objective scaffold；真正的训练优化和 learned ranking 仍未实现"。
8. **GeoFM gate 是契约不是实测**。B0/B1 prediction map 是 deterministic scaffold，没有 Prithvi 或 AlphaEarth 真实下游 planning lift 实验。
9. **fallback rate 0.343333**（admin20 上 900 个 source-class 拟合中 309 走 fallback）。说明 dynamics backend 在稀疏类别上有显著数据稀疏问题，hierarchical pooled 与 cross-region smoothing 都没真正赢过 independent baseline。

### 🟨 可观察 / 中期改

10. **JSONB 滥用**。`twm_state_object.attributes` / `twm_rule_hit.metrics` 等高频读字段应抽列 + GIN 索引。
11. **OTel 无专属 TWM span**。dynamics 训练 / 因果校准 / 反事实 rollout 缺生产可观测性埋点。
12. **rule DSL（`rule_dsl.py` 82 行）极简**。当前规则体只有 normalize/validate 工具函数，缺少分支表达式、空间谓词（intersects/within/buffer/distance）、时间约束等核心 DSL，所有空间关系实际由 `state_builder.py` + `rule_evaluator.py` 硬编码处理。把规则做成数据是好方向，但 DSL 表达能力当前不足以承诺 "治理规则" 层。
13. **没有 model registry / version pinning**。`twm_state_version` 有 build_status，但模型版本（torch_multi_head_mlp / torch_hierarchical_graph / torch_spatiotemporal_transformer）没有对应注册表，回滚链路不闭合。

---

## 六、走向行业级突破的改进路径

### 短期（3 个月内 — 把目前 "严肃工程" 变成 "可信小规模 PoC"）

1. **拆分 `service.py`** 成 state_service / dynamics_service / calibration_service / planner_service / evidence_service 五个文件，路由层只调 service interface，service 不调 route。
2. **修复 `future_latent_state` head**：把 token group encoder 的 pooled state 显式输出成 latent vector，再下接 area / 连片度 / 质量 / 承载力等 head；同步修对外口径。
3. **拿到一个区县真实历史数据**（5 年 + 10K 图斑 + 审批记录 + 复核记录 + 红线版本变更），全程脱敏，进物理隔离内网；在内网做第一次真实 train-region-A / test-region-B 留出。
4. **写一篇 GIScience / IJGIS 体系架构论文**：定位为 governance-oriented geospatial world model 的体系工作，主结果用 Dynamic World admin20 的 100 个 rolling case + FLUS 完整管线对比。
5. **把 SCCA 改成可插拔后端**：本地 observational backend 保留，但留一个 `spatial_causal_estimator_adapter` 给 paper 6/7 风格的空间 treatment-effect estimator 做服务对接。

### 中期（6–12 个月 — 跨过三道硬门槛）

6. **完整 FLUS（ANN suitability + adaptive inertia + roulette wheel + 多类型竞争）复现**作为强 baseline，避免被审稿人挑 "和谁比"。
7. **learned action-mask head + learned risk calibration**，把现有 post-hoc affine calibration 与启发式 ranking 替换成端到端可训练版本；保留 false_allow=0 这种安全侧约束作为 inequality loss。
8. **跨区域 holdout × 跨年度 holdout 双因子 ablation**，至少 3 个省 × 5 年；用 D3 / D4 验证套件出 GeoFM 真实下游 ablation 报告。
9. **规划增益盲评**：找规划院 5 位以上专家，对 TWM beam-selected plan vs FLUS-allocated plan vs 人工方案做盲评打分，输出 Cohen's Kappa 与排序 regret。
10. **加入端到端 differentiable planning**：把 beam 中的 utility-risk 加权用 Gumbel-softmax 改成可反传，让 planning ranking loss 真正驱动 dynamics 训练，而不只是事后排序。

### 中长期（行业级突破的真正路径）

11. **从 "TWM = Simulator 主体" 升级为 "治理基础模型（Governance Foundation Model）"**：把 (a) GeoFM 多模态感知（Prithvi / AlphaEarth）、(b) 层级 GIS 状态、(c) action-conditioned dynamics、(d) 规则可执行 DSL、(e) 空间因果、(f) 大语言模型推理 / 复审解释，**联合训练在同一个统一表征空间内**。MoE 多任务 head 解决 "治理决策 × 政策合规 × 规划方案 × 审计证据" 四类任务。这是真正的 "行业首创" 机会窗口。
12. **政策语义层与规则 DSL 二级化**：把 "用途管制条例 / 永农划定办法 / 生态红线 / 城镇开发边界 / 占补平衡" 等法定规则用一种 first-class 的空间 + 时间 + 严重度 DSL 表达，规则版本与 `twm_rule_set` 绑定，规则演化作为一等 audit 实体（policy_version → state_version → rule_hit 三联血缘）。这一步打通后，TWM 就从 "决策辅助工具" 升级为 "政策仿真器"，能回答 "如果某条管制条例改了 X，未来 5 年治理后果是什么"——这是国家级国土规划重大需求。
13. **空间扰动检验（spatial perturbation test）与 conformal prediction**：每次 forecast 输出 conformal 区间而不是点估计，evidence gate 与 conformal coverage 绑定。这把 TWM 的 "可审计" 从制度承诺升级成数学保证。
14. **建立 "治理基础模型基准（Governance Foundation Benchmark）"**：发起跨学校/院的开放基准，把 Dynamic World × 中国土地变更调查 × 一张图脱敏样本 × 真实审批数据组合成多任务公开 benchmark，TWM 作为 reference implementation。**数据集 + 基准 + reference 三位一体是占据领域定义权的最高效路径**。
15. **政企生态：内网 "治理大模型即服务" 形态**。每个国土厅一套内网 TWM 实例，外网集中接合成数据、公开数据、模型权重版本与离线评估包；通过 "脱敏指标反馈" 持续学习而原始数据不出域。这种部署形态本身就是一项制度创新。

---

## 七、综合评级与给决策层的一句话

| 维度 | 评级 |
|---|---|
| 架构完整性 | A- |
| 架构合理性 | B+ |
| 架构可行性 | B |
| 当前实用性 | C+（演示 A- / 生产 D） |
| 算法创新性 | C+ |
| 架构 / 范式创新性 | B+ / A-（行业层面） |
| 工程严谨性 | B+（不掩盖短板） |
| 改进后潜力 | A- → A |
| **综合** | **B+** |

**一句话给决策层**：

> TWM 现在不是噱头，是一次架构上很认真的工程，21K 行代码、12 表 schema、47 测试用例都对得起它声称的 10 层体系；但它的下一笔投入不应该再加架构层，而应该买 "一个真实区县 5 年以上的脱敏审批 / 复核 / 规划历史数据" 和 "3 位规划专家的盲评时间"——把 "工程可信" 升级到 "业务可信"，这是 TWM 走向行业级突破的唯一关键门。

---

## 八、与历史评审的关系

- 2026-06-20 评审（`docs/twm-technical-review-2026-06-20.md`）：首轮整体性评审，提出 `validate_twm_state_input` 校验过浅等具体技术问题，已被采纳。
- 2026-06-23 评审（`docs/twm-technical-review-2026-06-23.md`）：第二轮独立评审，重点在创新性边界与实用性门槛的客观判定，确认 21K 行代码 / 12 表 schema / 32 份文档的工程量与文档诚实度均高于行业平均。
- 本次（2026-06-25）评审：在 6 维（架构合理性 / 可行性 / 实用性 / 创新性 / 问题不足 / 改进路径）下做更细粒度审查，**新增**对 `service.py` 单体规模、`future_latent_state` 名实问题、JSONB 滥用、rule DSL 极简、缺 model registry、缺 OTel TWM 专属 span 等 6 处工程层缺口的判定，以及面向 "治理基础模型 / 政策仿真器 / 治理基础模型基准" 三条中长期突破路径的具体建议。

三轮评审可并列阅读，本轮不替代前两轮。

---

**评审签名**：Claude Opus 4.8（1M context）
**评审依据**：核心包 `data_agent/territory_world_model/`（16 个源文件）+ `data_agent/fusion/twm_state_input.py` + `data_agent/api/territory_world_model_routes.py` + `migrations/090_twm_core.sql` + `migrations/091_twm_spatial_policy_rule_derivation.sql` + 15 个 `test_twm_*.py` + 34 份 `docs/twm-*.md` + 30+ 份 `docs/reports/twm_*.{md,json,csv}` + `scripts/run_twm_validation_bundle.py` + `scripts/run_twm_production_onboarding.py` + 最新 `docs/twm-current-handoff.md`（2026-06-25）。
