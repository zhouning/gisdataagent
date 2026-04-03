# GIS Data Agent: 多模态数据智能化语义融合分析报告

## 1. 核心功能概述
**多模态数据智能化语义融合 (Multi-Modal Fusion Engine, MMFE)** 是本项目中用于处理异构地理空间数据的核心组件。它通过自动化流水线，解决了矢量 (Vector)、栅格 (Raster)、表格 (Tabular)、点云 (Point Cloud) 及实时流 (Stream) 数据之间的空间与属性关联难题。

## 2. 架构设计：五阶段流水线
MMFE 采用标准化的五阶段处理流水线设计，确保了数据处理的严谨性与算子的可扩展性：

1.  **数据探测 (Profiling)**
    *   **职责**：自动识别输入模态，提取 CRS（坐标系）、空间范围、波段、分辨率及字段统计信息。
    - **实现**：`profile_source()` 方法调用模态专用的分析器。

2.  **兼容性评估 (Compatibility Assessment)**
    *   **职责**：计算数据集间的融合可行性得分（0.0-1.0）。
    - **维度**：评估空间重叠度 (IoU)、坐标系冲突、字段语义匹配度。

3.  **智能语义对齐 (Semantic Alignment)**
    *   **职责**：消除数据间的“语境冲突”。
    - **核心机制**：
        - **坐标转换**：自动重投影至统一坐标系。
        - **单位换算**：基于正则识别和换算（如 `m2` 自动转 `mu`）。
        - **列名对齐**：处理同名或同义字段重叠。

4.  **融合执行引擎 (Fusion Execution)**
    *   **职责**：执行核心空间/属性计算。
    - **算法库**：包含 `spatial_join`、`overlay`、`zonal_statistics`、`raster_vectorize`、`nearest_join` 等 10 种核心策略。
    - **自动化决策**：基于数据感知策略打分（v5.6+），根据 IoU 和几何类型自动路由最佳算子。

5.  **质量验证与反馈 (Quality Validation)**
    *   **职责**：融合后的质量门控。
    - **指标**：检测空值率、拓扑有效性、异常值（IQR）、小碎多边形比例。

## 3. 语义融合的实现机制
语义融合的”智能”主要体现在**四层渐进式匹配策略**（v7.1 新增 LLM Schema 对齐作为可选高层方案）：

*   **绝对匹配**：字段名称的字面完全匹配。
*   **知识库等价组**：依托 `semantic_catalog.yaml` 中的行业本体库，实现 `[“area”, “面积”, “zmj”]` 等跨语言/简写的语义关联。
*   **向量嵌入匹配**（v7.0）：Gemini `text-embedding-004` 语义向量空间，cosine ≥ 0.75，默认关闭。
*   **单位感知匹配**：智能识别 `_m2`、`_ha` 等后缀，并自动应用转换系数。
*   **模糊序列匹配**：利用 Jaccard Token 相似度与 Python 序列匹配算法进行保底对齐。
*   **LLM Schema 对齐**（v7.1 新增）：Gemini 2.5 Flash 将两表 Schema + 采样数据 → 结构化 JSON 映射配置，通过 `use_llm_schema=True` 启用。

## 4. 现状评估与改进建议

### 4.1 现有优势
*   **算子丰富**：完整覆盖了主流 GIS 空间与非空间融合场景。
*   **自动化程度高**：从 CRS 到单位换算均实现了“无感”处理。
*   **反馈闭环**：详尽的质量评估报告能引导 LLM Agent 发现并修正数据问题。

### 4.2 改进方向（不足之处）— ✅ 全部已在 v7.0 实现
针对系统当前的智能化深度和性能瓶颈，提出以下优化建议：

1.  **引入向量 Embedding 语义匹配** ✅ v7.0 已实现
    *   **不足**：目前过度依赖硬编码别名字典，对长尾字段和复杂语境理解不足。
    *   **建议**：集成 `sentence-transformers` 等模型，将字段名转为向量进行语义相似度计算，提升匹配的通用性。
    *   **v7.0 实现**：使用 Gemini `text-embedding-004` API（避免 ~400MB sentence-transformers 依赖），插入 Tier 2.5 嵌入层，cosine 阈值 ≥0.75，模块级缓存，API 失败静默降级。通过 `use_embedding=”true”` 显式启用。
    *   **v7.1 补充**：嵌入匹配实现已从单体文件拆分至 `fusion/matching.py` 模块，缓存机制不变。

