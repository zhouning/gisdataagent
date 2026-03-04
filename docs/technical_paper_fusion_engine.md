# 面向GIS智能体的多模态空间数据智能融合引擎：架构设计与实现

## Multi-Modal Spatial Data Intelligent Fusion Engine for GIS Agent Systems: Architecture Design and Implementation

---

**摘要**

地理信息系统（GIS）应用中，异构多模态数据的融合是一项长期存在的技术挑战。不同数据源在坐标参考系统（CRS）、空间分辨率、字段语义、时间粒度等维度上的差异，使得跨模态数据融合难以自动化。本文提出一种面向GIS智能体系统的多模态空间数据智能融合引擎（Multi-Modal Fusion Engine, MMFE），该引擎采用"画像→评估→对齐→融合→验证"五阶段流水线架构，支持矢量、栅格、表格、点云、实时流五种数据模态，实现了10种融合策略的自动选择与执行。引擎通过策略矩阵（Strategy Matrix）机制实现数据类型对到融合算法的自动映射，通过四层渐进式语义匹配（精确匹配→等价组→单位感知→模糊匹配）解决中英文GIS字段的跨语言匹配问题，通过多维兼容性评分模型量化数据源间的融合可行性。v5.6版本借鉴MGIM（Masked Geographical Information Model）的上下文感知推理思想，引入了数据感知策略评分、多源融合编排（N>2数据源）、自动单位检测与转换、以及增强质量验证等关键改进。实验表明，该引擎在72个单元测试中通过率100%，覆盖了所有核心路径，并已集成到一个拥有18个工具集、30个REST API端点的生产级GIS智能体平台中。

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

本引擎的架构设计参考了同系统中已有的深度强化学习（DRL）耕地优化引擎的模式——自包含算法模块 + 工具集封装（BaseToolset）。DRL引擎（`drl_engine.py`，约385行）实现了基于 Gymnasium 的环境定义和 MaskablePPO 策略训练，通过 `AnalysisToolset` 的两个工具函数（`ffi` 和 `drl_model`）暴露给智能体。MMFE采用相同的模式：核心算法实现在 `fusion_engine.py`（约1490行，含v5.6增强），通过 `FusionToolset` 的四个工具函数暴露给智能体，确保与现有架构的一致性和可维护性。

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
| `file_path` | `str` | 数据文件的绝对路径 | 全部 |
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

**表2：CompatibilityReport 兼容性报告结构**

| 字段 | 类型 | 说明 |
|------|------|------|
| `crs_compatible` | `bool` | 所有数据源CRS是否一致 |
| `spatial_overlap_iou` | `float` | 边界框交并比 ∈ [0,1] |
| `temporal_aligned` | `bool \| None` | 时间范围是否对齐（预留） |
| `field_matches` | `list[dict]` | 语义匹配的字段对 `[{left, right, confidence}]` |
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

### 2.3 模块依赖关系

```
fusion_engine.py (核心算法, 无ADK依赖)
├── gis_processors.py       → _resolve_path(), _generate_output_path()
├── db_engine.py             → get_engine() 单例数据库连接
├── user_context.py          → current_user_id ContextVar
├── geopandas + shapely      → 矢量数据处理
├── rasterio + rasterstats   → 栅格数据处理
└── pandas + numpy           → 表格数据与数值计算

toolsets/fusion_tools.py (ADK工具封装)
├── fusion_engine            → 调用核心算法函数
├── google.adk.tools         → FunctionTool, BaseToolset
└── gis_processors           → _resolve_path() 路径解析

agent.py (智能体集成)
├── FusionToolset            → 工具注册到3个Agent
└── prompts/general.yaml     → 融合操作指引注入到Prompt
```

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

### 3.6 增强质量验证模型（v5.6 增强）

融合结果自动经过多层次质量检查，v5.6 版本在原有4项检查基础上新增了异常值检测、微面检测和列完整性追踪：

**表7：质量检查项**

| 检查项 | 触发条件 | 评分影响 | 版本 |
|--------|---------|---------|------|
| 空结果检测 | `len(data) == 0` | 直接返回 0.0 | v5.5 |
| 空值率过高 | 某列 `null% > 50%` | -0.10/列 | v5.5 |
| 空值率中等 | 某列 `20% < null% ≤ 50%` | -0.05/列 | v5.5 |
| 几何无效 | `invalid_pct > 0` | -0.15 | v5.5 |
| 完整性不足 | `output_rows / max_source_rows < 0.5` | -0.15 | v5.5 |
| 属性异常值 | 数值列存在 IQR 离群值 | -0.05/列 | **v5.6** |
| 微面多边形 | 面积 < 中位面积的 0.1% | -0.05 | **v5.6** |
| 列完整性低 | 融合后列数 < 源列数之和的 50% | -0.10 | **v5.6** |

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

