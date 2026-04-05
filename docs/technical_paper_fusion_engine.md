# 面向GIS智能体的多模态空间数据智能融合引擎：架构设计与实现

## Multi-Modal Spatial Data Intelligent Fusion Engine for GIS Agent Systems: Architecture Design and Implementation

---

**摘要**

地理信息系统（GIS）应用中，异构多模态数据的融合是一项长期存在的技术挑战。不同数据源在坐标参考系统（CRS）、空间分辨率、字段语义、时间粒度等维度上的差异，使得跨模态数据融合难以自动化。本文提出一种面向GIS智能体系统的多模态空间数据智能融合引擎（Multi-Modal Fusion Engine, MMFE），该引擎采用"画像→评估→对齐→融合→验证"五阶段流水线架构，支持矢量、栅格、表格、点云、实时流五种数据模态，实现了10种融合策略的自动选择与执行。引擎通过策略矩阵（Strategy Matrix）机制实现数据类型对到融合算法的自动映射，通过四层渐进式语义匹配（精确匹配→等价组→单位感知→模糊匹配）解决中英文GIS字段的跨语言匹配问题，通过多维兼容性评分模型量化数据源间的融合可行性。v5.6版本借鉴MGIM（Masked Geographical Information Model）的上下文感知推理思想，引入了数据感知策略评分、多源融合编排（N>2数据源）、自动单位检测与转换、以及增强质量验证等关键改进。v7.0版本引入向量嵌入语义匹配（Gemini text-embedding-004）、地理知识图谱（networkx DiGraph）和分布式/核外计算（dask + fiona）。v7.1版本完成了4阶段工程重构：单体拆包（22模块 fusion/ 包）、AI职责纠偏（LLM路由弃用 + LLM Schema对齐新增）、异步化（asyncio.to_thread）、PostGIS计算下推（3种SQL策略，>10万行自动下推）。实验表明，该引擎在147个单元测试中通过率100%，覆盖了所有核心路径，并已集成到一个拥有19个工具集、31个REST API端点的生产级GIS智能体平台中。

**关键词**：多模态数据融合；GIS智能体；语义对齐；空间数据互操作；策略矩阵；模糊匹配；大语言模型

---

## 1 引言

### 1.1 研究背景

随着空间信息技术的快速发展，地理空间数据的来源和形态日趋多样化。一个典型的国土空间规划项目可能同时涉及：高分辨率遥感影像（栅格数据）、土地利用现状矢量图层、社会经济统计表格、城市三维模型点云数据、以及物联网设备产生的实时流数据。这些异构数据模态在坐标参考系统、空间分辨率、属性字段命名、度量单位、时间粒度等方面存在显著差异，传统的手动融合方式不仅耗时费力，而且容易引入人为错误。

与此同时，基于大语言模型（LLM）的智能体系统在空间分析领域展现出了强大的潜力。这类系统能够理解自然语言指令，自动编排分析工具链，但面对多模态数据融合任务时，仍面临两个核心挑战：

1. **语义鸿沟**：不同数据源中表示相同概念的字段可能使用完全不同的命名（如面积字段在不同数据集中可能命名为 `area`、`zmj`、`TBMJ`、`面积`），LLM难以自动建立这些字段间的等价关系。

2. **策略选择**：不同数据模态组合需要不同的融合策略（矢量与栅格需要分区统计，矢量与表格需要属性连接），这种策略选择逻辑难以仅通过LLM的提示词工程来可靠实现。

### 1.2 研究目标

本文设计并实现了一个多模态空间数据智能融合引擎（MMFE），其核心目标包括：

- 支持5种数据模态（矢量、栅格、表格、点云、实时流）的自动识别与画像
- 实现10种融合策略的类型驱动自动选择
- 解决中英文GIS字段的跨语言语义匹配问题
- 提供融合结果的自动化质量验证与血缘追踪
- 作为自包含算法模块无缝集成到现有GIS智能体框架中

### 1.3 与现有工作的关系

本引擎的架构设计参考了同系统中已有的深度强化学习（DRL）耕地优化引擎的模式——自包含算法模块 + 工具集封装（BaseToolset）。DRL引擎（`drl_engine.py`，约385行）实现了基于 Gymnasium 的环境定义和 MaskablePPO 策略训练，通过 `AnalysisToolset` 的两个工具函数（`ffi` 和 `drl_model`）暴露给智能体。MMFE采用相同的模式，v7.1 版本已从单体文件重构为标准 Python 包 `data_agent/fusion/`（22 个模块，~121KB），通过 `FusionToolset` 的四个异步工具函数暴露给智能体，确保与现有架构的一致性和可维护性。原 `fusion_engine.py` 保留为薄代理层，通过 `from data_agent.fusion import *` 实现向后兼容。

---

## 2 系统架构

### 2.1 总体架构

MMFE采用五阶段流水线架构，每个阶段有明确的输入、输出和职责边界：

```
┌─────────────────────────────────────────────────────────────────────┐
│                        用户自然语言输入                              │
│         "把遥感NDVI、地块矢量、气象站点CSV融合分析"                   │
└───────────────────────────┬─────────────────────────────────────────┘
                            │
                            ▼
┌─── Stage 1: 数据画像 (Profiling) ──────────────────────────────────┐
│   profile_source() → FusionSource                                  │
│   ├─ _profile_vector()    : GeoPandas read → CRS/bounds/columns    │
│   ├─ _profile_raster()    : Rasterio read → bands/resolution/stats │
│   ├─ _profile_tabular()   : Pandas read → columns/dtypes/stats     │
│   ├─ _profile_point_cloud(): laspy read → bounds/point_count       │
│   └─ _detect_data_type()  : 扩展名 → 数据模态枚举                  │
│   输出: List[FusionSource] — 每个源的完整元数据画像                  │
└───────────────────────────┬─────────────────────────────────────────┘
                            │
                            ▼
┌─── Stage 2: 兼容性评估 (Compatibility Assessment) ─────────────────┐
│   assess_compatibility() → CompatibilityReport                     │
│   ├─ CRS 一致性检查       : 集合比较 {s.crs for s in sources}       │
│   ├─ 空间范围重叠 (IoU)   : BBox intersection / union               │
│   ├─ 字段语义匹配         : 四层渐进式 (精确→等价组→单位感知→模糊)   │
│   ├─ 策略推荐             : STRATEGY_MATRIX[type_pair] + 数据感知评分  │
│   └─ 综合评分             : 4维加权评分 → overall_score ∈ [0,1]      │
│   输出: CompatibilityReport — 评分/推荐策略/警告列表                 │
└───────────────────────────┬─────────────────────────────────────────┘
                            │
                            ▼
┌─── Stage 3: 语义对齐 (Semantic Alignment) ─────────────────────────┐
│   align_sources() → (List[aligned_data], List[log])                │
│   ├─ CRS 统一             : to_crs(target_crs) 重投影               │
│   ├─ 数据加载             : 按模态分类加载为内存对象                  │
│   ├─ 列名冲突消解         : _resolve_column_conflicts() → _right后缀│
│   └─ 单位转换             : _apply_unit_conversions() 自动数值转换   │
│   输出: List[(data_type, data_object)] — 对齐后的内存数据            │
└───────────────────────────┬─────────────────────────────────────────┘
                            │
                            ▼
┌─── Stage 4: 融合执行 (Fusion Execution) ───────────────────────────┐
│   execute_fusion() → FusionResult                                  │
│   ├─ 策略选择             : "auto" → _auto_select_strategy() + 评分  │
│   ├─ 多源编排             : N>2 → _orchestrate_multisource() 逐步合并│
│   ├─ 策略执行             : _STRATEGY_REGISTRY[strategy](data,params)│
│   ├─ 结果持久化           : GeoJSON 输出到用户沙箱目录               │
│   └─ 质量验证             : validate_quality() 自动触发              │
│   输出: FusionResult — 路径/行列数/质量分/血缘/耗时                  │
└───────────────────────────┬─────────────────────────────────────────┘
                            │
                            ▼
┌─── Stage 5: 质量验证 (Quality Validation) ─────────────────────────┐
│   validate_quality() → {score, warnings, details}                    │
│   ├─ 空结果检测           : len(data) == 0 → score = 0             │
│   ├─ 空值率检查           : 逐列 null% > 50% → 警告 + 扣分          │
│   ├─ 几何有效性           : is_valid 检查 → 无效比例扣分             │
│   ├─ 完整性比较           : output_rows / max_source_rows            │
│   ├─ 异常值检测           : IQR 离群值标记 (v5.6)                    │
│   ├─ 微面多边形检测       : area < 0.1% median (v5.6)               │
│   └─ 列完整性追踪         : 融合后列数 / 源列数之和 (v5.6)           │
│   输出: {score: 0-1, warnings: [...], details: {...}}                │
└─────────────────────────────────────────────────────────────────────┘
```

### 2.2 核心数据结构

引擎定义了三个核心数据类（`@dataclass`），分别对应流水线的输入、中间状态和输出：

**表1：FusionSource 数据画像结构**

| 字段 | 类型 | 说明 | 适用模态 |
|------|------|------|----------|
| `file_path` | `str` | 数据文件路径或 `"postgis://schema.table"` | 全部 |
| `data_type` | `str` | 数据模态枚举值 | 全部 |
| `crs` | `str \| None` | 坐标参考系统标识符（如 `EPSG:4326`） | 矢量/栅格/点云 |
| `bounds` | `tuple \| None` | 空间范围 `(minx, miny, maxx, maxy)` | 矢量/栅格/点云 |
| `row_count` | `int` | 要素/行计数 | 矢量/表格/点云 |
| `columns` | `list[dict]` | 列信息 `[{name, dtype, null_pct}]` | 全部 |
| `geometry_type` | `str \| None` | 几何类型（如 `Polygon`, `Point`） | 矢量 |
| `temporal_range` | `tuple \| None` | 时间范围（预留） | 实时流 |
| `semantic_domain` | `str \| None` | 语义领域标签 | 全部（可选） |
| `stats` | `dict` | 列级统计 `{col: {min, max, mean}}` 或 `{unique}` | 全部 |
| `band_count` | `int` | 波段数 | 栅格 |
| `resolution` | `tuple \| None` | 空间分辨率 `(x_res, y_res)` | 栅格 |
| `postgis_table` | `str \| None` | PostGIS 表名 `schema.table`（v7.1 计算下推） | 矢量 |
| `postgis_srid` | `int \| None` | PostGIS SRID（v7.1 计算下推） | 矢量 |

