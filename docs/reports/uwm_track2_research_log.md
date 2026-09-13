# UWM Track 2 Research Log

起始日期：2026-07-04

## 1. 研究主线

目标：

```text
构建 Urban World Model，并用它研究城市宜居性、气候健康风险和空间公平。
```

当前业务场景：

```text
面向气候健康与空间公平的城市宜居性世界模型：
以重庆中心城区为核心，评估规划干预对热暴露、空气污染、
服务可达性和社会公平的动态影响。
```

## 2. AI 协作记录

### 2026-07-04

- 明确 GWM / TWM / UWM 关系：
  - GWM 是总理论框架；
  - TWM 是自然资源和国土空间治理方向实例；
  - UWM 是城市科学和城市治理方向实例；
  - 耕地保护是 TWM 场景；
  - 城市宜居性分析是 UWM 场景。
- 明确 UWM 不等于传统宜居性评价工具，而是 action-conditioned、evidence-gated urban world model。
- 固化 renderer / simulator / planner 理论和架构边界。
- 确定第一批实现不做前端 tab，不做模拟器 facade，先做契约、manifest 和 MMFE state-input 骨架。

## 3. 数据发现记录

### 已确认的本地或项目内资产

- 规划院样例：
  - 重庆 DEM；
  - 重庆 CLCD；
  - OSM roads；
  - 中心城区建筑与楼层；
  - 高德 POI；
  - 百度 AOI；
  - 区县人口；
  - 通勤和 OD 线索。
- Paper6：
  - 重庆 UHI；
  - SCCA；
  - EPA Green Book policy-structure benchmark；
  - CountyData 社会资本和健康案例。
- Paper58：
  - AlphaEarth / GeoFM state prior；
  - LAS / FLUS hybrid allocation evidence。

### 待补公开数据

- ERA5 气象；
- CAMS / MAIAC / MERRA-2 / OpenAQ 空气污染代理；
- Sentinel / Landsat / MODIS 遥感补充；
- WorldPop / GHSL 人口代理；
- OSM 或公开交通网络补充。

### 2026-07-04 公开数据下载与本地数据补充记录

- Open-Meteo：
  - 已真实下载重庆中心点 current weather / current air-quality payload；
  - 本地路径：`data/uwm_public_proxy/chongqing_central/openmeteo_current/`；
  - 用途边界：live environmental proxy 和 smoke/live context；不能替代 ERA5/CAMS 历史栅格或站点校准 holdout。
- OSM Overpass：
  - 已通过 Overpass 下载重庆中心 bbox 的 amenity 样本 200 个；
  - 本地路径：`data/uwm_public_proxy/chongqing_central/osm_services/`；
  - 用途边界：公共服务可达性公开替代源的原始样本；需分类、去重、ODbL attribution 和 completeness 评估。
- OpenAQ：
  - 已尝试 v3 locations API；
  - 返回 Unauthorized，需要 `X-API-Key`；
  - 本地失败记录：`data/uwm_public_proxy/chongqing_central/openaq/snapshot_manifest.json`；
  - 用途边界：该失败记录不能用于任何空气污染观测 claim；
  - 2026-07-05 已用运行时 key 重新下载 OpenAQ 站点观测代理，见第 10 节。
- WorldPop：
  - 已下载中国人口产品目录和 REST index；
  - 2020 中国 100m GeoTIFF HEAD 探测约 4.98GB，当前未直接下载全国大文件；
  - 用途边界：目录可复现，后续需选择裁剪/更低分辨率产品或云端裁剪流程。
- GHSL：
  - 已下载 GHSL R2023A 2020 人口和建成区 4326 30ss 瓦片，覆盖重庆全市范围；
  - 瓦片：R6/R7 与 C29/C30，共 8 个 zip；
  - 本地路径：`data/uwm_public_proxy/chongqing_central/ghsl/tiles/`；
  - 全部通过 `python3 -m zipfile -t` 校验；
  - 用途边界：2026-07-04 时为 raw public proxy available；2026-07-05 已生成行政单元分区统计和 MMFE state input，但仍不能替代真实观测 holdout。
- 行政单元：
  - 已读取 `/Users/zhouning/Downloads/shp/xiangzhen.shp`；
  - 原始数据为全国乡镇/街道级多边形，EPSG:4326，43,655 个要素；
  - 已提取重庆子集 1,017 个乡镇/街道要素，38 个区县，963 个 Polygon 和 54 个 MultiPolygon；
  - 本地路径：`data/uwm_public_proxy/chongqing_central/admin_units/`；
  - 用途边界：UWM 治理单元、空间聚合单元、政策干预单元和公平性评估单元；但来源许可、官方年代和历史区县名需要核验，总 claim ceiling 降为 fragile。

## 4. 实验登记

| 日期 | 实验 | 输入 | 输出 | 证据等级 | 备注 |
| --- | --- | --- | --- | --- | --- |
| 2026-07-04 | UWM foundation contract tests | UWM test fixtures | 9 focused tests | contract_only | 首批契约测试 |
| 2026-07-04 | UWM renderer and traditional baseline tests | MMFE-UWM state-input fixture; static indicator fixture | 4 focused tests | contract_only | Renderer 产出 `UwmCanonicalObservation.v1`；baseline 明确为静态指标对照，不声明经验超越 |
| 2026-07-04 | UWM action-conditioned simulator tests | `UwmCanonicalObservation.v1` fixture; greening intervention; invalid observation fixture | 3 focused tests | known_effect_rollout | `mechanistic_urban_livability_v0` 产出 `UwmRolloutTrace.v1`；支持邻接溢出、证据等级和 `not_for_claim` 降级 |
| 2026-07-04 | UWM dynamic advantage evaluation tests | Static livability baseline; UWM rollout; no-op negative control | 2 focused tests | controlled_known_effect | 证明 UWM 在受控动态任务上强于静态指标 baseline；明确 `empirical_superiority_claim = False` |
| 2026-07-04 | UWM evidence-gated planner tests | 多候选 `UwmRolloutTrace.v1`；公平、不确定性、证据等级约束 | 2 focused tests | planner_contract | Planner 只能消费 rollout trace；违规候选进入 `rejected_actions`；raw action 被拒绝 |
| 2026-07-04 | UWM planner advantage evaluation tests | UWM planner 推荐行动；传统静态启发式行动；known-effect rollout 集合 | 2 focused tests | controlled_known_effect | 证明 UWM planner 在受控候选集上降低 known-effect regret；明确 `empirical_superiority_claim = False` |

## 4.1 当前相对传统方法的证明状态

已完成的事实：

- 传统宜居性 baseline 已被显式编码为 `static_weighted_indicator_overlay`；
- baseline 标记为 `action_conditioned = False` 和 `dynamic_rollout = False`；
- UWM renderer 已能从 `mmfe.uwm_state_input.v1` 产出 `UwmCanonicalObservation.v1`；
- canonical observation 保留城市图结构、数据来源、合成/公开代理标记、claim boundary 和 renderer trace；
- `baseline_vs_uwm_capability_report` 已能指出 UWM 当前已有的契约能力和仍未完成的经验证明门槛。
- UWM simulator 已实现第一版 action-conditioned rollout：
  - 模块：`data_agent.uwm.simulator`；
  - 后端标识：`mechanistic_urban_livability_v0`；
  - 输入：`UwmCanonicalObservation.v1`、行动序列、情景；
  - 输出：`UwmRolloutTrace.v1`；
  - 行动类型覆盖：增绿、冷屋顶/建筑降温改造、交通减排、社区服务补足；
  - 动态机制覆盖：直接效应、邻接单元溢出、聚合宜居性增量、不确定性区间、证据等级。
- UWM evaluation 已实现第一版动态优势评估：
  - 模块：`data_agent.uwm.evaluation`；
  - 对照对象：传统静态加权指标 baseline；
  - 核心检查：dynamic action response、negative-control stability、simulator trace completeness；
  - 支持结论：`known_effect_dynamic_advantage_over_static_baseline` 或 `exploratory_known_effect_dynamic_advantage_only`；
  - 强制保留：`empirical_superiority_claim = False`。
- UWM planner 已实现第一版 evidence-gated plan package：
  - 模块：`data_agent.uwm.planner`；
  - 后端标识：`evidence_gated_rollout_planner_v0`；
  - 输入只能是 `UwmRolloutTrace.v1`；
  - 输出：`UwmPlanPackage.v1`；
  - 硬约束覆盖：最低宜居性收益、公平非负、不确定性上限、允许证据等级；
  - 输出必须包含 `recommended_actions`、`rejected_actions`、`risk_flags`、`data_gaps` 和 `planner_trace`。
- UWM planner advantage evaluation 已实现第一版规划层优势评估：
  - 对照对象：传统静态启发式行动；
  - UWM planner 决策依据：`simulator_rollout_trace`；
  - 传统启发式决策依据：`static_indicator_priority`；
  - 核心指标：`known_effect_regret_reduction`；
  - 支持结论：`known_effect_planner_advantage_over_static_heuristic`；
  - 强制保留：`empirical_superiority_claim = False`。
- 记录赛事二 Vibe Research 约束：
  - 初评截止：2026-07-22；
  - 初评反馈：2026-07-29；
  - 终评：2026-08-08 至 2026-08-09；
  - 初评材料：研究报告、数据说明与可复现代码、AI 协作过程记录；
  - 评审重点：问题重要性与新颖性、数据创造性、分析严谨性与可复现性、AI 协作有效性、城市科学启发价值。
