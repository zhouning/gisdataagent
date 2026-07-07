# UWM Data Foundation Coverage Audit

日期：2026-07-04；更新：2026-07-06

## 1. 审计目的

TAP status update on 2026-07-06: local TAP PM2.5 package is now parsed and registered as
`tap_pm25_observed_gridded_chongqing_2018_2024`. It strengthens `air_pollution_exposure`
from TAP-pending to TAP gridded available and supports a bounded gridded temporal
state-prediction benchmark. It does not close the observed policy outcome gate because TAP is
a multisource gridded product, not a station-observed intervention outcome.
The scene-aligned gridded PM2.5 holdout adds a CHAP-admin-point to TAP daily 1 km
state-reconstruction benchmark: spatial IDW message reconstruction improves over static
baselines, but it remains gridded and not station-calibrated.
The new TAP external dynamics holdout is an explicit transition-layer gate: residual-delta
transition ridge slightly beats the adaptive non-spatial online baseline on the 40,000-point
holdout (MAE 7.003808 vs 7.011689; paired win rate 0.5077). It is `bounded_support`
for temporal transition improvement, but neighbor shuffle is not worse, so it does not
support spatial-attribution or observed policy-outcome superiority.

本文件记录 UWM-Livability 数据基础的角色级覆盖状态。它不是简单的数据清单，而是回答：

```text
当前数据基础能否支撑 UWM renderer / simulator / planner / evaluation？
当前数据基础能否支撑“比传统方法更强”的实证声明？
```

## 2. 当前审计结果

Manifest：

```text
docs/reports/uwm_data_foundation_manifest.csv
```

审计摘要：

```text
manifest_valid = true
manifest_row_count = 72
missing_required_roles = []
claim_ceiling = fragile
```

角色覆盖：

