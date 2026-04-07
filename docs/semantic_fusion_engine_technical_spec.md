# 多模态地理空间数据智能化语义融合引擎 — 技术详述

> 本文档基于 GIS Data Agent v18.5+ 源码（`data_agent/fusion/`，20 个 Python 模块 + 11 个策略实现）精确提取，供科技奖申报材料引用。

---

## 一、总体架构：7 阶段流水线

融合引擎采用 **7 阶段串行流水线** 设计，每个阶段有明确的输入/输出契约：

```
┌─────────────────────────────────────────────────────────────────────────┐
│                    7 阶段融合流水线 (Pipeline)                          │
│                                                                         │
│  S1           S2              S3          S4         S5       S6    S7  │
│ 源画像 → 兼容性评估 → 源对齐 → 时序预对齐 → 策略执行 → 冲突解决 → 质量验证│
│                  ↓                                     ↓        ↓       │
│            语义字段匹配                           可解释性注解  资产注册  │
│            (4层渐进式)                           (置信度+热力图) (血缘)   │
└─────────────────────────────────────────────────────────────────────────┘
```

| 阶段 | 模块文件 | 核心功能 | 关键技术 |
|:----:|---------|---------|---------|
| **S1 源画像** | `profiling.py` | 自动检测数据类型（矢量/栅格/表格/点云/流），提取 CRS、空间范围、字段元数据、统计分布 | 支持 6 类格式（含 GDB），大栅格窗口采样（>1M 像素时取中心 1024×1024），Dask 惰性加载大 CSV |
| **S2 兼容性评估** | `compatibility.py` + `matching.py` | CRS 一致性判定、Bounding Box IoU 空间重叠度计算、**4 层渐进式语义字段匹配**、融合策略推荐 | IoU 基于 Shapely 几何运算；兼容性综合评分 4 维加权（CRS 0.3 + 空间重叠 0.3 + 字段匹配 0.2 + 策略可用 0.2）|
| **S3 源对齐** | `alignment.py` | CRS 统一投影（矢量 to_crs + 栅格 rasterio 重投影）、度量单位自动转换（亩↔公顷↔m²）、字段名冲突解决（`_right` 后缀） | 单位检测基于 `UNIT_PATTERNS` 正则 + 基名相似度 ≥0.6 触发自动换算 |
| **S4 时序预对齐** | `temporal.py` | 时间列自动检测（23 种模式含中文）、异构时间戳标准化（10 种格式→UTC ISO8601）、时间窗口连接、事件序列对齐、变化检测 | 3 种插值方法（linear/nearest/spline），支持 `pre_align()` 在策略执行前完成时序对齐 |
| **S5 策略执行** | `execution.py` + `strategies/`(11 文件) | 10 种融合策略的实际执行 + 自动策略选择 + N>2 多源级联编排 + PostGIS 下推加速 | 自动策略选择基于多维评分（IoU、几何类型兼容性、数据量比、用户意图关键词），PostGIS 下推减少内存占用 |
| **S6 冲突解决** | `conflict_resolver.py` | 属性冲突检测 + 6 种解决策略 + 置信度评分 + 来源标注 | 置信度公式：`0.4×timeliness + 0.3×precision + 0.3×completeness`，冲突行置信度额外 −0.3 |
| **S7 质量验证** | `validation.py` + `explainability.py` | 10 项质量检查评分 + 4 列可解释性注解 + 质量热力图 + 血缘追踪 + 数据资产注册 | KS 检验分布漂移检测（scipy），微多边形检测（面积<中位数 0.1%），拓扑自相交验证（shapely） |

---

## 二、10 种融合策略

策略由 `STRATEGY_MATRIX` 基于数据类型对自动路由（`constants.py`），每种策略独立实现在 `strategies/` 目录：

| 策略 | 数据类型对 | 实现文件 | 核心算法 |
|------|-----------|---------|---------|
| `spatial_join` | 矢量×矢量 | `spatial_join.py` | 空间谓词连接（intersects/contains/within），>100K 行分块执行 |
| `overlay` | 矢量×矢量 | `overlay.py` | 几何叠加（union/intersection/symmetric_difference） |
| `nearest_join` | 矢量×矢量 | `nearest_join.py` | K 近邻空间连接，低 IoU(<0.3) 时自动优选 |
| `attribute_join` | 矢量×表格 | `attribute_join.py` | 键字段属性连接，自动检测 ID 类字段 |
| `zonal_statistics` | 矢量×栅格 | `zonal_stats.py` | 分区统计（mean/min/max/count/sum/median/std） |
| `point_sampling` | 矢量×栅格 | `point_sampling.py` | 点位栅格值采样 |
| `band_stack` | 栅格×栅格 | `band_stack.py` | 多波段叠加 |
| `time_snapshot` | 矢量×时序流 | `time_snapshot.py` | 时间窗口空间连接 |
| `height_assign` | 矢量×点云 | `height_assign.py` | LiDAR 高程赋值 |
| `raster_vectorize` | 栅格→表格 | `raster_vectorize.py` | 栅格网格矢量化 |
| PostGIS 下推 | 大数据集 | `postgis_pushdown.py` | SQL 级别执行融合，避免全量加载内存 |

