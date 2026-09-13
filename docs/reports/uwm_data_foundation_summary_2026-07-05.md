# UWM 数据基础与 Roadmap 总览

日期：2026-07-05；TAP 更新：2026-07-06

静态预览页：

```text
docs/reports/uwm_data_foundation_overview_2026-07-05.html
```

## 1. 当前一句话结论

TAP status update on 2026-07-06: local TAP PM2.5 package is now parsed and registered as
`tap_pm25_observed_gridded_chongqing_2018_2024`. It strengthens `air_pollution_exposure`
from TAP-pending to TAP gridded available and supports a bounded gridded temporal
state-prediction benchmark. It does not close the observed policy outcome gate because TAP is
a multisource gridded product, not a station-observed intervention outcome.
The TAP external dynamics holdout is now also registered as a bounded transition-layer
gate: residual-delta transition ridge slightly beats the adaptive non-spatial online baseline
(MAE 7.003808 vs 7.011689; paired win rate 0.5077), but neighbor shuffle is not worse,
so it supports only temporal transition improvement, not spatial attribution or policy-outcome superiority.

UWM 已经形成可运行的世界模型链条：

```text
data foundation / MMFE state input
-> renderer
-> scene state
-> simulator
-> evidence-gated planner
-> evaluation / Track 2 readiness gate
```

当前最强的事实性证明是：

```text
OpenAQ 600 条真实小时观测 temporal holdout 上，
UWM online temporal state update 显著优于传统静态 baseline suite。
```

但当前仍不能宣称：

```text
UWM planner 在真实政策 outcome 上优于传统方法。
```

原因是仍缺真实政策干预 outcome holdout、场景一致 air-quality station-calibrated observed holdout、因果识别/政策效果验证。气象侧已补入 NOAA ISD 2024-07 江北站观测，但仍不是全城格网/面状气象校准。

## 2. Roadmap 完成情况

