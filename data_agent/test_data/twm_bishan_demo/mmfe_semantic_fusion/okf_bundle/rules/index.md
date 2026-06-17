# Rules

* [空间数据质量门槛](twm-dq-001.md) - invalid geometries must be zero and rule input features must pass qa_use_for_rules
* [生态保护红线触碰审查](twm-eco-001.md) - flag if project_eco_rel.overlap_area_m2 > 1
* [多模态证据完整性审查](twm-evd-001.md) - each project should have text evidence and at least one remote sensing tile relation
* [永久基本农田占用审查](twm-farm-001.md) - flag if project_pbf_rel.overlap_area_m2 > 1
* [规则命中项目审批一致性审查](twm-gov-001.md) - high or critical rule hits require in_review, returned, supplement_required, or conditional approval
* [用途管制分区一致性审查](twm-plan-001.md) - compare project_type with dominant plan_zone_type
* [城镇开发边界内外审查](twm-urban-001.md) - flag construction projects outside urban boundary for review
