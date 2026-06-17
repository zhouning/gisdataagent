# TWM 自然资源“一张图”标准材料评估

- **日期**：2026-06-16
- **材料包**：`/Users/zhouning/Downloads/自然资源一张图数据库标准1128 (2).zip`
- **解压分析目录**：`.tmp/twm_standard_1128/自然资源一张图数据库标准1128`
- **用途**：将 GIS Data Agent 的“数据标准全生命周期智能化管理”能力接入 TWM，形成可替换、可质检、可追溯的数据标准契约。

## 1. 结论

该材料包对 TWM 非常有用，不能只当作参考文档。它应转化为 TWM 的标准契约来源：

1. **标准分册可作为 TWM 角色字段契约来源**：已覆盖统一调查监测、统一规划、底线安全、用途管制、执法督察、元数据等 TWM 核心角色。
2. **当前 TWM 测试包需要升级**：现有 synthetic PBF、生态红线、城镇开发边界、项目、审批、执法数据能支撑工程逻辑，但还不符合“一张图”标准字段结构。
3. **样例村规划数据可直接利用**：包内和平村、斑竹村规划数据库包含 `JQDLTB`、`TDGHDL`、`JSYDGZQ`、`STBHHX`、`YBD` 等图层，可作为比纯合成数据更真实的“标准结构替身测试集”。
4. **标准平台应接管这些契约**：应将字段、约束、值域、引用标准、版本来源导入标准平台，再派生 TWM 的 `field_mapping`、`quality_rule` 和 `spatial_policy_rule` 候选。

## 2. 材料包内容

### 2.1 标准文档

核心分册：

| 分册 | 与 TWM 的关系 |
|---|---|
| `（0）绪论1128` | 总体数据库模块、引用标准清单 |
| `（1）统一地理底图1126` | 行政区、遥感影像、DEM、基础道路等底图数据 |
| `（2）统一调查监测1126` | `DLTB`、年度更新、城镇开发边界、生态红线、统计汇总 |
| `（4）统一规划1126` | 永久基本农田、生态红线、城镇开发边界、规划分区、村庄规划 |
| `（5）底线安全1126` | 永久基本农田保护图斑、占用补划、耕地保护、设施农业、土地征收 |
| `（6）用途管制1128V2` | 项目占地范围、预审选址、农转用、土地征收、规划许可 |
| `（8）执法督察0922` | 违法地块、遥感新增/疑似建设用地图斑、违法处置、证据 |
| `（10）元数据0907` | `meta_VectorData`、`meta_NormalData`，可映射到 data catalog 与 lineage |

### 2.2 本地已具备的引用标准

| 标准 | 本地状态 | 说明 |
|---|---|---|
| `GB/T 21010-2017 土地利用现状分类` | 已在包内，含 PDF 和整理版 docx | 可用于 `DLBM/DLMC` 值域、地类语义、TWM land-use mapping |

### 2.3 仍需外部权威获取的引用标准

绪论和分册中引用但当前未在包内发现原文的关键标准包括：

| 标准/规范 | 用途 |
|---|---|
| `乡镇级国土空间规划数据库规范(试行)` | 村镇规划数据库结构、规划地类、空间管制要素 |
| `城镇开发边界内详细规划数据库规范(试行)` | 城镇开发边界内详细规划图层和字段 |
| `永久基本农田数据库标准（2021版）(试行)` | PBF 图斑字段、保护责任、质量字段 |
| `永久基本农田数据库标准（2019版）` | 历史兼容 |
| `全国国土空间用途管制监管系统交互数据规范（一）（二）` | 用途管制审批/项目空间范围、电子监管号、案卷关联 |

在线检索未稳定获取到官方直链。后续应优先通过自然资源部、标准全文公开系统、业务合作环境或政府内网获取权威版本。

## 3. TWM 核心角色标准契约

### 3.1 `parcel_current` 对应 `DLTB`

来源：`统一调查监测` 表5-13 `DLTB`。

关键必填字段：