| Roadmap 模块 | 当前状态 | 已完成事实 | 不能过度宣称 |
| --- | --- | --- | --- |
| UWM 契约层 | 已完成 v0 | `UwmCanonicalObservation.v1`、`UwmRolloutTrace.v1`、`UwmPlanPackage.v1` 和 MMFE state input 已有测试 | 只是契约可运行，不等于实证有效 |
| Data foundation manifest | 已完成 v0，持续扩展 | manifest 66 行；核心角色不缺项；新增本地区县人口统计、联通职住通勤、百度搜索指数、历史文化街区、璧山 DLTB/台账/边界、村规数据库、CHAP PM2.5、NOAA ISD 观测气象、OSM complete bbox 服务/道路抽取、UWM fitted 人口下推和联通潜在通勤图、learned rollout planner、graph-aware world model、synthetic policy outcome scaffold、livability intervention package、data-foundation evidence gate、TAP-like PM2.5 v2、TAP observed gridded PM2.5、TAP external dynamics bounded transition gate；来源、synthetic/proxy、claim boundary 可审计 | claim ceiling 仍为 `fragile` |
| Renderer | 已完成 v0 | 可把 MMFE state input 转成 canonical observation，并保留 trace、claim boundary、proxy flags | 不是完整城市数字孪生 |
| Scene state | 已完成 v0 | 可把 GHSL、Open-Meteo、GEE/CAMS、OpenAQ 等证据转为 simulator controls | 部分环境仍是 point/representative-point proxy |
| Simulator | 已完成 known-effect v0 | action-conditioned rollout、邻接溢出、情景控制、negative control 已实现 | 参数还不是 data-calibrated mechanism table |
| Planner | 已完成 evidence-gated v0 | planner 只能消费 rollout trace；可做 known-effect regret benchmark | 不是 observed policy outcome 优越性 |
| Admin exposure/equity/service/livability targeting | 已完成 proxy v0 | GHSL+GEE+OSM 可形成 admin panel、top proxy target 和 planner benchmark | proxy target 不是真实健康/宜居 outcome |
| Admin spatial adjacency Graph-MDP | 已完成 v0 | 由全量 1017 个重庆乡镇/街道行政单元派生 2847 条边界邻接边；36 个 livability 候选单元诱导出 96 条真实空间边；offline value model 在 replay holdout 上优于 train-mean baseline | 这是行政拓扑图，不是道路/出行/mobility graph；value model 仍不是 PPO 或真实 outcome model |
| Offline world-model policy | 已完成 v0 | 基于 355 条 spatial Graph-MDP replay 训练 action-conditioned reward+dynamics model；holdout reward MAE 0.000165324 vs train-mean baseline 0.002418188；保守策略在 replay 中 0.009041181 vs 静态启发式 0.007839757 | 这是 simulator replay 上的离线世界模型策略改进，不是真实政策 outcome，也不是在线 PPO |
| Learned world-model rollout planner | 已完成 v0 | 使用同一个 action-conditioned reward+dynamics model 做 2-step imagined rollout，逐步写回 latent state；selected sequence 为 `increase_green_infrastructure-江北区|观音桥街道|653` -> `add_community_service-九龙坡区|谢家湾街道|785`；imagined conservative score 0.011528613 vs static 0.00124898 and one-step learned policy 0.002012933 | 这是 learned dynamics imagination 上的规划优势，不是真实政策 outcome，也不是在线 PPO |
| Graph-aware world model | 已完成 v0 | 在 36 个空间候选单元和 96 条行政邻接边上训练 graph-aware action-conditioned reward+dynamics model；holdout reward MAE 0.000103937 vs target-only baseline 0.000844982 vs train-mean baseline 0.002418188；reward win rate vs target-only = 0.957746479 | 证明的是 prepared spatial Graph-MDP replay holdout 上的 graph-aware dynamics 优势，不是真实政策 outcome |
| Livability intervention package | 已完成 v0 | 把 low-livability area identification、mechanism explanation、intervention suitability map、multi-step action sequence、before/after indicator deltas、equity conclusion 和 evidence boundary 组织成证据门控方案包；综合 deltas 为 heat -1.027807246、air -0.411081019、service +0.965080014、equity +0.552991953、livability +0.786721588；supported proxy claim 为 `business_theory_aligned_learned_rollout_beats_static_proxy_baseline` | 依赖 learned rollout、synthetic policy outcome 和 TAP-like PM2.5 v2；只能作 exploratory/proxy 方案，不是 observed intervention outcome |
| Data-foundation evidence gate | 已完成 v1 | 读取完整 UWM 数据基础和实际产物，不限于 `real` 标签；接受 real/public_proxy/fitted_proxy/semi_synthetic/synthetic/restricted_expected，但按 claim boundary 分层。OpenAQ observed temporal holdout：600 observations、180 holdout、150 wins、win rate 0.833333、PM2.5 dynamic MAE 2.4 vs best static 9.466667；TAP external transition：40,000 holdout、residual-delta MAE 7.003808 vs adaptive online 7.011689、paired win rate 0.5077 | 只允许声明 observed temporal state prediction 和 TAP external temporal transition 优于相应传统/动态基线；observed policy outcome superiority 仍为 false |
| OpenAQ observed temporal validation | 已完成当前最强实证切片 | 6 个污染物全部击败 `static_train_mean` 和 `static_last_train_observation`；sign test 显著；时间顺序负控通过 | 只证明状态预测层，不证明政策 outcome |
| TAP external spatiotemporal dynamics validation | 已完成 transition gate v1 | 10,000 grid series / 40,000 holdout points；future leakage guard 通过；residual-delta transition ridge MAE 7.003808 vs adaptive online dynamic baseline 7.011689；paired win rate 0.5077；时间顺序旋转负控变差 1.585932 MAE | 支持 `tap_external_temporal_dynamics_advantage_without_spatial_claim`；neighbor shuffle 不变差，因此不支持空间归因或政策 outcome 优越性 |
| Track 2 readiness | 部分完成 | 数据说明、代码、AI 协作记录已具备；readiness gate 可机器判定边界 | 完整初评研究报告仍未完成 |
| 真实政策 outcome / 因果验证 | 未完成 | 当前只记录为 gate/blocker | 不得宣称真实政策效果优于传统方法 |

## 3. 数据基础总体盘点

来自 `docs/reports/uwm_data_foundation_manifest.csv`：

| 维度 | 数量 | 说明 |
| --- | ---: | --- |
| manifest rows | 66 | 当前 UWM 数据基础登记行数 |
| real | 18 个 manifest 条目 | 本地/项目已有真实资产或论文资产；这里统计的是资产登记条目，不是要素/记录数量 |
| public_proxy | 39 | 公开下载、API、GEE、OSM、GHSL、OpenAQ、Open-Meteo、CHAP、NOAA ISD、Graph-MDP proxy search、offline value model、offline world-model policy、learned rollout planner、graph-aware world model、data-foundation evidence gate、TAP external dynamics bounded transition gate 等代理/证据门控产物 |
| fitted_proxy | 2 | 本轮由真实/代理输入拟合生成的人口总量守恒下推层和联通潜在通勤图；只作 simulator/planner scaffold |
| restricted_expected | 1 | 保留 TAP 账号/授权跟踪历史行；真实 TAP 本地包已另登记为 public_proxy |
| semi_synthetic | 3 | EPA Green Book policy-structure benchmark；scene-aligned PM2.5 半合成压力测试面板；CHAP 锚定 TAP-like PM2.5 v2 |
| synthetic | 3 | synthetic policy outcome scaffold；livability intervention package；synthetic air placeholder |
| available | 59 | 已有本地产物或可用文件 |
| api_reachable | 2 | Open-Meteo current live API 已验证但不作为 archived holdout |
| raw_public_proxy_available | 1 | GHSL raw tiles 已下载并校验，另有 alignment 可用行 |
| planned_public_download | 1 | WorldPop 全国 100m 大文件未下载 |
| planned synthetic | 1 | synthetic air placeholder |

