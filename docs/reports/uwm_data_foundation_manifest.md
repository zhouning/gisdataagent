# UWM Data Foundation Manifest Notes

日期：2026-07-04；更新：2026-07-05

## 1. 目的

TAP status update on 2026-07-06: local TAP PM2.5 package is now parsed and registered as
`tap_pm25_observed_gridded_chongqing_2018_2024`. It strengthens `air_pollution_exposure`
from TAP-pending to TAP gridded available and supports a bounded gridded temporal
state-prediction benchmark. It does not close the observed policy outcome gate because TAP is
a multisource gridded product, not a station-observed intervention outcome.
The TAP external spatiotemporal dynamics holdout is also registered as a transition-layer
evidence gate. On 10,000 sampled grid series / 40,000 holdout points, the residual-delta
transition candidate slightly improves over the adaptive non-spatial online baseline
(MAE 7.003808 vs 7.011689; paired win rate 0.5077), so the artifact is `bounded_support`
for temporal transition improvement. Neighbor shuffle is not worse, so it still does not
support a spatial-attribution or policy-outcome superiority claim.

`uwm_data_foundation_manifest.csv` 是 UWM-Livability 的第一版数据基础清单。它用于约束后续 UWM 实现：没有进入 manifest、没有来源和 claim boundary 的数据，不应进入 renderer、simulator 或 planner。

## 2. 数据状态分层

### 2.1 真实或受限本地数据

这类数据来自规划院样例、Paper6 本地样本或其它本地工作区。它们可以支持研究推进，但需要保留使用边界。

当前包括：

- 重庆中心城区建筑轮廓与楼层；
- 重庆 DEM；
- 重庆 CLCD；
- OSM roads 样例；
- 高德 POI；
- 百度 AOI；
- 联通职住通勤；
- 百度搜索指数；
- 历史文化街区；
- 璧山 DLTB、行政/地籍边界、2019 用地台账和福禄镇村规数据库；
- CLCD 分类字典；
- 本地 `xiangzhen.shp` 提取的重庆乡镇/街道行政单元；
- Paper6 重庆 UHI 分析案例。

本轮对“你提供的数据是不是只有 8 行”做了口径修正：`8` 是早期 manifest 中 `synthetic_status=real` 的资产组数量，不是数据量。2026-07-05 重新复核并加入 fitted gap filling、offline world-model policy、learned rollout planner、graph-aware world model、synthetic policy outcome scaffold、livability intervention package、data-foundation evidence gate 与 TAP-like PM2.5 v2，2026-07-06 进一步加入 TAP observed gridded PM2.5 和 TAP external dynamics bounded transition gate 后，manifest 为 66 行，其中 `synthetic_status=real` 为 18 个资产组，`synthetic_status=fitted_proxy` 为 2 个资产组。已核对到的本地源规模包括：

- `/Users/zhouning/Downloads/规划院提供数据样例及Demo系统功能演示建议.zip`：447 MB 压缩包；解压后的 `01数据样例` 实扫 584 个文件，其中包含 FileGDB 内部文件；
- 规划院 zip 中建筑轮廓 shapefile：按 `.shx` record index 推算为 107,452 条记录；
- 规划院 zip 中 OSM roads：按 `.shx` record index 推算为 50,366 条记录；
- 规划院 zip 中高德 POI FileGDB：1,194,351 个 Point features；
- 规划院 zip 中百度 AOI FileGDB：26,292 个 MultiPolygon features；
- 规划院 zip 中联通职住通勤 CSV：2,120 行、259 个居住格网、697 个工作格网、扩样后人口 29,634.79665；但缺格网几何字典；
- 规划院 zip 中百度搜索指数 FileGDB：325 条城际搜索流、26 个出发城市、26 个目的城市、总搜索指数 8,694,518；
- 规划院 zip 中中心城区历史文化街区：20 个 Polygon Z features；
- 规划院 zip 中璧山 DLTB：101,657 个 MultiPolygon features；
- 规划院 zip 中璧山 2019 用地台账：1,438 个非空工作表行，含表头/标题行；
- 规划院 zip 中福禄镇村规数据库：31 个 shapefile、8,050 个总要素；
- DEM GeoTIFF：1,766 x 1,454，共 2,567,764 个像元；
- CLCD 2020 GeoTIFF：18,579 x 15,082，共 280,208,478 个像元；
- `/Users/zhouning/Downloads/shp`：126 个文件，约 1.05 GB，15 组 shapefile；
- `xiangzhen.shp` 原始层：按 `.shx` record index 推算为 43,655 条记录；UWM 当前派生重庆子集为 1,017 个乡镇/街道行政单元、38 个区县。
- 已从上述 1,017 个重庆乡镇/街道行政单元派生 `chongqing_admin_spatial_adjacency_graph_2026_07_05`，包含 1,017 个节点、2,847 条行政边界邻接边、0 个孤立节点。它是行政拓扑图，不是道路网络或出行/mobility graph。