- 记录 AI Urban Scientist 工具链映射：
  - Idea Generation -> UWM 研究问题与新颖性；
  - Data Seeking -> UWM data foundation manifest 和 MMFE 数据接入；
  - Paper Planning -> 世界模型评估设计与 claim boundary；
  - Paper Writing -> 初评报告、数据说明、复现代码说明、research log。
- 新增 Track 2 readiness matrix：
  - 模块：`data_agent.uwm.track2_submission`；
  - 文档：`docs/reports/uwm_track2_vibe_research_submission_readiness.md`；
  - 当前状态：数据说明、复现代码、AI 协作记录已具备；完整初评研究报告仍为 partial。
- 新增 UWM 数据基础角色级审计：
  - 模块：`data_agent.uwm.data_foundation`；
  - 文档：`docs/reports/uwm_data_foundation_coverage_audit.md`；
  - manifest 从 12 行扩展到 25 行；
  - 新增 public proxy planned rows：WorldPop population、GHSL population/built-up、OSM public service substitute；
  - 新增 OpenAQ air quality proxy 候选，并在 2026-07-05 通过运行时 key 下载站点观测代理；
  - 新增 Open-Meteo weather / air-quality live proxy 候选，并在 2026-07-05 增加历史点位代理快照；
  - 修正 CAMS row 的 `used_by` 字段，明确进入 `evidence_gate`。
- 新增 UWM public data acquisition plan：
  - 模块：`data_agent.uwm.data_acquisition`；
  - 官方源映射：ERA5、CAMS、OpenAQ、Open-Meteo、WorldPop、GHSL、OSM；
  - 明确 `no_silent_substitution = true`；
  - 修正旧判断：ERA5/CAMS 可通过本机已认证 GEE 获取；OpenAQ v3 需要运行时 `X-API-Key`，但 key 不得进入仓库；
  - 当前可尝试公共下载但需核查覆盖的数据：GEE ERA5/CAMS、OpenAQ、Open-Meteo、WorldPop、GHSL、OSM。
- 新增行政单元数据角色：
  - 模块：`data_agent.uwm.data_foundation`；
  - 角色：`administrative_units`；
  - 理论定位：城市治理/政策干预/空间公平评估的空间单元；
  - 已生成重庆乡镇/街道 GeoJSON 子集；
  - 修复一个误匹配问题：`equity_evaluation` 不能被当作 `population_vulnerability` 数据源。
- 新增 `raw_proxy_available` 覆盖等级：
  - 用于表示公开代理原始数据已真实下载，但尚未裁剪、校准或 MMFE 对齐；
  - 该等级比 `planned_proxy` 进展更实，但仍保留在 `empirical_superiority_blockers` 中。
- 接入 savemyself 项目中的实际环境 API 经验：
  - 已核对 `/Users/zhouning/savemyself/frontend/src/app/page.tsx`，当前真实前端路径使用 Open-Meteo forecast 和 Open-Meteo air-quality；
  - 已核对 `/Users/zhouning/savemyself/backend/app/environmental_service.py`，QWeather/OpenWeatherMap 是后端规划实现；
  - 已核对 `/Users/zhouning/savemyself/backend/app/main.py` 和 `config.py`，当前 `/logs` 主流程保存前端提交数据，没有接入 QWeather/OpenWeatherMap key 配置；
  - 本机已用重庆坐标 curl 验证 Open-Meteo forecast / air-quality API 可访问；
  - 本机已下载 Open-Meteo historical weather / air-quality 2024-07-01 至 2024-07-07 重庆中心点数据；
  - 新增标准化入口：`data_agent.uwm.openmeteo_proxy.build_openmeteo_environmental_proxy`；
  - 结论：Open-Meteo 可作为 UWM live environmental proxy，但不能替代 ERA5/CAMS 历史栅格或站点校准 holdout。
- 当前 UWM 核心数据角色覆盖：
  - `missing_required_roles = []`；
  - `claim_ceiling = fragile`；
  - `empirical_superiority_blockers = [air_pollution_exposure, meteorology]`。

尚未完成、不能提前宣称的事项：

- 已实现 OpenAQ 真实观测时间序列 temporal holdout，用于状态预测层比较；但尚未实现真实政策 outcome holdout；
- 尚未实现真实政策结果 holdout 上的 planner regret 验证；
- 尚未接入真实城市观测结果进行外部城市泛化验证；
- 尚未完成因果识别或 SCCA 证据门控对 rollout 结果的再验证；
- 尚未完成 Track 2 初评研究报告；
- 空气污染和气象已有 Open-Meteo 历史点位公开代理、GEE ERA5/CAMS 中心点代理、GEE 行政单元 representative-point 代理、OpenAQ 真实站点观测代理和 MMFE state input；但仍不是 2024 场景 station-calibrated observed holdout，也不是面状 zonal mean 或全城栅格校准结果；人口脆弱性已有 GHSL 行政单元公开代理分区统计和 MMFE state input，但不是本地人口普查或真实观测 holdout；
- 行政单元已有本地真实子集，但来源许可、官方年代和现代区县名称 crosswalk 尚未核验；
- ERA5 / CAMS 已通过本机 GEE 认证下载重庆中心点代理；若要支撑空间显式宜居性实证，还需扩展为城市栅格或行政单元聚合；
- 因此当前可以说 UWM 已经在受控 known-effect 动态任务和规划候选集上事实性强于传统静态评价/启发式方法，但不能说已经在真实观测 holdout 或实际政策收益上全面更强。

当前证明边界：

```text
已证明：
UWM 能对干预行动产生可追踪动态响应，而传统静态宜居性 baseline 的 action_response_delta = 0。
UWM 通过 no-op negative control，说明不是所有 action 都会被机械地判为改善。
UWM planner 只能消费 simulator rollout trace，并能在 known-effect 候选集上降低相对传统静态启发式的 regret。

未证明：
UWM 预测结果尚未与真实干预后的观测结果做 holdout 对比；
尚未证明跨城市泛化；
尚未证明规划器推荐的政策组合在真实治理目标上优于传统方法。
```

## 5. 失败记忆

当前硬约束：

- 不能只做静态宜居性指数。
- 不能把 UWM tab 做成普通 dashboard。
- 不能让 planner 绕过 simulator trace。
- 不能把 AlphaEarth 说成完整城市世界模型。
- 不能把 Paper6 EPA benchmark 说成重庆空气污染观测。
- 不能混淆真实、公开代理、受限预期、合成数据。
- 不能没有领域理论就开始宣传 UWM 结论。

## 6. 声明边界

UWM 输出分四类：

1. **Factual observation**
   - 来自真实数据和可追溯来源。

2. **Model prediction**
   - 来自 simulator rollout，必须附带 trace 和不确定性。

3. **Causal / counterfactual claim**
   - 必须通过 SCCA 或其它 evidence gate。

4. **Synthetic / exploratory scenario**
   - 只能用于流程验证、机制演示和压力测试。

当前 UWM v0 默认最高声明等级为：

```text
fragile
```

合成和半合成数据默认：

```text
exploratory_only
```

## 7. Track 2 初评推进计划

当前下一步按优先级排序：

1. **数据驱动验证**
   - Paper6 EPA Green Book benchmark -> UWM-Air known-effect / semi-synthetic validation；
   - 重庆 UHI + ERA5 + CAMS/MAIAC/MERRA-2/OpenAQ 空气污染代理 + WorldPop/GHSL 人口脆弱性 + POI 服务可达性 -> UWM-Livability MMFE state input；
   - simulator 参数从硬编码机制表推进到 data-calibrated mechanism table。
   - ERA5/CAMS 优先走本机 GEE 认证路径；OpenAQ 使用运行时 key；所有公开代理都必须明确 claim boundary。

2. **初评报告**
   - 文件目标：`docs/reports/uwm_track2_initial_report.md`；
   - 必须包含：研究问题、数据来源、方法、主要发现、城市科学意义；
   - 必须写清楚：当前已证明的是 known-effect dynamic / planner advantage，不是 observed holdout empirical superiority。

3. **可复现材料**
   - 保留测试命令；
   - 保留 manifest audit；
   - 保留 evaluation gate 输出；
   - 保留每次 claim 降级和失败测试记录。

## 8. 2026-07-05 GHSL 行政单元代理对齐

本次继续 UWM 数据基础补齐，目标是把已下载的 GHSL 2020 人口/建成区原始瓦片推进到可被 UWM/MMFE 消费的状态输入，而不是停留在“文件已下载”。

新增代码：

```text
data_agent/uwm/ghsl_alignment.py
data_agent/test_uwm_ghsl_alignment.py
```

新增真实数据产物：

```text
data/uwm_public_proxy/chongqing_central/ghsl_admin_alignment/ghsl_admin_alignment_manifest.json
data/uwm_public_proxy/chongqing_central/ghsl_admin_alignment/ghsl_admin_zonal_proxy.csv
data/uwm_public_proxy/chongqing_central/ghsl_admin_alignment/mmfe_uwm_state_input_ghsl_admin.json
data/uwm_public_proxy/chongqing_central/ghsl_admin_alignment/uwm_canonical_observation_ghsl_admin.json
```

对齐结果：

