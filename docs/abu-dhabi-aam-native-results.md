# AAM L1 / L2 原生结果接入与运行记录

本功能属于 `feat/abu-dhabi-hydrodynamics-reproducible-runtime` 分支。提供既有一维 SWMM / 二维 ANUGA 耦合计算的只读查看、原生文件下载、排水管线和历史积水点叠加，以及蓄水池连接问题的地图说明。

## 本次计算的范围

| 项目 | 本次设置 |
|---|---|
| 范围 | 所提供的 69 个 AAM 行政区面合并，全行政区 |
| L1 | 行政区、排水管网、5 m DTM |
| L2 | L1 加入 1 个已确认 POND，初始为空 |
| 一维 / 二维引擎 | EPA SWMM 5.2.4 / ANUGA 浅水方程有限体积计算 |
| 网格 | 100 m；1,344,449 个有效格，每格 2 个三角形 |
| 坐标 | EPSG:32640；地图显示转为 EPSG:4326 |
| 降雨 | 均匀 60 mm/h，持续 1 小时，再退水 4 小时；未获得核实后的当地小时内雨型 |
| 输出 / 耦合 | 每 300 秒输出；每 30 秒交换地表与管网水量，共 600 个窗口 |
| 初始与损失 | 地表、管网干；零入渗、零蒸发，无外部来水 |
| 泵与蓄水池 | 无已核实泵曲线及控制，未启用主动泵送；蓄水池采用管道进水、45,000 m³ 等效库容 |

`prepared/configuration.json` 保存完整假设与输入摘要，`results/L1/run_receipt.json` 和 `results/L2/run_receipt.json` 保存实际运行状态及质量指标。两场景均已完成，但 **`quality_passed=false`**：SWMM 路由误差约 1.27%，不收敛步比例约 0.87%。这些是未校准的诊断计算，不能据此量化现实设施的减涝效益。

## 原生文件与可拷贝交付

本机运行根目录为：

```text
/Users/zhouning/Downloads/阿布扎比/AAM_L1_L2_100m_60mm1h_20261016
```

| 文件 | 含义 |
|---|---|
| `results/L1/AAM_L1_1D.out`、`results/L2/AAM_L2_1D.out` | SWMM 原生二进制结果，全部节点和管段；60 帧，300–18,000 秒 |
| `results/L1/AAM_L1_1D.rpt`、`results/L2/AAM_L2_1D.rpt` | SWMM 原生文本报告，包括计算警告及路由统计 |
| `results/L1/AAM_L1_1D.inp`、`results/L2/AAM_L2_1D.inp` | 本次使用的一维模型输入副本；准备阶段源文件为 `prepared/L1/model.inp`、`prepared/L2/model.inp` |
| `results/L1/AAM_L1_2D.sww`、`results/L2/AAM_L2_2D.sww` | ANUGA 原生 NetCDF 结果，61 帧，0–18,000 秒，含初始帧 |
| `results/L1/run_receipt.json`、`results/L2/run_receipt.json` | 运行回执、质量状态、库和输入哈希 |

可直接拷贝运行根目录下的 `原生计算结果_可拷贝/L1/`、`原生计算结果_可拷贝/L2/`，或 `AAM_L1_L2_原生计算结果_100m_60mm1h_退水4h.zip`（约 5.8 GB）。原生结果、客户 GIS 数据、派生地图数据及核查 evidence 保留在本地，不随代码提交。

**单独执行 `.inp` 不能复现本次降雨事件。** 雨只施加到二维地表，雨水口入流、水头反馈和溢流回灌由外部耦合程序逐窗口传递；需要匹配的网格、接口映射、求解器和桥接库。

## 在 GIS Data Agent 中接入

启动后端前设置 `ABU_DHABI_AAM_RESULTS_DIR` 指向运行根目录；未设置时使用上述本机路径。沿用项目的后端、前端启动流程，登录后打开：

```text
http://127.0.0.1:5173/?view=aam_native
```

后端预期目录：

```text
<run-root>/
  prepared/
    configuration.json
    grid.npz
    aam_boundary.gpkg
    aam_pond.gpkg
    node_mapping.csv
    link_mapping_and_adaptations.csv
    L1/interfaces.npz
    L2/interfaces.npz
    map_assets/
      manifest.json
      aam_drainage.fgb
      aam_hotspots.geojson
      aam_connection_gap.geojson
  results/
    L1/  # 原生文件、run_receipt.json、cell_results.npz、depth_frames.npy
    L2/  # 同上
```

接口均要求登录，前缀为 `/api/abu-dhabi/flood/aam`：

