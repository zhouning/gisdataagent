---
name: spatial-analysis
description: "空间数据探查、处理与分析技能。包含数据质量审计、坐标转换、缓冲区分析、聚类、遥感指标计算和空间统计。"
metadata:
  domain: gis
  version: "1.0"
  intent_triggers: "optimization, governance, spatial"
---

# 空间分析技能

## 核心能力

1. **数据质量审计**: `describe_geodataframe` 数据画像、`check_topology` 拓扑检查、`check_field_standards` 字段标准验证、`check_consistency` 一致性检查
2. **空间处理**: `reproject_spatial_data` 坐标重投影、`engineer_spatial_features` 特征工程、`create_buffer` 缓冲区、`clip_data` 裁剪、`overlay_analysis` 叠加分析、`tessellate` 镶嵌
3. **地理编码**: `batch_geocode` 批量正向编码、`reverse_geocode` 逆向编码、`calculate_driving_distance` 驾车距离
4. **遥感分析**: `describe_raster` 栅格描述、`calculate_ndvi` NDVI 计算、`download_lulc` 土地利用数据、`download_dem` DEM 高程数据
5. **空间统计**: `spatial_autocorrelation` 全局 Moran's I、`local_moran` 局部 Moran 聚类、`hotspot_analysis` Getis-Ord 热点分析

## 分析工作流

1. 先用 `describe_geodataframe` 对数据进行全面画像（字段、CRS、几何类型、统计摘要）
2. 根据画像结果判断是否需要预处理（`reproject_spatial_data` 统一坐标系、`engineer_spatial_features` 添加面积/周长等派生字段）
3. 执行核心空间分析任务（缓冲区、叠加、聚类等）
4. 使用空间统计方法（Moran's I、热点分析）验证分析结果的空间显著性

## 参考资源

- 加载 `references/coordinate_systems.md` 获取中国常用坐标系选择指南