高德 POI、百度 AOI、百度搜索指数等 FileGDB 已在本轮用 `pyogrio` 实读；此前“feature count 待 profile”的旧口径已废弃。本轮复核报告见：

```text
docs/reports/uwm_local_planning_zip_audit_2026-07-05.md
```

这些数据不能自动等价为公开可发布数据。用于 Track 2 时，需要在数据说明中解释来源、权限和可复现替代方案。

### 2.2 公开代理数据

这类数据优先从公开渠道补齐，并通过 MMFE 进入 UWM。

当前候选包括：

- ERA5 气象；
- GEE ERA5 hourly point proxy，当前已下载 2024-07-01 至 2024-07-07 重庆中心点 168 条小时记录；
- GEE ERA5/CAMS 行政单元 representative-point proxy，当前已覆盖 1017 个重庆乡镇/街道代表点；
- GEE ERA5/CAMS livability candidate simplified-polygon zonal proxy，当前已覆盖 36/36 个 admin livability 候选行政面；
- Open-Meteo current weather live proxy；
- Open-Meteo historical weather point proxy，当前已下载 2024-07-01 至 2024-07-07 重庆中心点气象历史代理；
- Open-Meteo 2018-10 weather point proxy，当前已下载 OpenAQ temporal benchmark 同期天气上下文；空气质量接口返回全 null，因此不作为空气污染有效证据；
- CAMS 或同类空气污染代理；
- GEE CAMS/NRT point proxy，当前已下载 2024-07-01 至 2024-07-07 重庆中心点 574 条记录；
- OpenAQ 站点空气污染代理，当前已下载重庆中心点 25 km 内 15 个站点、90 个传感器、600 条观测样本；
- OpenAQ 2024-07 scene attempt 已用运行时 key 尝试下载重庆中心 25 km 内 2024-07-01 至 2024-07-07 sensor measurements；结果为 15 个 locations、90 个 sensors、0 条 measurements，因此不能登记为 scene-aligned observed holdout；
- OpenAQ temporal state benchmark，已用上述 600 条真实小时观测构造 70% train / 30% holdout，并证明动态状态更新在 6 个污染物上均击败 `static_train_mean` 和 `static_last_train_observation`，总体 sign test p 值分别为 3.17e-23 和 7.02e-28；确定性乱序负控显示 6/6 个污染物依赖真实时间顺序；
- Open-Meteo current air-quality live proxy；
- Open-Meteo historical air-quality point proxy，当前已下载 2024-07-01 至 2024-07-07 重庆中心点空气质量历史代理；
- Open-Meteo livability admin air-quality proxy，当前已下载 36/36 个 admin livability 候选行政单元代表点、6048 条小时空气质量记录；
- CHAP ChinaHighPM2.5 2024-07 monthly 1km proxy，当前已从 Zenodo 下载 `CHAP_PM2.5_M1K_202407_V4.nc`，并对 36/36 个 admin livability 候选行政单元代表点完成最近邻采样，PM2.5 均值 16.433 ug/m3；它是公开 AI-fused gridded product，不是站点观测；
- NOAA ISD 2024-07 observed weather，当前已下载 `575160-99999-2024.gz` 和 `isd-history.csv`，核验站点为 JIANGBEI / ZUCK，并解析 2024-07-01 至 2024-07-07 共 224 条场景窗口观测；
- Paper58 AlphaEarth / GeoFM 表征；
- WorldPop 人口代理；
- 本地重庆区县人口统计，来自规划样例 Excel，来源字段为 `重庆市统计年鉴2022`；已生成 39 个区县 + 1 个全市总计的 normalized proxy 与 MMFE state input；
- 本地联通职住通勤和百度搜索指数，来自规划院 zip；已生成 normalized proxy 和 CSV。它们增强 `mobility_activity`，但联通缺格网几何字典、百度搜索指数不是出行观测，不能替代 travel-time / traffic-flow / OD outcome；
- GHSL 人口与建成区代理，当前已下载 2020 年覆盖重庆全市范围的 4326 30ss 人口/建成区瓦片，并生成了面向重庆乡镇/街道行政单元的分区统计代理产物；
- OSM public service POI / road substitute，已从 200 点历史样本升级出一版完整 bbox 抽取：786 个 amenity node/way/relation center 元素，以及 6,762 条 highway ways、45,468 条道路拓扑边；
- UWM Graph-MDP model-based graph search report，上一版基于 admin livability proxy panel 生成 8 个 proxy admin units、2-step beam search 和 109 条 replay transitions；它只支持 known-effect model-based graph search advantage，不是 observed policy outcome；
- UWM Spatial Graph-MDP model-based graph search report，当前基于全量行政边界邻接图和 36 个 admin livability 候选单元生成 96 条真实空间邻接边、355 条 replay transitions；best known-effect reward 为 0.012346806，static single-step reward 为 0.001439757；仍不是 observed policy outcome；
- UWM offline graph value model report，当前基于上述 355 条 spatial Graph-MDP simulator replay transitions 训练 ridge value model；holdout MAE 为 0.000165326，train-mean baseline MAE 为 0.002418188；只说明 replay value fitting 成立，不是 observed policy outcome；
- UWM offline world-model policy report，当前基于上述 355 条 replay 训练 action-conditioned reward+dynamics model；holdout reward MAE 为 0.000165324，train-mean baseline MAE 为 0.002418188；保守 learned policy 在 replay 中的 mean reward 为 0.009041181，高于静态启发式 0.007839757；这是真正的世界模型 RL scaffold，但仍不是真实政策 outcome 或在线 PPO；
- UWM learned world-model rollout planner report，当前基于同一 action-conditioned reward+dynamics model 做 2-step imagined rollout，并逐步写回 latent state；selected sequence 为 `increase_green_infrastructure-江北区|观音桥街道|653` -> `add_community_service-九龙坡区|谢家湾街道|785`；imagined conservative score 为 0.011528613，高于 static 0.00124898 和 one-step learned policy 0.002012933；这是真正的 learned dynamics planning scaffold，但仍不是真实政策 outcome 或在线 PPO；
- UWM graph-aware world model report，当前基于同一 spatial Graph-MDP replay 和 96 条候选单元行政邻接边训练 graph-aware action-conditioned dynamics；holdout reward MAE 为 0.000103937，优于 target-only baseline 0.000844982 和 train-mean baseline 0.002418188，reward win rate vs target-only 为 0.957746479；这是空间消息驱动的世界模型结构增强，但仍不是真实政策 outcome；
- UWM livability intervention package，当前把 learned rollout、synthetic policy outcome scaffold 和 TAP-like PM2.5 v2 组织成证据门控城市干预方案包，输出低宜居区域识别、机制解释、干预适宜性、多步 action sequence、前后指标变化、公平性结论和证据边界；supported proxy claim 为 `business_theory_aligned_learned_rollout_beats_static_proxy_baseline`，claim boundary 为 `exploratory_only`，仍不是 observed intervention outcome；
- UWM data-foundation evidence gate，当前读取完整 manifest、OpenAQ observed temporal benchmark、TAP external dynamics holdout、本地规划院 inventory、行政空间邻接图、learned rollout 和 livability intervention package；明确所有数据基础资产均可使用，但按 `synthetic_status`、`source_type`、`access_status` 和 artifact-level evidence 分层；OpenAQ observed temporal state prediction superiority 为 true，TAP external temporal transition superiority 为 true，observed policy outcome superiority 为 false；
- UWM fitted population downscaling，当前基于本地区县人口统计和 GHSL admin alignment 生成 852 行 fitted proxy，3290.08 万输入人口与输出人口完全守恒；845 行使用 GHSL 权重，7 行为无 GHSL 匹配的区县 fallback。它不是乡镇/街道权威人口、格网人口或 2024 场景人口；
- UWM Unicom latent mobility graph，当前基于联通职住通勤 CSV 聚合为 1,067 条有向边和 756 个节点，expanded population 合计 29,634.796667。它无格网几何字典，不是空间 OD 面、出行时间、交通流或政策 outcome；
- UWM semi-synthetic scene-aligned PM2.5 panel，当前基于 GEE/CAMS 2024 zonal PM2.5 空间基底和 OpenAQ 2018 真实 PM2.5 小时扰动结构生成 36 个候选行政单元 x 168 小时 = 6048 条记录；仅用于 stress test 和 negative control，不是 observed holdout；
- 后续可补充 Sentinel、Landsat、MODIS、OpenAQ 等。
- TAP Tracking Air Pollution in China 本地包已解析为 `tap_pm25_observed_gridded_chongqing_2018_2024`，包含 2018-10-17 至 2018-10-23 与 2024-07-01 至 2024-07-07 重庆 1km 日 PM2.5 栅格窗口，以及 2024-07 10km PM2.5 species 月包；它是 TAP 多源融合格网产品，不是站点观测或政策 outcome。
- TAP external spatiotemporal dynamics holdout 已生成 `tap_pm25_external_spatiotemporal_dynamics_chongqing_2018_2024`：10,000 grid series / 40,000 holdout points，residual-delta transition ridge MAE 7.003808，adaptive online dynamic baseline MAE 7.011689，static train mean MAE 9.309192；paired win rate vs best non-spatial dynamic 为 0.5077，时间顺序旋转负控变差 1.585932 MAE，未来标签泄漏检查通过；但 neighbor shuffle 负控不变差，因此 supported claim 为 `tap_external_temporal_dynamics_advantage_without_spatial_claim`，claim boundary 为 `bounded_support`，不能作空间归因或政策 outcome 优越性声明。