**表2：CompatibilityReport 兼容性报告结构**

| 字段 | 类型 | 说明 |
|------|------|------|
| `crs_compatible` | `bool` | 所有数据源CRS是否一致 |
| `spatial_overlap_iou` | `float` | 边界框交并比 ∈ [0,1] |
| `temporal_aligned` | `bool \| None` | 时间范围是否对齐（预留） |
| `field_matches` | `list[dict]` | 语义匹配的字段对 `[{left, right, confidence, match_type, left_unit?, right_unit?}]` |
| `overall_score` | `float` | 综合兼容性评分 ∈ [0,1] |
| `recommended_strategies` | `list[str]` | 推荐的融合策略列表 |
| `warnings` | `list[str]` | 兼容性问题警告信息 |

**表3：FusionResult 融合结果结构**

| 字段 | 类型 | 说明 |
|------|------|------|
| `output_path` | `str` | 输出文件路径（GeoJSON） |
| `strategy_used` | `str` | 实际使用的融合策略名称 |
| `row_count` | `int` | 输出要素/行数 |
| `column_count` | `int` | 输出属性列数（不含 geometry） |
| `quality_score` | `float` | 质量验证评分 ∈ [0,1] |
| `quality_warnings` | `list[str]` | 质量问题列表 |
| `alignment_log` | `list[str]` | 对齐操作日志记录 |
| `duration_s` | `float` | 融合执行耗时（秒） |
| `provenance` | `dict` | 血缘信息 `{sources, strategy, params}` |

### 2.3 模块架构（v7.1 重构）

v7.1 版本将单体 `fusion_engine.py`（~2100行）重构为标准 Python 包 `data_agent/fusion/`，共 22 个模块、26 个文件（~121KB），遵循单一职责原则：

```
data_agent/fusion/                    # 核心算法包 (~121KB)
├── __init__.py                       # 公共 API 导出
├── models.py                         # FusionSource/CompatibilityReport/FusionResult 数据类
├── constants.py                      # 策略矩阵、单位转换、阈值常量
├── profiling.py                      # 5 种模态画像器 + PostGIS 画像
├── matching.py                       # 4 层语义字段匹配（分词→句法→嵌入→等价组）
├── compatibility.py                  # CRS/空间重叠/字段匹配兼容性评估
├── alignment.py                      # CRS 统一、单位转换、列冲突消解
├── execution.py                      # 策略选择（规则评分）、编排、多源融合
├── validation.py                     # 10 维质量评分
├── io.py                             # 大数据集分块 I/O（500K 行 / 500MB 阈值）
├── raster_utils.py                   # 栅格重投影与重采样
├── llm_routing.py                    # LLM 策略路由（已弃用，保留兼容）
├── schema_alignment.py               # LLM Schema 对齐（opt-in，Gemini 2.5 Flash）
├── db.py                             # 融合操作记录（agent_fusion_operations 表）
└── strategies/                       # 策略实现目录
    ├── __init__.py                   # _STRATEGY_REGISTRY 注册表
    ├── spatial_join.py               # 空间连接 + 大数据集分块（50K）
    ├── overlay.py                    # 叠置分析
    ├── nearest_join.py               # 最近邻连接
    ├── attribute_join.py             # 属性连接 + 自动键检测
    ├── zonal_statistics.py           # 分区统计
    ├── point_sampling.py             # 点采样
    ├── band_stack.py                 # 波段堆叠 + 自动重采样
    ├── time_snapshot.py              # 时间快照融合
    ├── height_assign.py              # 点云高度赋值（laspy + KDTree）
    ├── raster_vectorize.py           # 栅格矢量化
    └── postgis_pushdown.py           # PostGIS 计算下推（v7.1 新增）

data_agent/fusion_engine.py           # 薄代理层 (~72行，向后兼容)
├── from data_agent.fusion import *   # 重导出全部符号

data_agent/toolsets/fusion_tools.py   # ADK 工具封装 (~230行)
├── FusionToolset(BaseToolset)        # 4 个 async 工具函数
├── profile_fusion_sources()          # 画像
├── assess_fusion_compatibility()     # 兼容性评估
├── fuse_datasets()                   # 融合执行（含错误恢复指导）
└── validate_fusion_quality()         # 质量验证

agent.py (智能体集成)
├── FusionToolset                     # 注册到 3 个 Agent
├── KnowledgeGraphToolset             # 注册到 2 个 Agent
└── prompts/general.yaml              # 融合操作指引 + 知识图谱指引
```

**模块间依赖关系**：

```
fusion/__init__.py ─── 聚合导出 ──→ models/constants/profiling/matching/
                                     compatibility/alignment/execution/
                                     validation/io/db/strategies

fusion/profiling.py ──→ gis_processors._resolve_path()
                   ──→ db_engine.get_engine() (PostGIS 画像)

fusion/matching.py ──→ google.genai (嵌入向量, opt-in)
                   ──→ semantic_layer.py (目录等价组)

fusion/execution.py ──→ strategies/* (策略注册表)
                    ──→ matching._find_field_matches()
                    ──→ validation.validate_quality()
                    ──→ strategies/postgis_pushdown.py (>10万行自动下推)

fusion/db.py ──→ db_engine.get_engine()
             ──→ user_context.current_user_id

fusion/schema_alignment.py ──→ google.genai (LLM Schema 对齐, opt-in)

toolsets/fusion_tools.py ──→ fusion/* (核心算法)
                         ──→ asyncio.to_thread() (异步包装)
                         ──→ gis_processors._resolve_path()
```

**v7.1 重构要点**：
- 每个模块严格遵循单一职责，最大模块 matching.py (16KB)、execution.py (14KB)
- 策略实现独立为 `strategies/` 子包，每个策略一个文件，便于扩展
- PostGIS 计算下推作为独立策略模块 `postgis_pushdown.py`
- 薄代理层 `fusion_engine.py` 确保现有代码无需修改
- Mock 目标从 `fusion_engine.X` 变为 `fusion.module.X`（如 `fusion.db.get_engine`）

---

## 3 核心算法

### 3.1 策略矩阵与数据感知策略选择

策略矩阵是MMFE的核心调度机制，它将数据类型对映射到可用的融合策略列表：

**表4：策略矩阵定义**

| 数据类型对 | 可用策略 | 首选策略 |
|-----------|---------|---------|
| (vector, vector) | spatial_join, overlay, nearest_join | 数据感知评分 |
| (vector, raster) | zonal_statistics, point_sampling | 数据感知评分 |
| (raster, vector) | zonal_statistics, point_sampling | 数据感知评分 |
| (raster, raster) | band_stack | band_stack |
| (vector, tabular) | attribute_join | attribute_join |
| (tabular, vector) | attribute_join | attribute_join |
| (vector, stream) | time_snapshot | time_snapshot |
| (stream, vector) | time_snapshot | time_snapshot |
| (vector, point_cloud) | height_assign | height_assign |
| (point_cloud, vector) | height_assign | height_assign |
| (raster, tabular) | raster_vectorize | raster_vectorize |

#### 3.1.1 基础策略查表

自动策略选择的第一步是类型对查表：

```
输入: aligned_data (已对齐的数据列表), sources (源画像列表)
输出: strategy_name (字符串)

1. 提取前两个数据源的类型: type_pair = (aligned_data[0][0], aligned_data[1][0])
2. 查询策略矩阵: strategies = STRATEGY_MATRIX.get(type_pair, [])
3. 若为空, 尝试反转类型对: strategies = STRATEGY_MATRIX.get(reverse(type_pair), [])
4. 若仍为空, 抛出 ValueError
5. 若仅一个候选策略, 直接返回
6. 若有多个候选策略, 进入数据感知评分阶段
```

#### 3.1.2 数据感知策略评分（v5.6 新增）

v5.6 版本借鉴 MGIM（Masked Geographical Information Model）的上下文感知推理思想，引入了数据感知策略评分机制 `_score_strategies()`。当策略矩阵返回多个候选策略时，评分器根据数据的空间特征动态选择最优策略，而非简单返回第一个候选项。

评分因子包括：

| 评分因子 | 影响的策略选择 | 权重 |
|---------|--------------|------|
| 空间重叠度 (IoU) | IoU高 → 偏好 spatial_join；IoU低 → 偏好 nearest_join | +0.3 |
| 几何类型 | Point → 偏好 nearest_join/point_sampling；Polygon → 偏好 spatial_join/zonal_statistics | +0.3 |
| 数据量比率 | 大比率差异 → 偏好 zonal_statistics | +0.2 |
| 面×面适中重叠 | Polygon × Polygon + IoU 适中 → 偏好 overlay | +0.2 |

评分算法：

```
输入: candidates (候选策略列表), aligned_data (已对齐数据), sources (源画像列表)
输出: best_strategy (字符串)

1. 初始化 scores = {strategy: 0.0 for strategy in candidates}
2. 计算空间重叠度: iou = sources[0].spatial_overlap with sources[1]
3. 提取几何类型: geom_types = [s.geometry_type for s in sources]
4. 计算数据量比率: row_ratio = max(rows) / min(rows) if min > 0

5. 评分规则:
   - 若 "spatial_join" in candidates:
     if iou > 0.1 and any(geom == "Polygon"): scores["spatial_join"] += 0.3
   - 若 "nearest_join" in candidates:
     if iou < 0.3 or any(geom == "Point"): scores["nearest_join"] += 0.3
   - 若 "overlay" in candidates:
     if all(geom == "Polygon") and 0.05 < iou < 0.8: scores["overlay"] += 0.2
   - 若 "zonal_statistics" in candidates:
     if any(geom == "Polygon"): scores["zonal_statistics"] += 0.3
   - 若 "point_sampling" in candidates:
     if any(geom == "Point"): scores["point_sampling"] += 0.3

6. 返回 max(scores, key=scores.get) — 得分最高的策略
   若所有得分为0, 退回 candidates[0] 作为默认选择
```

