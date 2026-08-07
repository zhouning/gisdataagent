# 规划实施智能监测评估模型：重庆样例验证

**验证日期**：2026-08-07
**验证对象**：`gda.nr.planning-monitoring.current-state@1.0.0`
**样例来源**：`规划院提供数据样例及Demo系统功能演示建议.zip`
**验证口径**：重庆样例只作为技术验证数据，不是宁夏权威数据，也不产生宁夏规划或审批结论。

## 结论

已经开发并实际运行了“规划实施智能监测评估”的现状空间单元子模型。它完成了：

- 从治理后的 GeoParquet/COG 目标自动识别建筑、POI、道路、土地覆盖和 DEM 数据角色；
- 以建筑范围内的 5 km 规则网格建立现状空间单元；
- 计算建筑数量、建筑占地面积、建筑覆盖率、平均层数、估算建筑面积、估算容积率、设施点数量/密度、道路长度/路网密度、土地覆盖不透水面/水体占比、平均海拔和平均坡度；
- 对空间单元进行样例内部相对强度排名和四类相对诊断；
- 输出 GeoParquet、GeoJSON、CSV、JSON 报告、中文 Markdown 报告、质量报告和血缘；
- 对每个输入目标重新计算 SHA-256，并与入湖物化声明进行核验。

本次真实运行结果为：**122 个有建筑网格，5 个输入角色均可用，5 个输入哈希均通过；建筑源有 417 条空几何记录，因此模型状态为 `succeeded_with_review`，生产发布为 `false`。** 这说明链路和模型可执行，但质量门禁没有被绕过。

## 实际输入

| 角色 | 样例数据 | 规模 | 处理方式 |
|---|---|---:|---|
| 建筑 | 中心城区建筑数据带层高 | 107,452 栋 | 面内点归属网格；面积由投影几何计算；`Floor` 参与楼面面积估算 |
| 设施 | 高德地图 POI 数据 2024 年 | 1,194,351 点 | 转换到分析投影后按点落网格 |
| 道路 | OSM_roads | 50,366 条 | 与网格相交切分后计实际单元内长度 |
| 土地覆盖 | `CLCD_v01_2020_chongqing` | 单期栅格 | 按网格做类别 8（不透水面）和类别 5（水体）分区统计 |
| 地形 | `Chongqing_aster_gdem_80m` | 单期 DEM | 重投影到米制坐标；计算平均海拔和有限差分坡度 |

## 机器可读合同

指标、公式、分子/分母、单位、周期、空间粒度、缺失规则和诊断规则位于：

`data_agent/model_contracts/planning_monitoring_current_state.v1.json`

合同明确了一个重要边界：规则网格只是没有权威规划评估单元时的演练适配器，不能被称作行政区、规划分区或法定审批单元。

## 可验证的需求范围

本次已验证：

- 单期现状指标计算和空间化展示；
- 多空间单元比较、排序和相对问题识别；
- 从治理数据到模型结果的输入引用、哈希和血缘；
- 缺失角色、空几何、栅格覆盖不足时的 `review` 处置；
- 可落盘的指标结果和 Markdown 报告生成。

本次没有、也不能声称验证：

- 规划目标达成率、变化趋势或年度监测，因为重庆样例没有完整多年度序列、基期值、目标值和目标年份；
- 正式规划实施体检评估，因为尚未提供批准的指标字典、阈值、空间矛盾规则和建议政策库；
- 宁夏自然资源厅的合规结论、法律效力或生产发布；
- 用地智能选址中的永久基本农田、法定生态保护红线、城镇开发边界等约束审查。

## 运行方式

先执行已有的重庆入湖/标准化流程，获得 `materialization.json`，再执行：

```bash
uv run python scripts/run_planning_monitoring_evaluation.py \
  --materialization <lake>/materialized/<run-id>/materialization.json \
  --output <lake>/model/planning-monitoring
```

现场 Windows 离线运行不需要 ArcPy、ArcGIS Pro、ArcPy MCP、数据库、容器或联网服务。运行时使用随 GIS Data Agent 提供的 `geopandas/pyogrio/rasterio/pyarrow/shapely` 能力。

## 交付物

模型运行目录包含：

- `monitoring_evaluation_report.json`：模型状态、输入目标、哈希、分位数和诊断计数；
- `monitoring_evaluation_report.md`：客户可读报告；
- `spatial_units.parquet`、`spatial_units.geojson`、`indicators.csv`：空间单元结果；
- `quality_report.json`：空几何、覆盖率、角色可用性和质量状态；
- `lineage.json`：数据目标 -> 模型运行 -> 结果文件的有向血缘。

部署到宁夏后，应将规则网格适配器替换为经批准的行政区/规划分区合同，并补齐年度序列、目标值、指标字典、规则库和案例库，之后才可以把模型从演练状态提升到生产评估状态。