2.  **LLM 增强的策略路由决策** ✅ v7.0 已实现 → ⚠️ v7.1 已弃用（改为 LLM Schema 对齐）
    *   **不足**：融合算子的选择目前仍主要通过硬编码的规则打分决策。
    *   **建议**：将兼容性评估报告直接暴露给 LLM，允许模型基于用户的自然语言意图（如”按人口密度筛选异常地块”）来动态组合、规划融合步骤。
    *   **v7.0 实现**：新增 `strategy=”llm_auto”` 选项，调用 Gemini 2.0 Flash 进行策略推理，接收候选策略 + 数据元信息 + `user_hint` 参数，返回 JSON `{strategy, reasoning}`，失败回退规则评分。
    *   **v7.1 调整**：技术评审（`technical-review-mmfe.md`）指出策略路由是纯规则决策不应交由 LLM，已弃用 `_llm_select_strategy()`，`strategy=”llm_auto”` 回退为规则评分。LLM 职责转向更适合的 **Schema 对齐**（`fusion/schema_alignment.py`），通过 `use_llm_schema=True` 启用。

3.  **从”物理合并”转向”地理实体融合”** ✅ v7.0 已实现
    *   **不足**：目前的产出多为”宽表”，缺乏对地理对象的结构化理解。
    *   **建议**：建立**地理知识图谱**架构，将多模态数据映射为地理实体的属性与关系边，实现特征级深度融合。
    *   **v7.0 实现**：新建 `knowledge_graph.py` (~625行)，使用 networkx DiGraph 构建内存图，7 种实体类型 + 5 种关系类型，STRtree 空间索引加速，`KnowledgeGraphToolset` 提供 3 个工具（构建/查询/导出）。

4.  **分布式与核外计算扩展** ✅ v7.0 已实现
    *   **不足**：依赖单机内存（GeoPandas/Rasterio），在处理大规模（百万级图斑）或超高分辨率影像时存在 OOM 风险。
    *   **建议**：底层适配 `Dask-GeoPandas` 或 `Apache Sedona`，支持分布式大数据环境下的并行融合处理。
    *   **v7.0 实现**：利用已有 dask + fiona 实现透明分块处理。阈值 500K行/500MB，fiona 分块读取矢量文件，dask.dataframe 延迟计算大 CSV，分块 spatial_join。对调用方透明，小文件行为不变。
    *   **v7.1 补充**：新增 PostGIS 计算下推（`fusion/strategies/postgis_pushdown.py`），>10万行 PostGIS 数据源自动生成 SQL（ST_Intersects/ST_Intersection/LATERAL），彻底避免大表拉回内存。

## 5. v7.1 架构重构（2026-03-09）

v7.1 基于 `docs/technical-review-mmfe.md` 技术评审报告，完成了 4 阶段系统性重构：

| 阶段 | 重构内容 | 解决的缺陷 |
|------|---------|-----------|
| Phase 1 | 工程解耦：单体 → `fusion/` 包 (22 模块)，策略模式 | P0~P2 架构臃肿 |
| Phase 2 | AI 精简：LLM 路由弃用 + LLM Schema 对齐新增 | P2 LLM 滥用 + P2 语义匹配伪智能 |
| Phase 3 | 异步化：4 工具 `async` + `asyncio.to_thread()` | P0 事件循环阻塞 |
| Phase 4 | PostGIS 下推：3 种 SQL 策略，>10万行自动下推 | P1 内存计算瓶颈 |

**架构变更**：
- `fusion_engine.py` (~2100行) → `fusion/` 包 (22模块，26文件，~121KB) + 薄代理层 (72行)
- 10 种策略实现独立为 `fusion/strategies/*.py`，通过 `_STRATEGY_REGISTRY` 注册
- 新增 `fusion/schema_alignment.py`（LLM Schema 对齐）、`fusion/strategies/postgis_pushdown.py`（计算下推）
- FusionSource 扩展：`postgis_table`、`postgis_srid` 字段
- 质量验证扩展至 10 维（+CRS一致性、拓扑验证、KS分布偏移）