| 路径 | 用途 |
|---|---|
| `/scenarios` | L1 / L2 状态、质量、时间轴及文件地址 |
| `/{scenario}/frame?time_index=0` | 时间帧 GeoJSON 预览 |
| `/{scenario}/maximum-depth` | 最大水深预览 |
| `/boundary`、`/pond` | 行政区和已纳入的蓄水池 |
| `/pipelines`、`/hotspots`、`/connection-gap` | 管线下载、AAM 内历史积水点及连接问题图层 |
| `/assets/{scenario}/{name}` | 白名单原生文件下载，支持 HTTP Range |

地图仅显示水深至少 0.05 m 的格子，单帧最多 24,000 格；全量二维结果以 `.sww` 为准。管线地图通过已注册的 MVT 图层显示，下载为 FlatGeobuf。历史积水点是客户提供的 506 点中落入 AAM 的子集，属于历史参考信息。

## 生成地图与核查材料

以下命令在仓库根目录运行；`AAM_RUN`、`AAM_SOURCE`、`AAM_EVIDENCE` 分别替换为运行根目录、已解压并完成前处理的数据目录、独立的本地 evidence 目录。GIS Python 环境需要 NumPy、Pandas、SciPy、GeoPandas、Pyogrio、Shapely、Rasterio、PyProj；MVT 注册还需要项目数据库配置与 PostGIS。

```bash
PYTHONPATH=. .venv/bin/python scripts/build_aam_map_overlays.py \
  --run-dir "$AAM_RUN" \
  --gdb "$AAM_SOURCE/stormwater.gdb" \
  --hotspots /path/to/abu_dhabi_customer_hotspots_506.geojson \
  --register-tiles --owner admin

.venv/bin/python scripts/audit_aam_l2_pond_connection.py \
  --run-root "$AAM_RUN" --source-root "$AAM_SOURCE" \
  --output-dir "$AAM_EVIDENCE"

.venv/bin/python scripts/build_aam_connection_gap_overlay.py \
  --run-dir "$AAM_RUN" --evidence-dir "$AAM_EVIDENCE"
```

`AAM_SOURCE` 必须包含 `aam_boundary.gpkg`、`stormwater.gdb` 和 `aa_wr/*.gdb`，包括 `aa_wr/DMT_IrrigationStormWater_AlAin.gdb`。先生成地图 manifest，再生成连接问题叠加；接口分别读取 manifest 和连接问题 GeoJSON。这些命令生成展示与诊断材料，不重算 L1 / L2。

## 蓄水池为何没有进水

已查明模型塘侧 `N004823` 与有来水的上游侧 `N004824` 相距约 2.9 cm，按 1 mm 端点键建模时没有合并。塘侧 8 管、9 节点的分量没有有效雨水口，与上游分离。原生 OUT 全部输出时刻及 600 个耦合窗口均记录蓄水池水量为零；这不能解释为现实管道断裂或蓄水池无效。

地图“定位 2.9cm 模型断点”按钮可定位这一问题。完整证据解释见 [蓄水池连接核查说明](deliverables/AAM_L2_蓄水池连接核查_20261016/核查说明.md)。后续应按资产关联治理拓扑、标高、地表交换与库容，再以同一治理后的基础管网成对重算 L1 / L2。本次只纳入一个已确认 POND，不代表现实中只有一个蓄水设施。

## 实际计算源码快照

`scripts/abu_dhabi_aam/` 保存本机运行目录的准备、求解、导出、交付和调度源码，`source_snapshot.json` 记录每个源文件的 SHA-256。这是实际运行源码归档，仍保留当时的本机路径和目录假设，尚不是全自动、跨平台的复现入口。

重新运行前需在**独立的新运行目录**部署这些脚本，准备 `prepared/`、`rainfall_sources/` 等相邻目录，并核对或调整：

- `prepare_aam.py` 的 `AUDIT` 路径：除上述 GIS 外，还读取 `aam_dtm_100m_preview.tif`、`pipe_endpoints_dtm5m.npy`、`source_archives.json` 等前处理产物；未归档完整的上游 GIS 前处理流水线。
- `run_aam.py` 的 `ROOT`、`overnight_supervisor.py` 的 ANUGA Python 路径；求解环境须已有 ANUGA、NumPy、SciPy 和 NetCDF 支持。
- 已安装的 SWMM 5.2.4 动态库；`aam_swmm_bridge.c` 必须用该版本匹配的内部头文件和库编译为相邻的 `aam_swmm_bridge.dylib`。桥接直接访问内部结构，不应随意替换 SWMM 版本。
- 调度依赖 macOS `caffeinate`；额外的报告导出脚本依赖 Pandoc。

源码快照没有附带求解器二进制、编译产物、原始 GIS 或大型运行数据。接入已有结果仅需上面的查看接口及数据目录，不需要启动调度器。不要直接在现有交付目录重跑或覆盖结果。