公开代理数据可以支持 bounded support，但不能在没有本地校准和证据门控的情况下升级为 core support。

### 2.3 拟合补全数据

`fitted_proxy` 是由已审计真实/公开代理输入拟合得到的状态补全层。它可以改善 simulator/planner 输入完整性，但不能升级为真实观测、权威数据或实证优越性证据。

当前包括：

- `uwm_fitted_admin_population_downscaling_2021`：区县总量守恒人口下推层；
- `uwm_unicom_latent_mobility_graph_2023`：联通 OD 表聚合得到的无坐标潜在通勤图。

### 2.4 半合成和合成数据

EPA Green Book benchmark 当前在 Paper6 中是真实政策地理结构加半合成已知效应结果，适合用于 UWM-Air 的公开验证，但不能替代重庆空气污染观测。

`semi_synthetic_air_quality_scene_2024_07` 是在 OpenAQ 2024-07 重庆场景尝试返回 0 measurements 后生成的半合成 scene-aligned PM2.5 面板，只能用于 pipeline 压力测试、负控和合成 holdout scaffold。

`tap_like_pm25_scene_v2_2024_07` 是 TAP 审核通过前的开发替代层：CHAP 2024-07 月均 PM2.5 作为硬锚，Open-Meteo 2024 小时 PM2.5 提供时序形状，OpenAQ 历史 PM2.5 提供真实扰动结构，NOAA ISD 观测气象提供通风/温度调整，GEE CAMS zonal 作为可选空间上下文。当前输出 36 个候选行政单元 x 168 小时 = 6048 条记录，CHAP anchor max abs error = 0.0 ug/m3。它不是 TAP 数据、不是 observed holdout，只用于 UWM 开发、simulator/planner/OPE 管线压力测试。