```text
admin_feature_count = 1017
population_nonzero_units = 1013
built_surface_nonzero_units = 1011
population_tiles = 4
built_surface_tiles = 4
alignment_status = proxy_zonal_stats_available
mmfe_state_input_valid = true
canonical_observation_valid = true
empirical_superiority_claim = false
```

失败与修复记录：

```text
真实数据第一次运行失败：部分行政区几何只触碰 GHSL 瓦片边界，shapely.intersects 判定相交，但 rasterio window 为空，抛出 WindowError。
处理方式：先增加回归测试 test_align_ghsl_tiles_to_admin_units_skips_admin_units_that_only_touch_tile_edge，再修复 _sum_layer_for_geometry 使空 window 被跳过。
```

声明边界：

```text
GHSL 行政单元分区统计现在可以作为 population_vulnerability / urban_form / remote_sensing_state 的公开代理输入。
它不能替代重庆本地人口普查、楼栋权威数据、空气污染观测或政策结果 holdout。
因此 population_vulnerability 不再是当前数据基础补齐 blocker，但 observed holdout empirical superiority 仍被 air_pollution_exposure 和 meteorology 阻塞。
```

## 9. 2026-07-05 Open-Meteo 历史环境代理下载与证据门控

本次继续补齐 UWM 环境数据基础，目标是把空气污染和气象从纯 planned proxy 推进到可复现的历史点位代理状态输入，同时防止把点位代理误判为 observed holdout。

新增代码：

```text
data_agent/uwm/openmeteo_history.py
data_agent/test_uwm_openmeteo_history.py
```

新增真实数据产物：

```text
data/uwm_public_proxy/chongqing_central/openmeteo_history_2024_07_01_07/openmeteo_historical_weather_raw.json
data/uwm_public_proxy/chongqing_central/openmeteo_history_2024_07_01_07/openmeteo_historical_air_quality_raw.json
data/uwm_public_proxy/chongqing_central/openmeteo_history_2024_07_01_07/openmeteo_historical_environmental_proxy.json
data/uwm_public_proxy/chongqing_central/openmeteo_history_2024_07_01_07/snapshot_manifest.json
data/uwm_public_proxy/chongqing_central/openmeteo_history_2024_07_01_07/mmfe_uwm_state_input_openmeteo_history.json
data/uwm_public_proxy/chongqing_central/openmeteo_history_2024_07_01_07/uwm_canonical_observation_openmeteo_history.json
```

下载结果：

```text
time_range = 2024-07-01_to_2024-07-07
weather_hourly_records = 168
weather_daily_records = 7
air_quality_hourly_records = 168
meteorology_roles_in_state_input = 2
air_pollution_roles_in_state_input = 1
mmfe_state_input_valid = true
canonical_observation_valid = true
empirical_superiority_claim = false
```

同时修正数据基础审计逻辑：

```text
available public_proxy 不再自动解除 empirical superiority blocker。
对 air_pollution_exposure / meteorology，只有 quality_status 或 lineage 明确包含 holdout_ready / station_calibrated_holdout / observed_holdout / empirical_ready，才允许解除 observed empirical superiority blocker。
Open-Meteo 历史点位代理的 quality_status = point_history_proxy_not_holdout，因此覆盖等级为 proxy_available，但仍保留在 empirical_superiority_blockers 中。
```

Renderer 修正：

```text
renderer 不再因为 manifest 里存在无关 exploratory_only 行，就把当前 observation 全局降级。
claim boundary 现在只根据当前 observation 实际消费的 role bindings 和 manifest 是否有效来派生。
renderer 同时对重复 public_proxy/synthetic flags 去重，避免同一数据源多角色绑定导致提交材料噪声。
```

本轮已纠正的数据下载判断：

```text
ERA5: 可通过本机已认证 GEE 访问 ECMWF/ERA5/HOURLY，已下载 2024-07-01 至 2024-07-07 重庆中心点 168 条记录。
CAMS: 可通过本机已认证 GEE 访问 ECMWF/CAMS/NRT，已下载 2024-07-01 至 2024-07-07 重庆中心点 574 条记录。
OpenAQ v3: 已通过运行时 X-API-Key 下载重庆中心 25 km 内 15 个站点、90 个传感器、600 条观测样本；key 未写入仓库。
```

## 10. 2026-07-05 GEE ERA5/CAMS 与 OpenAQ 数据基础补齐

新增代码：

```text
data_agent/uwm/gee_environment.py
data_agent/uwm/openaq_station_observations.py
data_agent/test_uwm_gee_environment.py
data_agent/test_uwm_openaq_station_observations.py
scripts/download_uwm_gee_era5_cams_proxy.py
scripts/download_uwm_openaq_station_observations.py
```

新增真实数据产物：

```text
data/uwm_public_proxy/chongqing_central/gee_era5_cams_2024_07_01_07/
data/uwm_public_proxy/chongqing_central/openaq_station_observations/
```

新增 renderer 产物：

```text
data/uwm_public_proxy/chongqing_central/gee_era5_cams_2024_07_01_07/uwm_canonical_observation_gee_era5_cams.json
data/uwm_public_proxy/chongqing_central/openaq_station_observations/uwm_canonical_observation_openaq_station.json
```

下载结果：

```text
GEE ERA5 records = 168
GEE CAMS records = 574
OpenAQ locations = 15
OpenAQ sensors = 90
OpenAQ measurements = 600
OpenAQ observed_time_range = 2018-10-17T12:00:00Z_to_2021-08-09T11:00:00Z
scene_holdout_ready = false
empirical_superiority_claim = false
```

证据边界：

```text
这次补齐显著增强了 UWM 的环境数据基础，尤其解决了 ERA5/CAMS 数据来源问题；
但它仍不能证明 UWM 在真实观测 holdout 上优于传统方法；
GEE ERA5/CAMS 是 reanalysis/model proxy，OpenAQ 是真实站点观测但时间不覆盖 2024-07 场景；
下一步若要提升到实证 claim，必须构造场景一致的 observed holdout 或将时间场景切换到 OpenAQ 覆盖期并设计严格评估。
```

## 11. 2026-07-05 Scene State 与状态条件化 Simulator

本次把 UWM 从“数据已经进入 renderer”继续推进到“renderer 输出被 simulator 消费”。新增 `uwm.scene_state.v1` 作为 renderer 与 simulator 之间的场景状态契约。

新增代码：

```text
data_agent/uwm/scene_state.py
data_agent/test_uwm_scene_state.py
```

新增真实产物：

```text
data/uwm_public_proxy/chongqing_central/uwm_scene_state_livability_2024_07.json
data/uwm_public_proxy/chongqing_central/uwm_simulator_scenario_livability_2024_07.json
data/uwm_public_proxy/chongqing_central/uwm_rollout_normal_air_reference.json
data/uwm_public_proxy/chongqing_central/uwm_rollout_scene_conditioned_livability_2024_07.json
data/uwm_public_proxy/chongqing_central/uwm_scene_conditioned_dynamic_advantage_2024_07.json
```

核心机制：

```text
GHSL-admin observation + Open-Meteo historical observation
-> uwm.scene_state.v1
-> simulator scenario controls
-> UwmRolloutTrace.v1
-> dynamic advantage evaluation
```

真实代理 scene controls：

```text
heat_stress_multiplier = 1.0857
air_pollution_stress_multiplier = 1.136285
vulnerability_multiplier = 1.088987
```

同一交通控排行动的响应差异：

```text
normal_air_delta = -0.08
scene_air_delta = -0.0909028
normal_livability_delta = 0.02225
scene_livability_delta = 0.02517592075
```

可声明结论：

```text
UWM 已经实现状态条件化 + 动作条件化 rollout；
相对于 traditional static_weighted_indicator_overlay，UWM 在 known-effect 动态任务上有 action_response_delta，传统 baseline 的 action_response_delta = 0；
supported_claim = known_effect_dynamic_advantage_over_static_baseline。
```

不可声明结论：

```text
empirical_superiority_claim = false
Open-Meteo 和 GHSL 仍是 public proxy，不是 observed intervention holdout。
当前结果不能表述为真实政策效果或真实观测 holdout 上优于传统方法。
```

## 12. 2026-07-05 多源环境证据融合推进

本次把环境状态从单一 Open-Meteo proxy 推进到多源证据融合：

```text
Open-Meteo historical proxy
+ GEE ERA5/CAMS proxy
+ OpenAQ station observation context
-> uwm.environmental_evidence_bundle.v1
-> uwm.scene_state.v1
-> UWM simulator scenario
-> rollout trace
-> dynamic advantage evaluation
```

新增代码：

```text
data_agent/uwm/environmental_fusion.py
data_agent/test_uwm_environmental_fusion.py
```

新增真实产物：

```text
data/uwm_public_proxy/chongqing_central/uwm_environmental_evidence_bundle_2024_07_multisource.json
data/uwm_public_proxy/chongqing_central/uwm_scene_state_livability_2024_07_multisource.json
data/uwm_public_proxy/chongqing_central/uwm_simulator_scenario_livability_2024_07_multisource.json
data/uwm_public_proxy/chongqing_central/uwm_rollout_scene_conditioned_livability_2024_07_multisource.json
data/uwm_public_proxy/chongqing_central/uwm_scene_conditioned_dynamic_advantage_2024_07_multisource.json
```

真实数据结果：

