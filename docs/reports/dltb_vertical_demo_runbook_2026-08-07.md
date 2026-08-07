# DLTB 单数据集纵向演示运行手册

## 目标

本手册把一个 `DLTB.gdb`（地类图斑）在无容器、无 ArcPy、物理隔离 Windows 主机上的链路固定为：

```text
受控目录/GDB
  -> 探查与 SHA-256
  -> Raw 原始区
  -> 深度质量
  -> 标准化 GeoParquet
  -> 本体引用绑定（不复制图斑记录）
  -> land_parcel_current 离线语义投影
  -> 离线自然语言问数
  -> Paper9 Tool 1（可选，需要 DEM）
```

本链路的入口命令是 `scripts/run_dltb_vertical_demo.py`。它使用随 GIS Data Agent 打包的 GeoPandas/pyogrio/GDAL 运行时，不依赖 ArcPy、MCP、PostGIS、容器或外网。

## 内网部署后的命令

把真实文件放入安装时配置的受控目录（例如 `D:\NX_INCOMING\批次01`），然后在 GIS Data Agent 的 Python 运行时执行：

```powershell
python scripts\run_dltb_vertical_demo.py `
  --source D:\NX_INCOMING\批次01\DLTB.gdb `
  --lake D:\GDA_DATA\file_lake `
  --output D:\GDA_DATA\reports\dltb-$(Get-Date -Format yyyyMMddHHmmss).json `
  --mode production
```

如果需要 Paper9 Tool 1，另外提供 DEM 和已批准的 Paper9 本地目录：

```powershell
python scripts\run_dltb_vertical_demo.py `
  --source D:\NX_INCOMING\批次01\DLTB.gdb `
  --dem D:\NX_INCOMING\批次01\DEM.tif `
  --lake D:\GDA_DATA\file_lake `
  --output D:\GDA_DATA\reports\dltb-paper9.json `
  --paper9-repo D:\GDA_RUNTIME\paper9 `
  --run-paper9-tool1 `
  --mode production
```

现场不需要修改脚本或安装 ArcGIS。`GDA_LOCAL_INGEST_DIRS` 必须只指向受控输入目录；这样既限制路径访问，也避免把无关目录扫描入湖。

生产命令的退出码含义：`0` 表示本批次完成了请求的生产链路，`2` 表示数据质量、标准化或本体门禁阻断。两种情况下都会写出 `--output` 指定的 JSON；生产阻断报告中的 `quality_gate.findings` 和 `production_blockers` 是现场处理依据，不要用删除日志或改名绕过门禁。

## 页面操作

“数据面板 → 离线入湖”页面按以下顺序操作：

1. 扫描受控目录，确认图层识别为 `DLTB`，查看字段映射、CRS、资产哈希和质量状态。
2. 质量状态为 `pass` 时生成标准化计划；演示数据若为 `review`，只能使用“人工复核后生成”。
3. 执行标准化，默认生成 GeoParquet（也可由部署配置切换为 GPKG/PostGIS 适配器）。
4. 样例或待核验数据使用“演示本体绑定”；正式宁夏数据使用“申请生产绑定”。
5. 生成 `DLTB 语义投影`，然后在同一面板中执行离线问数。

页面的“演示本体绑定”和命令行 `--mode rehearsal` 都会写明 `production_eligible=false`，不会把重庆样例或待复核数据发布成权威数据源。

## 宁夏合同编译

部署前在联网 staging 机或开发机编译两份宁夏工作簿。下面的路径是仓库内置的角色、别名、值域和标准字段目录；若 EA 仓库已经导出表级、逻辑实体级对比 CSV，则追加两个 `--ea-*` 参数，编译器会把证据按数据集并列保留。没有导出文件时可省略这两个参数，运行基线仍会覆盖工作簿字段和自然资源标准字段，真实文件到达后继续逐数据集核验。

```powershell
python scripts\compile_nx_standard_contract.py `
  --role-contracts data_agent\test_data\twm_bishan_demo\standards\one_map_role_contracts.zh.json `
  --field-aliases data_agent\test_data\twm_bishan_demo\standards\one_map_field_aliases.zh.json `
  --value-domains data_agent\test_data\twm_bishan_demo\standards\one_map_value_domains.zh.json `
  --field-catalog data_agent\test_data\twm_bishan_demo\tables\standard_field_catalog.csv `
  --standard-docx-catalog data_agent\standards\compiled_docx\02_统一调查监测.yaml `
  --shp-workbook D:\GDA_CONFIG\SHP矢量数据表及字段梳理_追加更新版.xlsx `
  --inventory-workbook D:\GDA_CONFIG\提供数据内容详细梳理分析20260716.xlsx `
  --standard-version NX-2026-08-baseline `
  --output D:\GDA_CONFIG\natural_resource_standard_baseline.json `
  --report D:\GDA_CONFIG\nx-standard-contract-compile.md
