# GIS Data Agent 地类图斑（DLTB）全流程演示脚本

**版本**：2026-08-07
**演示类型**：单数据集纵向演示
**验证状态**：已使用重庆规划院样例的真实 `GDB.gdb/DLTB` 和 `Chongqing_aster_gdem_80m.tif` 验证
**建议时长**：20 分钟（不含首次解压和大文件传输）

## 1. 演示口径

开场必须先说明：

> 今天使用的是重庆规划院样例，用来证明 GIS Data Agent 的技术链路可以执行。它不是宁夏权威生产数据，因此所有演示绑定都标记为 `rehearsal`，不会发布为宁夏生产语义源。现场接入宁夏真实 DLTB 后，使用同一流程和宁夏数据模型合同重新执行质量门禁。

本演示证明的是：

```text
DLTB.gdb
  -> 探查与原始入湖
  -> 深度质量
  -> 标准化 GeoParquet
  -> 自然资源本体 2.3 引用绑定
  -> land_parcel_current 语义投影
  -> 语义问数与空间预览
  -> Paper9 Tool 1（DLTB + DEM）
```

本演示不声称：

- 重庆数据已经符合宁夏生产标准；
- 重庆样例可以直接作为宁夏正式数据；
- 质量为 `review` 的数据可以申请生产本体绑定；
- Paper9 Tool 1 的派生结果就是本体实例。

## 2. 输入与验证证据

### 2.1 输入文件

已验证的输入为：

```text
GDB.gdb/DLTB
  /Users/zhouning/Downloads/规划院提供数据样例及Demo系统功能演示建议_解压/
  规划院提供数据样例及Demo系统功能演示建议/01数据样例/07规划编制相关数据/
  区县/现状用地数据/GDB.gdb

DEM（仅用于 Paper9 Tool 1）
  /Users/zhouning/Downloads/规划院提供数据样例及Demo系统功能演示建议_解压/
  规划院提供数据样例及Demo系统功能演示建议/01数据样例/01重庆市DEM数据2020年/
  Chongqing_aster_gdem_80m.tif
```

Windows 现场把上面两个路径替换为例如：

```text
D:\NX_INCOMING\批次01\DLTB.gdb
D:\NX_INCOMING\批次01\DEM.tif
```

### 2.2 已验证的报告

本次演示的完整 JSON 报告：

```text
/private/tmp/gda-dltb-demo-script-validation.json
```

生产门禁验证报告：

```text
/private/tmp/gda-dltb-demo-script-production-validation.json
```

现场应把输出路径改为 `D:\GDA_DATA\reports\`。报告不能删除，尤其是质量为 `review` 时。

## 3. 演示前准备

### 演示人员

| 角色 | 任务 |
|---|---|
| 主讲人 | 按本脚本讲解数据流、模型、本体和门禁边界 |
| 操作员 | 执行命令或点击页面按钮，展示实时状态 |
| 业务方 | 确认字段含义、质量问题是否可接受、是否允许生产发布 |

### 检查清单

- GIS Data Agent 已启动，使用内置 Python GIS 运行时；不依赖 ArcPy、MCP、容器或外网。
- `GDA_FILE_LAKE_ROOT` 指向演示湖目录。
- 受控输入目录只包含本次 DLTB 和 DEM，避免其他样例资产干扰结果。
- 本体活动版本为 `2.3.0`。
- 演示模式使用 `rehearsal`，不使用 `production`。

## 4. 主演示流程

### Step 1：说明数据对象和目标

**主讲人说：**

> 这次只选择地类图斑，不把所有数据清单一次性塞进演示。我们要证明一个数据对象能不能走通从文件到语义问数的完整链路。DLTB 在数据模型中对应“地类图斑”，在本体中对应 `LandParcel`；具体图斑记录留在数据湖/标准化产品中，本体只保存概念、字段语义、关系和治理产品引用。

**页面位置：** `数据资源 → 数据接入 → 离线入湖`

### Step 2：扫描受控目录

**页面操作：**

1. 在“Windows 受控目录”输入 `D:\NX_INCOMING\批次01`。
2. 点击“扫描目录”。
3. 在最近运行中打开本批次详情。

**命令行等价操作：**

```powershell
python scripts\run_dltb_vertical_demo.py `
  --source D:\NX_INCOMING\批次01\DLTB.gdb `
  --dem D:\NX_INCOMING\批次01\DEM.tif `
  --lake D:\GDA_DATA\file_lake `
  --output D:\GDA_DATA\reports\dltb-rehearsal.json `
  --mode rehearsal
```