## 6. v17.0 融合 v2.0 增强（2026-04-04）

v17.0 在 v7.1 架构基础上新增 4 大模块（6 个新文件，~1700 行），模块总数从 22 扩展到 28，实现从「能融合」到「融合好、解释清、冲突明」的质变。所有新功能 opt-in，零破坏性变更。

### 6.1 新增 4 大模块

| 模块 | 文件 | 行数 | 核心能力 |
|------|------|------|---------|
| 时序对齐 | `fusion/temporal.py` | ~400 | 多时区标准化 + linear/nearest/spline 插值 + 轨迹融合 + 多期变化检测 + 时序一致性验证 |
| 语义增强-本体 | `fusion/ontology.py` | ~300 | GIS 领域本体 (15 等价组 + 8 推导规则 + 5 推理规则) + Tier 1.5 匹配 |
| 语义增强-LLM | `fusion/semantic_llm.py` | ~250 | Gemini 2.5 Flash 字段语义分类 + 可推导字段推断 + 深度语义匹配 |
| 语义增强-KG | `fusion/kg_integration.py` | ~200 | 桥接 GeoKnowledgeGraph + 实体关系丰富 + KG 辅助冲突解决 |
| 冲突消解 | `fusion/conflict_resolver.py` | ~350 | 6 策略 + 置信度评分 + 来源标注 + `_fusion_conflicts` 列 |
| 可解释性 | `fusion/explainability.py` | ~200 | 逐要素元数据 + 质量热力图 + 融合溯源 + 模板化决策解释 |

### 6.2 语义匹配升级（6 层 → 7 层）

| 层级 | 名称 | 置信度 | 版本 |
|------|------|--------|------|
| Tier 1 | 精确匹配（大小写不敏感）| 1.0 | v5.6 |
| **Tier 1.5** | **本体推理匹配** | **0.85** | **v17.0** |
| Tier 2 | 等价组匹配 | 0.8 | v5.6 |
| Tier 2.5a | LLM Schema 对齐 | LLM 输出 | v7.1 |
| Tier 2.5b | 向量嵌入匹配 | 0.78 | v7.0 |
| Tier 3 | 单位感知匹配 | 0.75 | v5.6 |
| Tier 4 | 模糊序列匹配 | 0.5-0.7 | v5.6 |

### 6.3 execute_fusion() 签名扩展

```python
def execute_fusion(
    aligned_data, strategy, sources, params=None, report=None, user_hint="",
    # v2 parameters (all opt-in, default off)
    temporal_config: dict | None = None,      # 时序预对齐配置
    conflict_config: dict | None = None,      # 冲突消解配置 (strategy + priorities)
    enable_explainability: bool = False,       # 逐要素可解释性
    enable_kg: bool = False,                   # 知识图谱增强
) -> FusionResult  # 扩展: +explainability_path +conflict_summary +temporal_log
```

### 6.4 数据库与 API 扩展

- **Migration 049**: `agent_fusion_operations` +4 列 (temporal_alignment_log, semantic_enhancement_log, conflict_resolution_log, explainability_metadata) + `agent_fusion_ontology_cache` 新表
- **5 个新 REST API**: /api/fusion/{quality|lineage|conflicts}/{id}, /api/fusion/operations, /api/fusion/temporal-preview
- **前端**: `FusionQualityTab.tsx` — 融合质量监控面板 (操作列表 + 质量徽章 + 详情展开)

### 6.5 测试覆盖

- 84 个新测试（5 个测试文件）
- 214 个 fusion 测试全部通过 (130 existing + 84 new)
- 3100+ 全平台测试零回归

---
**文档版本**：v1.0 → v2.0 (2026-03-05 更新，标注 v7.0 实现状态) → v3.0 (2026-03-09 更新，标注 v7.1 重构状态) → v4.0 (2026-04-04 更新，标注 v17.0 融合 v2.0 增强)
**生成日期**：2026-04-04
