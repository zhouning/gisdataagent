---
type: "MMFE Layer"
title: "现状地类图斑"
description: "从璧山 DLTB 坡度增强数据抽样得到的现状地类图斑。"
resource: "parcel_current.geojson"
tags: ["layer", "parcel_current", "parcel"]
timestamp: "2026-06-17T08:28:31.856176+00:00"
role: "parcel_current"
standard_role: "parcel_current"
object_type: "parcel"
synthetic: false
not_for_production: true
---

# Role Binding

| Property | Value |
| --- | --- |
| Physical role | `parcel_current` |
| Standard role | `parcel_current` |
| Business role | 状态对象底板 |
| Object type | `parcel` |
| Source path | `parcel_current.geojson` |
| CRS | `EPSG:4326` |
| Field count | 46 |
| Quality score | 85.0 |

# TWM Binding

| Semantic key | Source field |
| --- | --- |
| `object_id` | `BSM` |
| `land_use_code` | `DLBM` |
| `land_use_name` | `DLMC` |
| `area_m2` | `TBMJ` |
| `admin_code` | `QSDWDM` |
| `admin_name` | `QSDWMC` |
| `temporal_key` | `SJNF` |

# Required Fields

| Field | Alias | Requirement | Semantic key |
| --- | --- | --- | --- |
| [BSM](/fields/parcel_current/bsm.md) | 标识码 | `required` | `object_id` |
| [YSDM](/fields/parcel_current/ysdm.md) | 要素代码 | `required` | `` |
| [DLBM](/fields/parcel_current/dlbm.md) | 地类编码 | `required` | `land_use_code` |
| [DLMC](/fields/parcel_current/dlmc.md) | 地类名称 | `required` | `land_use_name` |
| [QSDWDM](/fields/parcel_current/qsdwdm.md) | 权属单位代码 | `required` | `admin_code` |
| [QSDWMC](/fields/parcel_current/qsdwmc.md) | 权属单位名称 | `required` | `admin_name` |
| [ZLDWDM](/fields/parcel_current/zldwdm.md) | 坐落单位代码 | `required` | `` |
| [ZLDWMC](/fields/parcel_current/zldwmc.md) | 坐落单位名称 | `required` | `` |
| [TBMJ](/fields/parcel_current/tbmj.md) | 图斑面积 | `required` | `area_m2` |
| [TBBH](/fields/parcel_current/tbbh.md) | 图斑编号 | `required` | `` |
| [QSXZ](/fields/parcel_current/qsxz.md) | 权属性质 | `required` | `` |
| [TBDLMJ](/fields/parcel_current/tbdlmj.md) | 图斑地类面积 | `required` | `` |
| [SJNF](/fields/parcel_current/sjnf.md) | 数据年份 | `required` | `temporal_key` |
| [MSSM](/fields/parcel_current/mssm.md) | 描述说明 | `required` | `` |

# Recommended Fields

| Field | Alias | Requirement | Semantic key |
| --- | --- | --- | --- |
| [TBYBH](/fields/parcel_current/tbybh.md) | 图斑预编号 | `recommended` | `` |
| [KCDLBM](/fields/parcel_current/kcdlbm.md) | 扣除地类编码 | `recommended` | `` |
| [KCXS](/fields/parcel_current/kcxs.md) | 扣除系数 | `recommended` | `` |
| [KCMJ](/fields/parcel_current/kcmj.md) | 扣除面积 | `recommended` | `` |
| [GDLX](/fields/parcel_current/gdlx.md) | 耕地类型 | `recommended` | `` |
| [GDPDJB](/fields/parcel_current/gdpdjb.md) | 耕地坡度级别 | `recommended` | `` |
| [TBXHDM](/fields/parcel_current/tbxhdm.md) | 图斑细化代码 | `recommended` | `` |
| [TBXHMC](/fields/parcel_current/tbxhmc.md) | 图斑细化名称 | `recommended` | `` |
| [ZZSXDM](/fields/parcel_current/zzsxdm.md) | 种植属性代码 | `recommended` | `` |
| [ZZSXMC](/fields/parcel_current/zzsxmc.md) | 种植属性名称 | `recommended` | `` |
| [CZCSXM](/fields/parcel_current/czcsxm.md) | 城镇村属性码 | `recommended` | `` |
| [GXSJ](/fields/parcel_current/gxsj.md) | 更新时间 | `recommended` | `` |
| [BZ](/fields/parcel_current/bz.md) | 备注 | `recommended` | `` |

# Semantically Bound Fields

| Field | Alias | Requirement | Semantic key |
| --- | --- | --- | --- |
| [BSM](/fields/parcel_current/bsm.md) | 标识码 | `required` | `object_id` |
| [DLBM](/fields/parcel_current/dlbm.md) | 地类编码 | `required` | `land_use_code` |
| [DLMC](/fields/parcel_current/dlmc.md) | 地类名称 | `required` | `land_use_name` |
| [QSDWDM](/fields/parcel_current/qsdwdm.md) | 权属单位代码 | `required` | `admin_code` |
| [QSDWMC](/fields/parcel_current/qsdwmc.md) | 权属单位名称 | `required` | `admin_name` |
| [TBMJ](/fields/parcel_current/tbmj.md) | 图斑面积 | `required` | `area_m2` |
| [SJNF](/fields/parcel_current/sjnf.md) | 数据年份 | `required` | `temporal_key` |