```text
Open-Meteo PM2.5 average = 35.16 ug/m3
GEE CAMS PM2.5 average = 16.81 ug/m3
fused scene PM2.5 proxy = 25.985 ug/m3
PM2.5 source range = 18.35 ug/m3
evidence_flags = high_pm25_source_disagreement, observed_holdout_not_ready, openaq_not_scene_aligned
OpenAQ observed range = 2018-10-17T12:00:00Z_to_2021-08-09T11:00:00Z
```

世界模型意义：

```text
传统静态宜居性 overlay 通常只把环境指标作为静态输入；
UWM 现在把多源环境证据转成状态、差异标记、claim gate 和 simulator controls；
因此它能形成 action-conditioned rollout，并在 known-effect dynamic task 上保持相对传统静态 baseline 的动态优势；
但由于 observed_holdout_ready = false，这仍不是 observed empirical superiority。
```

## 13. 2026-07-05 行政单元空间环境代理与 Exposure-Equity Panel

本次把环境数据基础从重庆中心点推进到 1017 个乡镇/街道代表点：

```text
xiangzhen admin units
-> representative point
-> GEE ERA5 weekly mean / precipitation sum
-> GEE CAMS PM2.5 / AOD mean
-> uwm.gee_admin_environment_proxy.v1
-> mmfe.uwm_state_input.v1
-> UwmCanonicalObservation.v1
```

新增代码：

```text
data_agent/uwm/gee_admin_environment.py
data_agent/uwm/admin_exposure_equity.py
data_agent/test_uwm_gee_admin_environment.py
data_agent/test_uwm_admin_exposure_equity.py
scripts/download_uwm_gee_admin_environment_proxy.py
```

新增真实数据产物：

```text
data/uwm_public_proxy/chongqing_central/gee_admin_environment_2024_07_01_07/
data/uwm_public_proxy/chongqing_central/admin_exposure_equity_2024_07_01_07/
```

结果摘要：

```text
admin_feature_count = 1017
sampled_admin_count = 1017
sampled_admin_share = 1.0
temperature_2m_mean_c_avg = 26.334
precipitation_total_mm_avg = 37.973
cams_pm25_ugm3_avg = 18.269
cams_pm25_ugm3_max = 34.94
joined_admin_count = 1017
strict_target_candidate_count = 0
exported_top_priority_proxy_units = 50
top_priority_proxy_unit = 沙坪坝区|覃家岗街道|973
```

证据边界：

```text
这是行政单元 representative point 空间代理，不是 polygon zonal mean；
exposure-equity priority score 是 planner targeting hypothesis，不是政策效果或健康结果；
严格三高 target_candidate 为 0，系统没有硬造目标，而是导出 top 50 proxy units 供 simulator/planner 试算；
empirical_superiority_claim = false。
```

## 14. 2026-07-05 Admin Planner Benchmark

本次把 exposure-equity panel 接入 UWM planner：

```text
admin_exposure_equity_panel
-> top priority proxy units
-> UwmCanonicalObservation.v1
-> candidate intervention actions
-> UwmRolloutTrace.v1
-> evidence_gated_rollout_planner_v0
-> planner advantage evaluation
```

新增代码：

```text
data_agent/uwm/admin_planner_benchmark.py
data_agent/test_uwm_admin_planner_benchmark.py
```

新增真实产物：

```text
data/uwm_public_proxy/chongqing_central/admin_planner_benchmark_2024_07_01_07/uwm_admin_planner_benchmark.json
```

真实 benchmark 结果：

```text
top_proxy_units_used = 10
rollout_count = 31
static_heuristic_action = static-priority-traffic-control::沙坪坝区|覃家岗街道|973
world_model_planner_action = uwm-urban-greening::沙坪坝区|覃家岗街道|973
static_livability_delta = 0.002334092075
planner_livability_delta = 0.004734535475
known_effect_regret_reduction = 0.0024004434
supported_claim = known_effect_planner_advantage_over_static_heuristic
empirical_superiority_claim = false
```

这里可以写进 Track 2 的“相对传统方法更强”的部分，但措辞必须严格：

```text
可以说：UWM 在受控 known-effect rollout benchmark 上，相比传统静态 top-priority heuristic 有正的 regret reduction。
不能说：UWM 已在真实 observed policy outcome 上优于传统方法。
```

## 15. 2026-07-05 OSM Service Accessibility Proxy

本次补齐 UWM-Livability 的服务设施维度。原始 `osm_services/` 样本没有 lat/lon，不能用于空间可达性。我没有冒充它可用，而是重新从 Overpass 下载了带坐标的 bbox amenity 样本。

新增代码：

```text
data_agent/uwm/osm_service_accessibility.py
data_agent/test_uwm_osm_service_accessibility.py
```

新增真实数据产物：

```text
data/uwm_public_proxy/chongqing_central/osm_services_geometry_2026_07_05/
```

结果摘要：

```text
requested_bbox = [29.52, 106.50, 29.60, 106.60]
elements = 200
coordinate_elements = 200
service_category_count = 8
essential_service_count = 16
food_retail_count = 116
healthcare_count = 10
education_count = 6
```

边界：

```text
这是 Overpass bbox service point sample；
不是完整 OSM extract；
不是网络出行时间可达性面；
但已经足够进入 MMFE state input 和 renderer，作为 UWM service_accessibility 的公开代理层。
```

## 16. 2026-07-05 Admin Service Accessibility Panel

本次把 OSM 服务点进一步归属到行政单元：

```text
OSM service accessibility proxy
+ Chongqing township/street admin units
-> uwm.admin_service_accessibility_panel.v1
```

新增代码：

```text
data_agent/uwm/admin_service_accessibility.py
data_agent/test_uwm_admin_service_accessibility.py
```

新增真实产物：

```text
data/uwm_public_proxy/chongqing_central/admin_service_accessibility_2026_07_05/
```

结果摘要：

```text
bbox_admin_count = 36
admin_units_with_service_points = 25
admin_units_without_sample_points = 11
service_point_count = 200
essential_service_count = 16
```

边界：

```text
只在 OSM bbox 相交行政单元内解释；
无点单元标记为 sample gap，不解释为真实服务缺失；
下一步若要形成服务公平实证，需要完整 POI extract 或路网出行时间服务可达性。
```

## 17. 2026-07-05 Composite Livability Target 与 Planner Benchmark

本次把环境暴露、人口脆弱性和服务样本弱项合成复合规划目标：

```text
admin_exposure_equity_panel
+ admin_service_accessibility_panel
-> uwm.admin_livability_target_panel.v1
-> UWM admin planner benchmark
```

新增代码：

```text
data_agent/uwm/admin_livability_targeting.py
data_agent/test_uwm_admin_livability_targeting.py
```

新增真实产物：

```text
data/uwm_public_proxy/chongqing_central/admin_livability_target_2024_07_2026_07_05/
data/uwm_public_proxy/chongqing_central/admin_livability_planner_benchmark_2024_07_2026_07_05/
```

结果摘要：

```text
joined_admin_count = 36
target_candidate_count = 3
top_target = 九龙坡区|九龙镇|77
rollout_count = 31
static_action = static-priority-traffic-control::九龙坡区|九龙镇|77
planner_action = uwm-urban-greening::九龙坡区|九龙镇|77
known_effect_regret_reduction = 0.0024004434
supported_claim = known_effect_planner_advantage_over_static_heuristic
```

严格声明：

```text
可以说：UWM 在复合 livability proxy target 的 known-effect rollout benchmark 上优于传统静态启发式。
不能说：UWM 已经在真实宜居性结果或真实政策 outcome holdout 上优于传统方法。
```

## 18. 2026-07-05 OpenAQ Observed Temporal Holdout

本次加入真实观测时间序列验证，不再只依赖 known-effect simulator benchmark。

新增代码：

```text
data_agent/uwm/openaq_temporal_benchmark.py
data_agent/test_uwm_openaq_temporal_benchmark.py
data_agent/uwm/track2_submission.py
data_agent/test_uwm_track2_submission.py
```

新增真实产物：

```text
data/uwm_public_proxy/chongqing_central/openaq_temporal_benchmark_2018_10/uwm_openaq_observed_temporal_benchmark.json
```

方法：

```text
OpenAQ station hourly observations
-> 70% train / 30% holdout
-> traditional static baseline suite: static_train_mean + static_last_train_observation
-> UWM online persistence state update
-> holdout MAE comparison
```

结果：

```text
pollutant_count = 6
observation_count = 600
holdout_count = 180
overall_holdout_win_count = 150
overall_holdout_win_rate = 0.833333
all_pollutants_dynamic_advantage = true
all_pollutants_dynamic_advantage_over_static_baseline_suite = true
pm25_static_mean_mae = 12.895238
pm25_best_static_baseline = static_last_train_observation
pm25_best_static_baseline_mae = 9.466667
pm25_dynamic_persistence_mae = 2.4
pm25_mae_reduction = 10.495238
pm25_mae_reduction_vs_best_static = 7.066667
pm25_holdout_win_count = 29/30
pm25_holdout_win_rate = 0.966667
pm25_dynamic_win_rate_vs_best_static = 0.833333
overall_sign_test_vs_static_train_mean_p = 3.169461318928462e-23
overall_sign_test_vs_static_last_train_observation_p = 7.023485467083628e-28
pm25_sign_test_vs_best_static_p = 2.823770046234131e-06
temporal_order_negative_control_ordered_advantage_count = 6/6
temporal_order_negative_control_mean_ordered_mae_advantage = 2.572222
pm25_ordered_mae_advantage_over_shuffled = 0.6
supported_claim = observed_temporal_state_prediction_advantage_over_static_baseline_suite
```

