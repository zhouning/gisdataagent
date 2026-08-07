# 宁夏时空数据底座清单合同化与入湖接入说明（2026-08）

## 1. 本次输入与边界

本次接入分析使用两份工作簿：

- `提供数据内容详细梳理分析20260716.xlsx`：主表识别 21 个数据项，说明格式、业务用途和已知交付情况；其中 8 个专题页还给出了 116 条字段记录，作为对应数据集的字段基线。
- `SHP矢量数据表及字段梳理_追加更新版.xlsx`：由 31 张 ArcGIS 属性截图整理出的 30 个不重复 SHP 图层/数据表，共 765 条可辨字段记录。

第二份工作簿的字段类别统计如下：

| 字段类别 | 记录数 | 建模含义 |
| --- | ---: | --- |
| 标识编码字段 | 209 | 候选主键、实体编码、要素代码、行政区代码等，必须核验唯一性和编码规则 |
| 业务属性字段 | 293 | 对象的业务描述、分类、评价等级、统计值等 |
| 系统/几何字段 | 126 | OBJECTID、SHAPE、长度、面积等，不直接等同业务语义 |
| 时态字段 | 79 | 产生、消亡、更新时间和调查时间，形成有效期/版本语义 |
| 来源与安全字段 | 58 | 数据源、涉密等级，参与权限、目录和问数可信度判定 |

工作簿明确提示 `czzz` 的截图没有显示完整字段，`CQPG` 仍有后续字段；这些少数图层在接入时需要额外复核。其余字段清单作为宁夏运行基线使用，真实 SHP/DBF/GDB 到达后核验物理类型、长度、CRS、几何和值域，不再把整个工作簿降级为不可用的 `screenshot_candidate`。

第一份清单中的行政区划界线和应急避难场所已从自然资源标准正文补齐为 `XZQJX`、`YJBNA`，共 12 条完整字段定义。`重大危险源数据`、`社会经济数据`、`医疗养老数据` 仍是没有唯一表代码的集合名称；它们保留在覆盖清单中，部署后根据真实文件画像选择具体标准表，不能在开发环境凭名称伪造字段。

## 2. 合同目录产物

开发机可以把两份工作簿编译成一个可带入物理隔离内网的 JSON 目录：

```powershell
uv run python scripts\build_standard_contract_catalog.py `
  --shp-workbook "D:\GDA_CONFIG\SHP矢量数据表及字段梳理_追加更新版.xlsx" `
  --inventory-workbook "D:\GDA_CONFIG\提供数据内容详细梳理分析20260716.xlsx" `
  --output "D:\GDA_CONFIG\nx_standard_contract_catalog.json"
```

目录保存每个代码的中文名、几何类型、字段顺序、字段类别、两个工作簿的字段来源、完整性说明、合同权威级别和发布门禁，也保存第一份清单的 21 个数据项作为输入证据。JSON 目录不是自然资源本体本身；本体仍由 EA/数据标准确认的类、关系、约束、代码表和字段语义构成。

生产配置建议：

```text
GDA_STANDARD_CONTRACT_XLSX=D:\GDA_CONFIG\SHP矢量数据表及字段梳理_追加更新版.xlsx
GDA_STANDARD_CONTRACTS=D:\GDA_CONFIG\natural_resource_standard_contracts.json
GDA_DATA_INVENTORY_XLSX=D:\GDA_CONFIG\提供数据内容详细梳理分析20260716.xlsx
```

`GDA_STANDARD_CONTRACT_XLSX` 或编译后的 JSON 都是运行基线。EA/标准和真实 DBF 核验结果以数据集版本保存；需要行政发布留痕时再生成 `authority=ea_standard` 的审核版本，不作为整个系统启动前置条件。

## 3. 文件接入与结构画像

Windows 物理隔离环境不需要容器。共享目录、移动硬盘或受控上传客户端均进入同一个 `OfflineIngestStore`：

1. 大文件通过 upload session 分片流式写盘；每片和全文件均做 SHA-256 校验，分片可以乱序重传，进程/断电后查询 session 状态继续上传。
2. 完成后原子提交到不可变 `raw/YYYY/MM/DD`，生成 manifest、运行日志、事件 JSONL、质量报告和血缘边。
3. FileGDB 优先使用 ArcPy，随后尝试 Python OGR，最后使用 `ogrinfo -json -ro -al -so`；Windows 主机应固定 `GDA_OGRINFO_PATH` 和 `GDA_PROJ_DATA`。
4. SHP 与 `.dbf/.shx/.prj/.cpg/.sbn/.sbx` 等 sidecar 作为一个 bundle 计算 hash、复制和追踪；现在 SHP 也会读取字段、要素数、几何类型、extent 和坐标系名称。
5. TIFF/DEM 读取栅格尺寸、波段、数据类型、CRS、范围、分辨率和 nodata；后续执行器再把 TIFF 转 COG 并登记 STAC。

常驻采集可由 `scripts/windows_ingest_worker.py` 通过 Windows Task Scheduler、NSSM 或 WinSW 运行。collector 以源路径+hash 幂等，重启不会重复入湖或覆盖同名资产。

## 4. 映射与质量门禁

图层画像中新增 `contract` 对象，包含 `authority`、来源工作簿、来源照片、字段类别和完整性说明；`mapping` 对象包含 required/matched/missing 字段、字段级映射、置信度、`auto_publish` 和标准版本。

- 30 个 SHP 工作簿代码可按代码或中文名进行基线匹配；字段完整匹配后进入该数据集的质量门禁。
- 工作簿字段基线的字段完整匹配即可返回 `accepted`，但仍必须在真实数据到达时核验物理类型、长度、CRS、几何和值域；核验失败的数据集单独进入 `review`/`blocked`。
- 通过 EA/标准评审的 JSON 合同可另行标记为 `ea_standard/approved` 用于行政发布；这不是系统启动或其他合格数据集进入问数的全局前置条件。缺必需字段继续 `manual_review`，未知图层为 `unmatched`。
- FileGDB 与 SHP 都检查可读性、schema、几何/CRS；缺少几何或 CRS 名称会进入复核，无法画像则阻断。

`POST /api/offline-ingest/runs/{run_id}/standardize` 只在质量门禁后生成 FileGDB→PostGIS/GeoParquet、TIFF→COG/STAC 和三维索引计划，不伪造开发机上的真实转换。`review` 只有显式人工复核参数才能生成计划，`blocked` 永远不能绕过。

管理面板可通过 `GET /api/offline-ingest/contracts` 查看当前合同目录，包含字段顺序、字段类别、来源照片和完整性提示。

## 5. 与自然资源本体的关系

所有原始记录不进入本体库。建议的边界是：

- 文件湖：原始 GDB、SHP bundle、TIFF、三维资产和不可变版本。
- 治理数据层：通过标准合同校正字段、类型、CRS、编码和质量后，矢量进入 PostGIS/GeoParquet，栅格进入 COG/STAC。
- 本体库：保存自然资源类层级、对象关系、字段语义、代码表、约束、版本和通过质量门禁的实例索引/引用；不保存数千万条原始几何记录的副本。
- 语义/问数层：只消费已绑定且具备质量证据的治理数据；缺字段或不合格数据可被目录发现，但不能作为答案。是否具有行政 `ea_standard` 标记，不再替代数据集质量证据。

第二份工作簿提示需要在本体字段合同中统一公共属性层（实体标识码、实体编码、一张图要素代码、行政区划代码、产生/消亡时间、数据源、涉密等级和几何度量），再按地类图斑、建筑/宗地、公共服务设施、评价结果、规划管制和监测指标分域。`CQPG` 应建成“空间单元—指标定义—观测值—统计周期”结构，不应把每个指标或智能问数功能直接建成自然资源实体类。

## 6. 本机样例实际执行结果

新增命令 `scripts/run_nx_sample_ingest.py` 可以直接对规划院样例 ZIP 做安全解压和全量扫描：

```bash
GDA_OGRINFO_PATH=/path/to/ogrinfo \\
GDA_PROJ_DATA=/path/to/proj \\
GDA_STANDARD_CONTRACT_XLSX=/path/to/SHP矢量数据表及字段梳理_追加更新版.xlsx \\
uv run python scripts/run_nx_sample_ingest.py \\
  --zip "/path/to/规划院提供数据样例及Demo系统功能演示建议.zip" \\
  --lake /private/tmp/gda-nx-pipeline-run \\
  --output /private/tmp/gda-nx-pipeline-run/report.json \\
  --allow-review-plan
