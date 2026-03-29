# Roadmap v6.0: 遥感智能体能力增强

> **Vision**: 从"通用 GIS 分析平台"升级为"遥感领域专业智能体平台"——对标学术前沿 RS Agent 架构，补齐遥感专属能力。
>
> **理论基础**: Tang et al. (2026) *"Intelligent Remote Sensing Agents: A Survey"* — 遥感 AI Agent 五元组 `(P, T, M, Oa, δ)` 四维架构
>
> **标杆系统**: CangLing-KnowFlow (经验进化)、RS-Agent (Solution Space)、GeoFlow (工作流自动化)、EarthLink (自进化)、Change-Agent (变化检测)、WildfireGPT (RAG 应急)
>
> **Last updated**: 2026-03-21 &nbsp;|&nbsp; **Baseline**: v14.3 &nbsp;|&nbsp; **ADK**: v1.27.2

---

## 对标分析：论文四维架构 vs 当前项目

| 维度 | 论文分类 | 当前状态 | 差距 |
|------|---------|---------|------|
| **规划 (Planning)** | 开环 / 闭环 | ✅ 闭环 (QualityLoop + GovernanceReportLoop) | 缺环境驱动闭环 (数据质量门控 → 自动切换源) |
| **记忆 (Memory)** | 内部状态 + 外部经验池 | ⚠️ 内部有 (ADK output_key)；外部部分有 (memory.py + KG) | 缺 Experience Pool (成功经验复用) |
| **动作执行 (Action)** | 外部工具 / 程序生成 / 具身执行 | ✅ 外部工具 (24 toolsets)；⚠️ 无代码生成执行 | 缺 Programmatic Actions (动态代码生成) |
| **多智能体协作** | 集中式 / 去中心化 | ✅ 集中式 (SequentialAgent) | 缺去中心化 Debate/Critique 模式 |

### 已有领先优势

| 特性 | 学术系统 | 本项目 |
|------|---------|--------|
| 工具规模 | GeoGPT 7-20 tools | 24 toolsets × 多函数 = 100+ tools |
| 用户自服务扩展 | 无论文涉及 | Custom Skills + User Tools + Workflow Editor |
| 多模态数据融合 | 少数系统有 | 10 策略 + LLM 路由 + 质量验证 |
| DRL 优化 | AEOSSP-DRL (调度) | MaskablePPO 土地利用优化 |
| 知识图谱 | KG-Agent-QA | networkx DiGraph + GeoJSON export |
| Pipeline 可组合 | 固定 pipeline 居多 | DAG editor + custom skill nodes |
| 前端交互 | 大多数命令行 | 三面板 SPA (Chat + Map + Data) |

---

## v15.0 — 遥感核心能力增强

> **主题**: 补齐遥感领域专属工具链，从"通用 GIS"到"专业遥感"

### 光谱指数库

- [ ] **spectral_indices.py** — 15+ 常用遥感指数计算引擎
  - 植被类: NDVI (已有), EVI, SAVI, MSAVI, GNDVI, ARVI, LAI
  - 水体类: NDWI, MNDWI
  - 建筑/裸土类: NDBI, BSI, UI
  - 雪冰类: NDSI
  - 火烧类: NBR, dNBR
  - 统一接口: `calculate_index(raster_path, index_name, **params) → GeoTIFF`
- [ ] **智能指数推荐** — 根据用户意图自动选择指数组合
  - "城市扩张" → NDBI + NDVI 差异
  - "水体提取" → MNDWI + 阈值分割
  - "火烧迹地" → dNBR
  - 实现: LLM 路由或规则映射表
- [ ] **RemoteSensingToolset 扩展** — 新增 `calculate_spectral_index` + `recommend_indices` 工具

### 经验池 (Experience Pool)

> 参考: CangLing-KnowFlow 经验进化记忆、RS-Agent Solution Space

- [ ] **experience_pool.py** — 成功分析经验记录与检索
  - 数据模型: `agent_experience_pool` 表 (task_type, region_bbox, data_types, tool_chain JSON, quality_score, user_id, created_at)
  - 记录时机: pipeline 成功完成 + QualityLoop 通过时自动记录
  - 记录内容: 完整 tool invocation 序列 + 参数 + 中间结果摘要
- [ ] **经验 RAG 检索** — 新任务时检索相似经验注入 agent prompt
  - 相似度维度: 任务类型 + 数据格式 + 空间范围 (bbox 交集)
  - 注入方式: `ExperienceToolset.recall_similar_experience()` → prompt prefix