该设计体现了"约定 + 数据感知"的双层原则：策略矩阵提供类型级别的粗筛，评分器基于具体数据特征进行精选，同时保留用户通过显式指定 `strategy` 参数覆盖自动选择的能力。

### 3.2 融合策略实现

引擎实现了10种融合策略，每种策略作为独立函数注册到 `_STRATEGY_REGISTRY` 字典中。以下对每种策略的算法原理、输入约束和输出特征进行详细说明。

#### 3.2.1 空间连接 (spatial_join)

适用场景：两个矢量数据集基于空间关系进行属性关联。

```
算法:
1. 提取两个 GeoDataFrame: gdf_left, gdf_right
2. 执行 gpd.sjoin(gdf_left, gdf_right, how="left", predicate=spatial_predicate)
3. 清除 index_right 辅助列
4. 返回连接结果

空间谓词选项: intersects (默认) | contains | within
时间复杂度: O(n·m) (无空间索引), O(n·log(m)) (R-tree索引)
输出行数: ≥ len(gdf_left), 因左连接可能产生一对多匹配
```

#### 3.2.2 叠置分析 (overlay)

适用场景：两个面矢量数据集的几何叠置运算。

```
算法:
1. 提取两个 GeoDataFrame
2. 执行 gpd.overlay(gdf_left, gdf_right, how=overlay_how)
3. 返回叠置结果

叠置方式: union (默认) | intersection | difference | symmetric_difference
几何处理: 自动切割多边形边界, 生成新的拓扑关系
输出行数: 取决于几何交集数量, 通常 > max(len(left), len(right))
```

#### 3.2.3 最近邻连接 (nearest_join)

适用场景：基于空间距离的最近邻匹配，适用于无精确空间重叠的数据。

```
算法:
1. 提取两个 GeoDataFrame
2. 执行 gpd.sjoin_nearest(gdf_left, gdf_right, how="left")
3. 清除辅助列
4. 返回连接结果

特点: 即使无空间交集也能建立关联
注意: 地理坐标系下距离计算可能不准确 (应投影到适当的投影坐标系)
```

#### 3.2.4 属性连接 (attribute_join)

适用场景：矢量与表格数据基于共同键字段的属性合并。

```
算法:
1. 分离矢量 (GeoDataFrame) 和表格 (DataFrame) 数据
2. 若未指定 join_column:
   a. 调用 _auto_detect_join_column() 自动检测
   b. 优先匹配 ID 类字段 (包含 "id", "code", "bm", "dm", "fid" 的列名)
   c. 其次匹配任意同名列 (大小写不敏感)
3. 在表格数据中查找对应列 (支持大小写不敏感 + _right 后缀匹配)
4. 执行 gdf.merge(df, left_on=join_column, right_on=right_col, how="left")
5. 确保输出为 GeoDataFrame (保留几何信息)

自动键检测: 3层匹配策略 — 精确→不敏感→后缀
错误处理: 无法检测到共同键时抛出 ValueError 并给出提示
```

#### 3.2.5 分区统计 (zonal_statistics)

适用场景：将栅格数据的像元值按矢量面要素进行区域统计。

```
算法:
1. 分离矢量 (GeoDataFrame) 和栅格 (文件路径) 数据
2. 调用 rasterstats.zonal_stats(gdf, raster_path, stats=["mean","min","max","count"])
3. 将统计结果列添加 raster_ 前缀, 避免与原有列冲突
4. 合并到原 GeoDataFrame

关键参数: stats 列表可自定义 (mean/min/max/sum/count/std/median)
CRS处理: rasterstats 内部自动处理矢量到栅格CRS的重投影
输出: 原矢量 + N 个统计列 (N = len(stats))
```

#### 3.2.6 点采样 (point_sampling)

适用场景：在点矢量位置处提取栅格像元值。

```
算法:
1. 分离点矢量 (GeoDataFrame) 和栅格 (文件路径) 数据
2. 提取所有点坐标: [(x, y) for geom in gdf.geometry]
3. 使用 rasterio.sample(coords) 逐点采样
4. 为每个波段创建新列: raster_band_1, raster_band_2, ...

约束: 矢量数据应为 Point 类型 (多边形会使用质心)
输出: 原点矢量 + B 个波段值列 (B = 栅格波段数)
```

#### 3.2.7 波段堆叠 (band_stack)

适用场景：多个单波段栅格合并为多波段数据集。

```
算法:
1. 提取两个栅格文件路径
2. 读取第一个栅格的 band_1, transform, crs 作为参考
3. 读取第二个栅格的 band_1
4. 检查维度一致性: shape[0] == shape[1]
5. 计算归一化差异比值: (band_0 - band_1) / (band_0 + band_1)
6. 分类为5级: bins=[-0.5, -0.2, 0.0, 0.2, 0.5]
7. 矢量化为多边形 (rasterio.features.shapes)
8. 构建 GeoDataFrame

特点: 当前实现执行归一化差异 + 分类 + 矢量化的完整流程
约束: 两个栅格的空间分辨率和范围必须一致
```

#### 3.2.8 时间快照 (time_snapshot)

适用场景：将实时流数据的时间切片与矢量数据关联。

```
算法:
1. 提取矢量 GeoDataFrame
2. 添加 _fusion_timestamp 列 (当前时间戳 ISO 格式)
3. 返回标注了时间戳的结果

设计说明: 当前实现为占位框架, 完整实现需与 streaming_tools 的实时
数据获取接口集成, 执行空间-时间双重连接
```

#### 3.2.9 高度赋值 (height_assign)

适用场景：将点云数据的高程信息赋予矢量面要素。

```
算法:
1. 提取矢量 GeoDataFrame
2. 添加 height_m 列 (默认值 0.0)
3. 返回结果

设计说明: 当前实现为占位框架, 完整实现需使用 laspy 库读取点云,
按空间位置计算每个面要素内点云的平均/最大/最小高度
```

#### 3.2.10 栅格矢量化 (raster_vectorize)

适用场景：将栅格数据转换为矢量后与表格数据合并。

```
算法:
1. 分离栅格 (文件路径) 和表格 (DataFrame) 数据
2. 读取栅格 band_1, transform, crs
3. 使用 rasterio.features.shapes() 将像元值相同的区域矢量化
4. 构建 GeoDataFrame (raster_value 列 + 多边形几何)
5. 若表格行数与矢量化结果行数一致, 直接追加属性列

约束: 栅格应为分类数据 (整型值), 连续栅格需先分类
```

### 3.3 兼容性评分模型

兼容性评估采用四维加权评分模型，总分 ∈ [0, 1]：

```
overall_score = min(S_crs + S_spatial + S_field + S_strategy, 1.0)

其中:
  S_crs     = 0.30  若 CRS 完全一致
            = 0.15  若 CRS 不一致但可修复 (存在已知CRS)
            = 0.00  若无CRS信息

  S_spatial = 0.30  若 IoU(bbox_1, bbox_2) > 0.1
            = 0.20  若任一数据源为表格类型 (无需空间重叠)
            = 0.00  其他情况

  S_field   = 0.20  若发现至少一个语义匹配的字段对
            = 0.00  无匹配

  S_strategy= 0.20  若策略矩阵中存在该类型对的融合策略
            = 0.00  无可用策略
```

该评分模型的设计考虑了以下原则：

- **CRS权重最高（0.30）**：坐标系不一致是融合失败的最常见原因，但该问题可通过重投影自动修复，因此不一致但可修复的情况仍给予部分分数
- **空间重叠次高（0.30）**：空间范围不重叠的数据融合通常无意义，但对于表格数据（无空间属性），降低此维度的要求
- **字段匹配和策略可用性各占0.20**：作为辅助判断维度

### 3.4 四层渐进式语义字段匹配（v5.6 增强）

v5.6 版本将字段匹配从原始的两阶段硬编码策略升级为四层渐进式匹配系统，借鉴了 MGIM 通过数据驱动方式自动发现地理元素间语义关系的思路，在确定性规则引擎框架内实现了从精确匹配到模糊推理的渐进式语义发现。

#### 第一层：精确匹配（confidence = 1.0）

对两个数据源的列名进行大小写不敏感的精确比较。例如 `AREA` 与 `Area` 会匹配。这是最高置信度的匹配层，不会产生误匹配。

#### 第二层：等价组匹配（confidence = 0.8）

定义了10个语义等价组（从v5.5的6组扩展），覆盖GIS领域最常见的中英文字段命名模式：

```python
equiv_groups = [
    {"area", "面积", "zmj", "tbmj", "mj", "shape_area"},    # 面积语义组
    {"name", "名称", "mc", "dlmc", "qsdwmc", "dkmc"},        # 名称语义组
    {"code", "编码", "dm", "dlbm", "bm", "dkbm"},            # 编码语义组
    {"type", "类型", "lx", "dllx", "tdlylx"},                # 类型语义组
    {"slope", "坡度", "pd", "slope_deg"},                      # 坡度语义组
    {"id", "objectid", "fid", "gid", "pkid"},                # 标识符语义组
    {"population", "人口", "rk", "rksl", "pop"},              # 人口语义组（新增）
    {"address", "地址", "dz", "addr", "location"},            # 地址语义组（新增）
    {"elevation", "高程", "dem", "gc", "alt", "height"},      # 高程语义组（新增）
    {"perimeter", "周长", "zc", "shape_length"},              # 周长语义组（新增）
]
```

匹配算法：对于每个等价组，在两个数据源的列名中分别查找属于该组的成员。若左源命中 `area`，右源命中 `zmj`，则建立 `{left: "area", right: "zmj", confidence: 0.8}` 的匹配关系。采用"右列优先"的去重策略——每个右侧列最多匹配一个左侧列，避免一对多歧义。

#### 第三层：单位感知匹配（confidence = 0.75，v5.6 新增）

