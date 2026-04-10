# Data Agent 技能清单

> 系统中所有 Skills 的完整清单：25 个内置 ADK Skills + 用户自定义 Custom Skills + Skill Bundles。
> v23.0 (ADK v1.27.2, 2026-04-10)

---

## 技能总数

| 类别 | 数量 | 存储 | 来源 |
|------|------|------|------|
| **内置 ADK Skills** | 25 | `data_agent/skills/` 目录（kebab-case） | 开发者预定义 |
| **Custom Skills** | 用户创建（每人上限 20） | PostgreSQL `agent_custom_skills` | 用户前端 CRUD |
| **Skill Bundles** | 5 内置 + 用户创建（每人上限 30） | 内置代码 + PostgreSQL `agent_skill_bundles` | 内置 + 用户组合 |

---

## 25 个内置 ADK Skills

按领域分组：

### GIS 空间分析（6 个）

| # | 技能名 | 版本 | 模式 | 描述 | Toolsets | 触发关键词 |
|---|--------|------|------|------|----------|-----------|
| 1 | **buffer-overlay** | 2.0 | Standard | 缓冲区与叠加分析。创建缓冲区、执行空间叠加（交集/合并/差集/裁剪），统计面积和属性 | GeoProcessingToolset | buffer, overlay, clip, 缓冲区, 叠加, 裁剪, 相交, 差集 |
| 2 | **coordinate-transform** | 2.0 | Standard | 坐标系转换与验证。CGCS2000/WGS84/GCJ-02/BD-09 转换，验证坐标系正确性 | GeoProcessingToolset | CRS, coordinate, 坐标系, EPSG, 重投影 |
| 3 | **geocoding** | 2.0 | Standard | 地理编码与距离计算。批量正向/逆向编码、驾车距离、POI 搜索、行政区划 | LocationToolset | geocode, 地理编码, 地址, POI, 行政区划 |
| 4 | **land-fragmentation** | 3.0 | Inversion | 土地碎片化分析与 DRL 优化（采访模式）。结构化参数收集 → FFI 指数计算 → 深度强化学习用地布局优化 | AdvancedAnalysisToolset, GeoProcessingToolset | fragmentation, FFI, 碎片化, DRL, 布局优化 |
| 5 | **site-selection** | 3.0 | Inversion | 多因素选址分析（采访模式）。排除法 + 加权叠加法，支持学校/医院/工厂等选址场景 | GeoProcessingToolset, VisualizationToolset | site selection, 选址, 适宜性, 多因素 |
| 6 | **ecological-assessment** | 2.0 | Standard | 生态环境评估。NDVI + DEM + LULC 综合生态敏感性评价 | RemoteSensingToolset, GeoProcessingToolset | ecology, NDVI, DEM, 生态, 遥感, 植被, 地形, LULC |

### 数据治理与质检（5 个）

| # | 技能名 | 版本 | 模式 | 描述 | Toolsets | 触发关键词 |
|---|--------|------|------|------|----------|-----------|
| 7 | **data-profiling** | 3.0 | Generator | 空间数据画像与质量评估。全面画像分析，四维质量评估报告模板输出。附带 `assets/data_quality_report_template.md` + `references/quality_dimensions.md` | ExplorationToolset, GovernanceToolset | profile, 画像, 数据质量, 探查, 概览, 数据评估 |
| 8 | **farmland-compliance** | 3.0 | Reviewer | 耕地合规审计。基于可替换检查清单执行结构化审查，支持耕地合规、城市规划、生态红线等多种审计场景。附带 `references/farmland_compliance_checklist.md` + `references/audit_standards.md` | GovernanceToolset | audit, compliance, 合规, 国土调查, 三调, GB/T 21010 |
| 9 | **topology-validation** | 2.0 | Standard | 拓扑质量检查。重叠/间隙/自相交检测，严重程度分级，修复建议 | GovernanceToolset | topology, 拓扑, overlap, gap, 自相交, 几何检查 |
| 10 | **data-quality-reviewer** | 1.0 | Reviewer | 数据入库前质量审查。基于可替换检查清单执行结构化审查，确保满足入库标准。检查字段标准、拓扑、完整性、CRS 一致性、敏感性分类，产出 pass/fail 审查报告。附带 `references/data_ingestion_checklist.md` | GovernanceToolset | 入库审查, 质量审查, 入库前检查, quality review, 数据验收 |
| 11 | **surveying-qc** | 1.0 | Inversion | 测绘成果质量检查与验收智能体，遵循 GB/T 24356 标准。4 阶段采访协议：任务理解 → 数据审查 → 精度核验 → 报告生成。缺陷分级 A/B/C，质量等级 优/良/合格/不合格 | GovernanceToolset, PrecisionToolset, DataCleaningToolset, ReportToolset, ExplorationToolset, FileToolset | 测绘质检, 质量检查, 质检报告, GB/T 24356, 成果验收, 精度核验 |

