# UWM 本地规划院 Zip 复核报告

日期：2026-07-05

源文件：

```text
/Users/zhouning/Downloads/规划院提供数据样例及Demo系统功能演示建议.zip
```

审计产物：

```text
data/uwm_public_proxy/chongqing_central/local_planning_zip_audit_2026_07_05/
```

## 1. 对漏审问题的结论

这次批评是成立的。之前漏掉人口数据的根因不是“数据不存在”，而是审计方法不合格：只按 12 个顶层目录和少数已知图层做资产登记，没有逐个打开表格、FileGDB 图层、SHP 和深层规划数据库。因此 `08重庆市各区县人口规模表格数据/重庆市各区县人口规模数据.xlsx` 被漏看，联通通勤、百度搜索指数、历史文化街区、璧山 DLTB、规划台账和村规数据库也没有进入 UWM 数据基础。

本次修正后的规则是：

```text
先枚举文件 -> 再读取表/图层/栅格元数据 -> 再判断 UWM 角色 -> 最后写入 manifest 和 claim boundary
```

没有读到的内容不再写成事实。

## 2. 解压目录实扫

本次对解压后的 `01数据样例` 实扫到 584 个文件。这个数量包含 FileGDB 内部文件；此前 zip 条目口径和解压后文件口径不同，不能混用。

主要类型：

| 类型 | 数量 | 说明 |
| --- | ---: | --- |
| `.shp/.shx/.dbf` | 31 / 31 / 33 | 含道路、建筑、历史文化街区、村规数据库等 |
| FileGDB 目录 | 6 | 其中 5 个可读；一个外层 wrapper 不可直接读，但其内部嵌套 GDB 可读 |
| `.tif` | 2 | DEM、CLCD 2020 |
| `.csv` | 1 | 联通职住通勤 |
| `.xlsx` | 14 | 人口、CLCD 字典、储备土地、村规表 |
| `.xls` | 5 | 建设用地规划许可、征地、出让划拨、土地利用结构、空间功能布局 |
| `.dwg/.pdf/.doc/.jpg/.png` | 多类 | 规划文本、图纸、附件，作为规划上下文，不直接进入 UWM 状态 |

## 3. 本次新增或补画像的 UWM 数据资产

| 数据资产 | 实读规模 | UWM 角色 | 状态边界 |
| --- | ---: | --- | --- |
| `chongqing_unicom_commuting_2023_local` | 2,120 行；259 个居住格网；697 个工作格网；扩样后人口 29,634.79665 | `mobility_activity` / `commuting_od` / `population_vulnerability` | 真实本地表，但缺格网几何字典；`工作格网=0` 含义未核验，不能当出行时间或交通流 |
| `baidu_search_index_2023_local` | 325 条城际搜索流；26 个出发城市；26 个目的城市；总搜索指数 8,694,518 | `urban_activity_proxy` / `mobility_activity` | 真实搜索兴趣，不是观测出行、交通量或政策 outcome |
| `chongqing_historic_districts_local` | 20 个 Polygon Z | `urban_form` / `cultural_heritage` / `livability_context` | 支撑文化宜居性和保护约束；来源许可、年代仍需核验 |
| `bishan_land_use_dltb_local` | 101,657 个 DLTB MultiPolygon | `land_use_context` / `planning_constraints` | 璧山样例，不是重庆全城现状；可作规划约束上下文 |
| `bishan_admin_cadastral_boundary_local` | CJDCQ 1,488 个面；XZQ 15 个面 | `administrative_units` / `planning_constraints` | 本地边界上下文，不替代全市现代行政单元 |
| `bishan_land_development_ledger_2019_local` | 1,438 个非空工作表行，含表头/标题行 | `land_development_pressure` / `planner_constraints` | 台账上下文，不是空间 outcome |
| `fulu_village_planning_database_local` | 31 个 shapefile；8,050 个总要素 | `planning_constraints` / `village_livability_context` | 福禄镇和平村/斑竹村样例，不是全城 |
| `clcd_classification_dictionary_local` | 9 个 CLCD 类别 | `remote_sensing_state` | 支撑 CLCD 栅格解释 |

同时补全了原 manifest 中已有但此前未画像的资产：

| 已有资产 | 本次实读结果 |
| --- | --- |
| `gaode_poi_2024` | 1,194,351 个 Point；EPSG:4490 |
| `baidu_aoi_2024` | 26,292 个 MultiPolygon；EPSG:4490 |
| `chongqing_central_buildings_2021` | 107,452 个 Polygon；EPSG:4326 |
| `chongqing_osm_roads_2021` | 50,366 个 LineString；EPSG:4326 |
| `chongqing_dem_80m` | 1,766 x 1,454 = 2,567,764 pixels；EPSG:4490 |
| `chongqing_clcd_2020` | 18,579 x 15,082 = 280,208,478 pixels；EPSG:4326 |
| `chongqing_district_population_stats_2021_local` | 40 条数据行：39 个区县 + 1 个全市总计；2021 年区县常住人口合计 3,290.08 万人 |

## 4. 已写入的 UWM 产物

新增文件：

```text
data/uwm_public_proxy/chongqing_central/local_planning_zip_audit_2026_07_05/
  snapshot_manifest.json
  uwm_local_planning_zip_audit.json
  uwm_local_planning_zip_inventory.csv
  chongqing_unicom_commuting_proxy.json
  chongqing_unicom_commuting_od_rows.csv
  baidu_search_index_proxy.json
  baidu_search_index_flows.csv
```

新增代码：

```text
data_agent/uwm/local_planning_zip_audit.py
scripts/build_uwm_local_planning_zip_audit.py
data_agent/test_uwm_local_planning_zip_audit.py
```

主清单 `docs/reports/uwm_data_foundation_manifest.csv` 已更新为 55 行，其中 `synthetic_status=real` 为 18 个资产组。

## 5. 仍然不能伪装成已解决的缺口

| 缺口 | 说明 |
| --- | --- |
| 联通格网几何字典 | zip 里没有找到对应格网边界/中心点字典，因此通勤表不能直接空间化 |
| 出行时间/交通流/网络阻抗 | OSM roads 和联通 OD 都不能替代真实 travel-time 或 traffic-flow |
| 2024 场景站点校准空气质量 holdout | OpenAQ 2024-07 返回 0 measurements；TAP 仍待账号审核 |
| 真实政策干预 outcome | 仍缺，不能宣称 planner 真实政策效果优于传统方法 |
| 乡镇/街道或格网权威人口 | 已有区县统计和 GHSL 代理，但不是 2024 场景的权威细粒度人口 |
| 受限本地数据许可 | 规划院 zip、高德、百度、联通、规划台账等均需保留 restricted/local 边界 |

## 6. 对 UWM 的意义

这次复核显著加强了 UWM 数据基础：宜居性不再只依赖 OSM/GHSL/GEE 公开代理，而是补入了真实本地 POI/AOI、文化街区、通勤活动、搜索活动、地类图斑、开发台账和村规约束。它们能支撑更完整的 renderer 状态、simulator 约束和 planner 候选动作空间。

但这次复核没有把 UWM 的最高实证结论升级为“真实政策效果优于传统方法”。当前可证明的强结论仍是 OpenAQ temporal holdout 上的状态预测优势，以及透明 known-effect simulator 中 Graph-MDP 搜索/离线 value fitting 的优势。
