"""
知识管理层 — 语义等价库

管理 GIS 字段语义等价关系，用于数据画像和标准对照中的字段语义匹配。

数据来源：
  1. standards/gis_ontology.yaml — 静态基线（原有 15 组 + 三调扩充）
  2. 未来可对接底座的语义注册表，支持用户自定义等价关系

核心能力：
  - 给定一个字段名，识别它属于哪个语义等价组
  - 给定两个字段名，判断它们是否语义等价
  - 给定一组字段名，和标准字段列表做语义匹配
"""

from __future__ import annotations

import logging
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)

# 默认 ontology 文件路径
_DEFAULT_ONTOLOGY_PATH = (
    Path(__file__).parent.parent / "standards" / "gis_ontology.yaml"
)

# 三调场景扩充的等价组（补充 gis_ontology.yaml 中未覆盖的三调字段）
_SURVEY_EXTENSIONS: list[dict] = [
    # --- 三调 DLTB 核心字段 ---
    {
        "group_id": "feature_id",
        "fields": ["BSM", "bsm", "标识码", "feature_id", "FID", "OBJECTID"],
    },
    {
        "group_id": "feature_code",
        "fields": ["YSDM", "ysdm", "要素代码", "feature_code", "要素编码"],
    },
    {
        "group_id": "parcel_number",
        "fields": ["TBBH", "tbbh", "图斑编号", "parcel_no", "图斑号", "TBYBH", "tbybh", "图斑预编号"],
    },
    {
        "group_id": "ownership_type",
        "fields": ["QSXZ", "qsxz", "权属性质", "ownership_type", "权属类型"],
    },
    {
        "group_id": "ownership_code",
        "fields": ["QSDWDM", "qsdwdm", "权属单位代码", "ownership_code"],
    },
    {
        "group_id": "ownership_name",
        "fields": ["QSDWMC", "qsdwmc", "权属单位名称", "ownership_name"],
    },
    {
        "group_id": "location_code",
        "fields": ["ZLDWDM", "zldwdm", "坐落单位代码", "location_code", "XZQDM", "xzqdm", "行政区代码", "admin_code"],
    },
    {
        "group_id": "location_name",
        "fields": ["ZLDWMC", "zldwmc", "坐落单位名称", "location_name"],
    },
    {
        "group_id": "deduct_land_code",
        "fields": ["KCDLBM", "kcdlbm", "扣除地类编码"],
    },
    {
        "group_id": "deduct_coefficient",
        "fields": ["KCXS", "kcxs", "扣除地类系数", "TKXS", "tkxs", "田坎系数"],
    },
    {
        "group_id": "deduct_area",
        "fields": ["KCMJ", "kcmj", "扣除地类面积", "TKMJ", "tkmj", "田坎面积"],
    },
    {
        "group_id": "parcel_land_area",
        "fields": ["TBDLMJ", "tbdlmj", "图斑地类面积"],
    },
    {
        "group_id": "farmland_type",
        "fields": ["GDLX", "gdlx", "耕地类型", "farmland_type"],
    },
    {
        "group_id": "farmland_slope",
        "fields": ["GDPDJB", "gdpdjb", "耕地坡度级别", "farmland_slope_level", "PDJB", "pdjb", "坡度级别"],
    },
    {
        "group_id": "linear_feature_width",
        "fields": ["XZDWKD", "xzdwkd", "线状地物宽度"],
    },
    {
        "group_id": "parcel_detail_code",
        "fields": ["TBXHDM", "tbxhdm", "图斑细化代码"],
    },
    {
        "group_id": "parcel_detail_name",
        "fields": ["TBXHMC", "tbxhmc", "图斑细化名称"],
    },
    {
        "group_id": "planting_attr_code",
        "fields": ["ZZSXDM", "zzsxdm", "种植属性代码"],
    },
    {
        "group_id": "planting_attr_name",
        "fields": ["ZZSXMC", "zzsxmc", "种植属性名称"],
    },
    {
        "group_id": "farmland_grade",
        "fields": ["GDDB", "gddb", "耕地等别", "farmland_grade"],
    },
    {
        "group_id": "enclave_flag",
        "fields": ["FRDBS", "frdbs", "飞入地标识"],
    },
    {
        "group_id": "urban_rural_code",
        "fields": ["CZCSXM", "czcsxm", "城镇村属性码"],
    },
    {
        "group_id": "data_year",
        "fields": ["SJNF", "sjnf", "数据年份", "data_year"],
    },
    {
        "group_id": "description",
        "fields": ["MSSM", "mssm", "描述说明", "BZ", "bz", "备注", "remark", "note", "SM", "sm", "说明"],
    },
    # --- 通用 GIS 字段补充 ---
    {
        "group_id": "geometry",
        "fields": ["geometry", "geom", "SHAPE", "shape", "the_geom", "wkb_geometry"],
    },
    {
        "group_id": "coordinate_system",
        "fields": ["crs", "srid", "坐标系", "coordinate_system", "spatial_ref"],
    },
]


