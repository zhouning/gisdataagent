"""Reviewed Makani v2 table-local semantic expansion contracts."""

from __future__ import annotations

from typing import Any


def _intent(
    *,
    intent_id: str,
    table: str,
    entity: str,
    labels: dict[str, str],
    aliases: list[str],
    dimensions: list[str],
    questions: dict[str, str],
    match_asset_terms: dict[str, list[str]],
    match_dimension_terms: dict[str, list[list[str]]],
) -> dict[str, Any]:
    return {
        "id": intent_id,
        "contract_id": f"{intent_id.upper()}_V2",
        "table": table,
        "entity": entity,
        "labels": labels,
        "aliases": aliases,
        "dimensions": dimensions,
        "questions": questions,
        "match": {
            "required_term_groups": {
                language: [
                    {
                        "zh": ["统计", "汇总"],
                        "en": ["count", "summarize"],
                        "ar": ["احسب", "لخص"],
                    }[language],
                    match_asset_terms[language],
                    *match_dimension_terms[language],
                ]
                for language in ("zh", "en", "ar")
            }
        },
    }


EXPANSION_INTENTS: tuple[dict[str, Any], ...] = (
    _intent(
        intent_id="electric_distribution_busbar_summary_by_type_status",
        table="layer.ed_busbar",
        entity="dmt_utility.electric_distribution_busbar",
        labels={
            "zh": "配电母线",
            "en": "electric distribution busbar",
            "ar": "قضيب توزيع الكهرباء",
        },
        aliases=["ed_busbar", "distribution busbars", "配电母线", "قضبان التوزيع"],
        dimensions=["busbartype", "statusindicator"],
        questions={
            "zh": "按母线类型和状态统计配电母线数量。",
            "en": "Count electric distribution busbars by busbar type and status.",
            "ar": "احسب قضبان توزيع الكهرباء حسب نوع القضيب والحالة.",
        },
        match_asset_terms={
            "zh": ["配电母线"],
            "en": ["electric distribution busbars", "distribution busbars"],
            "ar": ["قضبان توزيع الكهرباء"],
        },
        match_dimension_terms={
            "zh": [["母线类型"], ["状态"]],
            "en": [["busbar type"], ["status"]],
            "ar": [["نوع القضيب"], ["الحالة"]],
        },
    ),
    _intent(
        intent_id="electric_distribution_streetlight_summary_by_status_subtype",
        table="layer.ed_streetlight",
        entity="dmt_utility.electric_distribution_streetlight",
        labels={
            "zh": "配电路灯设施",
            "en": "electric distribution streetlight",
            "ar": "إنارة شوارع شبكة التوزيع",
        },
        aliases=["ed_streetlight", "distribution streetlights", "配电路灯设施"],
        dimensions=["statusindicator", "subtypecd"],
        questions={
            "zh": "按状态和子类型代码统计配电路灯设施数量。",
            "en": "Count electric distribution streetlights by status and subtype code.",
            "ar": "احسب إنارة شوارع شبكة التوزيع حسب الحالة ورمز النوع الفرعي.",
        },
        match_asset_terms={
            "zh": ["配电路灯设施"],
            "en": ["electric distribution streetlights", "distribution streetlights"],
            "ar": ["إنارة شوارع شبكة التوزيع"],
        },
        match_dimension_terms={
            "zh": [["状态"], ["子类型代码"]],
            "en": [["status"], ["subtype code"]],
            "ar": [["الحالة"], ["رمز النوع الفرعي"]],
        },
    ),
    _intent(
        intent_id="electric_transmission_overhead_structure_summary",
        table="layer.et_t_overheadstructure",
        entity="dmt_utility.electric_transmission_overhead_structure",
        labels={
            "zh": "输电架空结构",
            "en": "electric transmission overhead structure",
            "ar": "هيكل نقل كهربائي علوي",
        },
        aliases=["et_t_overheadstructure", "transmission overhead structures", "输电架空结构"],
        dimensions=["planningstatus", "subtypecd"],
        questions={
            "zh": "按规划状态和子类型代码统计输电架空结构数量。",
            "en": (
                "Count electric transmission overhead structures by planning "
                "status and subtype code."
            ),
            "ar": "احسب هياكل نقل الكهرباء العلوية حسب حالة التخطيط ورمز النوع الفرعي.",
        },
        match_asset_terms={
            "zh": ["输电架空结构"],
            "en": ["electric transmission overhead structures", "transmission overhead structures"],
            "ar": ["هياكل نقل الكهرباء العلوية"],
        },
        match_dimension_terms={
            "zh": [["规划状态"], ["子类型代码"]],
            "en": [["planning status"], ["subtype code"]],
            "ar": [["حالة التخطيط"], ["رمز النوع الفرعي"]],
        },
    ),
    _intent(
        intent_id="electric_transmission_duct_summary_by_material_subtype",
        table="layer.et_t_ductedge",
        entity="dmt_utility.electric_transmission_duct",
        labels={
            "zh": "输电管沟线段",
            "en": "electric transmission duct segment",
            "ar": "مقطع قناة نقل الكهرباء",
        },
        aliases=["et_t_ductedge", "transmission duct segments", "输电管沟线段"],
        dimensions=["material", "subtypecd"],
        questions={
            "zh": "按材质和子类型代码统计输电管沟线段数量。",
            "en": "Count electric transmission duct segments by material and subtype code.",
            "ar": "احسب مقاطع قنوات نقل الكهرباء حسب المادة ورمز النوع الفرعي.",
        },
        match_asset_terms={
            "zh": ["输电管沟线段"],
            "en": ["electric transmission duct segments", "transmission duct segments"],
            "ar": ["مقاطع قنوات نقل الكهرباء"],
        },
        match_dimension_terms={
            "zh": [["材质"], ["子类型代码"]],
            "en": [["material"], ["subtype code"]],
            "ar": [["المادة"], ["رمز النوع الفرعي"]],
        },
    ),
    _intent(
        intent_id="irrigation_pressure_main_summary_by_subtype_condition",
        table="layer.ir_irrpressuremain",
        entity="dmt_utility.irrigation_pressure_main",
        labels={
            "zh": "灌溉压力主管",
            "en": "irrigation pressure main",
            "ar": "خط ضغط رئيسي للري",
        },
        aliases=["ir_irrpressuremain", "irrigation pressure mains", "灌溉压力主管"],
        dimensions=["subtype", "condition"],
        questions={
            "zh": "按子类型和状况统计灌溉压力主管数量。",
            "en": "Count irrigation pressure mains by subtype and condition.",
            "ar": "احسب خطوط الضغط الرئيسية للري حسب النوع الفرعي وحالة الأصل.",
        },
        match_asset_terms={
            "zh": ["灌溉压力主管"],
            "en": ["irrigation pressure mains"],
            "ar": ["خطوط الضغط الرئيسية للري"],
        },
        match_dimension_terms={
            "zh": [["子类型"], ["状况"]],
            "en": [["subtype"], ["condition"]],
            "ar": [["النوع الفرعي"], ["حالة الأصل"]],
        },
    ),
    _intent(
        intent_id="irrigation_spray_head_summary_by_condition",
        table="layer.ir_sprayhead",
        entity="dmt_utility.irrigation_spray_head",
        labels={"zh": "灌溉喷头", "en": "irrigation spray head", "ar": "رأس رش للري"},
        aliases=["ir_sprayhead", "irrigation spray heads", "灌溉喷头"],
        dimensions=["condition"],
        questions={
            "zh": "按状况统计灌溉喷头数量。",
            "en": "Count irrigation spray heads by condition.",
            "ar": "احسب رؤوس الرش للري حسب حالة الأصل.",
        },
        match_asset_terms={
            "zh": ["灌溉喷头"],
            "en": ["irrigation spray heads"],
            "ar": ["رؤوس الرش للري"],
        },
        match_dimension_terms={
            "zh": [["状况"]],
            "en": [["condition"]],
            "ar": [["حالة الأصل"]],
        },
    ),
    _intent(
        intent_id="recycled_water_pressurized_main_summary",
        table="layer.rw_pressurizedmain_rw",
        entity="dmt_utility.recycled_water_pressurized_main",
        labels={
            "zh": "再生水压力主管",
            "en": "recycled water pressurized main",
            "ar": "خط ضغط رئيسي للمياه المعاد تدويرها",
        },
        aliases=["rw_pressurizedmain_rw", "recycled water pressurized mains", "再生水压力主管"],
        dimensions=["lifecyclestatus", "subtype"],
        questions={
            "zh": "按生命周期状态和子类型统计再生水压力主管数量。",
            "en": "Count recycled water pressurized mains by lifecycle status and subtype.",
            "ar": (
                "احسب خطوط الضغط الرئيسية للمياه المعاد تدويرها حسب حالة دورة "
                "الحياة والنوع الفرعي."
            ),
        },
        match_asset_terms={
            "zh": ["再生水压力主管"],
            "en": ["recycled water pressurized mains"],
            "ar": ["خطوط الضغط الرئيسية للمياه المعاد تدويرها"],
        },
        match_dimension_terms={
            "zh": [["生命周期状态"], ["子类型"]],
            "en": [["lifecycle status"], ["subtype"]],
            "ar": [["حالة دورة الحياة"], ["النوع الفرعي"]],
        },
    ),
    _intent(
        intent_id="recycled_water_chamber_summary_by_lifecycle_subtype",
        table="layer.rw_chamber_rw",
        entity="dmt_utility.recycled_water_chamber",
        labels={
            "zh": "再生水井室",
            "en": "recycled water chamber",
            "ar": "غرفة مياه معاد تدويرها",
        },
        aliases=["rw_chamber_rw", "recycled water chambers", "再生水井室"],
        dimensions=["lifecyclestatus", "subtype"],
        questions={
            "zh": "按生命周期状态和子类型统计再生水井室数量。",
            "en": "Count recycled water chambers by lifecycle status and subtype.",
            "ar": "احسب غرف المياه المعاد تدويرها حسب حالة دورة الحياة والنوع الفرعي.",
        },
        match_asset_terms={
            "zh": ["再生水井室"],
            "en": ["recycled water chambers"],
            "ar": ["غرف المياه المعاد تدويرها"],
        },
        match_dimension_terms={
            "zh": [["生命周期状态"], ["子类型"]],
            "en": [["lifecycle status"], ["subtype"]],
            "ar": [["حالة دورة الحياة"], ["النوع الفرعي"]],
        },
    ),
    _intent(
        intent_id="stormwater_inlet_summary_by_material_condition",
        table="layer.st_inlet",
        entity="dmt_utility.stormwater_inlet",
        labels={"zh": "排水进水口", "en": "drainage inlet", "ar": "مدخل تصريف"},
        aliases=["st_inlet", "drainage inlets", "排水进水口"],
        dimensions=["material", "condition"],
        questions={
            "zh": "按材质和状况统计排水进水口数量。",
            "en": "Count drainage inlets by material and condition.",
            "ar": "احسب مداخل التصريف حسب المادة وحالة الأصل.",
        },
        match_asset_terms={
            "zh": ["排水进水口"],
            "en": ["drainage inlets"],
            "ar": ["مداخل التصريف"],
        },
        match_dimension_terms={
            "zh": [["材质"], ["状况"]],
            "en": [["material"], ["condition"]],
            "ar": [["المادة"], ["حالة الأصل"]],
        },
    ),
    _intent(
        intent_id="stormwater_catch_basin_summary_by_condition",
        table="layer.st_catchbasin",
        entity="dmt_utility.stormwater_catch_basin",
        labels={"zh": "排水集水井", "en": "drainage catch basin", "ar": "حوض تجميع تصريف"},
        aliases=["st_catchbasin", "drainage catch basins", "排水集水井"],
        dimensions=["condition"],
        questions={
            "zh": "按状况统计排水集水井数量。",
            "en": "Count drainage catch basins by condition.",
            "ar": "احسب أحواض تجميع التصريف حسب حالة الأصل.",
        },
        match_asset_terms={
            "zh": ["排水集水井"],
            "en": ["drainage catch basins"],
            "ar": ["أحواض تجميع التصريف"],
        },
        match_dimension_terms={
            "zh": [["状况"]],
            "en": [["condition"]],
            "ar": [["حالة الأصل"]],
        },
    ),
    _intent(
        intent_id="sewage_gravity_manhole_summary_by_subtype",
        table="layer.sw_adssc_s_sgravitymanhole",
        entity="dmt_utility.sewage_gravity_manhole",
        labels={
            "zh": "污水重力检查井",
            "en": "sewage gravity manhole",
            "ar": "غرفة تفتيش صرف صحي بالجاذبية",
        },
        aliases=["sw_adssc_s_sgravitymanhole", "sewage gravity manholes", "污水重力检查井"],
        dimensions=["subtypecd"],
        questions={
            "zh": "按子类型代码统计污水重力检查井数量。",
            "en": "Count sewage gravity manholes by subtype code.",
            "ar": "احسب غرف تفتيش الصرف الصحي بالجاذبية حسب رمز النوع الفرعي.",
        },
        match_asset_terms={
            "zh": ["污水重力检查井"],
            "en": ["sewage gravity manholes"],
            "ar": ["غرف تفتيش الصرف الصحي بالجاذبية"],
        },
        match_dimension_terms={
            "zh": [["子类型代码"]],
            "en": [["subtype code"]],
            "ar": [["رمز النوع الفرعي"]],
        },
    ),
    _intent(
        intent_id="sewage_house_connection_summary_by_material_subtype",
        table="layer.sw_adssc_s_shouseconnection",
        entity="dmt_utility.sewage_house_connection",
        labels={
            "zh": "污水入户连接",
            "en": "sewage house connection",
            "ar": "وصلة صرف صحي منزلية",
        },
        aliases=["sw_adssc_s_shouseconnection", "sewage house connections", "污水入户连接"],
        dimensions=["material", "subtypecd"],
        questions={
            "zh": "按材质和子类型代码统计污水入户连接数量。",
            "en": "Count sewage house connections by material and subtype code.",
            "ar": "احسب وصلات الصرف الصحي المنزلية حسب المادة ورمز النوع الفرعي.",
        },
        match_asset_terms={
            "zh": ["污水入户连接"],
            "en": ["sewage house connections"],
            "ar": ["وصلات الصرف الصحي المنزلية"],
        },
        match_dimension_terms={
            "zh": [["材质"], ["子类型代码"]],
            "en": [["material"], ["subtype code"]],
            "ar": [["المادة"], ["رمز النوع الفرعي"]],
        },
    ),
    _intent(
        intent_id="du_telecom_span_summary_by_type",
        table="layer.tc_l_du_span",
        entity="dmt_utility.du_telecommunications_span",
        labels={"zh": "DU 通信线段", "en": "DU telecom span", "ar": "مقطع اتصالات دو"},
        aliases=["tc_l_du_span", "DU telecom spans", "DU 通信线段"],
        dimensions=["span_type"],
        questions={
            "zh": "按线段类型统计 DU 通信线段数量。",
            "en": "Count DU telecom spans by span type.",
            "ar": "احسب مقاطع اتصالات دو حسب نوع المقطع.",
        },
        match_asset_terms={
            "zh": ["DU 通信线段"],
            "en": ["DU telecom spans"],
            "ar": ["مقاطع اتصالات دو"],
        },
        match_dimension_terms={
            "zh": [["线段类型"]],
            "en": [["span type"]],
            "ar": [["نوع المقطع"]],
        },
    ),
    _intent(
        intent_id="etisalat_telecom_span_summary_by_category_inventory_status",
        table="layer.tc_l_etisalat_span",
        entity="dmt_utility.etisalat_telecommunications_span",
        labels={
            "zh": "Etisalat 通信线段",
            "en": "Etisalat telecom span",
            "ar": "مقطع اتصالات اتصالات",
        },
        aliases=["tc_l_etisalat_span", "Etisalat telecom spans", "Etisalat 通信线段"],
        dimensions=["category_name", "inventory_status_code"],
        questions={
            "zh": "按类别和库存状态统计 Etisalat 通信线段数量。",
            "en": "Count Etisalat telecom spans by category and inventory status.",
            "ar": "احسب مقاطع اتصالات اتصالات حسب الفئة وحالة المخزون.",
        },
        match_asset_terms={
            "zh": ["Etisalat 通信线段"],
            "en": ["Etisalat telecom spans"],
            "ar": ["مقاطع اتصالات اتصالات"],
        },
        match_dimension_terms={
            "zh": [["类别"], ["库存状态"]],
            "en": [["category"], ["inventory status"]],
            "ar": [["الفئة"], ["حالة المخزون"]],
        },
    ),
    _intent(
        intent_id="water_distribution_service_line_summary",
        table="layer.wd_serviceline",
        entity="dmt_utility.water_distribution_service_line",
        labels={
            "zh": "配水服务管线",
            "en": "water distribution service line",
            "ar": "خط خدمة توزيع المياه",
        },
        aliases=["wd_serviceline", "water distribution service lines", "配水服务管线"],
        dimensions=["lifecyclestatus", "material"],
        questions={
            "zh": "按生命周期状态和材质统计配水服务管线数量。",
            "en": "Count water distribution service lines by lifecycle status and material.",
            "ar": "احسب خطوط خدمة توزيع المياه حسب حالة دورة الحياة والمادة.",
        },
        match_asset_terms={
            "zh": ["配水服务管线"],
            "en": ["water distribution service lines"],
            "ar": ["خطوط خدمة توزيع المياه"],
        },
        match_dimension_terms={
            "zh": [["生命周期状态"], ["材质"]],
            "en": [["lifecycle status"], ["material"]],
            "ar": [["حالة دورة الحياة"], ["المادة"]],
        },
    ),
    _intent(
        intent_id="water_distribution_chamber_summary_by_lifecycle_subtype",
        table="layer.wd_chamber",
        entity="dmt_utility.water_distribution_chamber",
        labels={
            "zh": "配水井室",
            "en": "water distribution chamber",
            "ar": "غرفة توزيع المياه",
        },
        aliases=["wd_chamber", "water distribution chambers", "配水井室"],
        dimensions=["lifecyclestatus", "subtype"],
        questions={
            "zh": "按生命周期状态和子类型统计配水井室数量。",
            "en": "Count water distribution chambers by lifecycle status and subtype.",
            "ar": "احسب غرف توزيع المياه حسب حالة دورة الحياة والنوع الفرعي.",
        },
        match_asset_terms={
            "zh": ["配水井室"],
            "en": ["water distribution chambers"],
            "ar": ["غرف توزيع المياه"],
        },
        match_dimension_terms={
            "zh": [["生命周期状态"], ["子类型"]],
            "en": [["lifecycle status"], ["subtype"]],
            "ar": [["حالة دورة الحياة"], ["النوع الفرعي"]],
        },
    ),
    _intent(
        intent_id="water_transmission_system_valve_summary",
        table="layer.wt_trans_systemvalve",
        entity="dmt_utility.water_transmission_system_valve",
        labels={
            "zh": "输水系统阀门",
            "en": "water transmission system valve",
            "ar": "صمام نظام نقل المياه",
        },
        aliases=["wt_trans_systemvalve", "water transmission system valves", "输水系统阀门"],
        dimensions=["lifecyclestatus", "subtype"],
        questions={
            "zh": "按生命周期状态和子类型统计输水系统阀门数量。",
            "en": "Count water transmission system valves by lifecycle status and subtype.",
            "ar": "احسب صمامات نظام نقل المياه حسب حالة دورة الحياة والنوع الفرعي.",
        },
        match_asset_terms={
            "zh": ["输水系统阀门"],
            "en": ["water transmission system valves"],
            "ar": ["صمامات نظام نقل المياه"],
        },
        match_dimension_terms={
            "zh": [["生命周期状态"], ["子类型"]],
            "en": [["lifecycle status"], ["subtype"]],
            "ar": [["حالة دورة الحياة"], ["النوع الفرعي"]],
        },
    ),
    _intent(
        intent_id="water_transmission_gravity_pipe_summary",
        table="layer.wt_trans_gravitypipe",
        entity="dmt_utility.water_transmission_gravity_pipe",
        labels={
            "zh": "输水重力管",
            "en": "water transmission gravity pipe",
            "ar": "أنبوب نقل مياه بالجاذبية",
        },
        aliases=["wt_trans_gravitypipe", "water transmission gravity pipes", "输水重力管"],
        dimensions=["lifecyclestatus", "subtype"],
        questions={
            "zh": "按生命周期状态和子类型统计输水重力管数量。",
            "en": "Count water transmission gravity pipes by lifecycle status and subtype.",
            "ar": "احسب أنابيب نقل المياه بالجاذبية حسب حالة دورة الحياة والنوع الفرعي.",
        },
        match_asset_terms={
            "zh": ["输水重力管"],
            "en": ["water transmission gravity pipes"],
            "ar": ["أنابيب نقل المياه بالجاذبية"],
        },
        match_dimension_terms={
            "zh": [["生命周期状态"], ["子类型"]],
            "en": [["lifecycle status"], ["subtype"]],
            "ar": [["حالة دورة الحياة"], ["النوع الفرعي"]],
        },
    ),
)


