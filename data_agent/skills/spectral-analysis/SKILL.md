---
name: spectral-analysis
description: "遥感光谱分析技能。计算15+光谱指数(NDVI/EVI/NDWI/NDBI/NBR等)、智能指数推荐、云覆盖评估、多时相对比和植被/水体/城市/火灾监测。"
metadata:
  domain: remote_sensing
  version: "1.0"
  intent_triggers: "光谱 spectral NDVI EVI SAVI NDWI NDBI NBR NDSI 植被指数 vegetation index 水体指数 water 城市指数 urban 火灾 burn 遥感指数 remote sensing 波段运算 band math 光谱分析"
---

# 遥感光谱分析技能

## 技能概述

本技能提供完整的遥感光谱分析能力，覆盖从数据质量评估到专业指数计算的全流程：

1. **数据质量门控**：云覆盖检测 + 自动降级策略
2. **光谱指数计算**：15+ 预置指数 + 自定义波段运算
3. **智能推荐**：根据分析目标自动推荐最适指数组合
4. **经验池检索**：复用历史成功分析经验

## 光谱指数库 (15+ 指数)

### 植被指数

| 指数 | 公式 | 适用场景 | Sentinel-2 波段 |
|------|------|----------|----------------|
| NDVI | (NIR-Red)/(NIR+Red) | 通用植被监测 | B08, B04 |
| EVI | 2.5×(NIR-Red)/(NIR+6×Red-7.5×Blue+1) | 高密度植被，减少大气影响 | B08, B04, B02 |
| SAVI | (NIR-Red)×(1+L)/(NIR+Red+L) | 裸土暴露区域，L=0.5 | B08, B04 |
| GNDVI | (NIR-Green)/(NIR+Green) | 叶绿素含量估算 | B08, B03 |
| NDRE | (NIR-RedEdge)/(NIR+RedEdge) | 精准农业，早期胁迫检测 | B08, B05 |
| ARVI | (NIR-2×Red+Blue)/(NIR+2×Red-Blue) | 大气校正增强 | B08, B04, B02 |

### 水体指数

| 指数 | 公式 | 适用场景 |
|------|------|----------|
| NDWI | (Green-NIR)/(Green+NIR) | 水体提取 |
| MNDWI | (Green-SWIR)/(Green+SWIR) | 城区水体，抑制建筑噪声 |

### 城市/土壤指数

| 指数 | 公式 | 适用场景 |
|------|------|----------|
| NDBI | (SWIR-NIR)/(SWIR+NIR) | 建设用地提取 |
| BSI | ((SWIR+Red)-(NIR+Blue))/((SWIR+Red)+(NIR+Blue)) | 裸土识别 |

### 火灾/雪/水分指数

| 指数 | 公式 | 适用场景 |
|------|------|----------|
| NBR | (NIR-SWIR2)/(NIR+SWIR2) | 火灾烧伤面积评估 |
| NDSI | (Green-SWIR)/(Green+SWIR) | 积雪覆盖检测 |
| NDMI | (NIR-SWIR1)/(NIR+SWIR1) | 植被水分含量 |
| LAI | EVI × 3.618 - 0.118 | 叶面积指数（从EVI派生） |
| CI | (Red-Blue)/(Red+Blue) | 土壤颜色指数 |

## 数据质量门控

### 云覆盖检测

分析前自动评估影像云覆盖率：

| 云覆盖率 | 处理策略 |
|----------|----------|
| < 10% | 直接分析 |
| 10%-30% | 警告 + 可选云掩膜 |
| 30%-70% | 建议切换时相或使用 SAR 数据 |
| > 70% | 自动降级到 SAR 或拒绝分析 |

### 自动降级策略

当光学影像不可用时，系统自动推荐替代方案：
- **光学 → SAR**：适用于持续阴雨区域
- **高分辨率 → 中分辨率**：Sentinel-2 不可用时降级到 Landsat
- **单时相 → 多时相合成**：利用时间窗口内多景影像合成

## 分析工作流

```
1. assess_cloud_cover       → 检查影像质量，决定是否继续
2. recommend_indices         → 根据分析目标推荐指数组合
3. search_rs_experience      → 检索相似案例的最佳实践
4. calculate_spectral_index  → 计算推荐的光谱指数
5. describe_raster           → 查看计算结果统计信息
6. visualize_raster          → 生成指数分布可视化
```

## 经验池

系统内置遥感分析经验池，覆盖常见场景：
- **植被监测**：NDVI + EVI + SAVI 组合，夏季影像优先
- **水体检测**：NDWI + MNDWI，注意城区建筑干扰
- **城市扩张**：NDBI + BSI，多时相差异分析
- **火灾评估**：NBR + dNBR（火前火后差值）
- **干旱监测**：NDMI + 温度数据结合

## 常见问题

| 问题 | 原因 | 解决方案 |
|------|------|----------|
| 指数值异常 | 云层/阴影干扰 | 先做云掩膜再计算 |
| 结果与预期不符 | 波段选择错误 | 确认传感器波段编号 |
| 局部噪声大 | 影像边缘效应 | 裁剪有效范围后分析 |
| 多时相不可比 | 大气条件差异 | 使用地表反射率产品 |

## 可用工具

- `calculate_spectral_index` — 计算任意光谱指数（从15+预置指数中选择或自定义公式）
- `list_spectral_indices` — 列出所有可用光谱指数及其公式、波段、适用场景
- `recommend_indices` — 根据分析目标智能推荐指数组合
- `assess_cloud_cover` — 评估影像云覆盖率和数据质量
- `search_rs_experience` — 检索遥感分析经验池中的相似案例
- `describe_raster` — 栅格数据描述（波段/分辨率/统计信息）
- `calculate_ndvi` — 快捷 NDVI 计算
- `raster_band_math` — 自定义波段运算表达式
- `visualize_raster` — 栅格数据可视化