class SemanticVocab:
    """语义等价库"""

    def __init__(self, ontology_path: str | Path | None = None):
        self._groups: dict[str, list[str]] = {}  # group_id → [field_names]
        self._field_to_group: dict[str, str] = {}  # lowercase(field) → group_id

        # 加载基线 ontology
        path = Path(ontology_path) if ontology_path else _DEFAULT_ONTOLOGY_PATH
        if path.exists():
            self._load_yaml(path)

        # 加载三调扩充
        self._load_extensions(_SURVEY_EXTENSIONS)

        logger.info(
            "语义等价库初始化: %d 个等价组, %d 个字段映射",
            len(self._groups),
            len(self._field_to_group),
        )

    def _load_yaml(self, path: Path):
        """从 YAML 文件加载等价组"""
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        for eq in data.get("equivalences", []):
            group_id = eq["group_id"]
            fields = eq["fields"]
            self._add_group(group_id, fields)

    def _load_extensions(self, extensions: list[dict]):
        """加载扩充的等价组"""
        for ext in extensions:
            group_id = ext["group_id"]
            fields = ext["fields"]
            self._add_group(group_id, fields)

    def _add_group(self, group_id: str, fields: list[str]):
        """添加一个等价组，如果 group_id 已存在则合并字段"""
        if group_id in self._groups:
            existing = set(self._groups[group_id])
            for f in fields:
                if f not in existing:
                    self._groups[group_id].append(f)
                    existing.add(f)
        else:
            self._groups[group_id] = list(fields)

        for f in fields:
            key = f.lower()
            if key not in self._field_to_group:
                self._field_to_group[key] = group_id

    def lookup(self, field_name: str) -> str | None:
        """查找字段所属的等价组 ID，返回 None 如果未匹配"""
        return self._field_to_group.get(field_name.lower())

    def are_equivalent(self, field_a: str, field_b: str) -> bool:
        """判断两个字段是否语义等价"""
        group_a = self.lookup(field_a)
        group_b = self.lookup(field_b)
        if group_a is None or group_b is None:
            return False
        return group_a == group_b

    def get_group_fields(self, group_id: str) -> list[str]:
        """获取一个等价组中的所有字段名"""
        return self._groups.get(group_id, [])

    def match_fields(
        self,
        source_fields: list[str],
        target_fields: list[str],
    ) -> list[dict]:
        """
        将源字段列表与目标字段列表做语义匹配。

        返回匹配结果列表，每项包含：
        - source: 源字段名
        - target: 匹配到的目标字段名（None 表示未匹配）
        - group_id: 匹配的等价组 ID（None 表示未匹配）
        - match_type: "exact"（完全相同）/ "semantic"（语义等价）/ "unmatched"
        """
        target_lookup: dict[str, str] = {}  # lowercase → original
        target_groups: dict[str, str] = {}  # group_id → original target field
        for t in target_fields:
            target_lookup[t.lower()] = t
            grp = self.lookup(t)
            if grp and grp not in target_groups:
                target_groups[grp] = t

        results = []
        for s in source_fields:
            s_lower = s.lower()

            # 精确匹配（大小写不敏感）
            if s_lower in target_lookup:
                results.append({
                    "source": s,
                    "target": target_lookup[s_lower],
                    "group_id": self.lookup(s),
                    "match_type": "exact",
                })
                continue

            # 语义匹配
            s_group = self.lookup(s)
            if s_group and s_group in target_groups:
                results.append({
                    "source": s,
                    "target": target_groups[s_group],
                    "group_id": s_group,
                    "match_type": "semantic",
                })
                continue

            # 未匹配
            results.append({
                "source": s,
                "target": None,
                "group_id": None,
                "match_type": "unmatched",
            })

        return results

    @property
    def group_count(self) -> int:
        return len(self._groups)

    @property
    def field_count(self) -> int:
        return len(self._field_to_group)

    def summary(self) -> dict:
        return {
            "等价组数": self.group_count,
            "字段映射数": self.field_count,
            "等价组列表": [
                {"group_id": gid, "字段数": len(fields)}
                for gid, fields in self._groups.items()
            ],
        }
