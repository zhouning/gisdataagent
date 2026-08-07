# 宁夏时空数据底座：Windows 内网数据接入与治理方案

状态：实施基线（2026-08-06）

## 1. 结论先行

两份宁夏工作簿共同构成数据接入基线：`提供数据内容详细梳理分析20260716.xlsx` 主表提供 21 项
数据范围、格式和业务用途，8 个专题页另提供 116 条字段明细；`SHP矢量数据表及字段梳理_追加更新版.xlsx`
提供 30 个图层/数据表和 765 条字段明细。EA 仓库和自然资源数据标准用于补充字段定义、代码表、几何/CRS
和质量规则；真实文件到达后按数据集核验物理实现，通过后才发布标准化产物。

在当前没有真实文件的开发环境中，可以先完成接入契约和模拟测试；部署到宁夏物理隔离内网后，使用 Windows 采集目录或共享盘完成真实 ingest。新增的 `data_agent.offline_ingest.OfflineIngestStore` 不依赖 Docker、云对象存储或消息队列，提供分片上传、断点续传、原始区原子提交、FileGDB/TIFF/OSGB/OBJ 画像、质检门禁、血缘和诊断包。

Paper9 Tool 1 的真实输入是 DLTB 面图层和 DEM；PDT 是由 DEM 派生的坡度结果，不是必须另有一张名为 PDT 的输入图层。STBHHX/YJJBNT 属于其他自然资源业务数据，不是 Tool 1 的输入。Paper9 正式发布仍需现场批准的离线算法包、字段/CRS/覆盖质量证据和版本兼容性检查。

## 2. 清单资产分层

| 资产族 | 清单代表 | 原始形态 | 接入与服务策略 |
| --- | --- | --- | --- |
| 调查/确权矢量 | DLTB、ZRZ、ZJDZRZ、行政区 | FileGDB | 原始 `.gdb` bundle 原样保留；feature class 建逻辑子资产；治理后写入 PostGIS/GeoParquet |
| 规划与评价矢量 | CZJSSYXPJJG、NYSCSYXPJJG、STBHZY、ZXCQ 黄绿蓝紫线/规划用地 | FileGDB | 依据标准章节、物理代码、几何类型和 SRID 映射；评价结果与法定红线分开建模 |
| 城市存量与指标 | FWJZ2024、SQCPG2025 | FileGDB/表 | 建筑实体与统计指标分离；指标必须维护统计周期、空间单元和计算口径 |
| 公共服务/风险 POI | 应急避难、医疗、学校、重大危险源 | 点图层/表 | 统一地址、行政区划、坐标系、设施分类代码和有效期 |
| 栅格 | 高程/DEM、遥感影像 | TIFF | 原始 TIFF 保留；生成 COG/STAC 派生资产；需要时切片为 Zarr/瓦片，不把像元全部写进本体 |
| 三维资产 | 倾斜摄影 OSGB、原片、空三、OBJ | 目录/大文件 | 目录 bundle 整体入湖；维护空间范围、坐标系、采集批次、瓦片/模型索引和预览地址 |
| 社会经济 | 社会经济、医疗养老等 | 表/文件 | 维护指标定义、时间粒度、行政区粒度、来源和脱敏等级；不与空间实体强行合并 |

覆盖范围同时包括全自治区和银川/金凤区局部成果，必须保留“原始全量 + 派生研究范围”，不能用局部切片覆盖原始数据。

## 3. Windows 物理隔离部署

### 3.1 推荐组件边界

```text
共享目录/移动硬盘/采集客户端
             |
             v
      offline_ingest（staging + manifest + run logs）
             |
             +--> raw file lake（只读原始文件/目录）
             +--> 内置 pyogrio/geopandas schema scan
             +--> 内置 rasterio COG/STAC raster scan
             +--> quality gate + standard mapping
             |
             v
  PostGIS（标准化可查询矢量，可选但推荐）
  文件湖派生区（GeoParquet/COG/三维索引）
  元数据/血缘目录（PostgreSQL 或离线 JSON 投影）
             |
             v
  语义层/自然资源本体应用（只绑定通过门禁的标准化数据）
             |
             v
  智能问数、空间核查、Paper9 准备/运行
```

物理隔离环境只需安装 GIS Data Agent 随附的版本锁定 Windows Python GIS wheelhouse（pyogrio/geopandas/rasterio/pyarrow 及其 GDAL/PROJ 运行库）；不依赖 ArcPy、ArcGIS Pro、ArcPy MCP、容器或联网安装。GIS Data Agent 作为 Windows Service/计划任务运行。PostgreSQL/PostGIS 使用 Windows 原生安装包，不依赖容器。外部 GDAL 仅是可选加速器。

### 3.2 文件湖目录

