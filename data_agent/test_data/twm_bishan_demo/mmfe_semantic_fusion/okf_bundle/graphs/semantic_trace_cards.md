---
type: "MMFE Semantic Trace Cards"
title: "MMFE semantic trace cards"
description: "Compact semantic graph trace cards for key MMFE nodes."
tags: ["graph", "trace", "mmfe", "semantic-fusion"]
timestamp: "2026-06-17T08:28:31.856176+00:00"
trace_card_count: 14
---

# Trace Summary

| Property | Value |
| --- | ---: |
| Trace cards | 14 |
| Standard-source paths | 95 |
| Source graph nodes | 1424 |
| Source graph edges | 3547 |

# Focus Types

| Value | Count |
| --- | ---: |
| `field` | 6 |
| `optimization_objective` | 2 |
| `rule` | 2 |
| `standard_source` | 2 |
| `value_domain` | 2 |

# Trace Cards

| Node | Type | Standard Paths | Value Domains | Rules | Objectives | Summary |
| --- | --- | ---: | ---: | ---: | ---: | --- |
| `field:parcel_current.DLBM` | `field` | 8 | 1 | 0 | 0 | 地类编码 是 MMFE 语义图中的 field 节点。直接出边 2 条，直接入边 1 条。可追溯到 1 条值域路径。可追溯到 8 条标准来源路径。 |
| `field:parcel_current.QSXZ` | `field` | 8 | 1 | 0 | 0 | 权属性质 是 MMFE 语义图中的 field 节点。直接出边 2 条，直接入边 1 条。可追溯到 1 条值域路径。可追溯到 8 条标准来源路径。 |
| `field:synthetic_pbf.WDGD` | `field` | 8 | 1 | 0 | 0 | 稳定利用耕地标识 是 MMFE 语义图中的 field 节点。直接出边 2 条，直接入边 1 条。可追溯到 1 条值域路径。可追溯到 8 条标准来源路径。 |
| `field:synthetic_projects.YDMJ` | `field` | 8 | 0 | 0 | 0 | 用地面积 是 MMFE 语义图中的 field 节点。直接出边 1 条，直接入边 1 条。可追溯到 8 条标准来源路径。 |
| `field:synthetic_eco_redline.LXDM` | `field` | 8 | 1 | 0 | 0 | 类型代码 是 MMFE 语义图中的 field 节点。直接出边 2 条，直接入边 1 条。可追溯到 1 条值域路径。可追溯到 8 条标准来源路径。 |
| `field:synthetic_planning_zones.GHFQDM` | `field` | 8 | 1 | 0 | 0 | 规划分区代码 是 MMFE 语义图中的 field 节点。直接出边 2 条，直接入边 1 条。可追溯到 1 条值域路径。可追溯到 8 条标准来源路径。 |
| `value_domain:gb_t_21010_2017_land_use_code` | `value_domain` | 8 | 0 | 0 | 0 | gb_t_21010_2017_land_use_code 是 MMFE 语义图中的 value_domain 节点。直接出边 2 条，直接入边 1 条。可追溯到 8 条标准来源路径。 |
| `value_domain:ownership_nature_code` | `value_domain` | 7 | 0 | 0 | 0 | ownership_nature_code 是 MMFE 语义图中的 value_domain 节点。直接出边 1 条，直接入边 1 条。可追溯到 7 条标准来源路径。 |
| `standard_source:gb-t-21010-2017` | `standard_source` | 0 | 0 | 0 | 0 | 土地利用现状分类 是 MMFE 语义图中的 standard_source 节点。直接出边 0 条，直接入边 3 条。 |
| `standard_source:nr-one-map-db-arch-02-survey-monitoring` | `standard_source` | 0 | 0 | 0 | 0 | 自然资源“一张图”数据库体系结构（2）统一调查监测1126 是 MMFE 语义图中的 standard_source 节点。直接出边 0 条，直接入边 2 条。 |
| `rule:TWM-FARM-001` | `rule` | 8 | 1 | 0 | 0 | 永久基本农田占用审查 是 MMFE 语义图中的 rule 节点。直接出边 4 条，直接入边 39 条。可追溯到 1 条值域路径。可追溯到 8 条标准来源路径。 |
| `rule:TWM-ECO-001` | `rule` | 8 | 1 | 0 | 0 | 生态保护红线触碰审查 是 MMFE 语义图中的 rule 节点。直接出边 4 条，直接入边 28 条。可追溯到 1 条值域路径。可追溯到 8 条标准来源路径。 |
| `objective:pbf_overlap_m2` | `optimization_objective` | 8 | 1 | 0 | 0 | 永久基本农田占用最小化 是 MMFE 语义图中的 optimization_objective 节点。直接出边 1 条，直接入边 40 条。可追溯到 1 条值域路径。可追溯到 8 条标准来源路径。 |
| `objective:eco_overlap_m2` | `optimization_objective` | 8 | 1 | 0 | 0 | 生态保护红线触碰最小化 是 MMFE 语义图中的 optimization_objective 节点。直接出边 1 条，直接入边 29 条。可追溯到 1 条值域路径。可追溯到 8 条标准来源路径。 |