- [ ] **经验进化** — 同类任务多次执行后自动合并/精炼经验模板
  - 频率阈值: 同类型 ≥ 3 次 → 提炼为 "最佳实践" 模板

### 数据质量门控 (闭环增强)

> 参考: 论文环境驱动闭环 — 云覆盖/数据质量差 → 自动切换数据源

- [ ] **云覆盖检测** — `detect_cloud_coverage(raster_path) → float`
  - 基于 SCL (Scene Classification Layer) 或简单亮度阈值
  - 阈值可配: 默认 > 30% 触发降级
- [ ] **数据质量评估** — `assess_data_quality(geodataframe) → QualityReport`
  - 检测: 空值率、几何有效性、CRS 一致性、时间新鲜度
  - 输出: 质量评分 + 问题列表 + 建议操作
- [ ] **自动降级/切换** — DataExploration 阶段集成质量门控
  - 光学影像云覆盖高 → 建议切换 SAR 或其他时相
  - 数据质量低 → 自动触发清洗/修复工具
  - 实现: QualityLoop 前置检查 + agent prompt 注入质量报告

### 卫星数据接入增强

> 基于已有 VirtualSourceToolset (WFS/STAC/OGC API)

- [ ] **Sentinel-2 STAC Connector** — 预置 Element84 Earth Search STAC 连接器
  - 默认 endpoint: `https://earth-search.aws.element84.com/v1`
  - 支持: 时间范围 + bbox + 云覆盖过滤
  - 返回: COG URL 列表 + 缩略图 + 元数据
- [ ] **Landsat STAC Connector** — USGS Landsat STAC 预置
- [ ] **预置源模板** — `virtual_sources` 表预置 3-5 个常用遥感数据源
  - Sentinel-2 L2A, Landsat 8/9, Copernicus DEM, ESA WorldCover, Dynamic World

### 新增 ADK Skills

- [ ] **spectral-analysis** — 光谱分析技能 (指数计算 + 阈值分类 + 结果解读)
- [ ] **satellite-imagery** — 卫星影像获取与预处理技能 (搜索 + 下载 + 裁剪 + 云掩膜)

### 测试

- [ ] **test_spectral_indices.py** — 15+ 指数计算 + 边界条件 + 推荐逻辑
- [ ] **test_experience_pool.py** — CRUD + RAG 检索 + 经验进化
- [ ] **test_data_quality_gate.py** — 云覆盖检测 + 质量评估 + 降级逻辑

---

## v16.0 — 时空分析与变化检测

> **主题**: 从静态快照分析到时空动态理解
>
> 参考: Change-Agent (多级变化解释)、MMUEChange (what-where-why)、STA-CoT (时空推理)

### 变化检测引擎

- [ ] **change_detection.py** — 多方法变化检测模块
  - **双时相差异分析**: 影像差值 + 阈值 → 变化掩膜
  - **指数差异法**: dNDVI / dNDBI / dNDWI → 特定类型变化提取
  - **分类后比较**: 两期分类结果 → 转移矩阵 + 变化图
  - 统一接口: `detect_changes(before, after, method, **params) → ChangeResult`
- [ ] **变化语义描述** — LLM 生成 "what-where-why" 变化报告
  - 输入: 变化掩膜 + 统计信息 + 区域上下文
  - 输出: "XX区域 2023-2025 年间，约 15.3 公顷耕地转为建设用地，主要集中在城市东部扩展区"
- [ ] **ChangeDetectionToolset** — 新增 BaseToolset，3-5 个工具
  - `detect_land_cover_change`, `generate_change_matrix`, `describe_changes`

### 时间序列分析

- [ ] **time_series.py** — 遥感时间序列分析模块
  - **趋势检测**: Mann-Kendall 趋势检验 + Sen's slope
  - **断点检测**: BFAST-like 断点识别 (基于 scipy.signal)
  - **物候提取**: 生长季起止日期、峰值日期、生长季长度
  - **异常检测**: Z-score / IQR 异常时相识别
- [ ] **时序可视化** — 时间序列折线图 + 断点标注 + 趋势线
- [ ] **TimeSeriesToolset** — 新增 BaseToolset
  - `analyze_temporal_trend`, `detect_breakpoints`, `extract_phenology`

### 证据充分性评估 (闭环增强 v2)

> 参考: 论文目标/证据驱动闭环

- [ ] **分析深度评估** — QualityLoop 增加证据充分性检查
  - 评估维度: 数据覆盖度、分析方法多样性、结论支撑强度
  - 不足时: 自动追加辅助分析 (如空间统计验证、多源交叉验证)
