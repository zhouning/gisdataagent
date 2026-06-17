---
type: "MMFE Layer"
title: "合成用途管制分区"
description: "由现状地类归并并 dissolve 得到的用途管制分区演示层。"
resource: "synthetic_planning_zones.geojson"
tags: ["layer", "planning_zone", "planning_zone"]
timestamp: "2026-06-17T08:28:31.856176+00:00"
role: "synthetic_planning_zones"
standard_role: "planning_zone"
object_type: "planning_zone"
synthetic: true
not_for_production: true
---

# Role Binding

| Property | Value |
| --- | --- |
| Physical role | `synthetic_planning_zones` |
| Standard role | `planning_zone` |
| Business role | 规划一致性约束 |
| Object type | `planning_zone` |
| Source path | `synthetic_planning_zones.geojson` |
| CRS | `EPSG:4326` |
| Field count | 21 |
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
| [BSM](/fields/synthetic_planning_zones/bsm.md) | 标识码 | `required` | `object_id` |
| [YSDM](/fields/synthetic_planning_zones/ysdm.md) | 要素代码 | `required` | `` |
| [XZQDM](/fields/synthetic_planning_zones/xzqdm.md) | 行政区代码 | `required` | `admin_code` |
| [XZQMC](/fields/synthetic_planning_zones/xzqmc.md) | 行政区名称 | `required` | `admin_name` |
| [GHFQDM](/fields/synthetic_planning_zones/ghfqdm.md) | 规划分区代码 | `required` | `zone_code` |
| [GHFQMC](/fields/synthetic_planning_zones/ghfqmc.md) | 规划分区名称 | `required` | `zone_name` |
| [MJ](/fields/synthetic_planning_zones/mj.md) | 面积 | `required` | `area_m2` |

# Recommended Fields

_None._

# Semantically Bound Fields

| Field | Alias | Requirement | Semantic key |
| --- | --- | --- | --- |
| [BSM](/fields/synthetic_planning_zones/bsm.md) | 标识码 | `required` | `object_id` |
| [XZQDM](/fields/synthetic_planning_zones/xzqdm.md) | 行政区代码 | `required` | `admin_code` |
| [XZQMC](/fields/synthetic_planning_zones/xzqmc.md) | 行政区名称 | `required` | `admin_name` |
| [GHFQDM](/fields/synthetic_planning_zones/ghfqdm.md) | 规划分区代码 | `required` | `zone_code` |
| [GHFQMC](/fields/synthetic_planning_zones/ghfqmc.md) | 规划分区名称 | `required` | `zone_name` |
| [MJ](/fields/synthetic_planning_zones/mj.md) | 面积 | `required` | `area_m2` |
