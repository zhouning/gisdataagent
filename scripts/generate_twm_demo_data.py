#!/usr/bin/env python3
"""Generate a local demo dataset for the Territorial World Model MVP.

The generated layers are for engineering tests and product demos only. They
derive synthetic control zones and events from available local DLTB-like data,
and every synthetic layer is explicitly marked as not for production use.
"""

from __future__ import annotations

import argparse
import json
import math
import random
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import GeometryCollection, MultiPolygon, Polygon, box
from shapely.ops import unary_union
from shapely.validation import make_valid

try:
    import rasterio
    from rasterio.features import rasterize
    from rasterio.transform import from_bounds
except ImportError:  # pragma: no cover - runtime dependency check is handled in generator.
    rasterio = None
    rasterize = None
    from_bounds = None


DEFAULT_PARCELS = Path("/Users/zhouning/Downloads/bishan/DLTB_with_slope.gpkg")
DEFAULT_SCENARIO = Path("/Users/zhouning/farmland_mpc_runs/bishan/mpc_output/optimized.shp")
DEFAULT_WORLD_MODEL_SUMMARY = Path(
    "/Users/zhouning/farmland_mpc_runs/bishan/mpc_output/mpc_summary.json"
)
DEFAULT_ADMIN_BOUNDARIES = Path("/Users/zhouning/Downloads/shp/xiangzhen.shp")
DEFAULT_OUTPUT_DIR = Path("data_agent/test_data/twm_bishan_demo")
DEFAULT_PROJECT_CRS = "EPSG:32648"
DEFAULT_ADMIN_PREFIX = "500227100"
DEFAULT_DATASET_ID = "twm_bishan_demo"
DEFAULT_DATASET_ALIAS_ZH = "国土空间世界模型璧山演示数据包"
STANDARD_CONTRACT_DIR = Path("data_agent/test_data/twm_standards")
STANDARD_CONTRACT_FILES = [
    "one_map_role_contracts.zh.json",
    "one_map_field_aliases.zh.json",
    "one_map_value_domains.zh.json",
]


LAYER_ALIASES = {
    "parcel_current": {
        "alias_zh": "现状地类图斑",
        "description_zh": "从璧山 DLTB 坡度增强数据抽样得到的现状地类图斑。",
        "business_role_zh": "状态对象底板",
        "style_hint": {"fill": "#c7c7c7", "stroke": "#777777"},
    },
    "synthetic_pbf": {
        "alias_zh": "合成永久基本农田",
        "description_zh": "基于低坡度、较大面积耕地图斑合成的永久基本农田演示层。",
        "business_role_zh": "耕地保护硬约束",
        "style_hint": {"fill": "#2ca25f", "stroke": "#006d2c"},
    },
    "synthetic_eco_redline": {
        "alias_zh": "合成生态保护红线",
        "description_zh": "基于林地、水域、高坡度图斑并局部缓冲合成的生态保护红线演示层。",
        "business_role_zh": "生态保护硬约束",
        "style_hint": {"fill": "#dd1c77", "stroke": "#980043"},
    },
    "admin_units": {
        "alias_zh": "乡镇行政区边界",
        "description_zh": "从乡镇行政区边界数据中按演示区叠加筛选得到的行政边界参考层。",
        "business_role_zh": "区域汇总与项目范围",
        "style_hint": {"fill": "transparent", "stroke": "#756bb1"},
    },
    "synthetic_annual_change": {
        "alias_zh": "合成年度变化图斑",
        "description_zh": "从 WorldModel v2.1 优化结果的 ORIG_DLBM 到 OPT_DLBM 派生的变化图斑。",
        "business_role_zh": "状态变化与时序证据",
        "style_hint": {"fill": "#fb6a4a", "stroke": "#a50f15"},
    },
    "synthetic_projects": {
        "alias_zh": "合成建设项目范围",
        "description_zh": "按多类业务场景合成的拟建/调整项目范围，用于触线风险和审批一致性演示。",
        "business_role_zh": "项目约束校验主体",
        "style_hint": {"fill": "transparent", "stroke": "#f16913"},
    },
    "synthetic_planning_zones": {
        "alias_zh": "合成用途管制分区",
        "description_zh": "由现状地类归并并 dissolve 得到的用途管制分区演示层。",
        "business_role_zh": "规划一致性约束",
        "style_hint": {"fill": "#9ecae1", "stroke": "#2171b5"},
    },
    "synthetic_urban_boundary": {
        "alias_zh": "合成城镇开发边界",
        "description_zh": "由建设用地图斑聚合、缓冲、简化得到的城镇开发边界演示层。",
        "business_role_zh": "城镇开发边界约束",
        "style_hint": {"fill": "transparent", "stroke": "#54278f"},
    },
    "synthetic_remote_sensing_tiles": {
        "alias_zh": "合成遥感影像瓦片索引",
        "description_zh": "覆盖演示区的合成遥感影像瓦片索引，用于 MMFE 多模态证据链测试。",
        "business_role_zh": "多模态观测证据",
        "style_hint": {"fill": "transparent", "stroke": "#08519c"},
    },
}


FIELD_ALIASES = {
    "BSM": {"alias_zh": "标识码", "description_zh": "原始地类图斑唯一标识。"},
    "bsm_norm": {"alias_zh": "规范化标识码", "description_zh": "去除浮点后缀后的稳定图斑标识。"},
    "YSDM": {"alias_zh": "要素代码", "description_zh": "自然资源调查监测要素代码。"},
    "DLBM": {"alias_zh": "地类编码", "description_zh": "土地利用分类编码。"},
    "DLMC": {"alias_zh": "地类名称", "description_zh": "土地利用分类中文名称。"},
    "QSDWDM": {"alias_zh": "权属单位代码", "description_zh": "图斑权属单位代码。"},
    "QSDWMC": {"alias_zh": "权属单位名称", "description_zh": "图斑权属单位中文名称。"},
    "ZLDWDM": {"alias_zh": "坐落单位代码", "description_zh": "图斑坐落单位代码。"},
    "ZLDWMC": {"alias_zh": "坐落单位名称", "description_zh": "图斑坐落单位中文名称。"},
    "TBMJ": {"alias_zh": "图斑面积", "description_zh": "原始图斑面积，单位通常为平方米。"},
    "SHAPE_Length": {"alias_zh": "几何周长", "description_zh": "源数据中的系统几何周长字段。"},
    "SHAPE_Area": {"alias_zh": "几何面积", "description_zh": "源数据中的系统几何面积字段。"},
    "category": {"alias_zh": "归并地类", "description_zh": "为 WorldModel 使用归并后的地类类别。"},
    "slope_mean": {"alias_zh": "平均坡度", "description_zh": "图斑范围内 DEM 派生平均坡度。"},
    "slope_max": {"alias_zh": "最大坡度", "description_zh": "图斑范围内 DEM 派生最大坡度。"},
    "slope_pixel_count": {"alias_zh": "坡度像元数", "description_zh": "参与坡度统计的像元数量。"},
    "demo_role": {"alias_zh": "演示角色", "description_zh": "该要素在 TWM demo 中承担的角色。"},
    "demo_sample": {"alias_zh": "演示抽样标记", "description_zh": "标记该要素是否来自演示抽样。"},
    "synthetic": {"alias_zh": "是否合成", "description_zh": "true 表示该要素由脚本合成。"},
    "not_for_production": {"alias_zh": "禁止生产使用", "description_zh": "true 表示只能用于工程测试和演示。"},
    "synthetic_method": {"alias_zh": "合成方法", "description_zh": "生成该图层或要素的合成方法。"},
    "source_dataset": {"alias_zh": "来源数据集", "description_zh": "生成该要素所依据的源文件。"},
    "control_id": {"alias_zh": "管控区编号", "description_zh": "合成永久基本农田管控区编号。"},
    "control_type": {"alias_zh": "管控区类型", "description_zh": "管控区业务类型。"},
    "redline_id": {"alias_zh": "红线区编号", "description_zh": "合成生态保护红线编号。"},
    "zone_type": {"alias_zh": "分区类型", "description_zh": "生态或规划分区类型。"},
    "admin_code": {"alias_zh": "行政单元代码", "description_zh": "行政管理单元代码或稳定标识。"},
    "admin_name": {"alias_zh": "行政单元名称", "description_zh": "行政管理单元名称。"},
    "admin_level": {"alias_zh": "行政层级", "description_zh": "行政单元层级。"},
    "admin_parent_code": {"alias_zh": "上级行政单元代码", "description_zh": "该行政管理单元的上级代码。"},
    "admin_level_rank": {"alias_zh": "行政层级序号", "description_zh": "用于排序的行政层级序号。"},
    "admin_source_level": {"alias_zh": "行政来源层级", "description_zh": "从权属单位代码截取或汇总形成的来源层级。"},
    "province_name": {"alias_zh": "省级名称", "description_zh": "乡镇边界数据中的省级行政名称。"},
    "city_name": {"alias_zh": "市级名称", "description_zh": "乡镇边界数据中的市级行政名称。"},
    "county_name": {"alias_zh": "县区名称", "description_zh": "乡镇边界数据中的县区行政名称。"},
    "township_name": {"alias_zh": "乡镇街道名称", "description_zh": "乡镇边界数据中的乡镇或街道名称。"},
    "city_county_name": {"alias_zh": "市县组合名", "description_zh": "乡镇边界数据中的市县组合名称。"},
    "province_county_name": {"alias_zh": "省县组合名", "description_zh": "乡镇边界数据中的省县组合名称。"},
    "matched_admin9_values": {"alias_zh": "匹配九位行政前缀", "description_zh": "该乡镇边界与演示图斑叠加匹配到的 admin9 前缀集合。"},
    "matched_parcel_count": {"alias_zh": "匹配图斑数量", "description_zh": "与该乡镇边界发生正面积叠加的演示图斑数量。"},
    "overlap_area_m2": {"alias_zh": "叠加面积", "description_zh": "行政边界与演示图斑并集的正面积叠加面积，单位平方米。"},
    "overlap_ratio_to_parcels": {"alias_zh": "图斑覆盖比例", "description_zh": "行政边界叠加面积占演示图斑并集面积比例。"},
    "change_id": {"alias_zh": "变化编号", "description_zh": "合成年度变化事件编号。"},
    "from_dlbm": {"alias_zh": "变化前地类编码", "description_zh": "变化前土地利用分类编码。"},
    "to_dlbm": {"alias_zh": "变化后地类编码", "description_zh": "变化后土地利用分类编码。"},
    "change_type": {"alias_zh": "变化类型", "description_zh": "来自 WorldModel 输出的变化类型标记。"},
    "change_year": {"alias_zh": "变化年份", "description_zh": "合成变化所属年份。"},
    "event_date": {"alias_zh": "事件日期", "description_zh": "变化、审批、执法或复核事件发生日期。"},
    "temporal_stage": {"alias_zh": "时序阶段", "description_zh": "基期、现状、预测或复核等时序阶段。"},
    "evidence_confidence": {"alias_zh": "证据置信度", "description_zh": "合成证据链置信度。"},
    "source_feature_id": {"alias_zh": "来源要素编号", "description_zh": "来源图斑、项目或规则结果编号。"},
    "OPT_DLBM": {"alias_zh": "优化后地类编码", "description_zh": "WorldModel v2.1 输出的优化后地类编码。"},
    "OPT_DLMC": {"alias_zh": "优化后地类名称", "description_zh": "WorldModel v2.1 输出的优化后地类名称。"},
    "ORIG_DLBM": {"alias_zh": "原始地类编码", "description_zh": "WorldModel v2.1 输出中的原始地类编码。"},
    "CHG_FLAG": {"alias_zh": "变化标记", "description_zh": "WorldModel v2.1 输出中的变化标记。"},
    "project_id": {"alias_zh": "项目编号", "description_zh": "合成建设项目编号。"},
    "project_name": {"alias_zh": "项目名称", "description_zh": "合成建设项目名称。"},
    "project_type": {"alias_zh": "项目类型", "description_zh": "合成项目业务类型。"},
    "approval_status": {"alias_zh": "审批状态", "description_zh": "合成项目审批状态。"},
    "scenario_id": {"alias_zh": "方案编号", "description_zh": "项目关联的 WorldModel 方案编号。"},
    "admin9": {"alias_zh": "九位行政前缀", "description_zh": "从权属单位代码截取的九位行政区划/乡镇前缀。"},
    "qa_geometry_fixed": {"alias_zh": "几何修复标记", "description_zh": "true 表示生成时对源几何做过有效性修复或面提取。"},
    "geom_area_m2": {"alias_zh": "投影几何面积", "description_zh": "按项目投影坐标系重新计算的几何面积，单位平方米。"},
    "area_source_m2": {"alias_zh": "源属性面积", "description_zh": "源数据面积字段，优先来自 TBMJ，单位平方米。"},
    "tbmj_area_rel_error": {"alias_zh": "面积相对误差", "description_zh": "投影几何面积与源属性面积的相对误差。"},
    "qa_area_warning": {"alias_zh": "面积异常标记", "description_zh": "true 表示几何面积与源属性面积偏差超过 QA 阈值。"},
    "qa_use_for_rules": {"alias_zh": "可用于规则计算", "description_zh": "true 表示该要素通过基础质量门槛，可参与规则和合成数据生成。"},
    "control_name": {"alias_zh": "管控区名称", "description_zh": "合成管控区中文名称。"},
    "control_grade": {"alias_zh": "管控区等级", "description_zh": "合成永久基本农田保护等级。"},
    "control_area_m2": {"alias_zh": "管控区面积", "description_zh": "合成永久基本农田面对象面积，单位平方米。"},
    "source_bsm_count": {"alias_zh": "来源图斑数量", "description_zh": "合成面对象覆盖或派生自的源图斑数量。"},
    "source_bsms": {"alias_zh": "来源图斑标识集合", "description_zh": "合成对象关联的源图斑标识，多个值用竖线分隔。"},
    "source_bsms_sample": {"alias_zh": "来源图斑样例", "description_zh": "合成对象关联源图斑的截断样例。"},
    "effective_date": {"alias_zh": "生效日期", "description_zh": "合成规则或管控边界的生效日期。"},
    "redline_name": {"alias_zh": "红线区名称", "description_zh": "合成生态保护红线区中文名称。"},
    "protection_level": {"alias_zh": "保护等级", "description_zh": "合成生态保护红线保护等级。"},
    "ecological_function": {"alias_zh": "生态功能", "description_zh": "合成生态红线主要生态功能。"},
    "redline_area_m2": {"alias_zh": "红线区面积", "description_zh": "合成生态保护红线面对象面积，单位平方米。"},
    "plan_zone_id": {"alias_zh": "用途分区编号", "description_zh": "合成用途管制分区编号。"},
    "plan_zone_type": {"alias_zh": "用途分区类型", "description_zh": "合成用途管制分区类型。"},
    "plan_zone_name": {"alias_zh": "用途分区名称", "description_zh": "合成用途管制分区中文名称。"},
    "plan_rule": {"alias_zh": "用途管制规则", "description_zh": "该分区对应的合成用途准入规则。"},
    "zone_area_m2": {"alias_zh": "分区面积", "description_zh": "用途管制分区面积，单位平方米。"},
    "boundary_id": {"alias_zh": "边界编号", "description_zh": "合成城镇开发边界编号。"},
    "boundary_type": {"alias_zh": "边界类型", "description_zh": "城镇开发边界或其他边界类型。"},
    "boundary_name": {"alias_zh": "边界名称", "description_zh": "合成城镇开发边界中文名称。"},
    "boundary_area_m2": {"alias_zh": "边界面积", "description_zh": "合成城镇开发边界面积，单位平方米。"},
    "tile_id": {"alias_zh": "影像瓦片编号", "description_zh": "合成遥感影像瓦片索引编号。"},
    "modality": {"alias_zh": "模态类型", "description_zh": "数据模态，例如 remote_sensing、vector、text。"},
    "sensor": {"alias_zh": "传感器", "description_zh": "合成影像瓦片对应的传感器名称。"},
    "acquisition_date": {"alias_zh": "采集日期", "description_zh": "合成影像瓦片采集日期。"},
    "band_set": {"alias_zh": "波段组合", "description_zh": "合成影像瓦片可用波段说明。"},
    "cloud_cover_pct": {"alias_zh": "云量百分比", "description_zh": "合成影像瓦片云量百分比。"},
    "image_uri": {"alias_zh": "影像资源地址", "description_zh": "影像文件或对象存储 URI。"},
    "raster_product_id": {"alias_zh": "栅格产品编号", "description_zh": "瓦片关联的合成栅格观测产品编号。"},
    "raster_uri": {"alias_zh": "栅格资源地址", "description_zh": "瓦片关联的 GeoTIFF 栅格资源相对路径。"},
    "tile_area_m2": {"alias_zh": "瓦片覆盖面积", "description_zh": "合成遥感瓦片覆盖面积，单位平方米。"},
    "risk_scenario": {"alias_zh": "风险场景", "description_zh": "项目用于测试的规则风险场景。"},
    "review_priority": {"alias_zh": "复核优先级", "description_zh": "项目规则复核优先级。"},
    "planned_start": {"alias_zh": "计划开始日期", "description_zh": "合成项目计划开始日期。"},
    "planned_end": {"alias_zh": "计划结束日期", "description_zh": "合成项目计划结束日期。"},
    "planned_area_m2": {"alias_zh": "项目计划面积", "description_zh": "合成项目范围投影面积，单位平方米。"},
    "related_change_ids": {"alias_zh": "关联变化编号集合", "description_zh": "项目关联的年度变化编号，多个值用竖线分隔。"},
    "approval_id": {"alias_zh": "审批编号", "description_zh": "合成项目审批记录编号。"},
    "application_date": {"alias_zh": "申请日期", "description_zh": "合成项目审批申请日期。"},
    "decision_date": {"alias_zh": "决定日期", "description_zh": "合成审批决定日期。"},
    "decision_result": {"alias_zh": "审批决定", "description_zh": "批准、退回、补正或审查中等审批结果。"},
    "approved_area_m2": {"alias_zh": "批准面积", "description_zh": "合成审批批准面积，单位平方米。"},
    "reviewing_department": {"alias_zh": "审查部门", "description_zh": "合成审批或复核的责任部门。"},
    "legal_basis": {"alias_zh": "法规依据", "description_zh": "规则或审批依据的合成条款。"},
    "standard_version": {"alias_zh": "标准版本", "description_zh": "规则或字段所属标准版本。"},
    "rule_eval_id": {"alias_zh": "规则评估编号", "description_zh": "项目规则评估结果编号。"},
    "rule_id": {"alias_zh": "规则编号", "description_zh": "TWM 演示规则编号。"},
    "rule_name_zh": {"alias_zh": "规则中文名", "description_zh": "规则中文名称。"},
    "severity": {"alias_zh": "严重程度", "description_zh": "规则命中严重程度。"},
    "finding_status": {"alias_zh": "判定状态", "description_zh": "规则评估结果状态。"},
    "finding_basis": {"alias_zh": "判定依据", "description_zh": "规则命中的证据和面积依据。"},
    "metric_value": {"alias_zh": "指标值", "description_zh": "规则评估使用的数值指标。"},
    "metric_unit": {"alias_zh": "指标单位", "description_zh": "规则评估指标单位。"},
    "enforcement_id": {"alias_zh": "执法事件编号", "description_zh": "合成执法督察事件编号。"},
    "event_type": {"alias_zh": "事件类型", "description_zh": "执法、预警、复核等事件类型。"},
    "event_status": {"alias_zh": "事件状态", "description_zh": "事件办理状态。"},
    "assigned_department": {"alias_zh": "承办部门", "description_zh": "合成执法或复核任务承办部门。"},
    "review_task_id": {"alias_zh": "复核任务编号", "description_zh": "合成人工复核任务编号。"},
    "task_status": {"alias_zh": "任务状态", "description_zh": "复核任务处理状态。"},
    "reviewer_role": {"alias_zh": "复核角色", "description_zh": "复核任务责任角色。"},
    "due_date": {"alias_zh": "截止日期", "description_zh": "复核任务截止日期。"},
    "review_result": {"alias_zh": "复核结论", "description_zh": "合成人工复核结论。"},
    "snapshot_year": {"alias_zh": "快照年份", "description_zh": "状态摘要所属年份。"},
    "land_space_type": {"alias_zh": "国土空间类型", "description_zh": "地类归并后的国土空间类型。"},
    "feature_count": {"alias_zh": "要素数量", "description_zh": "摘要中的要素数量。"},
    "area_m2": {"alias_zh": "面积", "description_zh": "摘要或关系中的面积，单位平方米。"},
    "area_delta_m2": {"alias_zh": "面积变化量", "description_zh": "相对上一期的面积变化量，单位平方米。"},
    "field_name": {"alias_zh": "字段名", "description_zh": "数据标准字段英文名。"},
    "field_alias_zh": {"alias_zh": "字段中文别名", "description_zh": "数据标准字段中文显示名。"},
    "lifecycle_status": {"alias_zh": "生命周期状态", "description_zh": "标准字段或规则的生命周期状态。"},
    "introduced_version": {"alias_zh": "引入版本", "description_zh": "字段或规则首次引入的标准版本。"},
    "deprecated_version": {"alias_zh": "废止版本", "description_zh": "字段或规则废止版本。"},
    "replacement_field": {"alias_zh": "替代字段", "description_zh": "字段废止后的替代字段。"},
    "evidence_id": {"alias_zh": "证据编号", "description_zh": "多模态证据索引编号。"},
    "evidence_type": {"alias_zh": "证据类型", "description_zh": "矢量、影像、文本、标准或规则评估证据类型。"},
    "evidence_uri": {"alias_zh": "证据地址", "description_zh": "证据文件、URI 或关系表引用。"},
    "linked_object_id": {"alias_zh": "关联对象编号", "description_zh": "证据关联的项目、图斑、规则或瓦片编号。"},
    "linked_object_type": {"alias_zh": "关联对象类型", "description_zh": "证据关联对象类型。"},
    "observed_date": {"alias_zh": "观测日期", "description_zh": "证据观测或生成日期。"},
    "confidence": {"alias_zh": "置信度", "description_zh": "关系或证据置信度。"},
}


