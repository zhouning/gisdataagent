# 国土空间世界模型数据需求与现有数据评估

- **状态**：Draft（开发前置数据盘点）
- **日期**：2026-06-15
- **关联设计**：`docs/superpowers/specs/2026-06-15-territorial-world-model-design.md`
- **结论**：现有数据足够支撑 P0-P2 的工程 MVP 与演示闭环；当前阶段不以获取真实权威管控数据为前置条件，而以验证 TWM 的数据契约、入模、质检、规则、证据链和未来可替换能力为目标。缺失的控制线、规划分区、审批和执法数据可以作为“权威数据替身测试集”合成，不能作为真实业务结论依据。

> 2026-06-16 阶段更新：TWM 暂不进入完整产品化实现。当前数据包的优先用途调整为 **paper 验证底座**：用统一的 `S_t`、硬约束、动态推演输入、多目标指标、Pareto 比选和审计证据链，验证后续 paper 中的 WorldModel、MPC、DRL、CA、图时序或其他优化方法是否真正具备落地价值。待关键 paper 验证通过后，再恢复 TWM 系统级实现。

## 1. 当前阶段数据原则

当前研发环境暂时无法获得真实权威自然资源管控数据。这个限制不应被视为 TWM 系统开发的阻塞条件，因为 TWM 最终会部署到真实权威数据环境中运行；到那个阶段，永久基本农田、生态保护红线、城镇开发边界、用途管制分区、审批、执法和年度变更调查等数据将由业务环境提供。

因此，当前阶段的数据准备目标不是“凑齐真实权威数据”，而是建立并验证一套未来可替换的数据适配能力：

1. **真实可获得数据做底板**：DLTB 图斑、乡镇行政界、公开 Sentinel-2 影像等已可获得数据，用于验证 CRS、几何拓扑、空间关系、影像证据、预览和 QA。
2. **不可获得的权威数据做高质量替身**：永久基本农田、生态保护红线、用途管制、项目审批、执法督察和复核记录可以合成，但必须模拟真实数据的角色、字段、版本、状态、异常和质量问题。
3. **合成数据只用于验证系统能力**：合成图层和表格必须持续标记 `synthetic=true`、`not_for_production=true`，不得在任何文档、界面或报告中暗示其为真实业务结论。
4. **系统实现必须按角色绑定而非按文件名写死**：TWM 核心逻辑只能依赖 `role = parcel_current / pbf / eco_redline / planning_zone / project / approval / enforcement` 等业务角色、字段映射和 semantic product，不得依赖 `synthetic_pbf.geojson` 这类演示文件名。
5. **真实权威数据进入时应只替换输入资产**：未来在真实环境中，应通过 `twm_layer_binding`、数据目录资产、MMFE semantic manifest 和字段映射替换输入，不重写状态构建、规则执行、证据链和复核闭环。

换言之，当前数据包的定位是 **生产数据适配能力测试集**，不是生产数据本身。后续开发验收应重点检查“真实数据能否按相同契约替换进来”，而不是检查当前是否已经拥有所有权威数据。

## 2. 结论摘要

目前已有数据可以支撑三类开发目标：

1. **状态表征 MVP**：可以满足。已有璧山、东兴 DLTB-like 图斑数据，字段、几何、面积、行政权属和地类编码基本完整。
2. **规则命中与证据链 MVP**：可以满足，但永久基本农田、生态红线、用途管制分区等控制线需要先合成演示数据。
3. **方案比选与 WorldModel v2.1 集成**：可以满足。已有 prepared 目录、ONNX ensemble、MPC 输出和 summary。

目前不能支撑生产级业务闭环：

- 缺少权威永久基本农田保护范围。
- 缺少生态保护红线。
- 缺少城镇开发边界、规划分区、用途管制单元。
- 缺少建设项目审批范围。
- 缺少执法督察/疑似违法变化图斑。
- 缺少真实年度变更调查时序链。
- 当前本地环境未连上 GIS Data Agent 数据库，`agent_data_assets` 资产目录无法查询，开发阶段需要先按文件路径读取。

## 3. TWM MVP 数据角色

| 数据角色 | 必需性 | 用途 | 当前状态 |
|---|---:|---|---|
| `parcel_current` 地类图斑/地块 | 必需 | 构建 `twm_state_object(parcel)` | 已有，可直接用 |
| `admin_unit` 行政区/乡镇/村界 | 推荐 | 汇总、项目范围、区域指标 | 可由图斑 `QSDWDM/QSDWMC` dissolve 合成 |
| `pbf` 永久基本农田 | 必需于耕地规则 | `TWM-FARM-001` 约束对象 | 缺真实数据，可合成演示 |
| `eco_redline` 生态保护红线 | 必需于生态规则 | `TWM-ECO-001` 约束对象 | 缺真实数据，可合成演示 |
| `planning_zone` 规划分区/用途管制单元 | P1/P2 | 用途准入、规划一致性 | 缺真实数据，可合成演示 |
| `project` 建设项目/调整方案范围 | P1 | 项目触线、方案评估 | 可从 MPC `CHG_FLAG` 或人工选择图斑合成 |
| `annual_change` 年度变化调查 | P2 | 时序状态、变化检测 | 缺真实数据，可由 `ORIG_DLBM -> OPT_DLBM` 合成 |
| `approval` 审批数据 | P2 | 审批一致性与项目证据 | 缺失，只能合成 |
| `enforcement` 执法督察 | P2/P3 | 违法疑似点、复核闭环 | 缺失，只能合成 |
| `semantic_product` MMFE manifest | 推荐 | 字段映射、质量、语义证据 | 当前未发现 `.semantic.json`，可重新生成或包装 |
| `standard_rules` 标准/政策规则 | 必需 | 规则版本与法律依据 | 标准平台已有底座，TWM 规则需新增 |
| `world_model_output` 模型方案输出 | P3 | 方案比选、模型证据 | 已有，可直接用 |

## 4. 已有数据清单

### 4.1 璧山 DLTB 图斑

可用文件：

- `/Users/zhouning/Downloads/shp/bishan.shp`
- `/Users/zhouning/Downloads/bishan/DLTB_with_slope.gpkg`
- `/Users/zhouning/farmland_mpc_runs/bishan/prepared/dem_slope_analysis/output/DLTB_with_slope.shp`

数据概况：

| 指标 | 值 |
|---|---|
| 行数 | 101,657 |
| CRS | 原始 `EPSG:4610`；坡度增强版 `EPSG:4326` |
| 几何 | Polygon / MultiPolygon |
| 关键字段 | `BSM`, `YSDM`, `DLBM`, `DLMC`, `QSDWDM`, `QSDWMC`, `ZLDWDM`, `ZLDWMC`, `TBMJ`, `slope_mean` |
| 地类结构 | 村庄 33,500；旱地 25,496；水田 14,021；有林地 13,004；坑塘水面 5,072 |
| 语义分类 | Farmland 39,562；Forest 13,524；Orchard 4,145；Other 44,426 |

适配判断：

- 可以直接作为 `parcel_current`。
- `BSM` 可作为 `source_feature_id/object_code`。
- `DLBM/DLMC` 可映射为 land use code/name。
- `QSDWDM/QSDWMC` 可用于图斑权属汇总；乡镇边界优先使用 `/Users/zhouning/Downloads/shp/xiangzhen.shp`。
- `slope_mean` 可用于耕地质量/生态敏感演示规则。

### 4.2 东兴 DLTB 图斑

可用文件：

- `/Users/zhouning/Downloads/shp/dongxing.shp`
- `/Users/zhouning/Downloads/DLTB_with_slope.gpkg`
- `/Users/zhouning/arcgis-farmland-mpc/runs/dongxing/dongxing.shp`
- `/Users/zhouning/arcgis-farmland-mpc/runs/dongxing/prepared/dem_slope_analysis/output/DLTB_with_slope.shp`

数据概况：

| 指标 | 值 |
|---|---|
| 行数 | 134,369 |
| CRS | 原始 `EPSG:2359`；坡度增强版 `EPSG:4326` |
| 几何 | Polygon |
| 关键字段 | `BSM`, `TBYBH`, `TBBH`, `DLBM`, `DLMC`, `QSDWDM`, `QSDWMC`, `GDLX`, `GDPDJ`, `TBMJ`, `slope_mean` |
| 地类结构 | 村庄 35,930；旱地 29,897；有林地 29,143；水田 15,787；坑塘水面 6,372 |
| 语义分类 | Farmland 45,735；Forest 30,643；Orchard 8,355；Other 49,636 |

适配判断：

- 可以直接作为第二个区域的 `parcel_current`。
- 字段更完整，适合做标准字段兼容性测试。
- `GDPDJ/GDLX` 可用于耕地质量和坡度规则扩展。

### 4.3 WorldModel v2.1 方案输出

可用文件：