```text
<GDA_FILE_LAKE_ROOT>/
  sessions/                 # 分片会话状态，可断点恢复
  staging/<session-id>/     # 临时分片与组装文件
  raw/YYYY/MM/DD/           # 原始不可变资产（文件或目录 bundle）
  manifests/                # raw asset manifest、hash、来源
  standardized/             # 标准化 GeoParquet/PostGIS 导出引用
  derivatives/              # COG、坡度、坡向、瓦片、三维索引
  runs/<run-id>/            # run.json、events.jsonl、quality_report.json、lineage.json
  diagnostics/              # 可带出内网的诊断 zip
```

原始文件永远不覆盖。重复文件以 SHA-256 去重/复用；同名不同 hash 作为不同版本并记录来源、采集时间和生效时间。

## 4. 接入方式

### 4.1 共享目录/采集客户端（首选）

`scripts/windows_ingest_worker.py` 可通过 Windows Task Scheduler、NSSM 或 WinSW 启动：

```powershell
python scripts\windows_ingest_worker.py --inbox D:\NX_INCOMING --lake D:\GDA_FILE_LAKE --interval 30
```

采集端只将完成写入的文件放入目录；建议先写入 `.gda-incoming`，完成后原子改名。worker 以文件/目录 hash 作为幂等键，断电重启后重新核对 hash，已处理资产不会重复入湖。FileGDB 不拆成 feature class 文件上传；`.gdb` 作为 bundle 入湖，内部 feature class 作为逻辑子资产扫描。

### 4.2 Web 分片上传（补充）

路由已接入前端 API：

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| POST | `/api/offline-ingest/sessions` | 创建 upload session（文件名、大小、64/128/256 MiB 分片、全文件 hash） |
| PUT | `/api/offline-ingest/sessions/{id}/chunks/{index}` | 流式写入单块，`X-Chunk-SHA256` 校验，支持乱序重传 |
| GET | `/api/offline-ingest/sessions/{id}` | 查询已完成分片和恢复状态 |
| POST | `/api/offline-ingest/sessions/{id}/finalize` | 顺序组装、全文件 hash 校验、原子提交 raw 区 |
| POST | `/api/offline-ingest/local-scan` | 对允许目录做本地扫描 |
| GET | `/api/offline-ingest/runs/{id}` | 查看运行摘要、质量、血缘 |
| POST | `/api/offline-ingest/runs/{id}/standardize` | 质量门禁后生成标准化/派生目标计划 |
| GET | `/api/offline-ingest/runs/{id}/diagnostics` | 导出诊断 zip |

现有普通上传接口仍适合小文件；TIFF、OSGB、OBJ、GDB 压缩包必须使用上述分片接口或采集客户端，避免整文件读入内存。

## 5. 画像、EA/标准映射与标准化

每个资产至少形成以下对象：`source_asset`、`source_bundle`、`layer/resource`、`source_field`、`canonical_field`、`mapping_decision`、`quality_report`、`ontology_binding`。映射证据按以下顺序记录：

1. 标准章节和物理代码（例如 DLTB、STBHHX、YJJBNT）；Paper9 的 PDT 由 DEM 派生时另存算法参数和血缘；
2. EA Package 路径和逻辑实体；
3. 字段物理名、中文名、类型、长度、可空性、代码表；
4. 几何类型、SRID、主键/唯一约束、空间索引；
5. 名称别名只能作为候选证据，低置信度必须人工复核。

`GDA_STANDARD_CONTRACTS` 可指向项目 JSON 合同扩展默认字段别名；两份宁夏工作簿已提供 DLTB 等数据集的字段基线，EA/标准文档继续补充类型、长度、值域和业务约束。真实文件缺字段不得静默填空后发布，应标记 `manual_review` 或 `blocked`。

治理结果写入标准化区：矢量推荐 PostGIS（几何、空间索引和 SQL 问数），批处理交换推荐 GeoParquet；栅格推荐 COG/STAC；三维资产保留原始目录并另建索引。任何派生数据都要写入 `standardized/derivatives` manifest 并追加血缘边。

`POST /api/offline-ingest/runs/{id}/standardize` 生成并执行标准化计划。内置运行时直接生成 GeoParquet/COG/STAC；PostGIS 和外部 GDAL 是可选目标适配器。`blocked` 永远拒绝，`review` 只有显式 `allow_review` 才能生成演练计划。

## 6. 质量门禁

当前离线扫描已实现可扩展的阻断框架，真实适配器接入后应至少启用：

- FileGDB：目录完整性、可读性、feature class/table 数量、字段类型/长度、主键空值和重复、几何类型一致性、无效/空几何、SRID、空间索引、代码表和行政区代码；
- DLTB：地类编码字典、图斑面积与几何面积容差、权属/坐落代码、年度版本；
- ZRZ/FWJZ：建筑编码唯一性、层数/高度/面积逻辑、规划用途与实际用途、行政区代码；
- 规划线/评价结果：分类代码、拓扑重叠、法定红线与评价结果的语义区分；
- TIFF/DEM：可读性、CRS、范围、分辨率、波段/dtype、nodata 占比、高程异常和派生参数；
- OSGB/OBJ：坐标系、范围、瓦片/文件索引、孤立文件、模型可预览性。

