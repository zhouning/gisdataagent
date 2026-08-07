# 宁夏时空数据底座：GIS Data Agent 实施交付说明

**日期**：2026-08-07
**范围**：Windows 物理隔离环境、FileGDB/SHP/TIFF/三维文件接入、数据治理、本体和 Paper9 门禁

## 先说结论

这次交付的对象不是“把文件导入本体库”，而是一条可审计的数据管理链路：

```text
受控目录/分片上传
    -> immutable Raw 原始区
    -> 文件画像和质量报告
    -> EA/数据标准合同匹配
    -> GeoParquet/GPKG/PostGIS/COG/STAC 标准化产物
    -> 本体 2.3 引用绑定
    -> 语义层和智能问数
```

原始业务记录进入文件湖/湖仓，必要的在线查询投影进入 PostGIS；本体库只保存类、属性、关系、代码、约束和经过门禁的数据引用，不保存千万级图斑几何和全部字段副本。

## 已经可以运行的部分

| 能力 | 当前实现 | 结果证据 |
|---|---|---|
| 大文件接收 | `OfflineIngestStore` 分片流式写入、乱序上传、单片 SHA-256、全文件 SHA-256 | `data_agent/offline_ingest.py` |
| 断点续传 | session 状态写入 `sessions/*.json`，已完成分片重启后跳过 | 同上；HTTP `GET /api/offline-ingest/sessions/{id}` |
| 原始入湖 | 原始文件写入 `raw/YYYY/MM/DD`，hash 命名，原子提交，不覆盖同名资产 | `manifest.json`、`run.json` 等运行产物 |
| FileGDB | 内置 pyogrio/OpenFileGDB；读取图层、字段、几何、CRS、范围，外部 GDAL 仅可选 | `scan_local_path()` |
| SHP | `.shp/.dbf/.shx/.prj` 等 sidecar 作为一个 bundle 计算 hash 并保存 | SHP 资产 manifest |
| TIFF/DEM | 读取尺寸、波段、类型、CRS、范围、nodata；可转 COG 和 STAC | `execute_standardization_plan()` |
| 质量与日志 | 每个 run 生成 `run.json`、`events.jsonl`、`quality_report.json`、lineage | 诊断包下载接口 |
| 数据模型基线 | 解析两份 Excel，形成 47 个运行时合同：30 个 SHP 图层/765 条字段，加上第一份 Excel 8 个字段页/116 条字段和 21 项清单证据 | `nx-standard-contract-catalog.v2.candidate.json`（历史文件名） |
| 发布门禁 | 字段匹配、CRS、几何和值域质量按数据集判定；通过即可 `accepted`，失败项单独复核 | `_map_layer()` 和 ontology binding gate |
| 标准化 | GeoParquet/GPKG/PostGIS、TIFF→COG/STAC、三维索引；工具缺失时 fail-closed | materialization manifest |
| 本体边界 | 只生成对治理产物的引用绑定，不复制原始业务记录 | `create_ontology_binding()` |
| Paper9 检查 | Tool 1 按真实接口检查 DLTB+DEM；PDT 为派生结果，其他图层按场景单独门禁 | `world_model_v21.py` |
| 管理页面 | 工作台“数据资源 → 数据接入 → 离线入湖”可查看运行、质量、合同、诊断和发布动作 | `OfflineIngestTab.tsx` |

## 在系统页面怎么操作

1. 打开“数据资源 → 数据接入 → 离线入湖”。
2. 内网采集目录可以直接输入 `D:\\NX_INCOMING\\批次01`，点击“扫描目录”。浏览器不能直接读取 Windows 路径，扫描请求由 GIS Data Agent 服务进程执行。
3. 小批量或跨隔离区传输可以选择文件，点击“分片上传”。每个分片独立校验，网络中断后重新提交同一 session 会跳过已完成分片。
4. 在“最近运行”中选择批次，先看每个资产的质量状态、字段映射和 hash，再生成标准化计划。
5. `review` 状态必须由管理员确认后使用“人工复核后生成”；`blocked` 永远不能绕过。
6. 标准化执行完成后才能申请“本体绑定”。绑定只登记治理产物 URI、数据版本和本体版本，不把原始记录灌进本体库。
7. “诊断包”包含事件 JSONL、manifest、质量报告和血缘，可在隔离网中交给运维或审计人员。

## Windows 物理隔离部署

复制并修改：`.env.windows-standalone.example`。