| UWM 数据角色 | 覆盖等级 | 当前含义 |
| --- | --- | --- |
| urban_form | usable_real | 已有建筑、AOI、历史文化街区、璧山 DLTB、GHSL 代理等城市形态/土地利用数据 |
| heat_exposure | usable_real | 已有 DEM、UHI、ERA5 planned proxy 等热暴露线索 |
| air_pollution_exposure | proxy_available | 已有 Open-Meteo 历史空气质量代理、Open-Meteo 36 个候选行政单元代表点空气质量代理、GEE CAMS/NRT 中心点代理、GEE 行政单元代表点代理、GEE livability candidate polygon zonal proxy、CHAP 2024-07 月均 1km PM2.5、OpenAQ 真实站点观测代理和 MMFE state input；OpenAQ 2024-07 attempt 为 0 measurements，TAP gridded PM2.5 已解析可用，但重庆 2024 场景 station-calibrated observed air-quality holdout 仍缺 |
| service_accessibility | usable_real | 已有高德 POI 1,194,351 点、百度 AOI 26,292 面、历史文化街区 20 面，并补 OSM 200 点历史样本、786 个 amenity node/way/relation center 完整 bbox 抽取、36 个 bbox 相交行政单元服务面板和 MMFE state input |
| mobility_graph | usable_real | 已有本地 OSM roads 50,366 线、OSM complete bbox highway topology：6,762 条 highway ways、42,058 个 coordinate nodes、45,468 条图边；另新增联通职住通勤 2,120 行、百度搜索指数 325 条和 UWM Unicom latent mobility graph 作为 `mobility_activity` 上下文 |
| population_vulnerability | usable_real | 新增本地规划样例中的重庆区县人口统计 Excel：2021 年 40 行，其中 39 个区县、1 个全市总计；同时 GHSL 2020 人口/建成区公开瓦片已完成重庆乡镇/街道分区统计；本轮新增总量守恒 fitted population downscaling：3290.08 万输入人口 = 3290.08 万输出人口，852 fitted rows |
| administrative_units | usable_real | 本地 `xiangzhen.shp` 原始层按 `.shx` 推算为 43,655 条记录；UWM 已提取重庆乡镇/街道 1,017 个治理单元；因来源许可、年代和历史区县名未核验，claim ceiling 为 fragile |
| spatial_adjacency_graph | usable_real | 已由全量 1,017 个重庆乡镇/街道行政单元派生 2,847 条行政边界邻接边和 0 个孤立节点；支持 Graph-MDP 空间状态和 simulator 邻接溢出，但不是道路/mobility graph |
| meteorology | proxy_available | 已有 Open-Meteo 历史气象代理、GEE ERA5 中心点代理、GEE 行政单元代表点代理、GEE livability candidate polygon zonal proxy、NOAA ISD 江北站 2024-07 观测气象和 MMFE state input；role audit 硬 blocker 已解除，但全城 zonal/grid 观测校准仍是空间代表性弱点 |
| remote_sensing_state | usable_real | CLCD、CLCD 分类字典与 AlphaEarth / GeoFM prior 可支撑状态表征 |
| causal_evidence_gate | usable_real | 已接入 Paper6 真实结果产物：ArcGIS SCI Plus county parity、SCCA county credibility 和重庆 UHI analysis manifest；支持 UWM policy evaluator 的因果诊断能力，但不支持 observed policy outcome superiority |
| external_observed_holdout | usable_real | 已接入 OpenAQ station temporal holdout 和 TAP gridded temporal holdout 双源真实外部观测 suite；支持 state-prediction over static baseline 的 bounded claim，但不替代 2024 scene-aligned station-calibrated holdout 或 policy outcome |
| station_aligned_air_quality_holdout | usable_real | 已接入历史站点对齐 PM2.5 holdout：OpenAQ 上清寺站 100 条小时 PM2.5 观测对齐最近 TAP 1km grid；raw TAP holdout MAE 5.463333，优于 station static train mean 12.895238 和 static last observation 9.466667；但 2024-07 OpenAQ scene attempt 为 0 measurements，因此不关闭 scene-aligned station-calibrated gate |
| scene_aligned_gridded_air_quality_holdout | proxy_available | 已接入 CHAP admin representative points + TAP daily 1km PM2.5 gridded holdout；36 个行政候选单元、144 个 holdout predictions，spatial IDW message reconstruction MAE 1.058085 vs static train mean MAE 2.783102；90% split-conformal interval coverage 0.944444，UWM interval score 5.559385 vs static 13.7；支持 bounded gridded state reconstruction 和 uncertainty calibration，但不是 station-calibrated observation 或 policy outcome |
| data_calibrated_mechanism_table | usable_real | 已接入由 OpenAQ/TAP/NOAA/admin panel 校准的 simulator mechanism table；traffic air-pollution delta = -0.216、green heat delta = -0.2304、service accessibility delta = 0.221044；替代硬编码机制先验，但不支持 observed policy outcome superiority |
| data_calibrated_planner_replay | usable_real | 已接入基于 data-calibrated mechanism table 的 Graph-MDP planner replay；best two-step sequence reward = 0.017180838，高于 static single-step reward = 0.003837146，learned rollout holdout MAE = 0.0001991，优于 train-mean baseline MAE = 0.002339847；进一步接入 scene-aligned gridded PM2.5 conformal uncertainty，使用同一 UWM uncertainty penalty 后 risk-adjusted advantage = 0.012777213；支持 bounded planner replay 和 risk-calibrated planner replay claim，但不支持 observed policy outcome superiority |
| multisource_livability_scene | usable_real | 已接入 9 类真实/公开代理数据源并渲染 36 个 admin-unit livability state：admin exposure/equity、service、GHSL、GEE、TAP/CHAP scene PM2.5、admin spatial graph、Unicom latent mobility 和 OSM mobility context；source-gated air-quality head 在 leave-one-admin-out TAP scene PM2.5 mean 任务上 MAE 0.949891，优于 best single-source 0.952794；支持 bounded multisource renderer/air-quality-head claim，但不支持完整宜居性 outcome 或 observed policy outcome superiority |
| osm_admin_mobility_crosswalk | usable_real | 已用 OSM Overpass raw highway nodes/ways 与 admin spatial graph bbox 生成单元级 road segment crosswalk；45,449 个 road segments 归属到 36 个候选行政单元；service-accessibility LOO head MAE 12.887057，优于 best static baseline 14.028006；支持 bounded mobility/accessibility head claim，但不是精确 polygon overlay、出行时间或 policy outcome |

