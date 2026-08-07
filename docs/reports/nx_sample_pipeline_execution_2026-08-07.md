# 本机样例入湖与治理执行结果（2026-08-07）

## 样例与环境

输入：`规划院提供数据样例及Demo系统功能演示建议.zip`，约 447 MB 压缩包，解压内容约 664 MB。样例来自重庆规划院，只用于验证技术链路，不能作为宁夏权威数据。

本次旧记录使用了本地 QGIS 4.0.2 命令行。当前基线已改为 GIS Data Agent 内置 `pyogrio/geopandas/rasterio/pyarrow`，不依赖 ArcPy、ArcPy MCP、外部 GDAL、容器或网络；最新记录见 [重庆全流程记录](nx_chongqing_full_flow_execution_2026-08-07.md)。

## 实际结果

| 阶段 | 结果 |
| --- | --- |
| 安全解压 | 通过，防 Zip Slip，限制解压总量 |
| 原始入湖 | 38 个资产复制到 immutable raw 区 |
| FileGDB 画像 | 4 个 GDB，包含 DLTB、POI、AOI、搜索指数 |
| TIFF 画像 | DEM 与 CLCD 两个栅格，读取尺寸、CRS、nodata |
| SHP 画像 | 31 个 SHP bundle，读取字段、要素数、几何和 CRS 名称 |
| 质量状态 | `review`，候选字段和区域/标准证据仍需复核 |
| 标准化计划 | 38 个目标，计划状态 `planned` |
| 实际标准化 | 4 个 DLTB/POI/AOI/指标类 GeoParquet，2 个 COG，2 个 STAC item |
| 本体绑定 | 最新演练使用 `rehearsal`，6 个引用绑定，生产资格为 false |
| Paper9 | Tool 1 真实输入为 DLTB+DEM；旧记录未执行 Tool 1 |

## 运行产物

本次临时 file lake：`/private/tmp/gda-nx-pipeline-run`

```text
runs/e1ae4fce-3b7c-4254-a7b2-4799ac8c26f9/       # local_scan，review
runs/5d7ad865-9a9c-4e72-9d88-76f1caad71fa/       # standardization_plan，planned
runs/cc9c6da9-f890-4e72-8088-f8f4c198afbf/       # standardization_execute，succeeded
standardized/5d7ad865-9a9c-4e72-9d88-76f1caad71fa/standardization_plan.json
materialized/5d7ad865-9a9c-4e72-9d88-76f1caad71fa/materialization.json
```

每次运行都包含 `run.json`、`events.jsonl`、`manifest.json`、`quality_report.json` 和 lineage 信息。标准化产物只引用 raw asset，不覆盖原始文件。

## 结论

技术链路已经可以在无容器 Windows 环境中工作：文件接收、断点续传、原始入湖、结构画像、质量门禁、GeoParquet/COG 派生和血缘记录均有可执行路径。但“治理完成”和“本体可问数”仍以宁夏 EA/标准权威合同、真实数据质量和 Paper9 DLTB+DEM/算法包版本门禁通过为前提。
