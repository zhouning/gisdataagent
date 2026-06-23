# TWM 技术评审报告

**评审对象**: GIS Data Agent (D:\adk) 中的 Territory World Model (TWM) 子系统
**评审日期**: 2026-06-23
**评审人**: Claude Opus 4.8 (1M context)
**评审范围**: 代码 ≈ 19K 行 (`data_agent/territory_world_model/`) + 1 个迁移 (`090_twm_core.sql`, 12 表) + 32 份文档 (≈ 13.5K 行) + 10 个测试文件 + ≈ 700 个 test_data 资产
**最近 5 次 TWM 提交**: `199a523`(基础设施) → `01d25f8`(因果校准) → `f576cb4`(离线验证) → `0282888`(就绪门) → `c5f991f`(FLUS 基线)

---

## 一、一句话结论

> TWM 是一次**严肃的工程实践**,在体系结构层面把"分层 GIS 状态 + 动作条件动力学 + 多头输出 + 因果校准 + 证据门控 + 分层验证"组装成一套连贯系统;**架构完整、代码扎实**;但**当前所有验证均建立在 256 行合成数据上**,"创新性"主要体现在**组合架构**而非单个算法,"实用性"距离生产可用仍有**真实历史数据获取、跨区域留出实验、规划增益闭环验证**三个**硬性门槛**未跨越。

---

## 二、TWM 在做什么 — 客观技术画像

### 2.1 体系定位

TWM 不是把 Ha & Schmidhuber 的 World Models 或 Dreamer 直接搬到 GIS,而是**面向国土空间治理**重新定义了 world model 的四要素:

| 要素 | 自动驾驶/具身世界模型 | TWM |
|---|---|---|
| Agent 关心对象 | 车辆、机械臂、行人 | 地块/图斑/村镇/区县/红线/项目 |
| Action 范围 | 转向、抓取、变道 | 选址、整治、保护、审批、规划调整 |
| Observation 形态 | 相机帧、点云、传感器流 | 遥感影像、GIS 图层、审批记录、政策文本 |
| Prediction horizon | 秒到分钟 | 月/年/规划周期 |
| 主要约束 | 物理、碰撞、交通规则 | 耕保红线、生态红线、城镇开发边界、审批一致性、证据链 |

这是一次**合理且非套壳的尺度迁移**。TWM 显式承认与 FLUS/PLUS、Earth Foundation Models、Palantir Foundry、AlphaEarth 等相邻工作的边界,**没有把"首次做地理空间模拟"作为创新点**。

### 2.2 实现规模 (定量)

| 模块 | 行数 | 性质 |
|---|---:|---|
| `service.py` | 10,797 | 核心服务编排 (单文件偏大,值得拆分) |
| `neural_dynamics.py` | 1,513 | MLP/Graph/Transformer 三种动力学后端 |
| `rule_evaluator.py` | 1,200 | 规则命中评估 |
| `repository.py` | 1,176 | DB 持久化 |
| `state_builder.py` | 1,114 | 状态构建 (parcel/block/township/county token) |
| `models.py` | 812 | 数据契约 (dataclass) |
| `planner.py` | 693 | 规划消费器 (beam/rollout) |
| `causal_calibration.py` | 560 | ATT/IPW/AIPW + 空间干扰诊断 |
| `spatial_causal_estimator.py` | 461 | 空间因果估计 |
| `fusion/twm_state_input.py` | 579 | MMFE → TWM 状态契约 |
| `api/territory_world_model_routes.py` | 871 | REST API |
| `migrations/090_twm_core.sql` | 218 | 12 表 + 11 索引 |
| **合计 (核心)** | **~21,000** | — |
| **测试** | ~500 (10 文件) | — |
| **文档** | ~13,500 (32 文件) | — |

**比例提示**: 文档/代码 ≈ 0.65, 测试/代码 ≈ 0.025。**测试比偏低**,文档比偏高 — 这是设计先行项目的典型特征,但也说明工程验证密度不足。