- `/Users/zhouning/farmland_mpc_runs/bishan/mpc_output/optimized.shp`
- `/Users/zhouning/arcgis-farmland-mpc/runs/dongxing/mpc_output/optimized.shp`
- `data_agent/uploads/gemma4_bishan_test/world_model_v21/20260606_130534_351576/optimized_dltb.shp`
- `data_agent/uploads/gemma4_dongxing_test/world_model_v21/20260606_130218_720509/optimized_dltb.shp`

关键字段：

- `OPT_DLBM`
- `OPT_DLMC`
- `CHG_FLAG`
- `ORIG_DLBM`
- `slope_mean`

变化统计：

| 区域 | 方案输出行数 | `CHG_FLAG=1` | `CHG_FLAG=2` | 变化含义 |
|---|---:|---:|---:|---|
| 璧山 | 101,657 | 426 | 426 | 426 个耕地图斑转林地，426 个反向补偿 |
| 东兴 | 134,369 | 454 | 454 | 454 个耕地图斑转林地，454 个反向补偿 |

适配判断：

- 可以作为 P2/P3 的 `scenario_candidate`。
- 可以在 P0/P1 中提前用于合成 `project` 或 `annual_change`。
- 每个变化图斑可生成 `twm_evidence_item(model_output)`，引用 `mpc_summary.json`。

### 4.4 WorldModel v2.1 prepared 与模型文件

可用目录：

- `/Users/zhouning/farmland_mpc_runs/bishan/prepared`
- `/Users/zhouning/arcgis-farmland-mpc/runs/dongxing/prepared`

已有内容：

- `prepare_data_summary.json`
- `townships.json`
- `tool2/transitions.npz`
- `tool2/pairwise.npz`
- `ensemble_seed*/ensemble_member*.onnx`
- `train_summary.json`

适配判断：

- P3 接入 Paper9 WorldModel v2.1 时可直接使用。
- P0-P2 不依赖这些文件。

### 4.5 小范围格网与交互地图数据

可用文件：

- `/Users/zhouning/Downloads/shp/土地利用现状小格网v2.shp`
- `/Users/zhouning/Downloads/shp/banzhu100.shp`
- `/Users/zhouning/Downloads/shp/banzhu25.shp`
- `/Users/zhouning/Downloads/shp/和平村8000.shp`
- `data_agent/uploads/admin/interactive_map_e3159945.geojson`
- `data_agent/uploads/admin/interactive_map_e3159945_diff.geojson`
- `data_agent/uploads/admin/interactive_map_e3159945_opt.geojson`

适配判断：

- 适合前端快速演示和单元测试。
- 字段较少，不适合作为完整 DLTB 标准兼容性主数据。
- `interactive_map_e3159945_diff.geojson` 已有 `Change_Type`，适合测试变化证据链。

### 4.6 生态修复/自然资源治理示例数据

可用文件：

- `/Users/zhouning/arcgis-farmland-mpc/runs/restoration/synthetic/restoration_units.geojson`
- `/Users/zhouning/arcgis-farmland-mpc/runs/restoration/synthetic/ecological_sources.geojson`
- `/Users/zhouning/arcgis-farmland-mpc/runs/restoration/synthetic/water_network.geojson`
- `/Users/zhouning/arcgis-farmland-mpc/runs/restoration/synthetic/settlements.geojson`
- `/Users/zhouning/arcgis-farmland-mpc/runs/restoration/buchanan_va/planning_units_2km.geojson`
- `/Users/zhouning/arcgis-farmland-mpc/runs/restoration/buchanan_va/eamlis_buchanan_va.geojson`
- `/Users/zhouning/arcgis-farmland-mpc/runs/restoration/buchanan_va/nhd_flowline_buchanan.geojson`
- `/Users/zhouning/arcgis-farmland-mpc/runs/restoration/buchanan_va/buchanan_county_boundary.geojson`

适配判断：

- 适合验证“生态约束、居民点距离、水系距离、修复优先级”类 TWM 泛化能力。
- 不适合直接作为中国国土空间规划监管演示的主数据，因为业务制度、编码和区域背景不同。

## 5. 缺失数据与合成方案

### 5.1 永久基本农田 `pbf`

真实状态：缺失。

MVP 合成方案：

1. 从 `parcel_current` 中筛选耕地：
   - `DLBM in ('011', '012', '013')`
   - 或 `category = 'Farmland'`
2. 选择坡度较低、面积较大、连片性较好的图斑：
   - `slope_mean <= 15`
   - `TBMJ >= 1000`
3. 按乡镇或全域保留一定比例，例如 60%-80% 的耕地图斑。
4. dissolve 或保留 parcel-level 作为 `synthetic_pbf`。
5. 增加元数据：
   - `synthetic=true`
   - `synthetic_method='farmland_low_slope_area_threshold'`
   - `not_for_production=true`

适用范围：

- 可用于 `TWM-FARM-001` 的工程测试和演示。
- 不可用于真实监管或对外汇报。

### 5.2 生态保护红线 `eco_redline`

真实状态：缺失。

MVP 合成方案：

1. 从林地、水域、高坡度图斑派生生态敏感区：
   - 林地：`DLBM in ('031', '032', '033')`
   - 水域：`DLBM in ('111', '113', '114', '116')`
   - 高坡度：`slope_mean >= 25`
2. 对水域或林地做 buffer/聚合，形成连续保护片区。
3. 过滤面积过小斑块。
4. 输出 `synthetic_eco_redline`。

适用范围：

- 可用于生态红线触碰风险演示。
- 不可代表法定生态保护红线。

### 5.3 城镇开发边界 / 规划分区 / 用途管制单元

真实状态：缺失。

MVP 合成方案：

- 城镇开发边界：
  - 选择 `DLBM in ('201', '202', '203')` 或 `DLMC in ('城市', '建制镇', '村庄')`。
  - dissolve + buffer + simplify，形成 `synthetic_urban_boundary`。
- 规划分区：
  - 按 `DLBM/DLMC/category` 映射为 `agricultural_space / ecological_space / urban_space / water_space`。
  - 可在 parcel-level 直接作为 `planning_zone`。
- 用途管制单元：
  - 基于规划分区 dissolve，生成管制区面。

适用范围：

- 可用于用途冲突和规划一致性规则测试。
- 生产必须接入权威规划“一张图”和用途管制分区。

### 5.4 建设项目 / 方案范围 `project`

真实状态：缺失。

MVP 合成方案：

- 从 WorldModel 输出中筛选变化图斑：
  - `CHG_FLAG = 1` 或 `CHG_FLAG = 2`
  - `ORIG_DLBM != OPT_DLBM`
- 或从图斑中人工抽样一组建设项目范围。
- 增加项目属性：
  - `project_id`
  - `project_type`
  - `approval_status='proposed'`
  - `scenario_id`

适用范围：

- 可用于方案触碰 PBF/生态红线的命中测试。
- 不可代表真实审批项目。

### 5.5 年度变化调查 `annual_change`

真实状态：缺少多年真实调查链。

MVP 合成方案：

- 以原始 DLTB 为 `t0`。
- 以 MPC optimized 输出为 `t1`。
- 使用 `ORIG_DLBM -> OPT_DLBM` 和 `CHG_FLAG` 形成变化事件。
- 输出变化字段：
  - `from_dlbm`
  - `to_dlbm`
  - `change_type`
  - `change_year='synthetic_2026'`

适用范围：

- 可验证 `S_t -> S_t+1`、状态变化证据链和方案对比。
- 不可替代年度变更调查。

### 5.6 执法督察 / 人工复核样本

真实状态：缺失。

MVP 合成方案：

- 从规则命中结果中抽样生成 `enforcement_event`。
- 或从 `project` 和 `pbf/eco_redline` 的交叠区域生成疑似违法变化。
- 复核结论可人工在 UI 中写入。

适用范围：

- 可用于验证 `twm_review_task` 和审计链。
- 不可作为真实执法数据。

### 5.7 MMFE semantic product

真实状态：当前文件系统中未发现 `.semantic.json`。

补齐方案：

1. 最好：用已有 MMFE 对 DLTB + 合成控制线运行一次 `fuse_datasets(..., semantic_product=true)`，生成真实 manifest。
2. 次选：为现有 DLTB 文件生成最小 manifest wrapper，只包含：
   - `business_output.path`
   - `sources`
   - `semantic_mappings`
   - `quality`
   - `lineage`
3. TWM `semantic_loader.py` 必须同时支持：
   - 有 `.semantic.json`
   - 只有普通 GIS 文件

## 6. 推荐开发数据包

### 6.1 主推：璧山耕地监管 MVP

