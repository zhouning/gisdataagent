---
type: "MMFE Semantic Product"
title: "sfp-twm-dc2a707aabda0c01"
description: "MMFE semantic fusion product exported as OKF."
resource: "data_agent/test_data/twm_bishan_demo/mmfe_semantic_fusion/twm_mmfe_business_view.csv"
tags: ["mmfe", "semantic-product"]
timestamp: "2026-06-17T08:28:31.856176+00:00"
product_id: "sfp-twm-dc2a707aabda0c01"
---

# Summary

This concept describes MMFE semantic fusion product `sfp-twm-dc2a707aabda0c01`.

| Item | Count |
| --- | ---: |
| Sources | 9 |
| Layers | 9 |
| Field semantic mappings | 274 |
| Value-domain audits | 6 |
| Semantic relations | 728 |
| Active standard fields | 266 |
| Rule bindings | 7 |
| Optimization objectives | 13 |
| Optimization scenarios | 7 |
| Semantic graph nodes | 1424 |
| Semantic graph edges | 3547 |

# Sources

* [admin_units](/sources/admin_units.md)
* [parcel_current](/sources/parcel_current.md)
* [synthetic_annual_change](/sources/synthetic_annual_change.md)
* [synthetic_eco_redline](/sources/synthetic_eco_redline.md)
* [synthetic_pbf](/sources/synthetic_pbf.md)
* [synthetic_planning_zones](/sources/synthetic_planning_zones.md)
* [synthetic_projects](/sources/synthetic_projects.md)
* [synthetic_remote_sensing_tiles](/sources/synthetic_remote_sensing_tiles.md)
* [synthetic_urban_boundary](/sources/synthetic_urban_boundary.md)

# Layers

* [乡镇行政区边界](/layers/admin_units.md)
* [现状地类图斑](/layers/parcel_current.md)
* [合成年度变化图斑](/layers/synthetic_annual_change.md)
* [合成生态保护红线](/layers/synthetic_eco_redline.md)
* [合成永久基本农田](/layers/synthetic_pbf.md)
* [合成用途管制分区](/layers/synthetic_planning_zones.md)
* [合成建设项目范围](/layers/synthetic_projects.md)
* [合成遥感影像瓦片索引](/layers/synthetic_remote_sensing_tiles.md)
* [合成城镇开发边界](/layers/synthetic_urban_boundary.md)

# Rules

* [永久基本农田占用审查](/rules/twm-farm-001.md)
* [生态保护红线触碰审查](/rules/twm-eco-001.md)
* [用途管制分区一致性审查](/rules/twm-plan-001.md)
* [城镇开发边界内外审查](/rules/twm-urban-001.md)
* [空间数据质量门槛](/rules/twm-dq-001.md)
* [规则命中项目审批一致性审查](/rules/twm-gov-001.md)
* [多模态证据完整性审查](/rules/twm-evd-001.md)

# Optimization Objectives

* [永久基本农田占用最小化](/objectives/pbf_overlap_m2.md)
* [生态保护红线触碰最小化](/objectives/eco_overlap_m2.md)
* [用途管制冲突最小化](/objectives/planning_conflict_m2.md)
* [耕地损失最小化](/objectives/farmland_loss_m2.md)
* [耕地补充最大化](/objectives/farmland_gain_m2.md)
* [建设承载能力最大化](/objectives/development_area_m2.md)
* [空间紧凑性最大化](/objectives/compactness_score.md)
* [调整成本最小化](/objectives/adjustment_cost_proxy.md)
* [行政区负担均衡](/objectives/admin_fairness_cv.md)
* [方案稳健性最大化](/objectives/robustness_score.md)
* [人工复核负荷最小化](/objectives/review_load_count.md)
* [坡度适宜性改善最大化](/objectives/slope_improvement_pct.md)
* [空间连片度提升最大化](/objectives/contiguity_gain.md)
