"""元数据增强器 - 自动推理和补充元数据"""
from typing import Dict, Any


class MetadataEnricher:
    """元数据增强器"""

    # 省级行政区 bbox 字典 (WGS84)
    REGION_BBOXES = {
        "北京市": (115.42, 39.44, 117.51, 41.06),
        "上海市": (120.85, 30.68, 122.12, 31.87),
        "重庆市": (105.28, 28.16, 110.19, 32.20),
        "天津市": (116.72, 38.56, 118.04, 40.25),
        "四川省": (97.35, 26.05, 108.55, 34.32),
        "广东省": (109.66, 20.22, 117.32, 25.52),
        "浙江省": (118.01, 27.02, 123.25, 31.11),
        "江苏省": (116.36, 30.75, 121.92, 35.20),
        "山东省": (114.79, 34.38, 122.71, 38.40),
        "河南省": (110.35, 31.38, 116.65, 36.37),
    }

    REGION_TO_AREA = {
        "北京市": "华北", "天津市": "华北", "河北省": "华北", "山西省": "华北", "内蒙古自治区": "华北",
        "上海市": "华东", "江苏省": "华东", "浙江省": "华东", "安徽省": "华东", "福建省": "华东", "江西省": "华东", "山东省": "华东",
        "重庆市": "西南", "四川省": "西南", "贵州省": "西南", "云南省": "西南", "西藏自治区": "西南",
        "广东省": "华南", "广西壮族自治区": "华南", "海南省": "华南",
    }

    DOMAIN_KEYWORDS = {
        "LAND_USE": ["土地利用", "地类", "lulc", "landuse", "用地"],
        "ELEVATION": ["高程", "dem", "elevation", "地形"],
        "POPULATION": ["人口", "population", "census"],
        "TRANSPORTATION": ["道路", "交通", "road", "transport"],
        "BUILDING": ["建筑", "房屋", "building"],
    }

    def enrich_geography(self, metadata: Dict[str, Any]) -> Dict[str, Any]:
        """根据 bbox 推理地区标签"""
        extent = metadata.get("technical", {}).get("spatial", {}).get("extent")
        if not extent:
            return metadata

        minx, miny, maxx, maxy = extent["minx"], extent["miny"], extent["maxx"], extent["maxy"]
        matched_regions = []

        for region, (r_minx, r_miny, r_maxx, r_maxy) in self.REGION_BBOXES.items():
            if not (maxx < r_minx or minx > r_maxx or maxy < r_miny or miny > r_maxy):
                matched_regions.append(region)

        if matched_regions:
            areas = list(set(self.REGION_TO_AREA.get(r, "其他") for r in matched_regions))
            metadata.setdefault("business", {})["geography"] = {
                "region_tags": matched_regions,
                "area_tags": areas,
            }

        return metadata

    def enrich_domain(self, metadata: Dict[str, Any], file_name: str = "") -> Dict[str, Any]:
        """根据文件名推理领域分类"""
        text = file_name.lower()
        for domain, keywords in self.DOMAIN_KEYWORDS.items():
            if any(kw in text for kw in keywords):
                metadata.setdefault("business", {})["classification"] = {"domain": domain}
                break
        return metadata

    def enrich_quality(self, metadata: Dict[str, Any]) -> Dict[str, Any]:
        """推理数据质量分数"""
        score = 0.5
        tech = metadata.get("technical", {})

        if tech.get("spatial", {}).get("crs"):
            score += 0.2
        if tech.get("structure", {}).get("columns"):
            score += 0.15
        if tech.get("spatial", {}).get("extent"):
            score += 0.15

        metadata.setdefault("business", {})["quality"] = {"completeness_score": min(score, 1.0)}
        return metadata