| role | 文件/生成方式 |
|---|---|
| `parcel_current` | `/Users/zhouning/Downloads/bishan/DLTB_with_slope.gpkg` |
| `scenario_candidate` | `/Users/zhouning/farmland_mpc_runs/bishan/mpc_output/optimized.shp` |
| `world_model_summary` | `/Users/zhouning/farmland_mpc_runs/bishan/mpc_output/mpc_summary.json` |
| `pbf` | 从低坡度耕地图斑合成 |
| `eco_redline` | 从林地/水域/高坡度图斑合成 |
| `admin_unit` | 按 `QSDWDM` 前 9 位 dissolve 合成 |
| `annual_change` | 从 `ORIG_DLBM -> OPT_DLBM` 合成 |

优势：

- 数据量足够真实，字段清晰。
- 已有 MPC 输出，可贯通 P3。
- `EPSG:4326` 和 `EPSG:32648` 两种 CRS 都可测试。

注意：

- 原始 `BSM` 有浮点字符串形式，例如 `1105665.0`，状态构建时要规范化为稳定字符串。

### 6.2 备选：东兴耕地监管 MVP

| role | 文件/生成方式 |
|---|---|
| `parcel_current` | `/Users/zhouning/Downloads/DLTB_with_slope.gpkg` |
| `scenario_candidate` | `/Users/zhouning/arcgis-farmland-mpc/runs/dongxing/mpc_output/optimized.shp` |
| `world_model_summary` | `/Users/zhouning/arcgis-farmland-mpc/runs/dongxing/mpc_output/mpc_summary.json` |
| `pbf` | 从低坡度耕地图斑合成 |
| `eco_redline` | 从林地/水域/高坡度图斑合成 |
| `admin_unit` | 按 `QSDWDM` 前 9 位 dissolve 合成 |
| `annual_change` | 从 `ORIG_DLBM -> OPT_DLBM` 合成 |

优势：

- 字段比璧山更完整，包含 `GDPDJ/GDLX/TBBH/TBYBH`。
- 图斑数量更大，适合后续性能测试。

### 6.3 小数据快速测试包

| role | 文件/生成方式 |
|---|---|
| `parcel_current` | `data_agent/uploads/admin/interactive_map_e3159945.geojson` |
| `annual_change` | `data_agent/uploads/admin/interactive_map_e3159945_diff.geojson` |
| `scenario_candidate` | `data_agent/uploads/admin/interactive_map_e3159945_opt.geojson` |
| `pbf/eco_redline` | 从小格网合成 |

优势：

- 数据小，适合单元测试、API 测试和前端调试。
- 字段简单，处理速度快。

## 7. 满足度判断

| 开发阶段 | 数据是否满足 | 说明 |
|---|---|---|
| Phase 0 schema/contracts | 满足 | 不依赖真实 GIS 数据 |
| Phase 1 state builder | 满足 | DLTB 图斑足够 |
| Phase 2 rule evaluator/evidence | 基本满足 | 需要合成 PBF/生态红线 |
| Phase 3 REST API | 满足 | 可用文件路径做集成测试 |
| Phase 4 ADK Toolset | 满足 | 需要准备固定测试数据路径或 fixture |
| Phase 5 Frontend MVP | 满足 | 小格网 + 璧山数据均可 |
| Phase 6 standards derivation | 部分满足 | 标准平台底座有，TWM 规则需新增 |
| Phase 7 audit/catalog lineage | 部分满足 | 当前本地数据库未配置，需补 DB 环境 |
| Phase 8 scenario comparison | 满足 | optimized 输出可用 |
| Phase 9 WorldModel v2.1 adapter | 满足 | prepared/ONNX/MPC 输出可用 |

## 8. 开发前建议

1. P0-P2 直接以 **璧山数据包** 作为主开发数据。
2. 实现一个 `scripts/generate_twm_demo_data.py` 或 `data_agent/territory_world_model/synthetic.py`，专门生成：
   - `synthetic_pbf.geojson`
   - `synthetic_eco_redline.geojson`
   - `admin_units.geojson`
   - `synthetic_annual_change.geojson`
   - `synthetic_projects.geojson`
3. 所有合成数据必须写入元数据字段：
   - `synthetic=true`
   - `synthetic_method`
   - `source_dataset`
   - `not_for_production=true`
4. TWM API/UI 必须在合成数据参与规则命中时显示“演示/合成数据”标记。
5. 生产落地前必须替换为权威数据：
   - 永久基本农田
   - 生态保护红线
   - 城镇开发边界
   - 国土空间规划“一张图”用途分区
   - 建设用地审批范围
   - 年度变更调查
   - 执法督察记录

## 9. 对后续实现的影响

数据盘点带来的实现约束：

- `state_builder.py` 不能强依赖 MMFE `.semantic.json`，必须支持普通 GIS 文件。
- `source_feature_id` 需要支持 `BSM`、`GRID_ID`、`unit_id` 等不同字段。
- `field_mapping` 必须允许用户或配置显式指定。
- 所有空间规则必须能处理不同 CRS，面积计算应投影到项目 CRS。
- `rule_evaluator.py` 需要能识别并传播 synthetic metadata。
- `evidence.py` 需要记录合成方法，否则审计链会误导用户。

最终判断：**已有数据足够开始 Phase 0-Phase 2 开发；缺失数据可以合成补齐工程验证，但生产级落地必须接入权威自然资源数据。**

## 10. 2026-06-15 数据基础补强基线

为避免后续 TWM 开发建立在“看起来完整、但推理过于理想化”的样例数据上，已将
`data_agent/test_data/twm_bishan_demo/` 从简单演示包升级为可复跑的数据基线。

生成命令：

```bash
PROJ_DATA=/Users/zhouning/miniconda3/envs/farmland-mpc/share/proj \
  .venv/bin/python scripts/generate_twm_demo_data.py --clean

PROJ_DATA=/Users/zhouning/miniconda3/envs/farmland-mpc/share/proj \
  .venv/bin/python scripts/qa_twm_demo_data.py

PROJ_DATA=/Users/zhouning/miniconda3/envs/farmland-mpc/share/proj \
  .venv/bin/python scripts/preview_twm_demo_data.py
```

### 10.1 当前数据包内容

| 数据 | 行数 | 作用 |
|---|---:|---|
| `parcel_current.geojson` | 4900 | 连续片区现状地类图斑底板 |
| `synthetic_pbf.geojson` | 14 | 聚合后的合成永久基本农田边界 |
| `synthetic_eco_redline.geojson` | 10 | 聚合/缓冲后的合成生态保护红线边界 |
| `admin_units.geojson` | 5 | 从 `xiangzhen.shp` 按演示区正面积叠加筛选得到的乡镇行政区边界 |
| `synthetic_annual_change.geojson` | 78 | 从 WorldModel `ORIG_DLBM -> OPT_DLBM` 派生的变化图斑 |
| `synthetic_projects.geojson` | 60 | 多场景合成项目范围 |
| `synthetic_planning_zones.geojson` | 5 | 合成用途管制分区 |
| `synthetic_urban_boundary.geojson` | 5 | 合成城镇开发边界 |
| `synthetic_remote_sensing_tiles.geojson` | 11 | MMFE 遥感瓦片索引，占位连接影像证据 |

配套资产：

- `relations/*.csv`：项目-图斑、项目-PBF、项目-生态红线、项目-用途分区、项目-城镇边界、项目-遥感瓦片、变化-图斑关系表。
- `documents/project_documents.zh.jsonl`：合成中文项目材料，用于文本语义融合和规则解释。
- `standard_rules.lifecycle.json`：演示标准规则和版本生命周期。
- `raster_manifest.json` 和 `rasters/*.tif`：可读取的合成 GeoTIFF 观测夹具。
- `data_quality_report.json` / `data_quality_report.md`：自动 QA 结果。
- `preview/index.html` 和 `preview/twm_bishan_demo_layers.gpkg`：人工审阅入口。

### 10.2 已修复/增强的问题

1. **空间连续性**：从随机抽样改为按 `admin_prefix=500227100` 的连续片区；当前最大连通分量占比 `0.9986`。
2. **几何有效性**：生成流程对多边形做 `make_valid` 和 polygonal extraction；当前全部图层无 invalid/empty geometry。
3. **面积 QA**：现状图斑新增 `geom_area_m2`、`area_source_m2`、`tbmj_area_rel_error`、`qa_area_warning`、`qa_use_for_rules`。
4. **规则输入门槛**：合成管控线、项目和关系链只使用 `qa_use_for_rules=true` 的候选要素。
5. **管控线真实感**：PBF/生态红线从“图斑复制”改为“候选图斑聚合、缓冲、简化”的边界层。
6. **项目真实感**：项目由多类场景驱动生成，包括 PBF 全压占/部分压占、生态红线全压占/部分压占、规划冲突、城镇边界内项目、低风险项目、生态修复项目。
7. **显式证据链**：新增关系表，避免完全依赖临时空间叠加结果。
8. **MMFE 基础**：新增遥感瓦片索引、合成 GeoTIFF 观测夹具和中文项目文本材料，支撑矢量-栅格-文本-规则的语义融合测试。
9. **标准生命周期基础**：新增机器可读规则和标准版本生命周期文件，可对接“数据标准全生命周期智能化管理”能力。
10. **中文可理解性**：`data_dictionary.zh.json` 覆盖所有当前字段和图层，无未知字段缺口。
11. **行政边界替换**：发现并接入 `/Users/zhouning/Downloads/shp/xiangzhen.shp`，不再使用图斑 dissolve 的合成乡镇边界。