```

EA 导出文件存在时，在 `--field-catalog` 后追加：

```powershell
  --ea-table-comparison D:\GDA_CONFIG\ea-standard-table-comparison.csv `
  --ea-logical-comparison D:\GDA_CONFIG\ea-standard-logical-entity-comparison.csv
```

## 语义投影包含什么

语义源固定为 `land_parcel_current`。投影只保存治理产品的元数据和引用，不复制全部图斑记录：

| 语义字段 | 原始/标准字段 | 本体属性 | 关系/类别 |
| --- | --- | --- | --- |
| `feature_identifier` | `BSM` | `featureIdentifier` | `LandParcel` |
| `feature_code` | `YSDM` | `featureTypeCode` | `LandParcel` |
| `land_use_code` | `DLBM` | `currentLandUseCode` | `LandParcel` |
| `land_use_name` | `DLMC` | `currentLandUseName` | `LandParcel` |
| `parcel_area_sqm` | `TBMJ` | `parcelArea` | `LandParcel` |
| `located_admin_code/name` | `ZLDWDM/ZLDWMC` | `administrativeDivisionCode/Name` | `AdministrativeUnit` |

每次投影会生成：

- `semantic_projection.json`：语义源、字段、本体版本、质量状态、生产资格和治理产品 SHA-256；
- `dltb_metrics.json/csv`：图斑数、地类面积/占比、行政区面积汇总、面积一致性检查；
- `dltb_preview.geojson`：最多 500 个图斑的空间预览；
- `lineage.json`：Raw → GeoParquet → 语义源 → 本体引用的血缘边；
- `catalog.json`：无 PostgreSQL 时由语义解析器读取的离线语义源目录。

## 可演示问数

- “2024 年各地类图斑数量和面积是多少？”
- “耕地面积及其占比是多少？”
- “某行政区的建设用地面积是多少？”
- “列出面积属性与几何面积差异较大的图斑。”
- “定位图斑 BSM:1105665，并展示地类、面积和来源。”

当前离线问数是受控的确定性查询适配器，先验证语义字段再计算；它不是把问数功能冒充成本体类。后续接入数据库查询引擎时，可复用同一个 `land_parcel_current` 语义源和字段合同。

## Paper9 边界

DLTB 单独可以完成探查、治理、质量、语义问数和空间预览，但不能单独完成 Paper9。Tool 1 至少需要 `DLTB + DEM`；Tool 2/3/4 还需要采样、已批准的训练参数、ONNX ensemble、算法包版本和运行审计。

Paper9 Tool 1 的输出是派生分析产品（例如 `DLTB_with_slope.shp`），不是本体实例库，也不会改变 DLTB 原始数据。若 DEM 缺失，报告会明确 `ready_for_tool_1=false`，而不是用预计算结果冒充运行结果。

## 重庆样例实跑证据

使用规划院重庆样例的 `GDB.gdb/DLTB` 和 `Chongqing_aster_gdem_80m.tif` 实跑结果：

- 101,657 个图斑进入 GeoParquet；
- 24 个 `DLBM` 分组完成面积和占比汇总；
- 面积一致性检查识别出 1,266 个超过 5% 差异的记录；
- 样例深度质量为 `review`，原因包括 180 个无效几何和字段基线缺少 `图斑编号`；
- 本体绑定为 `accepted_for_rehearsal`，生产资格为 `false`；
- Paper9 Tool 1 成功生成 `DLTB_with_slope.shp`，但有 92,948 个图斑没有直接 DEM 覆盖，使用了中位坡度填充，需在正式验收前由业务方确认覆盖策略。

按 `--mode production` 重跑时命令返回退出码 `2`，并生成阻断报告；`production_blockers` 明确列出 DEM 样例有效像元比例 `0.388805`、DLTB 的 `manual_review` 映射和 `invalid_geometry:180`。这证明生产门禁会停在质量复核阶段，而不是把重庆数据发布成宁夏权威语义源。

这组结果只证明技术链路在样例上可执行，不代表宁夏权威数据已经验收。正式发布必须使用宁夏基线字段、CRS、几何、主键、值域、调查年度和质量规则逐项通过后的真实 GDB。
