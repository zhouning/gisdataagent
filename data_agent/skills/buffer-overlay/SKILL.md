---
name: buffer-overlay
description: "缓冲区与叠加分析技能。创建缓冲区、执行空间叠加（交集/合并/差集/裁剪），统计分析结果面积和属性。"
metadata:
  domain: gis
  version: "2.0"
  intent_triggers: "buffer, overlay, clip, 缓冲区, 叠加, 裁剪, 相交, 差集"
---

# 缓冲区与叠加分析技能

## 核心能力

1. **缓冲区分析**: `create_buffer` 创建等距/变距缓冲区
2. **叠加分析**: `overlay_analysis` 执行交集/合并/差集/对称差
3. **裁剪**: `clip_data` 按边界裁剪数据
4. **镶嵌**: `tessellate` 创建规则格网（六边形/正方形）
5. **坐标转换**: `reproject_spatial_data` 确保投影坐标系下操作

## 缓冲区类型

| 类型 | 说明 | 适用场景 |
|------|------|----------|
| 等距缓冲区 | 所有方向相同距离 | 保护区划定、服务范围 |
| 变距缓冲区 | 根据属性字段确定距离 | 不同等级道路的影响范围 |
| 单侧缓冲区 | 仅在一侧生成 | 河流一侧的保护带 |
| 溶解缓冲区 | 合并重叠的缓冲区 | 多个设施的联合服务范围 |

### 关键规则
- **必须使用投影坐标系**: 地理坐标系（度）下 buffer(100) ≈ 1100万米，完全错误
- 缓冲区前先 `reproject_spatial_data` 到当地高斯带或 UTM 带
- 缓冲区后建议 `dissolve=True` 合并重叠区域
- 负值缓冲区可用于内缩（收缩多边形边界）

## 叠加分析类型

| 类型 | 函数参数 | 说明 | 典型应用 |
|------|---------|------|----------|
| intersection | `how='intersection'` | 两层的公共部分 | 耕地与保护区重叠面积 |
| union | `how='union'` | 两层的全部范围 | 合并多个行政区 |
| difference | `how='difference'` | A 减去 B | 排除已建设区域 |
| symmetric_difference | `how='symmetric_difference'` | 不重叠的部分 | 变化检测 |

### 裁剪 vs 相交
- **裁剪** (`clip_data`): 保留 A 在 B 范围内的部分，只保留 A 的属性
- **相交** (`overlay_analysis`, intersection): 保留公共部分，合并 A 和 B 的属性
- 只需要几何裁剪时用 clip，需要属性合并时用 overlay

## 面积统计方法

- 叠加后用 `describe_geodataframe` 获取面积统计
- 或用 `engineer_spatial_features` 添加面积字段
- 面积计算必须在投影坐标系下进行
- 百分比计算: `overlay_area / original_area × 100%`

## 分析工作流

1. **确认坐标系**: `describe_geodataframe` 检查 CRS，必要时 `reproject_spatial_data`
2. **创建缓冲区**: `create_buffer(distance=500, dissolve=True)` — 距离单位取决于 CRS
3. **执行叠加**: `overlay_analysis(how='intersection')` 或 `clip_data`
4. **统计结果**: `engineer_spatial_features` 计算面积/周长
5. **可视化**: `visualize_interactive_map` 或 `generate_choropleth` 展示结果

## 常见问题与解决方案

| 问题 | 原因 | 解决方案 |
|------|------|----------|
| 缓冲区异常大/小 | 在地理坐标系下操作 | 先投影到米制坐标系 |
| 叠加后出现碎片 | 边界精度不一致产生 slivers | 设置容差或过滤微小面积 |
| 属性丢失 | 使用了 clip 而非 overlay | 需要属性合并时用 overlay |
| 拓扑错误 | 叠加后几何无效 | 用 `buffer(0)` 修复或 `make_valid` |
| 结果为空 | 两层无空间重叠 | 先检查两层的空间范围是否有交集 |
| 面积计算不准 | 在 EPSG:4326 下计算 | 投影到当地高斯带后再计算 |