| 字段 | 中文名 | 约束 |
|---|---|---|
| `BSM` | 标识码 | M |
| `YSDM` | 要素代码 | M |
| `TBBH` | 图斑编号 | M |
| `DLBM` | 地类编码 | M |
| `DLMC` | 地类名称 | M |
| `QSXZ` | 权属性质 | M |
| `QSDWDM` | 权属单位代码 | M |
| `QSDWMC` | 权属单位名称 | M |
| `ZLDWDM` | 坐落单位代码 | M |
| `ZLDWMC` | 坐落单位名称 | M |
| `TBMJ` | 图斑面积 | M，`>0`，平方米 |
| `TBDLMJ` | 图斑地类面积 | M，`>0`，平方米 |
| `SJNF` | 数据年份 | M |
| `MSSM` | 描述说明 | M |

当前 TWM 测试包差距：

- 已有：`BSM`、`YSDM`、`DLBM`、`DLMC`、`QSDWDM`、`QSDWMC`、`ZLDWDM`、`ZLDWMC`、`TBMJ`。
- 缺少或未标准化：`TBBH`、`QSXZ`、`TBDLMJ`、`SJNF`、`MSSM`。

### 3.2 `pbf` 对应 `YJJBNT / YJJBNTTB`

来源：

- `统一规划` 永久基本农田属性结构 `YJJBNT`
- `底线安全` 永久基本农田保护图斑 `YJJBNTTB`

关键字段：

| 字段 | 中文名 | 约束/说明 |
|---|---|---|
| `BSM` | 标识码 | 基本标识 |
| `YSDM` | 要素代码 | 标准要素代码 |
| `XZQDM`/`XZQMC` | 行政区代码/名称 | M |
| `YJJBNTTBBH` | 永久基本农田图斑编号 | M |
| `TBBH` | 来源图斑编号 | M |
| `DLBM`/`DLMC` | 地类编码/名称 | M |
| `QSXZ` | 权属性质 | M |
| `QSDWDM`/`QSDWMC` | 权属单位 | M |
| `ZLDWDM`/`ZLDWMC` | 坐落单位 | M |
| `YJJBNTTBMJ` | 永久基本农田图斑面积 | M |
| `YJJBNTMJ` | 永久基本农田面积 | M |
| `GDPDJB` | 耕地坡度级别 | 耕地必选 |
| `SJNF` | 数据年份 | M |
| `BHKSSJ`/`BHJSSJ` | 保护起止时间 | M/O |
| `WDGD` | 是否稳定利用耕地 | M |

当前测试包差距：

- `synthetic_pbf.geojson` 只有演示字段，尚未镜像 `YJJBNT/YJJBNTTB` 字段。
- 下一步应为合成 PBF 增加标准字段镜像，或新增 `standard_role=pbf` 的语义字段映射。

### 3.3 `eco_redline` 对应 `STBHHX`

来源：

- `统一调查监测` `STBHHX`
- `统一规划` `STBHHX`

两套字段口径有差异：

| 来源 | 重点字段 |
|---|---|
| 调查监测 | `BSM`、`YSDM`、`XJXZQHDM`、`LXDM`、`SLDM`、`MC`、`QYMJ`、`SLSJ`、`GKCS` |
| 统一规划 | `BSM`、`YSDM`、`XJXZQDM`、`SJXZQMC`、`SJXZQMC1`、`XJXZQMC`、`LHLX`、`MJ` |

当前测试包差距：

- `synthetic_eco_redline.geojson` 尚未包含上述标准字段。
- 建议优先采用统一规划口径作为 TWM 硬约束图层字段契约，调查监测口径作为兼容别名。

### 3.4 `urban_boundary` / `planning_zone` 对应 `CZKFBJ` 与规划分区

来源：

- `统一调查监测` `CZKFBJ`
- `统一规划` `CZKFBJ`

统一规划 `CZKFBJ` 关键字段：

| 字段 | 中文名 |
|---|---|
| `BSM` | 标识码 |
| `YSDM` | 要素代码 |
| `XZQDM` | 行政区代码 |
| `XZQMC` | 行政区名称 |
| `GHFQDM` | 规划分区代码 |
| `GHFQMC` | 规划分区名称 |
| `MJ` | 面积 |