`uwm_synthetic_policy_outcome_benchmark_admin_livability_spatial_graph` 是在真实政策 outcome 缺失时生成的合成 policy-outcome scaffold。它用 UWM simulator 在同一 reconstructed Graph-MDP observation 和同一 scenario 下比较 static heuristic、Graph-MDP best 与 learned rollout policy；learned rollout synthetic reward 为 0.006346806，static reward 为 -0.004560243，advantage 为 0.010907049。它只能用于 OPE/negative-control 管线联调，不能解除真实政策 outcome gate。

`uwm_livability_intervention_package_admin_livability_spatial_graph` 是在真实政策 outcome 和 TAP 权威场景数据仍缺时生成的合成业务方案包。它不是额外观测数据，而是把 UWM 世界模型输出转成城市宜居性理论要求的结果形态：低宜居区域识别、机制解释、干预适宜性、多步行动、前后指标变化、公平性和证据边界。它只能用于开发、方案表达和 OPE/negative-control 脚手架，不能替代客户权威数据验证后的政策方案。

合成空气质量占位数据只允许用于：

- smoke test；
- pipeline 联调；
- 已知效应验证；
- 缺失权威数据时的流程占位。

合成数据不能用于真实城市事实结论。

## 3. Claim Boundary

清单中的 `claim_boundary` 字段定义下游结论上限：

