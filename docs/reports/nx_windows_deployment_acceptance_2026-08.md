# 宁夏 GIS Data Agent 内网部署与真实数据到达验收手册

**适用环境**：Windows 物理隔离主机，无容器；FileGDB、SHP、TIFF、三维文件通过受控目录或分片客户端到达。

## 先明确“保证”的边界

真实数据尚未交付时，不能保证字段名、长度、代码值域、坐标系和业务含义一定符合标准，也不能用重庆样例替代宁夏法定数据。系统能保证的是：

- 文件到达后先以 SHA-256 和版本标识写入不可变 Raw 区，断电或进程重启不会覆盖原始资产；
- FileGDB/SHP/TIFF 的画像、字段差距、质量结果、事件日志和血缘会落盘，即使后续适配器缺失也会生成可诊断的 `blocked` 报告；
- 未知图层、缺字段、类型/CRS/质量不符的数据进入 `review`/`unmatched`，不会被误当作权威数据；
- 运行基线按数据集完成字段匹配、质量门禁和标准化后即可申请本体绑定；正式 EA/标准合同可用于行政发布留痕，但不是整个系统启动或其他合格数据集问数的全局前置条件；
- Paper9 Tool 1 需要宁夏真实 DLTB 和 DEM；PDT 由 DEM 派生。系统还会对算法包版本、覆盖、几何和坡度有效率保持 fail-closed；STBHHX/YJJBNT 是否参与分析由具体场景合同规定。

## 交付前在开发机执行

### 1. 编译宁夏数据模型运行基线

```powershell
uv run python scripts\compile_nx_standard_contract.py `
  --role-contracts .tmp\twm_standard_generation_check\standards\one_map_role_contracts.zh.json `
  --field-aliases .tmp\twm_standard_generation_check\standards\one_map_field_aliases.zh.json `
  --value-domains .tmp\twm_standard_generation_check\standards\one_map_value_domains.zh.json `
  --field-catalog .tmp\twm_standard_generation_check\tables\standard_field_catalog.csv `
  --ea-table-comparison D:\GDA_CONFIG\ea-standard-table-comparison.csv `
  --ea-logical-comparison D:\GDA_CONFIG\ea-standard-logical-entity-comparison.csv `
  --shp-workbook D:\GDA_CONFIG\SHP矢量数据表及字段梳理_追加更新版.xlsx `
  --inventory-workbook D:\GDA_CONFIG\提供数据内容详细梳理分析20260716.xlsx `
  --standard-version NX-2026-08-baseline `
  --output D:\GDA_CONFIG\nx-standard-contract-catalog.v2.baseline.json `
  --report D:\GDA_CONFIG\nx-standard-contract-compile.md
```

这里的 JSON 是由两份宁夏 Excel、EA 对比证据和自然资源标准整理出的运行基线。真实文件到达后，系统按数据集补充并核验实际字段类型、长度、精度、必填性、主键/唯一性、值域、SRID、时间语义和质量规则。需要行政发布留痕时可以另行生成 `authority=ea_standard`、`review_status=approved` 的版本，但该版本不是 Windows 主机启动、入湖或其他合格数据问数的全局前置条件。

### 2. 做 Windows 主机预检

```powershell
python scripts\preflight_windows_ingest.py --mode production `
  --lake D:\GDA_FILE_LAKE `
  --inbox D:\NX_INCOMING `
  --contracts D:\GDA_CONFIG\natural_resource_standard_contracts.json `
  --ontology D:\GDA_CONFIG\ontology\natural_resource_one_map\active.json `
  --min-free-gb 500 `
  --output D:\GDA_DIAGNOSTICS\preflight.json `
  --markdown D:\GDA_DIAGNOSTICS\preflight.md
```

预检为 `blocked` 时禁止启动生产 worker。重点检查内置 Python GIS wheelhouse、GDAL/PROJ 数据目录、磁盘空间、Raw/日志/诊断目录 ACL、合同哈希、本体包版本、PostGIS DSN（如启用）和日志轮转。ArcPy、ArcPy MCP 和外部 GDAL 不属于必需项。

