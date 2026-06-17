---
type: "MMFE Layer"
title: "合成城镇开发边界"
description: "由建设用地图斑聚合、缓冲、简化得到的城镇开发边界演示层。"
resource: "synthetic_urban_boundary.geojson"
tags: ["layer", "urban_boundary", "control_boundary"]
timestamp: "2026-06-17T08:28:31.856176+00:00"
role: "synthetic_urban_boundary"
standard_role: "urban_boundary"
object_type: "control_boundary"
synthetic: true
not_for_production: true
---

# Role Binding

| Property | Value |
| --- | --- |
| Physical role | `synthetic_urban_boundary` |
| Standard role | `urban_boundary` |
| Business role | 城镇开发边界约束 |
| Object type | `control_boundary` |
| Source path | `synthetic_urban_boundary.geojson` |
| CRS | `EPSG:4326` |
| Field count | 25 |
| Quality score | 85.0 |

# TWM Binding

| Semantic key | Source field |
| --- | --- |
| `object_id` | `BSM` |
| `zone_code` | `GHFQDM` |
| `zone_name` | `GHFQMC` |
| `area_m2` | `MJ` |
| `admin_code` | `XZQDM` |
| `admin_name` | `XZQMC` |

# Required Fields

| Field | Alias | Requirement | Semantic key |
| --- | --- | --- | --- |
| [BSM](/fields/synthetic_urban_boundary/bsm.md) | 标识码 | `required` | `object_id` |
| [YSDM](/fields/synthetic_urban_boundary/ysdm.md) | 要素代码 | `required` | `` |
| [XZQDM](/fields/synthetic_urban_boundary/xzqdm.md) | 行政区代码 | `required` | `admin_code` |
| [XZQMC](/fields/synthetic_urban_boundary/xzqmc.md) | 行政区名称 | `required` | `admin_name` |
| [GHFQDM](/fields/synthetic_urban_boundary/ghfqdm.md) | 规划分区代码 | `required` | `zone_code` |
| [GHFQMC](/fields/synthetic_urban_boundary/ghfqmc.md) | 规划分区名称 | `required` | `zone_name` |
| [MJ](/fields/synthetic_urban_boundary/mj.md) | 面积 | `required` | `area_m2` |
| [CZMC](/fields/synthetic_urban_boundary/czmc.md) | 城镇名称 | `required` | `` |
| [XJXZQHDM](/fields/synthetic_urban_boundary/xjxzqhdm.md) | 县级行政区划代码 | `required` | `` |
| [CZKFMJ](/fields/synthetic_urban_boundary/czkfmj.md) | 城镇开发面积 | `required` | `` |
| [SLSJ](/fields/synthetic_urban_boundary/slsj.md) | 收录时间 | `required` | `` |

# Recommended Fields

_None._

# Semantically Bound Fields

| Field | Alias | Requirement | Semantic key |
| --- | --- | --- | --- |
| [BSM](/fields/synthetic_urban_boundary/bsm.md) | 标识码 | `required` | `object_id` |
| [XZQDM](/fields/synthetic_urban_boundary/xzqdm.md) | 行政区代码 | `required` | `admin_code` |
| [XZQMC](/fields/synthetic_urban_boundary/xzqmc.md) | 行政区名称 | `required` | `admin_name` |
| [GHFQDM](/fields/synthetic_urban_boundary/ghfqdm.md) | 规划分区代码 | `required` | `zone_code` |
| [GHFQMC](/fields/synthetic_urban_boundary/ghfqmc.md) | 规划分区名称 | `required` | `zone_name` |
| [MJ](/fields/synthetic_urban_boundary/mj.md) | 面积 | `required` | `area_m2` |