### 2.3 数据库 schema (`090_twm_core.sql`)

12 张表组织清晰:`twm_project / twm_layer_binding / twm_state_version / twm_state_object / twm_state_relation / twm_rule_set / twm_policy_rule / twm_rule_hit / twm_evidence_item / twm_review_task / twm_scenario / twm_scenario_metric`。

**评价**: 刻意采用 JSONB 承载演化字段(`rule_body`、`legal_basis`、`metric_payload`),**牺牲规范化换取演进能力** — 在标准还在动的阶段是务实选择,但需要在 v1 GA 前把高频查询字段提取为独立列。

---

## 三、创新性评估

### 3.1 不是创新点 (诚实先说)

下列要素**单独看都不新**,TWM 也明确承认:

- **Action-conditioned dynamics**: Sutton Dyna / Ha & Schmidhuber / Hafner Dreamer / Schrittwieser MuZero 早已成熟
- **Multi-head 输出**: multi-task learning 标准做法
- **ATT / IPW / AIPW 因果估计**: Pearl / Rosenbaum / Imbens 经典方法
- **MPC / beam / constrained rollout**: Rawlings 经典控制理论
- **Hierarchical token**: GNN / Transformer 圈常见
- **GeoFM embedding**: Prithvi / AlphaEarth 已是成熟基础设施

### 3.2 真正的创新 — 体系性组合

TWM 的创新性应落在**3 个体系层面的设计选择**上,这些选择**单独不新但组合到一起在公开文献中确实少见**:

**创新点 1: 分层 GIS 对象-关系-规则-证据状态作为 world state primitive**
不是把一个县的特征压成 flat vector,而是显式构造 `parcel ⊂ block ⊂ township ⊂ county` 的 token 层次,并把"对象-关系-规则命中-证据"作为状态原语。这与 FLUS/PLUS 的栅格元胞 + 转移概率范式有**本质区别**。`state_builder.py` (1114 行) 完整实现了这一构造。

**创新点 2: 证据门控 (evidence gate) 与声明阶梯 (claim ladder)**
`claim_ladder.py` (205 行) + `evidence.py` (63 行) 把模型输出按**证据充分度**分级为 `pass / review_required / blocked`,而不是无条件给出预测。这把 "模型预测" 与 "可声明的治理结论" 解耦 — **是 TWM 区别于纯 ML 模型的关键设计**。这一思想在数据卡片(Gebru et al.)和模型卡片(Mitchell et al.)的传统下有源流,但**把它作为 world model 的一等组件嵌入推理链路**,确实较少见。

**创新点 3: GeoFM 是受门控的可选增强,不是默认主角**
B0 (无 GeoFM) / B1 (有 GeoFM) 消融契约写进了架构,只有当下游 planning lift 显著时才允许 GeoFM 进入主路径。这避免了"上 foundation model 就一定好"的盲目性,**是健康的工程克制**。

**创新点 4: 治理闭环而非控制闭环**
显式声明 loop 不是 robot → action → physics,而是 `GIS evidence → rule review → audit → calibration → planning revision`。这把 world model 与**人类审批工作流**结合,在国土治理场景下是合理建模。

### 3.3 创新性等级判定

| 维度 | 评级 | 理由 |
|---|---|---|
| 算法新颖性 | **C** | 单算法都是已有方法 |
| 架构新颖性 | **B+** | 体系组合 + 证据门控 + 治理闭环 在公开文献中较罕见 |
| 工程新颖性 | **B+** | 12 表 schema + 多后端动力学 + 因果校准嵌入服务层 |
| 学术发表面 | **B / B-** | 体系架构 + 合成验证可投顶级 GIS 会议 (e.g., GIScience, IJGIS),**不够投 NeurIPS/ICLR** — 算法新颖度不足 |
| 行业首创性 | **A-** | 在国土空间治理这个**具体业务场景**内,把 evidence gate + causal calibration + action-conditioned dynamics 写到产品代码里的工作,在国内外公开领域确实较少见 |