严格声明：

```text
可以说：UWM 的动态状态更新在 OpenAQ 真实观测时间序列 holdout 上优于传统静态 baseline suite。
更具体地说：6 个污染物全部击败 static_train_mean 和 static_last_train_observation；180 个 holdout 时点中有 150 个动态模型误差更小。
总体成对 sign test 支持该状态预测层优势：vs static_train_mean p = 3.17e-23，vs static_last_train_observation p = 7.02e-28。
PM2.5 相比 best static baseline 的 MAE 从 9.466667 降到 2.4，PM2.5 vs best static 的 sign test p = 2.82e-6。
时间顺序负控也通过：确定性乱序 holdout 后，6/6 个污染物的 ordered online update 更优，平均 MAE advantage = 2.572222，说明结果依赖真实 temporal continuity。
不能说：这证明 UWM planner 在真实政策 outcome 上优于传统方法；该门槛仍未通过。
```

机器可读门控：

```text
track2_submission.build_track2_readiness_matrix 现在可接收 observed_temporal_benchmark；
输出 observed_validation_readiness；
temporal_state_prediction_ready = true；
temporal_state_prediction_suite_ready = true；
temporal_state_prediction_suite_significant_at_0_05 = true；
temporal_order_negative_control_passed = true；
policy_outcome_superiority_ready = false；
remaining_gates = observed_policy_outcome_holdout_required, planner_regret_observed_outcome_required, causal_policy_effect_validation_required。
```

防过度声明修复：

```text
data_foundation 的环境 holdout-ready 判定新增回归测试；
observed_holdout_not_policy_outcome / temporal_state_benchmark 不能解除 air_pollution_exposure 或 meteorology 的 empirical superiority blocker；
只有明确 station_calibrated_holdout / observed_holdout / empirical_ready 且没有 not_policy_outcome 边界的环境数据，才允许解除真实实证优越性 gate。
```

## 19. 2026-07-05 Open-Meteo 2018-10 对齐 OpenAQ 时间窗下载

为补齐 OpenAQ temporal benchmark 的同期气象上下文，本轮尝试下载 Open-Meteo 2018-10-17 至 2018-10-23 重庆中心点历史数据。

新增/更新代码：

```text
data_agent/uwm/openmeteo_history.py
data_agent/test_uwm_openmeteo_history.py
```

新增真实数据产物：

```text
data/uwm_public_proxy/chongqing_central/openmeteo_history_2018_10_17_23/
```

下载结果：

```text
weather_hourly_records = 168
weather_daily_records = 7
air_quality_hourly_timestamps = 168
weather_non_null_counts = relative_humidity_2m:168, surface_pressure:168, temperature_2m_mean:7
air_quality_non_null_counts = pm10:0, pm2_5:0, carbon_monoxide:0, nitrogen_dioxide:0, sulphur_dioxide:0, ozone:0
```

严格边界：

```text
可以说：Open-Meteo 2018-10 天气数据可作为 OpenAQ temporal benchmark 的同期气象上下文。
不能说：Open-Meteo 2018-10 空气质量数据可用；该 API 对本时间窗返回了空气质量时间戳但污染物值全为 null。
因此新增 manifest 行只登记为 meteorology / temporal context，不登记为空气污染有效证据，也不解除 empirical superiority blocker。
```

## 20. 2026-07-06 TAP external spatiotemporal dynamics transition gate

本轮将 `/Users/zhouning/Downloads/tap_uwm` 中已解析的 TAP 1km PM2.5 日格网数据进一步用于 UWM transition-layer 外部验证。

新增代码与产物：

```text
data_agent/uwm/tap_external_dynamics.py
data_agent/test_uwm_tap_external_dynamics.py
scripts/build_uwm_tap_external_dynamics.py
data/uwm_public_proxy/chongqing_central/tap_pm25_external_dynamics_2026_07_06/tap_external_dynamics_report.json
data/uwm_public_proxy/chongqing_central/tap_pm25_external_dynamics_2026_07_06/snapshot_manifest.json
```

验证设计：

```text
scope = action-free external state transition
transition = state_t -> state_t+1
train_days = 3
sampled_grid_series = 10000
holdout_points = 40000
traditional_static_baselines = static_train_mean, static_last_train_observation, period_static_mean, tile_static_mean
non_spatial_dynamic_baselines = online_persistence_state_update, adaptive_online_state_update
spatial_world_model_candidates = spatial_message_ridge, spatial_residual_delta_ridge
negative_controls = neighbor_shuffle_control, non_spatial_feature_ablation_control, temporal_order_rotation_control, future_label_leakage_guard
```

最终真实 TAP 结果：

```text
best_spatial_method = spatial_residual_delta_ridge
best_transition_mae = 7.003808
best_traditional_static_method = static_train_mean
best_traditional_static_mae = 9.309192
best_non_spatial_dynamic_method = adaptive_online_state_update
best_non_spatial_dynamic_mae = 7.011689
mae_reduction_vs_best_static = 2.305384
mae_reduction_vs_best_non_spatial_dynamic = 0.007881
paired_win_rate_vs_best_non_spatial_dynamic = 0.5077
neighbor_shuffle_control_mae = 7.001213
spatial_negative_control_passed = false
temporal_order_negative_control_passed = true
future_label_leakage_guard_passed = true
supported_claim = tap_external_temporal_dynamics_advantage_without_spatial_claim
claim_boundary = bounded_support
empirical_superiority_claim = false
observed_policy_outcome_superiority_claim = false
```

严格解释：

```text
可以说：TAP external dynamics 现在支持 bounded temporal transition improvement over adaptive non-spatial dynamic baseline。
可以说：best residual-delta transition MAE = 7.003808，低于 best non-spatial dynamic MAE = 7.011689，paired win rate = 0.5077，且 future-label leakage guard 通过。
不能说：该结果支持 TAP spatial attribution；neighbor shuffle negative control MAE = 7.001213，不差于真实邻接，因此 spatial_negative_control_passed = false。
不能说：这证明 UWM planner 或城市干预在真实政策 outcome 上优于传统方法。
```

对 roadmap 的影响：

```text
这是一个边界清楚的正结果和负控结果：时序 transition 层相对强非空间动态基线有有限改进，但空间归因未成立。
UWM 的总体超越目标应继续按系统链条推进：renderer/state foundation -> observed temporal dynamics -> transition gate -> learned rollout planner -> policy outcome evaluator -> evidence gate。
下一步不应把 0.007881 MAE 改进夸大成总体胜利，而应补 scene-aligned station-calibrated air-quality holdout、observed policy outcome validation data 和 causal policy effect validation。
```

## 21. 2026-07-06 UWM world-model evidence readiness claim ladder

本轮新增系统级证据 readiness 层，把 data foundation evidence gate 接入 Track 2 readiness，而不是让各实验孤立存在。

新增代码与产物：

```text
data_agent/uwm/world_model_evidence_readiness.py
data_agent/test_uwm_world_model_evidence_readiness.py
data_agent/test_uwm_track2_readiness_report.py
scripts/build_uwm_track2_readiness_report.py
docs/reports/uwm_track2_readiness_2026_07_06/uwm_track2_readiness_matrix.json
docs/reports/uwm_track2_readiness_2026_07_06/uwm_track2_readiness_summary.md
```

机器门控结论：

```text
system_level_superiority_summary = bounded_state_prediction_and_transition_advantage_without_policy_outcome_superiority
overall_claim_ceiling = bounded_support
traditional_method_comparison_ready = true
policy_outcome_superiority_ready = false
empirical_superiority_claim = false
```

claim ladder：

```text
allowed = observed_temporal_state_prediction_advantage_over_static_baseline_suite
allowed = tap_external_temporal_dynamics_advantage_without_spatial_claim
allowed = learned_world_model_rollout_improves_imagined_static_and_one_step_baselines
not_allowed_as_empirical_claim = business_theory_aligned_learned_rollout_beats_static_proxy_baseline
```

禁止声明：

```text
observed_policy_outcome_superiority
spatial_attribution_for_tap_external_transition
overall_empirical_policy_superiority
```

架构状态：

```text
renderer.ready = true, but renderer.claim_level = fragile
simulator.ready = true, bounded transition/state evidence
planner.ready = true, exploratory proxy intervention package only
policy_outcome_evaluator.ready = false
```

严格解释：

```text
可以说：UWM 当前在状态预测和 transition 层面对传统静态方法、强非空间动态基线有 bounded evidence。
可以说：UWM 的 renderer/simulator/planner/evidence gate 已形成可审计 claim ladder。
不能说：UWM 已经证明城市政策干预 outcome 或总体经验优越性。
```

## 22. 2026-07-06 Paper6 causal diagnostic evidence 接入 UWM policy evaluator

本轮重新审查更新后的 Paper6 仓库后，没有把 SCCA/ArcGIS SCI Plus 误用为 UWM 主 dynamics；而是把它作为 policy evaluator 的因果诊断证据层接入。

新增代码与产物：

