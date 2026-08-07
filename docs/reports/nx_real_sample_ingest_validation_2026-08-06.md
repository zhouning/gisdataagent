# 规划院样例数据接入验证记录

## 样例范围

样例文件：`规划院提供数据样例及Demo系统功能演示建议.zip`，压缩包约 447 MB，解压后约 664 MB。它是重庆规划院样例，不是宁夏权威生产数据；这里只验证 FileGDB/TIFF 接入、画像、原始保留、质量和血缘链路，不能把样例区域或字段结论直接迁移到宁夏。

实际扫描命令使用 QGIS 4.0.2 的 GDAL 3.12 `ogrinfo` OpenFileGDB 驱动，以及 Python `rasterio`。本机使用的环境变量是：

```text
GDA_OGRINFO_PATH=/Applications/QGIS-final-4_0_2.app/Contents/MacOS/ogrinfo
GDA_PROJ_DATA=/Applications/QGIS-final-4_0_2.app/Contents/Resources/qgis/proj
```

Windows 部署时分别替换为 `ogrinfo.exe` 和 GDAL/PROJ 的 `proj.db` 所在目录。

## 扫描结果

| 资产 | 结果 |
| --- | --- |
| FileGDB 数量 | 4 个 |
| TIFF 数量 | 2 个 |
| 扫描候选资产总数 | 38 个（另含 Shapefile、压缩包等样例资产） |
| 原始路径唯一性 | 通过；同批次同名中文文件不会互相覆盖 |
| 运行状态 | `review` |
| 质量统计 | 34 `pass`、4 `review`、0 `blocked` |

标准化门禁也已验证：默认请求被拒绝（`quality review is required before promotion`）；显式人工复核后生成 38 个输出目标的 `planned` 计划。这只是执行合同，不代表在本机已经写入 PostGIS 或生成 COG。

### FileGDB

| GDB/图层 | 要素数 | 几何 | CRS | 字段数 | 映射结论 |
| --- | ---: | --- | --- | ---: | --- |
| `GDB.gdb / DLTB` | 101,657 | MultiPolygon | EPSG:4610 | 11 | `manual_review`，核心字段匹配 5/6，缺 `图斑编号/TBBH` |
| 高德 POI 2024 | 1,194,351 | Point | EPSG:4490 | 11 | `unmatched`，需补 POI 标准合同 |
| 百度 AOI 2024 | 26,292 | MultiPolygon | EPSG:4490 | 24 | `unmatched`，需补 AOI/设施语义映射 |
| 成渝环渝百度搜索指数 2023 | 325 | MultiLineString | EPSG:4490 | 7 | `unmatched`，应作为社会经济/流动性指标域，不应误归 DLTB |

DLTB 实际字段包括 `BSM、YSDM、DLBM、DLMC、QSDWDM、QSDWMC、ZLDWDM、ZLDWMC、TBMJ、SHAPE_Length、SHAPE_Area`。`BSM` 在样例中被 GDAL 识别为 Real，需要在宁夏标准合同中确认标识码类型和唯一性，不能直接照搬清单的中文字段名。

### TIFF

| 栅格 | 尺寸/波段 | 类型 | CRS | nodata | 范围 |
| --- | --- | --- | --- | --- | --- |
| 重庆 DEM 80 m | 1766 x 1454 / 1 | int16 | EPSG:4490 | 32767 | 105.2898–110.1954E, 28.1653–32.2042N |
| CLCD 2020 | 18579 x 15082 / 1 | uint8 | EPSG:4326 | 15 | 105.2130–110.2200E, 28.1408–32.2054N |

样例规划成果中还发现 `STBHHX.shp`（1 个面）和 `JQDLTB.shp`（662 个面），均为 CGCS 2000 三度带投影坐标；但样例中未找到明确的 `YJJBNT` 或 `PDT` 权威图层。

## 对宁夏接入的影响

1. QGIS/GDAL `ogrinfo -json -ro -al -so` 可以在没有 ArcGIS Pro 的主机上完成 FileGDB schema、要素数、几何类型、extent、字段类型和 CRS 画像；生产 Windows 应优先 ArcPy，GDAL 作为兜底，并固定 `PROJ_DATA`。
2. 样例 DLTB 的缺字段被严格标记为 `manual_review`，说明清单字段不能作为完整模型；EA/标准合同确认后才可生成标准化计划。
3. 真实宁夏数据入湖前必须做 CRS/区域门禁，不能把重庆样例直接用于宁夏 Paper9；DEM 只能证明“可以派生 PDT 的技术路径”，不证明宁夏 PDT 已具备。
4. 样例没有永久基本农田，仍然不能解除 Paper9 正式运行的 YJJBNT 硬门禁。

## 产物位置

本次本机验证的临时 file lake 为 `/private/tmp/gda-nx-lake-v2.TqcEHj`，运行 ID 为 `f69afc56-afa0-4861-8f2c-35a7dc24a0ea`。关键产物包括：

```text
runs/<run-id>/run.json
runs/<run-id>/events.jsonl
runs/<run-id>/manifest.json
runs/<run-id>/quality_report.json
raw/2026/08/06/<run-id>_<hash>_<safe-name>
```

这些临时产物用于验证，不应提交到仓库；内网部署时将 `GDA_FILE_LAKE_ROOT` 指向正式磁盘，并由备份策略接管 raw 和 runs 目录。