注：城镇开发边界规划分区包括城镇集中建设区、城镇弹性发展区、特别用途区。

当前测试包差距：

- `synthetic_urban_boundary.geojson` 与 `synthetic_planning_zones.geojson` 字段为演示口径。
- 应补 `GHFQDM/GHFQMC/MJ`，并建立 `plan_zone_type -> GHFQDM/GHFQMC` 映射。

### 3.5 `project` / `approval` 对应用途管制

来源：`用途管制` 分册。

空间图层包括：

| 业务 | 属性表名 | TWM 角色 |
|---|---|---|
| 建设项目用地预审与规划选址 | `XS_XMKJFW` | `project` / `approval` |
| 国家重点项目先行用地 | `XX_XMZDFW` | `project` |
| 农用地转用 | `ZZ_NYDZYFW` | `approval` |
| 土地征收 | `ZZ_TDZSFW` | `approval` |
| 临时用地 | `LSYD_XMZDFW` | `project` / `approval` |

关键字段包括 `YSDM`、`XMDM`、`DZJGH`、`AJBH`、`XZQDM`、`XMMC` 等。

当前测试包差距：

- `synthetic_projects.geojson` 和 `approval_records.csv` 没有采用用途管制字段结构。
- 应增加 `XMDM`、`DZJGH`、`AJBH`、`XZQDM`、`XMMC` 字段，并把现有 `project_id` 保留为内部对象 ID。

### 3.6 `enforcement` 对应执法督察

来源：`执法督察` 分册。

空间图层：

| 图层 | 属性表名 | TWM 角色 |
|---|---|---|
| 违法地块 | `WFDK` | `enforcement` |
| 遥感新增建设用地图斑 | `YGXZJSYDTB` | `remote_sensing_change` |
| 遥感疑似新增建设用地图斑 | `YGYSXZJSYDTB` | `enforcement` / `remote_sensing_change` |

关键字段：

| 表 | 字段 |
|---|---|
| `WFDK` | `WFXWZJ`、`WFDKXH`、`XZQDM`、`QSSJ`、`ZZSJ`、`GXZT` |
| `YGYSXZJSYDTB` | `YGTBZJ`、`XZQDM`、`JCSDQ`、`JCSDH`、`JCMJ`、`TDZL`、`TBLX`、`ND` |

当前测试包差距：

- `enforcement_events.csv` 是工程演示表，不符合执法督察标准字段。
- 应补标准字段镜像，并把 `enforcement_id` 作为内部 ID。

### 3.7 元数据对接 `meta_VectorData`

来源：`元数据` 分册表5。

TWM 和 GIS Data Agent 数据目录应重点映射：

| 标准字段 | 可映射到 GIS Data Agent |
|---|---|
| `data_id` | asset id / stable dataset id |
| `resource_id` | data catalog resource id |
| `data_name` | asset name |
| `data_alias` | layer alias |
| `data_format` | file/driver type |
| `geometry_type` | geometry type |
| `wkid` | CRS EPSG/WKID |
| `coordinate_unit` | CRS unit |
| `product_date` / `update_date` | temporal metadata |
| `source_currency` | 数据现势性 |
| `integrity` / `score` / `quality_evaluation` | QA result |

## 4. 样例数据可利用性

### 4.1 可直接用于 TWM 标准结构替身的数据

| 样例路径/图层 | 行数 | 用途 |
|---|---:|---|
| 和平村 `JQDLTB.shp` | 662 | 基期地类图斑，字段更接近规划数据库 |
| 和平村 `TDGHDL.shp` | 902 | 土地规划地类，可用于规划一致性和方案比选 |
| 和平村 `JSYDGZQ.shp` | 4 | 建设用地管制区 |
| 和平村 `STBHHX.shp` | 1 | 生态保护红线样例 |
| 和平村 `YBD.shp` | 12 | 郁闭度大于 0.7 林地，生态约束 |
| 斑竹村 `JQDLTB.shp` | 1555 | 基期地类图斑 |
| 斑竹村 `TDGHDL.shp` | 1555 | 土地规划地类 |
| 斑竹村 `JSYDGZQ.shp` | 190 | 建设用地管制区，样本量更好 |