```text
data_agent/uwm/causal_policy_evidence.py
data_agent/test_uwm_causal_policy_evidence.py
scripts/build_uwm_causal_policy_evidence.py
data/uwm_public_proxy/chongqing_central/causal_policy_evidence_2026_07_06/uwm_causal_policy_evidence_gate.json
data/uwm_public_proxy/chongqing_central/causal_policy_evidence_2026_07_06/snapshot_manifest.json
```

真实输入证据：

```text
Paper6 IJGIS result root = /Users/zhouning/paper6-spatial-causal-inference/paper/ijgis_submission_20260605/07_results
ArcGIS SCI Plus county input_rows = 3108
ArcGIS SCI Plus county trimmed_rows = 3044
ArcGIS 3.7 documented ERF parity MAE = 0.015153286175193017
SCCA county credibility decision = strong_support
Chongqing UHI sample_size = 5000
Chongqing buildings_total = 107035
```

机器门控结论：

```text
algorithmic_causal_diagnostic_ready = true
observed_local_policy_outcome_ready = false
observed_policy_outcome_superiority_claim = false
empirical_superiority_claim = false
```

对 roadmap 的影响：

```text
causal_policy_effect_validation_required 已从 data foundation evidence gate 的 remaining_gates 中移除。
当时 observed_policy_outcome_required、scene_aligned_station_calibrated_air_quality_holdout_required、external_observed_holdout_required 仍然保留；后续 external observed holdout suite 单独处理。
Paper6 证明的是因果诊断工作流和 ArcGIS documented mode algorithmic parity，不是 UWM 策略实施后的观测 outcome。
```

## 23. 2026-07-06 External observed holdout suite 接入

本轮新增双源外部观测 holdout suite，用真实 OpenAQ station temporal benchmark 和 TAP gridded temporal benchmark 支撑 state-prediction over static baseline 的 bounded claim。

新增代码与产物：

```text
data_agent/uwm/external_observed_holdout.py
data_agent/test_uwm_external_observed_holdout.py
scripts/build_uwm_external_observed_holdout_suite.py
data/uwm_public_proxy/chongqing_central/external_observed_holdout_suite_2026_07_06/uwm_external_observed_holdout_suite.json
data/uwm_public_proxy/chongqing_central/external_observed_holdout_suite_2026_07_06/snapshot_manifest.json
```

真实输入证据：

```text
OpenAQ station temporal benchmark: observation_count = 600, holdout_count = 180, dynamic win count = 150, PM2.5 dynamic MAE = 2.4, best static PM2.5 MAE = 9.466667
TAP gridded temporal benchmark: series_count = 10000, holdout_count = 40000, adaptive online state update MAE = 7.01169, static train mean MAE = 9.309192, series beats all static baselines rate = 0.6318
```

机器门控结论：

```text
external_observed_holdout_ready = true
external_observed_state_prediction_superiority_claim = true
scene_aligned_station_calibrated_air_quality_holdout_ready = false
observed_policy_outcome_superiority_claim = false
empirical_superiority_claim = false
```

对 roadmap 的影响：

```text
external_observed_holdout_required 已从 data foundation evidence gate 的 remaining_gates 中移除。
observed_policy_outcome_required、scene_aligned_station_calibrated_air_quality_holdout_required 仍然保留。
这个结果能证明 UWM-style online state update 在真实外部观测 holdout 上强于传统静态 baseline suite；不能证明 2024 场景 station-calibrated air-quality，也不能证明政策 outcome 或总体经验优越性。
```

## 24. 2026-07-06 Historical station-aligned air-quality holdout

本轮继续补 scene-aligned station-calibrated air-quality holdout 时，先复核了本地 OpenAQ 2024-07 场景尝试结果：重庆中心 25 km 内 15 个 locations、90 个 sensors，但 2024-07-01 至 2024-07-07 measurements = 0。因此本轮没有把 2024 场景硬伪造成 station holdout，而是构造了一个历史站点对齐验证层：用 OpenAQ 2018-10 真实 PM2.5 站点观测对齐最近 TAP 1km PM2.5 grid，验证格网状态对真实站点 holdout 的预测能力。

新增代码与产物：

```text
data_agent/uwm/station_aligned_air_quality_holdout.py
data_agent/test_uwm_station_aligned_air_quality_holdout.py
scripts/build_uwm_station_aligned_air_quality_holdout.py
data/uwm_public_proxy/chongqing_central/station_aligned_air_quality_holdout_2026_07_06/uwm_station_aligned_air_quality_holdout.json
data/uwm_public_proxy/chongqing_central/station_aligned_air_quality_holdout_2026_07_06/snapshot_manifest.json
```

真实输入证据：

```text
OpenAQ station = 上清寺
OpenAQ PM2.5 hourly station observations = 100
nearest TAP tile = 075
nearest TAP grid = 62722
nearest TAP grid distance = 446.95923 m
train_count = 70
holdout_count = 30
```

机器评估结果：

```text
best_station_aligned_method = raw_tap_nearest_grid
raw_tap_mae = 5.463333
static_train_mean_mae = 12.895238
static_last_observation_mae = 9.466667
linear_station_calibrated_tap_mae = 9.608119
raw_tap_beats_static_station_baselines = true
linear_calibration_beats_raw_tap = false
historical_station_aligned_holdout_ready = true
scene_aligned_station_calibrated_air_quality_holdout_ready = false
observed_policy_outcome_superiority_claim = false
empirical_superiority_claim = false
```

对 roadmap 的影响：

```text
可以新增 bounded claim：
historical_station_aligned_tap_pm25_beats_static_station_baselines

仍不能关闭：
scene_aligned_station_calibrated_air_quality_holdout_required
observed_policy_outcome_required
synthetic_proxy_boundary_must_remain_visible
```

严格解释：

可以说：历史 2018 OpenAQ 上清寺站 PM2.5 holdout 上，TAP nearest-grid 状态优于两个 station static baselines。
不能说：已经完成 2024-07 场景 station-calibrated air-quality holdout。
不能说：已经证明政策 outcome 或总体实证优越性。

## 25. 2026-07-06 Data-calibrated simulator mechanism table

本轮继续推进 UWM simulator 的世界模型技术架构，把 action-effect 机制从纯硬编码 `_action_effect` 系数推进到由真实观测/公开代理证据校准的机制表。这个机制表不是政策干预后的 observed outcome，也不是因果政策效果；它的作用是让 simulator 的 action-conditioned priors 带有可审计数据来源和 evidence gate，而不是停留在不可追踪常数。

新增代码与产物：

```text
data_agent/uwm/data_calibrated_mechanism_table.py
data_agent/test_uwm_data_calibrated_mechanism_table.py
scripts/build_uwm_data_calibrated_mechanism_table.py
data/uwm_public_proxy/chongqing_central/data_calibrated_mechanism_table_2026_07_06/uwm_data_calibrated_mechanism_table.json
data/uwm_public_proxy/chongqing_central/data_calibrated_mechanism_table_2026_07_06/snapshot_manifest.json
```

真实输入证据：

```text
OpenAQ observation_count = 600
OpenAQ holdout_count = 180
OpenAQ PM2.5 dynamic MAE = 2.4
OpenAQ PM2.5 best static MAE = 9.466667
TAP holdout_count = 40000
TAP best transition MAE = 7.003808
TAP best static MAE = 9.309192
station-aligned OpenAQ/TAP observations = 100
station-aligned raw TAP MAE = 5.463333
station-aligned best static MAE = 9.466667
NOAA ISD scene weather observations = 224
NOAA temperature range = 13.6 C
admin livability rows = 36
admin service gap mean = 0.760073
admin livability need mean = 0.56574
```

机制表输出：

```text
air_pollution_scale = 1.35
heat_scale = 1.28
service_scale = 1.228022
equity_scale = 1.141435

traffic_emission_control.air_pollution_exposure_delta = -0.216
increase_green_infrastructure.heat_risk_delta = -0.2304
add_community_service.service_accessibility_delta = 0.221044
data_calibrated_mechanism_ready = true
hardcoded_mechanism_replacement_ready = true
observed_policy_outcome_superiority_claim = false
empirical_superiority_claim = false
```

Simulator 接入方式：

```text
simulate_livability_rollout(..., mechanism_table=table)
```

当机制表验证通过时，simulator trace 会新增：

```text
read_data_calibrated_mechanism_table
apply_action_effects.mechanism_source = data_calibrated_mechanism_table
```

对 roadmap 的影响：

```text
新增 allowed bounded claim：
data_calibrated_simulator_mechanism_replaces_hardcoded_coefficients

仍不能关闭：
observed_policy_outcome_required
scene_aligned_station_calibrated_air_quality_holdout_required
synthetic_proxy_boundary_must_remain_visible
```

严格解释：

可以说：UWM simulator 的 greening、traffic、service action-effect 机制表已经由真实观测 state/transition evidence 和公开代理 admin panel 校准，替代了不可追踪硬编码常数。
可以说：UWM 在 observed state prediction 和 external transition holdout 上已有 bounded evidence 强于传统静态 baseline suite。
不能说：机制表证明真实政策干预 outcome 优于传统方法。

## 26. 2026-07-06 Data-calibrated Graph-MDP planner replay