- `core_support`：强证据支持。当前 UWM v0 不默认使用。
- `bounded_support`：可用于有限证据结论，必须说明数据和模型边界。
- `fragile`：仅用于探索，存在明显风险。
- `exploratory_only`：只能做演示、压力测试或研究假设生成。
- `not_for_claim`：不能用于任何研究结论。

规则：

```text
synthetic / semi_synthetic / fitted_proxy / smoke_only 数据不能使用 core_support。
public_proxy 数据必须经过证据门控后才可形成 bounded_support。
restricted_local 数据必须说明复现替代路线。
raw_public_proxy_available 只表示原始公开数据已下载，不能跳过裁剪、MMFE 对齐和验证。
proxy_available 表示公开代理数据已经进入可审计的对齐产物，但仍不能替代权威本地数据或真实观测 holdout。
fitted_proxy 表示由已审计输入拟合得到的补全层，只能用于 simulator/planner scaffold 或探索性分析。
```

## 4. 与 MMFE 的关系

UWM 不应直接消费散乱原始数据。数据进入 UWM 的目标路径是：

```text
data manifest
-> MMFE profiling / assessment / alignment / execution / validation
-> mmfe.uwm_state_input.v1
-> UwmCanonicalObservation.v1
```

后续每次补充公开数据或合成数据，都应更新本 manifest 并保留 MMFE trace。

## 5. 下一步

1. 用 `data_agent.uwm.manifest.audit_uwm_manifest` 持续检查 CSV。
2. 用 `data_agent.uwm.data_foundation.audit_uwm_data_foundation_manifest` 检查 UWM 核心数据角色覆盖。
3. 为公开数据补充 source URL、许可证和下载记录。
4. 将通勤、空气污染、气象、人口脆弱性和公共服务数据逐步补齐。
5. 将 manifest 接入 UWM tab 的 Data Foundation 面板。

## 6. 当前角色级覆盖审计

审计文件：

```text
docs/reports/uwm_data_foundation_coverage_audit.md
```

当前摘要：

```text
manifest_valid = true
manifest_row_count = 66
missing_required_roles = []
claim_ceiling = fragile
empirical_superiority_blockers = [
  air_pollution_exposure
]
```

解释：

- UWM 核心数据角色已经不再缺项；
- 人口脆弱性已有本地区县人口统计、GHSL public proxy 分区统计产物、`mmfe.uwm_state_input.v1` 状态输入和 fitted population downscaling，但 fitted_proxy 仍不是本地人口普查、乡镇/街道权威人口、2024 场景人口或观测 holdout；
- 空气污染已有 Open-Meteo 历史点位代理、GEE CAMS 点位代理、GEE 行政单元代表点代理、GEE livability candidate polygon zonal proxy、CHAP 2024-07 月均 1km PM2.5、OpenAQ 真实站点观测代理，并已生成部分 `mmfe.uwm_state_input.v1` 状态输入；OpenAQ temporal benchmark 可以支撑状态预测层 observed holdout 结论，但仍不是 2024 scene station-calibrated observed intervention holdout；OpenAQ 2024-07 scene attempt 为 0 measurements；
- 气象已有 Open-Meteo 历史点位代理、GEE ERA5 点位/行政单元代理、GEE livability candidate polygon zonal proxy，并新增 NOAA ISD 2024-07 江北站观测气象；因此 meteorology role audit 硬 blocker 已解除，但单站观测仍不能替代全城格网/面状校准；
- 空间邻接图已有 `spatial_adjacency_graph` 角色覆盖，来源于全量 1,017 个重庆乡镇/街道行政单元，支持 Graph-MDP simulator/planner 的邻接溢出和空间状态编码；它不替代道路图、OD、通勤或 travel-time accessibility；
- 本地行政边界层可支撑治理单元对齐，但官方年代、许可和现代区县名 crosswalk 未核验，因此当前总 claim ceiling 为 fragile；
- 因此当前可以支撑带明确边界的世界模型链条和 known-effect 证明；
- 尚不能支撑真实 observed holdout 上“比传统方法更强”的实证声明。

下载阻塞：