ROLE_GUIDE = {
    "parcel": "用于构建国土空间状态对象的现状图斑底板。",
    "pbf": "用于永久基本农田保护类硬约束校验。",
    "eco_redline": "用于生态保护红线触碰风险校验。",
    "admin_unit": "用于区域汇总、行政范围过滤和地图背景。",
    "annual_change": "用于模拟年度变化调查和状态转移证据。",
    "project": "用于模拟建设项目或规划调整范围。",
    "planning_zone": "用于用途准入、规划一致性和国土空间格局约束测试。",
    "urban_boundary": "用于城镇开发边界内外合规性判断。",
    "remote_sensing_tile": "用于连接影像观测、图斑和文本说明的多模态语义融合测试。",
    "raster_observation": "用于验证矢量、文本、规则和栅格观测之间的 MMFE 证据链。",
}


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _standard_contract_dir() -> Path:
    path = _repo_root() / STANDARD_CONTRACT_DIR
    return path if path.exists() else STANDARD_CONTRACT_DIR


def _merge_standard_field_aliases() -> None:
    path = _standard_contract_dir() / "one_map_field_aliases.zh.json"
    if not path.exists():
        return
    payload = json.loads(path.read_text(encoding="utf-8"))
    for field_name, alias_zh in payload.get("field_aliases", {}).items():
        FIELD_ALIASES.setdefault(
            field_name,
            {
                "alias_zh": alias_zh,
                "description_zh": f"自然资源一张图标准字段：{alias_zh}。",
            },
        )


def _normalize_code(value: Any) -> str:
    if value is None or pd.isna(value):
        return ""
    text = str(value).strip()
    if text.endswith(".0"):
        return text[:-2]
    return text


def _first_non_empty(gdf: pd.DataFrame, column: str, default: str = "") -> str:
    if column not in gdf.columns:
        return default
    values = [
        str(v).strip()
        for v in gdf[column].dropna().tolist()
        if str(v).strip() and str(v).strip().lower() != "nan"
    ]
    return values[0] if values else default


def _mode_non_empty(gdf: pd.DataFrame, column: str, default: str = "") -> str:
    if column not in gdf.columns:
        return default
    values = [_normalize_code(v) for v in gdf[column].dropna().tolist() if _normalize_code(v)]
    if not values:
        return default
    return str(pd.Series(values, dtype="object").mode().iloc[0])


def _standard_admin_context(gdf: pd.DataFrame) -> dict[str, str]:
    qsdwdm = _mode_non_empty(gdf, "QSDWDM", DEFAULT_ADMIN_PREFIX)
    qsdwmc = _first_non_empty(gdf, "QSDWMC", "璧山区演示权属单位")
    zldwdm = _mode_non_empty(gdf, "ZLDWDM", qsdwdm)
    zldwmc = _first_non_empty(gdf, "ZLDWMC", qsdwmc)
    xzqdm = (qsdwdm or DEFAULT_ADMIN_PREFIX)[:6]
    return {
        "qsdwdm": qsdwdm,
        "qsdwmc": qsdwmc,
        "zldwdm": zldwdm,
        "zldwmc": zldwmc,
        "xzqdm": xzqdm,
        "xzqmc": "璧山区" if xzqdm == "500227" else qsdwmc,
    }


def _fill_text_column(df: pd.DataFrame, column: str, values: Any) -> None:
    if isinstance(values, pd.Series):
        fill = values.reindex(df.index).astype("object")
    elif isinstance(values, list):
        fill = pd.Series(values, index=df.index, dtype="object")
    else:
        fill = pd.Series([values] * len(df), index=df.index, dtype="object")
    if column not in df.columns:
        df[column] = fill
        return
    current = df[column].astype("object")
    mask = current.isna() | (current.astype(str).str.strip() == "")
    current.loc[mask] = fill.loc[mask]
    df[column] = current


def _fill_numeric_column(df: pd.DataFrame, column: str, values: Any) -> None:
    if isinstance(values, pd.Series):
        fill = values.reindex(df.index)
    elif isinstance(values, list):
        fill = pd.Series(values, index=df.index)
    else:
        fill = pd.Series([values] * len(df), index=df.index)
    if column not in df.columns:
        df[column] = fill
        return
    current = pd.to_numeric(df[column], errors="coerce")
    mask = current.isna()
    current.loc[mask] = pd.to_numeric(fill.loc[mask], errors="coerce")
    df[column] = current


def _standard_bsm(prefix: str, index: int) -> str:
    return f"{prefix}{index + 1:014d}"[-18:]


def _compact_id(prefix: str, index: int, width: int = 8) -> str:
    return f"{prefix}{index + 1:0{width}d}"


def _date_yyyymmdd(value: Any, default: str = "20250616") -> str:
    text = str(value or "").strip()
    if len(text) >= 10 and text[4] == "-" and text[7] == "-":
        return text[:10].replace("-", "")
    if len(text) == 8 and text.isdigit():
        return text
    return default


def _planning_partition(zone_type: str) -> tuple[str, str]:
    mapping = {
        "agricultural_space": ("01", "农业生产空间"),
        "ecological_space": ("02", "生态保护空间"),
        "urban_space": ("03", "城镇建设空间"),
        "water_space": ("04", "水域保护空间"),
        "other_space": ("99", "其他国土空间"),
    }
    return mapping.get(zone_type, ("99", "其他国土空间"))


def _apply_parcel_standard_fields(gdf: gpd.GeoDataFrame, data_year: str = "2025") -> gpd.GeoDataFrame:
    out = gdf.copy()
    if out.empty:
        return out
    bsm_values = (
        out["BSM"].map(_normalize_code)
        if "BSM" in out.columns
        else pd.Series([_standard_bsm("DLTB", i) for i in range(len(out))], index=out.index)
    )
    geom_area = pd.to_numeric(out.get("geom_area_m2", pd.Series(0, index=out.index)), errors="coerce").fillna(0)
    tbmj = pd.to_numeric(out["TBMJ"], errors="coerce").fillna(geom_area) if "TBMJ" in out.columns else geom_area
    kcmj = pd.to_numeric(out["KCMJ"], errors="coerce").fillna(0) if "KCMJ" in out.columns else pd.Series(0.0, index=out.index)
    tbdlmj = (tbmj - kcmj).clip(lower=0.001)

    _fill_text_column(out, "BSM", bsm_values)
    _fill_text_column(out, "YSDM", "2001010100")
    _fill_text_column(out, "TBYBH", [_compact_id("YB", i, 6) for i in range(len(out))])
    _fill_text_column(out, "TBBH", [_compact_id("", i, 8) for i in range(len(out))])
    _fill_text_column(out, "QSXZ", "20")
    _fill_text_column(out, "KCDLBM", "")
    _fill_numeric_column(out, "KCXS", 0.0)
    _fill_numeric_column(out, "KCMJ", kcmj)
    _fill_numeric_column(out, "TBDLMJ", tbdlmj.round(3))
    _fill_text_column(out, "GDLX", "00")
    _fill_text_column(out, "GDPDJB", "00")
    _fill_text_column(out, "TBXHDM", "00")
    _fill_text_column(out, "TBXHMC", "无细化")
    _fill_text_column(out, "ZZSXDM", "00")
    _fill_text_column(out, "ZZSXMC", "未标注")
    _fill_text_column(out, "CZCSXM", "000")
    _fill_text_column(out, "SJNF", data_year)
    _fill_text_column(out, "MSSM", "00")
    _fill_text_column(out, "GXSJ", f"{data_year}0616")
    _fill_text_column(out, "BZ", "TWM工程测试字段")
    return out


def _source_tbbh_from_sample(value: Any, fallback_index: int) -> str:
    text = str(value or "").split("|")[0].strip()
    return text[-8:].zfill(8) if text else _compact_id("", fallback_index, 8)


def _land_code_series(gdf: gpd.GeoDataFrame) -> pd.Series:
    if "DLBM" not in gdf.columns:
        return pd.Series([""] * len(gdf), index=gdf.index, dtype="object")
    return gdf["DLBM"].map(_normalize_code)


def _is_farmland(gdf: gpd.GeoDataFrame) -> pd.Series:
    code = _land_code_series(gdf)
    return code.str.startswith("01") | code.isin(["011", "012", "013"])


def _is_forest(gdf: gpd.GeoDataFrame) -> pd.Series:
    return _land_code_series(gdf).str.startswith("03")


def _is_water(gdf: gpd.GeoDataFrame) -> pd.Series:
    return _land_code_series(gdf).str.startswith("11")


def _is_construction(gdf: gpd.GeoDataFrame) -> pd.Series:
    code = _land_code_series(gdf)
    return code.str.startswith("20") | code.isin(["201", "202", "203", "204", "205"])


def _safe_numeric(gdf: gpd.GeoDataFrame, column: str, default: float = 0.0) -> pd.Series:
    if column not in gdf.columns:
        return pd.Series([default] * len(gdf), index=gdf.index, dtype="float64")
    return pd.to_numeric(gdf[column], errors="coerce").fillna(default)


def _polygonal_part(geom: Any) -> Polygon | MultiPolygon | None:
    if geom is None or geom.is_empty:
        return None
    if isinstance(geom, Polygon):
        return geom
    if isinstance(geom, MultiPolygon):
        return geom
    if isinstance(geom, GeometryCollection):
        polygons: list[Polygon] = []
        for part in geom.geoms:
            if isinstance(part, Polygon):
                polygons.append(part)
            elif isinstance(part, MultiPolygon):
                polygons.extend(list(part.geoms))
        if not polygons:
            return None
        if len(polygons) == 1:
            return polygons[0]
        return MultiPolygon(polygons)
    return None


def _repair_polygonal_geometry(geom: Any) -> tuple[Polygon | MultiPolygon | None, bool]:
    if geom is None or geom.is_empty:
        return None, False
    fixed = False
    candidate = geom
    if not candidate.is_valid:
        candidate = make_valid(candidate)
        fixed = True
    polygonal = _polygonal_part(candidate)
    if polygonal is None or polygonal.is_empty:
        return None, True
    if not polygonal.is_valid:
        polygonal = make_valid(polygonal)
        fixed = True
        polygonal = _polygonal_part(polygonal)
    if polygonal is None or polygonal.is_empty:
        return None, True
    return polygonal, fixed


def _quality_annotate(
    gdf: gpd.GeoDataFrame,
    project_crs: str,
    *,
    source_area_column: str = "TBMJ",
    min_area_m2: float = 10.0,
    area_warning_threshold: float = 0.05,
    area_block_threshold: float = 0.10,
) -> gpd.GeoDataFrame:
    """Repair geometry and add explicit QA fields used by downstream synthesis."""
    out = gdf.copy()
    repaired: list[Any] = []
    fixed_flags: list[bool] = []
    for geom in out.geometry:
        fixed_geom, fixed = _repair_polygonal_geometry(geom)
        repaired.append(fixed_geom)
        fixed_flags.append(fixed)
    out["geometry"] = repaired
    out["qa_geometry_fixed"] = fixed_flags
    out = out[out.geometry.notna() & (~out.geometry.is_empty)].copy()
    if out.empty:
        out["geom_area_m2"] = []
        out["area_source_m2"] = []
        out["tbmj_area_rel_error"] = []
        out["qa_area_warning"] = []
        out["qa_use_for_rules"] = []
        return out

    projected = out.to_crs(project_crs)
    geom_area = projected.geometry.area
    source_area = _safe_numeric(out, source_area_column, 0.0)
    area_rel_error = pd.Series([0.0] * len(out), index=out.index, dtype="float64")
    valid_source_area = source_area > 0
    area_rel_error.loc[valid_source_area] = (
        (geom_area.loc[valid_source_area] - source_area.loc[valid_source_area]).abs()
        / source_area.loc[valid_source_area]
    )

    out["geom_area_m2"] = geom_area.round(3)
    out["area_source_m2"] = source_area.round(3)
    out["tbmj_area_rel_error"] = area_rel_error.round(6)
    out["qa_area_warning"] = valid_source_area & (area_rel_error > area_warning_threshold)
    out["qa_use_for_rules"] = (
        out.geometry.is_valid
        & (geom_area >= min_area_m2)
        & ((~valid_source_area) | (area_rel_error <= area_block_threshold))
    )
    return out