**演示时展示：**

- 资产类型：`filegdb_bundle` 和 `raster`；
- 图层识别：`DLTB`；
- 要素数：`101,657`（重庆样例实测值）；
- DLTB 字段数：`11` 个物理字段；
- 原始文件 SHA-256、运行 ID、Raw 路径和 `events.jsonl`。

**讲解重点：**

> 这一步只是数据探查和原始入湖，不代表数据已经标准化。原始文件进入不可变 Raw 区，后续任何修复都生成新版本，不覆盖原始证据。

### Step 3：展示深度质量结果

**页面操作：**在运行详情中查看质量列和字段映射列；点击“诊断包”可下载 JSON/JSONL/血缘。

**重庆样例实测结果：**

| 检查项 | 结果 |
|---|---:|
| 深度质量状态 | `review` |
| DLTB 要素数 | 101,657 |
| 空几何 | 0 |
| 空几何对象 | 0 |
| 无效几何 | 180 |
| 重复 BSM | 0 |
| DLTB 映射 | `manual_review` |
| DEM 有效采样比例 | 0.388805 |

**主讲人说：**

> 系统没有因为字段名字相似就把重庆 DLTB 变成权威对象。现在质量是 `review`，原因是存在无效几何、字段映射需要人工确认，DEM 还有覆盖不足。`review` 可以用于演示治理，但不能直接生产发布。

### Step 4：生成标准化计划

**页面操作：**

1. 在运行详情点击“人工复核后生成”。
2. 展示计划中的 `DLTB` 输出目标和字段映射。
3. 说明人工复核按钮只允许演示/复核流程，不会清除质量问题。

**实测结果：**

- 计划状态：`planned`；
- DLTB/DEM 输出目标：`2` 个；
- 目标格式：DLTB 为 GeoParquet，DEM 为 COG/STAC。

### Step 5：执行标准化

**页面操作：**点击“执行标准化”。

**实测结果：**

- 执行状态：`succeeded`；
- `DLTB__<hash>.parquet` 已生成；
- DEM COG 和 STAC item 已生成；
- 每个目标均保留源资产、参数、SHA-256 和 lineage。

**主讲人说：**

> 标准化产品是治理后的数据产品，不是本体实例。后续查询优先读取这个产品，Raw 文件仍作为可追溯原件保留。

### Step 6：演示本体绑定

**页面操作：**点击“演示本体绑定”。

**实测结果：**

- 本体版本：`2.3.0`；
- 状态：`accepted_for_rehearsal`；
- 生产资格：`false`；
- 绑定对象：`DLTB` 和栅格标准对象 `SZGCMX`；
- 绑定策略：`reference_only_no_raw_record_copy`。

**主讲人说：**

> 本体绑定登记的是标准化数据产品引用、版本和治理证据，不把 101,657 条图斑记录复制进本体库。这样既保留本体的概念和关系能力，又避免把数据湖当成本体实例库。

### Step 7：生成 DLTB 语义投影

**页面操作：**点击“生成 DLTB 语义投影”。

**应看到：**

- 语义源：`land_parcel_current`；
- 本体版本：`2.3.0`；
- 质量：`review`；
- 标签：`rehearsal_only`；
- 产物：`semantic_projection.json`、`dltb_metrics.json/csv`、`dltb_preview.geojson`、`lineage.json`、`catalog.json`。

**字段语义映射：**

| 物理字段 | 语义字段 | 本体属性 | 本体域 |
|---|---|---|---|
| `BSM` | `feature_identifier` | `featureIdentifier` | `LandParcel` |
| `YSDM` | `feature_code` | `featureTypeCode` | `LandParcel` |
| `DLBM` | `land_use_code` | `currentLandUseCode` | `LandParcel` |
| `DLMC` | `land_use_name` | `currentLandUseName` | `LandParcel` |
| `TBMJ` | `parcel_area_sqm` | `parcelArea` | `LandParcel` |
| `ZLDWDM/ZLDWMC` | `located_admin_code/name` | `administrativeDivisionCode/Name` | `AdministrativeUnit` |

**实测指标：**

- 图斑数：`101,657`；
- 地类分组：`24`；
- 行政区分组：`1,596`；
- `TBMJ` 汇总面积：`962,102,221.63 m²`；
- 属性面积与几何面积差异超过 5%：`1,266` 条。

### Step 8：执行语义问数

在语义问数输入框依次输入：

```text
各地类图斑数量和面积是多少？
列出面积属性与几何面积差异较大的图斑
```

**第一问实测结果前 3 项：**