## 3. 阻止实证优越性声明的角色

当前 blocker：

```text
air_pollution_exposure
```

原因：

- `air_pollution_exposure` 已有 Open-Meteo 历史点位代理、GEE CAMS/NRT 点位代理、GEE livability candidate zonal proxy、CHAP 2024-07 月均 1km PM2.5、TAP observed gridded PM2.5、TAP external dynamics bounded transition gate、OpenAQ 真实站点观测代理和 OpenAQ temporal state benchmark；但 Open-Meteo/CAMS/CHAP/TAP 是 modeled 或 multisource gridded proxy，OpenAQ 2024-07 scene attempt 为 0 measurements，OpenAQ temporal benchmark 和 TAP gridded temporal benchmark 只支撑状态预测层 holdout，TAP external dynamics 只支持有界 temporal transition improvement，仍不支持空间消息归因优于非空间动态基线；这些都不是 2024-07 station-calibrated scene holdout 或政策 outcome holdout；
- `semi_synthetic_air_quality_scene_2024_07` 已在 OpenAQ 2024 scene observed 数据缺失后生成，可用于 stress test/negative control，但由于是 CAMS zonal base + OpenAQ 2018 temporal anomaly synthesis，不能解除 air_pollution_exposure empirical blocker；
- `tap_like_pm25_scene_v2_2024_07` 已在 TAP 审核通过前生成，可用于 UWM 开发、simulator/planner/OPE 压力测试；它由 CHAP 月均锚定、Open-Meteo 小时时序、OpenAQ 历史扰动、NOAA ISD 气象调整和 GEE 可选空间上下文构成，6048 条记录，CHAP anchor max abs error = 0.0 ug/m3；但它明确是 `semi_synthetic` 和 `not_tap_data`，不能解除 air_pollution_exposure empirical blocker；
- `population_vulnerability` 已有本地区县人口统计、GHSL 行政单元代理统计、MMFE state input 和 fitted population downscaling，因此不再是当前数据基础补齐 blocker；但 fitted_proxy 仍不能替代本地人口普查、乡镇/街道权威人口、2024 场景人口或真实观测 holdout；
- `meteorology` 已补入 NOAA ISD 575160-99999 江北站 2024-07-01 至 2024-07-07 观测气象，解析出 224 条 scene-window 记录，其中 temperature 224、pressure 56、wind 224；因此 role audit 中不再作为硬 blocker。但它是单站/混合 FM-12 FM-15 报文，不是全城格网或面状气象校准。
- `spatial_adjacency_graph` 已由本地全量重庆行政边界派生，可支撑当前 Graph-MDP 的空间邻接状态；但它不替代交通网络、OD、通勤或 travel-time accessibility。
- `mobility_activity` 新增了真实本地联通职住通勤 CSV、百度搜索指数 FileGDB 和由联通 OD 聚合的 latent mobility graph；但联通缺格网几何字典，百度搜索指数是搜索兴趣而非出行观测，latent graph 无坐标，三者不能解除 travel-time/traffic-flow 缺口。
- `administrative_units` 可支撑治理单元对齐，但由于 `xiangzhen.shp` 的官方年代、许可和现代区县名称 crosswalk 尚未核验，当前把总体 claim ceiling 降为 `fragile`。
- `causal_evidence_gate` 已由 Paper6 真实产物补强：ArcGIS SCI Plus documented continuous REGRESSION + MATCHING + ERF 模式与 ArcGIS 3.7 导出曲线 parity MAE = 0.015153286175193017；SCCA county credibility = strong_support；重庆 UHI analysis manifest 记录 5000 样本和 107035 栋建筑。它解除“因果诊断实现缺口”，但不是本地 UWM 策略实施后的观测 outcome。
- `external_observed_holdout` 已由 OpenAQ station temporal benchmark 和 TAP gridded temporal benchmark 组成双源外部观测 suite：OpenAQ 600 条观测/180 holdout 中 150 个动态 wins；TAP 10000 个 sampled grid series/40000 holdout 中 adaptive online MAE = 7.01169，优于 static train mean MAE = 9.309192。它解除“外部观测 holdout 缺口”，但仍不是 2024 scene-aligned station-calibrated station holdout。
- `station_aligned_air_quality_holdout` 已把 2018-10 OpenAQ 上清寺 PM2.5 真实站点小时观测与 TAP nearest-grid 对齐：100 条观测、70 train / 30 holdout、nearest TAP tile `075` grid `62722`，距离 446.95923 m。raw TAP nearest-grid holdout MAE = 5.463333，优于 station static train mean MAE = 12.895238 和 static last observation MAE = 9.466667；linear station calibration MAE = 9.608119，未优于 raw TAP。该结果支持 `historical_station_aligned_tap_pm25_beats_static_station_baselines` 的 bounded claim，但仍不是 2024-07 scene-aligned station-calibrated holdout。
- `scene_aligned_gridded_air_quality_holdout` 已把 36 个 CHAP 2024-07 admin representative points 与 TAP 2024-07-01 至 2024-07-07 daily 1 km PM2.5 grid 对齐：144 个 holdout predictions 中，`spatial_idw_message_reconstruction` MAE = 1.058085，优于 `static_train_mean` MAE = 2.783102，MAE reduction = 1.725017，并通过 reverse-coordinate spatial shuffle 负控。新增 split-conformal uncertainty head 使用 108 个训练期 calibration residuals，90% UWM interval coverage = 0.944444，UWM interval score = 5.559385，static interval score = 13.7。该结果支持 `scene_aligned_gridded_pm25_spatial_message_advantage_over_static_baselines` 和 `scene_aligned_gridded_pm25_conformal_uncertainty_advantage_over_static_baseline` 的 bounded claim，但仍不是 station-calibrated observation 或 policy outcome。
- `data_calibrated_mechanism_table` 已将 simulator action-effect coefficients 从硬编码表推进到数据校准机制表：OpenAQ observed state、TAP transition、station-aligned PM2.5、NOAA 2024 气象和 admin livability panel 共同给出 air/heat/service/equity scale。它支持 `data_calibrated_simulator_mechanism_replaces_hardcoded_coefficients` 的 bounded claim，但不是干预后观测 outcome，也不是 causal policy effect。
- `data_calibrated_planner_replay` 已将上述机制表接入 Graph-MDP multi-step planning 和 offline learned rollout：同一 36 个 admin livability candidates 上，best two-step model-based search reward 0.017180838 高于 static single-step heuristic 0.003837146；learned rollout holdout reward MAE 0.0001991 低于 train-mean baseline 0.002339847。新增 risk-calibrated replay 将 scene-aligned gridded PM2.5 split-conformal interval score 转成同一空气质量不确定性惩罚，同时作用于 model-based plan 和 static baseline；best risk-adjusted reward 0.016111838，static risk-adjusted reward 0.003334625，risk-adjusted advantage 0.012777213。它支持 `data_calibrated_planner_replay_advantage_over_static_heuristic` 和 `risk_calibrated_planner_replay_advantage_over_static_heuristic` 的 bounded claim，但仍是 model-internal replay 证据，不是 observed policy outcome 或真实政策反事实。
- `multisource_livability_scene` 已把可对齐数据源真正接入 renderer：36 个 candidate admin units 与 exposure/equity、service、GHSL、GEE、TAP/CHAP scene PM2.5 和 admin graph 全部 36/36 对齐；Unicom latent mobility 和 OSM mobility 作为 scene context 进入 source coverage，但因缺少 grid/road-to-admin crosswalk 暂不投影到单元分数。source-gated air-quality head 使用 CHAP+CAMS 预测 TAP scene PM2.5 mean，LOO MAE 0.949891，优于 CHAP-only 0.952794、CAMS-only 1.010687 和 LOO city mean 1.009252；paired wins vs CHAP = 20、losses = 16。该 claim 很窄，且 spatial interaction negative control 未通过，因此不能说完整多源宜居性已经在真实 outcome 上优于传统方法。
- `osm_admin_mobility_crosswalk` 已把 OSM mobility network 从 scene context 推进到 admin-unit state：使用 42,058 个 coordinate nodes 和 6,762 条 highway ways 解析 road segments，按 segment midpoint inside bbox 且 smallest bbox area rule 单归属到 36 个 candidate admin units；assigned segment count = 45,449，unassigned = 19。service-accessibility head 使用 road segment count 预测真实 OSM service point count，LOO MAE = 12.887057，优于 city mean 14.152381、GHSL population 14.760068 和 GHSL built-surface 14.028006；MAE reduction vs best static = 1.140949，paired wins/losses vs best static = 20/16。该结果支持 `osm_admin_mobility_crosswalk_service_accessibility_head_beats_static_baselines` 的 bounded claim，但 bbox midpoint assignment 仍不是精确 polygon overlay，也不是网络出行时间或 observed policy outcome。

