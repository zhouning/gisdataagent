---
name: satellite-imagery
description: "卫星影像数据获取与分析技能。预置Sentinel-2/Landsat/SAR/DEM数据源模板、LULC土地利用数据下载、影像预处理和多源数据集成。"
metadata:
  domain: remote_sensing
  version: "1.0"
  intent_triggers: "卫星 satellite Sentinel Landsat SAR DEM LULC 影像 imagery 遥感数据 下载 download 土地利用 land use land cover 高程 elevation 哨兵 陆地卫星 雷达 合成孔径"
---

# 卫星影像数据获取与分析技能

## 技能概述

本技能提供卫星遥感数据的全链路获取与分析能力：

1. **数据源管理**：5 个预置卫星数据源模板（Sentinel-2/Landsat/SAR/DEM/LULC）
2. **数据获取**：按范围/时间/云覆盖条件检索与下载
3. **数据预处理**：波段选择、重采样、裁剪、镶嵌
4. **数据集成**：多源遥感数据融合与标准化

## 预置卫星数据源

### Sentinel-2 (光学多光谱)

| 属性 | 值 |
|------|-----|
| 分辨率 | 10m (可见光/NIR)、20m (红边/SWIR) |
| 重访周期 | 5 天 |
| 波段数 | 13 |
| 数据类型 | 多光谱 |
| 适用场景 | 植被监测、水体提取、城市分析、农业 |

**关键波段**：
- B02 (Blue, 490nm) / B03 (Green, 560nm) / B04 (Red, 665nm)
- B05-B07 (Red Edge) / B08 (NIR, 842nm)
- B11 (SWIR1, 1610nm) / B12 (SWIR2, 2190nm)

### Landsat 8/9 (光学多光谱)

| 属性 | 值 |
|------|-----|
| 分辨率 | 30m (多光谱)、15m (全色) |
| 重访周期 | 16 天 (单星)、8 天 (双星) |
| 波段数 | 11 |
| 数据类型 | 多光谱 + 热红外 |
| 适用场景 | 长时序变化分析（1984至今） |

### SAR (合成孔径雷达)

| 属性 | 值 |
|------|-----|
| 分辨率 | 10m (Sentinel-1) |
| 重访周期 | 6 天 |
| 极化模式 | VV, VH |
| 数据类型 | 雷达后向散射 |
| 适用场景 | 全天候/全天时监测、水体/洪涝、形变 |

**SAR 优势**：不受云层影响，可穿透植被冠层。

### DEM (数字高程模型)

| 属性 | 值 |
|------|-----|
| 分辨率 | 30m (Copernicus GLO-30) |
| 覆盖范围 | 全球 |
| 精度 | <4m (绝对垂直精度) |
| 适用场景 | 地形分析、坡度坡向、流域分析 |

### LULC (土地利用/覆盖)

| 属性 | 值 |
|------|-----|
| 分辨率 | 10m (ESA WorldCover / ESRI LULC) |
| 覆盖范围 | 全球 |
| 可用年份 | 2017-2024 |
| 分类体系 | 9 类 (ESRI) / 11 类 (ESA) |
| 适用场景 | 城市扩张、生态评估、碳汇估算 |

## 数据获取工作流

### 按需求选择数据源

```
目标分析 → 选择数据源:
├── 植被/农业监测  → Sentinel-2 (10m, 5天重访)
├── 长时序变化     → Landsat (30m, 40年历史)
├── 全天候监测     → SAR Sentinel-1 (不受云影响)
├── 地形分析       → DEM Copernicus GLO-30
└── 土地利用分类   → LULC ESA/ESRI
```

### 标准获取流程

```
1. list_satellite_presets    → 查看可用卫星数据源及参数
2. search_rs_experience      → 查找相似场景的数据选择经验
3. download_lulc / download_dem → 下载数据
4. describe_raster           → 检查下载数据质量
5. assess_cloud_cover        → 评估光学影像质量
6. calculate_spectral_index  → 计算目标光谱指数
```

### STAC 数据检索

对于 Sentinel-2 和 Landsat 数据，通过 STAC 协议检索：

**检索参数**：
- `bbox`：空间范围 [west, south, east, north]
- `datetime`：时间范围 "2024-01-01/2024-12-31"
- `cloud_cover`：最大云覆盖率 (%)
- `collection`：数据集名称

## 多源数据集成

### 集成策略

| 策略 | 适用场景 | 说明 |
|------|----------|------|
| 空间连接 | 矢量+栅格 | 栅格统计提取到矢量区域 |
| 波段合成 | 多源栅格 | 不同传感器波段融合 |
| 时序堆叠 | 多时相 | 按时间排列形成时序立方体 |
| 分辨率匹配 | 不同分辨率 | 重采样到统一分辨率 |

### 注意事项

- **坐标系统一**：所有数据应转换到相同 CRS（推荐 EPSG:4326 或 EPSG:32650）
- **分辨率匹配**：粗分辨率向细分辨率重采样时，不会增加信息量
- **时间窗口**：多时相分析应考虑季节性差异

## 常见问题

| 问题 | 原因 | 解决方案 |
|------|------|----------|
| 下载超时 | 数据量过大 | 缩小空间范围或选择子区域 |
| 分辨率不匹配 | 不同数据源 | 统一重采样到目标分辨率 |
| 波段编号混淆 | 传感器不同 | 使用 list_spectral_indices 确认波段映射 |
| SAR 噪声 | 斑点噪声 | Lee 滤波或多视处理 |
| LULC 分类不准 | 分辨率限制 | 结合高分影像或实地调查校验 |

## 可用工具

- `list_satellite_presets` — 列出预置卫星数据源模板（分辨率、重访周期、波段）
- `download_lulc` — 下载指定范围/年份的 LULC 土地利用数据
- `download_dem` — 下载 Copernicus DEM 高程数据
- `describe_raster` — 栅格数据概况（波段/CRS/统计/NoData）
- `assess_cloud_cover` — 影像云覆盖率评估和质量门控
- `search_rs_experience` — 检索经验池中的数据选择建议
- `calculate_spectral_index` — 计算光谱指数
- `list_spectral_indices` — 列出所有可用光谱指数
- `classify_raster` — 栅格分类（K-Means/ISODATA）
- `raster_band_math` — 自定义波段运算
- `visualize_raster` — 栅格可视化输出
