# UWM Public Data Download Log

日期：2026-07-04

更新：2026-07-05 增加 GHSL 行政单元对齐产物。
更新：2026-07-05 增加 Open-Meteo 重庆中心点 2024-07-01 至 2024-07-07 历史气象/空气质量代理。
更新：2026-07-05 修正 ERA5/CAMS 获取路径：通过本机已认证 GEE 完成重庆中心点采样；OpenAQ v3 通过运行时 key 完成站点观测下载，key 未入库。
更新：2026-07-05 增加 Open-Meteo + GEE ERA5/CAMS + OpenAQ 多源环境证据融合 bundle，并生成多源 scene_state / rollout / dynamic advantage artifact。
更新：2026-07-05 增加 1017 个重庆乡镇/街道 representative point 的 GEE ERA5/CAMS 行政单元环境代理，并生成 exposure-equity planner target panel。
更新：2026-07-05 增加 admin planner benchmark，将 top priority proxy units 接入 UWM simulator/planner，与传统静态 top-priority traffic heuristic 做 known-effect regret 对比。
更新：2026-07-05 重新下载带坐标 OSM amenity 样本，生成 service accessibility proxy 和 MMFE state input。
更新：2026-07-05 将 OSM 服务点空间归属到 bbox 相交行政单元，生成 admin service accessibility panel。
更新：2026-07-05 生成 exposure-equity + service sample gap 复合 livability target panel，并运行复合目标 planner benchmark。
更新：2026-07-05 使用 OpenAQ 600 条真实小时观测生成 observed temporal holdout benchmark，证明动态状态更新优于静态均值 baseline。
更新：2026-07-05 增加 CHAP ChinaHighPM2.5 2024-07 monthly 1km NetCDF 下载和 36 个 livability candidate admin representative points 采样。
更新：2026-07-05 增加 NOAA ISD 575160-99999 2024 gzip 与 isd-history 下载，生成 2024-07 江北站 observed weather proxy。
更新：2026-07-05 记录 TAP 账号已申请但仍需审核，当前不作为可用数据。

## 1. 成功下载