FIELD_LABELS: dict[str, dict[str, str]] = {
    "busbartype": {"zh": "母线类型", "en": "busbar type", "ar": "نوع القضيب"},
    "statusindicator": {"zh": "状态", "en": "status", "ar": "الحالة"},
    "subtypecd": {"zh": "子类型代码", "en": "subtype code", "ar": "رمز النوع الفرعي"},
    "planningstatus": {"zh": "规划状态", "en": "planning status", "ar": "حالة التخطيط"},
    "material": {"zh": "材质", "en": "material", "ar": "المادة"},
    "subtype": {"zh": "子类型", "en": "subtype", "ar": "النوع الفرعي"},
    "condition": {"zh": "状况", "en": "condition", "ar": "حالة الأصل"},
    "lifecyclestatus": {
        "zh": "生命周期状态",
        "en": "lifecycle status",
        "ar": "حالة دورة الحياة",
    },
    "span_category": {"zh": "线段类别", "en": "span category", "ar": "فئة المقطع"},
    "span_status": {"zh": "线段状态", "en": "span status", "ar": "حالة المقطع"},
    "span_type": {"zh": "线段类型", "en": "span type", "ar": "نوع المقطع"},
    "category_name": {"zh": "类别", "en": "category", "ar": "الفئة"},
    "inventory_status_code": {
        "zh": "库存状态",
        "en": "inventory status",
        "ar": "حالة المخزون",
    },
}


__all__ = ["EXPANSION_INTENTS", "FIELD_LABELS"]