当前 role audit：

```text
missing_required_roles = []
claim_ceiling = fragile
empirical_superiority_blockers = [air_pollution_exposure]
```

## 4. 按来源分类

### 4.1 你提供 / 项目已有本地资产

注意：本节按 manifest 资产组统计，不按要素数统计。一个 manifest 条目可以对应重庆全量数据或大量空间要素；过去的“8 个 real 条目”和当前的“18 个 real 条目”都不是数据行数。当前已核对到的本地源规模如下：

| 本地源 | 已核对规模 | 说明 |
| --- | ---: | --- |
| 规划院 zip | 447 MB 压缩包；解压后 `01数据样例` 实扫 584 个文件，其中包含 FileGDB 内部文件 | 包含栅格、31 组 `.shp/.shx`、6 个 FileGDB 目录、DWG、PDF/JPG、CSV/XLS/XLSX 等 |
| `/Users/zhouning/Downloads/shp` | 126 个文件；约 1.05 GB；15 组 shapefile | 包含 `xiangzhen.shp`、`bishan.shp`、`dongxing.shp` 等 |
| `xiangzhen.shp` 原始层 | 43,655 records | UWM 当前派生重庆乡镇/街道子集为 1,017 个行政单元、38 个区县 |
| 重庆市各区县人口规模数据.xlsx | 40 rows | 来源字段为 `重庆市统计年鉴2022`；1 行全市总计、39 行区县；2021 区县常住人口合计 3290.08 万人 |
| 规划院 zip 中建筑轮廓 shapefile | 107,452 records | 由 `.shx` 标准 record index 推算 |
| 规划院 zip 中 OSM roads | 50,366 records | 由 `OSM_roads.shx` 推算 |
| 高德地图 POI 2024 FileGDB | 1,194,351 Point features | EPSG:4490；医疗保健服务 45,068 条；服务可达性和城市功能上下文 |
| 百度地图 AOI 2024 FileGDB | 26,292 MultiPolygon features | EPSG:4490；含评分、评论数、人均价格、分类等字段 |
| 成渝环渝百度搜索指数 FileGDB | 325 MultiLineString flows | 26 个出发城市、26 个目的城市；总搜索指数 8,694,518 |
| 中国联通手机信令通勤 CSV | 2,120 rows | 259 个居住格网、697 个工作格网；缺格网几何字典，不直接制图 |
| 中心城区历史文化街区 shapefile | 20 Polygon Z features | 城市文化宜居性和保护约束上下文 |
| 璧山 DLTB FileGDB | 101,657 MultiPolygon features | 区县样例土地利用/规划约束上下文，不是重庆全市 |
| 璧山 2019 用地台账 | 1,438 个非空工作表行，含表头/标题行 | 规划许可、征地、供地/划拨等开发压力上下文 |
| 福禄镇村规数据库 | 31 个 shapefile；8,050 total features | 和平村/斑竹村样例，支撑村规约束和局部宜居性上下文 |
| DEM | 1,766 x 1,454 = 2,567,764 pixels | 临时抽取 GeoTIFF 后用系统工具读取 |
| CLCD 2020 | 18,579 x 15,082 = 280,208,478 pixels | 临时抽取 GeoTIFF 后用系统工具读取 |

本轮已用项目虚拟环境中的 `pyogrio/rasterio/pandas/xlrd/openpyxl` 实读 FileGDB、SHP、CSV、XLS/XLSX 和 TIF；此前“GDB 内部 feature count 待 profile”的说法已经被替换为上表中的实读结果。