| 数据源 | 本地路径 | 状态 | UWM 角色 | Claim 边界 |
| --- | --- | --- | --- | --- |
| Open-Meteo current weather / air quality | `data/uwm_public_proxy/chongqing_central/openmeteo_current/` | raw JSON downloaded and normalized | meteorology; air_pollution_exposure live proxy | bounded support for live/smoke context only |
| Open-Meteo historical weather / air quality | `data/uwm_public_proxy/chongqing_central/openmeteo_history_2024_07_01_07/` | 168 hourly weather/air records plus 7 daily weather records downloaded and normalized | meteorology; air_pollution_exposure point-history proxy | bounded support for state context only; not station holdout |
| GEE ERA5/CAMS environmental proxy | `data/uwm_public_proxy/chongqing_central/gee_era5_cams_2024_07_01_07/` | ERA5 168 hourly records and CAMS 574 records sampled and normalized | meteorology; air_pollution_exposure; simulator_context | bounded support for state context only; not station holdout |
| GEE admin environment proxy | `data/uwm_public_proxy/chongqing_central/gee_admin_environment_2024_07_01_07/` | 1,017 township/street representative points sampled from ERA5/CAMS | meteorology; air_pollution_exposure; admin_environment_context | bounded support for spatial context only; representative point not zonal mean |
| Admin exposure-equity panel | `data/uwm_public_proxy/chongqing_central/admin_exposure_equity_2024_07_01_07/` | 1,017 GHSL admin rows joined with 1,017 GEE admin environment rows; top 50 proxy units exported | equity_evaluation; planner_targeting | bounded support for targeting hypotheses only; not policy effect |
| OpenAQ v3 station observations | `data/uwm_public_proxy/chongqing_central/openaq_station_observations/` | 15 locations, 90 sensors and 600 measurement samples downloaded | air_pollution_exposure; station_validation_context | bounded support as historical station proxy; not 2024 scene holdout |
| OSM Overpass amenity sample | `data/uwm_public_proxy/chongqing_central/osm_services/` | 200 amenity nodes downloaded | service_accessibility public substitute | bounded support after filtering and ODbL attribution |
| OSM Overpass amenity geometry sample | `data/uwm_public_proxy/chongqing_central/osm_services_geometry_2026_07_05/` | 200 coordinate amenity nodes downloaded and classified into 8 service categories | service_accessibility; baseline_context; planner_targeting | bounded support as bbox sample; not network accessibility surface |
| GHSL R2023A 2020 population tiles | `data/uwm_public_proxy/chongqing_central/ghsl/tiles/` | 4 zip tiles downloaded and zip-tested | population_vulnerability raw proxy | raw_proxy_available; not empirical-ready |
| GHSL R2023A 2020 built-surface tiles | `data/uwm_public_proxy/chongqing_central/ghsl/tiles/` | 4 zip tiles downloaded and zip-tested | urban_form; remote_sensing_state raw proxy | raw_proxy_available; not empirical-ready |
| GHSL admin zonal proxy alignment | `data/uwm_public_proxy/chongqing_central/ghsl_admin_alignment/` | 1,017 township/street rows generated from GHSL tiles and admin units | population_vulnerability; urban_form; remote_sensing_state; renderer_alignment | proxy_available; not observed holdout |
| Chongqing township/street admin units | `data/uwm_public_proxy/chongqing_central/admin_units/` | 1,017 features extracted from local `xiangzhen.shp` | administrative_units; governance_unit | fragile until source vintage/license/crosswalk are verified |
| CHAP ChinaHighPM2.5 2024-07 monthly 1km | `data/uwm_public_proxy/chongqing_central/chap_pm25_2024_07/` | NetCDF downloaded from Zenodo record 15208529 and sampled at 36/36 livability candidate admin representative points; PM2.5 avg 16.433 ug/m3 | air_pollution_exposure; planner_targeting; state_dynamics_validation | bounded support as AI-fused gridded proxy; not station observation |
| NOAA ISD Chongqing weather 2024-07 | `data/uwm_public_proxy/chongqing_central/noaa_isd_weather_2024_07_01_07/` | 575160-99999 gzip plus isd-history downloaded; 224 scene-window records parsed for JIANGBEI/ZUCK | meteorology observed station holdout; simulator_context | bounded support for station weather context; not full-city grid |

GHSL selected tiles:

```text
R6_C29
R6_C30
R7_C29
R7_C30
```

These cover the Chongqing administrative bounds derived from `xiangzhen.shp`:

```text
[105.28641493050314, 28.163669704666873, 110.19484375003047, 32.20342230918718]
```

## 2. Partial Or Metadata-Only

| 数据源 | 本地路径 | 状态 | Reason |
| --- | --- | --- | --- |
| WorldPop China population catalog | `data/uwm_public_proxy/chongqing_central/worldpop/` | catalog downloaded | 2020 China 100m GeoTIFF is about 4.98GB; not downloaded as a Chongqing-ready dataset |
| WorldPop Global2 metadata | `data/uwm_public_proxy/chongqing_central/worldpop_global2_metadata/List_of_countries_and_territories_and_types_of_data_used_Global2.csv` | 15,197 byte metadata CSV downloaded | China row says c.2020 round data type = Census; Global2 raster zip is 5.2GB and was not downloaded; metadata has no population values |
| GHSL catalog indexes and copyright | `data/uwm_public_proxy/chongqing_central/ghsl/` | index pages and copyright downloaded | useful for reproducibility and attribution |
| TAP Tracking Air Pollution in China | manifest row `tap_pm25_china_access_pending` | account registration submitted; approval expected in about 2 days | no TAP data downloaded yet; must not be treated as available evidence |

## 2.1 2026-07-05 Alignment Outputs

已生成文件：

```text
data/uwm_public_proxy/chongqing_central/ghsl_admin_alignment/ghsl_admin_alignment_manifest.json
data/uwm_public_proxy/chongqing_central/ghsl_admin_alignment/ghsl_admin_zonal_proxy.csv
data/uwm_public_proxy/chongqing_central/ghsl_admin_alignment/mmfe_uwm_state_input_ghsl_admin.json
data/uwm_public_proxy/chongqing_central/ghsl_admin_alignment/uwm_canonical_observation_ghsl_admin.json
```

