"""Reviewed Liveability v2 table-local semantic expansion contracts."""

# Ruff line-length checks are disabled for intact multilingual benchmark prompts.
# ruff: noqa: E501

from __future__ import annotations

from typing import Any

SUMMARY_TERMS = {
    "zh": ["统计", "汇总"],
    "en": ["count", "summarize"],
    "ar": ["احسب", "لخص"],
}


def _metric(
    aggregate: str,
    field: str,
    alias: str | None = None,
) -> dict[str, str]:
    return {
        "aggregate": aggregate,
        "field": field,
        "alias": alias or field,
    }


def _intent(
    *,
    intent_id: str,
    table: str,
    entity: str,
    labels: dict[str, str],
    aliases: list[str],
    dimensions: list[str],
    metrics: list[dict[str, str]],
    questions: dict[str, str],
    asset_terms: dict[str, list[str]],
) -> dict[str, Any]:
    return {
        "id": intent_id,
        "contract_id": f"LIVEABILITY_{intent_id.upper()}_V2",
        "table": table,
        "entity": entity,
        "labels": labels,
        "aliases": aliases,
        "dimensions": dimensions,
        "metrics": metrics,
        "questions": questions,
        "match": {
            "required_term_groups": {
                language: [SUMMARY_TERMS[language], asset_terms[language]]
                for language in ("zh", "en", "ar")
            }
        },
    }