**自动策略选择**（`_score_strategies()`）使用多维评分机制：
- 空间重叠 IoU 高 → 加权 spatial_join
- IoU 低或点几何 → 加权 nearest_join
- 面×面中等重叠 → 加权 overlay
- 用户意图关键词（12 个中英文关键词映射）→ 目标策略 +0.5 权重提升

---

## 三、4 层渐进式语义字段匹配（核心创新）

位于 `matching.py` 的 `_find_field_matches()` 函数实现了 **4 层渐进式语义匹配**，逐层递进、置信度递减：

```
输入: 源A字段列表 × 源B字段列表
  ↓
Layer 1: 精确匹配 (confidence=1.0)         ← 不区分大小写的字符串相等
  ↓ (未匹配字段)
Layer 1.5: 本体推理匹配 (confidence=0.85)   ← GIS领域本体图谱 (opt-in)
  ↓ (未匹配字段)
Layer 2: 等价组匹配 (confidence=0.8)        ← 硬编码10组 + 语义目录YAML动态加载
  ↓ (未匹配字段)
Layer 2.5a: LLM全Schema对齐 (opt-in)       ← Gemini 2.0 Flash 全字段推理
   或
Layer 2.5b: 嵌入向量匹配 (confidence=0.78)  ← Gemini text-embedding-004 余弦相似度≥0.75
  ↓ (未匹配字段)
Layer 3: 单位感知匹配 (confidence=0.75)     ← 基名相似度≥0.6 且检测到不同计量单位
  ↓ (未匹配字段)
Layer 4: 分词模糊匹配 (confidence=0.5-0.7)  ← 60%Jaccard+40%SequenceMatcher, 类型兼容门控
  ↓
输出: [{left, right, confidence, match_type, ...}]
```

**逐层技术细节**：

### Layer 1 — 精确匹配

大小写归一化后字符串比较，`confidence=1.0`。这是最高置信度的匹配，适用于相同系统或标准产出的数据源。

### Layer 1.5 — 本体推理匹配（opt-in）

加载 GIS 领域本体图谱（`ontology.py` 的 `OntologyReasoner`），通过概念层级关系发现语义等价字段，`confidence=0.85`。例如"土地利用类型"和"LULC_Class"通过本体中的 `rdfs:label` 多语言标签建立等价关系。

### Layer 2 — 等价组匹配

维护 10 个硬编码等价组，覆盖 GIS 领域最常见的语义等价关系：

```python
{"area", "面积", "zmj", "tbmj", "mj", "shape_area"}
{"name", "名称", "mc", "dlmc", "qsdwmc", "dkmc"}
{"code", "编码", "dm", "dlbm", "bm", "dkbm"}
{"type", "类型", "lx", "dllx", "tdlylx"}
{"slope", "坡度", "pd", "slope_deg"}
{"id", "objectid", "fid", "gid", "pkid"}
{"population", "人口", "rk", "rksl", "pop"}
{"address", "地址", "dz", "addr", "location"}
{"elevation", "高程", "dem", "gc", "alt", "height"}
{"perimeter", "周长", "zc", "shape_length"}
```

同时从 `semantic_catalog.yaml` 动态加载领域别名并合并（重叠组自动 union），`confidence=0.8`。

### Layer 2.5 — 两条可选路径

**2.5a LLM Schema 对齐**（`schema_alignment.py`）：将未匹配字段的完整元数据（name, dtype, null_pct）发送给 Gemini 2.0 Flash，一次 LLM 调用完成全局字段映射，返回带 reasoning 的匹配结果。启用后**跳过 2.5b 至 Layer 4**，适用于字段命名高度异构的场景。

**2.5b 嵌入向量匹配**（`matching.py`）：使用 Gemini `text-embedding-004` 模型对字段名+类型信息生成 768 维向量，计算余弦相似度，阈值 ≥0.75，模块级缓存避免重复 API 调用，`confidence=0.78`。同时执行类型兼容性检查，阻止数值型↔文本型的错误匹配。

