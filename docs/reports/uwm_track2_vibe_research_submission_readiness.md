# UWM Track 2 Vibe Research Submission Readiness

日期：2026-07-04；更新：2026-07-06

## 1. 赛事约束

赛事：

```text
Urban Cup 2026 Track 2 Vibe Research
```

初评截止：

```text
2026-07-22
```

初评反馈：

```text
2026-07-29
```

终评：

```text
2026-08-08 至 2026-08-09
```

当前距离初评截止：

```text
16 days
```

## 2. 工具链定位

赛事推荐工具：

```text
https://github.com/tsinghua-fib-lab/AI-Urban-Scientist
```

UWM 对该工具链的使用方式不是替代 UWM 架构，而是映射到 Track 2 提交材料生产流程：

| AI Urban Scientist 阶段 | UWM 中的作用 |
| --- | --- |
| Idea Generation | 城市宜居性、气候健康风险、空间公平的研究问题生成与新颖性论证 |
| Data Seeking | UWM data foundation manifest 与 MMFE 数据接入 |
| Paper Planning | 世界模型评估设计、claim boundary 和 evidence gate 规划 |
| Paper Writing | 初评研究报告、数据说明、复现代码说明、AI 协作记录 |

## 3. 当前材料矩阵

| 初评材料 | 当前状态 | 路径 | 必须覆盖 |
| --- | --- | --- | --- |
| 研究报告 | partial | `docs/reports/uwm_track2_initial_report.md` | research question; data sources; methods; main findings; urban science significance |
| 数据说明 | available | `docs/reports/uwm_data_foundation_manifest.md` | data sources; licenses or access boundaries; claim boundaries; synthetic or proxy flags |
| 可复现代码 | available | `data_agent/uwm` | runtime contracts; tests; manifest audit; evaluation gates |
| AI 协作过程记录 | available | `docs/reports/uwm_track2_research_log.md` | research log; tool or dialogue record; modeling decisions; failed or rejected claims |

当前 readiness：

```text
ready_for_initial_submission = false
partial_required_artifacts = ["research_report"]
missing_required_artifacts = []
```

## 3.1 数据基础 readiness

当前数据角色覆盖审计：

```text
manifest_valid = true
manifest_row_count = 72
missing_required_roles = []
claim_ceiling = fragile
```

当前仍阻止 observed holdout empirical superiority 的角色：

```text
air_pollution_exposure
```

解释：

- UWM 的核心数据角色已经补齐到 manifest；
- 人口脆弱性已有 GHSL public proxy 行政单元分区统计，并已生成 `mmfe.uwm_state_input.v1` 状态输入；
- 空气污染和气象已有 Open-Meteo 历史点位代理、GEE ERA5/CAMS 点位代理、OpenAQ 真实站点观测代理，并已生成 `mmfe.uwm_state_input.v1` 状态输入；
- GEE ERA5/CAMS 已从中心点扩展到 1017 个重庆乡镇/街道 representative point，并生成行政单元环境代理；
- 已新增 `uwm.environmental_evidence_bundle.v1`，把 Open-Meteo、GEE ERA5/CAMS 和 OpenAQ 合成多源环境证据链，并记录 PM2.5 源间差异与 observed holdout gate；
- TAP 外部日格网 transition gate 已接入 evidence gate；它支持 bounded temporal transition improvement，但不支持空间归因或政策 outcome superiority；
- 新增历史 station-aligned air-quality holdout：OpenAQ 上清寺站 100 条 PM2.5 小时观测对齐 TAP nearest-grid，raw TAP holdout MAE = 5.463333，优于 station static train mean 12.895238 和 static last observation 9.466667；
- 新增 data-calibrated simulator mechanism table：用 OpenAQ/TAP/NOAA/admin panel 真实和公开代理证据校准 greening、traffic、service action-effect 系数，替代硬编码机制先验；
- 新增 data-calibrated planner replay：把 data-calibrated mechanism table 接入 Graph-MDP multi-step planner 和 offline learned rollout；best two-step reward = 0.017180838，高于 static single-step reward = 0.003837146；learned rollout holdout reward MAE = 0.0001991，优于 train-mean baseline 0.002339847；
- 新增 scene-aligned gridded PM2.5 holdout：以 CHAP 2024-07 admin representative points 采样 TAP daily 1 km grid；36 个行政候选单元、144 个 holdout predictions，`spatial_idw_message_reconstruction` MAE = 1.058085，优于 `static_train_mean` MAE = 2.783102；90% split-conformal interval coverage = 0.944444，UWM interval score = 5.559385，static interval score = 13.7；该结果只支持 gridded state reconstruction 和 uncertainty calibration，不是 station-calibrated observation 或 policy outcome；
- 但 Open-Meteo/CAMS 是 modeled proxy，ERA5 是 reanalysis proxy，TAP 是多源融合格网产品，OpenAQ 2024-07 scene attempt 为 0 measurements；历史站点对齐结果不覆盖 2024-07 场景，因此空气污染暴露仍阻止真实 scene-aligned holdout empirical superiority 声明；
- 本地行政边界已可用作治理单元，但来源许可、官方年代和现代区县名 crosswalk 未核验，因此当前总 claim ceiling 为 fragile；
- 因此初评可以提交严格标注边界的 UWM known-effect 研究结果；
- 但报告中不能宣称已在真实观测 holdout 上全面优于传统方法。

