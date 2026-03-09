---
name: visualization
description: "地图渲染、图表生成与视觉导出技能。支持交互地图、Choropleth、热力图、气泡图、3D可视化和PNG导出。"
metadata:
  domain: visualization
  version: "1.0"
  intent_triggers: "visualization, map, chart"
---

# 可视化技能

## 核心能力

1. **交互地图**: `visualize_interactive_map` 生成 Folium 交互地图（自动选择底图、图层样式）
2. **专题地图**: `generate_choropleth` 分级设色图、`generate_bubble_map` 气泡大小图
3. **热力图**: `generate_heatmap` 基于 KDE 的热力密度图
4. **3D 地图**: `generate_3d_map` deck.gl/MapLibre 3D 渲染（拉伸体、柱状图、弧线、散点）
5. **图层控制**: `control_map_layer` 自然语言控制地图图层（显示/隐藏/样式/移除）
6. **静态导出**: `export_map_png` 高分辨率 PNG 导出
7. **多图层合成**: `compose_map` 多个数据源叠加到一张地图
8. **通用可视化**: `visualize_geodataframe` 快速预览 GeoDataFrame

## 地图样式建议

- 分级设色: 5~7 级为宜，推荐 Natural Breaks 分类
- 热力图: 半径 10~25 像素，适合点密度展示
- 3D 拉伸: height 字段应为数值型，extrusion_scale 根据数据范围调整
- 颜色方案: 土地利用推荐分类色，数值指标推荐连续色（YlOrRd、Blues）
