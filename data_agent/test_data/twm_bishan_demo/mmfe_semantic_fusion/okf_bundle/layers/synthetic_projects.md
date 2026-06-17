---
type: "MMFE Layer"
title: "合成建设项目范围"
description: "按多类业务场景合成的拟建/调整项目范围，用于触线风险和审批一致性演示。"
resource: "synthetic_projects.geojson"
tags: ["layer", "project", "project"]
timestamp: "2026-06-17T08:28:31.856176+00:00"
role: "synthetic_projects"
standard_role: "project"
object_type: "project"
synthetic: true
not_for_production: true
---

# Role Binding

| Property | Value |
| --- | --- |
| Physical role | `synthetic_projects` |
| Standard role | `project` |
| Business role | 项目约束校验主体 |
| Object type | `project` |
| Source path | `synthetic_projects.geojson` |
| CRS | `EPSG:4326` |
| Field count | 39 |
| Quality score | 85.0 |

# TWM Binding

| Semantic key | Source field |
| --- | --- |
| `object_id` | `XMDM` |
| `case_id` | `AJBH` |
| `project_name` | `XMMC` |
| `area_m2` | `YDMJ` |
| `admin_code` | `SZXZQDM` |
| `admin_name` | `SZXZQMC` |

# Required Fields

| Field | Alias | Requirement | Semantic key |
| --- | --- | --- | --- |
| [YSDM](/fields/synthetic_projects/ysdm.md) | 要素代码 | `required` | `` |
| [XMDM](/fields/synthetic_projects/xmdm.md) | 项目代码 | `required` | `object_id` |
| [DZJGH](/fields/synthetic_projects/dzjgh.md) | 电子监管号 | `required` | `` |
| [AJBH](/fields/synthetic_projects/ajbh.md) | 案卷编号 | `required` | `case_id` |
| [XMMC](/fields/synthetic_projects/xmmc.md) | 项目名称 | `required` | `project_name` |
| [SZXZQDM](/fields/synthetic_projects/szxzqdm.md) | 所在行政区代码 | `required` | `admin_code` |
| [SZXZQMC](/fields/synthetic_projects/szxzqmc.md) | 所在行政区名称 | `required` | `admin_name` |
| [YDMJ](/fields/synthetic_projects/ydmj.md) | 用地面积 | `required` | `area_m2` |
| [project_name](/fields/synthetic_projects/project_name.md) | 项目名称 | `required` | `project_name` |

# Recommended Fields

| Field | Alias | Requirement | Semantic key |
| --- | --- | --- | --- |
| [SQDW](/fields/synthetic_projects/sqdw.md) | 申请单位 | `recommended` | `` |
| [ZYNYDMJ](/fields/synthetic_projects/zynydmj.md) | 占用农用地面积 | `recommended` | `` |
| [ZYGDMJ](/fields/synthetic_projects/zygdmj.md) | 占用耕地面积 | `recommended` | `` |
| [SJSTHXMJ](/fields/synthetic_projects/sjsthxmj.md) | 涉及生态红线面积 | `recommended` | `` |
| [ZYJSYDMJ](/fields/synthetic_projects/zyjsydmj.md) | 占用建设用地面积 | `recommended` | `` |
| [ZYWLDMJ](/fields/synthetic_projects/zywldmj.md) | 占用未利用地面积 | `recommended` | `` |
| [SQRQ](/fields/synthetic_projects/sqrq.md) | 申请日期 | `recommended` | `` |
| [GXRQ](/fields/synthetic_projects/gxrq.md) | 更新日期 | `recommended` | `` |
| [XMPZLX](/fields/synthetic_projects/xmpzlx.md) | 项目批准类型 | `recommended` | `` |
| [HYFLBM](/fields/synthetic_projects/hyflbm.md) | 行业分类编码 | `recommended` | `` |
| [HYFLMC](/fields/synthetic_projects/hyflmc.md) | 行业分类名称 | `recommended` | `` |
| [TDYTDM](/fields/synthetic_projects/tdytdm.md) | 土地用途代码 | `recommended` | `` |
| [TDYTMC](/fields/synthetic_projects/tdytmc.md) | 土地用途名称 | `recommended` | `` |

# Semantically Bound Fields

| Field | Alias | Requirement | Semantic key |
| --- | --- | --- | --- |
| [XMDM](/fields/synthetic_projects/xmdm.md) | 项目代码 | `required` | `object_id` |
| [AJBH](/fields/synthetic_projects/ajbh.md) | 案卷编号 | `required` | `case_id` |
| [XMMC](/fields/synthetic_projects/xmmc.md) | 项目名称 | `required` | `project_name` |
| [SZXZQDM](/fields/synthetic_projects/szxzqdm.md) | 所在行政区代码 | `required` | `admin_code` |
| [SZXZQMC](/fields/synthetic_projects/szxzqmc.md) | 所在行政区名称 | `required` | `admin_name` |
| [YDMJ](/fields/synthetic_projects/ydmj.md) | 用地面积 | `required` | `area_m2` |
| [project_name](/fields/synthetic_projects/project_name.md) | 项目名称 | `required` | `project_name` |