公开数据补齐队列：

```text
download_or_mount_air_pollution_public_proxy
```

当前仍需补齐的数据：

```text
ERA5/CAMS: 已通过本机 GEE 认证下载重庆中心点代理；若要空间显式宜居性结论，还需扩展到城市栅格或行政单元聚合
OpenAQ: 已通过运行时 key 下载站点观测；若要 observed holdout，需要找到覆盖 2024-07 场景或其它评估期的站点/archive 记录
```

当前可以尝试公共下载但必须核查覆盖的数据：

```text
era5_meteorology_chongqing
cams_air_pollution_proxy
openaq_air_quality_proxy
openmeteo_weather_current_proxy
openmeteo_air_quality_current_proxy
worldpop_population_chongqing_proxy
ghsl_population_built_chongqing_proxy
osm_services_chongqing_public_proxy
```

Open-Meteo 的定位：

```text
可用于 UWM live environmental proxy 和 smoke/live context；
不能作为 GEE ERA5/CAMS 行政单元 representative-point 空间代理、面状 zonal mean 或站点校准 holdout 的等价替代。
```

已真实下载并进入本地数据基础的公开/本地快照：

```text
openmeteo_current: current weather + current air quality
openmeteo_history_2024_07_01_07: 2024-07-01 至 2024-07-07 重庆中心点历史气象/空气质量代理 + MMFE UWM state input
gee_era5_cams_2024_07_01_07: 2024-07-01 至 2024-07-07 重庆中心点 ERA5 168 条记录 + CAMS 574 条记录 + MMFE UWM state input
openaq_station_observations: 重庆中心 25 km 内 15 个 OpenAQ 站点、90 个传感器、600 条观测样本 + MMFE UWM state input
uwm_environmental_evidence_bundle_2024_07_multisource: Open-Meteo + GEE ERA5/CAMS + OpenAQ 多源环境证据融合
uwm_scene_conditioned_dynamic_advantage_2024_07_multisource: 多源环境状态驱动的 known-effect dynamic advantage 评估
gee_admin_environment_2024_07_01_07: 1017 个乡镇/街道 representative point 的 GEE ERA5/CAMS 环境代理 + MMFE UWM state input
admin_exposure_equity_2024_07_01_07: GHSL 人口/建成区 + GEE 行政单元环境代理联结得到的 exposure-equity panel 和 top 50 planner proxy units
admin_planner_benchmark_2024_07_01_07: top 10 proxy units 的 UWM rollout planner benchmark，known-effect regret reduction = 0.0024004434
osm_services_geometry_2026_07_05: 重庆中心 bbox 200 个带坐标 OSM amenity 节点，8 类服务设施代理 + MMFE UWM state input
admin_service_accessibility_2026_07_05: OSM 服务点归属到 36 个 bbox 相交行政单元；25 个有样本服务点，11 个为 sample gap
admin_livability_target_2024_07_2026_07_05: exposure-equity + service sample gap 复合目标面板；36 个行政单元联结，3 个 composite target candidate
admin_livability_planner_benchmark_2024_07_2026_07_05: 复合目标 UWM planner benchmark，known-effect regret reduction = 0.0024004434
openaq_temporal_benchmark_2018_10: OpenAQ 600 条真实小时观测的 temporal holdout；6 个污染物上动态状态更新均优于 `static_train_mean` + `static_last_train_observation` 传统静态 baseline suite；180 个 holdout 时点中 150 个动态模型误差更小；总体 sign test vs static mean p = 3.17e-23、vs static last-train p = 7.02e-28；PM2.5 相比 best static baseline 的 MAE 从 9.466667 降到 2.4，p = 2.82e-6；时间顺序负控通过，确定性乱序后 6/6 个污染物的 ordered online update 更优，平均 MAE advantage = 2.572222；已接入 `track2_submission.build_track2_readiness_matrix` 的 `observed_validation_readiness` 机器门控，明确 `temporal_state_prediction_suite_significant_at_0_05 = true`、`temporal_order_negative_control_passed = true` 且 `policy_outcome_superiority_ready = false`
tap_pm25_external_dynamics_2026_07_06: TAP 真实 1km PM2.5 日格网 external transition gate；sampled series = 10000，holdout = 40000；best method = `spatial_residual_delta_ridge`，MAE = 7.003808，强于 best static MAE 9.309192 和 best non-spatial dynamic MAE 7.011689，paired win rate vs best non-spatial dynamic = 0.5077；future-label leakage guard 和 temporal-order control 通过；但 neighbor shuffle negative control 不差于真实邻接，因此 `spatial_negative_control_passed = false`，只支持 `tap_external_temporal_dynamics_advantage_without_spatial_claim`
causal_policy_evidence_2026_07_06: Paper6 真实结果产物已接入 UWM policy evaluator 诊断层；ArcGIS SCI Plus county report 使用 3108 input rows / 3044 trimmed rows，ArcGIS 3.7 documented ERF parity MAE = 0.015153286175193017；SCCA county credibility = strong_support；重庆 UHI analysis manifest 有 5000 sample rows 和 107035 buildings；`algorithmic_causal_diagnostic_ready = true` 但 `observed_policy_outcome_superiority_claim = false`
external_observed_holdout_suite_2026_07_06: OpenAQ station temporal holdout 与 TAP gridded temporal holdout 已聚合为双源外部观测 suite；OpenAQ 600 observations / 180 holdout / 150 dynamic wins，TAP 10000 sampled grid series / 40000 holdout / adaptive online MAE 7.01169 vs static train mean MAE 9.309192；`external_observed_holdout_ready = true` 但 `scene_aligned_station_calibrated_air_quality_holdout_ready = false`
station_aligned_air_quality_holdout_2026_07_06: OpenAQ 上清寺站历史 PM2.5 观测与最近 TAP 1km grid 的 station-aligned holdout；100 observations、70 train / 30 holdout、nearest TAP tile `075` grid `62722`、距离 446.95923 m；raw TAP MAE = 5.463333，优于 static train mean MAE = 12.895238 和 static last observation MAE = 9.466667；linear station calibration MAE = 9.608119，未优于 raw TAP；`historical_station_aligned_holdout_ready = true` 但 `scene_aligned_station_calibrated_air_quality_holdout_ready = false`
data_calibrated_mechanism_table_2026_07_06: UWM simulator action-effect mechanism table 已由真实/代理证据校准；OpenAQ observation count = 600，TAP holdout = 40000，station-aligned observations = 100，NOAA scene weather observations = 224，admin livability rows = 36；traffic air-pollution delta = -0.216，green heat delta = -0.2304，service accessibility delta = 0.221044；`data_calibrated_mechanism_ready = true` 但 `observed_policy_outcome_superiority_claim = false`
data_calibrated_planner_replay_2026_07_06: UWM Graph-MDP planner 已使用 data-calibrated mechanism table 重放；transition count = 355，best sequence reward = 0.017180838，static single-step reward = 0.003837146，advantage = 0.013343692；offline learned rollout holdout reward MAE = 0.0001991，train-mean baseline MAE = 0.002339847；接入 scene-aligned PM2.5 conformal uncertainty 后，best risk-adjusted reward = 0.016111838，static risk-adjusted reward = 0.003334625，risk-adjusted advantage = 0.012777213；`data_calibrated_planner_replay_ready = true`、`risk_calibrated_planner_replay_ready = true`，但 `observed_policy_outcome_superiority_claim = false`
scene_aligned_gridded_air_quality_holdout_2026_07_06: CHAP admin representative points + TAP daily 1 km PM2.5 scene-aligned gridded holdout；36 admin units、144 holdout predictions；best method = `spatial_idw_message_reconstruction`，MAE = 1.058085，优于 static train mean MAE = 2.783102，spatial shuffle negative control passed；90% split-conformal interval coverage = 0.944444，UWM interval score = 5.559385 vs static interval score = 13.7；`scene_aligned_gridded_air_quality_holdout_ready = true` 但 `scene_aligned_station_calibrated_air_quality_holdout_ready = false`
multisource_livability_scene_2026_07_06: UWM renderer 已把 36 个 admin-unit livability candidates 与 admin exposure/equity、service accessibility、GHSL population/built-surface、GEE admin environment、TAP/CHAP scene PM2.5、admin spatial graph、Unicom latent mobility graph 和 OSM mobility network proxy 合成统一 state scene；source-gated air-quality head 在 leave-one-admin-out TAP scene PM2.5 mean 任务上 MAE = 0.949891，优于 best single-source MAE = 0.952794；`multisource_livability_scene_ready = true` 但 `observed_policy_outcome_superiority_claim = false`
osm_admin_mobility_crosswalk_2026_07_06: OSM Overpass highway nodes/ways 已用 admin bbox midpoint rule 归属到 36 个 admin-unit livability candidates；assigned road segments = 45449；service-accessibility head 在 leave-one-admin-out OSM service point count 任务上 MAE = 12.887057，优于 best static baseline MAE = 14.028006；`osm_admin_mobility_crosswalk_ready = true` 但 `observed_policy_outcome_superiority_claim = false`
data_foundation_evidence_gate_2026_07_05: 证据门已汇总 OpenAQ temporal state、TAP external transition、external observed holdout suite、station-aligned air-quality holdout、scene-aligned gridded air-quality holdout、data-calibrated mechanism table、data-calibrated planner replay、learned rollout、livability intervention package、本地规划数据、行政邻接图和 Paper6 causal diagnostic evidence；`observed_state_prediction_superiority_claim = true`、`external_observed_state_prediction_superiority_claim = true`、`external_temporal_transition_superiority_claim = true`、`observed_policy_outcome_superiority_claim = false`、`empirical_superiority_claim = false`
openmeteo_history_2018_10_17_23: Open-Meteo keyless public API 已下载 OpenAQ temporal benchmark 同期重庆中心点天气上下文；weather hourly = 168、daily = 7；air-quality API 返回 168 个时间戳但污染物值全为 null，因此只登记为 meteorology context，不作为空气污染证据
ghsl: 2020 population + built-surface 4326 30ss tiles R6/R7 C29/C30
ghsl_admin_alignment: 1017 township/street zonal proxy rows + MMFE UWM state input
admin_units: xiangzhen.shp 提取的重庆乡镇/街道治理单元
worldpop: 中国人口产品目录与 2020 全国 100m GeoTIFF 文件规模记录
openaq: 失败记录，v3 API 需要 X-API-Key
```