| 数据 | 角色 | 当前用途 | 边界 |
| --- | --- | --- | --- |
| `chongqing_central_buildings_2021` | urban_form | renderer、baseline | restricted local；可支撑形态状态，不自动支撑实证 superiority |
| `chongqing_dem_80m` | heat_exposure | heat context / renderer | planning sample |
| `chongqing_clcd_2020` | remote_sensing_state | land-cover / baseline | planning sample |
| `chongqing_osm_roads_2021` | mobility graph | graph context | planning sample；不是完整出行行为 |
| `gaode_poi_2024` | service_accessibility | service baseline | restricted local |
| `baidu_aoi_2024` | service_accessibility / urban_form | AOI / urban form context | restricted local |
| `chongqing_unicom_commuting_2023_local` | mobility_activity / commuting_od | 通勤活动状态、人口活动上下文 | 缺格网几何字典；不能替代出行时间/交通流 |
| `baidu_search_index_2023_local` | urban_activity_proxy / mobility_activity | 城际关注流和活动联系 | 搜索兴趣不等于真实出行或政策 outcome |
| `chongqing_historic_districts_local` | urban_form / cultural_heritage | 文化街区、保护约束、宜居性上下文 | 来源许可和年代需核验 |
| `bishan_land_use_dltb_local` | land_use_context / planning_constraints | 区县样例现状地类图斑 | 璧山局部，不是重庆全市 |
| `bishan_land_development_ledger_2019_local` | land_development_pressure / planner_constraints | 开发压力/用地审批上下文 | 台账不是空间 outcome |
| `fulu_village_planning_database_local` | planning_constraints / village_livability_context | 村规约束和局部规划状态 | 福禄镇样例，不是全市 |
| `clcd_classification_dictionary_local` | remote_sensing_state | CLCD 栅格类别解释 | 元数据，不是独立观测 |
| `chongqing_township_admin_units_local` | administrative_units | governance units、equity、planner、renderer | 本地真实子集；许可、官方年代、现代区县名 crosswalk 仍需核验 |
| `chongqing_admin_spatial_adjacency_graph_2026_07_05` | spatial_adjacency_graph | simulator、planner、model_based_rl | 由全量 1017 个重庆乡镇/街道行政单元派生 2847 条边；行政边界拓扑，不是道路或出行图 |
| `paper6_chongqing_uhi` | heat_exposure / evidence_gate | heat/UHI evidence | paper asset；不是政策 outcome |

### 4.2 已下载或已通过公开/认证路径生成的公开数据