EXPANSION_INTENTS: tuple[dict[str, Any], ...] = (
    _intent(
        intent_id="comparison_metric_group_summary",
        table="public.dim_cmp_metric_groups",
        entity="dmt_liveability.comparison_metric_group",
        labels={
            "zh": "对比指标组",
            "en": "comparison metric group",
            "ar": "مجموعة مؤشرات المقارنة",
        },
        aliases=["comparison metric groups", "对比指标组", "مجموعات مؤشرات المقارنة"],
        dimensions=["group_key", "group_name", "sort_order"],
        metrics=[_metric("count", "*", "group_row_count")],
        questions={
            "zh": "按组标识、组名称和排序统计对比指标组。",
            "en": "Count comparison metric groups by group key, group name, and sort order.",
            "ar": "احسب مجموعات مؤشرات المقارنة حسب مفتاح المجموعة واسمها وترتيبها.",
        },
        asset_terms={
            "zh": ["对比指标组"],
            "en": ["comparison metric groups"],
            "ar": ["مجموعات مؤشرات المقارنة"],
        },
    ),
    _intent(
        intent_id="comparison_metric_item_summary",
        table="public.dim_cmp_metric_items",
        entity="dmt_liveability.comparison_metric_item",
        labels={"zh": "对比指标项", "en": "comparison metric item", "ar": "عنصر مؤشر المقارنة"},
        aliases=["comparison metric items", "对比指标项", "عناصر مؤشرات المقارنة"],
        dimensions=["group_key", "data_source", "unit"],
        metrics=[_metric("count", "*", "item_count")],
        questions={
            "zh": "按指标组、数据来源和单位统计对比指标项数量。",
            "en": "Count comparison metric items by metric group, data source, and unit.",
            "ar": "احسب عناصر مؤشرات المقارنة حسب مجموعة المؤشر ومصدر البيانات والوحدة.",
        },
        asset_terms={
            "zh": ["对比指标项"],
            "en": ["comparison metric items"],
            "ar": ["عناصر مؤشرات المقارنة"],
        },
    ),
    _intent(
        intent_id="planning_project_summary_by_type",
        table="public.dim_projects",
        entity="dmt_project.planning_project",
        labels={"zh": "规划项目", "en": "planning project", "ar": "مشروع تخطيط"},
        aliases=["planning projects", "projects", "规划项目", "مشاريع التخطيط"],
        dimensions=["project_type"],
        metrics=[_metric("count", "*", "project_count")],
        questions={
            "zh": "按项目类型统计规划项目数量。",
            "en": "Count planning projects by project type.",
            "ar": "احسب مشاريع التخطيط حسب نوع المشروع.",
        },
        asset_terms={
            "zh": ["规划项目"],
            "en": ["planning projects"],
            "ar": ["مشاريع التخطيط"],
        },
    ),
    _intent(
        intent_id="population_version_summary",
        table="public.dim_scad_versions",
        entity="dmt_population.scad_version",
        labels={"zh": "人口数据版本", "en": "population data version", "ar": "إصدار بيانات السكان"},
        aliases=["SCAD versions", "population versions", "人口数据版本", "إصدارات بيانات السكان"],
        dimensions=["package", "version_label", "data_date"],
        metrics=[_metric("count", "*", "version_row_count")],
        questions={
            "zh": "按数据包、版本标签和数据日期统计人口数据版本。",
            "en": "Count population data versions by package, version label, and data date.",
            "ar": "احسب إصدارات بيانات السكان حسب الحزمة وتسمية الإصدار وتاريخ البيانات.",
        },
        asset_terms={
            "zh": ["人口数据版本"],
            "en": ["population data versions"],
            "ar": ["إصدارات بيانات السكان"],
        },
    ),
    _intent(
        intent_id="adeo_facility_summary",
        table="public.fact_adeo_facilities",
        entity="dmt_facility.adeo_facility_summary",
        labels={"zh": "ADEO 设施统计", "en": "ADEO facility summary", "ar": "ملخص مرافق ADEO"},
        aliases=["ADEO facilities", "ADEO 设施统计", "مرافق ADEO"],
        dimensions=["reporting_year", "facility_category", "subcategory"],
        metrics=[
            _metric("sum", "total_count"),
            _metric("sum", "aam_count"),
            _metric("sum", "adm_count"),
            _metric("sum", "wrm_count"),
        ],
        questions={
            "zh": "按报告年份、设施类别和子类别汇总 ADEO 设施总数以及 AAM、ADM、WRM 数量。",
            "en": "Summarize ADEO facilities by reporting year, category, and subcategory with total, AAM, ADM, and WRM counts.",
            "ar": "لخص مرافق ADEO حسب سنة التقرير والفئة والفئة الفرعية مع إجماليات AAM وADM وWRM.",
        },
        asset_terms={"zh": ["ADEO 设施"], "en": ["ADEO facilities"], "ar": ["مرافق ADEO"]},
    ),
    _intent(
        intent_id="action_plan_budget_statistics",
        table="public.fact_ap_budget_stats",
        entity="dmt_budget.action_plan_budget_statistics",
        labels={
            "zh": "行动计划预算统计",
            "en": "action-plan budget statistics",
            "ar": "إحصاءات ميزانية خطة العمل",
        },
        aliases=["action-plan budget statistics", "AP budget statistics", "行动计划预算统计"],
        dimensions=["municipality", "package", "score_range"],
        metrics=[
            _metric("sum", "parks_capex"),
            _metric("sum", "cycletrack_capex"),
            _metric("sum", "sidewalks_capex"),
            _metric("sum", "streetscape_capex"),
        ],
        questions={
            "zh": "按市政区域、数据包和得分区间汇总行动计划预算统计中的公园、自行车道、人行道和街景资本支出。",
            "en": "Summarize action-plan budget statistics by municipality, package, and score range for parks, cycle tracks, sidewalks, and streetscape capital expenditure.",
            "ar": "لخص إحصاءات ميزانية خطة العمل حسب البلدية والحزمة ونطاق الدرجة للنفقات الرأسمالية للحدائق ومسارات الدراجات والأرصفة ومشهد الشوارع.",
        },
        asset_terms={
            "zh": ["行动计划预算统计"],
            "en": ["action-plan budget statistics"],
            "ar": ["إحصاءات ميزانية خطة العمل"],
        },
    ),
    _intent(
        intent_id="detailed_action_plan_budget",
        table="public.fact_ap_detailed_budget",
        entity="dmt_budget.detailed_action_plan_budget",
        labels={
            "zh": "行动计划详细预算",
            "en": "detailed action-plan budget",
            "ar": "ميزانية خطة العمل التفصيلية",
        },
        aliases=["detailed action-plan budget", "AP detailed budget", "行动计划详细预算"],
        dimensions=["municipality", "package"],
        metrics=[_metric("sum", "total_capex"), _metric("sum", "total_opex")],
        questions={
            "zh": "按市政区域和数据包汇总行动计划详细预算的总资本支出和总运营支出。",
            "en": "Summarize the detailed action-plan budget by municipality and package for total capital and operating expenditure.",
            "ar": "لخص ميزانية خطة العمل التفصيلية حسب البلدية والحزمة لإجمالي النفقات الرأسمالية والتشغيلية.",
        },
        asset_terms={
            "zh": ["行动计划详细预算"],
            "en": ["detailed action-plan budget"],
            "ar": ["ميزانية خطة العمل التفصيلية"],
        },
    ),
    _intent(
        intent_id="district_budget_summary",
        table="public.fact_budget",
        entity="dmt_budget.district_budget",
        labels={"zh": "片区预算", "en": "district budget", "ar": "ميزانية المنطقة"},
        aliases=["district budgets", "片区预算", "ميزانيات المناطق"],
        dimensions=["district_id"],
        metrics=[
            _metric("sum", "capex_environment"),
            _metric("sum", "capex_social"),
            _metric("sum", "total_capex"),
            _metric("sum", "total_opex"),
        ],
        questions={
            "zh": "按片区汇总片区预算的环境资本支出、社会资本支出、总资本支出和总运营支出。",
            "en": "Summarize district budgets by district for environmental capital expenditure, social capital expenditure, total capital expenditure, and total operating expenditure.",
            "ar": "لخص ميزانيات المناطق حسب المنطقة للنفقات الرأسمالية البيئية والاجتماعية وإجمالي النفقات الرأسمالية والتشغيلية.",
        },
        asset_terms={"zh": ["片区预算"], "en": ["district budgets"], "ar": ["ميزانيات المناطق"]},
    ),
    _intent(
        intent_id="district_city_image_summary",
        table="public.fact_city_image",
        entity="dmt_liveability.district_city_image",
        labels={
            "zh": "片区城市形象指标",
            "en": "district city-image metric",
            "ar": "مؤشر صورة المدينة للمنطقة",
        },
        aliases=["district city-image metrics", "city image metrics", "片区城市形象指标"],
        dimensions=["district_id"],
        metrics=[
            _metric("avg", "cityimage_exist_pct", "average_existing_pct"),
            _metric("avg", "cityimage_ap50_pct", "average_ap50_pct"),
            _metric("avg", "cityimage_pipe_pct", "average_pipeline_pct"),
            _metric("sum", "cityimage_ap50_projects_count", "ap50_project_count"),
        ],
        questions={
            "zh": "按片区汇总片区城市形象指标的现状、AP50 和项目管线比例以及 AP50 项目数。",
            "en": "Summarize district city-image metrics by district for existing, AP50, and pipeline percentages and the AP50 project count.",
            "ar": "لخص مؤشرات صورة المدينة للمنطقة حسب المنطقة لنسب الوضع الحالي وAP50 وخط المشاريع وعدد مشاريع AP50.",
        },
        asset_terms={
            "zh": ["片区城市形象指标"],
            "en": ["district city-image metrics"],
            "ar": ["مؤشرات صورة المدينة للمنطقة"],
        },
    ),
    _intent(
        intent_id="dmt_strategy_summary",
        table="public.fact_dmt_strategy",
        entity="dmt_strategy.district_strategy",
        labels={"zh": "DMT 片区策略", "en": "DMT district strategy", "ar": "استراتيجية منطقة DMT"},
        aliases=["DMT district strategies", "DMT strategies", "DMT 片区策略"],
        dimensions=["owner_sector_lead"],
        metrics=[
            _metric("count", "*", "strategy_count"),
            _metric("count_distinct", "district_id", "district_count"),
            _metric("sum", "budget_capex"),
            _metric("sum", "budget_opex"),
            _metric("avg", "target_district_score", "average_target_district_score"),
        ],
        questions={
            "zh": "按责任部门汇总 DMT 片区策略数量、片区数、资本与运营预算及平均目标片区得分。",
            "en": "Summarize DMT district strategies by owner-sector lead with strategy count, district count, capital and operating budgets, and average target district score.",
            "ar": "لخص استراتيجيات مناطق DMT حسب القطاع المسؤول مع عدد الاستراتيجيات والمناطق والميزانيات الرأسمالية والتشغيلية ومتوسط درجة المنطقة المستهدفة.",
        },
        asset_terms={
            "zh": ["DMT 片区策略"],
            "en": ["DMT district strategies"],
            "ar": ["استراتيجيات مناطق DMT"],
        },
    ),
    _intent(
        intent_id="facility_demand_summary",
        table="public.fact_fc_demand",
        entity="dmt_facility.facility_demand",
        labels={"zh": "设施需求", "en": "facility demand", "ar": "الطلب على المرافق"},
        aliases=["facility demand", "facility demand counts", "设施需求"],
        dimensions=["facility_type"],
        metrics=[
            _metric("sum", "req_count_current_pop", "required_for_current_population"),
            _metric("sum", "req_count_ultimate_pop", "required_for_ultimate_population"),
        ],
        questions={
            "zh": "按设施类型汇总设施需求中的现状人口和远期人口所需数量。",
            "en": "Summarize facility demand by facility type for counts required by the current and ultimate populations.",
            "ar": "لخص الطلب على المرافق حسب نوع المرفق للأعداد المطلوبة للسكان الحاليين والنهائيين.",
        },
        asset_terms={"zh": ["设施需求"], "en": ["facility demand"], "ar": ["الطلب على المرافق"]},
    ),
    _intent(
        intent_id="facility_proximity_mode_score_summary",
        table="public.fact_fp_facility_scores",
        entity="dmt_liveability.facility_proximity_mode_score",
        labels={
            "zh": "设施邻近性出行方式得分",
            "en": "facility proximity mode score",
            "ar": "درجة وسيلة الوصول إلى المرفق",
        },
        aliases=[
            "facility proximity mode scores",
            "proximity mode scores",
            "设施邻近性出行方式得分",
        ],
        dimensions=["context", "facility_type", "stage"],
        metrics=[
            _metric("avg", "walking_score", "average_walking_score"),
            _metric("avg", "cycling_score", "average_cycling_score"),
            _metric("avg", "driving_score", "average_driving_score"),
        ],
        questions={
            "zh": "按场景、设施类型和阶段汇总设施邻近性出行方式的平均步行、骑行和驾车得分。",
            "en": "Summarize facility proximity mode scores by context, facility type, and stage with average walking, cycling, and driving scores.",
            "ar": "لخص درجات وسائل الوصول إلى المرافق حسب السياق ونوع المرفق والمرحلة مع متوسط درجات المشي وركوب الدراجة والقيادة.",
        },
        asset_terms={
            "zh": ["设施邻近性出行方式"],
            "en": ["facility proximity mode scores"],
            "ar": ["درجات وسائل الوصول إلى المرافق"],
        },
    ),
    _intent(
        intent_id="facility_proximity_score_summary",
        table="public.fact_fp_scores",
        entity="dmt_liveability.facility_proximity_score",
        labels={"zh": "设施邻近性得分", "en": "facility proximity score", "ar": "درجة قرب المرفق"},
        aliases=["facility proximity scores", "FP scores", "设施邻近性得分"],
        dimensions=["context", "facility_type", "mode", "stage"],
        metrics=[
            _metric("avg", "fp_score", "average_fp_score"),
            _metric("avg", "coverage_pct", "average_coverage_pct"),
            _metric("sum", "plots_served"),
            _metric("sum", "total_plots"),
        ],
        questions={
            "zh": "按场景、设施类型、出行方式和阶段汇总设施邻近性平均得分、平均覆盖率、已服务地块和总地块数。",
            "en": "Summarize facility proximity scores by context, facility type, mode, and stage with average score, average coverage, plots served, and total plots.",
            "ar": "لخص درجات قرب المرافق حسب السياق ونوع المرفق ووسيلة التنقل والمرحلة مع متوسط الدرجة والتغطية والقطع المخدومة وإجمالي القطع.",
        },
        asset_terms={
            "zh": ["设施邻近性平均得分"],
            "en": ["facility proximity scores"],
            "ar": ["درجات قرب المرافق"],
        },
    ),
    _intent(
        intent_id="infrastructure_completion_summary",
        table="public.fact_ic_scores",
        entity="dmt_liveability.infrastructure_completion_score",
        labels={
            "zh": "基础设施完成度",
            "en": "infrastructure completion",
            "ar": "اكتمال البنية التحتية",
        },
        aliases=["infrastructure completion scores", "IC scores", "基础设施完成度"],
        dimensions=["district_id"],
        metrics=[
            _metric("avg", "pedestrian_perc_existing", "average_pedestrian_existing_pct"),
            _metric("avg", "pedestrian_perc_ap50", "average_pedestrian_ap50_pct"),
            _metric("avg", "cycle_perc_existing", "average_cycle_existing_pct"),
            _metric("avg", "cycle_perc_ap50", "average_cycle_ap50_pct"),
        ],
        questions={
            "zh": "按片区汇总基础设施完成度中的现状与 AP50 步行和骑行平均比例。",
            "en": "Summarize infrastructure completion by district with average existing and AP50 pedestrian and cycling percentages.",
            "ar": "لخص اكتمال البنية التحتية حسب المنطقة بمتوسط نسب المشاة والدراجات للوضع الحالي وAP50.",
        },
        asset_terms={
            "zh": ["基础设施完成度"],
            "en": ["infrastructure completion"],
            "ar": ["اكتمال البنية التحتية"],
        },
    ),
    _intent(
        intent_id="other_indicator_inventory",
        table="public.fact_oi_indicators",
        entity="dmt_liveability.other_indicator",
        labels={
            "zh": "其他指标清单",
            "en": "other-indicator inventory",
            "ar": "جرد المؤشرات الأخرى",
        },
        aliases=["other indicators", "OI indicators", "其他指标清单"],
        dimensions=["indicator_type"],
        metrics=[
            _metric("count", "*", "indicator_row_count"),
            _metric("count_distinct", "district_id", "district_count"),
        ],
        questions={
            "zh": "按指标类型统计其他指标清单的记录数和片区数。",
            "en": "Count other-indicator inventory rows and districts by indicator type.",
            "ar": "احسب صفوف جرد المؤشرات الأخرى وعدد المناطق حسب نوع المؤشر.",
        },
        asset_terms={
            "zh": ["其他指标清单"],
            "en": ["other-indicator inventory"],
            "ar": ["جرد المؤشرات الأخرى"],
        },
    ),
    _intent(
        intent_id="parks_demand_summary",
        table="public.fact_parks_demand",
        entity="dmt_facility.parks_demand",
        labels={"zh": "公园面积需求", "en": "parks area demand", "ar": "الطلب على مساحة الحدائق"},
        aliases=["parks demand", "parks area demand", "公园面积需求"],
        dimensions=["district_id"],
        metrics=[
            _metric("sum", "existing_sqm"),
            _metric("sum", "area_required_sqm"),
            _metric("sum", "ap50_sqm"),
            _metric("sum", "pipeline_sqm"),
            _metric("sum", "ultimate_sqm"),
        ],
        questions={
            "zh": "按片区汇总公园面积需求的现状、需求、AP50、项目管线和远期面积。",
            "en": "Summarize parks area demand by district for existing, required, AP50, pipeline, and ultimate area.",
            "ar": "لخص الطلب على مساحة الحدائق حسب المنطقة للمساحة الحالية والمطلوبة وAP50 وخط المشاريع والمساحة النهائية.",
        },
        asset_terms={
            "zh": ["公园面积需求"],
            "en": ["parks area demand"],
            "ar": ["الطلب على مساحة الحدائق"],
        },
    ),
    _intent(
        intent_id="proximity_service_summary",
        table="public.fact_proximity_stats",
        entity="dmt_liveability.proximity_service_statistic",
        labels={
            "zh": "邻近性服务统计",
            "en": "proximity service statistic",
            "ar": "إحصاءات خدمة القرب",
        },
        aliases=["proximity service statistics", "proximity stats", "邻近性服务统计"],
        dimensions=["context", "facility_type", "mode", "stage"],
        metrics=[
            _metric("avg", "pct_served", "average_pct_served"),
            _metric("avg", "score", "average_score"),
            _metric("sum", "plots_served"),
            _metric("sum", "sum_resi_plots", "residential_plot_count"),
        ],
        questions={
            "zh": "按场景、设施类型、出行方式和阶段汇总邻近性服务统计的平均服务比例、平均得分、已服务地块和住宅地块数。",
            "en": "Summarize proximity service statistics by context, facility type, mode, and stage with average served percentage, average score, plots served, and residential plot count.",
            "ar": "لخص إحصاءات خدمة القرب حسب السياق ونوع المرفق ووسيلة التنقل والمرحلة مع متوسط نسبة الخدمة والدرجة والقطع المخدومة وعدد القطع السكنية.",
        },
        asset_terms={
            "zh": ["邻近性服务统计"],
            "en": ["proximity service statistics"],
            "ar": ["إحصاءات خدمة القرب"],
        },
    ),
    _intent(
        intent_id="qualitative_facility_score_summary",
        table="public.fact_qualitative_facility_scores",
        entity="dmt_liveability.qualitative_facility_score",
        labels={
            "zh": "设施定性质量得分",
            "en": "qualitative facility score",
            "ar": "درجة الجودة النوعية للمرفق",
        },
        aliases=["qualitative facility scores", "facility quality scores", "设施定性质量得分"],
        dimensions=["facility_type"],
        metrics=[
            _metric("avg", "qual_score", "average_qualitative_score"),
            _metric("count_distinct", "district_id", "district_count"),
            _metric("count", "*", "score_row_count"),
        ],
        questions={
            "zh": "按设施类型汇总设施定性质量平均得分、片区数和记录数。",
            "en": "Summarize qualitative facility scores by facility type with average score, district count, and row count.",
            "ar": "لخص درجات الجودة النوعية للمرافق حسب نوع المرفق مع متوسط الدرجة وعدد المناطق والصفوف.",
        },
        asset_terms={
            "zh": ["设施定性质量"],
            "en": ["qualitative facility scores"],
            "ar": ["درجات الجودة النوعية للمرافق"],
        },
    ),
    _intent(
        intent_id="school_capacity_summary",
        table="public.fact_school_fc",
        entity="dmt_facility.school_capacity",
        labels={"zh": "学校容量", "en": "school capacity", "ar": "سعة المدارس"},
        aliases=["school capacity", "school facility capacity", "学校容量"],
        dimensions=["school_type"],
        metrics=[
            _metric("sum", "school_count"),
            _metric("sum", "total_capacity"),
            _metric("sum", "total_students"),
            _metric("avg", "fc_kpi", "average_facility_capacity_kpi"),
        ],
        questions={
            "zh": "按学校类型汇总学校容量中的学校数、总容量、学生总数和平均设施容量 KPI。",
            "en": "Summarize school capacity by school type with school count, total capacity, total students, and average facility-capacity KPI.",
            "ar": "لخص سعة المدارس حسب نوع المدرسة مع عدد المدارس والسعة الإجمالية وإجمالي الطلاب ومتوسط مؤشر سعة المرافق.",
        },
        asset_terms={"zh": ["学校容量"], "en": ["school capacity"], "ar": ["سعة المدارس"]},
    ),
)