识别列名中的度量单位后缀，剥离单位部分后进行基名比较。这解决了同一概念因单位标注不同而无法匹配的问题（如 `area_m2` 与 `area_mu`）。

```
支持的单位模式:
  _(m2|sqm|平方米)          → m2 (平方米)
  _(mu|亩)                  → mu (亩)
  _(ha|hectare|公顷)        → ha (公顷)
  _(km2|sqkm|平方公里)      → km2 (平方公里)
  _(m|meter|米)             → m (米)
  _(km|千米|公里)           → km (千米)
  _(deg|degree|度)          → deg (度)

匹配算法:
1. 对列名调用 _detect_unit(col_name) → (base_name, unit)
2. 若两列的 base_name 相同且 unit 不同:
   标记为单位感知匹配, confidence = 0.75
   记录两侧的单位信息供后续自动转换
```

#### 第四层：模糊匹配（confidence = 0.5~0.7，v5.6 新增）

使用 `difflib.SequenceMatcher` 计算列名间的字符序列相似度，捕获拼写变体、缩写差异等情况。

```
匹配算法:
1. 对所有未匹配的列对, 计算 SequenceMatcher.ratio()
2. 阈值: ratio ≥ 0.6
3. confidence = ratio × 1.0 (即 0.6~1.0 之间, 实际范围 ~0.6~0.7)
4. 过滤: 跳过列名长度 ≤ 2 的字段 (短名易误匹配)
5. 去重: 已在上层匹配的列不参与模糊匹配
```

**四层匹配的设计哲学**：层级递增代表置信度递减和覆盖面递增的权衡。精确匹配最可靠但覆盖面最窄；模糊匹配覆盖面最广但可能引入假阳性。单位感知匹配作为第三层，介于等价组和模糊匹配之间，既有语义层面的理解（识别度量单位），又保持了较高的可靠性。

### 3.5 列名冲突消解

当两个数据源存在同名列（排除 `geometry`）时，引擎自动为第二个数据源的冲突列添加 `_right` 后缀：

```
源1: [OBJECTID, AREA, SLOPE, geometry]
源2: [OBJECTID, VALUE, OWNER]

冲突检测: {OBJECTID}
消解后源2: [OBJECTID_right, VALUE, OWNER]

后续 attribute_join 中的键查找支持 _right 后缀回溯:
join_column="OBJECTID" → 在源2中查找 "OBJECTID" → "objectid" → "OBJECTID_right"
```

### 3.6 增强质量验证模型（v5.6→v7.1 增强）

融合结果自动经过多层次质量检查。v5.6 版本在原有4项检查基础上新增了异常值检测、微面检测和列完整性追踪；v7.1 进一步扩展至 **10 维综合质量评分**：

**表7：质量检查项**

| 检查项 | 触发条件 | 评分影响 | 版本 |
|--------|---------|---------|------|
| 空结果检测 | `len(data) == 0` | 直接返回 0.0 | v5.5 |
| 空值率过高 | 某列 `null% > 50%` | -0.10/列 | v5.5 |
| 空值率中等 | 某列 `20% < null% ≤ 50%` | -0.05/列 | v5.5 |
| 几何无效 | `invalid_pct > 0` | -0.15 | v5.5 |
| 完整性不足 | `output_rows / max_source_rows < 0.5` | -0.15 | v5.5 |
| 属性异常值 | 数值列存在 5×IQR 离群值 | -0.05/列 | **v5.6** |
| 微面多边形 | 面积 < 中位面积的 0.1% | -0.05 | **v5.6** |
| 列完整性低 | 融合后列数 < 源列数之和的 50% | -0.10 | **v5.6** |
| CRS 一致性 | 融合结果 CRS 不一致或缺失 | -0.10 | **v7.1** |
| 拓扑验证 | `explain_validity` 检测自相交 | -0.10 | **v7.1** |
| 分布偏移 | KS 检验检测数值分布异常漂移 | -0.05/列 | **v7.1** |

#### 3.6.1 异常值检测（v5.6 新增）

对融合结果的数值型列进行基于四分位距（IQR）的异常值检测：

```
算法:
1. 对每个数值列 col:
   Q1 = col.quantile(0.25)
   Q3 = col.quantile(0.75)
   IQR = Q3 - Q1
2. 若 IQR > 0:
   lower_bound = Q1 - 3.0 × IQR
   upper_bound = Q3 + 3.0 × IQR
   outlier_count = count(values outside bounds)
3. 若 outlier_count > 0: 记录警告 + 扣 0.05 分

阈值说明: 使用 3.0 × IQR（而非常用的 1.5 × IQR）以降低假阳性，
          仅标记极端异常值，适配GIS数据的高方差特征。
```

#### 3.6.2 微面多边形检测（v5.6 新增）

检测融合过程中可能产生的碎片多边形（sliver polygons）：

```
算法:
1. 计算所有面要素的面积
2. 计算中位面积 median_area
3. 阈值 = median_area × 0.001
4. 统计面积 < 阈值的要素比例
5. 若比例 > 0: 记录警告 + 扣 0.05 分

场景: 空间叠置(overlay)和空间连接(spatial_join)可能在
      多边形边界处产生极小碎片，需提醒用户清理。
```

#### 3.6.3 详细质量报告（v5.6 新增）

v5.6 版本的 `validate_quality()` 返回结构从 `{score, warnings}` 扩展为 `{score, warnings, details}`：

```python
details = {
    "null_rates": {col: pct for col in columns},    # 逐列空值率
    "outlier_columns": ["col1", "col2"],             # 存在异常值的列
    "micro_polygon_pct": 0.02,                       # 微面多边形比例
    "column_completeness": 0.85,                     # 列完整性比率
    "total_columns": 15,                             # 总列数
    "source_column_sum": 18,                         # 源列数之和
}
```

### 3.7 自动单位检测与转换（v5.6 新增）

v5.6 版本在语义对齐阶段（Stage 3）新增了自动单位检测与转换功能，解决了同一属性因使用不同度量单位而导致数值不可比的问题。

#### 3.7.1 单位检测

通过列名的后缀模式匹配识别度量单位：

```python
UNIT_PATTERNS = {
    r"_(m2|sqm|平方米)$": "m2",
    r"_(mu|亩)$": "mu",
    r"_(ha|hectare|公顷)$": "ha",
    r"_(km2|sqkm|平方公里)$": "km2",
    r"_(m|meter|米)$": "m",
    r"_(km|千米|公里)$": "km",
    r"_(deg|degree|度)$": "deg",
}
```

`_detect_unit(column_name)` 函数返回 `(base_name, unit)` 元组。例如 `area_m2` → `("area", "m2")`，`slope_deg` → `("slope", "deg")`。

#### 3.7.2 单位转换

当字段匹配的第三层（单位感知匹配）发现两列基名相同但单位不同时，自动应用转换因子：

```python
UNIT_CONVERSIONS = {
    ("m2", "mu"):  1 / 666.67,    # 平方米 → 亩
    ("mu", "m2"):  666.67,        # 亩 → 平方米
    ("mu", "ha"):  1 / 15.0,      # 亩 → 公顷
    ("ha", "mu"):  15.0,          # 公顷 → 亩
    ("m2", "ha"):  1 / 10000.0,   # 平方米 → 公顷
    ("ha", "m2"):  10000.0,       # 公顷 → 平方米
    ("m", "km"):   1 / 1000.0,    # 米 → 千米
    ("km", "m"):   1000.0,        # 千米 → 米
    ("m2", "km2"): 1 / 1000000.0, # 平方米 → 平方千米
    ("km2", "m2"): 1000000.0,     # 平方千米 → 平方米
}
```

转换在 `align_sources()` 阶段自动执行，确保进入融合阶段的数据在数值上可直接比较。

### 3.8 多源融合编排（v5.6 新增）

v5.5 版本的融合执行器仅支持两个数据源的成对融合。v5.6 版本引入了 `_orchestrate_multisource()` 函数，实现了 N > 2 数据源的自动编排：

```
算法:
输入: aligned_data (N 个已对齐数据), sources (N 个源画像), params (策略参数)
输出: (final_result, fusion_steps)

1. 按数据类型优先级排序: vector → raster → tabular → point_cloud → stream
   (确保矢量数据作为主表，其他模态逐步合入)

2. 初始化:
   current_result = sorted_data[0]
   fusion_steps = []

3. 逐步合并:
   for i in range(1, N):
     pair = [current_result, sorted_data[i]]
     pair_sources = [sorted_sources[0], sorted_sources[i]]
     strategy = _auto_select_strategy(pair, pair_sources)
     current_result = _execute_strategy(strategy, pair, params)
     fusion_steps.append({step: i, strategy, left_type, right_type})

4. 返回 (current_result, fusion_steps)
```

**设计考量**：
- **类型优先级排序**保证矢量数据始终作为空间基座，避免因顺序不当导致几何信息丢失
- **逐步合并**策略简单可靠，每步的中间结果均为有效数据集，便于调试和审计
- **未来扩展**：可引入基于数据量级和空间重叠度的融合计划优化器，选择最优合并顺序

---

## 4 系统集成

### 4.1 工具集封装

`FusionToolset` 继承 `BaseToolset`，封装4个工具函数，通过ADK的 `FunctionTool` 包装器暴露给LLM Agent：

**表5：融合工具集工具列表**

| 工具名称 | 输入参数 | 功能 |
|----------|---------|------|
| `profile_fusion_sources` | `file_paths: str` (逗号分隔) | 分析多个数据源的特征画像 |
| `assess_fusion_compatibility` | `file_paths: str` | 评估数据源间的融合兼容性 |
| `fuse_datasets` | `file_paths, strategy, join_column, spatial_predicate` | 执行融合操作 |
| `validate_fusion_quality` | `file_path: str` | 验证融合结果质量 |

每个工具函数内部实现了完整的异常处理和结果序列化（JSON格式），确保LLM能够解析返回值。

### 4.2 智能体集成

`FusionToolset` 被注册到三个智能体（Agent）中：