## 3.2 世界模型证据 readiness

机器生成产物：

```text
docs/reports/uwm_track2_readiness_2026_07_06/uwm_track2_readiness_matrix.json
docs/reports/uwm_track2_readiness_2026_07_06/uwm_track2_readiness_summary.md
```

当前系统级结论：

```text
system_level_superiority_summary = bounded_state_prediction_and_transition_advantage_without_policy_outcome_superiority
overall_claim_ceiling = bounded_support
traditional_method_comparison_ready = true
policy_outcome_superiority_ready = false
empirical_superiority_claim = false
```

允许进入报告的 bounded claims：

```text
observed_temporal_state_prediction_advantage_over_static_baseline_suite
tap_external_temporal_dynamics_advantage_without_spatial_claim
learned_world_model_rollout_improves_imagined_static_and_one_step_baselines
paper6_arcgis_sci_plus_real_artifact_causal_diagnostic_ready
external_observed_state_prediction_advantage_over_static_baseline_suite
historical_station_aligned_tap_pm25_beats_static_station_baselines
data_calibrated_simulator_mechanism_replaces_hardcoded_coefficients
data_calibrated_planner_replay_advantage_over_static_heuristic
risk_calibrated_planner_replay_advantage_over_static_heuristic
scene_aligned_gridded_pm25_spatial_message_advantage_over_static_baselines
scene_aligned_gridded_pm25_conformal_uncertainty_advantage_over_static_baseline
multisource_livability_scene_air_quality_head_beats_single_source_baselines
osm_admin_mobility_crosswalk_service_accessibility_head_beats_static_baselines
```