| 数据 | 下载/生成方式 | 当前状态 | 用途 | 边界 |
| --- | --- | --- | --- | --- |
| ERA5 center-point proxy | GEE 已认证采样 | 168 hourly records | meteorology | reanalysis point proxy，不是 station holdout |
| Paper58 AlphaEarth / GeoFM state prior | 项目研究资产 | state prior 可用 | remote_sensing_state / simulator | public proxy/state prior，不是你提供的 8 个 real 资产组，也不是完整 UWM |
| CAMS/NRT center-point proxy | GEE 已认证采样 | 574 records | air_pollution_exposure | model proxy，不是 station holdout |
| GEE admin environment proxy | GEE representative-point sampling | 1017 admin representative points | admin environment / planner targeting | 不是 polygon zonal mean |
| GEE livability admin zonal environment proxy | GEE simplified-polygon reduceRegions | 36/36 livability candidate admin polygons | meteorology / air pollution scene context | ERA5/CAMS model proxy，不是 station holdout |
| CHAP PM2.5 2024-07 monthly 1km proxy | Zenodo CHAP record 15208529 | 36/36 livability candidate admin representative points；PM2.5 avg 16.433 ug/m3 | air_pollution_exposure / planner targeting / state context | AI 融合格网产品，不是站点观测；月均不是小时场景 |
| NOAA ISD 2024-07 observed weather | NOAA NCEI public ISD gzip + isd-history | 575160-99999 JIANGBEI/ZUCK；2024-07-01 至 2024-07-07 共 224 条观测；temperature 224、pressure 56、wind 224 | meteorology observed station holdout / simulator context | 单站/混合 FM-12 FM-15 报文，不是全城格网或面状气象 |
| OpenAQ station observations | OpenAQ v3 runtime key | 15 locations、90 sensors、600 measurements | real station context / temporal validation | 不覆盖 2024-07 scene；不是政策 outcome |
| OpenAQ 2024-07 scene attempt | OpenAQ v3 runtime key，经 stdin 使用且未落盘 | 15 locations、90 sensors、0 measurements | 下载可行性证据 | 源端不覆盖 2024-07 场景，不登记为可用观测资产 |
| OpenAQ temporal benchmark | 由 OpenAQ 600 observations 派生 | 6 pollutants、180 holdout points | observed temporal state validation | 只证明状态预测层 |
| Open-Meteo 2024-07 history | keyless public API | weather 168 hourly + air-quality 168 hourly | 2024 scene point proxy | modeled point proxy，不是 station-calibrated holdout |
| Open-Meteo livability admin air-quality | keyless public API | 36 admin representative points、6048 hourly air-quality records | 2024 scene admin air pollution proxy | public model proxy，不是 station observation |
| Open-Meteo 2018-10 history | keyless public API | weather 可用；air-quality 全 null | OpenAQ 时间窗同期 weather context | 不能作为 2018-10 air-quality evidence |
| GHSL raw tiles | public download | 8 zip tiles，zip 校验通过 | population / built-up raw proxy | raw tiles 本身未直接作为最终 state |
| GHSL admin alignment | 本地 alignment | 1017 township/street rows | population_vulnerability / urban_form / equity | pixel-center proxy，不是本地人口普查 |
| Chongqing district population statistics | 本地规划样例 Excel | 40 rows；39 个区县 + 1 个全市总计；2021 区县常住人口合计 3290.08 万人 | population_vulnerability / equity | 本地真实区县统计，但不是乡镇/街道或格网人口，不是 2024 场景 |
| OSM service geometry historical sample | Overpass | 200 amenity nodes | service sample / MMFE state | 早期 bbox sample，保留作对照 |
| OSM complete bbox service extract | Overpass | 786 amenity node/way/relation center elements；163 essential service proxy points | service accessibility / MMFE state | bbox 完整抽取，不是全市完整 POI 或 travel-time surface |
| OSM complete bbox highway topology | Overpass | 48,820 elements；42,058 coordinate nodes；6,762 highway ways；45,468 graph edges | mobility graph / simulator context / MMFE state | 道路拓扑，不是出行时间、OD 或交通流 |
| Admin exposure-equity panel | GHSL + GEE joined | 1017 admin rows | planner proxy targeting | priority 不是政策效果 |
| Admin service accessibility panel | OSM + admin units | 36 bbox-intersecting admin units；新版完整 bbox 中 34 个有服务点、2 个仍为空 | service gap proxy | bbox extract gap 不等于真实服务缺失 |
| Admin livability target panel | exposure-equity + service | 36 joined rows，3 target candidates | composite proxy target | proxy target，不是 observed livability |
| Graph-MDP model-based search report | admin livability proxy + UWM simulator | 8 proxy admin units、2-step beam search、109 replay transitions | model_based_rl / planner benchmark | known-effect reward advantage，不是真实政策 outcome |
| Spatial Graph-MDP model-based search report | admin livability proxy + 全量行政空间邻接图 + UWM simulator | 36 candidate admin units、96 spatial adjacency edges、355 replay transitions | model_based_rl / spatial planner benchmark | known-effect reward advantage，不是真实政策 outcome |
| Offline graph value model report | spatial Graph-MDP replay | 355 simulator replay transitions；holdout MAE 0.000165326 vs train-mean baseline MAE 0.002418188 | offline value model / planner scaffold | 只证明 replay value fitting，不是真实政策 outcome |
| Offline world-model policy report | spatial Graph-MDP replay | action-conditioned reward+dynamics model；holdout reward MAE 0.000165324 vs train-mean baseline 0.002418188；保守策略 replay mean reward 0.009041181 vs static heuristic 0.007839757 | offline world model / policy improvement | 只证明 simulator replay 上 learned world-model policy 优于静态启发式，不是真实政策 outcome |
| Learned world-model rollout planner report | spatial Graph-MDP replay | action-conditioned reward+dynamics model + 2-step imagined rollout；selected sequence 为 `increase_green_infrastructure-江北区|观音桥街道|653` -> `add_community_service-九龙坡区|谢家湾街道|785`；imagined conservative score 0.011528613 vs static 0.00124898 and one-step learned policy 0.002012933 | offline world model / learned rollout planner / policy improvement | 只证明 learned dynamics imagination 上的多步规划优势，不是真实政策 outcome |
| Graph-aware world model report | spatial Graph-MDP replay + admin adjacency | 使用 target features + neighbor means + target-neighbor contrasts + action-neighborhood pressure 训练空间感知 action-conditioned dynamics；reward MAE 0.000103937，target-only baseline 0.000844982，train-mean baseline 0.002418188 | graph-aware dynamics / offline world model / spatial planner scaffold | 只证明 spatial replay holdout 上 graph-aware model 优于 target-only baseline，不是真实政策 outcome |
| Livability intervention package | spatial Graph-MDP replay + learned rollout + synthetic outcome scaffold + TAP-like PM2.5 v2 | 证据门控城市干预方案包；识别低宜居单元、解释机制、给出干预适宜性、多步 action sequence、前后指标 delta、公平性结论和证据边界；claim boundary 为 `exploratory_only` | livability intervention package / planner output / evidence gate | 不是 observed intervention outcome；不能解除真实政策 outcome gate |
| Data-foundation evidence gate | 完整 UWM manifest + OpenAQ observed benchmark + TAP external dynamics + local planning inventory + admin graph + learned rollout + intervention package | 接受完整数据基础的各类资产并分层；observed state prediction superiority = true；external temporal transition superiority = true；observed policy outcome superiority = false；synthetic/proxy boundary 显式保留 | data foundation / evidence gate / claim boundary | 证明的是真实 OpenAQ 时间状态预测优于静态 baseline、TAP external residual-delta transition 优于 adaptive dynamic baseline；不是政策干预 outcome |
| UWM fitted population downscaling | 本地区县人口统计 + GHSL admin alignment | 852 fitted rows；3290.08 万输入人口 = 3290.08 万输出人口；845 个 GHSL 权重乡镇/街道行 + 7 个区县 fallback 行 | population_vulnerability / planner scaffold | fitted_proxy，不是乡镇/街道人口普查、格网人口或 2024 场景人口 |
| UWM Unicom latent mobility graph | 本地联通职住通勤 CSV 聚合 | 1,067 directed edges；756 nodes；expanded population 29,634.796667；work_grid=0 权重 12,933.005191 | mobility_activity / simulator_context | fitted_proxy；缺格网几何字典，不是空间 OD 面、travel-time surface 或交通流 |