因此当前可以继续支持：

```text
known-effect dynamic advantage
known-effect planner advantage
fragile-to-bounded UWM architecture claim with explicit administrative-boundary caveat
```

当前不能支持：

```text
observed holdout empirical superiority over traditional methods
real policy outcome superiority
```

## 4. 公开数据补齐队列

下一步 acquisition queue：

```text
download_or_mount_air_pollution_public_proxy
```

对应 manifest rows：

- `cams_air_pollution_proxy`
- `openaq_air_quality_proxy`
- `openmeteo_weather_current_proxy`
- `openmeteo_air_quality_current_proxy`
- `chap_pm25_monthly_1km_2024_07_proxy`
- `tap_pm25_china_access_pending`
- `worldpop_population_chongqing_proxy`
- `ghsl_population_built_chongqing_proxy`
- `ghsl_admin_zonal_proxy_alignment`
- `era5_meteorology_chongqing`
- `chongqing_township_admin_units_local`
- `chongqing_admin_spatial_adjacency_graph_2026_07_05`
- `uwm_fitted_admin_population_downscaling_2021`
- `uwm_unicom_latent_mobility_graph_2023`
- `noaa_isd_chongqing_weather_observation_2024_07`

## 4.1 当前下载阻塞说明

当前 acquisition blocker 摘要：