对齐摘要：

```text
admin_feature_count = 1017
population_nonzero_units = 1013
built_surface_nonzero_units = 1011
population_tiles = 4
built_surface_tiles = 4
mmfe_state_input_valid = true
canonical_observation_valid = true
empirical_superiority_claim = false
```

## 15. 2026-07-05 OSM Complete Bbox Service And Highway Extract

下载脚本：

```text
scripts/download_uwm_osm_complete_bbox_extract.py
```

数据源：

```text
OpenStreetMap Overpass API
endpoint = https://overpass-api.de/api/interpreter
service query = amenity node/way/relation with out center tags
mobility query = highway ways with child coordinate nodes
bbox = [29.52, 106.50, 29.60, 106.60]
license = ODbL
```

已生成文件：

```text
data/uwm_public_proxy/chongqing_central/osm_complete_bbox_2026_07_05/service/snapshot_manifest.json
data/uwm_public_proxy/chongqing_central/osm_complete_bbox_2026_07_05/service/osm_service_accessibility_proxy.json
data/uwm_public_proxy/chongqing_central/osm_complete_bbox_2026_07_05/service/mmfe_uwm_state_input_osm_service_accessibility.json
data/uwm_public_proxy/chongqing_central/osm_complete_bbox_2026_07_05/mobility/snapshot_manifest.json
data/uwm_public_proxy/chongqing_central/osm_complete_bbox_2026_07_05/mobility/osm_mobility_network_proxy.json
data/uwm_public_proxy/chongqing_central/osm_complete_bbox_2026_07_05/mobility/mmfe_uwm_state_input_osm_mobility_network.json
data/uwm_public_proxy/chongqing_central/admin_service_accessibility_complete_bbox_2026_07_05/uwm_admin_service_accessibility_complete_bbox_panel.json
data/uwm_public_proxy/chongqing_central/admin_livability_target_complete_bbox_2024_07_2026_07_05/uwm_admin_livability_target_complete_bbox_panel.json
```

结果摘要：

```text
amenity_elements = 786
essential_service_proxy_points = 163
admin_units_in_bbox = 36
admin_units_with_service_points = 34
admin_units_without_bbox_extract_points = 2
osm_elements_for_highway_extract = 48820
coordinate_nodes = 42058
highway_ways = 6762
graph_edges = 45468
connected_components = 57
```

过程说明：

```text
第一次 Overpass 下载成功并落盘 raw JSON；
修正文案后再次请求 Overpass 时服务端返回 504；
脚本已增加 --reuse-raw-if-present，并使用第一次成功下载的 raw JSON 重建 normalized proxy、MMFE state input 和 canonical observation；
没有把 504 写成数据缺失，也没有用合成数据替代。
```

边界：

```text
这是中心 bbox 的公开 OSM 完整抽取，不是全重庆市完整 POI；
OSM tag completeness 依赖志愿者贡献；
highway topology 不是 travel-time、OD、拥堵或交通流观测；
service bbox gap 不能解释为真实缺服务。
```

## 16. 2026-07-05 Local Chongqing District Population Statistics

来源文件：

```text
.tmp/twm_standard_1128/自然资源一张图数据库标准1128/规划院提供数据样例及Demo系统功能演示建议/01数据样例/08重庆市各区县人口规模表格数据/重庆市各区县人口规模数据.xlsx
```

表内来源字段：

```text
重庆市统计年鉴2022
```

已生成文件：

```text
data/uwm_public_proxy/chongqing_central/chongqing_district_population_2021/chongqing_district_population_raw_rows.json
data/uwm_public_proxy/chongqing_central/chongqing_district_population_2021/chongqing_district_population_proxy.json
data/uwm_public_proxy/chongqing_central/chongqing_district_population_2021/chongqing_district_population_district_rows.csv
data/uwm_public_proxy/chongqing_central/chongqing_district_population_2021/mmfe_uwm_state_input_chongqing_district_population.json
data/uwm_public_proxy/chongqing_central/chongqing_district_population_2021/uwm_canonical_observation_chongqing_district_population.json
data/uwm_public_proxy/chongqing_central/chongqing_district_population_2021/snapshot_manifest.json
```