| DLBM | 地类 | 图斑数 | 面积（m²） |
|---|---|---:|---:|
| 011 | 水田 | 14,021 | 263,235,524.36 |
| 031 | 有林地 | 13,004 | 231,712,709.15 |
| 013 | 旱地 | 25,496 | 222,561,263.61 |

**第二问应看到：**

- 返回面积属性、几何面积、差异值和差异百分比；
- 结果最多展示 100 条；
- 查询来源标记为 `land_parcel_current`。

**主讲人说：**

> 问数不是直接猜字段，也不是把问数功能建成一个本体类。系统先通过语义层把“地类、图斑、面积”解析到受控字段，再对标准化 GeoParquet 执行确定性计算。

### Step 9：展示空间预览和血缘

**操作：**打开 `dltb_preview.geojson` 或页面地图预览，随后下载诊断包。

**必须展示的血缘方向：**

```text
GDB.gdb/DLTB
  -> Raw asset
  -> DLTB GeoParquet
  -> land_parcel_current
  -> ontology:DLTB / LandParcel reference
```

强调：血缘记录的是数据产品和语义引用关系，原始图斑仍在数据湖，不进入本体库作为全量实例。

### Step 10：执行 Paper9 Tool 1（可选）

如果演示机器有本地 Paper9 算法目录，执行：

```powershell
python scripts\run_dltb_vertical_demo.py `
  --source D:\NX_INCOMING\批次01\DLTB.gdb `
  --dem D:\NX_INCOMING\批次01\DEM.tif `
  --lake D:\GDA_DATA\file_lake `
  --output D:\GDA_DATA\reports\dltb-paper9-rehearsal.json `
  --paper9-repo D:\GDA_RUNTIME\paper9 `
  --run-paper9-tool1 `
  --mode rehearsal
```

**重庆样例实测结果：**

- Tool 1 状态：`ok`；
- DLTB 输入图斑：`101,657`；
- 计算出坡度的图斑：`101,657`；
- DEM 直接未覆盖图斑：`92,948`；
- 中位坡度填充值：`2.434°`；
- 输出：`DLTB_with_slope.shp`。

**必须说明：**

> 这是 Paper9 Tool 1 的技术演示结果。正式宁夏运行还要通过宁夏字段、CRS、几何、覆盖率、算法包版本和运行审计门禁；不能用重庆样例结果替代正式验收。

## 5. 生产门禁反向演示

为证明系统不会“强行变绿”，可在演示结束执行生产模式：

```powershell
python scripts\run_dltb_vertical_demo.py `
  --source D:\NX_INCOMING\批次01\DLTB.gdb `
  --dem D:\NX_INCOMING\批次01\DEM.tif `
  --lake D:\GDA_DATA\file_lake-production-check `
  --output D:\GDA_DATA\reports\dltb-production-check.json `
  --mode production
```

**预期结果：**

- 进程退出码：`2`；
- 仍生成 JSON 报告；
- `production_eligible=false`；
- `production_blockers` 明确列出 `quality review is required before promotion`、`manual_review`、`invalid_geometry:180` 以及 DEM 覆盖问题；
- 不生成生产标准化计划，不生成生产语义源。

这一步是质量控制演示，不是失败。它证明系统不会将未通过质量和字段门禁的数据发布到权威语义层。

## 6. 演示结束语

> 通过一个真实 DLTB 图层，我们已经验证了 GIS Data Agent 在隔离环境中对地类图斑的完整处理链路：原始数据可追溯、质量问题可解释、数据模型负责标准化、本体负责概念和关系、语义层负责受控问数，Paper9 负责派生分析。下一步接入宁夏真实数据时，只需把输入目录和宁夏合同替换进去，不能跳过每个数据集的质量门禁。

## 7. 演示验收表

| 验收项 | 本次结果 | 结论 |
|---|---:|---|
| DLTB FileGDB 读取 | 101,657 个图斑 | 通过 |
| Raw 和运行日志 | `run.json/events.jsonl/manifest.json` | 通过 |
| 深度质量 | `review`，原因可解释 | 通过门禁行为验证 |
| GeoParquet 标准化 | `succeeded` | 通过 |
| 本体 2.3 演示绑定 | `accepted_for_rehearsal` | 通过，生产资格为否 |
| 语义投影 | `land_parcel_current` | 通过 |
| 离线问数 | 2 类查询返回结果 | 通过 |
| Paper9 Tool 1 | `ok` | 通过技术演示 |
| 生产发布 | 被退出码 `2` 阻断 | 符合预期 |