**结论**: TWM 的创新性是**真实的但范围有限** — 创新落在"国土治理 × 体系架构 × 工程化"三者交集,**不是算法层面突破,是范式层面的整合**。这与文档自述 ("不是单个组件,而是体系结构") 一致,**没有 overclaim**。

---

## 四、实用性评估

### 4.1 当前实现成熟度

| 组件 | 代码状态 | 验证状态 | 生产就绪度 |
|---|---|---|---|
| 状态 schema (objects/relations/rules/evidence) | ✅ 完整 | ✅ 单元测试 + 合成数据 | **可用** |
| 状态编码器 (4 级 token) | ✅ 完整 | ⚠️ Bishan demo + 合成 256 行 | **scaffolding** |
| 动作 schema (action/treatment/mask) | ✅ 完整 | ✅ 64+64 合成样本 | **可用** |
| 动力学后端 (MLP/Graph/Transformer) | ✅ 3 候选完整 | ⚠️ 仅 192 合成样本训练 | **scaffolding** |
| Multi-head 输出 (6 头) | ⚠️ 部分 | — | `future_latent_state` **当前只预测 area_total 一个标量**,与"latent state"契约不符 |
| 因果校准 (ATT/IPW/AIPW + 空间) | ✅ 完整 | ⚠️ 合成数据诊断 | **可用 (观察性)** |
| 证据门控 + Claim 阶梯 (L0-L4) | ✅ 完整 | ⚠️ 合成 | **可用** |
| 规划消费器 (beam/rollout) | ✅ 完整 | ⚠️ exact-match 合成 1.0 / 0.625 | **scaffolding** |
| GeoFM B0/B1 门 | ⚠️ 部分 | ❌ 真实跨区域 ablation 未跑 | **预览级** |
| 验证报告引擎 | ✅ 完整 | — | **可用** |
| 审计 / 溯源 (checksum, evidence_item) | ✅ 完整 | ✅ 单元测试 | **可用** |

### 4.2 三个硬性门槛 (距离生产可用)

**门槛 1: 真实历史数据 = 0 行**
所有训练/验证数据都是 `not_for_production` 标记的合成数据。没有任何真实地块的历史状态变化、真实审批记录、真实政策干预效果数据进入训练。这是**最大且不可绕过**的 gap。

**门槛 2: 跨区域留出实验 = 未做**
D3/D4 验证阶梯目前是从合成数据的预测图推断出的,**没有真正按地理区域切分训练/测试集**的实验。GeoFM 的 B0/B1 消融也停留在契约层面。

**门槛 3: 规划增益闭环验证 = 未做**
Beam search / rollout planner 在合成 64 题上 exact-match = 1.0,但**没有任何实验证明 TWM 给出的方案排序优于传统 MCDM / FLUS / 经验规则**。`twm-flus-v24-simulation-optimization-2026-06-22.md` 报告了对比但仍是合成数据。

### 4.3 风险与红旗

🟥 **Latent state 名实不符**: 文档反复强调"future latent state head",代码实现仅预测 `area_total` (一个标量)。这是**最严重的"代码不及文档"** gap,需要在投稿/汇报时口径修正。

🟥 **观察性 vs 干预性混淆风险**: 因果校准实现的是 `p(outcome | treated, observed)` 的 ATT / IPW / AIPW,**不是 `p(outcome | do(action))`**。在缺少 RCT 或自然实验数据时,这两者**不能等价**。当前代码的因果声明边界**需要 review 后明确标注为观察性校准**。

🟥 **合成数据规模过小**: 256 行 / 128 对 treated-control / 64+64 mask 样本 — 对于声称的"地理空间世界模型",这一规模**仅够 sanity check,不够任何泛化结论**。

🟧 **`service.py` 单文件 10,797 行**: 严重超出维护友好阈值,**强烈建议拆分**为 state / dynamics / calibration / planner / evidence 五个子服务。