### 10.3 当前 QA 结果

`scripts/qa_twm_demo_data.py` 当前 gate 状态为 `pass`：

| 指标 | 结果 |
|---|---:|
| blocker | 0 |
| invalid geometry | 0 |
| empty geometry | 0 |
| 字典未知字段 | 0 |
| `project_parcel_rel` | 354 |
| `project_pbf_rel` | 39 |
| `project_eco_rel` | 28 |
| `project_planning_rel` | 151 |
| `project_rs_tile_rel` | 71 |
| `raster_observation` evidence | 2 |

保留的 warning：

- `parcel_current` 中仍有 59 个源图斑 `TBMJ` 与投影几何面积相对误差超过 10%。
- 这些要素未删除，因为它们代表真实源数据质量风险；但已通过 `qa_use_for_rules=false` 排除出规则输入和合成候选。

### 10.4 仍不满足生产落地的部分

当前数据包仍是工程基线，不是生产监管数据：

- PBF、生态红线、用途分区、城镇开发边界均为合成，不能替代法定权威数据。
- 遥感瓦片已关联可读取的合成 GeoTIFF 像元夹具，但这些像元由矢量语义派生，不是真实卫星观测。
- 默认包行政边界来自 `xiangzhen.shp`，主覆盖乡镇为八塘镇；边界处还会保留少量相邻乡镇小面积叠加，用于 QA 和边界解释。
- 年度变化只有从 WorldModel 输出派生的一期变化，不是多年真实年度变更调查链。
- 项目审批、执法督察、复核结论仍为合成或未补齐。

### 10.5 后续 TWM 开发约束

后续开发必须按以下数据契约执行：

1. 所有面积型规则必须使用投影面积，优先读取 `geom_area_m2` 或在 `project_crs` 下计算。
2. 默认规则输入只接受 `qa_use_for_rules=true` 的对象；若用户要求分析异常数据，必须在结果中显式提示 QA 风险。
3. Agent 解释规则命中时优先使用 `relations/*.csv`，再按需现场空间叠加复核。
4. 所有 synthetic 层必须向前端和审计链传播 `synthetic`、`not_for_production`、`synthetic_method`、`source_dataset`。
5. MMFE 测试应同时加载 `synthetic_remote_sensing_tiles.geojson`、`raster_manifest.json`、`rasters/*.tif`、`documents/project_documents.zh.jsonl`、矢量图层和 `standard_rules.lifecycle.json`。
6. 生产落地前必须替换权威管控线、规划、项目审批、年度变更、执法督察和真实影像数据。

## 11. 2026-06-16 治理闭环与时序补强

在 2026-06-15 数据基线基础上，继续补齐 TWM 落地所需的治理闭环、标准生命周期和时序评估数据。当前默认数据包仍保持 `admin_prefix=500227100` 的连续空间片区，避免回到随机碎片抽样；行政边界优先使用 `xiangzhen.shp` 乡镇边界数据，而不是图斑 dissolve 合成边界。

### 11.1 新增/增强内容

| 类别 | 文件 | 行数 | 用途 |
|---|---|---:|---|
| 乡镇行政边界 | `admin_units.geojson` | 5 | 从 `xiangzhen.shp` 筛选得到的乡镇边界，主覆盖八塘镇 |
| 规则评估结果 | `tables/rule_evaluation.csv` | 240 | 每个项目对 4 类规则的评估结果 |
| 审批记录 | `tables/approval_records.csv` | 60 | 项目审批申请、决定和批准面积 |
| 执法事件 | `tables/enforcement_events.csv` | 92 | 规则命中后的执法/预警事件 |
| 人工复核任务 | `tables/review_tasks.csv` | 92 | 执法事件对应复核闭环 |
| 状态快照 | `tables/state_snapshots.csv` | 10 | 2025 基期与 2026 WorldModel 场景后的国土空间类型面积 |
| 标准字段目录 | `tables/standard_field_catalog.csv` | 137 | 字段生命周期、引入版本、废止样例 |
| 多模态证据索引 | `tables/multimodal_evidence_index.csv` | 166 | 文本、遥感瓦片、栅格观测、规则评估、标准规则证据统一索引 |
| 标准规则生命周期 | `standard_rules.lifecycle.json` | 7 rules / 3 versions | 规则库版本从 `0.1-draft` 到 `0.3-governance-loop` |

### 11.2 QA 结果

最新 QA gate 仍为 `pass`，无 blocker。新增治理闭环完整性检查结果：

| 检查项 | 结果 |
|---|---:|
| 项目规则评估覆盖 | 60 / 60 |
| 项目审批记录覆盖 | 60 / 60 |
| 规则命中需复核 | 92 |
| 执法事件复核覆盖 | 92 / 92 |
| 状态快照年份 | 2025, 2026 |
| 标准字段目录 | 137 字段，含 1 个废止字段样例 |
| 项目文本证据覆盖 | 60 / 60 |

保留的唯一 warning 仍是源 `parcel_current` 中 59 个图斑 `TBMJ` 与几何面积偏差超过 10%。该问题被保留为真实源数据质量风险样本，并通过 `qa_use_for_rules=false` 排除出规则输入。

### 11.3 对最终目标的支撑提升

本轮补强后，数据基础已经能支撑以下闭环开发：

1. **状态构建**：`parcel_current` + `state_snapshots` 支撑 2025/2026 状态对比。
2. **规则推理**：`standard_rules.lifecycle.json` + `rule_evaluation.csv` 支撑规则版本、命中结果和依据解释。
3. **审批一致性**：`approval_records.csv` 可验证规则命中与审批结论是否一致。
4. **执法复核闭环**：`enforcement_events.csv` + `review_tasks.csv` 支撑预警、派单、复核结论。
5. **MMFE 语义融合**：`project_documents.zh.jsonl`、`synthetic_remote_sensing_tiles.geojson`、`raster_manifest.json`、`rasters/*.tif`、`multimodal_evidence_index.csv` 支撑文本-栅格-矢量-规则的证据融合。
6. **数据标准生命周期**：`standard_field_catalog.csv` 和 `standard_rules.lifecycle.json` 支撑字段/规则版本演进、废止和替代字段样例。
7. **区域汇总过滤**：`admin_units.geojson` 支持按真实乡镇边界做区域筛选、边界解释和汇总展示。

### 11.4 仍需后续补强的边界

当前数据基础仍不等同生产数据：

- 默认包仍只有一个乡镇前缀，不覆盖跨乡镇、跨区县的占补平衡和指标流转。
- 遥感瓦片已关联可读取的合成 GeoTIFF 夹具，但不含真实卫星/UAV 影像像元、云检测结果或多时相变化检测产品。
- 审批、执法和复核均为合成记录，只能用于流程和 Agent 解释能力验证。
- 状态快照只有 2025/2026 两期，尚不能验证多年趋势、季节性遥感观测和长期推演。
- 标准规则是演示规则，不是权威法规条款或生产审查规则。

## 12. 2026-06-16 多行政评测包与栅格夹具补强

本轮已完成 11.4 中提出的两个优先事项：新增独立的多行政单元评测包，并将遥感瓦片索引补强为可读取的 GeoTIFF 栅格观测夹具。默认包仍作为稳定的小范围工程基线，多行政包用于更接近真实治理场景的跨乡镇汇总、边界项目、证据融合和 QA 压测。

### 12.1 数据包分工

| 数据包 | 路径 | 行政覆盖 | 定位 |
|---|---|---:|---|
| 默认连续样区包 | `data_agent/test_data/twm_bishan_demo/` | 1 个 `admin9`：`500227100` | 快速开发、单元测试、前端预览、稳定回归 |
| 多行政单元评测包 | `data_agent/test_data/twm_bishan_multi_admin_eval/` | 3 个相邻 `admin9`：`500227100`, `500227101`, `500227102` | 跨行政汇总、边界连通性、跨区项目与 MMFE 评测 |

多行政前缀选择依据是源数据行政单元邻接分析：`500227100-500227101`、`500227101-500227102` 均为真实相邻边界，且三者形成连续链，避免再次引入随机抽样造成的空间空洞和碎片化。

### 12.2 新增脚本能力

| 脚本 | 新能力 |
|---|---|
| `scripts/generate_twm_demo_data.py` | 支持 `--dataset-id`、`--dataset-alias-zh`、`--admin-boundaries`、`--admin-prefixes`、`--raster-size`；默认包和多行政包共用同一生成逻辑 |
| `scripts/qa_twm_demo_data.py` | 新增行政覆盖、栅格文件存在性、CRS、尺寸、有效像元、统计值和 `raster_observation` 证据检查 |
| `scripts/preview_twm_demo_data.py` | 支持 `--data-dir`，可为任意数据包生成 HTML、PNG 和 GeoPackage 预览 |