### 遥感（3 个）

| # | 技能名 | 版本 | 模式 | 描述 | Toolsets | 触发关键词 |
|---|--------|------|------|------|----------|-----------|
| 12 | **satellite-imagery** | 1.0 | Standard | 卫星影像数据获取与分析。5 种预置数据源模板（Sentinel-2 10m、Landsat 30m、Sentinel-1 SAR 10m、Copernicus DEM 30m、ESA/ESRI LULC 10m），支持 bbox/时间/云量筛选、预处理、多源集成 | RemoteSensingToolset | 卫星, satellite, Sentinel, Landsat, SAR, DEM, LULC, 影像, imagery, 遥感数据, 下载, 土地利用, 高程, 哨兵 |
| 13 | **spectral-analysis** | 1.0 | Standard | 遥感光谱分析。15+ 光谱指数（NDVI/EVI/NDWI/NDBI/NBR 等），智能指数推荐、云覆盖评估（光学→SAR 自动降级）、多时相对比 | RemoteSensingToolset | 光谱, spectral, NDVI, EVI, NDWI, NDBI, NBR, 植被指数, 水体指数, 城市指数, 遥感指数, 波段运算 |

### 数据库（2 个）

| # | 技能名 | 版本 | 模式 | 描述 | Toolsets | 触发关键词 |
|---|--------|------|------|------|----------|-----------|
| 14 | **postgis-analysis** | 2.0 | Standard | PostGIS 空间数据库分析。ST_* 函数查询、距离/面积/关系计算 | DatabaseToolset | PostGIS, SQL, 空间查询, ST_, 数据库 |
| 15 | **data-import-export** | 2.0 | Standard | 数据入库与导出。SHP/GeoJSON/GPKG/KML/CSV 导入 PostGIS，目录与血缘 | DatabaseToolset, DataLakeToolset | import, 入库, 导出, PostGIS, SHP, GeoJSON, GPKG, 数据目录 |

### 可视化（2 个）

| # | 技能名 | 版本 | 模式 | 描述 | Toolsets | 触发关键词 |
|---|--------|------|------|------|----------|-----------|
| 16 | **thematic-mapping** | 2.0 | Standard | 专题地图制作。自动选择最佳地图类型，配置分级方法/色彩/图例 | VisualizationToolset | map, choropleth, 专题图, 热力图, 气泡图, 制图 |
| 17 | **3d-visualization** | 2.0 | Standard | 三维可视化。deck.gl + MapLibre 3D 拉伸/柱状/弧线/散点图层，高度映射和视角调整 | VisualizationToolset | 3D, 三维, extrusion, deck.gl, 拉伸, 柱状图, 弧线图 |

### 分析（2 个）

| # | 技能名 | 版本 | 模式 | 描述 | Toolsets | 触发关键词 |
|---|--------|------|------|------|----------|-----------|
| 18 | **spatial-clustering** | 2.0 | Standard | 空间聚类与热点分析。全局 Moran's I、局部 LISA、Getis-Ord Gi* | SpatialStatisticsToolset | cluster, hotspot, 聚类, 热点, Moran, LISA, Getis-Ord |
| 19 | **advanced-analysis** | 1.0 | Standard | 高级分析。时间序列预测（ARIMA/ETS）、假设分析（What-If）、网络中心性、社区检测、可达性分析 | AdvancedAnalysisToolset | 时间序列, 预测, forecast, ARIMA, 假设分析, what-if, 网络分析, 可达性 |

### 预测与因果（2 个）

| # | 技能名 | 版本 | 模式 | 描述 | Toolsets | 触发关键词 |
|---|--------|------|------|------|----------|-----------|
| 20 | **world-model** | 1.0 | Inversion | 地理空间世界模型（Tech Preview）。AlphaEarth 嵌入 + LatentDynamicsNet 残差 CNN，JEPA 架构。1-50 年 LULC 预测，5 种情景模拟（城市蔓延/生态修复/农业集约/气候适应/基线）。4 阶段采访：区域定义 → 情景选择 → 时间参数 → 预测 | AdvancedAnalysisToolset | world model, 世界模型, 土地利用预测, LULC forecast, 情景模拟, 城市蔓延, 生态修复 |
| 21 | **rhinitis-causal-analysis** | 1.0 | Standard | 鼻炎时空因果推断。PSM/Granger/Causal Forest/GCCM 识别个体化症状触发因素（PM2.5、花粉、睡眠、压力），输出 Top 5 因果触发因子 + 置信区间 + 个性化防护建议 | CausalInferenceToolset, SpatialStatisticsToolset, VisualizationToolset | 鼻炎因果分析, 找出过敏原, 症状触发因素, 为什么症状加重, 因果推断 |