结果摘要：

```text
raw_rows = 40
district_rows = 39
city_total_rows = 1
year = 2021
district_resident_population_10k_sum = 3290.08
district_registered_population_10k_sum = 3506.01
max_resident_population_district = 渝北区 220.58 万人
max_urbanization_rate_district = 渝中区 100.0%
```

边界：

```text
这是本地规划样例中的真实区县统计表，不是 WorldPop 下载；
空间粒度是区县，不是乡镇/街道或栅格；
时间为 2021，不是 2024 场景；
许可、再分发和原始统计年鉴引用边界仍需核验；
不能作为政策 outcome 或 planner 实证优越性证据。
```

限制：

```text
aggregation = pixel-center inclusion, not fractional area weighting
GHSL proxy != local census or authoritative planning data
local xiangzhen.shp license/vintage/topology/crosswalk still pending
not an observed health/environment/policy holdout validation dataset
```

## 3. Remaining Gaps

| 数据源 | 本地路径 | 状态 | Required Next Step |
| --- | --- | --- | --- |
| ERA5/CAMS city grid | `data/uwm_public_proxy/chongqing_central/gee_era5_cams_2024_07_01_07/` | point proxy downloaded | expand from point sampling to grid/admin-unit aggregation if UWM scenario needs spatially explicit exposure |
| OpenAQ 2024 scene holdout | `data/uwm_public_proxy/chongqing_central/openaq_station_observations/` | station history downloaded but not scene aligned | find 2024 station/archive coverage or use another observed holdout source |
| TAP PM2.5 2024 scene source | `tap_pm25_china_access_pending` | access pending | download and align after account approval |
| WorldPop China 100m raster | `data/uwm_public_proxy/chongqing_central/worldpop/` | catalog only | download clipped/regional product rather than full 4.98GB national file |

## 4. Current Non-Negotiable Boundary

Downloaded raw public proxy data is not the same as MMFE-aligned UWM state. The next required step is:

```text
raw downloads
-> clipping / profiling / source attribution
-> MMFE alignment and validation
-> mmfe.uwm_state_input.v1
-> UwmCanonicalObservation.v1
-> simulator / planner / evaluation gates
```

GHSL 人口/建成区已经完成前半段的行政单元对齐和 `mmfe.uwm_state_input.v1` 生成；Open-Meteo 历史空气污染/气象点位代理、GEE ERA5/CAMS 点位代理、GEE 行政单元代表点代理和 OpenAQ 站点观测代理也已生成 `mmfe.uwm_state_input.v1`。服务可达性完整分类、ERA5/CAMS 面状 zonal 聚合和真实 2024 observed holdout 仍需继续补齐。

## 5. 2026-07-05 Open-Meteo Historical Outputs

已生成文件：

```text
data/uwm_public_proxy/chongqing_central/openmeteo_history_2024_07_01_07/openmeteo_historical_weather_raw.json
data/uwm_public_proxy/chongqing_central/openmeteo_history_2024_07_01_07/openmeteo_historical_air_quality_raw.json
data/uwm_public_proxy/chongqing_central/openmeteo_history_2024_07_01_07/openmeteo_historical_environmental_proxy.json
data/uwm_public_proxy/chongqing_central/openmeteo_history_2024_07_01_07/snapshot_manifest.json
data/uwm_public_proxy/chongqing_central/openmeteo_history_2024_07_01_07/mmfe_uwm_state_input_openmeteo_history.json
data/uwm_public_proxy/chongqing_central/openmeteo_history_2024_07_01_07/uwm_canonical_observation_openmeteo_history.json
```

对齐摘要：

