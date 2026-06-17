---
type: "MMFE Layer"
title: "合成生态保护红线"
description: "基于林地、水域、高坡度图斑并局部缓冲合成的生态保护红线演示层。"
resource: "synthetic_eco_redline.geojson"
tags: ["layer", "eco_redline", "control_boundary"]
timestamp: "2026-06-17T08:28:31.856176+00:00"
role: "synthetic_eco_redline"
standard_role: "eco_redline"
object_type: "control_boundary"
synthetic: true
not_for_production: true
---

# Role Binding

| Property | Value |
| --- | --- |
| Physical role | `synthetic_eco_redline` |
| Standard role | `eco_redline` |
| Business role | 生态保护硬约束 |
| Object type | `control_boundary` |
| Source path | `synthetic_eco_redline.geojson` |
| CRS | `EPSG:4326` |
| Field count | 35 |
| Quality score | 85.0 |

# TWM Binding

| Semantic key | Source field |
| --- | --- |
| `object_id` | `BSM` |
| `name` | `MC` |
| `area_m2` | `MJ` |
| `area_km2` | `QYMJ` |
| `admin_code` | `XJXZQDM` |
| `admin_name` | `XJXZQMC` |

# Required Fields

| Field | Alias | Requirement | Semantic key |
| --- | --- | --- | --- |
| [BSM](/fields/synthetic_eco_redline/bsm.md) | 标识码 | `required` | `object_id` |
| [YSDM](/fields/synthetic_eco_redline/ysdm.md) | 要素代码 | `required` | `` |
| [XJXZQDM](/fields/synthetic_eco_redline/xjxzqdm.md) | 县级行政区代码 | `required` | `admin_code` |
| [XJXZQMC](/fields/synthetic_eco_redline/xjxzqmc.md) | 县级行政区名称 | `required` | `admin_name` |
| [LHLX](/fields/synthetic_eco_redline/lhlx.md) | 陆海类型 | `required` | `` |
| [MJ](/fields/synthetic_eco_redline/mj.md) | 面积 | `required` | `area_m2` |
| [XJXZQHDM](/fields/synthetic_eco_redline/xjxzqhdm.md) | 县级行政区划代码 | `required` | `` |
| [LXDM](/fields/synthetic_eco_redline/lxdm.md) | 类型代码 | `required` | `` |
| [MC](/fields/synthetic_eco_redline/mc.md) | 名称 | `required` | `name` |
| [QYMJ](/fields/synthetic_eco_redline/qymj.md) | 区域面积 | `required` | `area_km2` |
| [SLSJ](/fields/synthetic_eco_redline/slsj.md) | 收录时间 | `required` | `` |
| [GKCS](/fields/synthetic_eco_redline/gkcs.md) | 管控措施 | `required` | `` |

# Recommended Fields

| Field | Alias | Requirement | Semantic key |
| --- | --- | --- | --- |
| [SLDM](/fields/synthetic_eco_redline/sldm.md) | 分类代码 | `recommended` | `` |
| [RKSL](/fields/synthetic_eco_redline/rksl.md) | 人口数量 | `recommended` | `` |
| [STGNYBHMB](/fields/synthetic_eco_redline/stgnybhmb.md) | 生态功能预保护目标 | `recommended` | `` |
| [STXTYZBLX](/fields/synthetic_eco_redline/stxtyzblx.md) | 生态系统因子斑类型 | `recommended` | `` |
| [RWHDLX](/fields/synthetic_eco_redline/rwhdlx.md) | 人为活动类型 | `recommended` | `` |
| [STHJWT](/fields/synthetic_eco_redline/sthjwt.md) | 生态环境问题 | `recommended` | `` |
| [BZ](/fields/synthetic_eco_redline/bz.md) | 备注 | `recommended` | `` |

# Semantically Bound Fields

| Field | Alias | Requirement | Semantic key |
| --- | --- | --- | --- |
| [BSM](/fields/synthetic_eco_redline/bsm.md) | 标识码 | `required` | `object_id` |
| [XJXZQDM](/fields/synthetic_eco_redline/xjxzqdm.md) | 县级行政区代码 | `required` | `admin_code` |
| [XJXZQMC](/fields/synthetic_eco_redline/xjxzqmc.md) | 县级行政区名称 | `required` | `admin_name` |
| [MJ](/fields/synthetic_eco_redline/mj.md) | 面积 | `required` | `area_m2` |
| [MC](/fields/synthetic_eco_redline/mc.md) | 名称 | `required` | `name` |
| [QYMJ](/fields/synthetic_eco_redline/qymj.md) | 区域面积 | `required` | `area_km2` |