### 4.2.1 已识别但未获得的数据

| 数据 | 当前状态 | 下一步 | 边界 |
| --- | --- | --- | --- |
| TAP observed gridded PM2.5 | 本地包 `/Users/zhouning/Downloads/tap_uwm` 已解析并登记为 `tap_pm25_observed_gridded_chongqing_2018_2024` | 1km PM2.5 rows = 9,451,218；valid rows = 9,422,882；10km species rows = 23,746；gridded temporal benchmark 支撑 bounded state-prediction claim | TAP 是多源融合格网产品，不是 station observation 或 observed intervention outcome |
| TAP external spatiotemporal dynamics holdout | 同一 TAP 本地包派生 | 10,000 grid series / 40,000 holdout；residual-delta transition ridge MAE 7.003808 vs adaptive online dynamic MAE 7.011689；future leakage guard passed；supported claim = `tap_external_temporal_dynamics_advantage_without_spatial_claim` | bounded temporal transition evidence；neighbor shuffle 不支持空间归因，不替代 station/policy outcome holdout |

### 4.3 API 可达但不能当 holdout 的数据

| 数据 | 当前状态 | 用途 | 不能说什么 |
| --- | --- | --- | --- |
| Open-Meteo current weather | API reachable | live context / smoke | 不能替代 ERA5/CAMS 历史栅格 |
| Open-Meteo current air quality | API reachable | live context / smoke | 不能替代 station-calibrated holdout |

### 4.4 拟合补全

| 数据 | 类型 | 当前用途 | 边界 |
| --- | --- | --- | --- |
| `uwm_fitted_admin_population_downscaling_2021` | fitted_proxy | 把 2021 区县常住人口总量用 GHSL 乡镇/街道权重下推；无匹配区县保留为显式区县 fallback；总量守恒 | 不是人口普查微观数据、不是 2024 场景人口、不能作为 empirical superiority 证据 |
| `uwm_unicom_latent_mobility_graph_2023` | fitted_proxy | 将联通 OD 表聚合成无坐标有向潜在通勤图，供 simulator/planner 做活动强度上下文 | 缺格网几何字典，不是空间 OD 几何、出行时间、交通流或政策 outcome |

### 4.5 半合成 / 合成

| 数据 | 类型 | 当前用途 | 边界 |
| --- | --- | --- | --- |
| `epa_greenbook_policy_structure` | semi_synthetic | policy-structure / evidence gate scaffold | 不是重庆真实政策 outcome |
| `semi_synthetic_air_quality_scene_2024_07` | semi_synthetic | 2024-07 scene-aligned PM2.5 stress-test panel，36 admin units x 168 hours = 6048 records | OpenAQ 2024 场景无 measurements 后生成；不能当 observed holdout |
| `tap_like_pm25_scene_v2_2024_07` | semi_synthetic | CHAP 2024-07 月均锚定 + Open-Meteo 2024 小时时序 + OpenAQ 历史 PM2.5 扰动 + NOAA ISD 气象调整 + GEE 可选空间上下文；36 admin units x 168 hours = 6048 records；CHAP anchor max abs error = 0.0 ug/m3 | 不是 TAP 数据、不是 observed holdout；仅用于 TAP 审核前的 UWM 开发、simulator/planner/OPE 管线压力测试 |
| `uwm_synthetic_policy_outcome_benchmark_admin_livability_spatial_graph` | synthetic | static heuristic、Graph-MDP best 和 learned rollout policy 的同场景 simulator outcome scaffold；learned/static synthetic reward advantage = 0.010907049 | 合成政策结果，不是 observed intervention outcome；只能用于 OPE/negative-control 脚手架 |
| `uwm_livability_intervention_package_admin_livability_spatial_graph` | synthetic | 由 learned rollout、synthetic policy outcome scaffold 和 TAP-like PM2.5 v2 组织出的城市宜居性干预方案包；包含机制解释、干预适宜性、多步 action sequence、前后指标变化、公平性和证据边界 | 业务方案产物是 exploratory scaffold；不是客户权威数据验证后的政策方案 |
| `synthetic_air_quality_placeholder` | synthetic planned | smoke tests | 不能支撑任何 empirical claim |