1. **GeneralProcessing** — 通用处理管道，处理大多数用户请求
2. **PlannerProcessor** — 规划管道的数据处理子代理
3. **DataProcessing** — 优化管道的数据预处理代理

通用处理代理的系统提示（`prompts/general.yaml`）中注入了融合操作指引，指导LLM按照 profile → assess → fuse → validate 的标准工作流编排工具调用。

### 4.3 数据血缘与审计

每次融合操作完成后，`record_operation()` 函数将以下信息写入 `agent_fusion_operations` 表：

```sql
agent_fusion_operations (
    id           SERIAL PRIMARY KEY,
    username     VARCHAR(100),       -- 执行用户
    source_files JSONB,              -- 源文件路径列表
    strategy     VARCHAR(50),        -- 使用的融合策略
    parameters   JSONB,              -- 策略参数
    output_file  TEXT,               -- 输出文件路径
    quality_score FLOAT,             -- 质量评分
    quality_report JSONB,            -- 质量报告详情
    duration_s   FLOAT,              -- 执行耗时
    created_at   TIMESTAMP           -- 创建时间
)
```

该表支持按用户和时间的历史查询，为数据血缘追踪提供底层支撑。

---

## 5 测试与验证

### 5.1 测试架构

测试套件包含72个独立测试用例（v5.5: 46个 + v5.6新增: 26个），组织为16个测试类：

**表8：测试覆盖矩阵**

| 测试类 | 测试内容 | 用例数 | 版本 |
|--------|---------|--------|------|
| `TestFusionSource` | 矢量/栅格/表格画像、数据类型检测 | 5 | v5.5 |
| `TestCompatibilityAssessor` | CRS检查、空间重叠、字段匹配、策略推荐 | 7 | v5.5 |
| `TestSemanticAligner` | CRS重投影、列冲突消解、类型对匹配 | 6 | v5.5 |
| `TestFusionExecutor` | 8种策略的执行正确性 | 8 | v5.5 |
| `TestStrategyMatrix` | 矩阵完整性、注册表一致性 | 3 | v5.5 |
| `TestQualityValidator` | 空值检测、空结果、几何有效性、完整性 | 5 | v5.5 |
| `TestRecordOperation` | DB记录写入、无DB降级 | 2 | v5.5 |
| `TestEnsureFusionTables` | 表创建、无DB降级 | 2 | v5.5 |
| `TestFusionToolset` | 工具注册、工具名称、过滤器 | 3 | v5.5 |
| `TestEndToEnd` | 矢量+表格、矢量+矢量完整流程 | 2 | v5.5 |
| `TestAutoDetectJoinColumn` | 共同列检测、ID优先、无匹配异常 | 3 | v5.5 |
| `TestFuzzyFieldMatching` | 精确/等价组/模糊/短名/扩展组/去重 | 6 | **v5.6** |
| `TestUnitDetectionConversion` | 单位检测/剥离/m²→亩/亩→ha/无因子 | 8 | **v5.6** |
| `TestDataAwareStrategyScoring` | nearest_join/spatial_join/zonal/point/单候选 | 5 | **v5.6** |
| `TestMultiSourceOrchestration` | 三源矢量融合、2步编排 | 1 | **v5.6** |
| `TestEnhancedQualityValidation` | details字典/异常值/微面/列完整性/空结果 | 5 | **v5.6** |
| `TestUnitAwareAlignment` | 单位感知匹配检测 | 1 | **v5.6** |

### 5.2 测试策略

- **Fixture生成**：测试使用临时目录中动态生成的小型数据集（3个多边形、3行CSV、10×10栅格），避免外部文件依赖
- **Mock隔离**：数据库操作通过 `@patch("data_agent.gis_processors.get_user_upload_dir")` 和 `@patch("data_agent.fusion_engine.get_engine")` 隔离，确保测试不依赖数据库连接
- **回归安全**：全量回归测试（1230个用例）验证了融合引擎的引入未破坏现有功能

### 5.3 测试结果

```
v5.6 测试: 72 passed, 0 failed, 3 warnings in 28.5s

全量回归: 1256 passed, 61 pre-existing failures (unrelated test_toolsets issues)
新增测试: +26 用例 (v5.6 增强功能)
累计测试: 72 用例 (v5.5 基础 46 + v5.6 增强 26)
```

---

## 6 现有实现的不足与改进方向

### 6.1 v5.6 已修复的局限性

v5.6 版本针对 v5.5 识别的主要不足进行了系统性改进：

#### 6.1.1 ~~语义匹配能力有限~~ → 四层渐进式匹配（已修复）

**原问题**：仅有6个硬编码等价组，无模糊匹配，未集成语义层，单位转换未激活。

**v5.6 改进**：
- 等价组从6个扩展到10个，新增人口、地址、高程、周长四组
- 引入基于 `SequenceMatcher` 的模糊匹配（第四层），支持拼写变体和缩写差异
- 引入单位感知匹配（第三层），自动识别列名中的度量单位后缀
- 激活 `_apply_unit_conversions()` 在对齐阶段自动执行数值单位转换

**效果**：字段匹配从2层扩展到4层，覆盖面显著提升。

#### 6.1.2 ~~策略选择过于简单~~ → 数据感知评分（已修复）

**原问题**：始终返回策略矩阵中的第一个选项，不考虑数据特征。

**v5.6 改进**：
- 引入 `_score_strategies()` 评分器，根据空间重叠度（IoU）、几何类型、数据量比率动态选择策略
- 低IoU + 点数据 → 自动选择 `nearest_join` 而非 `spatial_join`
- 面×面 + 适中重叠 → 偏好 `overlay` 进行几何叠置
- 仅一个候选时直接返回，无额外计算开销

**效果**：策略选择从"始终选首项"升级为"基于数据特征的智能选择"。

#### 6.1.3 ~~仅支持双源融合~~ → 多源编排（已修复）

**原问题**：引擎内部假设恰好有两个输入，无多源调度。

**v5.6 改进**：
- 引入 `_orchestrate_multisource()` 实现 N > 2 数据源的自动逐步融合
- 按类型优先级排序（vector → raster → tabular），确保矢量作为空间基座
- 每步自动选择最优策略，记录融合步骤日志

**效果**：支持任意数量数据源的自动融合，用户无需手动分步操作。

#### 6.1.4 ~~质量验证维度不足~~ → 增强质量模型（已修复）

**原问题**：仅4项基础检查，缺少属性异常、碎片多边形、列完整性等维度。

**v5.6 改进**：
- 新增基于 IQR 的异常值检测，标记数值极端偏离
- 新增微面多边形检测，识别融合产生的碎片几何
- 新增列完整性追踪，评估融合后属性列的保留率
- 返回结构扩展为包含 `details` 字典的详细报告

**效果**：质量检查从4项扩展到7+项，提供更全面的结果诊断。

### 6.2 当前版本仍存在的局限性

#### 6.2.1 ~~部分策略为占位实现~~（v6.0 已修复）

~~`time_snapshot` 和 `height_assign` 两个策略仍为占位实现：~~

- ~~**time_snapshot**：仅添加当前时间戳列，未与 `streaming_tools.py` 的实时数据获取接口集成~~
- ~~**height_assign**：仅添加默认值0.0的高度列，未实际读取点云数据进行空间采样~~

**v6.0 修复**：
- **time_snapshot**：完整实现了流数据时态融合——加载CSV/JSON流数据（含timestamp/lat/lng/value列），支持时间窗口过滤（默认60分钟），通过空间连接将流点匹配到矢量面，按面要素聚合统计（count/mean/latest），无坐标列时优雅降级
- **height_assign**：完整实现了点云高度赋值——使用laspy读取LAS/LAZ的x/y/z数组，对每个矢量要素的bounds做空间过滤，计算匹配点的height统计（支持mean/median/min/max参数），laspy未安装或文件缺失时优雅降级

#### 6.2.2 ~~栅格处理能力不完整~~（v6.0 已修复）

~~- **band_stack 限制**：要求两个栅格具有完全相同的空间分辨率和范围，不支持自动重采样对齐~~
~~- **无栅格重投影**：对齐阶段仅对矢量数据执行CRS重投影，栅格保持原始状态~~
~~- **大栅格性能**：全波段读取可能在大型遥感影像上导致内存溢出~~

**v6.0 修复**：
- **栅格自动重投影**：新增 `_reproject_raster()` 辅助函数，使用 `rasterio.warp.reproject` + `calculate_default_transform`，支持nearest/bilinear/cubic重采样方法。`align_sources()` 在栅格CRS不一致时自动调用，失败时降级使用原始路径
- **band_stack 自动重采样**：新增 `_resample_raster_to_match()` 辅助函数，两个栅格shape不同时自动重采样第二个栅格到第一个的网格，移除了硬性shape相等要求
- **大栅格窗口采样**：`_profile_raster()` 对大栅格（>1M像素）使用窗口采样读取中心区域（1024×1024）统计，避免全波段内存加载

#### 6.2.3 缺乏真实数据效果评估（v6.0 部分改善）

- ~~所有测试使用合成小型数据集（3个多边形、3行CSV、10×10栅格），未在真实GIS场景中验证~~
- 缺乏与手动融合的效果对比实验
- 未与其他融合方案（如 FME、QGIS Processing）进行性能基准测试

**v6.0 改善**：新增 `TestRealDataIntegration` 测试类（4个测试），使用 `evals/fixtures/sample_parcels.geojson`（10个真实地块要素，含DLBM/SLOPE/AREA/TBMJ字段）进行画像、质量验证、自融合、字段匹配的集成测试。但仍需更大规模的真实数据集和效果对比实验。

#### 6.2.4 ~~语义匹配的深度限制~~（v6.0 已修复）

~~虽然 v5.6 大幅提升了字段匹配能力，但仍存在以下限制：~~
~~- 模糊匹配可能产生假阳性（如 `slope` 匹配 `slope_type`）~~
~~- 未集成深度学习嵌入模型（如 sentence-transformers），无法处理语义等价但字面完全不同的字段~~
~~- 等价组仍需人工维护，未实现自动发现~~