### 融合（1 个）

| # | 技能名 | 版本 | 模式 | 描述 | Toolsets | 触发关键词 |
|---|--------|------|------|------|----------|-----------|
| 22 | **multi-source-fusion** | 3.0 | Pipeline | 多源数据融合（5 步 Pipeline + Gate）。源识别 → 兼容性评估 → Schema 匹配 → 融合执行 → 质量验证，每步设 Gate 需用户确认 | FusionToolset, DatabaseToolset | fusion, 融合, 多源, merge, join, 数据整合 |

### 知识（1 个）

| # | 技能名 | 版本 | 模式 | 描述 | Toolsets | 触发关键词 |
|---|--------|------|------|------|----------|-----------|
| 23 | **knowledge-retrieval** | 1.0 | Standard | 知识库检索与管理。创建私有 KB、文档上传（文本/PDF/Word）、语义搜索、RAG 增强 | KnowledgeBaseToolset | 知识库, knowledge, RAG, 文档检索, 查询知识, 知识管理 |

### 协作（1 个）

| # | 技能名 | 版本 | 模式 | 描述 | Toolsets | 触发关键词 |
|---|--------|------|------|------|----------|-----------|
| 24 | **team-collaboration** | 2.0 | Standard | 团队协作与知识共享。团队管理、记忆存储、资产共享、审计日志 | TeamToolset, DataLakeToolset | team, share, 团队, 协作, 共享, 记忆, 审计 |

### 元技能（1 个）

| # | 技能名 | 版本 | 模式 | 描述 | Toolsets | 触发关键词 |
|---|--------|------|------|------|----------|-----------|
| 25 | **skill-creator** | 1.0 | Standard | AI 辅助技能创建。从自然语言需求自动分析、推荐 Toolset 组合、生成可执行 Skill 配置。用户预览确认后保存 | UserToolset | 创建技能, 生成技能, 新建skill, create skill, generate skill, 技能模板 |

---

## 技能设计模式分布

| 模式 | 数量 | 说明 | 代表技能 |
|------|------|------|---------|
| **Standard** | 15 | 直接响应，LLM 自主选择工具 | buffer-overlay, geocoding, spatial-clustering |
| **Inversion** | 4 | 采访模式，结构化参数收集后执行 | land-fragmentation, site-selection, surveying-qc, world-model |
| **Reviewer** | 2 | 基于可替换检查清单的结构化审查 | data-quality-reviewer, farmland-compliance |
| **Generator** | 1 | 模板驱动输出，按标准化格式生成报告 | data-profiling |
| **Pipeline** | 1 | 多步工作流 + Gate 确认 | multi-source-fusion |

```
Standard (直接响应)    ████████████████████████████████████████████████ 15 (60%)
Inversion (采访模式)   ████████████████ 4 (16%)
Reviewer (检查清单)    ████████ 2 (8%)
Generator (模板输出)   ████ 1 (4%)
Pipeline (多步工作流)  ████ 1 (4%)
```

---

## 技能领域分布

```
GIS 空间分析      ██████████████████ 6 (24%)
数据治理与质检    ███████████████ 5 (20%)
遥感              █████████ 3 (12%)  [含 ecological-assessment 跨域]
数据库            ██████ 2 (8%)
可视化            ██████ 2 (8%)
分析              ██████ 2 (8%)
预测与因果        ██████ 2 (8%)
融合              ███ 1 (4%)
知识              ███ 1 (4%)
协作              ███ 1 (4%)
元技能            ███ 1 (4%)
```

---

## 技能加载机制

### 三级增量加载

| 级别 | 加载内容 | 时机 | 开销 |
|------|---------|------|------|
| **L1 Metadata** | name, description, domain, intent_triggers | 应用启动 | 极低（仅读 YAML frontmatter） |
| **L2 Instructions** | 完整 Prompt 文本（可达数千字） | 路由匹配到相关 Skill 时 | 低（读文件） |
| **L3 Resources** | 附加资源文件（参考数据、模板） | Skill 执行时 | 按需 |

### SKILL.md 结构

```yaml
---
name: data-profiling                    # 必须与目录名一致 (kebab-case)
description: "空间数据画像与质量评估技能"   # 简短描述
metadata:
  domain: "governance"                   # 领域分类
  version: "2.0"                         # 版本号
  intent_triggers: "profile, 画像, 数据质量"  # 逗号分隔的触发关键词
---

# 空间数据画像与质量评估技能

## 职责
数据画像是所有空间分析的第一步...

## 分析维度
| 检查项 | 内容 | 关注点 |
|--------|------|--------|
| ... | ... | ... |
```

### skill.yaml 结构（替代格式）

部分 Skill 使用 `skill.yaml` 而非 `SKILL.md`：