## 5. 按 UWM 核心角色看是否还有空缺

| UWM 角色 | 当前覆盖 | 来源类型 | 是否还有硬缺口 |
| --- | --- | --- | --- |
| urban_form | 有 | 本地建筑、Baidu AOI、GHSL built-up | 权威楼栋许可/年份仍需核验 |
| administrative_units | 有 | 本地 xiangzhen subset | 许可、官方年代、行政区 crosswalk 需核验 |
| spatial_adjacency_graph | 有 | 本地 xiangzhen subset 派生的 1017 节点/2847 边行政邻接图 | 不是道路网络、交通流或出行时间图 |
| remote_sensing_state | 有 | CLCD、AlphaEarth/Paper58、GHSL | 仍缺更完整城市遥感状态栅格链 |
| heat_exposure | 有 | DEM、Paper6 UHI、admin panel | 仍缺全城长期热暴露 observed holdout |
| meteorology | proxy_available + observed station | ERA5/Open-Meteo/GEE admin representative point/GEE candidate zonal proxy；NOAA ISD 江北站 2024-07 观测 | 硬 blocker 已解除；仍缺全城格网/面状气象校准 |
| air_pollution_exposure | proxy_available | CAMS/Open-Meteo/OpenAQ/CHAP/TAP/GEE admin representative point/GEE candidate zonal proxy；TAP gridded PM2.5 已解析可用；TAP external dynamics bounded transition gate 已登记 | 仍是 empirical blocker：OpenAQ 2024-07 attempt 为 0 measurements，TAP 是多源融合格网产品，TAP external dynamics 当前只支持 temporal transition improvement，不支持空间消息归因优势，缺 station-calibrated/policy outcome holdout |
| population_vulnerability | usable_real + proxy_available + fitted_proxy | 本地区县人口统计 2021；GHSL admin alignment；UWM fitted population downscaling；WorldPop metadata downloaded but population raster not downloaded | 仍缺乡镇/街道级权威人口、脆弱人群细分和 2024 场景人口；WorldPop 旧 100m 中国 GeoTIFF 约 4.98GB、Global2 raster zip 约 5.2GB，均未下载 |
| service_accessibility | proxy_available | Gaode/Baidu local + OSM 200 点历史样本 + OSM complete bbox service extract | 仍缺全市完整 POI、权威服务目录和 network travel-time accessibility surface |
| mobility_graph / mobility_activity | 有基础 + 新增真实活动表 + fitted_proxy | local roads、OSM complete bbox highway topology、联通职住通勤、百度搜索指数、UWM Unicom latent mobility graph | 缺格网几何字典、真实出行时间、交通流和网络阻抗；搜索指数不是出行观测；latent graph 不是空间 OD 面 |
| state_dynamics_validation | 有一项强实证 | OpenAQ temporal benchmark | 只覆盖 air-quality temporal state，不覆盖 policy outcome |
| causal_evidence_gate | 部分 | Paper6/EPA/OpenAQ temporal evidence | 真实因果识别和政策效果验证仍缺 |

## 6. 当前最强实证结果

Graph-MDP known-effect planning benchmark：

```text
source admin features = 1017
admin adjacency edges = 2847
livability candidate units = 36
selected spatial edges = 96
replay transitions = 355
best 2-step model-based reward = 0.012346806
static single-step reward = 0.001439757
advantage = 0.010907049
offline value holdout MAE = 0.000165326
train-mean baseline MAE = 0.002418188
offline world-model policy reward MAE = 0.000165324
offline world-model policy baseline MAE = 0.002418188
offline world-model conservative policy replay reward = 0.009041181
static heuristic replay reward = 0.007839757
learned rollout planner selected sequence = increase_green_infrastructure-江北区|观音桥街道|653 -> add_community_service-九龙坡区|谢家湾街道|785
learned rollout planner imagined conservative score = 0.011528613
learned rollout planner static imagined score = 0.00124898
learned rollout planner one-step imagined score = 0.002012933
graph-aware world model reward MAE = 0.000103937
graph-aware target-only reward MAE = 0.000844982
graph-aware train-mean reward MAE = 0.002418188
graph-aware reward win rate vs target-only = 0.957746479
synthetic policy outcome learned reward = 0.006346806
synthetic policy outcome static reward = -0.004560243
synthetic policy outcome learned advantage over static = 0.010907049
livability intervention package supported claim = business_theory_aligned_learned_rollout_beats_static_proxy_baseline
livability intervention package claim boundary = exploratory_only
livability intervention package predicted deltas = heat -1.027807246; air -0.411081019; service +0.965080014; equity +0.552991953; livability +0.786721588
data-foundation evidence gate observed state prediction superiority = true
data-foundation evidence gate external temporal transition superiority = true
data-foundation evidence gate observed policy outcome superiority = false
TAP observed gridded temporal benchmark series = 10000
TAP observed gridded temporal benchmark holdout = 40000
TAP best dynamic MAE = 7.011689
TAP best static MAE = 9.309192
TAP dynamic MAE reduction vs static = 2.297503
TAP external dynamics holdout series = 10000
TAP external dynamics holdout points = 40000
TAP external best method = spatial_residual_delta_ridge
TAP external residual-delta transition MAE = 7.003808
TAP external adaptive online dynamic baseline MAE = 7.011689
TAP external paired win rate vs best non-spatial dynamic = 0.5077
TAP external supported claim = tap_external_temporal_dynamics_advantage_without_spatial_claim
TAP-like PM2.5 v2 records = 6048
TAP-like PM2.5 v2 CHAP anchor max abs error = 0.0
TAP-like PM2.5 v2 PM2.5 mean = 16.433
empirical_superiority_claim = false
```