```text
time_range = 2024-07-01_to_2024-07-07
weather_hourly_records = 168
weather_daily_records = 7
air_quality_hourly_records = 168
weather_resolved_location = [29.56063, 106.5625]
air_quality_resolved_location = [29.599998, 106.600006]
mmfe_state_input_valid = true
canonical_observation_valid = true
empirical_superiority_claim = false
```

## 7. 2026-07-05 GEE ERA5/CAMS And OpenAQ Outputs

已生成文件：

```text
data/uwm_public_proxy/chongqing_central/gee_era5_cams_2024_07_01_07/gee_era5_hourly_raw.json
data/uwm_public_proxy/chongqing_central/gee_era5_cams_2024_07_01_07/gee_cams_nrt_raw.json
data/uwm_public_proxy/chongqing_central/gee_era5_cams_2024_07_01_07/gee_era5_cams_environmental_proxy.json
data/uwm_public_proxy/chongqing_central/gee_era5_cams_2024_07_01_07/mmfe_uwm_state_input_gee_era5_cams.json
data/uwm_public_proxy/chongqing_central/gee_era5_cams_2024_07_01_07/uwm_canonical_observation_gee_era5_cams.json
data/uwm_public_proxy/chongqing_central/openaq_station_observations/openaq_locations_raw.json
data/uwm_public_proxy/chongqing_central/openaq_station_observations/openaq_sensor_measurements_raw.json
data/uwm_public_proxy/chongqing_central/openaq_station_observations/openaq_station_observation_proxy.json
data/uwm_public_proxy/chongqing_central/openaq_station_observations/mmfe_uwm_state_input_openaq_station.json
data/uwm_public_proxy/chongqing_central/openaq_station_observations/uwm_canonical_observation_openaq_station.json
```

摘要：

```text
GEE ERA5 records = 168
GEE CAMS records = 574
ERA5 temperature_2m_mean_avg_c = 28.794
CAMS pm25_avg_ugm3 = 16.81
OpenAQ locations = 15
OpenAQ sensors = 90
OpenAQ measurements = 600
OpenAQ observed_time_range = 2018-10-17T12:00:00Z_to_2021-08-09T11:00:00Z
OpenAQ nearest_station = Shangqingsi, about 486m
scene_holdout_ready = false
empirical_superiority_claim = false
```

## 8. 2026-07-05 Multi-Source Environmental Evidence Chain

已生成文件：

```text
data/uwm_public_proxy/chongqing_central/uwm_environmental_evidence_bundle_2024_07_multisource.json
data/uwm_public_proxy/chongqing_central/uwm_scene_state_livability_2024_07_multisource.json
data/uwm_public_proxy/chongqing_central/uwm_simulator_scenario_livability_2024_07_multisource.json
data/uwm_public_proxy/chongqing_central/uwm_rollout_scene_conditioned_livability_2024_07_multisource.json
data/uwm_public_proxy/chongqing_central/uwm_scene_conditioned_dynamic_advantage_2024_07_multisource.json
```

摘要：

```text
pm25_scene_proxy_ugm3 = 25.985
pm25_scene_proxy_range_ugm3 = 18.35
evidence_flags = [high_pm25_source_disagreement, observed_holdout_not_ready, openaq_not_scene_aligned]
observed_holdout_ready = false
heat_stress_multiplier = 1.1127
air_pollution_stress_multiplier = 1.044535
vulnerability_multiplier = 1.088987
livability_delta_for_traffic_emission_control = 0.02334092075
supported_claim = known_effect_dynamic_advantage_over_static_baseline
empirical_superiority_claim = false
```

意义：

```text
UWM 不再只消费单一环境代理，而是显式融合 modeled proxy、reanalysis/model proxy 和 station observation context；
当 Open-Meteo 与 CAMS PM2.5 差异较大时，bundle 记录 high_pm25_source_disagreement，防止平均值掩盖不确定性；
OpenAQ 真实观测未覆盖 2024-07 场景，因此只作为 historical station reference，不能解锁 observed holdout empirical superiority。
```

## 9. 2026-07-05 Admin Environment And Exposure-Equity Outputs

已生成文件：

