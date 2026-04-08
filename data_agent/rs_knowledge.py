"""
Remote Sensing Domain Knowledge Base — spectral properties, processing workflows,
classification systems, and regulatory standards (v22.0).

Provides structured domain knowledge for RS agents to reference during analysis.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


# ---------------------------------------------------------------------------
# Spectral Index Knowledge
# ---------------------------------------------------------------------------

SPECTRAL_INDICES = {
    "NDVI": {
        "name": "归一化植被指数",
        "formula": "(NIR - Red) / (NIR + Red)",
        "range": [-1, 1],
        "interpretation": {
            "< 0": "水体/云/雪",
            "0-0.2": "裸土/建筑",
            "0.2-0.5": "稀疏植被/草地",
            "0.5-0.7": "中等植被/灌木",
            "> 0.7": "茂密植被/森林",
        },
        "bands": {"sentinel2": {"NIR": "B8", "Red": "B4"}},
        "applications": ["植被监测", "农作物长势", "生态评估"],
    },
    "NDWI": {
        "name": "归一化水体指数",
        "formula": "(Green - NIR) / (Green + NIR)",
        "range": [-1, 1],
        "interpretation": {
            "> 0.3": "水体",
            "0-0.3": "湿地/水边",
            "< 0": "非水体",
        },
        "bands": {"sentinel2": {"Green": "B3", "NIR": "B8"}},
        "applications": ["水体提取", "洪水监测", "湿地制图"],
    },
    "NDBI": {
        "name": "归一化建筑指数",
        "formula": "(SWIR - NIR) / (SWIR + NIR)",
        "range": [-1, 1],
        "interpretation": {
            "> 0.1": "建筑/不透水面",
            "< 0": "植被/水体",
        },
        "bands": {"sentinel2": {"SWIR": "B11", "NIR": "B8"}},
        "applications": ["城市扩张", "不透水面提取"],
    },
    "NBR": {
        "name": "归一化燃烧比",
        "formula": "(NIR - SWIR2) / (NIR + SWIR2)",
        "range": [-1, 1],
        "interpretation": {
            "< -0.1": "高度烧毁",
            "-0.1-0.1": "低度烧毁",
            "> 0.1": "未烧毁",
        },
        "bands": {"sentinel2": {"NIR": "B8", "SWIR2": "B12"}},
        "applications": ["火灾评估", "烧毁面积制图"],
    },
    "EVI": {
        "name": "增强型植被指数",
        "formula": "2.5 * (NIR - Red) / (NIR + 6*Red - 7.5*Blue + 1)",
        "range": [-1, 1],
        "interpretation": {
            "< 0.2": "裸土/稀疏",
            "0.2-0.5": "中等植被",
            "> 0.5": "茂密植被",
        },
        "bands": {"sentinel2": {"NIR": "B8", "Red": "B4", "Blue": "B2"}},
        "applications": ["高密度植被区域", "热带森林监测"],
    },
}


# ---------------------------------------------------------------------------
# Land Cover Classification Systems
# ---------------------------------------------------------------------------

CLASSIFICATION_SYSTEMS = {
    "GB/T_21010": {
        "name": "土地利用现状分类 (GB/T 21010-2017)",
        "country": "中国",
        "levels": 2,
        "categories": {
            "01": "耕地", "02": "园地", "03": "林地", "04": "草地",
            "05": "商服用地", "06": "工矿仓储用地", "07": "住宅用地",
            "08": "公共管理与公共服务用地", "09": "特殊用地",
            "10": "交通运输用地", "11": "水域及水利设施用地", "12": "其他土地",
        },
    },
    "CORINE": {
        "name": "CORINE Land Cover",
        "country": "欧洲",
        "levels": 3,
        "categories": {
            "1": "人工表面", "2": "农业区域", "3": "森林和半自然区域",
            "4": "湿地", "5": "水体",
        },
    },
    "NLCD": {
        "name": "National Land Cover Database",
        "country": "美国",
        "levels": 2,
        "categories": {
            "11": "Open Water", "21": "Developed, Open Space",
            "22": "Developed, Low Intensity", "23": "Developed, Medium Intensity",
            "24": "Developed, High Intensity", "31": "Barren Land",
            "41": "Deciduous Forest", "42": "Evergreen Forest",
            "43": "Mixed Forest", "52": "Shrub/Scrub",
            "71": "Grassland/Herbaceous", "81": "Pasture/Hay",
            "82": "Cultivated Crops", "90": "Woody Wetlands",
            "95": "Emergent Herbaceous Wetlands",
        },
    },
}


# ---------------------------------------------------------------------------
# Processing Workflow Templates
# ---------------------------------------------------------------------------

PROCESSING_WORKFLOWS = {
    "vegetation_monitoring": {
        "name": "植被监测标准流程",
        "steps": [
            "大气校正 (Sen2Cor / FLAASH)",
            "云掩膜 (QA60 / Fmask)",
            "NDVI/EVI 计算",
            "时间序列平滑 (Savitzky-Golay)",
            "物候参数提取 (SOS/EOS/LOS)",
            "变化检测 (Mann-Kendall 趋势)",
            "结果验证 (地面样点 / 高分影像)",
        ],
    },
    "urban_expansion": {
        "name": "城市扩张监测流程",
        "steps": [
            "多时相影像配准",
            "NDBI/NDVI 计算",
            "不透水面提取 (阈值法 / 随机森林)",
            "分类后比较变化检测",
            "转移矩阵分析",
            "扩张速率与方向统计",
            "热岛效应关联分析",
        ],
    },
    "flood_assessment": {
        "name": "洪水灾害评估流程",
        "steps": [
            "SAR/光学影像获取 (灾前+灾后)",
            "水体提取 (NDWI / SAR 阈值)",
            "淹没范围制图",
            "受灾面积统计 (按行政区/地类)",
            "损失评估 (叠加人口/GDP 数据)",
            "报告生成",
        ],
    },
}


# ---------------------------------------------------------------------------
# Query interface
# ---------------------------------------------------------------------------


def get_spectral_index(name: str) -> Optional[dict]:
    """Get spectral index knowledge by name."""
    return SPECTRAL_INDICES.get(name.upper())


def search_indices_by_application(keyword: str) -> list[dict]:
    """Search spectral indices by application keyword."""
    results = []
    keyword_lower = keyword.lower()
    for name, info in SPECTRAL_INDICES.items():
        for app in info.get("applications", []):
            if keyword_lower in app.lower():
                results.append({"index": name, **info})
                break
    return results


def get_classification_system(name: str) -> Optional[dict]:
    """Get land cover classification system by name."""
    return CLASSIFICATION_SYSTEMS.get(name)


def get_processing_workflow(name: str) -> Optional[dict]:
    """Get processing workflow template by name."""
    return PROCESSING_WORKFLOWS.get(name)


def list_all_knowledge() -> dict:
    """List all available domain knowledge."""
    return {
        "spectral_indices": list(SPECTRAL_INDICES.keys()),
        "classification_systems": list(CLASSIFICATION_SYSTEMS.keys()),
        "processing_workflows": list(PROCESSING_WORKFLOWS.keys()),
    }