### Layer 3 — 单位感知匹配

检测字段名中的度量单位模式（5 类：亩/m²/公顷/米/千米），剥离单位后缀提取基名，基名 SequenceMatcher 相似度 ≥0.6 即匹配，并触发 S3 阶段的自动单位换算（8 组转换因子），`confidence=0.75`。

### Layer 4 — 分词模糊匹配

- **分词器**：支持下划线分割、camelCase 拆分、数字边界切分（如 `landUseType` → `[land, use, type]`）
- **相似度计算**：60% Jaccard 令牌重叠 + 40% SequenceMatcher 全名比率
- **类型兼容门控**：数值型↔文本型不允许匹配（防止 `slope` 匹配 `slope_type`）
- 阈值 ≥0.65，`confidence = 0.5 + score×0.2`（范围 0.5-0.7）

---

## 四、10 项融合质量验证（S7 阶段详情）

`validation.py` 实现了 **10 项检查的扣分制评分**（满分 1.0）：

| 检查项 | 扣分 | 技术手段 |
|--------|:----:|---------|
| 1. 空结果检测 | −1.0 | 行数=0 直接判 0 分 |
| 2. 逐列空值率 | −0.10/−0.05 | >50% 重扣，20-50% 轻扣 |
| 3. 几何有效性 | −0.15 | `is_valid` 检测无效几何 |
| 4. 行数完整性 | −0.15 | 输出行数/源最大行数 <50% 扣分 |
| 5. 极端异常值 | −0.05 | >5×IQR 范围占比 >5% |
| 6. 微多边形检测 | −0.05 | 面积 < 中位数 0.1%，>10% 要素触发 |
| 7. 列完整性 | 信息项 | 输出列数/源列数比 |
| 8. CRS 一致性 | 信息项 | 验证投影是否统一 |
| 9. 拓扑验证 | −0.10 | `shapely.validation.explain_validity` 自相交检测 |
| 10. 分布漂移检测 | −0.05 | KS 双样本检验，p<0.01 为显著漂移 |

---

## 五、v2.0 增强模块

| 模块 | 文件 | 核心创新 |
|------|------|---------|
| **时序对齐** | `temporal.py` | 23 种时间列模式自动检测（含中文）、10 种异构日期格式→UTC、3 种插值法、变化检测（added/removed/modified/unchanged 分类） |
| **冲突解决** | `conflict_resolver.py` | 6 种策略（源优先级/最新优先/投票法/LLM 仲裁/空间邻近/自定义函数），加权置信度评分，来源标注 |
| **可解释性** | `explainability.py` | 4 列逐要素注解（`_fusion_confidence/sources/conflicts/method`）、三级质量热力图（低/中/高）、自然语言决策解释 |
| **LLM 语义理解** | `semantic_llm.py` | Gemini 驱动的字段语义分类（13 种语义类型）、可推导字段推理（公式生成）、深度语义匹配 |
| **LLM Schema 对齐** | `schema_alignment.py` | 全字段级一次性 LLM 推理，替代多层启发式规则，适用于字段命名高度异构的场景 |
| **文档上下文注入** | `fusion_tools.py` | 从 PDF/Word/Excel 提取结构化元数据（来源/时效/精度/完整性），驱动冲突解决权重 |

---

## 六、关键数字摘要

| 指标 | 数值 |
|------|------|
| 融合模块总代码 | 20 个 Python 模块 + 11 个策略实现 |
| 融合策略 | 10 种（覆盖矢量×矢量/栅格/表格/点云/时序流全组合） |
| 流水线阶段 | 7 阶段（画像→兼容性→对齐→时序→策略→冲突→质量） |
| 语义匹配层数 | 4 层渐进式（精确→等价组→嵌入/LLM→分词模糊），含 2 条可选 LLM 增强路径 |
| 质量检查项 | 10 项（含 KS 分布漂移检验、微多边形检测、拓扑自相交验证） |
| 冲突解决策略 | 6 种 |
| 时间格式支持 | 10 种异构格式 + 23 种列名模式 |
| 单位自动换算 | 5 类度量单位、8 组转换因子 |
| 等价语义组 | 10 组硬编码 + 语义目录 YAML 动态扩展 |
| 嵌入模型 | Gemini text-embedding-004（768 维） |
| 集成测试 | 84 个（v2.0 模块）+ 21 个（工具层集成） |