```powershell
$env:GDA_FILE_LAKE_ROOT = 'D:\\GDA_FILE_LAKE'
$env:GDA_LOCAL_INGEST_DIRS = 'D:\\NX_INCOMING;E:\\NX_REMOVABLE'
# 内置 pyogrio/geopandas/rasterio 已覆盖 FileGDB/SHP/TIFF；以下外部命令仅在现场主动配置时使用
# $env:GDA_OGRINFO_PATH = 'D:\\GDA_TOOLS\\gdal\\ogrinfo.exe'
# $env:GDA_OGR2OGR_PATH = 'D:\\GDA_TOOLS\\gdal\\ogr2ogr.exe'
# $env:GDA_GDAL_TRANSLATE_PATH = 'D:\\GDA_TOOLS\\gdal\\gdal_translate.exe'
$env:GDA_STANDARD_CONTRACTS = 'D:\\GDA_CONFIG\\natural_resource_standard_contracts.json'
chainlit run data_agent\\app.py --headless --host 0.0.0.0 --port 8000
python scripts\\windows_ingest_worker.py --inbox D:\\NX_INCOMING --lake D:\\GDA_FILE_LAKE
```

生产环境建议把 API 进程和 worker 分别注册为 Windows Service（NSSM/WinSW）或任务计划任务；`D:\\GDA_LOGS` 用于应用日志轮转，`D:\\GDA_FILE_LAKE\\runs` 用于按批次导出诊断包。Raw 区、合同 JSON 和 ontology 包必须纳入离线备份，并使用只读 ACL 保护。

## 两份工作簿的正确使用方式

- `提供数据内容详细梳理分析20260716.xlsx` 的主表提供 21 项范围、格式和业务用途；其中 8 个专题页同时提供 DLTB、ZRZ、三类适宜性评价、ZXCQ、FWJZ、SQCPG 的 116 条字段记录。
- `SHP矢量数据表及字段梳理_追加更新版.xlsx` 提供 30 个图层、765 条字段记录。两份工作簿的字段证据会并列保存，重合代码不互相覆盖；`czzz`、`CQPG` 等被工作簿明确标注不完整的少数图层单独复核。
- EA 仓库和自然资源数据标准用于补充字段类型、长度、代码域、SRID、主键/唯一性、业务定义和质量规则；真实文件到达后核验物理实现。`authority=ea_standard` 可用于行政发布留痕，但不是系统启动或全部问数的前置条件。

## 当前明确的未完成项

1. 30 个图层和清单 21 项已作为接入基线；仍需补齐的类型、长度和值域规则应继续从 EA/标准文档提取，无法自动对齐的少数项形成异常清单。
2. 质量规则还需要补几何有效性、重复主键、拓扑重叠/缝隙、行政区范围、面积闭合、时间有效性、代码值域、密级权限。
3. 当前“本体绑定”是引用 manifest，尚未替代已有 ontology publisher/compiler 的正式生产发布流程；接入真实宁夏数据后需要调用 2.3 runtime 的权威发布接口。
4. Paper9 Tool 1 只有在宁夏真实 DLTB+DEM、覆盖/几何/坡度质量和批准算法包版本全部通过后才能标记 `ready=true`。

## 本轮新增的交付物

- [数据模型运行基线](/Users/zhouning/gisdataagent/docs/architecture/nx-standard-contract-catalog.v2.candidate.json)：把 21 项清单、两份工作簿的 47 个合同、881 条字段证据、EA 对比证据、字段注册表和值域放在一个可校验版本中；文件名保留历史 `candidate` 后缀，但运行时不再把它作为全局阻断条件。
- [合同编译报告](/Users/zhouning/gisdataagent/docs/reports/nx-standard-contract-compile-2026-08.md)：逐字段列出类型、长度、精度和值域缺口，明确不允许把候选字段当作生产标准。
- [Windows 部署验收手册](/Users/zhouning/gisdataagent/docs/reports/nx_windows_deployment_acceptance_2026-08.md)：包含预检、无真实数据演练、真实文件到达流程、Paper9 门禁和现场验收判据。
- `scripts/preflight_windows_ingest.py`：生产模式检查宁夏字段基线、工具、目录权限和本体包；基线可用即可启动，数据质量在接入时逐项判定。
- `scripts/run_windows_ingest_drill.py`：验证 Raw 不可变、诊断文件、血缘、断点续传、标准化失败可见和本体 fail-closed。
- `scripts/windows_ingest_worker.py`：等待源目录签名稳定后再扫描，状态文件原子写入，合同变更会触发重新画像。

## 样例验证口径

`规划院提供数据样例及Demo系统功能演示建议.zip` 已用于本机模拟。它是重庆样例，只证明 FileGDB/TIFF/SHP 的技术链路可以执行，不证明宁夏数据覆盖，也不解除 Paper9 门禁。最近一次执行结果见：

- `docs/reports/nx_sample_pipeline_execution_2026-08-07.md`
- `docs/reports/nx_workbook_contract_integration_2026-08.md`

样例实际得到 38 个 raw 资产、4 个 GeoParquet、2 个 COG、2 个 STAC item。重庆样例仍按来源标记为演练数据；宁夏数据到达后，只要对应数据集通过基线匹配和质量门禁即可建立本体引用。Paper9 是否 `ready` 继续由其实际输入数据决定。