🟧 **测试比偏低 (~2.5%)**: 47 个测试覆盖 ~21K 行核心代码,远低于通常的 10-20% 行数比。Critical paths (规则评估、动力学训练) 的测试密度尤其需要提升。

🟧 **API 路由 871 行**: REST 层与服务层耦合较紧,建议在 GA 前做一次 contract-first 重构。

🟨 **JSONB 滥用风险**: 12 表中 6 个核心字段使用 JSONB,**长期会形成查询模式瓶颈**。当前可接受,v1 GA 前应做一次模式抽取审计。

🟨 **没有 OTel 埋点专项**: 已知 v23.0 已有 OTel 框架,但 TWM 的动力学训练 / 校准 / 规划三大耗时操作**没有看到专属 span 指标**,生产环境难以诊断。

### 4.4 实用性等级判定

| 场景 | 评级 | 说明 |
|---|---|---|
| 演示 / 客户技术交流 | **A-** | 架构图清晰、代码可跑、报告齐全,适合给自然资源系统、规划院做 vision pitch |
| 内部 PoC / 小规模试点 | **B** | 在合作单位提供真实历史数据后, 6-12 周可冷启动 |
| 生产部署 (替代现有 FLUS/PLUS) | **D** | 三大门槛未跨越前**不应**部署到任何会影响真实审批的工作流 |
| 学术发表 (顶级 GIS 会议) | **B / B+** | 投 GIScience / IJGIS / Computers, Environment and Urban Systems 可行,需把 latent state 口径修正 + 增加 ablation 实验 |
| 学术发表 (顶级 ML 会议) | **C** | 算法新颖度不足以支撑 NeurIPS / ICLR |

---

## 五、与同类工作的横向比较

| 维度 | TWM | FLUS / PLUS | Palantir Foundry | AlphaEarth / Prithvi | Google DeepMind GenWorld 类 |
|---|---|---|---|---|---|
| 主目标 | 治理决策 + 审计 | 土地利用模拟 | 通用企业决策 | 地球观测嵌入 | 通用世界模型 |
| 状态原语 | 对象-关系-规则-证据 | 栅格元胞 | object-link-action | 像素/patch 嵌入 | 视频帧/隐变量 |
| Action 条件 | ✅ 显式 | ⚠️ 部分(转移概率) | ⚠️ ontology level | ❌ | ✅ |
| 证据门控 | ✅ **核心特性** | ❌ | ⚠️ 通过 audit log | ❌ | ❌ |
| 因果校准 | ✅ 嵌入 | ❌ | ❌ | ❌ | ❌ |
| 多头输出 | ✅ 6 头 | ⚠️ 单输出 | ⚠️ ontology 化 | ⚠️ embedding | ✅ |
| 治理闭环 | ✅ 显式 | ❌ | ⚠️ 通用 | ❌ | ❌ |
| 真实数据训练 | ❌ | ✅ (历史 LULC) | ✅ (客户数据) | ✅ (PB 级遥感) | ✅ (大规模视频) |
| 行业领域聚焦 | 国土治理 | 土地利用 | 跨行业 | 通用 EO | 通用 |

**TWM 的独特定位**: **证据门控 + 因果校准 + 治理闭环**三件套同时具备的工作,在公开文献和产品中确实少见。但在**真实数据训练规模**这一硬指标上,TWM 大幅落后。

---

## 六、给项目的具体建议

### P0 (必做,3 个月内)

1. **修正 latent state 口径**: 要么把 head 实现扩到完整 latent state 预测,要么把文档/对外材料从 "future latent state" 改为 "future area & key indicators",**消除名实不符**。
2. **拿到第一批真实历史数据**: 与合作单位 (山西测绘院、自然资源部、规划院) 谈定一个**最小可信地块集** (建议 ≥ 1 个区县, ≥ 5 年历史, ≥ 10K 图斑),哪怕是脱敏版本。
3. **`service.py` 拆分**: 10,797 行单文件不可持续,按 state/dynamics/calibration/planner/evidence 拆 5 个文件。
4. **跑一次真实跨区域留出实验**: 哪怕在 Dongguan / Bishan 公开数据上,也要做一次 train-A-region / test-B-region 的真验证,不再只看 250 行合成。

