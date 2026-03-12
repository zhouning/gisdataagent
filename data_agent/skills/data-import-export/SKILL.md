---
name: data-import-export
description: "数据入库与导出技能。支持SHP/GeoJSON/GPKG/KML/CSV等格式导入PostGIS，管理数据目录和血缘追踪。"
metadata:
  domain: database
  version: "2.0"
  intent_triggers: "import, 入库, 导入, export, 导出, PostGIS, SHP, GeoJSON, GPKG, 数据目录"
---

# 数据入库与导出技能

## 概述

本技能负责将多种格式的空间数据导入 PostGIS 数据库，并通过数据目录系统管理资产元数据、
标签和血缘关系。支持从本地文件、用户上传和 OBS 云存储三种来源加载数据，覆盖从数据接收
到入库注册的完整链路。

## 支持的数据格式

### 矢量格式
| 格式 | 扩展名 | 特点 | 注意事项 |
|------|--------|------|---------|
| Shapefile | .shp/.dbf/.shx/.prj | 最广泛的 GIS 交换格式 | 字段名限 10 字符；需 4 个关联文件；中文属性需 .cpg 编码文件 |
| GeoJSON | .geojson/.json | 纯文本、Web 友好 | 默认 EPSG:4326；大文件性能差（无空间索引） |
| GeoPackage | .gpkg | OGC 标准、SQLite 容器 | 支持多图层、栅格和属性表；推荐替代 Shapefile |
| KML/KMZ | .kml/.kmz | Google Earth 格式 | KMZ 为 ZIP 压缩的 KML；坐标固定为 WGS84 |

### 表格格式（含坐标列）
| 格式 | 扩展名 | 坐标列自动检测规则 |
|------|--------|-------------------|
| CSV | .csv | 自动识别：lng/lat、lon/lat、longitude/latitude、x/y（不区分大小写） |
| Excel | .xlsx/.xls | 同 CSV 规则；默认读取第一个工作表 |

### 坐标列检测细节
- 经度列名匹配：`lng`, `lon`, `longitude`, `x`, `经度`
- 纬度列名匹配：`lat`, `latitude`, `y`, `纬度`
- 检测失败时提示用户手动指定列名
- 坐标值范围校验：经度 -180~180，纬度 -90~90

## 导入流程

### 标准工作流
1. 用户上传文件（ZIP 自动解压提取 .shp/.kml/.geojson/.gpkg）
2. 自动检测文件格式和坐标参考系（CRS）
3. 调用 `import_to_postgis` 执行入库
4. 验证导入结果（记录数、几何类型、空间范围）
5. 调用 `register_data_asset` 注册到数据目录
6. 调用 `tag_data_asset` 添加分类标签便于检索

### import_to_postgis 参数详解

| 参数 | 类型 | 说明 |
|------|------|------|
| file_path | str | 文件路径（用户沙箱内的相对或绝对路径） |
| table_name | str | 目标表名（小写字母、数字、下划线） |
| srid | int | 坐标系 EPSG 代码：0=保留原始、4326=WGS84、4490=CGCS2000 |
| if_exists | str | 表已存在时的策略：fail=报错、replace=替换、append=追加 |
| encoding | str | 字符编码（默认 UTF-8，Shapefile 中文常需 GBK） |

### CRS 处理策略
- 有 .prj 文件：自动读取并转换到目标 SRID
- GeoJSON：规范要求 WGS84，直接设为 4326
- 无 CRS 信息：警告用户，默认假设 4326，建议确认
- CGCS2000（4490）与 WGS84（4326）：实际偏差 < 1m，多数场景可互用

## 数据目录管理

### 资产注册
- `register_data_asset`：将入库表注册为数据资产
  - 必填：名称、描述、数据类型（vector/raster/table）
  - 可选：来源、更新频率、质量等级、空间范围
  - 注册后自动生成唯一资产 ID

### 资产检索
- `search_data_assets`：关键词搜索数据资产
  - 支持中文 n-gram 分词（如"耕地"可匹配"基本农田耕地保护区"）
  - 按相关度排序，返回资产元数据和标签
- `get_data_catalog`：浏览完整数据目录（分页）

### 标签体系
- `tag_data_asset`：为资产添加标签
  - 推荐标签维度：数据主题（耕地/林地/水域）、行政区划、时间范围、质量等级
  - 标签支持层级：`土地利用/耕地/水田`
- 标签用于快速过滤和推荐相关数据集

### 血缘追踪
- `get_data_lineage`：查询数据资产的来源和派生关系
  - 记录：源数据 → 处理操作 → 输出数据的完整链路
  - 用途：数据质量溯源、影响分析、合规审计

## 云存储资产

### OBS 云端数据
- 数据目录中注册了 OBS（对象存储）上的远程资产
- `download_cloud_asset`：按资产 ID 下载到用户本地沙箱
- 下载后可直接用 `import_to_postgis` 入库
- 典型资产：省级土地利用现状、行政区划、DEM 栅格

### 数据共享
- `share_data_asset`：将资产共享给团队成员
- 共享时自动记录审计日志
- 被共享者可在数据目录中看到该资产

## 常见问题与解决

- Shapefile 中文乱码：指定 `encoding='GBK'` 或确认 .cpg 文件存在且内容为 `GBK`
- CSV 坐标列未识别：列名不在自动检测列表中，手动指定经纬度列名
- 表名冲突：`if_exists='fail'` 时报错，改用 `replace`（覆盖）或 `append`（追加）
- 大文件导入慢：> 100MB 的 Shapefile 建议分批导入或先转为 GPKG 格式
- 几何无效：导入后执行 `UPDATE table SET geom = ST_MakeValid(geom)` 修复
- ZIP 解压失败：确认 ZIP 内文件结构扁平（非嵌套文件夹），且包含完整的关联文件

## 相关工具

- `import_to_postgis`：执行数据入库（核心工具）
- `register_data_asset`：注册数据资产到目录
- `search_data_assets`：搜索数据资产（中文 n-gram）
- `tag_data_asset`：为资产添加标签
- `get_data_lineage`：查询数据血缘关系
- `download_cloud_asset`：下载 OBS 云端资产
- `share_data_asset`：共享数据资产给团队