本轮继续把 UWM planner 从 known-effect simulator scaffold 推进到数据校准世界模型回放：Graph-MDP planner 不再只读取硬编码 simulator coefficients，而是显式读取 `uwm_data_calibrated_mechanism_table_2026_07_06`，并把机制来源写入 simulator trace 与 replay transition。该结果仍是 model-internal replay，不是已实施政策的 observed outcome。

新增代码与产物：

```text
data_agent/test_uwm_data_calibrated_planner_replay.py
scripts/build_uwm_data_calibrated_planner_replay.py
data/uwm_public_proxy/chongqing_central/data_calibrated_planner_replay_2026_07_06/uwm_data_calibrated_model_based_graph_search.json
data/uwm_public_proxy/chongqing_central/data_calibrated_planner_replay_2026_07_06/uwm_data_calibrated_offline_world_model_rollout_planner.json
data/uwm_public_proxy/chongqing_central/data_calibrated_planner_replay_2026_07_06/snapshot_manifest.json
```

真实输入证据：

```text
admin spatial graph nodes = 1017
admin spatial graph edges = 2847
admin livability panel rows = 36
data-calibrated mechanism table id = uwm-data-calibrated-mechanism-table-2026-07-06
mechanism table OpenAQ observations = 600
mechanism table TAP holdout = 40000
mechanism table station-aligned observations = 100
mechanism table NOAA scene weather observations = 224
```

Graph-MDP replay 输出：

```text
transition_count = 355
best_sequence_reward = 0.017180838
static_single_step_reward = 0.003837146
advantage_over_static_single_step = 0.013343692
supported_claim = data_calibrated_model_based_graph_search_advantage_over_static_heuristic
observed_policy_outcome_superiority_claim = false
empirical_superiority_claim = false
```

Offline learned rollout 输出：

```text
holdout_reward_mae = 0.0001991
train_mean_reward_mae = 0.002339847
learned_rollout_supported_claim = learned_world_model_rollout_improves_imagined_static_and_one_step_baselines
```

对 roadmap 的影响：

```text
新增 allowed bounded claim：
data_calibrated_planner_replay_advantage_over_static_heuristic

仍不能关闭：
observed_policy_outcome_required
scene_aligned_station_calibrated_air_quality_holdout_required
synthetic_proxy_boundary_must_remain_visible
```

严格解释：

可以说：在同一 admin livability graph 和同一数据校准 simulator 下，UWM Graph-MDP 多步搜索的 model-internal reward 高于 static single-step heuristic，并且 learned rollout 对 replay reward 的 holdout MAE 优于 train-mean baseline。
不能说：这已经证明真实城市政策 outcome 优于传统方法。
不能说：这已经替代 scene-aligned station-calibrated air-quality holdout 或 observed policy outcome validation。

## 27. 2026-07-06 Paper58/Paper6 最新更新复核与 scene-aligned gridded PM2.5 holdout

本轮在继续 UWM 开发前重新审查了本地最新同步的两个相关仓库：

```text
Paper58 repo = /Users/zhouning/paper58-geofm-world-model-rl
Paper58 HEAD = 1c029d8 submission: add SRS competing interests declaration
Paper6 repo = /Users/zhouning/paper6-spatial-causal-inference
Paper6 HEAD = d3c63c0 fix: remove duplicate references heading
```

对 UWM roadmap 的判断：

```text
Paper58 对 UWM 有用，但主要是 remote_sensing_state / latent suitability / spatial allocation baseline / benchmark discipline。
最新主分支提交主要是 SRS 投稿材料和图表清理，不直接提供新的 UWM 城市宜居性 policy outcome 数据。
可迁移的技术点是：高维遥感 embedding state prior、evidence-gated allocation、多尺度 spatial ranking、与 GeoSOS-FLUS 同网格对照的审计方式。
不能迁移的结论是：Paper58 在土地利用分配 benchmark 上优于 GeoSOS-FLUS，不能自动证明 UWM 在城市宜居性政策 outcome 上优于传统方法。

Paper6 对 UWM 有用，但主要是 causal policy evaluator / SCCA diagnostics / ArcGIS parity / UHI exposure evidence。
最新主分支提交主要是 IJGIS 投稿包修正和图件/引用审计，不直接提供 UWM 干预后的真实政策 outcome。
可迁移的技术点是：AnalysisRequest 统一算法边界、空间诊断、bootstrap、placebo、ERF 反演、ArcGIS/QGIS thin-adapter discipline。
不能迁移的结论是：Paper6 的 SCCA/ArcGIS SCI Plus 诊断不能替代 UWM planner 的 observed policy outcome validation。
```

因此本轮没有把 Paper58/Paper6 的论文结论直接写成 UWM 优越性，而是把它们分别保留为状态表征/空间分配先验和因果诊断证据层。随后继续补 UWM 自身的真实数据 holdout。

新增代码与产物：

```text
data_agent/uwm/scene_aligned_gridded_air_quality_holdout.py
data_agent/test_uwm_scene_aligned_gridded_air_quality_holdout.py
scripts/build_uwm_scene_aligned_gridded_air_quality_holdout.py
data/uwm_public_proxy/chongqing_central/scene_aligned_gridded_air_quality_holdout_2026_07_06/uwm_scene_aligned_gridded_air_quality_holdout.json
data/uwm_public_proxy/chongqing_central/scene_aligned_gridded_air_quality_holdout_2026_07_06/snapshot_manifest.json
```

真实输入：

```text
CHAP admin PM2.5 proxy = data/uwm_public_proxy/chongqing_central/chap_pm25_2024_07/chap_pm25_admin_proxy.json
TAP root = /Users/zhouning/Downloads/tap_uwm
scene period = 2024-07-01_to_2024-07-07
admin_unit_count = 36
holdout_count = 144
```

失败记录：

```text
初始 temporal persistence/adaptive online 方案在真实 TAP/CHAP scene-aligned 数据上失败。
adaptive online MAE = 4.036
best static baseline MAE = 2.783102
temporal negative control failed
```

处理原则：

```text
该失败结果没有被包装成 UWM 优势，也没有形成 supported claim。
由于真实数据表明单点时间更新弱于静态基线，本轮转向符合世界模型消息传递结构的 leave-one-admin-out spatial message reconstruction：
隐藏目标 admin point 的 same-day PM2.5；
用同日其它 admin points 的 gridded observations 作为空间上下文；
比较 scene mean message、spatial IDW message 与 static baselines；
用 reverse-coordinate IDW 做 spatial shuffle negative control。
```

真实 gridded holdout 结果：

```text
best_uwm_method = spatial_idw_message_reconstruction
best_uwm_mae = 1.058085
best_static_baseline_method = static_train_mean
best_static_baseline_mae = 2.783102
best_uwm_mae_reduction = 1.725017
spatial_shuffle_negative_control_passed = true
scene_aligned_gridded_air_quality_holdout_ready = true
scene_aligned_station_calibrated_air_quality_holdout_ready = false
observed_policy_outcome_superiority_claim = false
empirical_superiority_claim = false
```

对 roadmap 的影响：

```text
新增 allowed bounded claim：
scene_aligned_gridded_pm25_spatial_message_advantage_over_static_baselines

继续保留 remaining gates：
observed_policy_outcome_required
scene_aligned_station_calibrated_air_quality_holdout_required
synthetic_proxy_boundary_must_remain_visible
```

严格解释：

可以说：在 2024-07 scene-aligned gridded TAP/CHAP PM2.5 state reconstruction 任务上，UWM spatial message reconstruction 明显优于 traditional static baseline suite。
不能说：这是 station-calibrated observed air-quality holdout。
不能说：这是真实政策 outcome。
不能说：这证明 UWM planner 在真实治理结果上已经优于传统方法。

## 28. 2026-07-06 Scene-aligned gridded PM2.5 conformal uncertainty head

本轮继续沿世界模型技术架构补齐 `uncertainty` 头，而不是只停留在点预测 MAE。实现采用 split-conformal calibration：用训练期 same-day leave-one-admin spatial IDW residuals 校准 UWM interval radius，用训练期 leave-one-day static residuals 校准传统静态 baseline interval radius，然后在同一 144 个 TAP/CHAP scene-aligned gridded holdout predictions 上比较 coverage、interval width 和 interval score。

TDD 记录：

```text
RED:
uv run pytest data_agent/test_uwm_scene_aligned_gridded_air_quality_holdout.py -q
失败原因：
KeyError: 'uncertainty_calibration'
KeyError: 'uwm_uncertainty_calibration_ready'

GREEN:
uv run pytest data_agent/test_uwm_scene_aligned_gridded_air_quality_holdout.py -q
2 passed in 2.76s
```

新增实现：

```text
data_agent/uwm/scene_aligned_gridded_air_quality_holdout.py
_uncertainty_calibration(...)
_conformal_radius(...)
_interval_scores(...)
```

真实 gridded uncertainty 结果：

```text
confidence_level = 0.9
calibration_count = 108
holdout_count = 144
best_uwm_method = spatial_idw_message_reconstruction
static_baseline_method = static_train_mean
uwm_interval_radius = 2.291251
static_interval_radius = 6.85
uwm_interval_coverage = 0.944444
static_interval_coverage = 1.0
uwm_mean_interval_width = 4.582503
static_mean_interval_width = 13.7
uwm_interval_score = 5.559385
static_interval_score = 13.7
uwm_interval_score_reduction = 8.140615
```

新增 allowed bounded claim：

```text
scene_aligned_gridded_pm25_conformal_uncertainty_advantage_over_static_baseline
```

