# deck.gl 图层类型参考

## 支持的图层类型

### ExtrusionLayer (拉伸体)
- 用途: 3D 建筑物、人口密度柱状图
- 参数: `elevation_column`(高度字段), `elevation_scale`(倍率), `color`
- 示例: 建筑物按楼层数拉伸、各区县按人口密度拉伸

### ColumnLayer (柱状图)
- 用途: 点位置上的 3D 柱状图
- 参数: `radius`(柱半径), `elevation_column`, `color`
- 适合: 离散点位的数值对比

### ArcLayer (弧线)
- 用途: OD 流向图、通勤路径
- 参数: `source`(起点坐标), `target`(终点坐标), `color`, `width`
- 适合: 交通流、贸易流、人口迁移

### ScatterplotLayer (散点)
- 用途: 点分布图
- 参数: `radius`(半径), `color`, `opacity`
- 支持按字段动态调整半径和颜色

### HeatmapLayer (热力图)
- 用途: 密度分布
- 参数: `intensity`(强度), `radius_pixels`(像素半径), `threshold`
- 不需要预计算核密度，浏览器端实时渲染

## 底图配置 (MapLibre)

| 底图 | URL 格式 |
|------|---------|
| CartoDB Positron | `https://basemaps.cartocdn.com/gl/positron-gl-style/style.json` |
| CartoDB Dark | `https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json` |
| OSM Liberty | `https://tiles.stadiamaps.com/styles/osm_bright.json` |

## 交互功能
- hover tooltip: 鼠标悬停显示属性
- onClick: 点击选中要素
- viewState: 控制 longitude/latitude/zoom/pitch/bearing

## 性能建议
- 要素数 > 10 万时启用 binary transport
- 大面要素建议先简化几何（tolerance 0.001°）
- 热力图 radius_pixels 建议 20-50