### 12.2.1 `xiangzhen.shp` 行政边界评估

`/Users/zhouning/Downloads/shp/xiangzhen.shp` 已确认有用，并已接入生成流程作为 `admin_units.geojson` 的来源。

| 指标 | 结果 |
|---|---:|
| 行数 | 43,655 |
| CRS | `EPSG:4326` |
| 几何类型 | Polygon / MultiPolygon |
| 字段 | `省`, `市`, `县`, `乡`, `市_县`, `省_县` |
| invalid geometry | 0 |
| empty geometry | 0 |

与璧山图斑叠加后，主要 `admin9` 前缀能够稳定匹配到真实乡镇名称：

| `admin9` | 主匹配乡镇 | 图斑并集面积覆盖比例 |
|---|---|---:|
| `500227100` | 八塘镇 | 0.9861 |
| `500227101` | 七塘镇 | 0.9725 |
| `500227102` | 大路街道 | 0.9873 |

因此，乡镇级行政边界不再需要合成。仍需注意：边界处会出现相邻区县或相邻乡镇的极小面积叠加，生成脚本会保留这些对象并写入 `overlap_ratio_to_parcels`，用于解释边界效应，而不是把它们误判为主要行政覆盖。

### 12.3 默认包当前结果

`twm_bishan_demo` QA gate 为 `pass`，无 blocker。核心规模：

| 对象 | 数量 |
|---|---:|
| `parcel_current` | 4,900 |
| `admin_units` | 5 |
| `synthetic_annual_change` | 78 |
| `synthetic_projects` | 60 |
| `rule_evaluation` | 240 |
| `multimodal_evidence_index` | 166 |
| `raster_observation` evidence | 2 |

默认包新增两类栅格：

| 栅格 | 尺寸 | CRS | 有效像元 | 均值 |
|---|---:|---|---:|---:|
| `synthetic_ndvi_2026.tif` | 256 x 256 | `EPSG:32648` | 27,078 | 0.628087 |
| `synthetic_change_intensity_2026.tif` | 256 x 256 | `EPSG:32648` | 27,078 | 0.060754 |

保留 warning：`parcel_current` 中 59 个源图斑 `TBMJ` 与几何面积偏差超过 10%，这些要素保留为源数据质量风险样本，并通过 `qa_use_for_rules=false` 排除出规则输入。

默认包 `admin_units.geojson` 主覆盖为八塘镇，占演示图斑并集面积约 98.61%；七塘镇、盐井街道、澄江镇、旧县镇仅为边界小面积叠加。

### 12.4 多行政包当前结果

`twm_bishan_multi_admin_eval` QA gate 为 `pass`，无 blocker。核心规模：

| 对象 | 数量 |
|---|---:|
| `parcel_current` | 21,218 |
| `admin9` 覆盖 | 3 |
| `admin_units` | 11 |
| `synthetic_annual_change` | 266 |
| `synthetic_projects` | 90 |
| `project_planning_rel` | 264 |
| `project_rs_tile_rel` | 93 |
| `multimodal_evidence_index` | 217 |
| `raster_observation` evidence | 2 |

行政覆盖：

| `admin9` | 图斑数 |
|---|---:|
| `500227100` | 4,900 |
| `500227101` | 5,443 |
| `500227102` | 10,875 |

多行政包新增两类栅格：

| 栅格 | 尺寸 | CRS | 有效像元 | 均值 |
|---|---:|---|---:|---:|
| `synthetic_ndvi_2026.tif` | 384 x 384 | `EPSG:32648` | 64,753 | 0.583423 |
| `synthetic_change_intensity_2026.tif` | 384 x 384 | `EPSG:32648` | 64,753 | 0.058148 |

保留 warning：`parcel_current` 中 121 个源图斑 `TBMJ` 与几何面积偏差超过 10%，处理原则同默认包。

多行政包 `admin_units.geojson` 的主覆盖乡镇为大路街道、八塘镇、七塘镇，合计覆盖演示图斑并集面积约 99.58%；河边镇、璧城街道以及少量相邻区县乡镇为边界小面积叠加。

### 12.5 查看入口

| 数据包 | HTML 预览 | GeoPackage | QA 报告 |
|---|---|---|---|
| 默认包 | `data_agent/test_data/twm_bishan_demo/preview/index.html` | `data_agent/test_data/twm_bishan_demo/preview/twm_bishan_demo_layers.gpkg` | `data_agent/test_data/twm_bishan_demo/data_quality_report.md` |
| 多行政包 | `data_agent/test_data/twm_bishan_multi_admin_eval/preview/index.html` | `data_agent/test_data/twm_bishan_multi_admin_eval/preview/twm_bishan_multi_admin_eval_layers.gpkg` | `data_agent/test_data/twm_bishan_multi_admin_eval/data_quality_report.md` |

### 12.6 对最终目标的进一步对齐

本轮补强后，数据基础比 11.4 状态更接近“地理空间世界模型核心技术路线”的落地要求：

1. **空间底板更真实**：多行政包不再是单乡镇封闭样区，可验证跨乡镇统计、边界连通性、区域筛选和跨区项目关系。
2. **MMFE 不再只有索引**：遥感瓦片索引已关联实际 GeoTIFF 栅格文件，Agent 可以读取像元统计、CRS、范围和产品元数据。
3. **证据链更完整**：`multimodal_evidence_index.csv` 同时包含文本项目材料、遥感瓦片索引、栅格观测、规则评估和标准规则生命周期。
4. **质量门更严格**：QA 不只检查矢量几何，还检查行政覆盖、栅格存在性、有效像元和证据类型覆盖。
5. **复现性更强**：默认包和多行政包由同一生成脚本参数化生成，可稳定回归。

### 12.7 仍需后续补强的边界

当前数据基础依然是严谨的工程测试数据，不是生产落地数据：

- PBF、生态红线、用途分区、城镇开发边界仍为合成，生产必须替换为权威法定数据。
- 栅格像元为矢量语义派生的 synthetic fixture，不是真实 Sentinel/Gaofen/UAV 观测，也没有云检测、时相序列或传感器辐射定标。
- 多行政包覆盖 3 个相邻 `admin9`，但尚未覆盖全璧山或跨区县指标流转。
- 审批、执法、复核仍为合成流程记录，尚不能验证真实部门业务口径。
- 年度状态仍只有 2025/2026 两期，尚不能验证多年趋势、季节性变化和长期推演。

## 13. 2026-06-16 真实公开影像接入评估与初步落地

公开影像数据源可以替代当前 synthetic raster fixture 作为主 MMFE 影像证据，但不应删除 synthetic fixture。推荐策略是：真实影像优先，synthetic raster 作为离线测试和网络不可用时的 fallback。

### 13.1 当前样区与数据源可行性

两个样区范围很小，适合通过 STAC 在线检索 Sentinel-2 / Landsat / HLS 等公开影像后裁剪成本地 GeoTIFF：

| 数据包 | WGS84 范围 |
|---|---|
| 默认包 | `106.2483,29.7734,106.3675,29.8868` |
| 多行政包 | `106.1522,29.6675,106.3675,29.8868` |

已验证 Earth Search STAC 的 `sentinel-2-l2a` 可检索到真实 Sentinel-2 L2A COG。2025 年窗口内，两个样区均能找到 2025-08-03 的两景 Sentinel-2 L2A 瓦片，估算覆盖率 100%，平均云量约 0.0877%。

### 13.2 新增脚本

新增 `scripts/fetch_twm_real_imagery.py`：

| 能力 | 状态 |
|---|---|
| STAC 查询 | 已完成 |
| 按样区 bbox 选景 | 已完成 |
| Sentinel-2 COG 远程窗口读取 | 实验可用，但网络 IO 较慢 |
| 本地 reflectance stack 派生 RGB/NDVI | 已完成 |
| 更新 `multimodal_evidence_index.csv` | 已完成 |
| 更新 QA 真实影像产品一致性检查 | 已完成 |
| 更新预览页真实 RGB/NDVI 缩略图 | 已完成 |

常用命令：

```bash
PROJ_DATA=/Users/zhouning/miniconda3/envs/farmland-mpc/share/proj \
  .venv/bin/python scripts/fetch_twm_real_imagery.py \
  --data-dir data_agent/test_data/twm_bishan_demo \
  --datetime 2025-01-01/2025-12-31 \
  --cloud-cover-max 20 \
  --resolution-m 60 \
  --product-set core

PROJ_DATA=/Users/zhouning/miniconda3/envs/farmland-mpc/share/proj \
  .venv/bin/python scripts/fetch_twm_real_imagery.py \
  --data-dir data_agent/test_data/twm_bishan_demo \
  --refresh-local

PROJ_DATA=/Users/zhouning/miniconda3/envs/farmland-mpc/share/proj \
  .venv/bin/python scripts/fetch_twm_real_imagery.py \
  --data-dir data_agent/test_data/twm_bishan_multi_admin_eval \
  --datetime 2025-01-01/2025-12-31 \
  --cloud-cover-max 20 \
  --resolution-m 60 \
  --product-set core
```