```

本机实际结果：38 个资产进入 raw 区，运行状态 `review`；生成 38 个标准化目标计划。随后使用 QGIS GDAL 实际执行了标准化计划，生成 4 个 DLTB/POI/AOI/指标类 GeoParquet 和 2 个 COG 栅格，并写入 2 个 STAC item；执行状态 `succeeded`。这些输出是重庆样例的技术验证，不是宁夏生产数据，也没有绑定到权威本体实例。

执行接口为 `POST /api/offline-ingest/standardization/{plan_id}/execute`，可传 `{"vector_format":"Parquet"}`、`{"vector_format":"GPKG"}` 或 `{"vector_format":"PostgreSQL"}`。PostgreSQL 模式还需要受保护的 `GDA_POSTGIS_DSN`；未安装 `ogr2ogr`/`gdal_translate` 或缺少 DSN 时会产生明确的 `blocked` 结果和错误日志。

执行完成后通过 `POST /api/offline-ingest/standardization/{plan_id}/ontology-bind` 申请本体绑定。该接口接受 `mapping.status=accepted`、来自宁夏基线且质量门禁通过的治理产品，只保存对 GeoParquet/COG 的引用，不复制原始记录；重庆样例因来源和字段质量状态仍是演练，不代表宁夏生产资格。

## 7. Paper9 可运行性判断

Paper9 正式运行仍需权威且通过质量门禁的 DLTB、PDT、法定生态保护红线 STBHHX 和 YJJBNT。两份清单提供了 DLTB、评价类、规划管制类以及 STBHHX/JQDLTB 的候选线索，但当前没有明确的宁夏 YJJBNT/PDT 权威数据，也不能把 `STBHZYYXPJJG` 生态保护重要性评价结果等同法定红线。

DEM 可以在内网由固定参数派生 PDT，但必须保存参数、版本和血缘，并重新执行质量门禁。重庆规划院样例只能验证 FileGDB/TIFF/SHP 技术链路，不能证明宁夏区域覆盖、坐标和 Paper9 数据完备性。部署验收应以宁夏真实数据的字段核验、行政区覆盖、CRS、唯一性、拓扑、面积闭合和四项 Paper9 输入齐备为准。

## 8. 已验证事项

- 合同目录：49 个运行时合同、893 条直接字段证据（765 + 116 + 标准补齐 12，重合代码并列保留）、第一份清单 21 个数据项。
- 单元测试：`data_agent/test_offline_ingest.py` 与 `data_agent/test_offline_ingest_routes.py` 共 10 项通过。
- 真实样例：`STBHHX.shp` 已读取为 1 个 Polygon 要素，坐标系名称 `CGCS_2000_3_Degree_GK_Zone_35`，SHP sidecar 原样入 raw；因没有对应权威合同，发布门禁保持人工复核。
- 代码质量：新增模块、脚本和 ingest 修改通过 Ruff 与 Python 编译检查。