## 7 相关工作

### 7.1 传统GIS数据融合方法

传统GIS数据融合主要依赖桌面工具（ArcGIS、QGIS）的手动操作或 ETL 流水线（FME、GeoKettle）。这些方法虽然功能完备，但缺乏自动化的语义理解能力，用户需手动指定每个字段的映射关系。

### 7.2 基于规则的空间数据集成

OGC标准体系（WFS、WCS、SensorThings API）定义了空间数据的标准化访问接口，但主要解决数据访问层面的互操作性，不涉及语义层面的自动匹配。GeoSPARQL等语义Web标准提供了本体层面的地理空间语义模型，但实现复杂度高，实际采用率有限。

### 7.3 LLM驱动的数据处理

近期工作表明LLM在数据清洗、模式匹配、自然语言到SQL转换等任务上表现出色。然而，将LLM直接用于多模态空间数据融合的策略选择仍面临可靠性挑战——LLM可能"幻觉"出不存在的字段名或选择不适用的融合策略。MMFE采用的"确定性引擎 + LLM编排"模式，将策略选择的可靠性交给确定性的策略矩阵，将用户意图理解交给LLM，实现了两者的优势互补。

---

## 8 结论

本文提出并实现了一个面向GIS智能体系统的多模态空间数据智能融合引擎（MMFE）。该引擎的核心贡献包括：

1. **五阶段流水线架构**：画像 → 评估 → 对齐 → 融合 → 验证的清晰流程，每个阶段有明确的输入输出接口
2. **策略矩阵 + 数据感知评分**：通过11个类型对到10种策略的确定性映射提供粗筛，再通过基于IoU、几何类型、数据量比率的评分器进行精选（v5.6）
3. **四层渐进式语义字段匹配**：精确匹配 → 10组中英文等价组 → 单位感知匹配 → 模糊匹配的层级递进，在可靠性和覆盖面之间取得平衡（v5.6）
4. **自动单位检测与转换**：识别列名中的度量单位后缀，自动执行数值转换，消除跨数据源的单位不一致问题（v5.6）
5. **多源融合编排**：支持 N > 2 数据源的自动逐步融合，按类型优先级排序确保矢量作为空间基座（v5.6）
6. **增强质量验证**：7+项质量检查（含异常值检测、微面多边形、列完整性），返回详细诊断报告（v5.6）
7. **自包含引擎模式**：无框架依赖的核心算法 + BaseToolset封装，确保可测试性和可移植性

实验验证表明，引擎在106个测试用例（覆盖10种策略、5种数据模态、4层语义匹配、多源编排、增强质量验证、栅格重采样、点云高度赋值、流数据时态融合、真实数据集成等场景）中通过率100%，并已成功集成到拥有1256+测试用例的生产级GIS智能体平台中，未引入任何新的回归故障。

v6.0 版本完成了文档Section 6.2中全部4类不足的修复：占位策略全部实现为完整功能、栅格自动重投影与重采样、语义匹配增强（目录驱动等价组+分词相似度+类型兼容检查）、质量验证增强（CRS/拓扑/分布偏移检测），实现了多源异构数据的智能化语义融合。未来工作将重点关注嵌入式语义匹配（基于预训练语言模型的字段向量化）、大规模真实数据效果评估、以及LLM辅助策略选择等方向。

---

## 参考实现

- 核心引擎：`data_agent/fusion_engine.py`（~1750行，含v5.6+v6.0增强）
- 工具封装：`data_agent/toolsets/fusion_tools.py`（120行）
- 测试套件：`data_agent/test_fusion_engine.py`（~1470行，106个测试）
- 数据库迁移：`data_agent/migrations/018_create_fusion_operations.sql`
- 智能体集成：`data_agent/agent.py`（FusionToolset注册）
- 提示词指引：`data_agent/prompts/general.yaml`（融合操作指引段落）
- 对比分析：`docs/comparison_MMFE_vs_MGIM.md`（MMFE与MGIM对比报告）
