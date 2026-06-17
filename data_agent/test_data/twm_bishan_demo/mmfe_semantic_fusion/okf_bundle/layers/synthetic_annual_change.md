---
type: "MMFE Layer"
title: "合成年度变化图斑"
description: "从 WorldModel v2.1 优化结果的 ORIG_DLBM 到 OPT_DLBM 派生的变化图斑。"
resource: "synthetic_annual_change.geojson"
tags: ["layer", "parcel_current", "parcel"]
timestamp: "2026-06-17T08:28:31.856176+00:00"
role: "synthetic_annual_change"
standard_role: "parcel_current"
object_type: "parcel"
synthetic: true
not_for_production: true
---

# Role Binding

| Property | Value |
| --- | --- |
| Physical role | `synthetic_annual_change` |
| Standard role | `parcel_current` |
| Business role | 状态变化与时序证据 |
| Object type | `parcel` |
| Source path | `synthetic_annual_change.geojson` |
| CRS | `EPSG:4326` |
| Field count | 21 |
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
| [BSM](/fields/synthetic_annual_change/bsm.md) | 标识码 | `required` | `object_id` |

# Recommended Fields

_None._

# Semantically Bound Fields

| Field | Alias | Requirement | Semantic key |
| --- | --- | --- | --- |
| [BSM](/fields/synthetic_annual_change/bsm.md) | 标识码 | `required` | `object_id` |