```text
data/uwm_public_proxy/chongqing_central/gee_admin_environment_2024_07_01_07/gee_admin_environment_samples_raw.json
data/uwm_public_proxy/chongqing_central/gee_admin_environment_2024_07_01_07/gee_admin_environment_proxy.json
data/uwm_public_proxy/chongqing_central/gee_admin_environment_2024_07_01_07/mmfe_uwm_state_input_gee_admin_environment.json
data/uwm_public_proxy/chongqing_central/gee_admin_environment_2024_07_01_07/uwm_canonical_observation_gee_admin_environment.json
data/uwm_public_proxy/chongqing_central/admin_exposure_equity_2024_07_01_07/uwm_admin_exposure_equity_panel.json
data/uwm_public_proxy/chongqing_central/admin_exposure_equity_2024_07_01_07/uwm_admin_exposure_equity_panel.csv
```

摘要：

```text
admin_feature_count = 1017
sampled_admin_count = 1017
sampled_admin_share = 1.0
sampling_geometry = admin_representative_point
temperature_2m_mean_c_avg = 26.334
precipitation_total_mm_avg = 37.973
cams_pm25_ugm3_avg = 18.269
cams_pm25_ugm3_max = 34.94
joined_admin_count = 1017
strict_target_candidate_count = 0
exported_top_priority_proxy_units = 50
top_priority_proxy_unit = 沙坪坝区|覃家岗街道|973
top_priority_score = 0.841777
empirical_superiority_claim = false
```

限制：

```text
representative_point_not_zonal_mean
priority_score_is_proxy_targeting_not_policy_effect
not_observed_health_or_livability_outcome
admin_geometry_vintage_license_crosswalk_pending
```

## 10. 2026-07-05 Admin Planner Benchmark

已生成文件：

```text
data/uwm_public_proxy/chongqing_central/admin_planner_benchmark_2024_07_01_07/uwm_admin_planner_benchmark.json
```

摘要：

```text
top_proxy_units_used = 10
rollout_count = 31
static_heuristic_action_id = static-priority-traffic-control::沙坪坝区|覃家岗街道|973
world_model_planner_action = uwm-urban-greening::沙坪坝区|覃家岗街道|973
static_livability_delta = 0.002334092075
planner_livability_delta = 0.004734535475
known_effect_regret_reduction = 0.0024004434
supported_claim = known_effect_planner_advantage_over_static_heuristic
empirical_superiority_claim = false
```

边界：

```text
该 benchmark 证明 UWM planner 在 simulator known-effect rollout 上优于传统静态启发式；
它不证明真实政策 outcome 或 observed holdout 上优于传统方法；
下一步要提升 claim，需要 observed policy outcome holdout、外部城市验证和因果政策效果校验。
```

## 11. 2026-07-05 OSM Service Accessibility Proxy

已生成文件：

```text
data/uwm_public_proxy/chongqing_central/osm_services_geometry_2026_07_05/osm_services_overpass_geometry_raw.json
data/uwm_public_proxy/chongqing_central/osm_services_geometry_2026_07_05/osm_service_accessibility_proxy.json
data/uwm_public_proxy/chongqing_central/osm_services_geometry_2026_07_05/mmfe_uwm_state_input_osm_service_accessibility.json
data/uwm_public_proxy/chongqing_central/osm_services_geometry_2026_07_05/uwm_canonical_observation_osm_service_accessibility.json
```

摘要：

```text
requested_bbox = [29.52, 106.50, 29.60, 106.60]
osm_base_timestamp = 2026-07-05T03:06:42Z
elements = 200
coordinate_elements = 200
service_category_count = 8
essential_service_count = 16
food_retail_count = 116
healthcare_count = 10
education_count = 6
empirical_superiority_claim = false
```

限制：

```text
overpass_bbox_sample_not_complete_osm_extract
not_a_network_travel_time_accessibility_surface
osm_tag_completeness_varies_spatially
odbl_attribution_required
```

## 12. 2026-07-05 Admin Service Accessibility Panel

已生成文件：

```text
data/uwm_public_proxy/chongqing_central/admin_service_accessibility_2026_07_05/uwm_admin_service_accessibility_panel.json
data/uwm_public_proxy/chongqing_central/admin_service_accessibility_2026_07_05/uwm_admin_service_accessibility_panel.csv
```

