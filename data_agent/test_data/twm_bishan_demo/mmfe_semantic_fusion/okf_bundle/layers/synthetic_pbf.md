---
type: "MMFE Layer"
title: "合成永久基本农田"
description: "基于低坡度、较大面积耕地图斑合成的永久基本农田演示层。"
resource: "synthetic_pbf.geojson"
tags: ["layer", "pbf", "control_boundary"]
timestamp: "2026-06-17T08:28:31.856176+00:00"
role: "synthetic_pbf"
standard_role: "pbf"
object_type: "control_boundary"
synthetic: true
not_for_production: true
---

# Role Binding

| Property | Value |
| --- | --- |
| Physical role | `synthetic_pbf` |
| Standard role | `pbf` |
| Business role | 耕地保护硬约束 |
| Object type | `control_boundary` |
| Source path | `synthetic_pbf.geojson` |
| CRS | `EPSG:4326` |
| Field count | 48 |
| Quality score | 85.0 |

# TWM Binding

| Semantic key | Source field |
| --- | --- |
| `object_id` | `YJJBNTTBBH` |
| `source_parcel_id` | `TBBH` |
| `land_use_code` | `DLBM` |
| `area_m2` | `YJJBNTMJ` |
| `admin_code` | `XZQDM` |
| `admin_name` | `XZQMC` |

# Required Fields

| Field | Alias | Requirement | Semantic key |
| --- | --- | --- | --- |
| [BSM](/fields/synthetic_pbf/bsm.md) | 标识码 | `required` | `` |
| [YSDM](/fields/synthetic_pbf/ysdm.md) | 要素代码 | `required` | `` |
| [XZQDM](/fields/synthetic_pbf/xzqdm.md) | 行政区代码 | `required` | `admin_code` |
| [XZQMC](/fields/synthetic_pbf/xzqmc.md) | 行政区名称 | `required` | `admin_name` |
| [YJJBNTTBBH](/fields/synthetic_pbf/yjjbnttbbh.md) | 永久基本农田图斑编号 | `required` | `object_id` |
| [TBBH](/fields/synthetic_pbf/tbbh.md) | 图斑编号 | `required` | `source_parcel_id` |
| [DLBM](/fields/synthetic_pbf/dlbm.md) | 地类编码 | `required` | `land_use_code` |
| [DLMC](/fields/synthetic_pbf/dlmc.md) | 地类名称 | `required` | `` |
| [QSXZ](/fields/synthetic_pbf/qsxz.md) | 权属性质 | `required` | `` |
| [QSDWDM](/fields/synthetic_pbf/qsdwdm.md) | 权属单位代码 | `required` | `` |
| [QSDWMC](/fields/synthetic_pbf/qsdwmc.md) | 权属单位名称 | `required` | `` |
| [ZLDWDM](/fields/synthetic_pbf/zldwdm.md) | 坐落单位代码 | `required` | `` |
| [ZLDWMC](/fields/synthetic_pbf/zldwmc.md) | 坐落单位名称 | `required` | `` |
| [YJJBNTTBMJ](/fields/synthetic_pbf/yjjbnttbmj.md) | 永久基本农田图斑面积 | `required` | `` |
| [YJJBNTMJ](/fields/synthetic_pbf/yjjbntmj.md) | 永久基本农田面积 | `required` | `area_m2` |
| [SJNF](/fields/synthetic_pbf/sjnf.md) | 数据年份 | `required` | `` |
| [BHKSSJ](/fields/synthetic_pbf/bhkssj.md) | 保护开始时间 | `required` | `` |
| [BHJSSJ](/fields/synthetic_pbf/bhjssj.md) | 保护结束时间 | `required` | `` |
| [WDGD](/fields/synthetic_pbf/wdgd.md) | 稳定利用耕地标识 | `required` | `` |

# Recommended Fields

| Field | Alias | Requirement | Semantic key |
| --- | --- | --- | --- |
| [GDPDJB](/fields/synthetic_pbf/gdpdjb.md) | 耕地坡度级别 | `recommended` | `` |
| [KCDLBM](/fields/synthetic_pbf/kcdlbm.md) | 扣除地类编码 | `recommended` | `` |
| [KCXS](/fields/synthetic_pbf/kcxs.md) | 扣除系数 | `recommended` | `` |
| [KCMJ](/fields/synthetic_pbf/kcmj.md) | 扣除面积 | `recommended` | `` |
| [GDLX](/fields/synthetic_pbf/gdlx.md) | 耕地类型 | `recommended` | `` |
| [TBXHDM](/fields/synthetic_pbf/tbxhdm.md) | 图斑细化代码 | `recommended` | `` |
| [TBXHMC](/fields/synthetic_pbf/tbxhmc.md) | 图斑细化名称 | `recommended` | `` |
| [GDZZSXDM](/fields/synthetic_pbf/gdzzsxdm.md) | 耕地种植属性代码 | `recommended` | `` |
| [GDZZSXMC](/fields/synthetic_pbf/gdzzsxmc.md) | 耕地种植属性名称 | `recommended` | `` |
| [CFZR](/fields/synthetic_pbf/cfzr.md) | 承包方责任人 | `recommended` | `` |
| [ZRRMC](/fields/synthetic_pbf/zrrmc.md) | 责任人名称 | `recommended` | `` |
| [SJBH](/fields/synthetic_pbf/sjbh.md) | 数据编号 | `recommended` | `` |
| [SJMC](/fields/synthetic_pbf/sjmc.md) | 数据名称 | `recommended` | `` |
| [BZ](/fields/synthetic_pbf/bz.md) | 备注 | `recommended` | `` |

# Semantically Bound Fields

| Field | Alias | Requirement | Semantic key |
| --- | --- | --- | --- |
| [XZQDM](/fields/synthetic_pbf/xzqdm.md) | 行政区代码 | `required` | `admin_code` |
| [XZQMC](/fields/synthetic_pbf/xzqmc.md) | 行政区名称 | `required` | `admin_name` |
| [YJJBNTTBBH](/fields/synthetic_pbf/yjjbnttbbh.md) | 永久基本农田图斑编号 | `required` | `object_id` |
| [TBBH](/fields/synthetic_pbf/tbbh.md) | 图斑编号 | `required` | `source_parcel_id` |
| [DLBM](/fields/synthetic_pbf/dlbm.md) | 地类编码 | `required` | `land_use_code` |
| [YJJBNTMJ](/fields/synthetic_pbf/yjjbntmj.md) | 永久基本农田面积 | `required` | `area_m2` |