FIELD_LABELS: dict[str, dict[str, str]] = {
    "group_key": {"zh": "指标组标识", "en": "metric group key", "ar": "مفتاح مجموعة المؤشر"},
    "group_name": {"zh": "指标组名称", "en": "metric group name", "ar": "اسم مجموعة المؤشر"},
    "sort_order": {"zh": "排序", "en": "sort order", "ar": "الترتيب"},
    "data_source": {"zh": "数据来源", "en": "data source", "ar": "مصدر البيانات"},
    "unit": {"zh": "单位", "en": "unit", "ar": "الوحدة"},
    "project_type": {"zh": "项目类型", "en": "project type", "ar": "نوع المشروع"},
    "package": {"zh": "数据包", "en": "package", "ar": "الحزمة"},
    "version_label": {"zh": "版本标签", "en": "version label", "ar": "تسمية الإصدار"},
    "data_date": {"zh": "数据日期", "en": "data date", "ar": "تاريخ البيانات"},
    "reporting_year": {"zh": "报告年份", "en": "reporting year", "ar": "سنة التقرير"},
    "facility_category": {"zh": "设施类别", "en": "facility category", "ar": "فئة المرفق"},
    "subcategory": {"zh": "子类别", "en": "subcategory", "ar": "الفئة الفرعية"},
    "municipality": {"zh": "市政区域", "en": "municipality", "ar": "البلدية"},
    "score_range": {"zh": "得分区间", "en": "score range", "ar": "نطاق الدرجة"},
    "district_id": {"zh": "片区标识", "en": "district identifier", "ar": "معرف المنطقة"},
    "owner_sector_lead": {"zh": "责任部门", "en": "owner-sector lead", "ar": "القطاع المسؤول"},
    "facility_type": {"zh": "设施类型", "en": "facility type", "ar": "نوع المرفق"},
    "context": {"zh": "分析场景", "en": "analysis context", "ar": "سياق التحليل"},
    "stage": {"zh": "阶段", "en": "stage", "ar": "المرحلة"},
    "mode": {"zh": "出行方式", "en": "travel mode", "ar": "وسيلة التنقل"},
    "indicator_type": {"zh": "指标类型", "en": "indicator type", "ar": "نوع المؤشر"},
    "school_type": {"zh": "学校类型", "en": "school type", "ar": "نوع المدرسة"},
}
