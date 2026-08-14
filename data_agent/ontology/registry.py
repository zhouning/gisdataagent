"""Registered ontology identities shared by runtime, drafting and UI APIs."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .contracts import BASE_URI, ONTOLOGY_KEY

ONTOLOGY_KEY_RE = re.compile(r"^[a-z0-9][a-z0-9-]{2,79}$")
PACKAGE_ROOT = Path(__file__).resolve().parent / "packages"


@dataclass(frozen=True, slots=True)
class OntologyProfile:
    ontology_key: str
    package_slug: str
    title: str
    short_title: str
    description: str
    industry: str
    namespace_uri: str
    stable_id_prefix: str
    curated_source_id: str
    domain_labels: dict[str, str]
    graph_uri: str
    property_ids_scoped_by_owner: bool = False

    @property
    def package_root(self) -> Path:
        return PACKAGE_ROOT / self.package_slug

    def public_dict(self) -> dict[str, object]:
        return {
            "ontology_key": self.ontology_key,
            "title": self.title,
            "short_title": self.short_title,
            "description": self.description,
            "industry": self.industry,
            "namespace_uri": self.namespace_uri,
            "graph_uri": self.graph_uri,
            "domain_count": len(self.domain_labels),
        }


NATURAL_RESOURCE_PROFILE = OntologyProfile(
    ontology_key=ONTOLOGY_KEY,
    package_slug="natural_resource_one_map",
    title="自然资源本体模型",
    short_title="自然资源本体",
    description="自然资源实体、状态、过程、规则及数据结构映射的受治理本体。",
    industry="natural_resources",
    namespace_uri=BASE_URI,
    stable_id_prefix="gda:nr",
    curated_source_id="natural-resource-domain-model-v2",
    domain_labels={
        "01": "统一地理底图",
        "02": "统一调查监测",
        "03": "统一产权底板",
        "04": "统一规划",
        "05": "底线安全",
        "06": "用途管制",
        "07": "开发利用",
        "08": "执法督察",
        "09": "社会经济人口",
        "10": "元数据",
    },
    graph_uri="urn:gda:ontology:natural-resource-one-map",
)


DMT_PROFILE = OntologyProfile(
    ontology_key="abu-dhabi-dmt-gis",
    package_slug="abu_dhabi_dmt_gis",
    title="Abu Dhabi DMT 城市与市政 GIS 本体",
    short_title="DMT 城市与市政本体",
    description="面向阿布扎比市政、规划、资产、交通、设施与城市运营的数据语义本体。",
    industry="urban_municipal",
    namespace_uri="https://ontology.gis-data-agent.local/dmt/urban-municipal/",
    stable_id_prefix="gda:dmt",
    curated_source_id="dmt-gis-data-model-v1",
    domain_labels={
        "gda_meta": "元数据与血缘",
        "dmt_geo": "行政与空间骨架",
        "dmt_land": "地块、土地与规划",
        "dmt_built": "建筑与室内单元",
        "dmt_project": "项目与建设交付",
        "dmt_asset": "城市资产与运维",
        "dmt_utility": "公用设施网络",
        "dmt_facility": "公共设施与服务供给",
        "dmt_mobility": "交通、道路与移动性",
        "dmt_inspection": "调查、检查与缺陷",
        "dmt_iot": "物联网与实时观测",
        "dmt_liveability": "宜居、指标与情景",
        "dmt_realestate": "地产、租赁与权属",
        "dmt_party": "主体与责任边界",
        "dmt_service": "服务、案件与公众参与",
    },
    graph_uri="urn:gda:ontology:abu-dhabi-dmt-gis",
    property_ids_scoped_by_owner=True,
)


IRRIGATION_PROFILE = OntologyProfile(
    ontology_key="irrigation-district-water",
    package_slug="irrigation_district_water",
    title="灌区与水利工程本体",
    short_title="灌区与水利本体",
    description=(
        "面向灌区水源、渠系、控制设施、观测状态、输配水过程、调度行动与审计证据的候选领域本体。"
    ),
    industry="irrigation_water_conservancy",
    namespace_uri="https://ontology.gis-data-agent.local/water/irrigation/",
    stable_id_prefix="gda:irr",
    curated_source_id="irrigation-domain-model-seed-v1",
    domain_labels={
        "irr_system": "灌区系统与管理单元",
        "irr_network": "水源与输配水网络",
        "irr_observation": "监测、状态与需水",
        "irr_process": "水文水力与农业过程",
        "irr_operation": "调度行动与方案",
        "irr_governance": "约束、证据与审计",
    },
    graph_uri="urn:gda:ontology:irrigation-district-water",
    property_ids_scoped_by_owner=True,
)


_PROFILES = {
    profile.ontology_key: profile
    for profile in (NATURAL_RESOURCE_PROFILE, DMT_PROFILE, IRRIGATION_PROFILE)
}


def get_ontology_profile(ontology_key: str | None = None) -> OntologyProfile:
    key = str(ontology_key or ONTOLOGY_KEY).strip().casefold()
    if not ONTOLOGY_KEY_RE.fullmatch(key):
        raise ValueError("invalid ontology_key")
    try:
        return _PROFILES[key]
    except KeyError as exc:
        raise KeyError(f"ontology is not registered: {key}") from exc


def list_ontology_profiles() -> list[OntologyProfile]:
    return list(_PROFILES.values())