def _rule_ready(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    if "qa_use_for_rules" not in gdf.columns:
        return gdf.copy()
    return gdf[gdf["qa_use_for_rules"].astype(bool)].copy()


def _source_bsms(values: pd.Series, limit: int = 25) -> tuple[str, str, int]:
    normalized = [str(v) for v in values.dropna().astype(str).tolist() if str(v)]
    unique = list(dict.fromkeys(normalized))
    return "|".join(unique), "|".join(unique[:limit]), len(unique)


def _clean_projected_boundary(geom: Any, *, buffer_m: float = 0.0, simplify_m: float = 0.0) -> Any:
    if geom is None or geom.is_empty:
        return None
    candidate = geom
    if buffer_m:
        candidate = candidate.buffer(buffer_m)
    if simplify_m:
        candidate = candidate.simplify(simplify_m, preserve_topology=True)
    candidate, _ = _repair_polygonal_geometry(candidate)
    return candidate


def _connected_components_for_projected(gdf_projected: gpd.GeoDataFrame) -> dict[int, int]:
    if gdf_projected.empty:
        return {}
    parents = list(range(len(gdf_projected)))

    def find(x: int) -> int:
        while parents[x] != x:
            parents[x] = parents[parents[x]]
            x = parents[x]
        return x

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parents[rb] = ra

    sidx = gdf_projected.sindex
    for i, geom in enumerate(gdf_projected.geometry):
        for j in sidx.query(geom, predicate="intersects"):
            j = int(j)
            if j > i:
                union(i, j)

    return {i: find(i) for i in range(len(gdf_projected))}


def _component_polygons(
    source: gpd.GeoDataFrame,
    *,
    project_crs: str,
    max_components: int,
    min_component_area_m2: float,
    buffer_m: float,
    simplify_m: float,
    seed: int,
) -> list[dict[str, Any]]:
    if source.empty:
        return []
    projected = source.to_crs(project_crs).reset_index(drop=True)
    components = _connected_components_for_projected(projected)
    projected["component_id"] = [components[i] for i in range(len(projected))]
    records: list[dict[str, Any]] = []
    for component_id, group in projected.groupby("component_id"):
        geom = unary_union(list(group.geometry))
        geom = _clean_projected_boundary(geom, buffer_m=buffer_m, simplify_m=simplify_m)
        if geom is None or geom.is_empty:
            continue
        area_m2 = float(geom.area)
        if area_m2 < min_component_area_m2:
            continue
        source_rows = source.iloc[group.index]
        source_bsms, source_bsms_sample, source_bsm_count = _source_bsms(source_rows["bsm_norm"])
        records.append(
            {
                "component_id": int(component_id),
                "geometry": geom,
                "area_m2": area_m2,
                "source_bsms": source_bsms,
                "source_bsms_sample": source_bsms_sample,
                "source_bsm_count": source_bsm_count,
            }
        )
    records.sort(key=lambda x: x["area_m2"], reverse=True)
    if len(records) > max_components:
        top = records[: max_components * 2]
        rng = random.Random(seed)
        keys = []
        for i, rec in enumerate(top):
            weight = max(math.sqrt(float(rec["area_m2"])), 1.0)
            keys.append((math.log(max(rng.random(), 1e-12)) / weight, i))
        records = [top[i] for _, i in sorted(keys, reverse=True)[:max_components]]
        records.sort(key=lambda x: x["area_m2"], reverse=True)
    return records


def _area_m2(gdf: gpd.GeoDataFrame, project_crs: str) -> pd.Series:
    if gdf.empty:
        return pd.Series([], dtype="float64")
    return gdf.to_crs(project_crs).geometry.area


def _positive_overlay_records(
    left: gpd.GeoDataFrame,
    right: gpd.GeoDataFrame,
    *,
    left_id: str,
    right_id: str,
    project_crs: str,
    min_area_m2: float = 1.0,
) -> list[dict[str, Any]]:
    if left.empty or right.empty:
        return []
    lproj = left.to_crs(project_crs).reset_index(drop=True)
    rproj = right.to_crs(project_crs).reset_index(drop=True)
    joined = gpd.sjoin(
        lproj[[left_id, "geometry"]],
        rproj[[right_id, "geometry"]],
        predicate="intersects",
        how="inner",
    )
    records: list[dict[str, Any]] = []
    for idx, row in joined.iterrows():
        ridx = int(row["index_right"])
        geom_left = lproj.geometry.iloc[int(idx)]
        geom_right = rproj.geometry.iloc[ridx]
        inter = geom_left.intersection(geom_right)
        overlap_area = float(inter.area) if not inter.is_empty else 0.0
        if overlap_area <= min_area_m2:
            continue
        left_area = float(geom_left.area)
        right_area = float(geom_right.area)
        records.append(
            {
                left_id: str(row[left_id]),
                right_id: str(row[right_id]),
                "overlap_area_m2": round(overlap_area, 3),
                "overlap_ratio_left": round(overlap_area / left_area, 6) if left_area else 0.0,
                "overlap_ratio_right": round(overlap_area / right_area, 6) if right_area else 0.0,
            }
        )
    return records


def _land_space_type(code: str) -> tuple[str, str, str]:
    code = _normalize_code(code)
    if code.startswith("01") or code in {"011", "012", "013"}:
        return "agricultural_space", "农业生产空间", "严格保护耕地，建设占用需论证并落实补划。"
    if code.startswith("03"):
        return "ecological_space", "生态保护空间", "优先维护林地生态功能，限制高强度开发。"
    if code.startswith("11") or code in {"111", "113", "114", "116"}:
        return "water_space", "水域保护空间", "维护水系和水面功能，控制岸线开发。"
    if code.startswith("20") or code in {"201", "202", "203", "204", "205"}:
        return "urban_space", "城乡建设空间", "建设活动应符合城镇开发边界和规划许可。"
    return "other_space", "其他国土空间", "按现状用途和上位规划进行分类管控。"


def _prepare_gdf(path: Path, target_crs: str = "EPSG:4326") -> gpd.GeoDataFrame:
    gdf = gpd.read_file(path)
    if gdf.crs is None:
        raise ValueError(f"{path} has no CRS; cannot build TWM demo data safely")
    if str(gdf.crs) != target_crs:
        gdf = gdf.to_crs(target_crs)
    if "BSM" in gdf.columns:
        gdf["bsm_norm"] = gdf["BSM"].map(_normalize_code)
    elif "GRID_ID" in gdf.columns:
        gdf["bsm_norm"] = gdf["GRID_ID"].map(_normalize_code)
    else:
        gdf["bsm_norm"] = [str(i) for i in range(len(gdf))]
    if "QSDWDM" in gdf.columns:
        gdf["admin9"] = gdf["QSDWDM"].map(_normalize_code).str[:9]
    return gdf


def _parse_admin_prefixes(admin_prefix: str = "", admin_prefixes: str = "") -> list[str]:
    raw: list[str] = []
    if admin_prefix:
        raw.extend(admin_prefix.split(","))
    if admin_prefixes:
        raw.extend(admin_prefixes.split(","))
    prefixes = []
    for item in raw:
        prefix = item.strip()
        if prefix and prefix not in prefixes:
            prefixes.append(prefix)
    return prefixes


def _filter_admin_prefixes(gdf: gpd.GeoDataFrame, admin_prefixes: list[str]) -> gpd.GeoDataFrame:
    if not admin_prefixes:
        return gdf.copy()
    if "admin9" not in gdf.columns:
        raise ValueError("admin prefix filtering requires QSDWDM/admin9 field")
    filtered = gdf[gdf["admin9"].isin(admin_prefixes)].copy()
    if filtered.empty:
        raise ValueError(f"admin prefixes {admin_prefixes} produced no rows")
    return filtered


def _sample_indices(gdf: gpd.GeoDataFrame, count: int, seed: int) -> list[int]:
    if count <= 0 or gdf.empty:
        return []
    n = min(count, len(gdf))
    return list(gdf.sample(n=n, random_state=seed).index)


def _weighted_sample_gdf(
    gdf: gpd.GeoDataFrame,
    count: int,
    seed: int,
    weights: pd.Series,
) -> gpd.GeoDataFrame:
    if count <= 0 or gdf.empty:
        return gdf.head(0).copy()
    if count >= len(gdf):
        return gdf.copy()
    cleaned = pd.to_numeric(weights.reindex(gdf.index), errors="coerce").fillna(0.0).clip(lower=0.0)
    if float(cleaned.sum()) <= 0:
        return gdf.sample(n=count, random_state=seed).copy()
    rng = random.Random(seed)
    keys: list[tuple[float, Any]] = []
    for idx, weight in cleaned.items():
        weight = float(weight)
        if weight <= 0:
            continue
        u = max(rng.random(), 1e-12)
        keys.append((math.log(u) / weight, idx))
    if len(keys) < count:
        selected = [idx for _, idx in keys]
        remainder = gdf.drop(index=selected, errors="ignore")
        selected.extend(_sample_indices(remainder, count - len(selected), seed + 1))
        return gdf.loc[selected].copy()
    selected = [idx for _, idx in sorted(keys, reverse=True)[:count]]
    return gdf.loc[selected].copy()


def _build_parcel_sample(
    parcels: gpd.GeoDataFrame,
    changed_bsms: set[str],
    max_parcels: int,
    seed: int,
    source_dataset: Path,
    contiguous_mode: bool = False,
) -> gpd.GeoDataFrame:
    if contiguous_mode:
        sample = parcels.copy()
        if max_parcels > 0 and len(sample) > max_parcels:
            sample = sample.head(max_parcels).copy()
        sample["demo_role"] = "parcel_current"
        sample["demo_sample"] = True
        sample["synthetic"] = False
        sample["not_for_production"] = True
        sample["source_dataset"] = str(source_dataset)
        return _apply_parcel_standard_fields(sample)

    selected: set[int] = set(parcels.index[parcels["bsm_norm"].isin(changed_bsms)])

    farmland = parcels[_is_farmland(parcels)]
    forest = parcels[_is_forest(parcels)]
    water = parcels[_is_water(parcels)]
    construction = parcels[_is_construction(parcels)]
    other = parcels.drop(index=list(selected), errors="ignore")

    target_remaining = max(0, max_parcels - len(selected))
    buckets = [
        (farmland, int(target_remaining * 0.35), seed + 1),
        (forest, int(target_remaining * 0.20), seed + 2),
        (water, int(target_remaining * 0.10), seed + 3),
        (construction, int(target_remaining * 0.15), seed + 4),
        (other, target_remaining, seed + 5),
    ]
    for bucket, count, bucket_seed in buckets:
        if len(selected) >= max_parcels:
            break
        available = bucket.drop(index=list(selected), errors="ignore")
        selected.update(_sample_indices(available, min(count, max_parcels - len(selected)), bucket_seed))

    if len(selected) < max_parcels:
        available = parcels.drop(index=list(selected), errors="ignore")
        selected.update(_sample_indices(available, max_parcels - len(selected), seed + 99))

    sample = parcels.loc[sorted(selected)].copy()
    sample["demo_role"] = "parcel_current"
    sample["demo_sample"] = True
    sample["synthetic"] = False
    sample["not_for_production"] = True
    sample["source_dataset"] = str(source_dataset)
    return _apply_parcel_standard_fields(sample)


def _make_admin_units(
    parcel_sample: gpd.GeoDataFrame,
    source_dataset: Path,
    project_crs: str,
) -> gpd.GeoDataFrame:
    gdf = parcel_sample.copy()
    if "QSDWDM" in gdf.columns:
        normalized = gdf["QSDWDM"].map(_normalize_code)
        gdf["admin9"] = normalized.str[:9]
        gdf["admin12"] = normalized.str[:12]
        gdf["admin15"] = normalized.str[:15]
    else:
        gdf["admin9"] = "demo_admin"
        gdf["admin12"] = "demo_admin_village"
        gdf["admin15"] = "demo_admin_ownership"
    if "QSDWMC" in gdf.columns:
        base_name = gdf["QSDWMC"].fillna("").astype(str)
    else:
        base_name = gdf["admin9"]

    parts = []
    level_specs = [
        ("admin9", "synthetic_township", "", 1, "admin_prefix_9"),
        ("admin12", "synthetic_village", "admin9", 2, "admin_prefix_12"),
        ("admin15", "synthetic_ownership_unit", "admin12", 3, "admin_prefix_15"),
    ]
    for code_col, level, parent_col, rank, source_level in level_specs:
        temp = gdf.copy()
        temp["admin_code"] = temp[code_col]
        temp["admin_parent_code"] = temp[parent_col] if parent_col else ""
        temp["admin_name"] = base_name
        admin = temp.dissolve(
            by="admin_code",
            aggfunc={"admin_name": "first", "admin_parent_code": "first"},
            as_index=False,
        )
        admin["admin_level"] = level
        admin["admin_level_rank"] = rank
        admin["admin_source_level"] = source_level
        parts.append(admin)

    admin_all = pd.concat(parts, ignore_index=True)
    admin_all = gpd.GeoDataFrame(admin_all, geometry="geometry", crs=gdf.crs)
    admin_all = _quality_annotate(admin_all, project_crs, source_area_column="missing_source_area")
    admin_all["synthetic"] = True
    admin_all["synthetic_method"] = "dissolve_parcels_by_qsdwdm_prefix_9_12_15"
    admin_all["source_dataset"] = str(source_dataset)
    admin_all["not_for_production"] = True
    admin_all["geom_area_m2"] = _area_m2(admin_all, project_crs).round(3)
    keep = [
        "admin_code",
        "admin_name",
        "admin_parent_code",
        "admin_level",
        "admin_level_rank",
        "admin_source_level",
        "synthetic",
        "synthetic_method",
        "source_dataset",
        "not_for_production",
        "qa_geometry_fixed",
        "geom_area_m2",
        "qa_use_for_rules",
        "geometry",
    ]
    return admin_all[[c for c in keep if c in admin_all.columns]]


def _make_admin_units_from_boundaries(
    parcel_sample: gpd.GeoDataFrame,
    admin_boundaries_path: Path,
    project_crs: str,
    min_overlap_m2: float = 1000.0,
) -> gpd.GeoDataFrame:
    columns = [
        "admin_code",
        "admin_name",
        "admin_level",
        "admin_level_rank",
        "admin_source_level",
        "province_name",
        "city_name",
        "county_name",
        "township_name",
        "city_county_name",
        "province_county_name",
        "matched_admin9_values",
        "matched_parcel_count",
        "overlap_area_m2",
        "overlap_ratio_to_parcels",
        "synthetic",
        "synthetic_method",
        "source_dataset",
        "not_for_production",
        "qa_geometry_fixed",
        "geom_area_m2",
        "qa_use_for_rules",
        "geometry",
    ]
    if parcel_sample.empty or not admin_boundaries_path.exists():
        return gpd.GeoDataFrame(columns=columns, geometry="geometry", crs="EPSG:4326")

    raw = gpd.read_file(admin_boundaries_path)
    if raw.crs is None:
        raise ValueError(f"{admin_boundaries_path} has no CRS")
    admin_projected = raw.to_crs(project_crs).reset_index(drop=True)
    parcels_projected = parcel_sample.to_crs(project_crs).reset_index(drop=True)
    parcel_union = unary_union(list(parcels_projected.geometry))
    parcel_union_area = float(parcel_union.area) if parcel_union is not None and not parcel_union.is_empty else 0.0
    sidx = parcels_projected.sindex

    records = []
    for idx, row in admin_projected.iterrows():
        geom = row.geometry
        if geom is None or geom.is_empty:
            continue
        inter = geom.intersection(parcel_union)
        overlap_area = float(inter.area) if not inter.is_empty else 0.0
        if overlap_area < min_overlap_m2:
            continue
        candidate_idx = list(sidx.query(geom, predicate="intersects"))
        matched = parcels_projected.iloc[candidate_idx].copy() if candidate_idx else parcels_projected.head(0)
        positive_admin9: list[str] = []
        positive_count = 0
        if not matched.empty:
            for admin9, group in matched.groupby("admin9" if "admin9" in matched.columns else matched.index):
                area = float(group.geometry.intersection(geom).area.sum())
                if area > min_overlap_m2:
                    positive_admin9.append(str(admin9))
                    positive_count += int(len(group))
        township = str(row.get("乡", "")).strip()
        county = str(row.get("县", "")).strip()
        city = str(row.get("市", "")).strip()
        province = str(row.get("省", "")).strip()
        admin_code = f"XZ-{county}-{township}" if county or township else f"XZ-{idx:05d}"
        records.append(
            {
                "admin_code": admin_code,
                "admin_name": township or admin_code,
                "admin_level": "township",
                "admin_level_rank": 1,
                "admin_source_level": "township_boundary_file",
                "province_name": province,
                "city_name": city,
                "county_name": county,
                "township_name": township,
                "city_county_name": str(row.get("市_县", "")).strip(),
                "province_county_name": str(row.get("省_县", "")).strip(),
                "matched_admin9_values": "|".join(sorted(set(positive_admin9))),
                "matched_parcel_count": positive_count,
                "overlap_area_m2": round(overlap_area, 3),
                "overlap_ratio_to_parcels": round(overlap_area / parcel_union_area, 6) if parcel_union_area else 0.0,
                "synthetic": False,
                "synthetic_method": "",
                "source_dataset": str(admin_boundaries_path),
                "not_for_production": False,
                "geometry": geom,
            }
        )

    if not records:
        return gpd.GeoDataFrame(columns=columns, geometry="geometry", crs="EPSG:4326")
    admin = gpd.GeoDataFrame(records, geometry="geometry", crs=project_crs).to_crs("EPSG:4326")
    admin = _quality_annotate(admin, project_crs, source_area_column="missing_source_area")
    admin["synthetic"] = False
    admin["synthetic_method"] = ""
    admin["source_dataset"] = str(admin_boundaries_path)
    admin["not_for_production"] = False
    admin["geom_area_m2"] = _area_m2(admin, project_crs).round(3)
    admin["qa_use_for_rules"] = admin["qa_use_for_rules"].astype(bool)
    return admin[[c for c in columns if c in admin.columns]]


def _make_pbf(
    parcel_sample: gpd.GeoDataFrame,
    source_dataset: Path,
    project_crs: str,
    seed: int,
) -> gpd.GeoDataFrame:
    gdf = _rule_ready(parcel_sample)
    slope = _safe_numeric(gdf, "slope_mean", 0.0)
    area = _safe_numeric(gdf, "geom_area_m2", 0.0)
    pool = gdf[_is_farmland(gdf) & (slope <= 15.0) & (area >= 1000.0)].copy()
    if len(pool) > 900:
        pool = _weighted_sample_gdf(pool, 900, seed + 10, area.loc[pool.index].clip(lower=1.0))
    components = _component_polygons(
        pool,
        project_crs=project_crs,
        max_components=14,
        min_component_area_m2=8000.0,
        buffer_m=4.0,
        simplify_m=1.5,
        seed=seed + 11,
    )
    records = []
    ctx = _standard_admin_context(pool if not pool.empty else parcel_sample)
    for i, rec in enumerate(components):
        tbbh = _source_tbbh_from_sample(rec["source_bsms_sample"], i)
        area_m2 = round(float(rec["area_m2"]), 3)
        records.append(
            {
                "BSM": _standard_bsm("PBF", i),
                "YSDM": "2006010100",
                "XZQDM": ctx["xzqdm"],
                "XZQMC": ctx["xzqmc"],
                "YJJBNTTBBH": f"YJJBNT{tbbh}{i + 1:04d}"[-18:],
                "TBBH": tbbh,
                "DLBM": "0101",
                "DLMC": "水田",
                "QSXZ": "20",
                "QSDWDM": ctx["qsdwdm"],
                "QSDWMC": ctx["qsdwmc"],
                "ZLDWDM": ctx["zldwdm"],
                "ZLDWMC": ctx["zldwmc"],
                "YJJBNTTBMJ": area_m2,
                "YJJBNTMJ": area_m2,
                "SJNF": "2025",
                "BHKSSJ": "20250101",
                "BHJSSJ": "20991231",
                "WDGD": "1",
                "GDPDJB": "00",
                "KCDLBM": "",
                "KCXS": 0.0,
                "KCMJ": 0.0,
                "GDLX": "00",
                "TBXHDM": "00",
                "TBXHMC": "无细化",
                "GDZZSXDM": "00",
                "GDZZSXMC": "未标注",
                "CFZR": "TWM工程测试责任人",
                "ZRRMC": "TWM工程测试责任人",
                "SJBH": f"SJ-PBF-{i + 1:06d}",
                "SJMC": "TWM永久基本农田测试数据",
                "BZ": "TWM工程测试字段",
                "control_id": f"PBF-DEMO-{i:05d}",
                "control_name": f"合成永久基本农田保护片区{i + 1}",
                "control_type": "permanent_basic_farmland",
                "control_grade": "synthetic_priority_protection",
                "control_area_m2": area_m2,
                "source_bsm_count": rec["source_bsm_count"],
                "source_bsms_sample": rec["source_bsms_sample"],
                "effective_date": "2026-01-01",
                "synthetic": True,
                "synthetic_method": "dissolve_low_slope_farmland_components_with_boundary_generalization",
                "source_dataset": str(source_dataset),
                "not_for_production": True,
                "geometry": rec["geometry"],
            }
        )
    columns = [
        "BSM",
        "YSDM",
        "XZQDM",
        "XZQMC",
        "YJJBNTTBBH",
        "TBBH",
        "DLBM",
        "DLMC",
        "QSXZ",
        "QSDWDM",
        "QSDWMC",
        "ZLDWDM",
        "ZLDWMC",
        "YJJBNTTBMJ",
        "YJJBNTMJ",
        "SJNF",
        "BHKSSJ",
        "BHJSSJ",
        "WDGD",
        "GDPDJB",
        "KCDLBM",
        "KCXS",
        "KCMJ",
        "GDLX",
        "TBXHDM",
        "TBXHMC",
        "GDZZSXDM",
        "GDZZSXMC",
        "CFZR",
        "ZRRMC",
        "SJBH",
        "SJMC",
        "BZ",
        "control_id",
        "control_name",
        "control_type",
        "control_grade",
        "control_area_m2",
        "source_bsm_count",
        "source_bsms_sample",
        "effective_date",
        "synthetic",
        "synthetic_method",
        "source_dataset",
        "not_for_production",
        "geometry",
    ]
    if not records:
        return gpd.GeoDataFrame(columns=columns, geometry="geometry", crs="EPSG:4326")
    pbf = gpd.GeoDataFrame(records, geometry="geometry", crs=project_crs).to_crs("EPSG:4326")
    pbf = _quality_annotate(pbf, project_crs, source_area_column="control_area_m2")
    return pbf[[c for c in columns + ["qa_geometry_fixed", "geom_area_m2", "qa_use_for_rules"] if c in pbf.columns]]


def _make_eco_redline(
    parcel_sample: gpd.GeoDataFrame,
    source_dataset: Path,
    project_crs: str,
    seed: int,
) -> gpd.GeoDataFrame:
    gdf = _rule_ready(parcel_sample)
    slope = _safe_numeric(gdf, "slope_mean", 0.0)
    area = _safe_numeric(gdf, "geom_area_m2", 0.0)
    pool = gdf[(_is_forest(gdf) | _is_water(gdf) | (slope >= 25.0)) & (area >= 800.0)].copy()
    if len(pool) > 450:
        weights = (slope.loc[pool.index].clip(lower=1.0) + 1.0) * area.loc[pool.index].clip(lower=1.0).pow(0.25)
        pool = _weighted_sample_gdf(pool, 450, seed + 20, weights)
    components = _component_polygons(
        pool,
        project_crs=project_crs,
        max_components=10,
        min_component_area_m2=10000.0,
        buffer_m=22.0,
        simplify_m=3.0,
        seed=seed + 21,
    )
    functions = ["水源涵养", "水土保持", "生物多样性维护", "生态缓冲"]
    records = []
    ctx = _standard_admin_context(pool if not pool.empty else parcel_sample)
    for i, rec in enumerate(components):
        area_m2 = round(float(rec["area_m2"]), 3)
        area_km2 = round(area_m2 / 1_000_000.0, 6)
        function = functions[i % len(functions)]
        records.append(
            {
                "BSM": _standard_bsm("ECO", i),
                "YSDM": "2006030100",
                "XJXZQDM": ctx["xzqdm"],
                "XJXZQMC": ctx["xzqmc"],
                "LHLX": "陆域",
                "MJ": area_m2,
                "XJXZQHDM": ctx["xzqdm"],
                "LXDM": f"{(i % 3) + 1:02d}",
                "SLDM": f"ST{i % 4 + 1:02d}",
                "MC": f"合成生态保护红线片区{i + 1}",
                "QYMJ": area_km2,
                "SLSJ": "20250101",
                "GKCS": f"严格管控，重点维护{function}功能。",
                "RKSL": 0,
                "STGNYBHMB": function,
                "STXTYZBLX": "生态保护红线斑块",
                "RWHDLX": "无明显人为活动",
                "STHJWT": "工程测试无异常",
                "BZ": "TWM工程测试字段",
                "redline_id": f"ECO-DEMO-{i:05d}",
                "redline_name": f"合成生态保护红线片区{i + 1}",
                "zone_type": "synthetic_ecological_redline",
                "protection_level": "strict_control",
                "ecological_function": function,
                "redline_area_m2": area_m2,
                "source_bsm_count": rec["source_bsm_count"],
                "source_bsms_sample": rec["source_bsms_sample"],
                "effective_date": "2026-01-01",
                "synthetic": True,
                "synthetic_method": "dissolve_forest_water_high_slope_components_with_buffer",
                "source_dataset": str(source_dataset),
                "not_for_production": True,
                "geometry": rec["geometry"],
            }
        )
    columns = [
        "BSM",
        "YSDM",
        "XJXZQDM",
        "XJXZQMC",
        "LHLX",
        "MJ",
        "XJXZQHDM",
        "LXDM",
        "SLDM",
        "MC",
        "QYMJ",
        "SLSJ",
        "GKCS",
        "RKSL",
        "STGNYBHMB",
        "STXTYZBLX",
        "RWHDLX",
        "STHJWT",
        "BZ",
        "redline_id",
        "redline_name",
        "zone_type",
        "protection_level",
        "ecological_function",
        "redline_area_m2",
        "source_bsm_count",
        "source_bsms_sample",
        "effective_date",
        "synthetic",
        "synthetic_method",
        "source_dataset",
        "not_for_production",
        "geometry",
    ]
    if not records:
        return gpd.GeoDataFrame(columns=columns, geometry="geometry", crs="EPSG:4326")
    eco = gpd.GeoDataFrame(records, geometry="geometry", crs=project_crs).to_crs("EPSG:4326")
    eco = _quality_annotate(eco, project_crs, source_area_column="redline_area_m2")
    return eco[[c for c in columns + ["qa_geometry_fixed", "geom_area_m2", "qa_use_for_rules"] if c in eco.columns]]


def _make_planning_zones(
    parcel_sample: gpd.GeoDataFrame,
    source_dataset: Path,
    project_crs: str,
) -> gpd.GeoDataFrame:
    gdf = _rule_ready(parcel_sample).copy().reset_index(drop=True)
    if gdf.empty:
        return gpd.GeoDataFrame(
            columns=[
                "BSM",
                "YSDM",
                "XZQDM",
                "XZQMC",
                "GHFQDM",
                "GHFQMC",
                "MJ",
                "plan_zone_id",
                "plan_zone_type",
                "plan_zone_name",
                "plan_rule",
                "zone_area_m2",
                "source_bsm_count",
                "synthetic",
                "synthetic_method",
                "source_dataset",
                "not_for_production",
                "geometry",
            ],
            geometry="geometry",
            crs="EPSG:4326",
        )
    classified = gdf["DLBM"].map(lambda x: _land_space_type(x)[0])
    gdf["plan_zone_type"] = classified
    zone_names = {}
    zone_rules = {}
    for zone_type in sorted(classified.unique()):
        _, name, rule = _land_space_type(
            "011"
            if zone_type == "agricultural_space"
            else "031"
            if zone_type == "ecological_space"
            else "111"
            if zone_type == "water_space"
            else "203"
            if zone_type == "urban_space"
            else "999"
        )
        zone_names[zone_type] = name
        zone_rules[zone_type] = rule
    projected = gdf.to_crs(project_crs)
    records = []
    ctx = _standard_admin_context(gdf)
    for i, (zone_type, group) in enumerate(projected.groupby("plan_zone_type")):
        geom = _clean_projected_boundary(unary_union(list(group.geometry)), simplify_m=2.0)
        if geom is None or geom.is_empty:
            continue
        source_rows = gdf.iloc[group.index]
        _, source_bsms_sample, source_bsm_count = _source_bsms(source_rows["bsm_norm"])
        ghfqdm, ghfqmc = _planning_partition(str(zone_type))
        area_m2 = round(float(geom.area), 3)
        records.append(
            {
                "BSM": _standard_bsm("PLN", i),
                "YSDM": "2006020100",
                "XZQDM": ctx["xzqdm"],
                "XZQMC": ctx["xzqmc"],
                "GHFQDM": ghfqdm,
                "GHFQMC": ghfqmc,
                "MJ": area_m2,
                "plan_zone_id": f"PLAN-DEMO-{i:03d}",
                "plan_zone_type": zone_type,
                "plan_zone_name": zone_names.get(zone_type, zone_type),
                "plan_rule": zone_rules.get(zone_type, ""),
                "zone_area_m2": area_m2,
                "source_bsm_count": source_bsm_count,
                "source_bsms_sample": source_bsms_sample,
                "synthetic": True,
                "synthetic_method": "land_use_code_to_planning_space_dissolve",
                "source_dataset": str(source_dataset),
                "not_for_production": True,
                "geometry": geom,
            }
        )
    columns = [
        "BSM",
        "YSDM",
        "XZQDM",
        "XZQMC",
        "GHFQDM",
        "GHFQMC",
        "MJ",
        "plan_zone_id",
        "plan_zone_type",
        "plan_zone_name",
        "plan_rule",
        "zone_area_m2",
        "source_bsm_count",
        "source_bsms_sample",
        "synthetic",
        "synthetic_method",
        "source_dataset",
        "not_for_production",
        "geometry",
    ]
    if not records:
        return gpd.GeoDataFrame(columns=columns, geometry="geometry", crs="EPSG:4326")
    zones = gpd.GeoDataFrame(records, geometry="geometry", crs=project_crs).to_crs("EPSG:4326")
    zones = _quality_annotate(zones, project_crs, source_area_column="zone_area_m2")
    return zones[[c for c in columns + ["qa_geometry_fixed", "geom_area_m2", "qa_use_for_rules"] if c in zones.columns]]


def _make_urban_boundary(
    parcel_sample: gpd.GeoDataFrame,
    source_dataset: Path,
    project_crs: str,
    seed: int,
) -> gpd.GeoDataFrame:
    gdf = _rule_ready(parcel_sample)
    area = _safe_numeric(gdf, "geom_area_m2", 0.0)
    pool = gdf[_is_construction(gdf) & (area >= 300.0)].copy()
    components = _component_polygons(
        pool,
        project_crs=project_crs,
        max_components=5,
        min_component_area_m2=20000.0,
        buffer_m=45.0,
        simplify_m=5.0,
        seed=seed + 31,
    )
    records = []
    ctx = _standard_admin_context(pool if not pool.empty else parcel_sample)
    for i, rec in enumerate(components):
        area_m2 = round(float(rec["area_m2"]), 3)
        records.append(
            {
                "BSM": _standard_bsm("URB", i),
                "YSDM": "2006020200",
                "XZQDM": ctx["xzqdm"],
                "XZQMC": ctx["xzqmc"],
                "GHFQDM": "01",
                "GHFQMC": "城镇集中建设区",
                "MJ": area_m2,
                "CZMC": f"{ctx['xzqmc']}城镇开发边界片区{i + 1}",
                "XJXZQHDM": ctx["xzqdm"],
                "CZKFMJ": area_m2,
                "SLSJ": "20250101",
                "boundary_id": f"URBAN-DEMO-{i:04d}",
                "boundary_type": "synthetic_urban_development_boundary",
                "boundary_name": f"合成城镇开发边界片区{i + 1}",
                "boundary_area_m2": area_m2,
                "source_bsm_count": rec["source_bsm_count"],
                "source_bsms_sample": rec["source_bsms_sample"],
                "effective_date": "2026-01-01",
                "synthetic": True,
                "synthetic_method": "construction_land_dissolve_buffer_simplify",
                "source_dataset": str(source_dataset),
                "not_for_production": True,
                "geometry": rec["geometry"],
            }
        )
    columns = [
        "BSM",
        "YSDM",
        "XZQDM",
        "XZQMC",
        "GHFQDM",
        "GHFQMC",
        "MJ",
        "CZMC",
        "XJXZQHDM",
        "CZKFMJ",
        "SLSJ",
        "boundary_id",
        "boundary_type",
        "boundary_name",
        "boundary_area_m2",
        "source_bsm_count",
        "source_bsms_sample",
        "effective_date",
        "synthetic",
        "synthetic_method",
        "source_dataset",
        "not_for_production",
        "geometry",
    ]
    if not records:
        return gpd.GeoDataFrame(columns=columns, geometry="geometry", crs="EPSG:4326")
    urban = gpd.GeoDataFrame(records, geometry="geometry", crs=project_crs).to_crs("EPSG:4326")
    urban = _quality_annotate(urban, project_crs, source_area_column="boundary_area_m2")
    return urban[[c for c in columns + ["qa_geometry_fixed", "geom_area_m2", "qa_use_for_rules"] if c in urban.columns]]


def _make_remote_sensing_tiles(
    parcel_sample: gpd.GeoDataFrame,
    source_dataset: Path,
    project_crs: str,
    seed: int,
    dataset_id: str,
    tile_count_target: int = 12,
) -> gpd.GeoDataFrame:
    columns = [
        "tile_id",
        "modality",
        "sensor",
        "acquisition_date",
        "band_set",
        "cloud_cover_pct",
        "image_uri",
        "raster_product_id",
        "raster_uri",
        "tile_area_m2",
        "synthetic",
        "synthetic_method",
        "source_dataset",
        "not_for_production",
        "geometry",
    ]
    if parcel_sample.empty:
        return gpd.GeoDataFrame(columns=columns, geometry="geometry", crs="EPSG:4326")
    projected = parcel_sample.to_crs(project_crs)
    minx, miny, maxx, maxy = projected.total_bounds
    width = maxx - minx
    height = maxy - miny
    cols = max(2, int(math.ceil(math.sqrt(tile_count_target * width / max(height, 1.0)))))
    rows = max(2, int(math.ceil(tile_count_target / cols)))
    dx = width / cols
    dy = height / rows
    union_geom = unary_union(list(projected.geometry))
    records = []
    sensors = ["Sentinel-2 MSI", "Gaofen-2 PMS", "Synthetic UAV RGB"]
    for r in range(rows):
        for c in range(cols):
            tile_geom = box(minx + c * dx, miny + r * dy, minx + (c + 1) * dx, miny + (r + 1) * dy)
            clipped = tile_geom.intersection(union_geom)
            if clipped.is_empty or clipped.area < 5000:
                continue
            i = len(records)
            cloud = round(((seed + i * 13) % 23) + 1.5, 1)
            records.append(
                {
                    "tile_id": f"RS-DEMO-{i:04d}",
                    "modality": "remote_sensing",
                    "sensor": sensors[i % len(sensors)],
                    "acquisition_date": f"2026-0{(i % 6) + 3}-15",
                    "band_set": "synthetic-NDVI,synthetic-change-intensity",
                    "cloud_cover_pct": cloud,
                    "image_uri": f"synthetic://{dataset_id}/rasters/synthetic_ndvi_2026.tif",
                    "raster_product_id": "RASTER-NDVI-2026",
                    "raster_uri": "rasters/synthetic_ndvi_2026.tif",
                    "tile_area_m2": round(float(clipped.area), 3),
                    "synthetic": True,
                    "synthetic_method": "grid_tile_index_over_synthetic_raster_fixture",
                    "source_dataset": str(source_dataset),
                    "not_for_production": True,
                    "geometry": _clean_projected_boundary(clipped, simplify_m=1.0),
                }
            )
    if not records:
        return gpd.GeoDataFrame(columns=columns, geometry="geometry", crs="EPSG:4326")
    tiles = gpd.GeoDataFrame(records, geometry="geometry", crs=project_crs).to_crs("EPSG:4326")
    tiles = _quality_annotate(tiles, project_crs, source_area_column="tile_area_m2")
    return tiles[[c for c in columns + ["qa_geometry_fixed", "geom_area_m2", "qa_use_for_rules"] if c in tiles.columns]]


def _synthetic_ndvi_by_land_code(code: Any) -> float:
    code_text = _normalize_code(code)
    if code_text.startswith("01") or code_text in {"011", "012", "013"}:
        return 0.62
    if code_text.startswith("03"):
        return 0.78
    if code_text.startswith("11") or code_text in {"111", "113", "114", "116"}:
        return 0.18
    if code_text.startswith("20") or code_text in {"201", "202", "203", "204", "205"}:
        return 0.28
    return 0.42


def _raster_stats(array: np.ndarray, nodata: float) -> dict[str, Any]:
    valid = array[np.isfinite(array) & (array != nodata)]
    if valid.size == 0:
        return {"valid_pixels": 0, "min": None, "mean": None, "max": None}
    return {
        "valid_pixels": int(valid.size),
        "min": round(float(valid.min()), 6),
        "mean": round(float(valid.mean()), 6),
        "max": round(float(valid.max()), 6),
    }


def _write_synthetic_rasters(
    out_dir: Path,
    *,
    dataset_id: str,
    parcel_sample: gpd.GeoDataFrame,
    annual_change: gpd.GeoDataFrame,
    pbf: gpd.GeoDataFrame,
    eco: gpd.GeoDataFrame,
    project_crs: str,
    seed: int,
    raster_size: int,
) -> dict[str, Any]:
    if rasterio is None or rasterize is None or from_bounds is None:
        raise RuntimeError("rasterio is required to generate synthetic raster fixtures")
    if parcel_sample.empty:
        return {"products": {}, "warnings": ["parcel_sample is empty; no raster fixture generated"]}

    raster_dir = out_dir / "rasters"
    raster_dir.mkdir(parents=True, exist_ok=True)
    projected = parcel_sample.to_crs(project_crs).reset_index(drop=True)
    minx, miny, maxx, maxy = projected.total_bounds
    pad = max(maxx - minx, maxy - miny) * 0.015
    minx -= pad
    miny -= pad
    maxx += pad
    maxy += pad
    width = max(64, int(raster_size))
    height = max(64, int(raster_size))
    transform = from_bounds(minx, miny, maxx, maxy, width, height)
    nodata = -9999.0

    ndvi_shapes = []
    for _, row in projected.iterrows():
        slope = float(row.get("slope_mean", 0) or 0)
        base = _synthetic_ndvi_by_land_code(row.get("DLBM", ""))
        slope_penalty = min(max(slope, 0.0), 45.0) * 0.003
        ndvi_shapes.append((row.geometry, max(0.05, min(0.92, base - slope_penalty))))
    ndvi = rasterize(
        ndvi_shapes,
        out_shape=(height, width),
        transform=transform,
        fill=nodata,
        dtype="float32",
    )
    valid_mask = ndvi != nodata
    if valid_mask.any():
        rng = np.random.default_rng(seed)
        noise = rng.normal(0.0, 0.018, size=ndvi.shape).astype("float32")
        ndvi[valid_mask] = np.clip(ndvi[valid_mask] + noise[valid_mask], 0.0, 1.0)

    pbf_mask = np.zeros((height, width), dtype="float32")
    if not pbf.empty:
        pbf_mask = rasterize(
            [(geom, 0.06) for geom in pbf.to_crs(project_crs).geometry],
            out_shape=(height, width),
            transform=transform,
            fill=0.0,
            dtype="float32",
        )
    eco_mask = np.zeros((height, width), dtype="float32")
    if not eco.empty:
        eco_mask = rasterize(
            [(geom, 0.08) for geom in eco.to_crs(project_crs).geometry],
            out_shape=(height, width),
            transform=transform,
            fill=0.0,
            dtype="float32",
        )
    ndvi[valid_mask] = np.clip(ndvi[valid_mask] + pbf_mask[valid_mask] + eco_mask[valid_mask], 0.0, 1.0)

    change_intensity = np.full((height, width), nodata, dtype="float32")
    change_intensity[valid_mask] = 0.05
    if not annual_change.empty:
        change_projected = annual_change.to_crs(project_crs)
        change_shapes = []
        for _, row in change_projected.iterrows():
            from_type = _land_space_type(row.get("from_dlbm", ""))[0]
            to_type = _land_space_type(row.get("to_dlbm", ""))[0]
            value = 0.45 if from_type != to_type else 0.25
            if to_type == "urban_space":
                value = 0.8
            elif to_type == "ecological_space":
                value = 0.55
            change_shapes.append((row.geometry, value))
        if change_shapes:
            changed = rasterize(
                change_shapes,
                out_shape=(height, width),
                transform=transform,
                fill=0.0,
                dtype="float32",
            )
            change_intensity[valid_mask] = np.maximum(change_intensity[valid_mask], changed[valid_mask])

    profile = {
        "driver": "GTiff",
        "height": height,
        "width": width,
        "count": 1,
        "dtype": "float32",
        "crs": project_crs,
        "transform": transform,
        "nodata": nodata,
        "compress": "deflate",
        "predictor": 2,
    }
    products = {
        "synthetic_ndvi_2026": {
            "product_id": "RASTER-NDVI-2026",
            "filename": "synthetic_ndvi_2026.tif",
            "alias_zh": "合成NDVI观测栅格",
            "band_description_zh": "由现状地类、坡度和合成管控区派生的归一化植被指数。",
            "array": ndvi.astype("float32"),
        },
        "synthetic_change_intensity_2026": {
            "product_id": "RASTER-CHANGE-2026",
            "filename": "synthetic_change_intensity_2026.tif",
            "alias_zh": "合成变化强度栅格",
            "band_description_zh": "由 WorldModel 年度变化图斑派生的变化强度观测。",
            "array": change_intensity.astype("float32"),
        },
    }
    product_manifest: dict[str, Any] = {}
    for name, info in products.items():
        path = raster_dir / info["filename"]
        with rasterio.open(path, "w", **profile) as dst:
            dst.write(info["array"], 1)
            dst.set_band_description(1, info["band_description_zh"])
            dst.update_tags(
                dataset_id=dataset_id,
                product_id=info["product_id"],
                synthetic="true",
                not_for_production="true",
                synthetic_method="vector_semantic_fixture_rasterization",
            )
        product_manifest[name] = {
            "product_id": info["product_id"],
            "path": str(path),
            "relative_path": str(path.relative_to(out_dir)),
            "alias_zh": info["alias_zh"],
            "description_zh": info["band_description_zh"],
            "crs": project_crs,
            "width": width,
            "height": height,
            "bounds": [round(float(v), 3) for v in [minx, miny, maxx, maxy]],
            "transform": [round(float(v), 9) for v in tuple(transform)[:6]],
            "nodata": nodata,
            "dtype": "float32",
            "stats": _raster_stats(info["array"], nodata),
            "synthetic": True,
            "not_for_production": True,
            "synthetic_method": "vector_semantic_fixture_rasterization",
            "source_layers": [
                "parcel_current",
                "synthetic_annual_change",
                "synthetic_pbf",
                "synthetic_eco_redline",
            ],
        }

    payload = {
        "dataset_id": dataset_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "not_for_production": True,
        "synthetic": True,
        "products": product_manifest,
    }
    _write_json(out_dir / "raster_manifest.json", payload)
    return payload


def _changed_mask(scenario: gpd.GeoDataFrame) -> pd.Series:
    if "CHG_FLAG" in scenario.columns:
        return scenario["CHG_FLAG"].astype(str).isin(["1", "2", "true", "True"])
    if {"ORIG_DLBM", "OPT_DLBM"}.issubset(scenario.columns):
        return scenario["ORIG_DLBM"].map(_normalize_code) != scenario["OPT_DLBM"].map(_normalize_code)
    return pd.Series([False] * len(scenario), index=scenario.index)


def _make_annual_change(
    scenario: gpd.GeoDataFrame,
    source_dataset: Path,
    project_crs: str,
) -> gpd.GeoDataFrame:
    changed = scenario[_changed_mask(scenario)].copy()
    changed = _quality_annotate(changed, project_crs)
    changed["change_id"] = [f"CHG-DEMO-{i:05d}" for i in range(len(changed))]
    changed["from_dlbm"] = changed.get("ORIG_DLBM", changed.get("DLBM", "")).map(_normalize_code)
    changed["to_dlbm"] = changed.get("OPT_DLBM", "").map(_normalize_code)
    changed["change_year"] = "synthetic_2026"
    changed["change_type"] = changed.get("CHG_FLAG", "").astype(str)
    changed["synthetic"] = True
    changed["synthetic_method"] = "world_model_optimized_orig_to_opt_dlbm"
    changed["source_dataset"] = str(source_dataset)
    changed["not_for_production"] = True
    keep = [
        "change_id",
        "BSM",
        "bsm_norm",
        "from_dlbm",
        "to_dlbm",
        "change_type",
        "change_year",
        "OPT_DLBM",
        "OPT_DLMC",
        "ORIG_DLBM",
        "CHG_FLAG",
        "synthetic",
        "synthetic_method",
        "source_dataset",
        "not_for_production",
        "qa_geometry_fixed",
        "geom_area_m2",
        "area_source_m2",
        "tbmj_area_rel_error",
        "qa_area_warning",
        "qa_use_for_rules",
        "geometry",
    ]
    return changed[[c for c in keep if c in changed.columns]]


def _target_point_buffer(
    target_geom: Any,
    *,
    scenario: str,
    index: int,
    project_crs: str,
) -> Any:
    if target_geom is None or target_geom.is_empty:
        return None
    target_area = max(float(target_geom.area), 1.0)
    radius = max(28.0, min(180.0, math.sqrt(target_area / math.pi) * (0.22 + (index % 4) * 0.05)))
    if "partial" in scenario or "boundary" in scenario:
        boundary = target_geom.boundary
        if boundary is not None and not boundary.is_empty and boundary.length > 0:
            distance = ((index * 0.173) % 1.0) * boundary.length
            center = boundary.interpolate(distance)
        else:
            center = target_geom.representative_point()
        return _clean_projected_boundary(center.buffer(radius * 1.35), simplify_m=1.0)

    center = target_geom.representative_point()
    geom = center.buffer(radius)
    if "inside" in scenario or "full" in scenario:
        clipped = geom.intersection(target_geom)
        if not clipped.is_empty and clipped.area > 100:
            geom = clipped
    return _clean_projected_boundary(geom, simplify_m=1.0)


def _sample_target_geom(target: gpd.GeoDataFrame, index: int, project_crs: str) -> Any:
    if target.empty:
        return None
    projected = target.to_crs(project_crs).reset_index(drop=True)
    row = projected.iloc[index % len(projected)]
    return row.geometry


def _make_projects(
    parcel_sample: gpd.GeoDataFrame,
    annual_change: gpd.GeoDataFrame,
    pbf: gpd.GeoDataFrame,
    eco: gpd.GeoDataFrame,
    urban: gpd.GeoDataFrame,
    planning_zones: gpd.GeoDataFrame,
    source_dataset: Path,
    project_crs: str,
    seed: int,
    max_projects: int,
) -> gpd.GeoDataFrame:
    parcel_ready = _rule_ready(parcel_sample)
    parcel_projected = parcel_ready.to_crs(project_crs).reset_index(drop=True)
    all_union = unary_union(list(parcel_projected.geometry)) if not parcel_projected.empty else None
    pbf_union = unary_union(list(pbf.to_crs(project_crs).geometry)) if not pbf.empty else None
    eco_union = unary_union(list(eco.to_crs(project_crs).geometry)) if not eco.empty else None
    ctx = _standard_admin_context(parcel_sample)
    scenario_cycle = [
        ("pbf_full_overlap", "construction_expansion", "proposed", "high", pbf),
        ("pbf_partial_overlap", "rural_road", "in_review", "high", pbf),
        ("eco_partial_overlap", "tourism_facility", "supplement_required", "high", eco),
        ("eco_full_overlap", "mining_remediation", "returned", "critical", eco),
        ("urban_inside_low_risk", "public_service", "approved", "medium", urban),
        ("outside_control_low_risk", "rural_infrastructure", "approved", "low", gpd.GeoDataFrame()),
        ("planning_agricultural_conflict", "industrial_site", "proposed", "high", pbf),
        ("ecological_restoration", "ecological_restoration", "approved", "medium", eco),
    ]

    records = []
    outside_pool = parcel_projected.copy()
    if not outside_pool.empty:
        mask = pd.Series([True] * len(outside_pool), index=outside_pool.index)
        if pbf_union is not None and not pbf_union.is_empty:
            mask &= ~outside_pool.geometry.intersects(pbf_union)
        if eco_union is not None and not eco_union.is_empty:
            mask &= ~outside_pool.geometry.intersects(eco_union)
        outside_pool = outside_pool[mask].copy()
        if outside_pool.empty:
            outside_pool = parcel_projected.copy()

    for i in range(max_projects):
        risk_scenario, project_type, approval_status, review_priority, target = scenario_cycle[i % len(scenario_cycle)]
        geom = None
        if risk_scenario == "outside_control_low_risk" and not outside_pool.empty:
            seed_geom = outside_pool.iloc[(i * 17 + seed) % len(outside_pool)].geometry
            geom = _clean_projected_boundary(seed_geom.buffer(12 + (i % 4) * 8), simplify_m=1.0)
        elif risk_scenario == "planning_agricultural_conflict" and not pbf.empty:
            target_geom = _sample_target_geom(pbf, i + 11, project_crs)
            geom = _target_point_buffer(target_geom, scenario="pbf_partial_overlap", index=i, project_crs=project_crs)
        else:
            target_geom = _sample_target_geom(target, i, project_crs) if isinstance(target, gpd.GeoDataFrame) else None
            geom = _target_point_buffer(target_geom, scenario=risk_scenario, index=i, project_crs=project_crs)

        if geom is None or geom.is_empty:
            if parcel_projected.empty:
                continue
            seed_geom = parcel_projected.iloc[(i * 19 + seed) % len(parcel_projected)].geometry
            geom = _clean_projected_boundary(seed_geom.buffer(20 + (i % 5) * 5), simplify_m=1.0)
        if all_union is not None and not all_union.is_empty:
            clipped = geom.intersection(all_union.buffer(60))
            if not clipped.is_empty and clipped.area > 50:
                geom = _clean_projected_boundary(clipped, simplify_m=1.0)
        if geom is None or geom.is_empty or geom.area < 50:
            continue

        project_id = f"PRJ-DEMO-{len(records):04d}"
        area_m2 = round(float(geom.area), 3)
        project_no = len(records)
        ydmj = area_m2
        pbf_like = project_type in {"construction_expansion", "industrial_site", "rural_road"}
        eco_like = project_type in {"tourism_facility", "mining_remediation", "ecological_restoration"}
        land_use_code, land_use_name = (
            ("1001", "建设项目用地")
            if project_type in {"construction_expansion", "industrial_site", "public_service"}
            else ("1002", "交通水利用地")
            if project_type == "rural_road"
            else ("1301", "生态修复用地")
            if project_type == "ecological_restoration"
            else ("9999", "其他项目用地")
        )
        industry_code, industry_name = (
            ("E48", "土木工程建筑业")
            if project_type in {"construction_expansion", "industrial_site", "rural_road"}
            else ("N77", "生态保护和环境治理业")
            if eco_like
            else ("O80", "公共设施管理业")
        )
        records.append(
            {
                "YSDM": "3001010100",
                "XMDM": f"XMDM{project_no + 1:028d}"[-32:],
                "DZJGH": f"DZJG{project_no + 1:015d}"[-19:],
                "AJBH": f"AJ-YSXZ-2026-{project_no + 1:06d}",
                "XMMC": f"璧山世界模型合成项目{len(records) + 1:02d}",
                "SQDW": "合成项目申报单位",
                "SZXZQDM": ctx["xzqdm"],
                "SZXZQMC": ctx["xzqmc"],
                "YDMJ": ydmj,
                "ZYNYDMJ": round(ydmj * (0.65 if pbf_like else 0.25), 3),
                "ZYGDMJ": round(ydmj * (0.45 if pbf_like else 0.08), 3),
                "SJSTHXMJ": round(ydmj * (0.55 if eco_like else 0.02), 3),
                "ZYJSYDMJ": round(ydmj * (0.55 if project_type in {"construction_expansion", "industrial_site"} else 0.18), 3),
                "ZYWLDMJ": round(ydmj * 0.04, 3),
                "SQRQ": _date_yyyymmdd(f"2026-{(i % 6) + 3:02d}-01"),
                "GXRQ": "20260616",
                "XMPZLX": "建设项目用地预审与选址",
                "HYFLBM": industry_code,
                "HYFLMC": industry_name,
                "TDYTDM": land_use_code,
                "TDYTMC": land_use_name,
                "project_id": project_id,
                "project_name": f"璧山世界模型合成项目{len(records) + 1:02d}",
                "project_type": project_type,
                "approval_status": approval_status,
                "risk_scenario": risk_scenario,
                "review_priority": review_priority,
                "scenario_id": "scenario_world_model_v21_demo",
                "planned_start": f"2026-{(i % 6) + 3:02d}-01",
                "planned_end": f"2027-{(i % 6) + 3:02d}-28",
                "planned_area_m2": area_m2,
                "related_change_ids": "",
                "synthetic": True,
                "synthetic_method": "scenario_driven_project_footprints_from_control_boundaries_and_parcels",
                "source_dataset": str(source_dataset),
                "not_for_production": True,
                "geometry": geom,
            }
        )

    columns = [
        "YSDM",
        "XMDM",
        "DZJGH",
        "AJBH",
        "XMMC",
        "SQDW",
        "SZXZQDM",
        "SZXZQMC",
        "YDMJ",
        "ZYNYDMJ",
        "ZYGDMJ",
        "SJSTHXMJ",
        "ZYJSYDMJ",
        "ZYWLDMJ",
        "SQRQ",
        "GXRQ",
        "XMPZLX",
        "HYFLBM",
        "HYFLMC",
        "TDYTDM",
        "TDYTMC",
        "project_id",
        "project_name",
        "project_type",
        "approval_status",
        "risk_scenario",
        "review_priority",
        "scenario_id",
        "planned_start",
        "planned_end",
        "planned_area_m2",
        "related_change_ids",
        "synthetic",
        "synthetic_method",
        "source_dataset",
        "not_for_production",
        "geometry",
    ]
    if not records:
        return gpd.GeoDataFrame(columns=columns, geometry="geometry", crs="EPSG:4326")
    projects = gpd.GeoDataFrame(records, geometry="geometry", crs=project_crs).to_crs("EPSG:4326")
    projects = _quality_annotate(projects, project_crs, source_area_column="planned_area_m2")

    if not annual_change.empty:
        change_hits = _positive_overlay_records(
            projects,
            annual_change,
            left_id="project_id",
            right_id="change_id",
            project_crs=project_crs,
            min_area_m2=1.0,
        )
        change_map: dict[str, list[str]] = {}
        for hit in change_hits:
            change_map.setdefault(hit["project_id"], []).append(hit["change_id"])
        projects["related_change_ids"] = projects["project_id"].map(
            lambda pid: "|".join(sorted(set(change_map.get(str(pid), []))))
        )
    return projects[[c for c in columns + ["qa_geometry_fixed", "geom_area_m2", "qa_use_for_rules"] if c in projects.columns]]


def _make_overlay_relation_df(
    left: gpd.GeoDataFrame,
    right: gpd.GeoDataFrame,
    *,
    left_id: str,
    right_id: str,
    relation_type: str,
    right_role: str,
    project_crs: str,
    min_area_m2: float = 1.0,
) -> pd.DataFrame:
    records = _positive_overlay_records(
        left,
        right,
        left_id=left_id,
        right_id=right_id,
        project_crs=project_crs,
        min_area_m2=min_area_m2,
    )
    for i, row in enumerate(records):
        row["relation_id"] = f"{relation_type}-{i:06d}"
        row["relation_type"] = relation_type
        row["right_role"] = right_role
        row["confidence"] = 0.99
        row["synthetic"] = True
        row["not_for_production"] = True
    columns = [
        "relation_id",
        "relation_type",
        left_id,
        right_id,
        "right_role",
        "overlap_area_m2",
        "overlap_ratio_left",
        "overlap_ratio_right",
        "confidence",
        "synthetic",
        "not_for_production",
    ]
    return pd.DataFrame(records, columns=columns)


def _make_change_parcel_rel(
    annual_change: gpd.GeoDataFrame,
    parcel_sample: gpd.GeoDataFrame,
) -> pd.DataFrame:
    parcel_ids = set(parcel_sample["bsm_norm"].dropna().astype(str)) if "bsm_norm" in parcel_sample.columns else set()
    records = []
    for i, row in annual_change.iterrows():
        bsm = str(row.get("bsm_norm", ""))
        if bsm and bsm in parcel_ids:
            records.append(
                {
                    "relation_id": f"CHG-PARCEL-{len(records):06d}",
                    "relation_type": "CHANGE_OF_PARCEL",
                    "change_id": row.get("change_id", ""),
                    "bsm_norm": bsm,
                    "match_type": "exact_bsm_norm",
                    "confidence": 1.0,
                    "synthetic": True,
                    "not_for_production": True,
                }
            )
    return pd.DataFrame(records)


def _make_rule_eval_table(
    *,
    projects: gpd.GeoDataFrame,
    pbf_rel: pd.DataFrame,
    eco_rel: pd.DataFrame,
    planning_rel: pd.DataFrame,
    urban_rel: pd.DataFrame,
) -> pd.DataFrame:
    records = []
    pbf_area = pbf_rel.groupby("project_id")["overlap_area_m2"].sum().to_dict() if not pbf_rel.empty else {}
    eco_area = eco_rel.groupby("project_id")["overlap_area_m2"].sum().to_dict() if not eco_rel.empty else {}
    planning_area = planning_rel.groupby("project_id")["overlap_area_m2"].sum().to_dict() if not planning_rel.empty else {}
    urban_projects = set(urban_rel["project_id"].astype(str)) if not urban_rel.empty else set()
    for _, project in projects.iterrows():
        project_id = str(project.get("project_id", ""))
        project_type = str(project.get("project_type", ""))
        planned_area = float(project.get("planned_area_m2", 0) or 0)
        scenarios = [
            ("TWM-FARM-001", "永久基本农田占用审查", pbf_area.get(project_id, 0.0), "m2", "high"),
            ("TWM-ECO-001", "生态保护红线触碰审查", eco_area.get(project_id, 0.0), "m2", "critical"),
            (
                "TWM-PLAN-001",
                "用途管制分区一致性审查",
                planning_area.get(project_id, 0.0),
                "m2",
                "medium",
            ),
            (
                "TWM-URBAN-001",
                "城镇开发边界内外审查",
                1.0 if project_id not in urban_projects and project_type in {"construction_expansion", "industrial_site"} else 0.0,
                "boolean",
                "medium",
            ),
        ]
        for rule_id, rule_name, value, unit, severity in scenarios:
            hit = value > 1.0 if unit == "m2" else value > 0.0
            if rule_id == "TWM-PLAN-001":
                hit = project_type in {"industrial_site", "construction_expansion"} and value > planned_area * 0.2
            status = "hit_requires_review" if hit else "pass"
            records.append(
                {
                    "rule_eval_id": f"RULE-EVAL-{len(records):06d}",
                    "project_id": project_id,
                    "rule_id": rule_id,
                    "rule_name_zh": rule_name,
                    "severity": severity if hit else "info",
                    "finding_status": status,
                    "finding_basis": (
                        f"{rule_name} metric={round(float(value), 3)} {unit}; "
                        f"project_area={round(planned_area, 3)} m2"
                    ),
                    "metric_value": round(float(value), 3),
                    "metric_unit": unit,
                    "standard_version": "0.2-demo-release",
                    "legal_basis": "TWM演示规则库-工程测试条款",
                    "event_date": "2026-06-15",
                    "synthetic": True,
                    "not_for_production": True,
                }
            )
    return pd.DataFrame(records)


def _make_approval_table(projects: gpd.GeoDataFrame, rule_eval: pd.DataFrame) -> pd.DataFrame:
    hit_counts = (
        rule_eval[rule_eval["finding_status"] == "hit_requires_review"]
        .groupby("project_id")["rule_eval_id"]
        .count()
        .to_dict()
        if not rule_eval.empty
        else {}
    )
    records = []
    for i, row in projects.iterrows():
        project_id = str(row.get("project_id", ""))
        status = str(row.get("approval_status", "proposed"))
        hits = int(hit_counts.get(project_id, 0))
        if status == "approved" and hits == 0:
            decision = "approved"
        elif status == "approved" and hits > 0:
            decision = "approved_with_conditions"
        elif status == "returned":
            decision = "returned"
        elif status == "supplement_required":
            decision = "supplement_required"
        else:
            decision = "in_review"
        planned_area = float(row.get("planned_area_m2", 0) or 0)
        approved_area = planned_area if decision.startswith("approved") else 0.0
        admin_code = str(row.get("SZXZQDM", DEFAULT_ADMIN_PREFIX[:6]))
        admin_name = str(row.get("SZXZQMC", "璧山区"))
        farmland_area = float(row.get("ZYNYDMJ", 0) or 0)
        cultivated_area = float(row.get("ZYGDMJ", 0) or 0)
        records.append(
            {
                "YSDM": "3002010100",
                "DKBH": f"DK-{i + 1:06d}",
                "DKMC": f"{row.get('project_name', project_id)}审批地块",
                "DKMJ": round(planned_area, 3),
                "DKXZQDM": admin_code,
                "DKXZQMC": admin_name,
                "DKYTDM": "1001",
                "DKYTMC": "建设项目用地",
                "DKZT": decision,
                "DZJGH": row.get("DZJGH", f"DZJG{i + 1:015d}"[-19:]),
                "AJBH": row.get("AJBH", f"AJ-YSXZ-2026-{i + 1:06d}"),
                "XZQDM": admin_code,
                "XZQMC": admin_name,
                "ZYZMJ": round(planned_area, 3),
                "ZDZMJ": round(approved_area, 3),
                "QZNYDMJ": round(farmland_area, 3),
                "QZGDMJ": round(cultivated_area, 3),
                "XZYDZMJ": round(max(planned_area - approved_area, 0.0), 3),
                "approval_id": f"APR-DEMO-{i:05d}",
                "project_id": project_id,
                "application_date": row.get("planned_start", "2026-03-01"),
                "decision_date": f"2026-{(i % 6) + 4:02d}-20",
                "approval_status": status,
                "decision_result": decision,
                "approved_area_m2": round(approved_area, 3),
                "reviewing_department": "合成自然资源审查科",
                "legal_basis": "TWM演示规则库-工程测试条款",
                "standard_version": "0.2-demo-release",
                "synthetic": True,
                "not_for_production": True,
            }
        )
    return pd.DataFrame(records)


def _make_enforcement_table(projects: gpd.GeoDataFrame, rule_eval: pd.DataFrame) -> pd.DataFrame:
    hit_eval = rule_eval[rule_eval["finding_status"] == "hit_requires_review"].copy()
    if hit_eval.empty:
        return pd.DataFrame(
            columns=[
                "BSM",
                "YSDM",
                "WFXWZJ",
                "WFDKXH",
                "YGTBZJ",
                "XZQDM",
                "JCSDQ",
                "JCSDH",
                "JCMJ",
                "TDZL",
                "TBLX",
                "ND",
                "QSSJ",
                "ZZSJ",
                "GXZT",
                "enforcement_id",
                "project_id",
                "rule_eval_id",
                "event_type",
                "event_date",
                "event_status",
                "severity",
                "assigned_department",
                "synthetic",
                "not_for_production",
            ]
        )
    project_priority = projects.set_index("project_id")["review_priority"].astype(str).to_dict()
    project_meta = projects.set_index("project_id").to_dict("index") if "project_id" in projects.columns else {}
    records = []
    for _, row in hit_eval.iterrows():
        project_id = str(row["project_id"])
        priority = project_priority.get(project_id, "medium")
        if row["severity"] in {"critical", "high"} or priority in {"critical", "high"}:
            meta = project_meta.get(project_id, {})
            i = len(records)
            records.append(
                {
                    "BSM": _standard_bsm("WFD", i),
                    "YSDM": "4001010100",
                    "WFXWZJ": f"WFXWZJ-2026-{i + 1:06d}",
                    "WFDKXH": f"WFDK-{i + 1:06d}",
                    "YGTBZJ": f"YGTB-2026-{i + 1:06d}",
                    "XZQDM": str(meta.get("SZXZQDM", DEFAULT_ADMIN_PREFIX[:6])),
                    "JCSDQ": "20260601",
                    "JCSDH": "20260630",
                    "JCMJ": round(float(row.get("metric_value", 0) or meta.get("planned_area_m2", 0) or 0), 3),
                    "TDZL": str(meta.get("SZXZQMC", "璧山区")),
                    "TBLX": "疑似违法建设用地图斑",
                    "ND": "2026",
                    "QSSJ": "20260620",
                    "ZZSJ": "20260720",
                    "GXZT": "新增",
                    "enforcement_id": f"ENF-DEMO-{len(records):05d}",
                    "project_id": project_id,
                    "rule_eval_id": row["rule_eval_id"],
                    "event_type": "synthetic_rule_alert",
                    "event_date": "2026-06-20",
                    "event_status": "pending_field_review",
                    "severity": row["severity"],
                    "assigned_department": "合成执法督察组",
                    "synthetic": True,
                    "not_for_production": True,
                }
            )
    return pd.DataFrame(records)


def _make_review_task_table(enforcement: pd.DataFrame) -> pd.DataFrame:
    records = []
    for i, row in enforcement.iterrows():
        severity = str(row.get("severity", "medium"))
        result = "suspected_violation_confirmed" if severity == "critical" else "requires_supplementary_evidence"
        records.append(
            {
                "review_task_id": f"REV-DEMO-{i:05d}",
                "enforcement_id": row.get("enforcement_id", ""),
                "project_id": row.get("project_id", ""),
                "rule_eval_id": row.get("rule_eval_id", ""),
                "task_status": "open" if i % 3 else "completed",
                "reviewer_role": "county_natural_resource_reviewer",
                "due_date": f"2026-07-{(i % 20) + 5:02d}",
                "review_result": result if i % 3 == 0 else "pending",
                "synthetic": True,
                "not_for_production": True,
            }
        )
    return pd.DataFrame(records)


def _make_state_snapshots(parcel_sample: gpd.GeoDataFrame, annual_change: gpd.GeoDataFrame) -> pd.DataFrame:
    rows = []
    base = parcel_sample.copy()
    base["land_space_type"] = base["DLBM"].map(lambda x: _land_space_type(x)[0])
    for zone_type, group in base.groupby("land_space_type"):
        area = float(pd.to_numeric(group.get("geom_area_m2", 0), errors="coerce").fillna(0).sum())
        rows.append(
            {
                "snapshot_year": 2025,
                "temporal_stage": "baseline_current",
                "land_space_type": zone_type,
                "feature_count": int(len(group)),
                "area_m2": round(area, 3),
                "area_delta_m2": 0.0,
                "source_dataset": "parcel_current",
                "synthetic": False,
                "not_for_production": True,
            }
        )

    delta_by_type: dict[str, float] = {}
    for _, row in annual_change.iterrows():
        from_type = _land_space_type(row.get("from_dlbm", ""))[0]
        to_type = _land_space_type(row.get("to_dlbm", ""))[0]
        area = float(row.get("geom_area_m2", 0) or 0)
        delta_by_type[from_type] = delta_by_type.get(from_type, 0.0) - area
        delta_by_type[to_type] = delta_by_type.get(to_type, 0.0) + area
    base_area = {row["land_space_type"]: float(row["area_m2"]) for row in rows}
    for zone_type in sorted(set(base_area) | set(delta_by_type)):
        delta = delta_by_type.get(zone_type, 0.0)
        rows.append(
            {
                "snapshot_year": 2026,
                "temporal_stage": "scenario_after_world_model",
                "land_space_type": zone_type,
                "feature_count": int(base[base["land_space_type"] == zone_type].shape[0]),
                "area_m2": round(base_area.get(zone_type, 0.0) + delta, 3),
                "area_delta_m2": round(delta, 3),
                "source_dataset": "synthetic_annual_change",
                "synthetic": True,
                "not_for_production": True,
            }
        )
    return pd.DataFrame(rows)


def _make_standard_field_catalog() -> pd.DataFrame:
    rows = []
    for field_name, meta in sorted(FIELD_ALIASES.items()):
        rows.append(
            {
                "field_name": field_name,
                "field_alias_zh": meta.get("alias_zh", field_name),
                "lifecycle_status": "active",
                "introduced_version": "0.2-demo-release",
                "deprecated_version": "",
                "replacement_field": "",
                "standard_version": "0.2-demo-release",
                "synthetic": True,
                "not_for_production": True,
            }
        )
    rows.append(
        {
            "field_name": "legacy_area",
            "field_alias_zh": "旧版面积字段",
            "lifecycle_status": "deprecated",
            "introduced_version": "0.1-draft",
            "deprecated_version": "0.2-demo-release",
            "replacement_field": "geom_area_m2",
            "standard_version": "0.2-demo-release",
            "synthetic": True,
            "not_for_production": True,
        }
    )
    return pd.DataFrame(rows)


def _make_metadata_vector_table(
    layers: dict[str, dict[str, Any]],
    *,
    dataset_id: str,
    project_crs: str,
) -> pd.DataFrame:
    rows = []
    for i, (role, info) in enumerate(sorted(layers.items())):
        columns = info.get("columns", [])
        geom_types = info.get("geometry_types", [])
        layer_crs = str(info.get("crs") or project_crs)
        layer_wkid = layer_crs.replace("EPSG:", "") if layer_crs.startswith("EPSG:") else layer_crs
        coordinate_unit = "度" if layer_crs == "EPSG:4326" else "米"
        rows.append(
            {
                "data_id": f"META-{dataset_id}-{i + 1:04d}",
                "resource_id": f"{dataset_id}:{role}",
                "data_name": Path(str(info.get("path", role))).name,
                "data_alias": info.get("alias_zh", role),
                "data_des": info.get("description_zh", ""),
                "data_format": "GeoJSON",
                "data_type": "vector",
                "data_size": "",
                "cover_range_coor": json.dumps(info.get("bounds", []), ensure_ascii=False),
                "cover_range": "演示区范围",
                "security_order": "内部",
                "is_multilayer": "0",
                "layer_count": 1,
                "layer_name": role,
                "layer_field": ",".join(columns),
                "geometry_type": ",".join(geom_types) or "面要素",
                "is_shareable": "否",
                "share_type": "",
                "is_opentosociety": "否",
                "receive_mode": "script",
                "receive_batch": "20260616",
                "import_time": "20260616",
                "wkid": layer_wkid,
                "geodetic_datum": "WGS_1984/UTM",
                "projection": layer_crs,
                "coordinate_unit": coordinate_unit,
                "product_date": "20260616",
                "update_date": "20260616",
                "update_cycle": "按需",
                "release_date": "",
                "producer": "GIS Data Agent TWM test-data generator",
                "pro_unit_name": "GIS Data Agent",
                "source_type": "合成/公开数据工程测试",
                "source_currency": "202606",
                "integrity": "符合",
                "score": 85,
                "quality_check_date": "20260616",
                "check_unit_name": "TWM QA gate",
                "quality_evaluation": "良",
                "quality_des": "工程测试数据，已通过基础几何、关系、标准字段契约检查；不代表生产权威质量。",
                "synthetic": bool(role.startswith("synthetic_")),
                "not_for_production": True,
            }
        )
    return pd.DataFrame(rows)


def _make_multimodal_evidence_index(
    *,
    projects: gpd.GeoDataFrame,
    rs_tiles: gpd.GeoDataFrame,
    rule_eval: pd.DataFrame,
    project_documents: dict[str, Any],
    standard_rules: dict[str, Any],
    raster_manifest: dict[str, Any],
) -> pd.DataFrame:
    records = []
    for _, project in projects.iterrows():
        project_id = str(project.get("project_id", ""))
        records.append(
            {
                "evidence_id": f"EVD-DEMO-{len(records):06d}",
                "evidence_type": "text_project_document",
                "evidence_uri": project_documents.get("path", ""),
                "linked_object_id": project_id,
                "linked_object_type": "project",
                "observed_date": project.get("planned_start", "2026-03-01"),
                "confidence": 0.92,
                "synthetic": True,
                "not_for_production": True,
            }
        )
    for _, tile in rs_tiles.iterrows():
        records.append(
            {
                "evidence_id": f"EVD-DEMO-{len(records):06d}",
                "evidence_type": "remote_sensing_tile_index",
                "evidence_uri": tile.get("image_uri", ""),
                "linked_object_id": tile.get("tile_id", ""),
                "linked_object_type": "remote_sensing_tile",
                "observed_date": tile.get("acquisition_date", ""),
                "confidence": 0.75,
                "synthetic": True,
                "not_for_production": True,
            }
        )
    for product in raster_manifest.get("products", {}).values():
        records.append(
            {
                "evidence_id": f"EVD-DEMO-{len(records):06d}",
                "evidence_type": "raster_observation",
                "evidence_uri": product.get("relative_path", product.get("path", "")),
                "linked_object_id": product.get("product_id", ""),
                "linked_object_type": "raster_product",
                "observed_date": "2026-06-15",
                "confidence": 0.78,
                "synthetic": True,
                "not_for_production": True,
            }
        )
    for _, rule in rule_eval[rule_eval["finding_status"] == "hit_requires_review"].iterrows():
        records.append(
            {
                "evidence_id": f"EVD-DEMO-{len(records):06d}",
                "evidence_type": "rule_evaluation",
                "evidence_uri": "tables/rule_evaluation.csv",
                "linked_object_id": rule.get("rule_eval_id", ""),
                "linked_object_type": "rule_eval",
                "observed_date": rule.get("event_date", ""),
                "confidence": 0.99,
                "synthetic": True,
                "not_for_production": True,
            }
        )
    records.append(
        {
            "evidence_id": f"EVD-DEMO-{len(records):06d}",
            "evidence_type": "standard_rule_lifecycle",
            "evidence_uri": standard_rules.get("path", ""),
            "linked_object_id": "TWM-STD-BASE-2026",
            "linked_object_type": "standard",
            "observed_date": "2026-06-15",
            "confidence": 0.95,
            "synthetic": True,
            "not_for_production": True,
        }
    )
    return pd.DataFrame(records)


def _write_domain_tables(
    out_dir: Path,
    *,
    parcel_sample: gpd.GeoDataFrame,
    annual_change: gpd.GeoDataFrame,
    projects: gpd.GeoDataFrame,
    layers: dict[str, dict[str, Any]],
    dataset_id: str,
    project_crs: str,
    relation_tables: dict[str, dict[str, Any]],
    standard_rules: dict[str, Any],
    project_documents: dict[str, Any],
    rs_tiles: gpd.GeoDataFrame,
    raster_manifest: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    tables_dir = out_dir / "tables"
    tables_dir.mkdir(parents=True, exist_ok=True)

    def load_relation(name: str) -> pd.DataFrame:
        path = relation_tables.get(name, {}).get("path", "")
        if not path:
            return pd.DataFrame()
        return pd.read_csv(path)

    rule_eval = _make_rule_eval_table(
        projects=projects,
        pbf_rel=load_relation("project_pbf_rel"),
        eco_rel=load_relation("project_eco_rel"),
        planning_rel=load_relation("project_planning_rel"),
        urban_rel=load_relation("project_urban_boundary_rel"),
    )
    approval = _make_approval_table(projects, rule_eval)
    enforcement = _make_enforcement_table(projects, rule_eval)
    review_task = _make_review_task_table(enforcement)
    state_snapshot = _make_state_snapshots(parcel_sample, annual_change)
    field_catalog = _make_standard_field_catalog()
    metadata_vector = _make_metadata_vector_table(layers, dataset_id=dataset_id, project_crs=project_crs)
    evidence = _make_multimodal_evidence_index(
        projects=projects,
        rs_tiles=rs_tiles,
        rule_eval=rule_eval,
        project_documents=project_documents,
        standard_rules=standard_rules,
        raster_manifest=raster_manifest,
    )
    tables = {
        "rule_evaluation": rule_eval,
        "approval_records": approval,
        "enforcement_events": enforcement,
        "review_tasks": review_task,
        "state_snapshots": state_snapshot,
        "standard_field_catalog": field_catalog,
        "metadata_vector": metadata_vector,
        "multimodal_evidence_index": evidence,
    }
    manifest: dict[str, dict[str, Any]] = {}
    for name, df in tables.items():
        path = tables_dir / f"{name}.csv"
        df.to_csv(path, index=False)
        manifest[name] = {"path": str(path), "rows": int(len(df)), "columns": list(df.columns)}
    return manifest


def _write_relation_tables(
    out_dir: Path,
    *,
    parcel_sample: gpd.GeoDataFrame,
    annual_change: gpd.GeoDataFrame,
    projects: gpd.GeoDataFrame,
    pbf: gpd.GeoDataFrame,
    eco: gpd.GeoDataFrame,
    planning_zones: gpd.GeoDataFrame,
    urban: gpd.GeoDataFrame,
    rs_tiles: gpd.GeoDataFrame,
    project_crs: str,
) -> dict[str, dict[str, Any]]:
    relation_dir = out_dir / "relations"
    relation_dir.mkdir(parents=True, exist_ok=True)
    tables = {
        "change_parcel_rel": _make_change_parcel_rel(annual_change, parcel_sample),
        "project_parcel_rel": _make_overlay_relation_df(
            projects,
            parcel_sample,
            left_id="project_id",
            right_id="bsm_norm",
            relation_type="PROJECT_OVERLAPS_PARCEL",
            right_role="parcel",
            project_crs=project_crs,
        ),
        "project_pbf_rel": _make_overlay_relation_df(
            projects,
            pbf,
            left_id="project_id",
            right_id="control_id",
            relation_type="PROJECT_OVERLAPS_PBF",
            right_role="pbf",
            project_crs=project_crs,
        ),
        "project_eco_rel": _make_overlay_relation_df(
            projects,
            eco,
            left_id="project_id",
            right_id="redline_id",
            relation_type="PROJECT_OVERLAPS_ECO_REDLINE",
            right_role="eco_redline",
            project_crs=project_crs,
        ),
        "project_planning_rel": _make_overlay_relation_df(
            projects,
            planning_zones,
            left_id="project_id",
            right_id="plan_zone_id",
            relation_type="PROJECT_OVERLAPS_PLANNING_ZONE",
            right_role="planning_zone",
            project_crs=project_crs,
        ),
        "project_urban_boundary_rel": _make_overlay_relation_df(
            projects,
            urban,
            left_id="project_id",
            right_id="boundary_id",
            relation_type="PROJECT_OVERLAPS_URBAN_BOUNDARY",
            right_role="urban_boundary",
            project_crs=project_crs,
        ),
        "project_rs_tile_rel": _make_overlay_relation_df(
            projects,
            rs_tiles,
            left_id="project_id",
            right_id="tile_id",
            relation_type="PROJECT_OBSERVED_BY_RS_TILE",
            right_role="remote_sensing_tile",
            project_crs=project_crs,
        ),
    }
    manifest: dict[str, dict[str, Any]] = {}
    for name, df in tables.items():
        path = relation_dir / f"{name}.csv"
        df.to_csv(path, index=False)
        manifest[name] = {
            "path": str(path),
            "rows": int(len(df)),
            "columns": list(df.columns),
        }
    return manifest


def _write_standard_rules(out_dir: Path) -> dict[str, Any]:
    rules = {
        "dataset": "twm_standard_rules_demo",
        "version": "2026-06-16-demo",
        "not_for_production": True,
        "lifecycle": [
            {
                "standard_id": "TWM-STD-BASE-2026",
                "standard_name_zh": "国土空间世界模型演示数据标准",
                "version": "0.1-draft",
                "status": "draft",
                "effective_date": "2026-01-01",
                "supersedes": "",
            },
            {
                "standard_id": "TWM-STD-BASE-2026",
                "standard_name_zh": "国土空间世界模型演示数据标准",
                "version": "0.2-demo-release",
                "status": "released_for_engineering_test",
                "effective_date": "2026-06-15",
                "supersedes": "0.1-draft",
            },
            {
                "standard_id": "TWM-STD-BASE-2026",
                "standard_name_zh": "国土空间世界模型演示数据标准",
                "version": "0.3-governance-loop",
                "status": "released_for_engineering_test",
                "effective_date": "2026-06-16",
                "supersedes": "0.2-demo-release",
            },
        ],
        "rules": [
            {
                "rule_id": "TWM-FARM-001",
                "rule_name_zh": "永久基本农田占用审查",
                "target_layer": "synthetic_projects",
                "constraint_layer": "synthetic_pbf",
                "logic": "flag if project_pbf_rel.overlap_area_m2 > 1",
                "severity": "high",
            },
            {
                "rule_id": "TWM-ECO-001",
                "rule_name_zh": "生态保护红线触碰审查",
                "target_layer": "synthetic_projects",
                "constraint_layer": "synthetic_eco_redline",
                "logic": "flag if project_eco_rel.overlap_area_m2 > 1",
                "severity": "critical",
            },
            {
                "rule_id": "TWM-PLAN-001",
                "rule_name_zh": "用途管制分区一致性审查",
                "target_layer": "synthetic_projects",
                "constraint_layer": "synthetic_planning_zones",
                "logic": "compare project_type with dominant plan_zone_type",
                "severity": "medium",
            },
            {
                "rule_id": "TWM-URBAN-001",
                "rule_name_zh": "城镇开发边界内外审查",
                "target_layer": "synthetic_projects",
                "constraint_layer": "synthetic_urban_boundary",
                "logic": "flag construction projects outside urban boundary for review",
                "severity": "medium",
            },
            {
                "rule_id": "TWM-DQ-001",
                "rule_name_zh": "空间数据质量门槛",
                "target_layer": "all_vector_layers",
                "constraint_layer": "",
                "logic": "invalid geometries must be zero and rule input features must pass qa_use_for_rules",
                "severity": "blocking",
            },
            {
                "rule_id": "TWM-GOV-001",
                "rule_name_zh": "规则命中项目审批一致性审查",
                "target_layer": "approval_records",
                "constraint_layer": "rule_evaluation",
                "logic": "high or critical rule hits require in_review, returned, supplement_required, or conditional approval",
                "severity": "high",
            },
            {
                "rule_id": "TWM-EVD-001",
                "rule_name_zh": "多模态证据完整性审查",
                "target_layer": "synthetic_projects",
                "constraint_layer": "multimodal_evidence_index",
                "logic": "each project should have text evidence and at least one remote sensing tile relation",
                "severity": "medium",
            },
        ],
    }
    path = out_dir / "standard_rules.lifecycle.json"
    _write_json(path, rules)
    return {"path": str(path), "rules": len(rules["rules"]), "lifecycle_versions": len(rules["lifecycle"])}


def _write_standard_contract_bundle(out_dir: Path) -> dict[str, Any]:
    source_dir = _standard_contract_dir()
    target_dir = out_dir / "standards"
    target_dir.mkdir(parents=True, exist_ok=True)
    manifest: dict[str, Any] = {
        "standard_id": "NR_ONE_MAP_TWM_CORE_2026",
        "source_dir": str(source_dir),
        "files": {},
    }
    for filename in STANDARD_CONTRACT_FILES:
        src = source_dir / filename
        dst = target_dir / filename
        if src.exists():
            shutil.copyfile(src, dst)
            manifest["files"][filename] = {"path": str(dst), "exists": True}
        else:
            manifest["files"][filename] = {"path": str(dst), "exists": False}
    return manifest


def _write_project_documents(out_dir: Path, projects: gpd.GeoDataFrame) -> dict[str, Any]:
    docs_dir = out_dir / "documents"
    docs_dir.mkdir(parents=True, exist_ok=True)
    path = docs_dir / "project_documents.zh.jsonl"
    lines = []
    for _, row in projects.iterrows():
        text = (
            f"{row.get('project_name')}，项目编号{row.get('project_id')}，类型为{row.get('project_type')}，"
            f"审批状态为{row.get('approval_status')}。该项目用于测试{row.get('risk_scenario')}场景，"
            f"计划面积约{row.get('planned_area_m2')}平方米，复核优先级为{row.get('review_priority')}。"
            "本材料为合成文本，仅用于多模态语义融合和规则解释链路验证。"
        )
        lines.append(
            json.dumps(
                {
                    "document_id": f"DOC-{row.get('project_id')}",
                    "project_id": row.get("project_id"),
                    "doc_type": "synthetic_project_application",
                    "title_zh": f"{row.get('project_name')}用地审查材料",
                    "text_zh": text,
                    "synthetic": True,
                    "not_for_production": True,
                },
                ensure_ascii=False,
            )
        )
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    return {"path": str(path), "rows": len(lines), "format": "jsonl"}


def _write_layer(gdf: gpd.GeoDataFrame, path: Path) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    gdf.to_file(path, driver="GeoJSON")
    return {
        "path": str(path),
        "alias_zh": LAYER_ALIASES.get(path.stem, {}).get("alias_zh", path.stem),
        "description_zh": LAYER_ALIASES.get(path.stem, {}).get("description_zh", ""),
        "rows": int(len(gdf)),
        "crs": str(gdf.crs),
        "geometry_types": sorted(map(str, gdf.geom_type.dropna().unique().tolist())),
        "columns": [c for c in gdf.columns if c != "geometry"],
        "field_aliases_zh": {
            c: FIELD_ALIASES[c]["alias_zh"]
            for c in gdf.columns
            if c != "geometry" and c in FIELD_ALIASES
        },
        "bounds": [round(float(x), 6) for x in gdf.total_bounds] if len(gdf) else None,
    }


def _semantic_manifest(
    *,
    output_path: Path,
    source_path: Path,
    row_count: int,
    columns: list[str],
    role: str,
    mappings: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "product_type": "semantic_fusion_product",
        "version": "1.0-demo-wrapper",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "business_output": {
            "path": str(output_path),
            "format": "GeoJSON",
            "row_count": row_count,
            "column_count": len(columns),
            "crs": "EPSG:4326",
        },
        "sources": [
            {
                "path": str(source_path),
                "data_type": "vector",
                "row_count": row_count,
                "semantic_domain": role,
            }
        ],
        "semantic_mappings": mappings,
        "derived_fields": [],
        "inferred_fields": [],
        "feature_semantics": [],
        "ai_metadata": {
            "retrieval_text": (
                f"Demo semantic wrapper for TWM role {role}; generated from local data."
            ),
            "chunks": [],
            "embedding_ready": False,
            "recommended_vector_targets": ["pgvector"],
        },
        "quality": {
            "score": 0.85,
            "warnings": [
                "Generated as a minimal semantic wrapper, not by an MMFE run.",
                "Demo dataset is not for production use.",
            ],
        },
        "lineage": {
            "strategy": "demo_wrapper",
            "alignment_steps": [],
            "temporal_alignment": [],
            "conflict_resolution": {},
        },
    }


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def _write_readme(out_dir: Path, manifest: dict[str, Any]) -> None:
    layers = manifest.get("layers", {})
    inputs = manifest.get("inputs", {})
    generation = manifest.get("generation", {})
    dataset_id = manifest.get("dataset_id", out_dir.name)
    readme = f"""# TWM Bishan Demo Dataset

This package is generated by:

```bash
PROJ_DATA=/Users/zhouning/miniconda3/envs/farmland-mpc/share/proj \\
  .venv/bin/python scripts/generate_twm_demo_data.py --clean --dataset-id {dataset_id} --output-dir {out_dir}
```

It supports early Territorial World Model development:

- state building from DLTB-like parcels
- synthetic control-line rule evaluation
- evidence-chain tests
- WorldModel v2.1 scenario handoff tests

## Layers

| Role | Chinese alias | File | Notes |
|---|---|---|---|
| parcel | 现状地类图斑 | `parcel_current.geojson` | {layers.get("parcel_current", {}).get("rows", 0)} Bishan DLTB-like parcels selected by `{inputs.get("admin_prefixes", []) or inputs.get("admin_prefix", "") or "random sample"}` |
| pbf | 合成永久基本农田 | `synthetic_pbf.geojson` | {layers.get("synthetic_pbf", {}).get("rows", 0)} synthetic permanent-basic-farmland features |
| eco_redline | 合成生态保护红线 | `synthetic_eco_redline.geojson` | {layers.get("synthetic_eco_redline", {}).get("rows", 0)} synthetic ecological-redline features |
| admin_unit | 乡镇行政区边界 | `admin_units.geojson` | {layers.get("admin_units", {}).get("rows", 0)} township boundaries selected by positive overlap with demo parcels |
| annual_change | 合成年度变化图斑 | `synthetic_annual_change.geojson` | {layers.get("synthetic_annual_change", {}).get("rows", 0)} changes derived from WorldModel `ORIG_DLBM -> OPT_DLBM` |
| project | 合成建设项目范围 | `synthetic_projects.geojson` | {layers.get("synthetic_projects", {}).get("rows", 0)} scenario-driven project footprints |
| planning_zone | 合成用途管制分区 | `synthetic_planning_zones.geojson` | {layers.get("synthetic_planning_zones", {}).get("rows", 0)} synthetic planning-control zones |
| urban_boundary | 合成城镇开发边界 | `synthetic_urban_boundary.geojson` | {layers.get("synthetic_urban_boundary", {}).get("rows", 0)} synthetic urban-development-boundary features |
| remote_sensing_tile | 合成遥感影像瓦片索引 | `synthetic_remote_sensing_tiles.geojson` | {layers.get("synthetic_remote_sensing_tiles", {}).get("rows", 0)} multimodal evidence tile index |

Generation mode: `{generation.get("sampling_mode", "")}`.

The package also includes:

- `dataset_manifest.json`
- `data_dictionary.zh.json`
- `parcel_current.semantic.json`
- `synthetic_annual_change.semantic.json`
- `standard_rules.lifecycle.json`
- `documents/project_documents.zh.jsonl`
- `relations/*.csv`
- `tables/*.csv`
- `raster_manifest.json`
- `rasters/*.tif`
- `world_model_summary.json`

## Chinese Aliases

Use `data_dictionary.zh.json` for human-readable layer and field labels.
The stable data columns stay in ASCII/code form so backend code can read them
reliably, while the dictionary provides Chinese display names and descriptions.

Examples:

| Stable name | Chinese alias |
|---|---|
| `parcel_current` | 现状地类图斑 |
| `synthetic_pbf` | 合成永久基本农田 |
| `synthetic_eco_redline` | 合成生态保护红线 |
| `synthetic_annual_change` | 合成年度变化图斑 |
| `synthetic_projects` | 合成建设项目范围 |
| `synthetic_planning_zones` | 合成用途管制分区 |
| `synthetic_urban_boundary` | 合成城镇开发边界 |
| `synthetic_remote_sensing_tiles` | 合成遥感影像瓦片索引 |
| `DLBM` | 地类编码 |
| `DLMC` | 地类名称 |
| `TBMJ` | 图斑面积 |
| `slope_mean` | 平均坡度 |
| `not_for_production` | 禁止生产使用 |
| `qa_use_for_rules` | 可用于规则计算 |

The preview report at `preview/index.html` renders these aliases directly.

## Safety

All synthetic layers include:

- `synthetic=true`
- `not_for_production=true`
- `synthetic_method`
- `source_dataset`

Do not use this package for production natural-resource governance decisions.
Replace synthetic layers with authoritative permanent basic farmland,
ecological redline, planning, approval, and enforcement datasets before
production use.

## Data Quality Gate

The generator repairs polygonal geometry and writes explicit QA fields:

- `qa_geometry_fixed`
- `geom_area_m2`
- `area_source_m2`
- `tbmj_area_rel_error`
- `qa_area_warning`
- `qa_use_for_rules`

Synthetic control zones and projects are generated from features that pass
`qa_use_for_rules=true`. The raw sample still keeps QA flags so downstream
agents can explain source-data risk.

## Relation And Multimodal Artifacts

`relations/*.csv` contains explicit spatial/evidence bridges such as project to
parcel, project to PBF, project to ecological redline, project to planning zone,
project to urban boundary, and project to remote-sensing tile.

`documents/project_documents.zh.jsonl` contains Chinese synthetic project texts
for MMFE text-vector fusion tests. `synthetic_remote_sensing_tiles.geojson`
indexes the generated raster fixtures under `rasters/`.

`rasters/synthetic_ndvi_2026.tif` and
`rasters/synthetic_change_intensity_2026.tif` are small GeoTIFF fixtures
derived from parcel semantics, synthetic control zones, and annual changes.
They contain generated pixels for engineering tests only; they are not observed
satellite imagery.

`tables/*.csv` contains non-spatial governance-loop data: rule evaluations,
approval records, enforcement events, review tasks, annual state snapshots,
standard field lifecycle, and multimodal evidence index.

## Validation Snapshot

Current generated package:

- `parcel_current`: {layers.get("parcel_current", {}).get("rows", 0)} features
- `synthetic_pbf`: {layers.get("synthetic_pbf", {}).get("rows", 0)} features
- `synthetic_eco_redline`: {layers.get("synthetic_eco_redline", {}).get("rows", 0)} features
- `admin_units`: {layers.get("admin_units", {}).get("rows", 0)} features
- `synthetic_annual_change`: {layers.get("synthetic_annual_change", {}).get("rows", 0)} features
- `synthetic_projects`: {layers.get("synthetic_projects", {}).get("rows", 0)} features
- `synthetic_planning_zones`: {layers.get("synthetic_planning_zones", {}).get("rows", 0)} features
- `synthetic_urban_boundary`: {layers.get("synthetic_urban_boundary", {}).get("rows", 0)} features
- `synthetic_remote_sensing_tiles`: {layers.get("synthetic_remote_sensing_tiles", {}).get("rows", 0)} features
"""
    (out_dir / "README.md").write_text(readme, encoding="utf-8")


def generate_demo_data(args: argparse.Namespace) -> dict[str, Any]:
    _merge_standard_field_aliases()
    parcels_path = Path(args.parcels)
    scenario_path = Path(args.scenario)
    summary_path = Path(args.world_model_summary)
    admin_boundaries_path = Path(args.admin_boundaries) if args.admin_boundaries else Path("")
    out_dir = Path(args.output_dir)
    project_crs = args.project_crs
    dataset_id = args.dataset_id
    dataset_alias_zh = args.dataset_alias_zh
    admin_prefix = "" if args.admin_prefixes and args.admin_prefix == DEFAULT_ADMIN_PREFIX else args.admin_prefix
    admin_prefixes = _parse_admin_prefixes(admin_prefix, args.admin_prefixes)

    if not parcels_path.exists():
        raise FileNotFoundError(f"parcel source not found: {parcels_path}")
    if not scenario_path.exists():
        raise FileNotFoundError(f"scenario source not found: {scenario_path}")

    parcels = _prepare_gdf(parcels_path)
    scenario = _prepare_gdf(scenario_path)
    if admin_prefixes:
        parcels = _filter_admin_prefixes(parcels, admin_prefixes)
        scenario = _filter_admin_prefixes(scenario, admin_prefixes)
    parcels = _quality_annotate(parcels, project_crs)
    scenario = _quality_annotate(scenario, project_crs)
    changed = scenario[_changed_mask(scenario)].copy()
    changed_bsms = set(changed["bsm_norm"].dropna().astype(str))

    parcel_sample = _build_parcel_sample(
        parcels=parcels,
        changed_bsms=changed_bsms,
        max_parcels=args.max_parcels,
        seed=args.seed,
        source_dataset=parcels_path,
        contiguous_mode=bool(admin_prefixes),
    )
    annual_change = _make_annual_change(scenario, scenario_path, project_crs)
    pbf = _make_pbf(parcel_sample, parcels_path, project_crs, args.seed)
    eco = _make_eco_redline(parcel_sample, parcels_path, project_crs, args.seed)
    planning_zones = _make_planning_zones(parcel_sample, parcels_path, project_crs)
    urban = _make_urban_boundary(parcel_sample, parcels_path, project_crs, args.seed)
    rs_tiles = _make_remote_sensing_tiles(
        parcel_sample,
        parcels_path,
        project_crs,
        args.seed,
        dataset_id=dataset_id,
    )
    if admin_boundaries_path and admin_boundaries_path.exists():
        admin = _make_admin_units_from_boundaries(parcel_sample, admin_boundaries_path, project_crs)
    else:
        admin = _make_admin_units(parcel_sample, parcels_path, project_crs)
    projects = _make_projects(
        parcel_sample=parcel_sample,
        annual_change=annual_change,
        pbf=pbf,
        eco=eco,
        urban=urban,
        planning_zones=planning_zones,
        source_dataset=scenario_path,
        project_crs=project_crs,
        seed=args.seed,
        max_projects=args.max_projects,
    )

    if out_dir.exists() and args.clean:
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    layers: dict[str, dict[str, Any]] = {}
    layer_specs = {
        "parcel_current": (parcel_sample, out_dir / "parcel_current.geojson"),
        "synthetic_pbf": (pbf, out_dir / "synthetic_pbf.geojson"),
        "synthetic_eco_redline": (eco, out_dir / "synthetic_eco_redline.geojson"),
        "admin_units": (admin, out_dir / "admin_units.geojson"),
        "synthetic_annual_change": (annual_change, out_dir / "synthetic_annual_change.geojson"),
        "synthetic_projects": (projects, out_dir / "synthetic_projects.geojson"),
        "synthetic_planning_zones": (planning_zones, out_dir / "synthetic_planning_zones.geojson"),
        "synthetic_urban_boundary": (urban, out_dir / "synthetic_urban_boundary.geojson"),
        "synthetic_remote_sensing_tiles": (
            rs_tiles,
            out_dir / "synthetic_remote_sensing_tiles.geojson",
        ),
    }
    for role, (gdf, path) in layer_specs.items():
        layers[role] = _write_layer(gdf, path)

    raster_manifest = _write_synthetic_rasters(
        out_dir,
        dataset_id=dataset_id,
        parcel_sample=parcel_sample,
        annual_change=annual_change,
        pbf=pbf,
        eco=eco,
        project_crs=project_crs,
        seed=args.seed,
        raster_size=args.raster_size,
    )

    relation_tables = _write_relation_tables(
        out_dir,
        parcel_sample=parcel_sample,
        annual_change=annual_change,
        projects=projects,
        pbf=pbf,
        eco=eco,
        planning_zones=planning_zones,
        urban=urban,
        rs_tiles=rs_tiles,
        project_crs=project_crs,
    )
    standard_rules = _write_standard_rules(out_dir)
    standard_contracts = _write_standard_contract_bundle(out_dir)
    project_documents = _write_project_documents(out_dir, projects)
    domain_tables = _write_domain_tables(
        out_dir,
        parcel_sample=parcel_sample,
        annual_change=annual_change,
        projects=projects,
        layers=layers,
        dataset_id=dataset_id,
        project_crs=project_crs,
        relation_tables=relation_tables,
        standard_rules=standard_rules,
        project_documents=project_documents,
        rs_tiles=rs_tiles,
        raster_manifest=raster_manifest,
    )

    if summary_path.exists():
        shutil.copyfile(summary_path, out_dir / "world_model_summary.json")

    parcel_manifest = _semantic_manifest(
        output_path=out_dir / "parcel_current.geojson",
        source_path=parcels_path,
        row_count=len(parcel_sample),
        columns=[c for c in parcel_sample.columns if c != "geometry"],
        role="parcel_current",
        mappings=[
            {"source_field": "BSM", "target_field": "parcel_id", "confidence": 1.0, "match_type": "explicit"},
            {"source_field": "DLBM", "target_field": "land_use_code", "confidence": 1.0, "match_type": "explicit"},
            {"source_field": "DLMC", "target_field": "land_use_name", "confidence": 1.0, "match_type": "explicit"},
            {"source_field": "TBMJ", "target_field": "area_m2", "confidence": 0.95, "match_type": "explicit"},
            {"source_field": "QSDWDM", "target_field": "admin_code", "confidence": 0.95, "match_type": "explicit"},
            {"source_field": "QSDWMC", "target_field": "admin_name", "confidence": 0.95, "match_type": "explicit"},
            {"source_field": "slope_mean", "target_field": "slope_mean", "confidence": 0.9, "match_type": "explicit"},
        ],
    )
    _write_json(out_dir / "parcel_current.semantic.json", parcel_manifest)

    scenario_manifest = _semantic_manifest(
        output_path=out_dir / "synthetic_annual_change.geojson",
        source_path=scenario_path,
        row_count=len(annual_change),
        columns=[c for c in annual_change.columns if c != "geometry"],
        role="annual_change",
        mappings=[
            {"source_field": "BSM", "target_field": "parcel_id", "confidence": 1.0, "match_type": "explicit"},
            {"source_field": "ORIG_DLBM", "target_field": "from_land_use_code", "confidence": 1.0, "match_type": "explicit"},
            {"source_field": "OPT_DLBM", "target_field": "to_land_use_code", "confidence": 1.0, "match_type": "explicit"},
            {"source_field": "CHG_FLAG", "target_field": "change_type", "confidence": 0.95, "match_type": "explicit"},
        ],
    )
    _write_json(out_dir / "synthetic_annual_change.semantic.json", scenario_manifest)

    manifest = {
        "dataset_id": dataset_id,
        "dataset_alias_zh": dataset_alias_zh,
        "version": "2026-06-16",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "not_for_production": True,
        "description": "Demo data package for Territorial World Model engineering tests.",
        "description_zh": "面向国土空间世界模型工程验证的璧山演示数据包，含现状图斑、合成控制线、合成变化和合成项目范围。",
        "inputs": {
            "parcel_current": str(parcels_path),
            "scenario_candidate": str(scenario_path),
            "world_model_summary": str(summary_path) if summary_path.exists() else "",
            "admin_boundaries": str(admin_boundaries_path) if admin_boundaries_path and admin_boundaries_path.exists() else "",
            "project_crs": project_crs,
            "admin_prefix": admin_prefix,
            "admin_prefixes": admin_prefixes,
        },
        "aliases": {
            "layers": LAYER_ALIASES,
            "fields": FIELD_ALIASES,
            "roles": ROLE_GUIDE,
        },
        "generation": {
            "script": "scripts/generate_twm_demo_data.py",
            "seed": args.seed,
            "max_parcels": args.max_parcels,
            "max_projects": args.max_projects,
            "raster_size": args.raster_size,
            "sampling_mode": (
                "contiguous_multi_admin_prefixes"
                if len(admin_prefixes) > 1
                else "contiguous_admin_prefix"
                if len(admin_prefixes) == 1
                else "stratified_random"
            ),
            "synthetic_methods": {
                "synthetic_pbf": "dissolve_low_slope_farmland_components_with_boundary_generalization",
                "synthetic_eco_redline": "dissolve_forest_water_high_slope_components_with_buffer",
                "admin_units": (
                    "overlay_filter_township_boundaries"
                    if admin_boundaries_path and admin_boundaries_path.exists()
                    else "dissolve_parcels_by_qsdwdm_prefix_9_12_15"
                ),
                "synthetic_annual_change": "world_model_optimized_orig_to_opt_dlbm",
                "synthetic_projects": "scenario_driven_project_footprints_from_control_boundaries_and_parcels",
                "synthetic_planning_zones": "land_use_code_to_planning_space_dissolve",
                "synthetic_urban_boundary": "construction_land_dissolve_buffer_simplify",
                "synthetic_remote_sensing_tiles": "grid_tile_index_over_synthetic_raster_fixture",
                "synthetic_rasters": "vector_semantic_fixture_rasterization",
            },
            "quality_gate": {
                "geometry_repair": "shapely.make_valid_and_polygonal_extraction",
                "min_rule_area_m2": 10.0,
                "area_warning_threshold": 0.05,
                "area_block_threshold": 0.10,
                "rule_inputs": "synthetic layers are built from qa_use_for_rules=true features",
            },
        },
        "layers": layers,
        "relations": relation_tables,
        "rasters": raster_manifest.get("products", {}),
        "raster_manifest": {
            "path": str(out_dir / "raster_manifest.json"),
            "product_count": len(raster_manifest.get("products", {})),
        },
        "tables": domain_tables,
        "standard_rules": standard_rules,
        "standard_contracts": standard_contracts,
        "documents": {
            "project_documents_zh": project_documents,
        },
        "quality_reports": {
            "json": str(out_dir / "data_quality_report.json"),
            "markdown": str(out_dir / "data_quality_report.md"),
            "generator": "scripts/qa_twm_demo_data.py",
            "status": "run qa_twm_demo_data.py after generation",
        },
        "preview": {
            "html": str(out_dir / "preview" / "index.html"),
            "geopackage": str(out_dir / "preview" / f"{dataset_id}_layers.gpkg"),
            "generator": "scripts/preview_twm_demo_data.py",
        },
        "semantic_products": {
            "parcel_current": str(out_dir / "parcel_current.semantic.json"),
            "synthetic_annual_change": str(out_dir / "synthetic_annual_change.semantic.json"),
        },
        "known_limitations": [
            "Synthetic control zones, planning zones, project footprints, remote-sensing tile index, and raster fixtures are engineering scaffolds, not authoritative data.",
            "Admin units are sourced from the township boundary file when available; verify its source authority before production use.",
            "Synthetic raster fixtures contain generated pixels for MMFE tests; they are not observed satellite imagery.",
            "The default package keeps one township-level prefix; use the multi-admin eval package for cross-township balance tests.",
            "Some source parcel area attributes remain inconsistent with computed geometry area; use qa_use_for_rules for rule filtering.",
        ],
        "recommended_layer_bindings": [
            {"role": "parcel", "path": str(out_dir / "parcel_current.geojson"), "semantic_product_path": str(out_dir / "parcel_current.semantic.json")},
            {"role": "pbf", "path": str(out_dir / "synthetic_pbf.geojson")},
            {"role": "eco_redline", "path": str(out_dir / "synthetic_eco_redline.geojson")},
            {"role": "admin_unit", "path": str(out_dir / "admin_units.geojson")},
            {"role": "annual_change", "path": str(out_dir / "synthetic_annual_change.geojson"), "semantic_product_path": str(out_dir / "synthetic_annual_change.semantic.json")},
            {"role": "project", "path": str(out_dir / "synthetic_projects.geojson")},
            {"role": "planning_zone", "path": str(out_dir / "synthetic_planning_zones.geojson")},
            {"role": "urban_boundary", "path": str(out_dir / "synthetic_urban_boundary.geojson")},
            {"role": "remote_sensing_tile", "path": str(out_dir / "synthetic_remote_sensing_tiles.geojson")},
            {"role": "raster_observation", "path": str(out_dir / "raster_manifest.json")},
        ],
        "warnings": [
            "Synthetic control zones and project footprints are for testing and demos only.",
            "Synthetic raster fixtures are generated from vector semantics and are not real remote-sensing observations.",
            "Do not use this package for production natural-resource governance decisions.",
            "Replace synthetic layers with authoritative PBF, ecological redline, planning, approval, and enforcement datasets before production use.",
        ],
    }
    _write_json(out_dir / "dataset_manifest.json", manifest)
    _write_json(out_dir / "data_dictionary.zh.json", {
        "dataset_id": manifest["dataset_id"],
        "dataset_alias_zh": manifest["dataset_alias_zh"],
        "description_zh": manifest["description_zh"],
        "not_for_production": True,
        "layers": LAYER_ALIASES,
        "fields": FIELD_ALIASES,
        "roles": ROLE_GUIDE,
        "layer_fields": {
            role: {
                "alias_zh": info.get("alias_zh", role),
                "fields": {
                    field: FIELD_ALIASES.get(field, {
                        "alias_zh": field,
                        "description_zh": "未配置中文说明。",
                    })
                    for field in info.get("columns", [])
                },
            }
            for role, info in layers.items()
        },
    })
    _write_readme(out_dir, manifest)
    return manifest


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--parcels", default=str(DEFAULT_PARCELS))
    parser.add_argument("--scenario", default=str(DEFAULT_SCENARIO))
    parser.add_argument("--world-model-summary", default=str(DEFAULT_WORLD_MODEL_SUMMARY))
    parser.add_argument("--admin-boundaries", default=str(DEFAULT_ADMIN_BOUNDARIES),
                        help="Township boundary layer used for admin_units; empty string falls back to parcel dissolve")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--dataset-id", default=DEFAULT_DATASET_ID)
    parser.add_argument("--dataset-alias-zh", default=DEFAULT_DATASET_ALIAS_ZH)
    parser.add_argument("--project-crs", default=DEFAULT_PROJECT_CRS)
    parser.add_argument("--admin-prefix", default=DEFAULT_ADMIN_PREFIX,
                        help="QSDWDM prefix used to build a contiguous demo area; empty string disables")
    parser.add_argument("--admin-prefixes", default="",
                        help="Comma-separated QSDWDM/admin9 prefixes for multi-admin evaluation packages")
    parser.add_argument("--max-parcels", type=int, default=0,
                        help="Optional cap after admin-prefix filtering; 0 keeps all selected parcels")
    parser.add_argument("--max-projects", type=int, default=60)
    parser.add_argument("--raster-size", type=int, default=256)
    parser.add_argument("--seed", type=int, default=20260615)
    parser.add_argument("--clean", action="store_true", help="Remove output directory before writing")
    return parser.parse_args()


def main() -> None:
    manifest = generate_demo_data(parse_args())
    print(json.dumps({
        "dataset_id": manifest["dataset_id"],
        "output_dir": str(Path(manifest["layers"]["parcel_current"]["path"]).parent),
        "layers": {
            role: {"rows": info["rows"], "path": info["path"]}
            for role, info in manifest["layers"].items()
        },
        "not_for_production": manifest["not_for_production"],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