```text
requires_user_credentials = []

requires_runtime_secrets = [
  openaq_air_quality_proxy
]

requires_source_decision = [
  air_pollution_exposure,
  tap_pm25_china_access_pending
]

can_attempt_public_download = [
  era5_meteorology_chongqing,
  cams_air_pollution_proxy,
  openaq_air_quality_proxy,
  openmeteo_weather_current_proxy,
  openmeteo_air_quality_current_proxy,
  chap_pm25_monthly_1km_2024_07_proxy,
  noaa_isd_chongqing_weather_observation_2024_07,
  worldpop_population_chongqing_proxy,
  ghsl_population_built_chongqing_proxy,
  osm_services_chongqing_public_proxy,
  osm_services_complete_bbox_public_proxy,
  osm_mobility_network_complete_bbox_public_proxy
]
```

不能静默替换的规则：

```text
no_silent_substitution = true
```

解释：

- ERA5/CAMS 已确认可通过本机 GEE 认证访问，本轮已完成重庆中心点采样、1017 个重庆乡镇/街道 representative point 采样，并进一步完成 36 个 admin livability 候选行政面的 simplified-polygon zonal mean；
- Open-Meteo forecast / air-quality API 已在本机用重庆坐标 curl 验证可访问，适合作为 UWM live environmental proxy；
- Open-Meteo current payload 已有标准化入口：`data_agent.uwm.openmeteo_proxy.build_openmeteo_environmental_proxy`；
- Open-Meteo historical weather / air-quality 已在本机下载 2024-07-01 至 2024-07-07 重庆中心点代理数据，生成 168 小时气象/空气质量记录和 `mmfe.uwm_state_input.v1`；
- Open-Meteo historical weather 已在本机下载 2018-10-17 至 2018-10-23 重庆中心点代理数据用于对齐 OpenAQ temporal benchmark；同时间窗 air-quality API 只返回时间戳，污染物值全为 null，已标记为空气质量缺测；
- Open-Meteo 不能直接替代 ERA5/CAMS 的长期历史栅格，也不能替代站点校准 observed holdout；
- NOAA ISD 575160-99999 2024 gzip 已下载，`isd-history.csv` 已核验该站为 JIANGBEI / ZUCK；UWM 已解析 2024-07-01 至 2024-07-07 共 224 条观测，作为 scene-aligned meteorology observed station holdout。它解除 meteorology role audit 硬 blocker，但不能替代全城格网/面状气象校准，也不能替代空气质量或政策 outcome；
- OpenAQ v3 已用运行时 key 下载重庆中心 25 km 内站点样本；key 未入库。当前可用观测覆盖 2018-10-17 至 2021-08-09，不覆盖 2024-07 场景 holdout；本轮使用 scene datetime window 重新尝试 2024-07-01 至 2024-07-07，返回 15 locations、90 sensors、0 measurements；已派生 2018-10 temporal state benchmark，动态状态更新在 6 个污染物上均击败 `static_train_mean` 和 `static_last_train_observation`，总体 sign test p 值分别为 3.17e-23 和 7.02e-28，确定性乱序负控显示 6/6 个污染物依赖真实时间顺序，但不构成政策 outcome holdout；
- OpenAQ + TAP 已进一步派生历史站点对齐 PM2.5 holdout：上清寺站 100 条 PM2.5 小时观测对齐最近 TAP 1km grid，raw TAP nearest-grid 在 30 条 holdout 上 MAE = 5.463333，优于 station static train mean 12.895238 和 static last observation 9.466667；但 OpenAQ 2024-07 scene attempt 仍为 0 measurements，因此 scene-aligned station-calibrated air-quality holdout gate 保持打开；
- CHAP ChinaHighPM2.5 2024-07 monthly 1km NetCDF 已从 Zenodo record 15208529 下载并用 `h5py` 解析；UWM 已对 36/36 个 livability candidate admin representative points 做最近邻采样，36 个有效值，PM2.5 均值 16.433 ug/m3。它是公开 AI-fused gridded product，不是 station observation；
- TAP Tracking Air Pollution in China 本地包已解析并登记为 `tap_pm25_observed_gridded_chongqing_2018_2024`：1km PM2.5 rows = 9,451,218，valid rows = 9,422,882，10km species rows = 23,746；5000-series-per-period gridded temporal benchmark 覆盖 10,000 grid series / 40,000 holdout points，best UWM dynamic MAE = 7.01169，best static baseline MAE = 9.309192，MAE reduction = 2.297502，claim boundary = `bounded_support`。同一 TAP 包的 external spatiotemporal dynamics holdout 覆盖 10,000 grid series / 40,000 holdout points；residual-delta transition ridge MAE = 7.003808，adaptive online dynamic baseline MAE = 7.011689，static train mean MAE = 9.309192，paired win rate = 0.5077，时间顺序旋转负控变差 1.585932 MAE；但 neighbor shuffle control 不变差，因此 supported claim = `tap_external_temporal_dynamics_advantage_without_spatial_claim`，claim boundary = `bounded_support`，且不能作为空间归因或 observed policy outcome 证据。TAP 是多源融合格网产品，不是 station observation 或 observed policy outcome；
- WorldPop 国家目录已下载，2020 中国 100m GeoTIFF 经 HEAD 探测为约 4.98GB，当前未直接下载；进一步通过 7897 代理探测 WorldPop Global2 R2025A，完整人口 raster zip 为 5.2GB，未下载；已下载 15,197 byte 的 Global2 country/type metadata CSV，China 行显示 c.2020 round data type 为 Census，但该 CSV 不含人口值，不能作为 UWM 人口数据使用；
- 本地规划样例已核实 `08重庆市各区县人口规模表格数据/重庆市各区县人口规模数据.xlsx`，来源字段为 `重庆市统计年鉴2022`，共 40 行：1 行全市总计、39 行区县；已生成 normalized proxy、CSV、MMFE state input 和 canonical observation。它是区县级统计，不是乡镇/街道格网人口，也不是 2024 场景人口或政策 outcome；
- GHSL 2020 人口与建成区 4326 30ss 瓦片已下载 8 个 zip，覆盖重庆全市行政范围，全部通过 zip 校验，并生成乡镇/街道级代理分区统计：1017 个行政单元，1013 个有人口代理值，1011 个有建成区代理值；
- OSM Overpass 已保留早期 200 个带坐标 amenity 节点样本，并进一步下载重庆中心 bbox 的完整 amenity node/way/relation center 抽取：786 个 amenity 元素、163 个 healthcare/education essential service 代理点；同时下载完整 highway way bbox 抽取：48,820 个 OSM elements、42,058 个 coordinate nodes、6,762 条 highway ways、45,468 条图边、57 个连通分量。它改善服务/道路数据基础，但仍不是全市完整 POI、网络出行时间、OD 或交通流观测。
- 本地规划院 zip 已重新实扫并写出 `data/uwm_public_proxy/chongqing_central/local_planning_zip_audit_2026_07_05/snapshot_manifest.json`；新增/补画像包括高德 POI 1,194,351 点、百度 AOI 26,292 面、联通通勤 2,120 行、百度搜索指数 325 条、历史文化街区 20 面、璧山 DLTB 101,657 面、璧山 2019 用地台账 1,438 个非空工作表行和福禄镇村规数据库 8,050 个要素。联通格网几何字典仍缺，不能把通勤表直接当成空间 OD 面或 travel-time surface。
- UWM fitted gap filling 已生成 `data/uwm_public_proxy/chongqing_central/fitted_gap_filling_2026_07_05/snapshot_manifest.json`：人口下推层 852 行，3290.08 万输入人口和输出人口完全守恒；联通潜在通勤图 1,067 条有向边、756 个节点。两个资产都标记为 `fitted_proxy` 和 `exploratory_only`，不能解除 empirical superiority blocker。
- Graph-MDP model-based graph search report 上一版已基于 admin livability proxy panel 生成：8 个 proxy admin units、2-step beam search、109 条 replay transitions；known-effect reward 为 0.025056312，高于传统静态单步启发式 0.007987516，但该 graph 是 proxy priority similarity，不是真实空间邻接，且不是 observed policy outcome。
- Spatial Graph-MDP model-based graph search report 已基于全量行政空间邻接图生成：源行政单元 1,017 个、全图 2,847 条边、36 个 livability 候选单元诱导出 96 条真实空间边、355 条 replay transitions；known-effect reward 为 0.012346806，高于静态单步启发式 0.001439757，但仍不是 observed policy outcome，也不是 learned PPO/DRL policy。
- Offline graph value model report 已基于上述 355 条 simulator replay transitions 生成：ridge value model 的 holdout MAE 为 0.000165326，train-mean baseline MAE 为 0.002418188；这只支持 offline replay value fitting claim，不支持真实政策 outcome superiority。
- Offline world-model policy report 已基于上述 355 条 simulator replay transitions 生成：action-conditioned reward+dynamics model 的 holdout reward MAE 为 0.000165324，train-mean baseline MAE 为 0.002418188；保守策略在 replay 中的 mean reward 为 0.009041181，高于静态启发式 0.007839757。它补上 learned dynamics/reward + policy improvement 的世界模型 RL 切片，但仍不支持 observed policy outcome superiority。
- Learned world-model rollout planner report 已基于同一 action-conditioned reward+dynamics model 生成：2-step imagined rollout selected sequence 为 `increase_green_infrastructure-江北区|观音桥街道|653` -> `add_community_service-九龙坡区|谢家湾街道|785`；imagined conservative score 为 0.011528613，高于 static 0.00124898 和 one-step learned policy 0.002012933。它补上 learned dynamics + multi-step imagination 的世界模型规划切片，但仍不支持 observed policy outcome superiority。
- Graph-aware world model report 已基于同一 spatial Graph-MDP replay 和 96 条候选行政邻接边生成：graph-aware reward MAE 0.000103937，target-only reward MAE 0.000844982，train-mean reward MAE 0.002418188，reward win rate vs target-only 0.957746479。它补上邻接消息驱动的 action-conditioned dynamics，对 target-only 传统基线形成事实优势，但仍不支持 observed policy outcome superiority。
- Synthetic policy outcome benchmark 已生成同场景 simulator outcome scaffold：learned rollout synthetic reward 0.006346806，static reward -0.004560243，advantage 0.010907049，claim boundary 为 `exploratory_only`。它只能用于 OPE/negative-control 管线联调，不能解除真实政策 outcome blocker。
- Livability intervention package 已生成证据门控城市干预方案包：包含低宜居单元识别、机制解释、干预适宜性、多步 action sequence、前后指标 delta、公平性结论和 evidence boundary；supported proxy claim 为 `business_theory_aligned_learned_rollout_beats_static_proxy_baseline`，claim boundary 为 `exploratory_only`。它是业务方案表达和 OPE/negative-control 脚手架，不是 observed intervention outcome，也不能解除真实政策 outcome blocker。
- Data-foundation evidence gate 已生成：它读取完整 UWM 数据基础和实际产物，不只读取 `real` 标签；OpenAQ observed temporal benchmark 支撑 `observed_state_prediction_superiority_claim = true`，TAP external dynamics holdout 支撑 `external_temporal_transition_superiority_claim = true`，data-calibrated planner replay 支撑 model-internal planner advantage bounded claim，但 `observed_policy_outcome_superiority_claim = false`。该 gate 的作用是防止 synthetic/smoke/proxy 越界，同时允许所有已准备数据按证据等级参与 UWM 开发与评估。

## 5. 对 MMFE 的要求

这些 planned/raw proxy 不能直接进入 simulator。必须经过：

```text
manifest row
-> MMFE profiling / alignment / validation
-> mmfe.uwm_state_input.v1
-> UwmCanonicalObservation.v1
-> UwmRolloutTrace.v1
-> UwmPlanPackage.v1
```

GHSL 人口/建成区已经从 `raw_proxy_available` 升级为 `proxy_available`。Open-Meteo 历史气象/空气质量、GEE ERA5/CAMS 中心点代理、GEE 行政单元代表点代理、GEE livability candidate zonal proxy、CHAP PM2.5、NOAA ISD observed weather 和 OpenAQ 站点观测也已经进入 `proxy_available`。当前只剩 air pollution role 仍因缺 2024 scene station-calibrated observed holdout 而保留 empirical superiority blocker。