### 4.2 可作为辅助证据的数据

| 数据 | 用途 |
|---|---|
| 重庆 DEM 80m | 坡度、地形约束、生态敏感度 |
| CLCD 2020 重庆影像解译 | 遥感分类与 DLTB/规划地类对比 |
| OSM 道路 | 可达性、项目交通影响、空间关系 |
| 中心城区建筑轮廓 | 城镇建设强度、开发利用 |
| 历史文化街区 | 历史文化保护线/保护范围约束 |

## 5. 对当前 TWM 数据包的影响

当前 `twm_bishan_demo` 和 `twm_bishan_multi_admin_eval` 的数据包已经能验证 TWM 工程闭环，但标准对齐程度不足：

| 角色 | 工程可用性 | 标准字段对齐 |
|---|---:|---:|
| `parcel_current` | 高 | 中：缺 `TBBH/QSXZ/TBDLMJ/SJNF/MSSM` |
| `pbf` | 中 | 低：缺 `YJJBNT/YJJBNTTB` 字段镜像 |
| `eco_redline` | 中 | 低：缺 `STBHHX` 字段镜像 |
| `urban_boundary` | 中 | 低：缺 `CZKFBJ` 字段镜像 |
| `planning_zone` | 中 | 中：有业务分区，但缺标准规划字段 |
| `project/approval` | 中 | 低：缺用途管制 `XMDM/DZJGH/AJBH` 等字段 |
| `enforcement` | 中 | 低：缺执法督察 `WFDK/YGYSXZJSYDTB` 字段 |
| `metadata` | 中 | 低：未形成 `meta_VectorData` 镜像 |

## 6. 建议落地步骤

### 6.1 先建立标准契约包

新增结构化标准契约文件：

```text
data_agent/test_data/twm_standards/
  one_map_role_contracts.zh.json
  one_map_field_aliases.zh.json
  one_map_value_domains.zh.json
```

首批覆盖：

- `DLTB`
- `YJJBNT / YJJBNTTB`
- `STBHHX`
- `CZKFBJ`
- `XS_XMKJFW / ZZ_NYDZYFW / ZZ_TDZSFW`
- `WFDK / YGYSXZJSYDTB`
- `meta_VectorData`

### 6.2 再升级合成数据字段

保留现有演示字段，同时增加标准字段镜像：

- `synthetic_pbf.geojson` 增加 `YJJBNTTBBH`、`YJJBNTTBMJ`、`YJJBNTMJ`、`BHKSSJ`、`WDGD` 等。
- `synthetic_eco_redline.geojson` 增加 `XJXZQDM`、`LHLX`、`MJ` 或 `LXDM/QYMJ/SLSJ/GKCS`。
- `synthetic_urban_boundary.geojson` 增加 `GHFQDM/GHFQMC/MJ`。
- `synthetic_projects.geojson` 增加 `XMDM/DZJGH/AJBH/XMMC/XZQDM`。
- `enforcement_events.csv` 或新增 `synthetic_enforcement.geojson` 增加 `WFXWZJ/WFDKXH/YGTBZJ/JCSDQ/JCSDH/JCMJ`。

### 6.3 把样例村规划数据纳入标准回归测试

建议新增一个小型标准样例包：

```text
data_agent/test_data/twm_one_map_village_standard_sample/
```

来源优先用和平村或斑竹村：

- `JQDLTB` -> `parcel_current`
- `TDGHDL` -> `planning_zone` / `planned_land_use`
- `JSYDGZQ` -> `use_control_zone`
- `STBHHX` -> `eco_redline`
- `YBD/EJYSLD/LSWH/DZDYXFW` -> `sensitive_area`

该包的目标不是替代璧山多行政包，而是专门验证“真实标准结构字段能否被 TWM 自动识别、绑定和质检”。

### 6.4 接入标准平台

应将上述契约导入 GIS Data Agent 标准平台，派生：