### 13.3 已落地结果

默认包和多行政包均已生成真实 Sentinel-2 影像产品：

| 产品 | 路径 | 说明 |
|---|---|---|
| Reflectance stack | `real_imagery/sentinel2_l2a_reflectance_stack.tif` | Sentinel-2 L2A B02/B03/B04/B08 反射率栈，60m 工程验证分辨率 |
| RGB | `real_imagery/sentinel2_l2a_rgb.tif` | 从本地反射率栈百分位拉伸生成 |
| NDVI | `real_imagery/sentinel2_l2a_ndvi.tif` | 从本地反射率栈生成，已限制在 `[-1, 1]` |
| SCL | `real_imagery/sentinel2_l2a_scl.tif` | Sentinel-2 scene classification layer |
| Manifest | `real_imagery_manifest.json` | STAC 来源、选景、产品、处理历史 |

两个包当前 QA gate 均为 `pass`。真实影像选景信息：

| 指标 | 值 |
|---|---:|
| STAC endpoint | `https://earth-search.aws.element84.com/v1` |
| collection | `sentinel-2-l2a` |
| selected_date | `2025-08-03` |
| selected_items | `S2C_48RXU_20250803_0_L2A`, `S2C_48RXT_20250803_0_L2A` |
| coverage_ratio_estimate | 1.0 |
| avg_cloud_cover | 0.087723 |
| 默认包 target_grid | `EPSG:32648`, 60m, 197 x 214 |
| 多行政包 target_grid | `EPSG:32648`, 60m, 349 x 410 |

NDVI 修正后统计：

| 数据包 | valid_pixels | min | mean | max |
|---|---:|---:|---:|---:|
| 默认包 | 1,828 | -0.948030 | 0.774765 | 0.999818 |
| 多行政包 | 11,739 | -0.990590 | 0.645490 | 0.999984 |

真实影像已写入 `multimodal_evidence_index.csv`，证据类型为 `observed_remote_sensing`。默认包新增 4 条真实影像证据，多行政包也新增 4 条真实影像证据。预览页已生成 `real_sentinel2_rgb.png` 和 `real_sentinel2_ndvi.png`，可以在浏览器中快速检查云、阴影、地物纹理和指数分布。

### 13.4 与现实对齐程度提升

真实 Sentinel-2 影像引入后，MMFE 影像侧从“矢量语义派生的 synthetic pixel”提升为“真实观测源 + 明确 STAC lineage + 本地可读 GeoTIFF”。这对以下能力有实质提升：

1. 图斑状态解释：可基于 RGB/NDVI/SCL 辅助说明现状地表特征。
2. 多模态证据链：`multimodal_evidence_index.csv` 可同时引用文本、矢量、规则、synthetic raster 和 observed remote sensing。
3. 数据真实性分级：真实影像产品 `synthetic=false`，synthetic raster 仍保留为 fallback。
4. 后续时间序列：同一脚本可以扩展到多日期窗口，形成季节性或年度变化证据。

### 13.5 当前限制与后续优化

当前真实影像接入仍是工程验证版本：

- 远程 Sentinel-2 COG 通过 rasterio/GDAL 读取较慢，尤其是 10m/20m 多波段；当前默认落地为 60m core 产品，优先证明链路可行。
- Sentinel-2 10m/20m 对小图斑边界和执法级精度不足，不能替代高分/商业影像或现场核查。
- 当前只接入单日 Sentinel-2 L2A core 波段，尚未形成多日期时间序列、SWIR 指数产品和季节性对比。
- NDVI 有效像元受 SCL 掩膜影响，统计适合工程验证，不应直接作为生产结论。
- 合成 raster fixture 仍应保留，用于离线回归测试和网络不可用时的稳定 fallback。

后续优化优先级：

1. 增加 `--assets` 分批下载能力，先稳定下载 RGB/NIR/SCL，再逐步补 SWIR 和 `full` 产品。
2. 尝试 Copernicus Data Space、AWS CLI `/vsis3/`、或预签名下载方式，减少远程 COG Range 请求延迟。
3. 增加多日期窗口，形成春、夏、秋或年度变化证据。
4. 增加 parcel-level zonal stats，把 NDVI/SCL 汇总到图斑或项目证据表。
5. 增加高分、无人机或商业影像接入适配层，用于执法级或项目边界级验证。

## 14. 2026-06-16 自然资源“一张图”标准材料接入评估

已解压并分析 `/Users/zhouning/Downloads/自然资源一张图数据库标准1128 (2).zip`。详细评估见：

`docs/superpowers/specs/2026-06-16-twm-natural-resource-one-map-standard-assessment.md`

### 14.1 关键结论

该标准包应作为 TWM 数据标准契约来源，而不只是背景参考材料。它覆盖了统一调查监测、统一规划、底线安全、用途管制、执法督察和元数据分册，可直接支撑 TWM 的角色字段契约、字段别名、值域、质量规则和空间政策规则候选派生。

已确认的核心标准表包括：

| TWM 角色 | 标准表/图层 | 来源分册 |
|---|---|---|
| `parcel_current` | `DLTB` 地类图斑 | 统一调查监测 |
| `pbf` | `YJJBNT` / `YJJBNTTB` | 统一规划 / 底线安全 |
| `eco_redline` | `STBHHX` | 统一调查监测 / 统一规划 |
| `urban_boundary` | `CZKFBJ` | 统一调查监测 / 统一规划 |
| `project` / `approval` | `XS_XMKJFW`、`ZZ_NYDZYFW`、`ZZ_TDZSFW` 等 | 用途管制 |
| `enforcement` | `WFDK`、`YGXZJSYDTB`、`YGYSXZJSYDTB` | 执法督察 |
| `metadata` | `meta_VectorData`、`meta_NormalData` | 元数据 |

### 14.2 对当前测试包的影响

该小节记录的是标准材料刚接入时的差距判断。后续第 15 节已经完成对 `twm_bishan_demo` 和
`twm_bishan_multi_admin_eval` 的标准字段补齐，因此下列差距保留为历史评估依据，而不是当前状态：

- `parcel_current` 已有 `BSM/YSDM/DLBM/DLMC/QSDWDM/QSDWMC/ZLDWDM/ZLDWMC/TBMJ`，但缺 `TBBH/QSXZ/TBDLMJ/SJNF/MSSM` 等标准必填字段。
- `synthetic_pbf` 尚未镜像 `YJJBNT/YJJBNTTB` 字段，如 `YJJBNTTBBH/YJJBNTTBMJ/YJJBNTMJ/BHKSSJ/WDGD`。
- `synthetic_eco_redline` 尚未镜像 `STBHHX` 字段，如 `XJXZQDM/LHLX/MJ` 或 `LXDM/QYMJ/SLSJ/GKCS`。
- `synthetic_urban_boundary` 与 `synthetic_planning_zones` 尚未镜像 `CZKFBJ/GHFQDM/GHFQMC/MJ`。
- `synthetic_projects` 与 `approval_records` 尚未镜像用途管制字段，如 `XMDM/DZJGH/AJBH/XZQDM/XMMC`。
- `enforcement_events` 尚未镜像执法督察字段，如 `WFXWZJ/WFDKXH/YGTBZJ/JCSDQ/JCSDH/JCMJ`。

### 14.3 可进一步利用的样例数据

压缩包中的村规划样例数据值得纳入下一轮数据基础：

| 样例图层 | 可映射 TWM 角色 | 价值 |
|---|---|---|
| `JQDLTB.shp` | `parcel_current` | 标准结构更接近规划数据库的基期地类图斑 |
| `TDGHDL.shp` | `planning_zone` / `planned_land_use` | 真实规划地类字段，可用于规划一致性 |
| `JSYDGZQ.shp` | `use_control_zone` / `urban_boundary` | 建设用地管制区 |
| `STBHHX.shp` | `eco_redline` | 生态保护红线样例 |
| `YBD.shp`、`EJYSLD.shp`、`LSWH.shp` | `sensitive_area` | 生态/历史文化/林地约束 |

该建议已在第 16 节落地为 `data_agent/test_data/twm_one_map_village_standard_sample/`，用于验证 TWM 是否能识别真实标准字段、构建 `S_t`、执行标准 QA 和生成证据链。

### 14.4 下一轮数据补强方向

下一轮数据基础工作应从“继续完善合成数据内容”转为“标准契约对齐”：