这只能声明“在透明 known-effect simulator 和 proxy target panel 中，模型式图搜索优于静态单步启发式，基于 replay 的离线 value/world model 优于 train-mean baseline，且 learned dynamics imagined rollout 优于静态和一步 learned policy baseline”，不能声明真实政策效果优于传统方法。

OpenAQ 2018-10 temporal benchmark：

```text
observations = 600
pollutants = 6
holdout_points = 180
dynamic wins vs static_train_mean = 150/180
sign test vs static_train_mean p = 3.17e-23
sign test vs static_last_train_observation p = 7.02e-28
PM2.5 best static baseline MAE = 9.466667
PM2.5 dynamic MAE = 2.4
PM2.5 sign test vs best static p = 2.82e-6
ordered-vs-shuffled temporal control = passed on 6/6 pollutants
```

可声明：

```text
UWM online temporal state update 在真实 OpenAQ 时间序列 holdout 上，
显著优于传统静态 baseline suite，并通过时间顺序负控。
```

不可声明：

```text
UWM planner 已在真实政策 outcome 上优于传统方法。
```

## 7. 主要剩余缺口

| 缺口 | 为什么重要 | 当前处理 |
| --- | --- | --- |
| 真实政策 intervention outcome | 决定能否证明 planner 在真实治理上优于传统方法 | 未提供；未下载到公开可直接使用数据；本轮已补 synthetic policy outcome scaffold，但只作 OPE/负控脚手架，不能替代真实 outcome |
| 2024 scene-aligned station-calibrated air-quality holdout | 当前 2024 scene 用 Open-Meteo/CAMS/CHAP proxy 和 TAP-like semi-synthetic v2，OpenAQ 不覆盖 2024-07 | blocker 保留；v2 只解决开发闭环，不替代真实 holdout |
| scene-aligned meteorology grid/zonal validation | NOAA ISD 已补单站观测，但点位/representative point 仍不等于城市面状暴露 | 不再是 role audit 硬 blocker；作为空间代表性弱点保留 |
| 本地人口普查/脆弱性权威数据 | 已补本地区县人口统计，但 GHSL/WorldPop 仍是 public proxy 或 metadata，不是乡镇/街道权威人口普查 | 暂用区县统计 + GHSL；WorldPop 4.98GB/5.2GB 大文件未下载 |
| 完整服务可达性 | OSM 已从 200 点样本升级到中心 bbox 完整 amenity 抽取，但仍不是全市 POI 或路网时间面 | 已明确 bbox gap，不解释成真实服务缺失 |
| mobility / travel time / OD | OSM highway topology 已补 6,762 条 ways 和 45,468 条图边，但没有速度、拥堵、OD 和通勤观测 | 只能作为 mobility graph proxy，不作为真实可达性 outcome |
| learned value / policy | 当前已完成 offline value model、action-conditioned world-model policy 和 learned dynamics multi-step rollout planner，但仍不是在线 PPO/DRL，也没有 observed policy outcome OPE | 下一步是离线反事实策略评估、真实/准真实 outcome 接入和因果门控 |
| 行政边界许可/年代/crosswalk | 影响治理单元可信度 | 当前 claim ceiling 降为 fragile |
| 因果识别 / SCCA policy evidence | world-model policy claim 必须过因果门控 | 未完成 |

## 8. 下一步建议

1. 写完整 Track 2 初评研究报告：把“状态预测层强证据”和“政策 outcome 未完成”并列写清。
2. 继续下载或挂载 scene-aligned observed data：
   - 优先找 2024 或可切换场景期的站点空气质量；
   - 优先找本地人口普查、权威 POI/交通时间面、政策干预 outcome。
3. 把 simulator 从 known-effect 机制推进到 data-calibrated mechanism table。
4. 如果拿不到政策 outcome，就不要宣称 planner 真实优越性；只宣称架构优势、状态预测优势和 known-effect planner benchmark。