质量状态只有三种：`pass`（可发布）、`review`（需人工复核）、`blocked`（禁止发布/禁止绑定本体）。质量报告写入 run 目录，并作为元数据和血缘的实体，而不是只写日志。

## 7. 元数据与血缘

必须维护以下边：

```text
source file/目录 -> staging chunk -> raw asset
raw FileGDB -> scanned feature class -> standardized layer
raw TIFF -> raster profile -> COG/STAC -> slope/aspect
raw OSGB/OBJ -> model index -> preview/服务切片
standardized DLTB + DEM -> Paper9 slope/prepared dataset
standardized layer -> ontology binding -> ontology instance/query view
quality rule run -> quality report -> publish decision
```

元数据至少包括 owner、来源部门、采集时间、空间范围、CRS、版本、生效/失效时间、敏感等级、质量状态、标准版本、EA 候选、ontology concept、原始 hash 和派生参数。OpenMetadata/OpenLineage 可在有条件时同步；隔离环境不能连外部服务时，以本地 JSON manifest 为权威，恢复网络后再做受控投影。

## 8. 数据库、文件湖、本体的边界

- 文件湖保存每个原始记录的载体和不可变版本，适合大文件、审计和重放；不是所有记录都进入本体库。
- PostGIS 保存通过治理的标准化矢量和可查询属性，承担空间过滤、统计和服务发布。
- 本体库存储类、关系、约束、代码表语义和精选实例索引。大多数 DLTB 图斑、建筑和像元仍留在 PostGIS/文件湖；本体通过 `hasSourceAsset`、`hasGeometryRef`、`hasValidTime` 等引用和聚合指标关联。
- 只有通过质量门禁、字段映射和语义绑定的数据才进入本体应用查询面；原始不合格数据可以被目录检索，但不能被智能体当作权威答案。

## 9. 本体应用场景

首期按客户工作流设计，而不是把系统功能当成类：对象定位（地类图斑/自然幢/POI）、对象沿行政区和规划层级逐级展开、用途和权属关联、红线/黄绿蓝紫线冲突核查、建筑风险高亮、设施服务覆盖、版本对比与变化追踪。每个回答都应返回对象、关系、属性、数据版本、质量状态和来源资产，便于审计。

## 10. Paper9 就绪矩阵

| Paper9 Tool 1 输入/门禁 | 清单现状 | 处理结论 |
| --- | --- | --- |
| 最新 DLTB | 有 2024 变更调查 | 接入后校验年度、字段、几何和县域完整性 |
| DEM | 有高程 TIFF | Tool 1 直接读取，派生坡度并记录算法、分辨率、参数和血缘 |
| PDT | 不是 Tool 1 的原始必需输入 | 由 DEM 派生；如另有官方坡度图，需对比而不能盲目替换 |
| 生态保护红线/STBHHX | 有评价/红线候选 | 不作为 Tool 1 输入；进入自然资源治理和本体语义质量门禁 |
| YJJBNT 永久基本农田 | 清单是否包含取决于实际批次 | 不作为 Tool 1 输入；涉及相关业务分析时单独做权威性门禁 |
| 行政区 | 有省市县乡村界线 | 可作为分县运行和结果校验基础 |
| 土壤、水利、道路、权属、工程成本等扩展变量 | 部分缺失/未确认 | 可先运行核心版本，扩展分析需另做就绪评估 |

因此，宁夏数据具备支持 Paper9 Tool 1 准备流水线的条件，但正式县域运行仍需 DLTB/DEM 覆盖、几何拓扑、坡度有效率、算法包版本和独立 GIS 复核全部通过。其他保护类图层是否参与某个业务场景，由该场景的输入合同单独规定。

## 11. 无真实数据时的验证与上线顺序

开发环境使用 `test_offline_ingest.py`、`test_offline_ingest_routes.py` 的模拟二进制和伪 GDB 目录验证协议，不把模拟结果当业务质量结论。内网首批建议顺序：行政区 -> DLTB -> DEM/TIFF -> STBHHX/YJJBNT/PDT -> ZRZ/FWJZ -> 规划与评价 -> POI/社会经济 -> OSGB/OBJ。每批次都先 raw commit，再 scan/profile，再人工确认 mapping，再 quality gate，最后 standardize/publish/ontology bind。

已使用规划院样例压缩包完成一次真实驱动验证，详见 [重庆全流程记录](nx_chongqing_full_flow_execution_2026-08-07.md)。该样例为重庆数据，只验证技术链路，不能替代宁夏生产数据的质量和算法版本证明。