**v6.0 修复**：
- **目录驱动等价组**：`_load_catalog_equiv_groups()` 从 `semantic_catalog.yaml` 的15个域的 common_aliases 自动构建等价组，与硬编码10组合并去重，新域的字段自动纳入匹配范围
- **分词相似度**：`_tokenized_similarity()` 将字段名按下划线/驼峰/数字边界拆分为token，使用 Jaccard token重叠(60%) + SequenceMatcher(40%) 加权，解决了 `land_use_type` vs `landUseType` 的跨命名风格匹配
- **类型兼容检查**：`_types_compatible()` 阻止数值字段匹配文本字段，防止 `slope`(float) 误匹配 `slope_type`(string) 的假阳性
- **增强质量验证**：新增CRS一致性检查、拓扑验证（explain_validity检测自相交）、KS检验分布偏移检测

### 6.3 架构层面的改进路线

#### 6.3.1 近期改进（v6.0）— 已完成

| 改进项 | 优先级 | 状态 | 实现摘要 |
|--------|--------|------|---------|
| 完善 height_assign 实现 | P1 | ✅ 已完成 | laspy点云读取 + 空间过滤 + 多统计量 |
| 完善 time_snapshot 实现 | P1 | ✅ 已完成 | CSV/JSON流数据 + 时间窗口 + 空间聚合 |
| 栅格自动重采样对齐 | P1 | ✅ 已完成 | rasterio.warp重投影 + 网格重采样 |
| 大栅格窗口采样 | P1 | ✅ 已完成 | 中心1024²窗口采样 |
| 语义匹配增强 | P1 | ✅ 已完成 | 目录等价组 + 分词相似度 + 类型兼容 |
| 质量验证增强 | P1 | ✅ 已完成 | CRS检查 + 拓扑验证 + KS检验 |
| 真实数据集成测试 | P0 | ⚠️ 部分完成 | sample_parcels.geojson 4项测试 |

#### 6.3.2 中期改进

- **LLM辅助策略选择**：将兼容性报告作为上下文传递给LLM，让LLM基于用户意图和数据特征选择最优策略
- **增量融合**：支持对已融合数据集追加新数据源，而非每次全量重新融合
- **分布式执行**：对于大规模数据集（>1M行），将融合任务分发到 Dask/Spark 集群执行

#### 6.3.3 长期愿景

- **自学习策略优化**：基于历史融合操作的成功/失败记录，训练策略推荐模型
- **跨系统互操作**：通过 OGC API 标准实现与外部GIS系统的数据融合
- **知识图谱驱动**：构建GIS领域知识图谱，替代硬编码的等价组，实现任意字段的语义推理

---

## 7 v7.0 增强：智能化融合

v7.0 版本在 v6.0 基础上进一步增强了引擎的智能化水平，从四个维度提升融合引擎能力。

### 7.1 向量嵌入语义匹配

**动机**：现有四层匹配依赖硬编码的等价组和字符级模糊匹配，对于语义相近但拼写差异大的字段名（如 `population` vs `inhabitants`、`landuse_type` vs `DLBM`）匹配效果有限。

**方案**：在 Tier 2（等价组）和 Tier 3（单位感知）之间插入 **Tier 2.5 嵌入层**，利用 Gemini `text-embedding-004` 模型将字段名映射到高维语义向量空间，通过余弦相似度计算语义距离。

**实现细节**：
- 使用 `google.genai.Client().models.embed_content()` 批量获取字段名嵌入向量
- 模块级 `_embedding_cache` 字典避免重复 API 调用
- 余弦相似度阈值 ≥ 0.75，匹配置信度 0.78
- 匹配前检查字段类型兼容性（numeric↔numeric、string↔string）
- API 失败时静默降级到 Tier 3/4，不影响现有流程
- **默认关闭**，通过 `use_embedding=True` 显式启用，避免不必要的 API 开销

**设计权衡**：选择 Gemini text-embedding-004 而非 sentence-transformers 的原因：
1. sentence-transformers 引入 ~400MB 依赖（torch + transformers），不适合轻量部署
2. 项目已依赖 google-genai，API 调用无额外安装成本
3. 嵌入缓存机制减少了 API 调用频率

### 7.2 LLM 增强策略路由

**动机**：现有规则评分（IoU、几何类型、数据量比率）缺乏对用户分析意图的理解。例如，同一对数据源可能因"分析土地覆被变化"和"计算设施覆盖率"两种不同目的而需要不同的融合策略。

**方案**：新增 `strategy="llm_auto"` 选项，调用 Gemini 2.0 Flash 进行策略推理。LLM 接收候选策略列表、数据源元信息和用户意图提示（`user_hint`），返回 JSON 格式的策略推荐与推理链。

**实现细节**：
- `_llm_select_strategy()` 构造结构化 prompt，包含：
  - 候选策略列表（来自 STRATEGY_MATRIX 粗筛）
  - 各数据源的类型、行数、列名
  - 用户提供的分析意图描述
- LLM 返回 `{"strategy": "spatial_join", "reasoning": "..."}`
- 策略验证：LLM 推荐的策略必须在候选列表内，否则降级到规则评分
- JSON 解析失败时降级到规则评分
- 推理结果记录到 `alignment_log` 中，供审计追踪
- **非替代**：规则评分仍然是默认行为，LLM 仅在显式请求时介入

### 7.3 地理知识图谱

**动机**：传统融合引擎输出"宽表"（列合并），丢失了实体间的空间关系。例如，一个地块被道路分割为两部分，或一栋建筑包含在一个行政区内——这些关系在宽表中无法表达。

**方案**：新建独立模块 `knowledge_graph.py`，使用 networkx 有向图 (DiGraph) 构建内存级空间实体关系图。支持 7 种实体类型（地块、建筑、道路、水体、行政区、植被、POI）和 5 种关系类型（包含、被包含、邻接、重叠、最近）。

**核心类**：`GeoKnowledgeGraph`
- `build_from_geodataframe()`：GeoDataFrame 行 → 图节点，自动推断实体类型
- `merge_layer()`：增量添加图层，检测跨层空间关系
- `query_neighbors(depth=N)`：N 跳邻居查询
- `query_path(source, target)`：最短路径查询
- `query_by_type(entity_type)`：按实体类型筛选
- `export_to_json()`：`nx.node_link_data()` 标准格式导出
- `_detect_adjacency()`：STRtree 空间索引加速邻接关系检测
- `_detect_containment()`：contains/within 几何关系检测

**性能保护**：`_MAX_SPATIAL_PAIRS = 1000`，避免大数据集的 O(n²) 组合爆炸。

**工具集集成**：`KnowledgeGraphToolset(BaseToolset)` 封装 3 个工具函数（`build_knowledge_graph`、`query_knowledge_graph`、`export_knowledge_graph`），通过 ADK `FunctionTool` 注册到 GeneralProcessing 和 PlannerProcessor agent。

### 7.4 分布式/核外计算

**动机**：大数据集（>50万行或 >500MB）在内存中完整加载会导致 OOM。

**方案**：利用项目已有的 dask 和 fiona 库，实现透明的分块读取和处理。

**实现细节**：
- `_is_large_dataset(path, row_hint)`：通过文件大小（500MB）和行数（500K）双重阈值检测
- `_read_vector_chunked(path, chunk_size=100K)`：fiona 分块读取矢量文件
- `_read_tabular_lazy(path)`：dask.dataframe 延迟计算大 CSV 文件
- `_fuse_large_datasets_spatial(gdf_left, gdf_right, chunk_size=50K)`：分块执行 spatial_join
- **透明性**：修改 `_profile_vector()`、`_profile_tabular()`、`align_sources()`、`_strategy_spatial_join()` 使用新的读取函数，对调用方无感知
- 小文件行为完全不变，仅大文件自动切换到分块模式

## 7.5 v7.1 增强：工程重构与计算下推

v7.1 版本基于 `docs/technical-review-mmfe.md` 提出的 4 项核心缺陷（P0~P2），完成了 4 阶段系统性重构：

### 7.5.1 Phase 1：工程解耦 — 单体拆包

**问题**：`fusion_engine.py` 超 2200 行，违反单一职责原则，难以单元测试和扩展。

**方案**：拆解为 `data_agent/fusion/` 标准 Python 包（22 个模块，26 个文件），实施策略模式。

**关键设计**：
- 每个策略实现独立文件（`strategies/spatial_join.py` 等），通过 `_STRATEGY_REGISTRY` 字典注册
- PostGIS 计算下推作为独立策略 `strategies/postgis_pushdown.py`
- 原 `fusion_engine.py` 保留为薄代理层（72行），`from data_agent.fusion import *` 重导出全部符号
- 测试 Mock 目标相应变更：`fusion.db.get_engine`、`fusion.execution._llm_select_strategy`、`fusion.matching._get_embeddings`

### 7.5.2 Phase 2：AI 精简 — LLM 职责纠偏

**问题**：LLM 被滥用于策略路由（纯规则决策），同时语义匹配仍依赖大量正则规则。

**方案**：
- **弃用 LLM 策略路由**：`_llm_select_strategy()` 保留但标记弃用，`strategy="llm_auto"` 回退为 `"auto"`（规则评分），日志记录 warning
- **新增 LLM Schema 对齐**：`schema_alignment.py` 模块，将两表 Schema（字段名、类型、采样数据）组合为 Prompt，由 Gemini 2.5 Flash 输出结构化映射配置（JSON），通过 `use_llm_schema=True` 显式启用
- **保留规则匹配**：4 层匹配（分词→句法→嵌入→等价组）作为 LLM Schema 对齐的备选方案

### 7.5.3 Phase 3：异步化 — 事件循环解阻

**问题**：同步 I/O（GeoPandas/Rasterio CPU 密集计算）阻塞 ASGI 事件循环，多用户并发时系统冻结。

**方案**：
- 4 个工具函数全部改为 `async def`，内部使用 `await asyncio.to_thread()` 包装阻塞调用
- 影响范围：`profile_fusion_sources`、`assess_fusion_compatibility`、`fuse_datasets`、`validate_fusion_quality`
- 融合核心算法保持同步实现（纯计算逻辑），仅在 ADK 工具层做异步包装