```yaml
name: rhinitis-causal-analysis
description: "鼻炎时空因果推断分析"
category: health-analytics
version: "1.0.0"
model: gemini-2.5-pro
toolsets:
  - CausalInferenceToolset
  - SpatialStatisticsToolset
  - VisualizationToolset
trigger_keywords:
  - 鼻炎因果分析
  - 症状触发因素
```

---

## Skill Bundles（技能包）

### 5 个内置 Bundle

通过 `skill_bundles.py` 中的 `build_all_skills_toolset()` 暴露给 Planner：

| Bundle | 包含 Toolset | 覆盖场景 |
|--------|-------------|---------|
| **SPATIAL_ANALYSIS** | ExplorationToolset, GeoProcessingToolset, LocationToolset, RemoteSensingToolset, SpatialStatisticsToolset, AnalysisToolset, DatabaseToolset, FileToolset | 空间分析全栈 |
| **DATA_QUALITY** | ExplorationToolset, GovernanceToolset, DataCleaningToolset, PrecisionToolset | 数据治理 |
| **VISUALIZATION** | VisualizationToolset, ChartToolset, ReportToolset | 可视化制图 |
| **DATABASE** | DatabaseToolset, NL2SQLToolset, SemanticLayerToolset | 数据库操作 |
| **COLLABORATION** | TeamToolset, MemoryToolset, KnowledgeBaseToolset | 团队协作 |

**运行机制**：`build_all_skills_toolset()` 使用 ADK `SkillToolset` 将 `skills/` 目录下的 Skill 以增量加载方式注册给 Planner，Planner 根据用户意图动态激活相关 Skill。

### 用户自定义 Bundle

用户可在前端组合多个 Toolset + ADK Skills 为可复用的技能包：

| 字段 | 说明 |
|------|------|
| `bundle_name` | 技能包名称 |
| `toolset_names` | 工具集组合 |
| `skill_names` | ADK Skill 组合 |
| `intent_triggers` | 意图触发 |

**用途**: 预配置的工具+技能组合，一键分配给自定义 Skill 或工作流。每用户上限 30 个。

---

## 用户自定义 Custom Skills

用户可在前端"能力"Tab 创建自定义 Skill，每个 Skill 是一个独立的 LlmAgent：

| 字段 | 说明 | 限制 |
|------|------|------|
| `skill_name` | 技能名称 | 2-100 字符，字母/中文/连字符 |
| `instruction` | 指令（定义 Agent 行为） | 10,000 字符上限，Prompt 注入检测 |
| `description` | 简短描述 | 最大 10,000 字符 |
| `toolset_names` | 工具集选择 | 从 **40 个 Toolset** 中多选 |
| `trigger_keywords` | 触发关键词 | 逗号分隔，子串匹配 |
| `model_tier` | 模型等级 | fast / standard / premium |
| `is_shared` | 团队共享 | 可选 |
| `category` | 分类标签 | v14.1 |
| `tags` | 标签列表 | v14.1 |
| `version` | 版本号 | v14.1，自增 |

### 可选 Toolset（40 个）

```
ExplorationToolset, GeoProcessingToolset, LocationToolset, AnalysisToolset,
VisualizationToolset, DatabaseToolset, FileToolset, MemoryToolset, AdminToolset,
RemoteSensingToolset, SpatialStatisticsToolset, SemanticLayerToolset,
StreamingToolset, TeamToolset, DataLakeToolset, McpHubToolset, FusionToolset,
KnowledgeGraphToolset, KnowledgeBaseToolset, AdvancedAnalysisToolset,
SpatialAnalysisTier2Toolset, WatershedToolset, UserToolset, VirtualSourceToolset,
ChartToolset, GovernanceToolset, DataCleaningToolset, SparkToolset, StorageToolset,
ReportToolset, PrecisionToolset, CausalInferenceToolset, DreamerToolset,
ToolEvolutionToolset, WorldModelToolset, NL2SQLToolset, CausalWorldModelToolset,
LLMCausalToolset, OperatorToolset, SkillBundlesToolset
```

### 安全机制

- **Prompt 注入防御**：禁止 "system:", "ignore previous", "override:", "<<SYS>>" 等模式
- **名称校验**：`^[\w\u4e00-\u9fff\-]+$`（字母、中文、连字符）
- **惰性加载**：`_RegistryProxy` 延迟构建 Toolset 注册表，避免启动开销

### 运行时

`build_custom_agent(skill)` 从 DB 记录动态构建 `LlmAgent` 实例，通过 Workflow Engine 的 `custom_skill` 节点类型或 Planner 动态调用参与管线执行。

---

*本文档基于 GIS Data Agent v23.0 (ADK v1.27.2, 25 Skills, 40 Toolsets) 刷新，2026-04-10。*