```text
ERA5 和 CAMS 已确认可通过本机已认证 GEE 获取，本轮已完成重庆中心点 2024-07-01 至 2024-07-07 采样；
Open-Meteo forecast / air-quality 当前在本机可访问，可作为 live environmental proxy；
但 Open-Meteo 不能替代 ERA5/CAMS 的长期历史栅格或站点校准 holdout；
Open-Meteo historical weather / air-quality 已下载 2024-07-01 至 2024-07-07 重庆中心点代理数据，并生成 `data/uwm_public_proxy/chongqing_central/openmeteo_history_2024_07_01_07/mmfe_uwm_state_input_openmeteo_history.json`；
Open-Meteo historical weather 已下载 2018-10-17 至 2018-10-23 重庆中心点代理数据以对齐 OpenAQ temporal benchmark；同时间窗 air-quality API 返回全 null 污染物值，已在 proxy limitations 中标记 `air_quality_values_missing_for_requested_period`；
OpenAQ v3 已用运行时 X-API-Key 完成下载，key 未写入仓库；当前可用站点观测覆盖 2018-10-17 至 2021-08-09，不覆盖 2024-07 场景 holdout；本轮使用 scene datetime window 重新尝试 2024-07-01 至 2024-07-07，结果为 0 measurements；已派生 temporal state benchmark，但不能替代政策 outcome holdout；
CHAP ChinaHighPM2.5 2024-07 月均 1km NetCDF 已下载并生成 `data/uwm_public_proxy/chongqing_central/chap_pm25_2024_07/chap_pm25_admin_proxy.json`；
NOAA ISD 575160-99999 2024 文件与 station history 已下载并生成 `data/uwm_public_proxy/chongqing_central/noaa_isd_weather_2024_07_01_07/noaa_isd_weather_proxy.json`；
TAP 本地包 `/Users/zhouning/Downloads/tap_uwm` 已解析为 gridded public_proxy artifact；账号/授权和 TAP 非商业不可再分发条款仍需合规跟踪，且该数据不替代 station-calibrated observed holdout 或政策 outcome；TAP external dynamics holdout 已作为 bounded transition gate 登记，支持有限的外部状态转移改进，但不支持空间归因或政策 outcome 优越性；
GEE ERA5/CAMS 已进一步下载 36 个 admin livability 候选行政面的 simplified-polygon zonal proxy，可改善 scene context，但仍是 reanalysis/model proxy，不是 observed holdout；
WorldPop 国家目录已下载，但 2020 中国 100m GeoTIFF 约 4.98GB，当前只记录目录和文件规模，未下载全国大文件；已通过 7897 代理探测 WorldPop Global2 R2025A，完整人口 raster zip 为 5.2GB，未下载；已下载 15KB country/type metadata CSV，China 行显示 c.2020 round data type 为 Census，但该 CSV 不含人口值，不能作为 UWM 人口数据使用；
本地规划样例中的 `08重庆市各区县人口规模表格数据/重庆市各区县人口规模数据.xlsx` 已核实并生成 UWM 资产：40 行，其中 39 个区县、1 个全市总计；2021 年区县常住人口合计 3290.08 万人，最大常住人口区县为渝北区 220.58 万人；这是区县级统计，不是乡镇/街道或格网人口；
GHSL 2020 人口/建成区瓦片已真实下载到 `data/uwm_public_proxy/chongqing_central/ghsl/tiles`，并已生成 `data/uwm_public_proxy/chongqing_central/ghsl_admin_alignment/ghsl_admin_zonal_proxy.csv` 与 `mmfe_uwm_state_input_ghsl_admin.json`；
OSM Overpass 已保留重庆中心 bbox 200 个带坐标 amenity 节点历史样本，并新增完整 bbox amenity node/way/relation center 抽取：786 个 amenity 元素、163 个 essential service 代理点，已生成 `data/uwm_public_proxy/chongqing_central/osm_complete_bbox_2026_07_05/service/mmfe_uwm_state_input_osm_service_accessibility.json`；
OSM Overpass 已新增完整 bbox highway way + child nodes 抽取：48,820 个 OSM elements、42,058 个 coordinate nodes、6,762 条 highway ways、45,468 条图边和 57 个连通分量，已生成 `data/uwm_public_proxy/chongqing_central/osm_complete_bbox_2026_07_05/mobility/mmfe_uwm_state_input_osm_mobility_network.json`；它仍不是全市完整道路网、网络出行时间、OD 或交通流观测。
```