### 7.5.4 Phase 4：PostGIS 计算下推

**问题**：大表（>10万行）全量拉回 Python 内存计算导致 OOM 和性能瓶颈。

**方案**：`strategies/postgis_pushdown.py` 实现 3 种 SQL 下推策略，利用数据库原生空间索引：

| Python 策略 | PostGIS SQL 等价 | 触发条件 |
|------------|-----------------|---------|
| `spatial_join` | `WHERE ST_Intersects(a.geom, b.geom)` | 两源均 PostGIS-backed 且合计 >10万行 |
| `overlay` | `SELECT ST_Intersection(a.geom, b.geom)` | 同上 |
| `nearest_join` | `LATERAL (SELECT ... ORDER BY a.geom <-> b.geom LIMIT 1)` | 同上 |

**工作流**：
```
execute_fusion()
  → 检查 sources[0].postgis_table && sources[1].postgis_table
  → 检查 total_rows > LARGE_ROW_THRESHOLD (100K)
  → 检查 strategy in {spatial_join, overlay, nearest_join}
  → 满足条件 → postgis_pushdown.execute_pushdown_sql()
  → SQL 执行失败 → 降级到 Python 策略
```

**FusionSource 扩展**：新增 `postgis_table: Optional[str]` 和 `postgis_srid: Optional[int]` 字段，`profile_postgis_source(table_name)` 直接查询数据库元数据。

---

## 7.6 实验评估与量化指标

为系统性验证 MMFE 各模块的能力，我们设计了包含 9 项核心指标的基准测试套件（`benchmark_fusion.py`），在合成数据上运行真实引擎函数，产出可量化的技术指标。

### 7.6.1 语义匹配准确率

基于 50 对字段名 ground truth（含精确匹配、等价组、单位感知、模糊匹配及负例），测量 `_find_field_matches()` 的精确率/召回率/F1：

| 匹配层级 | 测试对数 | Precision | Recall | F1 |
|----------|---------|-----------|--------|-----|
| Tier 1 精确匹配 | 8 | 1.00 | 1.00 | 1.00 |
| Tier 2 等价组 | 12 | 1.00 | 1.00 | 1.00 |
| Tier 3 单位感知 | 10 | 1.00 | 0.80 | 0.89 |
| Tier 4 模糊匹配 | 12 | 1.00 | 1.00 | 1.00 |
| 负例（不应匹配） | 8 | 1.00 | — | — |
| **总体** | **50** | **1.00** | **0.95** | **0.98** |

### 7.6.2 策略推荐准确率

构造 30 个数据对场景（覆盖矢量×矢量、矢量×栅格、矢量×表格、栅格×栅格、跨模态特殊），验证 `_auto_select_strategy()` 的推荐准确率：

| 场景类别 | 数量 | 准确率 |
|---------|------|--------|
| vector × vector | 10 | 100% |
| vector × raster | 8 | 100% |
| vector × tabular | 6 | 100% |
| raster × raster | 2 | 100% |
| 跨模态特殊 | 4 | 100% |
| **总体** | **30** | **100%** |

### 7.6.3 单位转换精度

对 8 组双向转换对（m²↔亩、亩↔ha、m²↔ha、m↔km）执行 `_apply_unit_conversions()`，验证数值精度：

- **最大相对误差**: 0.00（浮点精度级，零误差）
- **支持转换对数**: 8

### 7.6.4 兼容性评分准确率

构造 15 个数据对（高/中/低兼容性各 5 个），验证 `assess_compatibility()` 评分是否落在预期区间：

| 兼容性等级 | 预期区间 | 命中率 |
|-----------|---------|--------|
| 高（同CRS+重叠+共享字段） | 0.7–1.0 | 100% |
| 中（不同CRS或部分匹配） | 0.35–0.95 | 100% |
| 低（跨类型、无共享字段） | 0.2–0.75 | 100% |

### 7.6.5 融合质量评分

对 8 种核心策略使用干净合成数据执行融合，收集 `validate_quality()` 的质量分数：

| 策略 | 质量分数 |
|------|---------|
| spatial_join | 1.0 |
| overlay | 1.0 |
| nearest_join | 1.0 |
| attribute_join | 1.0 |
| zonal_statistics | 0.7 |
| point_sampling | 1.0 |
| band_stack | 1.0 |
| raster_vectorize | 1.0 |
| **均值 ± 标准差** | **0.96 ± 0.10** |

### 7.6.6 异常检测率

向干净数据注入 7 类已知缺陷，验证 `validate_quality()` 的检出能力：

| 缺陷类型 | 检出 |
|---------|------|
| 高空值率（60%） | ✅ |
| 无效几何（自相交） | ✅ |
| 极端异常值（>5×IQR） | ✅ |
| 微面多边形（<0.1%中位面积） | ✅ |
| 拓扑错误（自相交多边形） | ✅ |
| 行丢失（<50%输入） | ✅ |
| 空结果（0行） | ✅ |
| **检出率** | **100%（7/7）** |

### 7.6.7 数据完整性保持率

对 6 种核心策略测量输出相对于输入的保持率：

- **平均行保持率**: 1.00（≥0.80阈值）
- **平均几何有效率**: 1.00（≥0.99阈值）

### 7.6.8 模态与策略覆盖度

| 维度 | 覆盖 |
|------|------|
| 数据模态 | 5/5（矢量、栅格、表格、点云、实时流） |
| 融合策略 | 10/10 |
| 类型对映射 | 11/11 |
| 质量检查项 | 10/10 |
| 单位转换对 | 8 |
| 语义等价组 | 10 |

### 7.6.9 处理性能

在不同规模的合成数据上测量 spatial_join 的端到端耗时：

| 数据规模 | 总耗时 | 吞吐量 |
|---------|--------|--------|
| 100 行 | 0.03s | ~3,500 rows/s |
| 1,000 行 | 0.07s | ~16,000 rows/s |
| 10,000 行 | 0.50s | ~30,000 rows/s |

所有测试在 Windows 11 / Python 3.13 / 单机内存环境下运行。

---

## 7.7 v17.0 增强：多模态时空数据智能化语义融合 v2.0

v17.0 在 v7.1 工程架构基础上新增 4 个核心模块，从「能融合」升级到「融合好、解释清、冲突明」。所有 v2.0 功能均为 opt-in（默认关闭），零破坏性变更。

### 7.7.1 时序对齐层 (`fusion/temporal.py`, ~400 行)

**解决的核心问题**: v1.0 的 `time_snapshot` 策略仅做时间过滤/聚合，无法处理多源数据的时间基准不一致（不同时区、不同采集间隔、不同日期格式）。

**核心能力**:

| 能力 | 算法 | 输入 | 输出 |
|------|------|------|------|
| 时间列自动检测 | 正则模式匹配 + dtype 检查 | GeoDataFrame | 时间列名列表 |
| 时间戳标准化 | pd.to_datetime + 多格式级联 + 时区统一 | 异构时间列 | `_std_timestamp` (UTC) |
| 时序插值 | linear / nearest / spline (scipy) | 多时相数据 + 参考时刻 | 对齐到统一时刻的数据 |
| 轨迹-静态融合 | sjoin_nearest + 时间窗口过滤 | 轨迹点 + 静态要素 | 时空关联结果 |
| 多期变化检测 | ID 匹配 / 空间 IoU 匹配 + 属性阈值比较 | T1, T2 数据集 | `_change_type` (added/removed/modified/unchanged) |
| 时序一致性验证 | 单调性 + 间断检测 + 重复检测 | 时间列 | 一致性报告 |

**集成方式**: `execute_fusion()` 新增 `temporal_config: dict | None` 参数。在策略执行前调用 `TemporalAligner.pre_align()` 完成时间基准统一。

### 7.7.2 语义增强层 (3 个子模块, ~750 行)

**解决的核心问题**: v1.0 字段匹配止步于名称相似度，不理解语义含义（如「建筑高度」≈「楼层数×层高」，「面积」≡「AREA」≡「mj」）。

**a) 本体推理** (`fusion/ontology.py`, ~300 行):
- GIS 领域本体 (`standards/gis_ontology.yaml`): 15 等价组、8 推导规则、5 推理规则
- `OntologyReasoner` 类: 等价字段查找、缺失字段推导（如 `building_height = floors × 3.0`）、条件推理（如「坡度≥25° → 陡坡」）
- 集成为 `_find_field_matches()` 的 **Tier 1.5**（在精确匹配和等价组之间），置信度 0.85

**b) LLM 语义理解** (`fusion/semantic_llm.py`, ~250 行):
- `SemanticLLM` 类: Gemini 2.5 Flash 驱动
- 字段语义分类、可推导字段推断、深度语义匹配、批量语义类型检测
- 单次 LLM 调用匹配两组字段集（非逐字段调用），降低成本

**c) 知识图谱集成** (`fusion/kg_integration.py`, ~200 行):
- 桥接现有 `knowledge_graph.py::GeoKnowledgeGraph`
- 实体关系丰富（`_kg_relationships` 列）、基于 KG 上下文的冲突解决
- 从多源数据构建/扩展 KG

### 7.7.3 冲突消解层 (`fusion/conflict_resolver.py`, ~350 行)

**解决的核心问题**: v1.0 对同名属性简单覆盖，无智能合并策略。多源融合时值冲突普遍存在。

**6 种消解策略**:

| 策略 | 逻辑 | 适用场景 |
|------|------|----------|
| `source_priority` | 按数据源优先级选值 | 权威数据源已知 |
| `latest_wins` | 按数据源时间戳选最新值 | 时效性优先 |
| `voting` | 数值取均值，类别取众数 | 多源等权 |
| `llm_arbitration` | Gemini 结合地理语境推理 | 复杂/模糊冲突 |
| `spatial_proximity` | 按空间精度元数据加权 | 空间密集区域 |
| `user_defined` | 用户自定义函数 | 业务定制 |

**置信度评分**: `confidence = 0.4×timeliness + 0.3×precision + 0.3×completeness`，冲突行自动降权。