### P1 (3-6 个月)

5. **明确因果声明边界**: 在 API 输出和文档中标注哪些 estimator 是观察性 (`E[Y | T=1, X]`) 哪些是干预性 (`E[Y | do(T=1)]`),不混用。
6. **GeoFM B0/B1 真实消融**: 用 Prithvi 或 AlphaEarth embedding 在 P0 拿到的真实数据上做一次完整对比,出一份真 ablation report。
7. **规划增益闭环验证**: 设计一个真实任务 (e.g., 耕地占补平衡选址),让 TWM planner 与传统 MCDM、FLUS 在专家盲评下打分。
8. **测试覆盖率提升到 ≥ 10%**: 重点是 rule_evaluator (1200 行) 和 neural_dynamics (1513 行) 的关键路径。

### P2 (6-12 个月)

9. **冲一次 GIScience 2027 / IJGIS 投稿**: 创新性 + 合成验证 + 真实小规模 PoC 可以撑起一篇 well-positioned 的体系架构论文,但**不要硬投 NeurIPS**。
10. **Schema v1 GA**: 12 表中的 JSONB 字段做查询模式审计,把高频字段抽出为独立列;加索引。

---

## 七、最终评级

| 维度 | 评级 | 一句话 |
|---|---|---|
| **架构完整性** | **A-** | 10 层架构落地,文档与代码对齐良好 |
| **代码质量** | **B+** | 模块化合理,但 service.py 过大,测试比偏低 |
| **算法创新性** | **C+** | 单算法不新,无突破 |
| **架构创新性** | **B+** | 证据门控 + 因果校准 + 治理闭环组合在公开领域较罕见 |
| **工程严谨性** | **B+** | 验证阶梯、合成 vs 真实分明、不 overclaim |
| **当前实用性** | **C+** | 演示可用,生产不可用 |
| **未来潜力** | **A-** | 拿到真实数据后, 6-12 个月可达到 PoC 部署门槛 |
| **综合评级** | **B+** | **架构上的认真工作,实用化前还差三道关键验证** |

---

## 八、给决策层的一段话

> 如果决策层在问 "TWM 现在能上生产吗" — 答案是 **不能**,差三道硬门槛 (真实数据 / 跨区域留出 / 规划增益)。
> 如果决策层在问 "TWM 是不是噱头" — 答案是 **不是**,这是一次架构上认真的工程,代码、schema、测试都对得起 21K 行的体量,文档与实现的诚实度高于行业平均。
> 如果决策层在问 "TWM 值不值得继续投" — 答案是 **值得**,但下一阶段的钱**应该花在拿到真实历史数据 + 与一个真实业务场景的甲方做 PoC** 上,而不是继续堆架构层。
> 如果决策层在问 "TWM 能不能投顶刊" — 答案是 **可以投 GIS 顶级会议 (GIScience / IJGIS)**,但需要先把 latent state 口径修正 + 真实数据 ablation 补上,**不要硬投 NeurIPS / ICLR**。

---

**评审签名**: Claude Opus 4.8 (1M context)
**评审依据**: 32 份 TWM 文档 + `data_agent/territory_world_model/` 全部 15 个源文件 + `migrations/090_twm_core.sql` + 10 个 `test_twm_*.py` 文件 + 5 次 git commit 详情 + Explore 子代理的系统调研报告
**与 2026-06-20 评审的关系**: 本报告是对 `docs/twm-technical-review-2026-06-20.md` 的独立第二轮评审,着重在创新性边界与实用性门槛的客观判定;不替代前轮报告,可并列阅读。