不能进入报告的强声明：

```text
observed_policy_outcome_superiority
spatial_attribution_for_tap_external_transition
overall_empirical_policy_superiority
```

剩余 gates：

```text
observed_policy_outcome_required
scene_aligned_station_calibrated_air_quality_holdout_required
synthetic_proxy_boundary_must_remain_visible
```

## 4. 当前必须继续推进的事项

1. 起草完整初评研究报告：
   - 研究问题；
   - 数据来源；
   - 世界模型方法；
   - known-effect 动态优势和 planner regret 结果；
   - 当前不能声明的边界；
   - 城市科学意义。

2. 推进数据驱动验证：
   - 将 machine-readable `world_model_evidence_readiness` 章节写入初评研究报告；
   - 补 station-calibrated observed air-quality holdout 或权威城市栅格；
   - 补 observed policy outcome validation data；Paper6 causal diagnostic 已完成接入，但不能替代真实政策 outcome holdout；
   - 历史 station-aligned holdout 已证明 TAP nearest-grid 在 2018 OpenAQ 上清寺站 PM2.5 holdout 上优于 station static baselines，但下一步仍需要补 2024 scene-aligned station-calibrated observed holdout 或权威城市栅格，否则不能宣称 2024 场景真实观测意义上优于传统方法；
   - 将 data-calibrated planner replay 继续推进到 observed policy outcome / OPE 验证管线，但不能把 planner replay 本身表述为政策 outcome 证明。

3. 保留 AI 协作过程证据：
   - 每次数据选择、模型修改、失败测试、claim 降级都写入 research log；
   - 不把 synthetic 或 public proxy 数据升级为真实城市结论。

## 5. 与 UWM 主线的关系

UWM 是 Geospatial World Model 在城市科学方向的实例。城市宜居性分析只是当前业务场景。Track 2 Vibe Research 的提交材料必须围绕以下链条组织：

```text
GWM
-> UWM
-> 城市宜居性世界模型
-> renderer / simulator / planner
-> evidence-gated evaluation
-> 城市科学发现与 AI 协作记录
```

因此，下一步不是单纯写报告，也不是只补数据，而是：

```text
用数据驱动验证把当前 known-effect fixture 结果推进到可复现城市科学研究发现。
```