| 派生类型 | 用途 |
|---|---|
| `to_semantic_hint` | 字段别名、中文名、语义映射 |
| `to_value_semantics` | `DLBM`、`GHFQDM`、`GZQLXDM`、违法类型等值域 |
| `to_qc_rule` | 必填、长度、类型、面积范围、日期格式 |
| `to_data_model` | TWM role contract |
| `to_spatial_policy_rule` | PBF/生态红线/用途管制/执法规则候选 |

## 7. 当前判断

材料包显著提升了 TWM 数据基础的可信度来源。现在应把“标准对齐”作为下一轮数据基础补强的主线：

1. 当前测试包继续用于 TWM 工程闭环。
2. 样例村规划数据用于标准结构回归测试。
3. 标准分册抽取出的字段契约进入标准平台。
4. TWM 的 `layer_binding`、`state_builder` 和 QA 必须优先支持这些标准字段，再兼容当前合成字段。

## 8. 2026-06-16 标准契约落地结果

本轮已将上述建议中的“标准契约对齐”落到可执行资产和测试数据中。

### 8.1 新增机器可读标准契约

已新增：

```text
data_agent/test_data/twm_standards/
  one_map_role_contracts.zh.json
  one_map_field_aliases.zh.json
  one_map_value_domains.zh.json
```

并在每个 TWM 数据包内复制一份：

```text
data_agent/test_data/twm_bishan_demo/standards/
data_agent/test_data/twm_bishan_multi_admin_eval/standards/
```

首批角色覆盖：

| TWM 角色 | 标准契约表 |
|---|---|
| `parcel_current` | `DLTB` |
| `pbf` | `YJJBNTTB` / `YJJBNT` |
| `eco_redline` | `STBHHX` |
| `urban_boundary` | `CZKFBJ` |
| `planning_zone` | 规划分区 / `CZKFBJ` 兼容契约 |
| `project` | `XS_XMKJFW` |
| `approval` | `ZZ_NYDZYFW` / `ZZ_TDZSFW` |
| `enforcement` | `WFDK` / `YGYSXZJSYDTB` |
| `metadata_vector` | `meta_VectorData` |

### 8.2 测试包已增加标准字段镜像

两个包均已补齐核心标准字段镜像：

| 数据 | 已补字段示例 |
|---|---|
| `parcel_current.geojson` | `TBBH/QSXZ/TBDLMJ/SJNF/MSSM/GXSJ` |
| `synthetic_pbf.geojson` | `YJJBNTTBBH/YJJBNTTBMJ/YJJBNTMJ/BHKSSJ/BHJSSJ/WDGD/XZQDM/XZQMC` |
| `synthetic_eco_redline.geojson` | `XJXZQDM/XJXZQMC/LHLX/MJ/LXDM/MC/QYMJ/SLSJ/GKCS` |
| `synthetic_urban_boundary.geojson` | `GHFQDM/GHFQMC/MJ/CZMC/XJXZQHDM/CZKFMJ/SLSJ` |
| `synthetic_planning_zones.geojson` | `BSM/YSDM/XZQDM/XZQMC/GHFQDM/GHFQMC/MJ` |
| `synthetic_projects.geojson` | `XMDM/DZJGH/AJBH/XMMC/SZXZQDM/SZXZQMC/YDMJ/SQRQ/GXRQ` |
| `tables/approval_records.csv` | `YSDM/DKBH/DKMC/DKMJ/DZJGH/AJBH/XZQDM/XZQMC` |
| `tables/enforcement_events.csv` | `BSM/YSDM/WFXWZJ/WFDKXH/YGTBZJ/JCSDQ/JCSDH/JCMJ/TDZL/TBLX/ND/QSSJ/ZZSJ/GXZT` |
| `tables/metadata_vector.csv` | `data_id/resource_id/data_name/data_alias/data_format/geometry_type/wkid/coordinate_unit/source_currency/integrity/score/quality_evaluation` |

原工程字段仍然保留，例如 `project_id`、`control_id`、`redline_id`、`plan_zone_id`，用于关系表和演示逻辑。