- [ ] **置信度评分** — 分析结果附带置信度 (0-1)
  - 基于: 数据质量 × 方法适用性 × 结果一致性

### 新增 ADK Skills

- [ ] **change-detection** — 变化检测技能 (双时相 + 语义描述 + 转移矩阵)
- [ ] **temporal-analysis** — 时序分析技能 (趋势 + 断点 + 物候)

### 测试

- [ ] **test_change_detection.py** — 差异法 + 指数法 + 分类后比较 + 语义描述
- [ ] **test_time_series.py** — 趋势检测 + 断点 + 物候 + 异常
- [ ] **test_evidence_assessment.py** — 充分性评估 + 置信度计算

---

## v17.0 — 智能化与可信度

> **主题**: 从工具调用到代码生成，从结果输出到可信决策
>
> 参考: EarthLink (自进化 + 代码生成)、GeoLLM-Squad (retrieval-augmented tool selection)、smileGeo (Debate/Critique)

### 程序化执行 (Programmatic Actions)

> 参考: 论文 Action 维度 — 高端 RS Agent 动态生成 Python 代码执行分析

- [ ] **code_execution 引擎** — user_tool_engines.py 新增 `code_execution` 类型
  - Agent 生成 Python 代码片段 (限定 GeoPandas/Rasterio/NumPy/Shapely)
  - 沙箱执行: AST 白名单 + subprocess 隔离 + 超时 + 内存限制
  - 结果回注: 执行输出 (GeoDataFrame / 数值 / 图表路径) 回传到 pipeline
  - 安全: 复用已有 Python 沙箱基础设施 (User Tools Phase 2)
- [ ] **代码审查 Guardrail** — 执行前 LLM 审查生成代码的安全性
  - 检查: 文件系统越权、网络请求、危险 import、无限循环

### 幻觉检测与可信度

> 参考: 论文 Hallucination and Trustworthiness 章节

- [ ] **空间约束 Fact-Checking** — 分析结果自动验证
  - 面积合理性: 变化面积 vs 研究区总面积
  - 拓扑一致性: 变化区域不应超出研究区边界
  - 统计一致性: 各类面积之和 = 总面积
  - 实现: QualityLoop 后置检查 + PostGIS 空间查询验证
- [ ] **多源交叉验证** — 关键结论用第二数据源验证
  - 如: NDVI 变化结论 → 用 ESA WorldCover 分类数据交叉验证
- [ ] **HallucinationGuardrail 增强** — 扩展现有 Guardrail
  - 新增: 空间关系合理性检查 (距离/方位/包含关系)
  - 新增: 数值范围检查 (NDVI ∈ [-1,1], 面积 > 0, 坐标合理)

### 多智能体 Debate/Critique 模式

> 参考: smileGeo (迭代 critique + 共识融合)、HI-MAFE (多 Agent 协作 RL)

- [ ] **Debate Pipeline** — 复杂分析场景的多视角验证
  - Agent A: 主分析 (如分类)
  - Agent B: 独立验证 (如变化检测交叉验证)
  - Agent C: 统计检验 (如空间自相关验证)
  - Judge Agent: 汇总三方结果 → 一致性评估 → 最终结论
  - 实现: ADK `ParallelAgent` + 后置 Judge LlmAgent
- [ ] **Critique 机制** — Agent 间结果互评
  - 每个 Agent 输出附带 "证据强度" 标签
  - Judge 对矛盾结论要求补充分析

### 遥感领域知识库 (RAG 增强)

> 参考: WildfireGPT (RAG + 领域知识)

- [ ] **RS 领域文档库** — KnowledgeBase 预置遥感专业知识
  - 光谱特性文档 (各传感器波段参数)
  - 常用处理流程 (大气校正 → 几何校正 → 指数计算 → 分类)
  - 分类体系 (国标土地利用分类、CORINE、NLCD)
  - 数据标准规范 (OGC 标准、元数据规范)
- [ ] **法规政策文档** — 土地管理法规、生态红线标准
- [ ] **知识检索增强** — 分析时自动检索相关领域知识注入 prompt

### 测试

- [ ] **test_code_execution.py** — 沙箱执行 + 安全检查 + 结果回注
- [ ] **test_fact_checking.py** — 空间约束 + 交叉验证 + 数值范围
- [ ] **test_debate_pipeline.py** — 多 Agent 并行 + Judge 汇总 + Critique

---

## v18.0 — 高级遥感能力 (远期)