### 3. 在没有宁夏真实数据时做演练

```powershell
python scripts\run_windows_ingest_drill.py `
  --sample-zip D:\GDA_SAMPLE\规划院提供数据样例及Demo系统功能演示建议.zip `
  --lake D:\GDA_DRILL_LAKE `
  --output D:\GDA_DIAGNOSTICS\windows-ingest-drill.json `
  --allow-review-plan
```

演练必须通过以下检查：Raw 资产存在且同名不同 hash 不覆盖、`run.json/manifest.json/quality_report.json/events.jsonl` 齐全、血缘边存在、分片上传在重启后继续、标准化工具失败可见、未通过数据集质量门禁的资产不能绑定本体。样例为重庆数据，只验证技术链路，不能解除宁夏 Paper9 输入门禁。

## 真实数据到达后的固定流程

1. 供应方把完整 FileGDB 目录、SHP sidecar 或 TIFF 放入 `D:\NX_INCOMING\<批次号>`；大文件也可以使用分片 HTTP session，禁止直接写 Raw 目录。
2. Windows worker 先计算目录/文件 hash，发现同一源路径的新 hash 时生成新资产版本；旧 Raw 保持只读。
3. 页面或 API 查看字段画像和 `quality_report.json`。每个字段都会展示 source field、canonical field、source/standard type、长度、必填和缺口。
4. `blocked` 必须修复后重新扫描；`review` 由管理员逐项确认后才能生成标准化计划。人工复核不能绕过 `blocked`。
5. 标准化产物写入 `materialized/<plan_id>`：矢量默认 GeoParquet（可选 GPKG/PostGIS），栅格转 COG 并生成 STAC item，三维数据登记索引；每个产物保存 hash、参数、命令、输出和 lineage。
6. 质量复核通过后，才允许申请 ontology binding。绑定只登记治理产物引用、标准版本、本体版本和血缘，不复制原始业务记录进本体库。
7. 语义层只读取 `accepted` 且具有质量证据的治理产品。字段不完整、过期、涉密或失败资产可在目录中发现，但不能成为问数答案。
8. Paper9 运行前单独检查 DLTB 与 DEM 的覆盖范围、字段、CRS、唯一性、拓扑、坡度有效率和派生参数；任一缺失则保持 `ready=false`。

## 现场验收判据

| 验收项 | 通过条件 |
|---|---|
| 断电恢复 | 中断上传后 session 查询到已完成分片，重启继续并最终全文件 hash 一致 |
| 原始不可变 | 同名不同 hash 形成两个 Raw 资产，历史 manifest 不被修改 |
| FileGDB | 内置 pyogrio/OpenFileGDB 能列出图层、字段、要素数、几何类型和 CRS；失败有明确日志 |
| TIFF | 能读取尺寸、波段、CRS、范围、分辨率、nodata；无法读取时进入复核/阻断 |
| 字段对齐 | 每个候选字段有 source/canonical/type/length/required/missing 证据；未知字段不丢弃 |
| 质量门禁 | 几何、主键、面积、拓扑、行政区、时间、值域和安全规则有 pass/review/blocked 结果 |
| 血缘与诊断 | 运行目录包含 JSON、JSONL、质量、血缘和可导出的诊断 ZIP |
| 本体边界 | 本体库只有类/关系/约束/治理产品引用，不出现全量原始图斑复制 |
| Paper9 | DLTB+DEM 及算法包版本、空间质量证据全部通过，否则明确列出阻断项 |

## 现场问题处理原则

不要为了让批次“变绿”而手工删除失败日志、修改 Raw 文件或把 screenshot/demo 合同改成权威。正确做法是保留原批次和诊断包，补充 EA/标准合同或修复工具环境后重新生成一个新 run；所有版本通过 hash 和 lineage 关联。