1. 新建结构化标准契约文件，覆盖 `DLTB`、`YJJBNT/YJJBNTTB`、`STBHHX`、`CZKFBJ`、用途管制项目范围、执法督察和元数据。
2. 将契约导入标准平台，派生 `to_semantic_hint`、`to_value_semantics`、`to_qc_rule`、`to_data_model` 和后续 `to_spatial_policy_rule`。
3. 为现有 synthetic 替身图层增加标准字段镜像，保留原工程字段作为内部辅助字段。
4. 利用村规划样例数据构建标准结构回归测试包，验证真实标准字段进入 TWM 后无需改核心逻辑。

## 15. 2026-06-16 自然资源“一张图”标准契约补强完成状态

已完成第一轮标准契约对齐改造。当前 TWM 数据基础不再只是“工程字段可跑”，而是具备了面向自然资源“一张图”标准的角色契约、字段镜像和 QA gate。

### 15.1 新增标准契约资产

新增全局标准契约：

```text
data_agent/test_data/twm_standards/
  one_map_role_contracts.zh.json
  one_map_field_aliases.zh.json
  one_map_value_domains.zh.json
```

每个数据包内也同步复制：

```text
standards/one_map_role_contracts.zh.json
standards/one_map_field_aliases.zh.json
standards/one_map_value_domains.zh.json
```

这使数据包可被独立 QA，不依赖外部说明文档。

### 15.2 当前标准字段覆盖情况

| TWM 角色 | 数据文件 | 标准字段覆盖 |
|---|---|---|
| `parcel_current` | `parcel_current.geojson` | `DLTB` 核心必填 14/14 |
| `pbf` | `synthetic_pbf.geojson` | `YJJBNTTB/YJJBNT` 核心必填 19/19 |
| `eco_redline` | `synthetic_eco_redline.geojson` | `STBHHX` 兼容必填 12/12 |
| `urban_boundary` | `synthetic_urban_boundary.geojson` | `CZKFBJ` 兼容必填 11/11 |
| `planning_zone` | `synthetic_planning_zones.geojson` | 规划分区必填 7/7 |
| `project` | `synthetic_projects.geojson` | 用途管制项目范围必填 8/8 |
| `approval` | `tables/approval_records.csv` | 农转用/征收审批必填 8/8 |
| `enforcement` | `tables/enforcement_events.csv` | 执法督察必填 15/15 |
| `metadata_vector` | `tables/metadata_vector.csv` | `meta_VectorData` 核心必填 12/12 |

### 15.3 QA 结果

最终验证命令：

```bash
PROJ_DATA=/Users/zhouning/miniconda3/envs/farmland-mpc/share/proj \
  .venv/bin/python scripts/qa_twm_demo_data.py --data-dir data_agent/test_data/twm_bishan_demo

PROJ_DATA=/Users/zhouning/miniconda3/envs/farmland-mpc/share/proj \
  .venv/bin/python scripts/qa_twm_demo_data.py --data-dir data_agent/test_data/twm_bishan_multi_admin_eval
```

结果：

| 数据包 | Gate | Blockers | Warnings |
|---|---|---:|---|
| `twm_bishan_demo` | pass | 0 | `parcel_current` 59 个要素面积差异超过 10% |
| `twm_bishan_multi_admin_eval` | pass | 0 | `parcel_current` 121 个要素面积差异超过 10% |

标准契约检查没有 blocker。真实 Sentinel-2 影像证据已重新注册到 `multimodal_evidence_index.csv`，两个包均包含 4 条 `observed_remote_sensing` 证据。

### 15.4 当前数据基础判断

当前数据基础已经可以支撑下一阶段 TWM 开发中的以下工作：

1. 按角色契约进行数据绑定，而不是按演示文件名绑定；
2. 按自然资源“一张图”字段结构执行基础 QA；
3. 在 synthetic authority-like 图层上验证 PBF、生态红线、规划区、项目审批、执法督察和元数据链路；
4. 在真实 Sentinel-2 观测影像与合成矢量/表格之间验证 MMFE 证据索引；
5. 在未来真实权威数据环境中，用同一套角色契约替换当前合成图层。

已在后续工作中完成的补强：

1. JSON 契约已导入 GIS Data Agent 标准平台，形成 `NR_ONE_MAP_TWM_CORE_2026 / 2026-06-16-draft` released 版本；
2. 标准平台已派生 `agent_semantic_hints` 174 条、值域语义 29 条、`agent_quality_rules` 135 条、`agent_defect_code_bindings` 135 条和 1 个 `std_data_model_snapshot`；
3. 两个 TWM 数据包已补齐推荐字段壳，导入计划中的 174 个 `bound_table.bound_column` 在两个数据包中均可找到，缺失绑定为 0。

仍需继续补强：

1. 增加更严格的值域校验，特别是 `DLBM` 对接 `GB/T 21010-2017` 全量值域；
2. 面向真实权威数据接入场景补充字段映射 UI/Agent 工作流，而不只依赖生成脚本；
3. 让 TWM 运行态从标准平台 released 版本拉取 semantic hints、quality rules 和 data model，而不是直接读测试包内 JSON；
4. 增加真实权威数据替换演练脚本，在没有真实权威数据时先用同构 fixture 验证替换流程。

## 16. 2026-06-16 村规划标准结构样例包完成状态

已基于 `/Users/zhouning/Downloads/自然资源一张图数据库标准1128 (2).zip` 中的和平村、斑竹村村规划汇交样例，生成第三个 TWM 数据基线包：

```text
data_agent/test_data/twm_one_map_village_standard_sample/
```

该包不替代两个璧山主数据包。它的定位是 **标准结构兼容性回归包**：验证真实村规划汇交结构中的 `JQDLTB`、`TDGHDL`、`JSYDGZQ`、`STBHHX` 和空间管制要素能否进入同一套 TWM 角色契约、QA、关系表和证据链。

### 16.1 生成脚本

```bash
PROJ_DATA=/Users/zhouning/miniconda3/envs/farmland-mpc/share/proj \
  .venv/bin/python scripts/generate_twm_village_standard_sample.py
```

脚本会保留源样例字段，并补齐 TWM 标准契约必填字段。来源样例层标记为 `source_sample=true`；缺失的权威角色替身标记为 `synthetic=true`、`not_for_production=true`。

### 16.2 当前规模

| 对象 | 数量 | 来源/定位 |
|---|---:|---|
| `parcel_current` | 2,217 | 和平村、斑竹村 `JQDLTB` |
| `synthetic_pbf` | 274 | 由现状耕地图斑派生的契约测试替身 |
| `synthetic_eco_redline` | 1 | 和平村 `STBHHX` |
| `admin_units` | 2 | 两村 `GHFW` |
| `synthetic_annual_change` | 260 | `TDGHDL` 现状地类到规划地类差异 |
| `synthetic_projects` | 36 | 由规划差异派生的项目范围替身 |
| `synthetic_planning_zones` | 2,457 | 和平村、斑竹村 `TDGHDL` |
| `synthetic_urban_boundary` | 194 | 两村 `JSYDGZQ` |
| `synthetic_remote_sensing_tiles` | 12 | 样例 AOI 格网化遥感索引 |
| `sensitive_areas` | 20 | `YBD/EJYSLD/LSWH/STHFQ` 等空间管制要素 |

治理与证据表：

| 表 | 行数 |
|---|---:|
| `rule_evaluation` | 108 |
| `approval_records` | 36 |
| `enforcement_events` | 24 |
| `review_tasks` | 24 |
| `state_snapshots` | 11 |
| `standard_field_catalog` | 130 |
| `metadata_vector` | 10 |
| `multimodal_evidence_index` | 51 |

### 16.3 QA 结果

验证命令：

```bash
PROJ_DATA=/Users/zhouning/miniconda3/envs/farmland-mpc/share/proj \
  .venv/bin/python scripts/qa_twm_demo_data.py \
  --data-dir data_agent/test_data/twm_one_map_village_standard_sample \
  --project-crs EPSG:4523
```

结果：

| 数据包 | Gate | Blockers | Warnings |
|---|---|---:|---|
| `twm_one_map_village_standard_sample` | pass | 0 | 5 个现状图斑面积差异超过 10%；未接入真实影像，使用 synthetic raster fallback |

标准契约覆盖：

| 角色 | 必填字段覆盖 |
|---|---:|
| `parcel_current` | 14/14 |
| `pbf` | 19/19 |
| `eco_redline` | 12/12 |
| `urban_boundary` | 11/11 |
| `planning_zone` | 7/7 |
| `project` | 8/8 |
| `approval` | 8/8 |
| `enforcement` | 15/15 |
| `metadata_vector` | 12/12 |

### 16.4 查看入口

| 入口 | 路径 |
|---|---|
| HTML 预览 | `data_agent/test_data/twm_one_map_village_standard_sample/preview/index.html` |
| GeoPackage | `data_agent/test_data/twm_one_map_village_standard_sample/preview/twm_one_map_village_standard_sample_layers.gpkg` |
| QA 报告 | `data_agent/test_data/twm_one_map_village_standard_sample/data_quality_report.md` |
| 数据说明 | `data_agent/test_data/twm_one_map_village_standard_sample/README.md` |

