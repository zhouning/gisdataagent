---
name: site-selection
description: "多因素选址分析技能（采访模式）。通过结构化参数收集 → 排除法 + 加权叠加法进行空间适宜性评价，支持学校、医院、工厂等多种选址场景。"
metadata:
  domain: gis
  version: "3.0"
  intent_triggers: "site selection, 选址, 适宜性, suitability, 多因素, 评价"
---

# 多因素选址分析技能（Inversion 采访模式）

## 技能概述

选址分析是 GIS 最经典的应用场景之一。本技能采用 **Inversion 设计模式**——
先通过结构化采访收集完整需求参数，确认后再执行分析，杜绝参数猜测。

## Interaction Protocol: Structured Interview

You MUST follow this 4-phase protocol. Do NOT skip phases or guess parameters.

### Phase 1: 目标定义
Ask the user these questions (wait for answers before proceeding):
- **选址目标用途**: 工业/商业/住宅/农业/公共服务/学校/医院/其他？
- **研究区域范围**: 请上传研究区边界数据（GeoJSON/Shapefile）或输入行政区名称

### Phase 2: 约束条件收集
Based on the use type, ask about relevant constraints:
- **距离约束**: 距主干道、水源、居民区等的距离要求？（参考 references/site_selection_criteria.md 中的标准缓冲距离）
- **地形约束**: 坡度上限？海拔范围？
- **土地利用限制**: 需排除的用地类型？（基本农田、生态红线、水域等）
- **面积约束**: 最小地块面积要求？

### Phase 3: 权重确认
1. Present ALL collected factors in a summary table
2. Load default weights from references/site_selection_criteria.md for the selected scenario
3. Ask: "以下是默认权重分配，您需要调整吗？（1-10 分，或确认默认值）"
4. Ask: "评价方法偏好？加权叠加（默认）/ AHP 层次分析法"

### ⛔ EXECUTION GATE

**DO NOT execute any spatial analysis tools until Phases 1-3 are ALL completed.**
**If any required parameter is missing or ambiguous, ASK the user — do NOT guess or use defaults silently.**

Specifically, you MUST have confirmed:
- [ ] 选址用途已明确
- [ ] 研究区数据已上传或区域已确认
- [ ] 至少 3 个评价因素已收集
- [ ] 权重分配已确认

### Phase 4: 执行分析

Only after the gate passes, execute the standard workflow:

```
1. describe_geodataframe   → 画像各输入图层
2. reproject_spatial_data  → 统一投影坐标系
3. create_buffer           → 硬约束排除区 + 评分区缓冲
4. clip_data               → 研究区裁剪
5. overlay_analysis        → 多因素加权叠加，计算综合得分
6. 筛选最优区域            → 按得分排序，提取 top-N 候选
7. 生成专题图              → 适宜性分级渲染 + 候选点标注
```

## 方法论框架

### 第一阶段：排除法（硬约束）

硬约束是不可违反的限制条件，不满足任一条件即排除：
- 生态红线（自然保护区、水源保护区、湿地公园）
- 基本农田保护区
- 地质灾害高风险区（滑坡、泥石流）
- 坡度超限区（一般建设用地 < 25°）
- 洪水淹没区（百年一遇）

### 第二阶段：加权叠加法（软约束评分）

```
适宜性得分 = Σ(因素权重 × 因素得分)
```

每个因素归一化到 0-100 分，权重之和为 1.0。详见 references/site_selection_criteria.md。

## 常见问题与陷阱

- **坐标系未统一**: 叠加前必须 `reproject_spatial_data` 到同一投影坐标系
- **地理坐标系做缓冲**: EPSG:4326 下缓冲单位是度而非米，必须先转投影
- **因素遗漏**: 选址质量取决于因素完整性，务必在 Phase 2 充分收集
- **数据时效性**: 城市扩张区域建议使用近 2-3 年数据

## 可用工具

- `describe_geodataframe` — 数据画像
- `reproject_spatial_data` — 坐标系转换
- `create_buffer` — 缓冲区生成
- `clip_data` — 研究区裁剪
- `overlay_analysis` — 多图层叠加
- `generate_choropleth` — 适宜性分级渲染