**来源标注**: 为每个属性列添加 `_source_{col}` 列，追踪最终值来自哪个数据源。

**集成方式**: `execute_fusion()` 新增 `conflict_config: dict | None` 参数。在策略函数执行后、保存前调用 `ConflictResolver.resolve_and_annotate()`。

### 7.7.4 可解释性层 (`fusion/explainability.py`, ~200 行)

**解决的核心问题**: v1.0 的 10 分制打分仅是全局摘要，用户无法知道哪些要素融合质量差、数据来自哪里、为什么这样融合。

**逐要素元数据**:
- `_fusion_confidence` (float 0-1): 置信度分数
- `_fusion_sources` (JSON): 来源文件列表
- `_fusion_method` (string): 使用的策略名
- `_fusion_conflicts` (JSON): 冲突详情

**质量热力图**: 按置信度三级分类 (low <0.3, medium 0.3-0.7, high >0.7)，输出简化 GeoJSON 用于前端渲染。大数据集 (>100K) 自动简化几何。

**融合溯源**: 结构化 lineage trace 包含 sources/strategy/alignment_steps/temporal_log/conflict_summary。

**决策解释**: 模板化自然语言（无需 LLM）：「该要素由 a.geojson、b.csv 融合生成，使用 spatial_join 策略。置信度: 0.85 (high)。」

### 7.7.5 数据库扩展

**Migration 049** (`migrations/049_fusion_v2_enhancements.sql`):
```sql
ALTER TABLE agent_fusion_operations
ADD COLUMN temporal_alignment_log TEXT,
ADD COLUMN semantic_enhancement_log TEXT,
ADD COLUMN conflict_resolution_log TEXT,
ADD COLUMN explainability_metadata JSONB;

CREATE TABLE agent_fusion_ontology_cache (
    id SERIAL PRIMARY KEY,
    field_name VARCHAR(255) UNIQUE NOT NULL,
    equivalent_fields JSONB,
    derivation_rules JSONB,
    semantic_type VARCHAR(100)
);
```

### 7.7.6 API 端点与前端

**5 个新 REST API**:
| 端点 | 方法 | 用途 |
|------|------|------|
| `/api/fusion/quality/{id}` | GET | 获取单次融合操作的质量详情 + 可解释性元数据 |
| `/api/fusion/lineage/{id}` | GET | 获取融合溯源链（含时序/语义日志）|
| `/api/fusion/conflicts/{id}` | GET | 获取冲突消解日志 |
| `/api/fusion/operations` | GET | 列表查询融合操作（含 v2 特性标记）|
| `/api/fusion/temporal-preview` | POST | 时序对齐预览（不执行融合）|

**前端**: `FusionQualityTab.tsx` — 融合操作列表 + 质量评分徽章 + v2 特性标记 + 详情面板（质量报告 + 可解释性 JSON 展示）。

### 7.7.7 测试验证

| 测试文件 | 测试数 | 覆盖 |
|---------|--------|------|
| `test_fusion_v2_explainability.py` | 16 | 元数据注入、热力图生成、溯源、决策解释 |
| `test_fusion_v2_temporal.py` | 20 | 时间列检测、标准化、插值、变化检测、一致性验证 |
| `test_fusion_v2_semantic.py` | 20 | 本体推理、LLM 语义（mock）、KG 集成（mock）、matching 集成 |
| `test_fusion_v2_conflict.py` | 14 | 冲突检测、6 策略解决、置信度评分、来源标注 |
| `test_fusion_v2_integration.py` | 14 | 端到端执行、向后兼容、工具注册、API 路由 |
| **合计** | **84** | 214 个 fusion 测试全部通过 (130 existing + 84 new) |

---

## 8 相关工作

### 8.1 传统GIS数据融合方法

传统GIS数据融合主要依赖桌面工具（ArcGIS、QGIS）的手动操作或 ETL 流水线（FME、GeoKettle）。这些方法虽然功能完备，但缺乏自动化的语义理解能力，用户需手动指定每个字段的映射关系。

### 8.2 基于规则的空间数据集成

OGC标准体系（WFS、WCS、SensorThings API）定义了空间数据的标准化访问接口，但主要解决数据访问层面的互操作性，不涉及语义层面的自动匹配。GeoSPARQL等语义Web标准提供了本体层面的地理空间语义模型，但实现复杂度高，实际采用率有限。

### 8.3 LLM驱动的数据处理

近期工作表明LLM在数据清洗、模式匹配、自然语言到SQL转换等任务上表现出色。然而，将LLM直接用于多模态空间数据融合的策略选择仍面临可靠性挑战——LLM可能"幻觉"出不存在的字段名或选择不适用的融合策略。MMFE采用的"确定性引擎 + LLM编排"模式，将策略选择的可靠性交给确定性的策略矩阵，将用户意图理解交给LLM，实现了两者的优势互补。

---

## 9 结论

本文提出并实现了一个面向GIS智能体系统的多模态空间数据智能融合引擎（MMFE）。该引擎的核心贡献包括：

1. **五阶段流水线架构**：画像 → 评估 → 对齐 → 融合 → 验证的清晰流程，每个阶段有明确的输入输出接口
2. **策略矩阵 + 数据感知评分**：通过11个类型对到10种策略的确定性映射提供粗筛，再通过基于IoU、几何类型、数据量比率的评分器进行精选（v5.6）
3. **五层渐进式语义字段匹配**：精确匹配 → 本体推理 → 等价组 → 向量嵌入 → 单位感知 → 模糊匹配的层级递进（v17.0 新增 Tier 1.5 本体层）
4. **自动单位检测与转换**：识别列名中的度量单位后缀，自动执行数值转换，消除跨数据源的单位不一致问题（v5.6）
5. **多源融合编排**：支持 N > 2 数据源的自动逐步融合，按类型优先级排序确保矢量作为空间基座（v5.6）
6. **10 维综合质量验证**：含异常值检测、微面多边形、列完整性、CRS一致性、拓扑验证、KS分布偏移检测（v7.1 扩展至10维）
7. **LLM Schema 对齐**：Gemini 2.5 Flash 基于两表 Schema + 采样数据输出结构化映射配置，替代脆弱的正则规则（v7.1）
8. **PostGIS 计算下推**：>10万行自动下推至数据库引擎执行 ST_Intersects/ST_Intersection/LATERAL 查询，避免 OOM（v7.1）
9. **模块化架构**：从单体 fusion_engine.py (~2100行) 重构为 fusion/ 包 (28模块)，策略模式 + 薄代理向后兼容（v7.1 → v17.0 扩展）
10. **异步工具层**：6 个工具函数 async + `asyncio.to_thread()` 包装，解除 ASGI 事件循环阻塞（v7.1 → v17.0 扩展）
11. **地理知识图谱**：networkx有向图建模空间实体关系，支持邻居查询、路径搜索、类型筛选（v7.0）
12. **分布式/核外计算**：大数据集自动分块读取和处理，透明切换，避免OOM（v7.0）
13. **自包含引擎模式**：无框架依赖的核心算法 + BaseToolset封装，确保可测试性和可移植性
14. **时序对齐层**：多时区标准化 + 3种插值 + 轨迹融合 + 多期变化检测，解决多源时间基准不一致问题（v17.0）
15. **GIS领域本体推理**：15等价组 + 8推导规则 + 5推理规则，实现语义级字段匹配和缺失字段自动推导（v17.0）
16. **6策略冲突消解**：source_priority/latest_wins/voting/llm_arbitration/spatial_proximity/user_defined + 置信度评分 + 来源标注（v17.0）
17. **逐要素可解释性**：`_fusion_confidence/sources/method/conflicts` 元数据 + 质量热力图 + 融合溯源（v17.0）

实验验证表明，引擎在 214 个测试用例（覆盖 10 种策略、5 种数据模态、6 层语义匹配、时序对齐、本体推理、冲突消解、可解释性、LLM 策略路由、嵌入语义匹配、知识图谱构建与查询、分块读取与融合、多源编排等场景）中通过率 100%，并已成功集成到拥有 3100+ 测试用例的生产级 GIS 智能体平台中，未引入任何新的回归故障。

v17.0 版本新增 4 大 v2.0 模块（6 个新文件，~1700 行生产代码 + ~1300 行测试 + ~540 行配置/迁移/前端），实现了从「能融合」到「融合好、解释清、冲突明」的质变。

---

## 参考实现

- 核心引擎包：`data_agent/fusion/`（28 模块，v17.0 扩展）
  - 公共 API：`fusion/__init__.py`
  - 数据结构：`fusion/models.py`
  - 策略注册：`fusion/strategies/__init__.py`（10 策略 + PostGIS 下推）
  - LLM Schema 对齐：`fusion/schema_alignment.py`（v7.1 新增）
- 向后兼容代理：`data_agent/fusion_engine.py`（~72行，薄代理层）
- 知识图谱：`data_agent/knowledge_graph.py`（~625行，v7.0新增）
- 工具封装：`data_agent/toolsets/fusion_tools.py`（~230行，4 个 async 工具）+ `data_agent/toolsets/knowledge_graph_tools.py`（~207行，v7.0新增）
- 测试套件：`data_agent/test_fusion_engine.py`（~1700行，147个测试）+ `data_agent/test_knowledge_graph.py`（~351行，17个测试）
- 基准测试：`data_agent/benchmark_fusion.py`（~700行，9项量化指标）
- 数据库迁移：`data_agent/migrations/018_create_fusion_operations.sql` + `019_create_knowledge_graph.sql`
- 智能体集成：`data_agent/agent.py`（FusionToolset + KnowledgeGraphToolset 注册）
- 提示词指引：`data_agent/prompts/general.yaml`（融合操作指引 + 知识图谱指引段落）
- 技术评审：`docs/technical-review-mmfe.md`（v7.0 缺陷评审 → v7.1 全部解决）
- 对比分析：`docs/comparison_MMFE_vs_MGIM.md`（MMFE与MGIM对比报告）
- 版本发布：`docs/RELEASE_NOTES_v7.0.md`（v7.0 + v7.1 发布说明）