摘要：

```text
bbox_admin_count = 36
admin_units_with_service_points = 25
admin_units_without_sample_points = 11
service_point_count = 200
essential_service_count = 16
empirical_superiority_claim = false
```

边界：

```text
11 个无点行政单元只能解释为 no_osm_points_in_bbox_sample；
不能解释为真实服务缺失；
该 panel 不是全城服务可达性面，也不是网络出行时间可达性。
```

## 13. 2026-07-05 Composite Admin Livability Target And Planner Benchmark

已生成文件：

```text
data/uwm_public_proxy/chongqing_central/admin_livability_target_2024_07_2026_07_05/uwm_admin_livability_target_panel.json
data/uwm_public_proxy/chongqing_central/admin_livability_target_2024_07_2026_07_05/uwm_admin_livability_target_panel.csv
data/uwm_public_proxy/chongqing_central/admin_livability_planner_benchmark_2024_07_2026_07_05/uwm_admin_livability_planner_benchmark.json
```

摘要：

```text
joined_admin_count = 36
target_candidate_count = 3
top_target = 九龙坡区|九龙镇|77
top_target_flags = high_exposure_priority, service_sample_gap, low_essential_service_sample, composite_livability_target
rollout_count = 31
static_action = static-priority-traffic-control::九龙坡区|九龙镇|77
planner_action = uwm-urban-greening::九龙坡区|九龙镇|77
known_effect_regret_reduction = 0.0024004434
supported_claim = known_effect_planner_advantage_over_static_heuristic
empirical_superiority_claim = false
```

边界：

```text
复合目标使用 public proxy，不是 observed livability outcome；
service_sample_gap 不是真实缺服务；
planner advantage 是 known-effect simulator benchmark，不是 observed policy outcome superiority。
```

## 14. 2026-07-05 OpenAQ Observed Temporal Benchmark

已生成文件：

```text
data/uwm_public_proxy/chongqing_central/openaq_temporal_benchmark_2018_10/uwm_openaq_observed_temporal_benchmark.json
```

摘要：

```text
pollutant_count = 6
observation_count = 600
holdout_count = 180
observed_temporal_state_advantage_over_static_baseline = true
supported_claim = observed_temporal_state_prediction_advantage_over_static_mean_baseline
empirical_superiority_claim = false
```

逐污染物 MAE reduction：

```text
co = 163.333333
no2 = 0.568572
o3 = 32.07619
pm10 = 11.395238
pm25 = 10.495238
so2 = 0.736191
```

边界：

```text
这是真实观测时间序列 holdout，可支撑 state dynamics 优于静态均值 baseline；
不是政策干预 outcome；
不能直接支撑 planner 的 observed policy superiority。
```

限制：

```text
not_station_calibrated_holdout
point_proxy_not_citywide_grid
not_a_replacement_for_era5_or_cams_historical_grids
not_a_replacement_for_local_monitoring_station_observations
```

## 6. 2026-07-05 Scene-State And Rollout Outputs

已生成文件：

```text
data/uwm_public_proxy/chongqing_central/uwm_scene_state_livability_2024_07.json
data/uwm_public_proxy/chongqing_central/uwm_simulator_scenario_livability_2024_07.json
data/uwm_public_proxy/chongqing_central/uwm_rollout_normal_air_reference.json
data/uwm_public_proxy/chongqing_central/uwm_rollout_scene_conditioned_livability_2024_07.json
data/uwm_public_proxy/chongqing_central/uwm_scene_conditioned_dynamic_advantage_2024_07.json
```

结果摘要：

```text
heat_stress_multiplier = 1.0857
air_pollution_stress_multiplier = 1.136285
vulnerability_multiplier = 1.088987
normal_air_delta = -0.08
scene_air_delta = -0.0909028
normal_livability_delta = 0.02225
scene_livability_delta = 0.02517592075
supported_claim = known_effect_dynamic_advantage_over_static_baseline
empirical_superiority_claim = false
```