### 8.3 QA 已加入标准契约检查

`scripts/qa_twm_demo_data.py` 已新增 `standard_contracts` 检查：

- 必填字段存在性；
- 必填字段空值；
- 数值字段非负/正数；
- 日期和年份格式；
- `metadata_vector` 元数据契约。

当前结果：

| 数据包 | QA gate | 标准契约覆盖 |
|---|---|---|
| `twm_bishan_demo` | pass | 9 个角色全部满额 |
| `twm_bishan_multi_admin_eval` | pass | 9 个角色全部满额 |

剩余 warning 仍为源 `parcel_current` 属性面积与几何面积不一致：

- 默认包：59 个图斑超过 10% 面积差异；
- 多行政包：121 个图斑超过 10% 面积差异。

该 warning 来自源图斑属性面积，不阻断 TWM 工程验证；规则生成仍使用 `qa_use_for_rules=true` 的要素。

### 8.4 标准平台导入与派生验证

本轮已将 JSON 契约导入 GIS Data Agent 标准全生命周期平台，并触发派生。

导入版本：

```text
doc_code: NR_ONE_MAP_TWM_CORE_2026
version_label: 2026-06-16-draft
version_id: 4a979e97-9d4c-43da-bfc0-c14a700a5321
status: released
```

平台写入结果：

| 对象 | 数量 |
|---|---:|
| 角色条款 `std_clause` | 9 |
| 数据元 `std_data_element` | 174 |
| 值域 `std_value_domain` | 29 |
| 值域项 `std_value_domain_item` | 53 |

派生结果：

| 派生物 | 数量 |
|---|---:|
| `agent_semantic_hints` | 174 |
| value semantics hints | 29 |
| `agent_quality_rules` | 135 |
| `agent_defect_code_bindings` | 135 |
| `std_data_model_snapshot` | 1 |

数据模型快照为 9 个实体、174 个属性、122 个约束。

### 8.5 2026-06-16 追加完成：村规划标准结构样例包

已将和平村、斑竹村村规划汇交样例转换为独立 TWM 标准结构回归包：

```text
data_agent/test_data/twm_one_map_village_standard_sample/
```

生成脚本：

```text
scripts/generate_twm_village_standard_sample.py
```

当前规模：

| 角色/图层 | 行数 | 来源/说明 |
|---|---:|---|
| `parcel_current` | 2,217 | 两村 `JQDLTB` |
| `synthetic_planning_zones` | 2,457 | 两村 `TDGHDL` |
| `synthetic_urban_boundary` | 194 | 两村 `JSYDGZQ` |
| `synthetic_eco_redline` | 1 | 和平村 `STBHHX` |
| `sensitive_areas` | 20 | `YBD/EJYSLD/LSWH/STHFQ` |
| `synthetic_pbf` | 274 | 由现状耕地图斑派生的契约测试替身 |
| `synthetic_projects` | 36 | 由规划差异派生的项目替身 |

QA 结果为 `pass`，无 blocker。9 个 TWM 标准角色的必填字段均满额覆盖：

| 角色 | 覆盖 |
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

该包的用途是验证真实汇交结构字段能否进入 TWM 角色绑定、QA、状态构建、规则评估和证据链。它不是权威生产数据：源样例层标记为 `source_sample=true`，缺失权威角色的补齐数据标记为 `synthetic=true`、`not_for_production=true`。

### 8.6 当前仍需继续的标准化工作

1. 当前标准字段镜像是“工程测试口径”，不是政府权威数据落标结果；真实权威数据接入后应按同一契约复核字段、值域、面积、时态和元数据。
2. 平台派生的 QC rule 已可落表，但 TWM 执行器若要直接消费，建议让 `to_qc_rule` 的 `config` 显式携带 `bound_table/bound_column`。
3. 后续应让 TWM 运行态优先读取标准平台 released 版本派生物，而不是直接依赖测试包内 JSON。
4. 值域校验需要继续增强，尤其是 `DLBM` 对 `GB/T 21010-2017` 全量分类和值域层级的严格校验。