### 16.5 三类数据包分工

| 数据包 | 主目标 | 是否含真实影像 | 是否侧重标准结构 |
|---|---|---|---|
| `twm_bishan_demo` | 快速开发、前端预览、端到端回归 | 是，Sentinel-2 L2A | 是 |
| `twm_bishan_multi_admin_eval` | 跨乡镇评测、边界项目、MMFE 压测 | 是，Sentinel-2 L2A | 是 |
| `twm_one_map_village_standard_sample` | 村规划汇交结构兼容性、标准字段回归 | 否，使用 synthetic raster fallback | 强 |

当前数据基础已经满足后续 TWM Phase 0-2 的开发需要：可按角色契约绑定，可构建状态，可执行规则 QA，可生成多模态证据和复核链。仍需在真实权威数据环境中替换 PBF、生态红线、规划分区、审批、执法和高精度影像后，才能进入生产结论验证。

## 17. 2026-06-16 多目标优化与方案比选数据基础补强

根据原始技术路线说明，TWM 的核心不是单纯的数据质检、规则筛查或证据索引，而是：

```text
可计算空间状态 S_t
+ 法定硬约束
+ 动态推演
+ 多目标优化
+ 方案比选
+ 可解释审计
```

此前的数据包已经较好覆盖了 `S_t`、标准契约、MMFE、规则命中、审批/执法/复核和影像证据，但对“多目标优化”和“方案比选”的数据支撑还偏弱。本轮新增 `scripts/generate_twm_optimization_dataset.py`，为三个 TWM 数据包补齐优化层工程夹具。

### 17.1 新增优化目录

三个数据包均新增：

```text
optimization/
  objective_catalog.csv
  action_space.geojson
  constraint_masks.geojson
  scenario_candidates.csv
  scenario_feasibility.csv
  scenario_project_membership.csv
  scenario_metrics.csv
  scenario_constraint_violations.csv
  pareto_summary.json
  README.md
```

这些文件的定位是 **TWM 优化层工程契约**，不是生产级优化结论。它们用于验证后续优化器、API、Agent 和前端是否能围绕固定数据结构完成：

1. 法定硬约束先过滤；
2. 在合法可行空间内做多目标指标计算；
3. 输出可比较候选方案；
4. 保留被阻断方案作为压力测试和人工复核样本；
5. 将优化结果写入证据链和审计链。

### 17.2 优化目标目录

`objective_catalog.csv` 当前包含 13 个目标：

| 目标 | 方向 | 类型 |
|---|---|---|
| 永久基本农田占用最小化 | min | hard constraint |
| 生态保护红线触碰最小化 | min | hard constraint |
| 用途管制冲突最小化 | min | planning consistency |
| 耕地损失最小化 | min | resource protection |
| 耕地补充最大化 | max | resource protection |
| 建设承载能力最大化 | max | development |
| 空间紧凑性最大化 | max | spatial form |
| 调整成本最小化 | min | cost |
| 行政区负担均衡 | min | fairness |
| 方案稳健性最大化 | max | uncertainty |
| 人工复核负荷最小化 | min | governance |
| 坡度适宜性改善最大化 | max | dynamic projection |
| 空间连片度提升最大化 | max | dynamic projection |

这组目标覆盖了 TWM 方案比选最小可行骨架：硬约束、资源保护、发展承载、空间形态、治理成本、公平性、稳健性和动态推演信号。

### 17.3 硬约束优先过滤

新增 `scenario_feasibility.csv`，显式记录每个方案的硬约束状态：

- `legal_feasible_space`：进入合法可行空间，可参与 Pareto 主排序；
- `stress_test_only`：触碰永久基本农田或生态红线，只保留为压力测试、证据链和人工复核样本；
- `excluded_from_recommendation=true`：不能作为可推荐方案输出。

`pareto_summary.json` 的主排序方法为：

```text
hard_constraint_filter_then_normalized_weighted_score_and_non_dominated_sorting
```

这与技术路线中的“先法定硬约束，再在合法可行空间内做 constrained RL / multi-objective optimization”保持一致。压力测试方案不会混入可推荐方案排名。

### 17.4 三个数据包当前优化结果

| 数据包 | 目标数 | 方案数 | 候选动作 | 指标行 | 合法可行方案 | 硬约束阻断方案 | QA |
|---|---:|---:|---:|---:|---:|---:|---|
| `twm_bishan_demo` | 13 | 7 | 60 | 91 | 2 | 5 | pass |
| `twm_bishan_multi_admin_eval` | 13 | 7 | 90 | 91 | 3 | 4 | pass |
| `twm_one_map_village_standard_sample` | 13 | 7 | 36 | 91 | 1 | 6 | pass |

当前合法可行方案数量较少是有意保留的工程测试结果：一方面验证系统能在硬约束下排除风险方案，另一方面保留足够的阻断样本来测试审计、复核和解释链。

### 17.5 QA 增强

`scripts/qa_twm_demo_data.py` 已新增优化层质量检查：

1. 检查 `optimization/` 必需文件是否存在；
2. 检查 `objective_catalog.csv` 是否包含 PBF、生态红线两个硬约束目标；
3. 检查 `scenario_feasibility.csv` 是否覆盖所有方案；
4. 检查 `scenario_metrics.csv` 行数是否等于 `objective_count * scenario_count`；
5. 检查 `pareto_summary.json` 主排名是否只包含 `legal_feasible_space` 方案；
6. 检查 `multimodal_evidence_index.csv` 是否包含优化方案集和 Pareto 摘要证据。

最新 QA 结果：

| 数据包 | Gate | Blockers | Warnings |
|---|---|---:|---|
| `twm_bishan_demo` | pass | 0 | 59 个现状图斑面积差异超过 10% |
| `twm_bishan_multi_admin_eval` | pass | 0 | 121 个现状图斑面积差异超过 10% |
| `twm_one_map_village_standard_sample` | pass | 0 | 5 个面积差异 warning；未接入真实影像 |

优化层本身无 blocker、无 warning。

### 17.6 中文可理解性

三个数据包的 `data_dictionary.zh.json` 已补充优化层中文说明，包括：

- `optimization`：多目标优化方案比选数据；
- `objective_id`：目标编号；
- `optimization_scope`：优化比较范围；
- `hard_constraint_status`：硬约束状态；
- `weighted_score`：加权得分；
- `optimization/objective_catalog.csv`：优化目标目录；
- `optimization/scenario_feasibility.csv`：方案硬约束可行性；
- `optimization/pareto_summary.json`：Pareto 比选摘要。

后续查看数据时，不需要只依赖英文字段名理解优化层含义。

### 17.7 与原始技术路线的对齐判断

| 原始路线要求 | 当前数据基础状态 | 判断 |
|---|---|---|
| `S_t = 对象 + 关系 + 属性 + 规则 + 时间版本` | 三个数据包均有图斑、关系表、属性、规则生命周期、状态快照 | 已满足工程开发 |
| 法定硬约束 | PBF、生态红线、规划、城镇边界均有 authority-like fixture，并显式标记 synthetic | 已满足工程开发，生产需替换权威数据 |
| 动态推演 | `synthetic_annual_change`、`world_model_summary`、WorldModel 参考方案、坡度/连片度指标 | 初步满足 |
| 多目标优化 | 13 个目标、动作空间、方案指标、权重、归一化和 Pareto 摘要 | 初步满足 |
| 方案比选 | 基线、WorldModel 参考推演、低风险、均衡、建设优先、生态优先、压力测试方案 | 初步满足 |
| 可解释审计 | 证据索引、规则结果、审批/执法/复核、优化证据、可行性原因 | 初步满足 |
| 真实生产结论 | 缺权威 PBF、生态红线、规划、审批、执法和真实年度变更链 | 不满足，需真实环境替换 |

### 17.8 当前复盘结论

截至本轮补强，数据基础已经从“状态/规则/证据链可开发”推进到“动态推演 + 多目标方案比选可开发”。也就是说，后续 TWM 主体开发不再只能验证数据标准、MMFE 和规则命中，还可以围绕 TWM 的核心决策闭环推进：

```text
输入数据角色绑定
-> 构建 S_t
-> 执行硬约束过滤
-> 读取动态推演/WorldModel 候选
-> 计算多目标指标
-> 生成合法可行空间 Pareto 比选
-> 输出风险解释、复核任务和审计证据
```

仍需坚持既定原则：当前数据是生产数据适配能力测试集。除真实 Sentinel-2 影像和可用乡镇边界外，PBF、生态红线、规划、审批、执法、年度变更等均不能被解释为真实权威业务数据。未来进入真实权威数据环境时，应通过角色契约、字段映射、标准平台规则和 QA 门替换输入资产，而不是改写 TWM 核心逻辑。
