# 生态环境评估报告

## 研究区概况
- 区域名称: {{study_area}}
- 总面积: {{total_area}} km²
- 数据源: {{data_sources}}
- 评估时间: {{timestamp}}

---

## NDVI 植被指数分析

| 指标 | 值 |
|------|-----|
| NDVI 均值 | {{ndvi_mean}} |
| NDVI 标准差 | {{ndvi_std}} |
| NDVI 最小值 | {{ndvi_min}} |
| NDVI 最大值 | {{ndvi_max}} |

### 植被覆盖分级

| 等级 | NDVI 范围 | 面积 (km²) | 占比 |
|------|----------|-----------|------|
| 无植被 | < 0 | {{ndvi_class_1_area}} | {{ndvi_class_1_pct}} |
| 极低覆盖 | 0-0.15 | {{ndvi_class_2_area}} | {{ndvi_class_2_pct}} |
| 低覆盖 | 0.15-0.3 | {{ndvi_class_3_area}} | {{ndvi_class_3_pct}} |
| 中覆盖 | 0.3-0.45 | {{ndvi_class_4_area}} | {{ndvi_class_4_pct}} |
| 中高覆盖 | 0.45-0.6 | {{ndvi_class_5_area}} | {{ndvi_class_5_pct}} |
| 高覆盖 | 0.6-0.75 | {{ndvi_class_6_area}} | {{ndvi_class_6_pct}} |
| 极高覆盖 | > 0.75 | {{ndvi_class_7_area}} | {{ndvi_class_7_pct}} |

---

## DEM 地形分析

| 指标 | 值 |
|------|-----|
| 高程范围 | {{elev_min}} – {{elev_max}} m |
| 平均高程 | {{elev_mean}} m |
| 平均坡度 | {{slope_mean}}° |
| 最大坡度 | {{slope_max}}° |

### 坡度分级

| 坡度级 | 范围 | 面积 (km²) | 占比 |
|--------|------|-----------|------|
| 平坦 | 0-5° | {{slope_flat_area}} | {{slope_flat_pct}} |
| 缓坡 | 5-15° | {{slope_gentle_area}} | {{slope_gentle_pct}} |
| 中坡 | 15-25° | {{slope_moderate_area}} | {{slope_moderate_pct}} |
| 陡坡 | 25-45° | {{slope_steep_area}} | {{slope_steep_pct}} |
| 极陡 | >45° | {{slope_extreme_area}} | {{slope_extreme_pct}} |

### 坡向分布
{{aspect_distribution}}

---

## LULC 土地利用现状

{{lulc_distribution_table}}

---

## 生态敏感性综合评价

### 评价因子与权重

| 因子 | 权重 | 评分依据 |
|------|------|---------|
| 植被覆盖 (NDVI) | 0.30 | NDVI 等级越高，生态价值越大 |
| 地形坡度 | 0.20 | 坡度越大，生态脆弱性越高 |
| 土地利用类型 | 0.25 | 林地/湿地最高，建设用地最低 |
| 高程 | 0.15 | 高海拔区域生态敏感性较高 |
| 水系距离 | 0.10 | 距水系越近，生态功能越重要 |

### 综合评分
- 敏感性评分: {{sensitivity_score}}/100
- 敏感性等级: {{sensitivity_grade}}

| 等级 | 分值范围 | 建议 |
|------|---------|------|
| 极高敏感 | ≥80 | 严格保护，禁止开发 |
| 高度敏感 | 60-79 | 限制开发，生态修复优先 |
| 中度敏感 | 40-59 | 有条件开发，需生态评估 |
| 低度敏感 | 20-39 | 可适度开发 |
| 不敏感 | <20 | 可按规划开发 |

---

## 改进建议

{{recommendations}}

---

*报告由 GIS Data Agent 自动生成*