> **主题**: 多源遥感深度集成，向具身执行延伸

### 多源数据支持

- [ ] **SAR 数据处理** — Sentinel-1 GRD/SLC 基础处理
  - 辐射定标、地形校正、滤波 (Lee / Refined Lee)
  - 后向散射系数计算
  - SAR + 光学协同分析 (云覆盖时 SAR 补充)
- [ ] **高光谱分析** — 波段选择、端元提取、光谱解混
- [ ] **点云/LiDAR** — 基础点云统计 (DSM/DTM 生成、冠层高度)

### 深度学习推理

- [ ] **模型服务接口** — 统一推理 API 对接预训练模型
  - 建筑物提取 (segment-anything-geo)
  - 地物分类 (SatMAE / Prithvi)
  - 目标检测 (DOTA 预训练)
- [ ] **模型注册表** — 管理可用的 RS 预训练模型 (本地 / HuggingFace / 远程)

### 具身执行接口 (预留)

> 参考: 论文 Embodied Actions — UAV 控制、传感器调度

- [ ] **卫星任务调度接口** — 抽象 API 对接星座调度系统
- [ ] **IoT 传感器集成** — 通过 MCP Hub 连接物联网数据流
- [ ] **无人机航线规划** — 给定 AOI → 生成航线 + 拍摄参数

### 因果推理 (探索)

> 参考: 论文高级推理 — "为什么土地退化"

- [ ] **因果链构建** — 从时序变化 + 驱动因子 → 因果假设
- [ ] **反事实分析** — "如果不修建道路，该区域植被会如何变化"

---

## 标杆对标进度 (遥感智能体维度)

| 能力维度 | 论文标杆系统 | v14.3 (当前) | v15.0 后 | v16.0 后 | v17.0 后 |
|----------|------------|-------------|---------|---------|---------|
| 光谱分析 | RS-Agent, REMSA | 🔴 仅 NDVI | 🟢 15+ 指数 | 🟢 | 🟢 |
| 变化检测 | Change-Agent, MMUEChange | 🔴 无 | 🔴 | 🟢 多方法+语义 | 🟢 |
| 时序分析 | STA-CoT, EarthLink | 🔴 无 | 🔴 | 🟢 趋势+断点+物候 | 🟢 |
| 经验复用 | CangLing-KnowFlow, RS-Agent | 🟡 仅失败学习 | 🟢 Experience Pool | 🟢 | 🟢 |
| 数据质量门控 | GeoFlow | 🟡 QualityLoop | 🟢 云覆盖+自动切换 | 🟢 | 🟢 |
| 卫星数据接入 | EarthAgent | 🟡 DEM+LULC | 🟢 Sentinel-2+Landsat | 🟢 | 🟢 |
| 代码生成执行 | EarthLink, CoP | 🔴 无 | 🔴 | 🔴 | 🟢 沙箱执行 |
| 幻觉检测 | — (论文建议) | 🟡 基础 Guardrail | 🟡 | 🟡 | 🟢 空间约束验证 |
| 多 Agent Debate | smileGeo, HI-MAFE | 🔴 无 | 🔴 | 🔴 | 🟢 Debate Pipeline |
| 领域知识 RAG | WildfireGPT | 🟡 GraphRAG | 🟡 | 🟡 | 🟢 RS 专业知识库 |
| SAR/高光谱 | OceanAI, HI-MAFE | 🔴 无 | 🔴 | 🔴 | 🟡 v18.0 |
| 具身执行 | FIRE-VLM, UAV-CodeAgents | 🔴 无 | 🔴 | 🔴 | 🟡 v18.0 预留 |

---

## 参考文献

- Tang, J. et al. (2026). *Intelligent Remote Sensing Agents: A Survey*. Technical Report. [GitHub](https://github.com/PolyX-Research/Awesome-Remote-Sensing-Agents)
- CangLing-KnowFlow: 经验进化记忆 + 跨任务复用
- RS-Agent: Solution Space + Task-Aware Retrieval (18 tasks benchmark)
- GeoFlow: Agentic workflow 自动化
- Change-Agent: 多级变化解释 (mask → 语义描述)
- EarthLink: 自进化 + 代码生成执行
- WildfireGPT: RAG + 多 Agent 协作应急决策
- GeoLLM-Squad: 521 API + retrieval-augmented tool selection
- smileGeo: 去中心化多 Agent critique + 共识融合
- MMUEChange: what-where-why 变化描述范式
- STA-CoT: 时空 Chain-of-Thought 推理