严格解释：

可以说：在 TAP/CHAP 2024-07 scene-aligned gridded PM2.5 reconstruction 任务上，UWM spatial message head 的 conformal interval 达到 0.944444 coverage，并以更窄区间和更低 interval score 优于 static train-mean baseline。
不能说：这是 station-calibrated observed holdout。
不能说：这是 observed policy outcome。
不能说：这关闭了 `scene_aligned_station_calibrated_air_quality_holdout_required` 或 `observed_policy_outcome_required`。

## 30. 2026-07-06 Multisource livability scene renderer

本轮回应“为什么没有把足够多的数据源都用上”的问题，把 UWM 从局部空气质量/Planner replay 推进到 multisource renderer。新 renderer 将 36 个 admin livability candidate 与 exposure/equity、service accessibility、GHSL population/built surface、GEE admin environment、TAP/CHAP scene-aligned PM2.5、admin spatial graph、Unicom latent mobility graph 和 OSM mobility network proxy 放入同一个 admin-unit scene。Unicom/OSM mobility 当前作为 scene context 使用，因缺少 grid/road-to-admin crosswalk，不硬投影到单元级分数。

TDD 记录：

```text
RED:
uv run pytest data_agent/test_uwm_multisource_livability_scene.py -q
失败原因：
ModuleNotFoundError: No module named 'data_agent.uwm.multisource_livability_scene'

GREEN:
uv run pytest data_agent/test_uwm_multisource_livability_scene.py -q
3 passed in 0.09s
```

新增实现与产物：

```text
data_agent/uwm/multisource_livability_scene.py
data_agent/test_uwm_multisource_livability_scene.py
scripts/build_uwm_multisource_livability_scene.py
data/uwm_public_proxy/chongqing_central/multisource_livability_scene_2026_07_06/uwm_multisource_livability_scene.json
data/uwm_public_proxy/chongqing_central/multisource_livability_scene_2026_07_06/snapshot_manifest.json
```

真实多源 renderer 覆盖：

```text
admin_unit_count = 36
data_source_count = 9
admin_exposure_equity matched = 36/36
ghsl_admin_alignment matched = 36/36
service_accessibility matched = 36/36
gee_admin_environment matched = 36/36
scene_aligned_gridded_pm25 matched = 36/36
admin_spatial_graph source_node_count = 1017
unicom_latent_mobility_graph edge_count = 1067
osm_mobility_network edge_count = 45468
```

真实 source-gated air-quality head 结果：

```text
target = tap_scene_pm25_mean_ugm3
model = chap_cams_standardized_ridge
holdout = leave-one-admin-out, 36 admin units
multisource_mae = 0.949891
chap_only_mae = 0.952794
cams_only_mae = 1.010687
loo_city_mean_mae = 1.009252
mae_reduction_vs_best_single_source = 0.002903
paired_win_count_vs_chap = 20
paired_loss_count_vs_chap = 16
spatial_interaction_negative_control_passed = false
observed_policy_outcome_superiority_claim = false
```

新增 allowed bounded claim：

```text
multisource_livability_scene_air_quality_head_beats_single_source_baselines
```

严格解释：

可以说：UWM renderer 已把多源数据真正对齐到统一 admin-unit scene，并且其中的空气质量 source-gated head 在真实 TAP scene PM2.5 mean 的 leave-one-admin-out 任务上略优于 CHAP-only、CAMS-only 和 LOO city-mean baseline。
不能说：所有数据源直接融合后都提高了每个任务；服务可达性外生多源预测没有稳定优于均值 baseline，不能强行写优势。
不能说：这是完整宜居性 observed outcome。
不能说：这是 observed policy outcome 或真实政策反事实。

## 31. 2026-07-06 OSM admin mobility crosswalk

本轮继续把 mobility 从 scene context 推进到真正的 admin-unit state。实现使用 OSM Overpass raw highway nodes/ways 和 admin spatial graph bbox，对 road segment midpoint 做单归属：若 midpoint 落入多个 candidate admin bbox，选择 bbox area 最小的行政单元，避免重复计数。这个 crosswalk 仍是 bbox proxy，不是精确 polygon overlay，也不是出行时间网络。

TDD 记录：

```text
RED:
uv run pytest data_agent/test_uwm_osm_admin_mobility_crosswalk.py -q
失败原因：
ModuleNotFoundError: No module named 'data_agent.uwm.osm_admin_mobility_crosswalk'

GREEN:
uv run pytest data_agent/test_uwm_osm_admin_mobility_crosswalk.py -q
3 passed in 0.39s
```

新增实现与产物：

```text
data_agent/uwm/osm_admin_mobility_crosswalk.py
data_agent/test_uwm_osm_admin_mobility_crosswalk.py
scripts/build_uwm_osm_admin_mobility_crosswalk.py
data/uwm_public_proxy/chongqing_central/osm_admin_mobility_crosswalk_2026_07_06/uwm_osm_admin_mobility_crosswalk.json
data/uwm_public_proxy/chongqing_central/osm_admin_mobility_crosswalk_2026_07_06/snapshot_manifest.json
```

真实 crosswalk 结果：

```text
admin_unit_count = 36
osm_raw_node_count = 42058
osm_highway_way_count = 6762
assigned_road_segment_count = 45449
unassigned_road_segment_count = 19
assignment_rule = segment_midpoint_inside_admin_bbox_choose_smallest_bbox_area
```

真实服务可达性 head 结果：

```text
target = osm_service_point_count
model = osm_road_segment_count_standardized_ridge
holdout = leave-one-admin-out, 36 admin units
mobility_crosswalk_mae = 12.887057
city_mean_mae = 14.152381
ghsl_population_proxy_mae = 14.760068
ghsl_built_surface_proxy_mae = 14.028006
mae_reduction_vs_best_traditional_static = 1.140949
paired_win_count_vs_best_traditional = 20
paired_loss_count_vs_best_traditional = 16
observed_policy_outcome_superiority_claim = false
```

新增 allowed bounded claim：

```text
osm_admin_mobility_crosswalk_service_accessibility_head_beats_static_baselines
```

严格解释：

可以说：OSM road segment count 的 admin-unit crosswalk 在真实 OSM service point count 的 LOO 任务上优于 city mean、GHSL population 和 GHSL built-surface static baseline。
不能说：这是精确道路网络可达性、出行时间或交通流观测。
不能说：这是完整宜居性 observed outcome。
不能说：这是 observed policy outcome 或真实政策反事实。

## 29. 2026-07-06 Risk-calibrated data-calibrated planner replay

本轮继续推进 planner boundary：不改变 Graph-MDP raw reward，也不把 gridded state holdout 伪装成政策 outcome；只把上一轮真实 TAP/CHAP scene-aligned gridded PM2.5 split-conformal uncertainty 接入 planner replay 的风险评估层。风险惩罚使用同一个 UWM PM2.5 interval score 同时作用于 model-based plan 和 static single-step baseline，避免通过给 baseline 施加额外不确定性来制造优势。

TDD 记录：

```text
RED:
uv run pytest data_agent/test_uwm_data_calibrated_planner_replay.py::test_data_calibrated_graph_search_uses_scene_aligned_conformal_uncertainty_for_risk_adjustment -q
失败原因：
TypeError: plan_with_model_based_graph_search() got an unexpected keyword argument 'air_quality_uncertainty_context'

GREEN:
uv run pytest data_agent/test_uwm_data_calibrated_planner_replay.py -q
5 passed in 0.26s
```

新增实现与产物：

```text
data_agent/uwm/model_based_rl.py
data_agent/uwm/data_foundation_evidence_gate.py
data_agent/uwm/world_model_evidence_readiness.py
scripts/build_uwm_data_calibrated_planner_replay.py
data/uwm_public_proxy/chongqing_central/data_calibrated_planner_replay_2026_07_06/uwm_data_calibrated_model_based_graph_search.json
data/uwm_public_proxy/chongqing_central/data_foundation_evidence_gate_2026_07_05/uwm_data_foundation_evidence_gate.json
docs/reports/uwm_track2_readiness_2026_07_06/uwm_track2_readiness_matrix.json
```

真实风险校准结果：

```text
air_quality_uncertainty_calibration_ready = true
uwm_interval_score = 5.559385
static_interval_score = 13.7
pm25_scene_range_ugm3 = 16.4
normalized_uwm_interval_score = 0.33898689
best_sequence_raw_reward = 0.017180838
static_single_step_raw_reward = 0.003837146
best_sequence_risk_adjusted_reward = 0.016111838
static_single_step_risk_adjusted_reward = 0.003334625
risk_adjusted_advantage_over_static_single_step = 0.012777213
risk_calibrated_planner_replay_ready = true
observed_policy_outcome_superiority_claim = false
```

新增 allowed bounded claim：

```text
risk_calibrated_planner_replay_advantage_over_static_heuristic
```

严格解释：

可以说：在 data-calibrated simulator replay 中，UWM Graph-MDP best two-step sequence 在使用同一 scene-aligned gridded PM2.5 conformal uncertainty penalty 后仍优于 static single-step heuristic。
不能说：这是 station-calibrated PM2.5 outcome。
不能说：这是 observed policy outcome。
不能说：这关闭了 `scene_aligned_station_calibrated_air_quality_holdout_required` 或 `observed_policy_outcome_required`。
