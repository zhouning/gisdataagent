"""Curated natural-resource domain model layered over source metadata.

EA and standard structures are evidence and mappings. They never define the
OWL class hierarchy automatically; only reviewed seeds in this module do.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from .contracts import (
    BASE_URI,
    ConceptRecord,
    MappingRecord,
    MappingStatus,
    PropertyRecord,
    RelationRecord,
    SourceRecord,
    sha256_json,
    stable_token,
)

if TYPE_CHECKING:
    from .compiler import CompiledOntology


CURATED_SOURCE_ID = "natural-resource-domain-model-v2"
CURATED_MODEL_VERSION = "2.3.0"
ATTACHMENT_SOURCE_ID = "attachment-spatiotemporal-base-attribute-attachment-0804"
ATTACHMENT_SOURCE_SHA256 = "a448fd83683ae180604f41aa513c906c88fad0e4530832f056cd23225cd0c1d7"


@dataclass(frozen=True)
class ClassSeed:
    name: str
    label: str
    kind: str
    parent: str | None
    domain_id: str
    definition: str
    aliases: tuple[str, ...] = ()


@dataclass(frozen=True)
class ObjectPropertySeed:
    name: str
    label: str
    domain: str
    range: str
    restriction: str | None = None
    inverse: str | None = None
    functional: bool = False


@dataclass(frozen=True)
class ClassRestrictionSeed:
    owner: str
    property_name: str
    filler: str
    cardinality: str
    count: int


@dataclass(frozen=True)
class DataPropertySeed:
    name: str
    label: str
    owner: str
    datatype: str
    source_codes: tuple[str, ...] = ()
    source_labels: tuple[str, ...] = ()
    min_count: int = 0
    max_count: int | None = 1
    definition: str = ""


@dataclass(frozen=True)
class SchemaBindingSeed:
    target_class: str
    source_codes: tuple[str, ...] = ()
    source_labels: tuple[str, ...] = ()
    package_path_contains: str = ""
    source_id: str = ""


@dataclass(frozen=True)
class FieldRelationSeed:
    relation_name: str
    target_class: str
    source_codes: tuple[str, ...] = ()
    source_labels: tuple[str, ...] = ()


def _seed(
    name: str,
    label: str,
    kind: str,
    parent: str | None,
    domain_id: str,
    definition: str,
    *aliases: str,
) -> ClassSeed:
    return ClassSeed(name, label, kind, parent, domain_id, definition, aliases)


def _data(
    name: str,
    label: str,
    owner: str,
    datatype: str,
    *source_codes: str,
    source_labels: tuple[str, ...] = (),
    definition: str = "",
) -> DataPropertySeed:
    return DataPropertySeed(
        name=name,
        label=label,
        owner=owner,
        datatype=datatype,
        source_codes=source_codes,
        source_labels=source_labels,
        definition=definition,
    )


def _binding(
    target_class: str,
    *source_codes: str,
    source_labels: tuple[str, ...] = (),
    package_path_contains: str = "",
    source_id: str = "",
) -> SchemaBindingSeed:
    return SchemaBindingSeed(
        target_class=target_class,
        source_codes=source_codes,
        source_labels=source_labels,
        package_path_contains=package_path_contains,
        source_id=source_id,
    )


def _field_relation(
    relation_name: str,
    target_class: str,
    *source_codes: str,
    source_labels: tuple[str, ...] = (),
) -> FieldRelationSeed:
    return FieldRelationSeed(
        relation_name=relation_name,
        target_class=target_class,
        source_codes=source_codes,
        source_labels=source_labels,
    )


CLASS_SEEDS = (
    _seed(
        "NaturalResourceThing",
        "自然资源领域事物",
        "DomainClass",
        None,
        "01",
        "自然资源领域中可被区分和描述的事物总类。",
    ),
    _seed(
        "NaturalResourceEntity",
        "自然资源实体",
        "DomainClass",
        "NaturalResourceThing",
        "01",
        "在空间中持续存在并可被调查、确权、规划或管制的现实对象。",
    ),
    _seed(
        "NaturalResource",
        "自然资源",
        "DomainClass",
        "NaturalResourceEntity",
        "02",
        "具有自然形成基础和资源利用、生态或资产价值的现实对象。",
    ),
    _seed(
        "Land",
        "土地",
        "DomainClass",
        "NaturalResource",
        "02",
        "由一定空间范围、地表及相关自然和利用属性构成的核心自然资源对象。",
    ),
    _seed(
        "SpatialUnit",
        "空间单元",
        "DomainClass",
        "NaturalResourceEntity",
        "01",
        "为调查、登记、规划、管控或管理而划定并具有稳定标识的空间范围。",
    ),
    _seed(
        "LandParcel",
        "地块",
        "DomainClass",
        "SpatialUnit",
        "02",
        "为调查、规划、管理或业务处理而划定边界并空间表征土地的空间单元。",
        "图斑",
    ),
    _seed(
        "CadastralParcel",
        "宗地",
        "DomainClass",
        "LandParcel",
        "03",
        "权属界址封闭且具有独立不动产单元语义的土地单元。",
    ),
    _seed(
        "AgriculturalLand",
        "农用地",
        "DomainClass",
        "Land",
        "02",
        "在某一有效时段主要用于农业生产及其直接服务活动的土地。",
    ),
    _seed(
        "ConstructionLand",
        "建设用地",
        "DomainClass",
        "Land",
        "02",
        "在某一有效时段用于建造建筑物、构筑物或其他建设活动的土地。",
    ),
    _seed(
        "UnusedLand",
        "未利用地",
        "DomainClass",
        "Land",
        "02",
        "在某一有效时段未归入农用地或建设用地利用状态的土地。",
    ),
    _seed(
        "CultivatedLand",
        "耕地",
        "DomainClass",
        "AgriculturalLand",
        "02",
        "用于种植农作物并按耕地制度调查、保护和管理的农用地。",
        "农田",
    ),
    _seed(
        "NonCultivatedAgriculturalLand",
        "非耕农用地",
        "DomainClass",
        "AgriculturalLand",
        "02",
        "除耕地以外用于农业生产或直接服务农业生产的农用地集合。",
    ),
    _seed(
        "PaddyField",
        "水田",
        "DomainClass",
        "CultivatedLand",
        "02",
        "用于种植水生作物、具备相应灌溉条件的耕地。",
    ),
    _seed(
        "IrrigatedLand",
        "水浇地",
        "DomainClass",
        "CultivatedLand",
        "02",
        "有水源和灌溉设施、一般年份能正常灌溉的耕地。",
    ),
    _seed(
        "DryLand",
        "旱地",
        "DomainClass",
        "CultivatedLand",
        "02",
        "主要依靠天然降水种植旱生作物的耕地。",
    ),
    _seed(
        "GardenLand",
        "园地",
        "DomainClass",
        "NonCultivatedAgriculturalLand",
        "02",
        "集约经营多年生作物的土地。",
    ),
    _seed(
        "ForestLand",
        "林地",
        "DomainClass",
        "NonCultivatedAgriculturalLand",
        "02",
        "生长乔木、竹类、灌木等林业植被并按林地管理的土地。",
    ),
    _seed(
        "GrassLand",
        "草地",
        "DomainClass",
        "NonCultivatedAgriculturalLand",
        "02",
        "生长草本植物并具有生态或牧业利用功能的土地。",
        "草原",
    ),
    _seed(
        "AgriculturalFacilityLand",
        "农业设施用地",
        "DomainClass",
        "NonCultivatedAgriculturalLand",
        "02",
        "直接服务于农业生产设施的土地；具体归类以适用标准和有效时点为准。",
        "设施农用地",
    ),
    _seed(
        "ResidentialLand",
        "居住用地",
        "DomainClass",
        "ConstructionLand",
        "04",
        "用于城乡居住及相应生活服务设施的建设用地。",
    ),
    _seed(
        "PublicServiceLand",
        "公共管理与公共服务用地",
        "DomainClass",
        "ConstructionLand",
        "04",
        "用于机关、教育、文化、体育、医疗和社会福利等公共服务的建设用地。",
    ),
    _seed(
        "CommercialServiceLand",
        "商业服务业用地",
        "DomainClass",
        "ConstructionLand",
        "04",
        "用于商业、商务金融、娱乐等服务业的建设用地。",
    ),
    _seed(
        "IndustrialMiningLand",
        "工矿用地",
        "DomainClass",
        "ConstructionLand",
        "04",
        "用于工业生产、采矿及其直接配套设施的建设用地。",
    ),
    _seed(
        "StorageLand",
        "仓储用地",
        "DomainClass",
        "ConstructionLand",
        "04",
        "用于物资储备、物流仓储设施的建设用地。",
    ),
    _seed(
        "TransportLand",
        "交通运输用地",
        "DomainClass",
        "ConstructionLand",
        "04",
        "用于铁路、公路、机场、港口、管道及交通场站的建设用地。",
    ),
    _seed(
        "UtilitiesLand",
        "公用设施用地",
        "DomainClass",
        "ConstructionLand",
        "04",
        "用于供水、排水、能源、通信、环卫、消防等公用设施的建设用地。",
    ),
    _seed(
        "GreenOpenSpaceLand",
        "绿地与开敞空间用地",
        "DomainClass",
        "ConstructionLand",
        "04",
        "城镇建设范围内承担游憩、防护或公共开放功能的土地。",
    ),
    _seed(
        "SpecialUseLand",
        "特殊用地",
        "DomainClass",
        "ConstructionLand",
        "04",
        "用于军事、宗教、文物保护、殡葬等特定用途的建设用地。",
    ),
    _seed(
        "VacantLand",
        "空闲地",
        "DomainClass",
        "UnusedLand",
        "02",
        "尚未确定现实利用活动或处于闲置状态的土地。",
    ),
    _seed(
        "SalineAlkaliLand",
        "盐碱地",
        "DomainClass",
        "UnusedLand",
        "02",
        "受盐碱作用影响且当前利用受限的土地。",
    ),
    _seed("SandyLand", "沙地", "DomainClass", "UnusedLand", "02", "地表主要由沙质物质覆盖的土地。"),
    _seed(
        "BareLand",
        "裸土地",
        "DomainClass",
        "UnusedLand",
        "02",
        "地表土质裸露、植被覆盖稀少的土地。",
    ),
    _seed(
        "BareRockGravelLand",
        "裸岩石砾地",
        "DomainClass",
        "UnusedLand",
        "02",
        "地表主要为裸露岩石或砾石的土地。",
    ),
    _seed(
        "WaterResource",
        "水资源",
        "DomainClass",
        "NaturalResource",
        "02",
        "地表水、地下水及其可利用或生态价值的资源对象。",
    ),
    _seed(
        "SurfaceWaterBody",
        "地表水体",
        "DomainClass",
        "WaterResource",
        "01",
        "在地表具有相对稳定空间范围的水体。",
    ),
    _seed(
        "River", "河流", "DomainClass", "SurfaceWaterBody", "01", "沿天然或人工河道流动的地表水体。"
    ),
    _seed(
        "Lake", "湖泊", "DomainClass", "SurfaceWaterBody", "01", "陆地洼地内相对静止的天然水体。"
    ),
    _seed(
        "Reservoir",
        "水库",
        "DomainClass",
        "SurfaceWaterBody",
        "01",
        "由水工程形成并调蓄水量的水体。",
    ),
    _seed(
        "Canal",
        "沟渠",
        "DomainClass",
        "SurfaceWaterBody",
        "01",
        "人工开挖或整治形成、用于输水、排水或航运的线性地表水体。",
        "渠道",
    ),
    _seed(
        "Pond",
        "池塘",
        "DomainClass",
        "SurfaceWaterBody",
        "01",
        "面积较小、相对静止且可为天然或人工形成的地表水体。",
        "山塘",
    ),
    _seed(
        "RiverSegment",
        "河流河段",
        "DomainClass",
        "SurfaceWaterBody",
        "01",
        "按拓扑、管理或观测需要划分并可关联整体河流的连续河段。",
        "地面河流",
    ),
    _seed(
        "WaterSystem",
        "水系",
        "DomainClass",
        "NaturalResourceEntity",
        "01",
        "由具有水文或连通关系的河流、沟渠、湖泊、水库、池塘及附属设施组成的整体。",
    ),
    _seed(
        "WaterConservancyFacility",
        "水利附属设施",
        "DomainClass",
        "NaturalResourceEntity",
        "01",
        "服务于取水、输水、调蓄、排水、防洪或水文管理的工程设施。",
    ),
    _seed(
        "GroundwaterBody",
        "地下水体",
        "DomainClass",
        "WaterResource",
        "02",
        "赋存于地下含水介质中的水资源对象。",
    ),
    _seed(
        "ForestResource",
        "森林资源",
        "DomainClass",
        "NaturalResource",
        "03",
        "由森林生态系统及其林木、林地等要素构成的资源对象。",
    ),
    _seed(
        "GrasslandResource",
        "草原资源",
        "DomainClass",
        "NaturalResource",
        "03",
        "由草原生态系统及其植被、土地等要素构成的资源对象。",
    ),
    _seed(
        "WetlandResource",
        "湿地资源",
        "DomainClass",
        "NaturalResource",
        "03",
        "具有显著水文、土壤和生物特征的湿地生态资源对象。",
    ),
    _seed(
        "MineralResource",
        "矿产资源",
        "DomainClass",
        "NaturalResource",
        "03",
        "经地质作用形成、具有利用价值的矿物或能源资源对象。",
    ),
    _seed(
        "MineralDeposit",
        "矿床",
        "DomainClass",
        "MineralResource",
        "03",
        "具有一定规模、形态和品位的矿产聚集体。",
    ),
    _seed(
        "MarineResource",
        "海洋资源",
        "DomainClass",
        "NaturalResource",
        "03",
        "海域、海岛、海岸带及其生物、矿产和空间资源对象。",
    ),
    _seed(
        "SeaArea", "海域", "DomainClass", "MarineResource", "03", "依法确定范围的海洋空间资源对象。"
    ),
    _seed(
        "Island",
        "海岛",
        "DomainClass",
        "MarineResource",
        "03",
        "四面环水且高潮时高于水面的自然形成陆地区域。",
    ),
    _seed(
        "BuiltStructure",
        "建构筑物",
        "DomainClass",
        "NaturalResourceEntity",
        "01",
        "由人工建造并占据稳定空间位置的建筑物、构筑物或设施实体。",
        "建构筑物及设施",
    ),
    _seed(
        "Building",
        "房屋建筑",
        "DomainClass",
        "BuiltStructure",
        "01",
        "具有屋盖、围护或内部空间并可承载居住、生产、服务等用途的建成实体。",
        "房屋",
        "建筑物",
    ),
    _seed(
        "ResidentialBuilding",
        "住宅建筑",
        "DomainClass",
        "Building",
        "01",
        "主要承担居住功能的建筑物。",
    ),
    _seed(
        "PublicBuilding",
        "公共建筑",
        "DomainClass",
        "Building",
        "01",
        "主要向公众或公共管理活动提供服务的建筑物。",
    ),
    _seed(
        "PublicFacility",
        "公共服务设施",
        "DomainClass",
        "BuiltStructure",
        "01",
        "承担公共管理、教育、医疗、文化、体育、福利、市政或交通服务功能的设施实体。",
    ),
    _seed(
        "EducationalFacility",
        "教育设施",
        "DomainClass",
        "PublicFacility",
        "01",
        "用于幼儿园、学校及其他教育活动的设施实体。",
        "学校",
    ),
    _seed(
        "MedicalFacility",
        "医疗卫生设施",
        "DomainClass",
        "PublicFacility",
        "01",
        "用于医院、卫生服务中心、卫生站等医疗卫生服务的设施实体。",
        "医疗机构",
    ),
    _seed(
        "CulturalFacility",
        "文化设施",
        "DomainClass",
        "PublicFacility",
        "01",
        "用于博物馆、图书馆、科技馆、艺术馆、剧场、文化馆等文化服务的设施实体。",
        "文艺场馆",
        "文化活动设施",
    ),
    _seed(
        "WelfareFacility",
        "社会福利设施",
        "DomainClass",
        "PublicFacility",
        "01",
        "提供养老、儿童福利、救助或其他社会福利服务的设施实体。",
        "福利机构",
    ),
    _seed(
        "SportsFacility",
        "体育设施",
        "DomainClass",
        "PublicFacility",
        "01",
        "用于体育训练、比赛、健身或群众体育活动的场馆、场地或设施。",
        "体育活动场馆",
        "露天体育场",
    ),
    _seed(
        "UtilityFacility",
        "公用设施",
        "DomainClass",
        "PublicFacility",
        "01",
        "承担供水、排水、能源、通信、环卫、消防等城市运行保障功能的设施实体。",
    ),
    _seed(
        "TransportStation",
        "交通运输场站",
        "DomainClass",
        "PublicFacility",
        "01",
        "为客货运输、换乘、停车或交通服务提供空间和设施的场站实体。",
        "交通服务场站",
        "地面公共停车场",
    ),
    _seed(
        "EmergencyShelter",
        "应急避难场所",
        "DomainClass",
        "PublicFacility",
        "05",
        "经规划或认定用于突发事件人员避险和安置的场所实体。",
    ),
    _seed(
        "GreenOpenSpace",
        "公园绿地",
        "DomainClass",
        "PublicFacility",
        "01",
        "具有公共开放、游憩、生态或防护功能的公园、广场及人工绿地实体。",
        "人工绿地",
        "公园广场",
    ),
    _seed(
        "Cemetery",
        "殡葬设施",
        "DomainClass",
        "BuiltStructure",
        "01",
        "用于安葬、纪念或相关殡葬服务的场地和设施实体。",
        "殡葬场院",
    ),
    _seed(
        "ResidentialCompound",
        "城镇住宅小区",
        "DomainClass",
        "SpatialUnit",
        "01",
        "由住宅建筑、配套设施和公共空间组成并具有相对稳定边界的居住空间单元。",
        "住宅小区",
    ),
    _seed(
        "Courtyard",
        "院落",
        "DomainClass",
        "SpatialUnit",
        "01",
        "由边界围合并承载一个或多个建筑及其附属空间的建成环境空间单元。",
        "场院",
    ),
    _seed(
        "AdministrativeUnit",
        "行政区",
        "DomainClass",
        "SpatialUnit",
        "01",
        "由法定行政界线确定的空间管理单元。",
    ),
    _seed(
        "Subdistrict",
        "街道行政区",
        "DomainClass",
        "AdministrativeUnit",
        "01",
        "街道办事处依法管理的行政范围。",
        "街道",
    ),
    _seed(
        "Village",
        "村级行政区",
        "DomainClass",
        "AdministrativeUnit",
        "01",
        "村民委员会所对应的基层行政管理范围。",
        "村行政范围",
    ),
    _seed(
        "Community",
        "社区",
        "DomainClass",
        "AdministrativeUnit",
        "01",
        "城市基层治理和公共服务组织所对应的社区范围。",
    ),
    _seed(
        "AdministrativePlace",
        "行政机构地点",
        "DomainClass",
        "SpatialUnit",
        "01",
        "用于标注行政机构所在位置并关联其行政范围的点状空间单元。",
    ),
    _seed(
        "SubdistrictOfficeSite",
        "街道办事处地点",
        "DomainClass",
        "AdministrativePlace",
        "01",
        "街道办事处办公机构所在位置的空间标注实体。",
    ),
    _seed(
        "VillageCommitteeSite",
        "村民委员会地点",
        "DomainClass",
        "AdministrativePlace",
        "01",
        "村民委员会办公机构所在位置的空间标注实体。",
        "村委会所在地点",
    ),
    _seed(
        "PlanningUnit",
        "规划单元",
        "DomainClass",
        "SpatialUnit",
        "04",
        "为国土空间规划编制、传导和实施管理划定的空间单元。",
    ),
    _seed(
        "PlannedLandUseArea",
        "规划用地用海单元",
        "DomainClass",
        "PlanningUnit",
        "04",
        "承载规划用地用海分类及空间范围的规划单元。",
        "规划用地用海",
    ),
    _seed(
        "PlanningZone",
        "规划分区",
        "DomainClass",
        "PlanningUnit",
        "04",
        "依据国土空间规划管控目标和主导功能划定的规划管理区域。",
    ),
    _seed(
        "NaturalResourceRegistrationUnit",
        "自然资源登记单元",
        "DomainClass",
        "SpatialUnit",
        "03",
        "为自然资源统一确权登记划定的空间单元。",
    ),
    _seed(
        "ControlBoundary",
        "管控边界",
        "DomainClass",
        "SpatialUnit",
        "05",
        "承载空间准入、保护或开发约束的边界或范围。",
    ),
    _seed(
        "EcologicalConservationRedline",
        "生态保护红线",
        "DomainClass",
        "ControlBoundary",
        "05",
        "在生态空间范围内具有特殊重要生态功能、必须强制性严格保护的区域边界。",
    ),
    _seed(
        "PermanentBasicFarmland",
        "永久基本农田",
        "DomainClass",
        "ControlBoundary",
        "05",
        "依法划定并实行特殊保护的耕地范围。",
    ),
    _seed(
        "UrbanDevelopmentBoundary",
        "城镇开发边界",
        "DomainClass",
        "ControlBoundary",
        "05",
        "在一定时期内允许城镇开发建设的空间边界。",
    ),
    _seed(
        "UrbanFourLine",
        "城市四线",
        "DomainClass",
        "ControlBoundary",
        "05",
        "中心城区蓝线、绿线、黄线和紫线等法定规划控制线的总类。",
    ),
    _seed(
        "UrbanBlueLine",
        "城市蓝线",
        "DomainClass",
        "UrbanFourLine",
        "05",
        "依法划定并保护城市地表水体的规划控制线。",
        "中心城区城市蓝线",
    ),
    _seed(
        "UrbanGreenLine",
        "城市绿线",
        "DomainClass",
        "UrbanFourLine",
        "05",
        "依法划定并保护城市各类绿地范围的规划控制线。",
        "中心城区城市绿线",
    ),
    _seed(
        "UrbanYellowLine",
        "城市黄线",
        "DomainClass",
        "UrbanFourLine",
        "05",
        "依法划定城市基础设施用地控制界线。",
        "中心城区城市黄线",
    ),
    _seed(
        "UrbanPurpleLine",
        "城市紫线",
        "DomainClass",
        "UrbanFourLine",
        "05",
        "依法划定历史文化街区和历史建筑保护范围的规划控制线。",
        "中心城区城市紫线",
    ),
    _seed(
        "NaturalResourceState",
        "自然资源状态",
        "StateClass",
        "NaturalResourceThing",
        "02",
        "自然资源对象在一个有效时段内具有的可变化情形。",
    ),
    _seed(
        "ObservedState",
        "观测状态",
        "StateClass",
        "NaturalResourceState",
        "02",
        "由调查、监测或其他证据确认的自然资源现实状态。",
    ),
    _seed(
        "PlannedState",
        "规划状态",
        "StateClass",
        "NaturalResourceState",
        "04",
        "由生效规划或管理方案表达的自然资源目标状态。",
    ),
    _seed(
        "LandUseState",
        "土地利用状态",
        "StateClass",
        "NaturalResourceState",
        "02",
        "地块在指定有效时段内的土地利用分类状态。",
    ),
    _seed(
        "ObservedLandUseState",
        "现状土地利用状态",
        "StateClass",
        "LandUseState",
        "02",
        "经调查或监测确认的地块现实土地利用状态。",
        "现状用地状态",
    ),
    _seed(
        "PlannedLandUseState",
        "规划土地利用状态",
        "StateClass",
        "LandUseState",
        "04",
        "由生效国土空间规划表达的地块目标土地利用状态。",
        "规划用地状态",
    ),
    _seed(
        "AgriculturalLandUseState",
        "农用地利用状态",
        "StateClass",
        "LandUseState",
        "02",
        "地块在有效时段内被分类为农用地的状态。",
    ),
    _seed(
        "ConstructionLandUseState",
        "建设用地利用状态",
        "StateClass",
        "LandUseState",
        "02",
        "地块在有效时段内被分类为建设用地的状态。",
    ),
    _seed(
        "UnusedLandUseState",
        "未利用地利用状态",
        "StateClass",
        "LandUseState",
        "02",
        "地块在有效时段内被分类为未利用地的状态。",
    ),
    _seed(
        "CultivatedLandUseState",
        "耕地利用状态",
        "StateClass",
        "AgriculturalLandUseState",
        "02",
        "地块在有效时段内被分类为耕地的状态。",
    ),
    _seed(
        "NonCultivatedAgriculturalLandUseState",
        "非耕农用地利用状态",
        "StateClass",
        "AgriculturalLandUseState",
        "02",
        "地块在有效时段内被分类为非耕农用地的状态。",
    ),
    _seed(
        "RightState",
        "权利状态",
        "StateClass",
        "NaturalResourceState",
        "03",
        "自然资源权利在有效、限制、注销等生命周期阶段的状态。",
    ),
    _seed(
        "QualityState",
        "质量状态",
        "StateClass",
        "NaturalResourceState",
        "02",
        "自然资源对象在质量评价时点或时段内的状态。",
    ),
    _seed(
        "NaturalResourceActivity",
        "自然资源活动",
        "ProcessClass",
        "NaturalResourceThing",
        "02",
        "随时间发生并可能改变、认知或管理自然资源对象的过程。",
    ),
    _seed(
        "SurveyActivity",
        "调查活动",
        "ProcessClass",
        "NaturalResourceActivity",
        "02",
        "获取自然资源位置、范围、属性或权属信息的活动。",
    ),
    _seed(
        "MonitoringActivity",
        "监测活动",
        "ProcessClass",
        "NaturalResourceActivity",
        "02",
        "持续或周期性观测自然资源状态及变化的活动。",
    ),
    _seed(
        "LandUseTransition",
        "土地利用转换",
        "ProcessClass",
        "NaturalResourceActivity",
        "06",
        "使地块从一个有时效的土地利用状态转移到另一个状态的过程。",
    ),
    _seed(
        "AgriculturalStructureAdjustment",
        "农业结构调整",
        "ProcessClass",
        "LandUseTransition",
        "06",
        "在符合法律政策和用途管制要求的前提下，造成耕地与非耕农用地利用状态转换的农业生产结构调整过程。",
    ),
    _seed(
        "ConstructionOccupation",
        "建设占用",
        "ProcessClass",
        "LandUseTransition",
        "06",
        "经依法审批，由建设活动占用农用地并形成建设用地利用状态的过程。",
        "农用地转用",
    ),
    _seed(
        "LandReclamation",
        "土地复垦",
        "ProcessClass",
        "LandUseTransition",
        "07",
        "对生产建设损毁或退化土地采取整治措施以恢复可利用状态的过程。",
    ),
    _seed(
        "LandConsolidation",
        "土地整治",
        "ProcessClass",
        "LandUseTransition",
        "07",
        "通过工程、生物或管理措施改善土地利用条件和空间格局的过程。",
    ),
    _seed(
        "EcologicalRestoration",
        "生态修复",
        "ProcessClass",
        "NaturalResourceActivity",
        "05",
        "修复受损自然生态系统结构、过程和功能的活动。",
    ),
    _seed(
        "LandExpropriation",
        "土地征收",
        "ProcessClass",
        "NaturalResourceActivity",
        "06",
        "国家基于公共利益并依照法定程序将集体所有土地征为国有的行政过程。",
    ),
    _seed(
        "LandSupply",
        "土地供应",
        "ProcessClass",
        "NaturalResourceActivity",
        "07",
        "依法配置国有建设用地使用权的行政和市场过程。",
    ),
    _seed(
        "UseApproval",
        "用途审批",
        "ProcessClass",
        "NaturalResourceActivity",
        "06",
        "对自然资源用途或用途变化进行审查并作出行政决定的过程。",
    ),
    _seed(
        "RightRegistration",
        "权利登记",
        "ProcessClass",
        "NaturalResourceActivity",
        "03",
        "将自然资源权利及其变动记载于法定登记簿的过程。",
    ),
    _seed(
        "EnforcementInspection",
        "执法检查",
        "ProcessClass",
        "NaturalResourceActivity",
        "08",
        "检查自然资源开发利用行为是否符合法律、规划和管制要求的活动。",
    ),
    _seed(
        "NaturalResourceObservation",
        "自然资源观测",
        "ObservationClass",
        "NaturalResourceThing",
        "02",
        "对自然资源对象、状态或过程在指定时空范围内形成的观测结果。",
    ),
    _seed(
        "LandChangeObservation",
        "土地变化观测",
        "ObservationClass",
        "NaturalResourceObservation",
        "02",
        "记录地块利用类别、范围或质量变化的观测结果。",
    ),
    _seed(
        "QualityAssessment",
        "质量评价",
        "ObservationClass",
        "NaturalResourceObservation",
        "02",
        "依据评价规则形成的自然资源质量判断结果。",
    ),
    _seed(
        "UrbanFormAssessment",
        "城市形态评价",
        "ObservationClass",
        "QualityAssessment",
        "09",
        "对院落、社区或行政单元的建筑形态、强度、年代和空间品质进行的评价。",
    ),
    _seed(
        "BuiltEnvironmentAssessment",
        "建成环境评价",
        "ObservationClass",
        "QualityAssessment",
        "09",
        "对建筑、用地权属、住房、服务设施和开发状况进行的综合评价。",
    ),
    _seed(
        "ServiceCoverageObservation",
        "公共服务覆盖观测",
        "ObservationClass",
        "NaturalResourceObservation",
        "09",
        "在明确空间范围、出行方式和时间阈值下形成的公共服务可达覆盖结果。",
        "可达覆盖率",
    ),
    _seed(
        "WaterBodyObservation",
        "水体观测",
        "ObservationClass",
        "NaturalResourceObservation",
        "02",
        "对水体面积、深度、宽度、长度、容积或通航等状态形成的观测结果。",
    ),
    _seed(
        "NaturalResourceRight",
        "自然资源权利",
        "InformationClass",
        "NaturalResourceThing",
        "03",
        "由法律确认、以自然资源对象为客体并由特定主体享有的权利。",
    ),
    _seed(
        "Ownership",
        "所有权",
        "InformationClass",
        "NaturalResourceRight",
        "03",
        "权利人依法对自然资源享有占有、使用、收益和处分的权利。",
    ),
    _seed(
        "Usufruct",
        "用益物权",
        "InformationClass",
        "NaturalResourceRight",
        "03",
        "权利人依法对他人所有的自然资源享有占有、使用和收益的权利。",
    ),
    _seed(
        "LandUseRight",
        "土地使用权",
        "InformationClass",
        "Usufruct",
        "03",
        "依法对土地占有、使用并取得收益的权利。",
    ),
    _seed(
        "ContractedManagementRight",
        "土地承包经营权",
        "InformationClass",
        "Usufruct",
        "03",
        "以家庭承包等方式依法取得的农村土地承包经营权。",
    ),
    _seed(
        "ExplorationRight",
        "探矿权",
        "InformationClass",
        "NaturalResourceRight",
        "03",
        "在许可证规定范围和期限内勘查矿产资源的权利。",
    ),
    _seed(
        "MiningRight",
        "采矿权",
        "InformationClass",
        "NaturalResourceRight",
        "03",
        "在许可证规定范围和期限内开采矿产资源并取得矿产品的权利。",
    ),
    _seed(
        "SpatialPlan",
        "国土空间规划",
        "InformationClass",
        "NaturalResourceThing",
        "04",
        "对一定区域国土空间保护、开发、利用和修复作出的总体安排。",
    ),
    _seed(
        "LandUseClassification",
        "用地用海分类",
        "InformationClass",
        "NaturalResourceThing",
        "04",
        "用于表达现状或规划用地用海类别的受控分类体系及分类概念。",
        "用地用海分类名称",
        "地类名称",
    ),
    _seed(
        "BuiltEnvironmentIndicator",
        "建成环境指标",
        "InformationClass",
        "NaturalResourceThing",
        "09",
        "用于量化建筑形态、开发强度、住房、权属或空间品质的指标定义。",
    ),
    _seed(
        "UrbanFormIndicator",
        "城市形态指标",
        "InformationClass",
        "BuiltEnvironmentIndicator",
        "09",
        "用于描述建筑数量、高度、密度、容积率、拥挤度或整齐度的指标定义。",
    ),
    _seed(
        "LandUseIntensityIndicator",
        "土地利用强度指标",
        "InformationClass",
        "BuiltEnvironmentIndicator",
        "09",
        "用于描述地上地下开发强度、功能比例和增量空间的指标定义。",
    ),
    _seed(
        "HousingIndicator",
        "住房指标",
        "InformationClass",
        "BuiltEnvironmentIndicator",
        "09",
        "用于描述住房面积、套数、年代、性质或价格的指标定义。",
    ),
    _seed(
        "AccessibilityIndicator",
        "公共服务可达性指标",
        "InformationClass",
        "BuiltEnvironmentIndicator",
        "09",
        "在给定出行方式和时间阈值下度量公共服务可达性或覆盖率的指标定义。",
    ),
    _seed(
        "Measurement",
        "测量值",
        "InformationClass",
        "NaturalResourceThing",
        "02",
        "由数值、单位、测量时间和方法共同限定的可追溯测量结果。",
    ),
    _seed(
        "MeasurementUnit",
        "计量单位",
        "InformationClass",
        "NaturalResourceThing",
        "10",
        "用于解释和比较测量数值量纲的受控单位。",
    ),
    _seed(
        "AggregationContext",
        "统计聚合上下文",
        "InformationClass",
        "NaturalResourceThing",
        "09",
        "声明指标计算的空间范围、统计周期、聚合方法和数据版本的上下文。",
    ),
    _seed(
        "DistanceThreshold",
        "可达时间或距离阈值",
        "InformationClass",
        "NaturalResourceThing",
        "09",
        "公共服务可达性计算采用的时间或距离限制条件。",
    ),
    _seed(
        "TravelMode",
        "出行方式",
        "InformationClass",
        "NaturalResourceThing",
        "09",
        "公共服务可达性计算采用的步行、驾车、消防救援等移动方式。",
    ),
    _seed(
        "PopulationDenominator",
        "人口分母",
        "InformationClass",
        "NaturalResourceThing",
        "09",
        "人均或每十万人指标计算所采用的人口口径、时点和数值。",
    ),
    _seed(
        "NaturalResourceRule",
        "自然资源规则",
        "InformationClass",
        "NaturalResourceThing",
        "06",
        "用于规范自然资源调查、保护、规划、利用或监管行为的可识别规则。",
    ),
    _seed(
        "LegalRule",
        "法律规则",
        "InformationClass",
        "NaturalResourceRule",
        "06",
        "由有效法律、法规或规章确立的自然资源规范。",
    ),
    _seed(
        "PlanningRule",
        "规划规则",
        "InformationClass",
        "NaturalResourceRule",
        "04",
        "由生效国土空间规划确立的空间配置、准入或控制规则。",
    ),
    _seed(
        "UseControlRule",
        "用途管制规则",
        "InformationClass",
        "NaturalResourceRule",
        "06",
        "规定空间准入、用途许可、禁止或条件要求的规则。",
    ),
    _seed(
        "DataQualityRule",
        "数据质量规则",
        "InformationClass",
        "NaturalResourceRule",
        "10",
        "用于检验自然资源数据完整性、一致性、准确性或时效性的规则。",
    ),
    _seed(
        "NaturalResourceRestriction",
        "自然资源限制",
        "InformationClass",
        "NaturalResourceThing",
        "06",
        "对自然资源权利行使、用途或空间活动施加的禁止、条件或限度。",
    ),
    _seed(
        "RightRestriction",
        "权利限制",
        "InformationClass",
        "NaturalResourceRestriction",
        "03",
        "依法对自然资源权利的设立、变更、转让或行使施加的限制。",
    ),
    _seed(
        "UseRestriction",
        "用途限制",
        "InformationClass",
        "NaturalResourceRestriction",
        "06",
        "对自然资源用途或用途转换施加的禁止、条件或限度。",
    ),
    _seed(
        "PlanningRestriction",
        "规划限制",
        "InformationClass",
        "NaturalResourceRestriction",
        "04",
        "由生效规划对空间开发、保护或利用活动施加的限制。",
    ),
    _seed(
        "LegalBasis",
        "法律政策依据",
        "InformationClass",
        "NaturalResourceThing",
        "06",
        "支撑管理活动或状态变更合法性的法律、法规、政策或标准依据。",
    ),
    _seed(
        "ApprovalDocument",
        "审批文件",
        "InformationClass",
        "NaturalResourceThing",
        "06",
        "由有权机关对申请事项作出的可追溯行政决定载体。",
    ),
    _seed(
        "EvidenceArtifact",
        "证据材料",
        "InformationClass",
        "NaturalResourceThing",
        "08",
        "用于证明自然资源事实、过程或行政行为的材料。",
    ),
    _seed(
        "SurveyEvidence",
        "调查证据",
        "InformationClass",
        "EvidenceArtifact",
        "02",
        "由调查活动形成并可复核自然资源位置、范围、属性或权属的证据。",
    ),
    _seed(
        "ObservationEvidence",
        "观测证据",
        "InformationClass",
        "EvidenceArtifact",
        "02",
        "由监测或观测活动形成并支持状态判断的证据。",
    ),
    _seed(
        "ApprovalEvidence",
        "审批证据",
        "InformationClass",
        "EvidenceArtifact",
        "06",
        "证明行政审批决定、依据和过程的证据。",
    ),
    _seed(
        "SpatialAnalysisEvidence",
        "空间分析证据",
        "InformationClass",
        "EvidenceArtifact",
        "05",
        "由可复现空间分析形成并支持叠加、邻接或范围判断的证据。",
    ),
    # Cross-volume concepts curated from the EA repository and all ten
    # natural-resource standard volumes. These are domain semantics, not
    # source table names or application capabilities.
    _seed(
        "GeographicName",
        "地理名称",
        "DomainClass",
        "NaturalResourceEntity",
        "01",
        "用于唯一或约定俗成地指称自然地物、人工设施或行政地域的名称实体。",
        "地名",
    ),
    _seed(
        "AddressPoint",
        "地址点",
        "DomainClass",
        "AdministrativePlace",
        "01",
        "表达门址、院落或设施位置并可关联规范地址的空间定位实体。",
        "地名地址",
    ),
    _seed(
        "Road",
        "道路",
        "DomainClass",
        "BuiltStructure",
        "01",
        "供车辆或行人通行并具有连续空间走向的交通基础设施。",
    ),
    _seed(
        "Railway",
        "铁路",
        "DomainClass",
        "BuiltStructure",
        "01",
        "由轨道、路基及附属设施组成的铁路交通基础设施。",
    ),
    _seed(
        "TerrainUnit",
        "地形单元",
        "DomainClass",
        "NaturalResourceEntity",
        "01",
        "依据地貌、坡度、高程或地形连续性划分的自然地表单元。",
    ),
    _seed(
        "SurveyControlPoint",
        "测量控制点",
        "DomainClass",
        "SpatialUnit",
        "01",
        "具有法定或测绘技术坐标、高程及等级的测量基准点。",
    ),
    _seed(
        "SoilResource",
        "土壤资源",
        "DomainClass",
        "NaturalResource",
        "02",
        "由土壤类型、质量、肥力及其空间分布构成的自然资源对象。",
    ),
    _seed(
        "GeologicResource",
        "地质资源",
        "DomainClass",
        "NaturalResource",
        "02",
        "由地层、岩体、构造及地质环境条件构成的资源与环境对象。",
    ),
    _seed(
        "GeologicUnit",
        "地质单元",
        "DomainClass",
        "GeologicResource",
        "02",
        "具有相对一致地层、岩性或成因特征的地质空间单元。",
    ),
    _seed(
        "GeologicStructure",
        "地质构造",
        "DomainClass",
        "GeologicResource",
        "02",
        "由构造运动形成并具有可识别形态和空间范围的地质结构。",
    ),
    _seed(
        "GeologicalHazard",
        "地质灾害",
        "DomainClass",
        "NaturalResourceEntity",
        "02",
        "由自然地质作用或人类活动诱发并可能造成人员财产损失的灾害对象。",
    ),
    _seed(
        "MonitoringStation",
        "监测站点",
        "DomainClass",
        "SpatialUnit",
        "02",
        "持续或周期性采集自然资源状态与环境变化数据的固定空间位置。",
    ),
    _seed(
        "SurveyPlot",
        "调查样地",
        "DomainClass",
        "SpatialUnit",
        "02",
        "为资源调查、样本观测或质量评价划定的样本空间单元。",
    ),
    _seed(
        "ProtectedNaturalArea",
        "自然保护地",
        "DomainClass",
        "ControlBoundary",
        "05",
        "依法划定并以自然生态系统、自然遗迹或生物多样性保护为主要目的的区域。",
    ),
    _seed(
        "NatureReserve",
        "自然保护区",
        "DomainClass",
        "ProtectedNaturalArea",
        "05",
        "依法划定并实施严格保护管理的自然保护地。",
    ),
    _seed(
        "ForestPark",
        "森林公园",
        "DomainClass",
        "ProtectedNaturalArea",
        "05",
        "以森林生态系统和景观资源保护利用为主要目的的自然保护地。",
    ),
    _seed(
        "WetlandPark",
        "湿地公园",
        "DomainClass",
        "ProtectedNaturalArea",
        "05",
        "以湿地生态系统保护、恢复和合理利用为主要目的的自然保护地。",
    ),
    _seed(
        "Geopark",
        "地质公园",
        "DomainClass",
        "ProtectedNaturalArea",
        "05",
        "以具有重要价值的地质遗迹保护和展示为主要目的的自然保护地。",
    ),
    _seed(
        "NaturalHeritageSite",
        "自然遗产地",
        "DomainClass",
        "ProtectedNaturalArea",
        "05",
        "因突出自然价值而依法或依国际公约确认的保护区域。",
    ),
    _seed(
        "DisasterRiskZone",
        "灾害风险区",
        "DomainClass",
        "ControlBoundary",
        "05",
        "依据危险性、暴露度和脆弱性评价划定的灾害风险管理区域。",
    ),
    _seed(
        "GeologicalHazardRiskZone",
        "地质灾害风险区",
        "DomainClass",
        "DisasterRiskZone",
        "05",
        "针对崩塌、滑坡、泥石流等地质灾害划定的风险区域。",
    ),
    _seed(
        "FloodRiskZone",
        "洪涝风险区",
        "DomainClass",
        "DisasterRiskZone",
        "05",
        "依据洪水或内涝危险性与承灾体暴露情况划定的风险区域。",
    ),
    _seed(
        "CultivatedLandReserve",
        "补充耕地储备区",
        "DomainClass",
        "ControlBoundary",
        "05",
        "经调查评价可用于补充耕地并纳入储备管理的空间范围。",
    ),
    _seed(
        "BasicFarmlandReserve",
        "永久基本农田储备区",
        "DomainClass",
        "ControlBoundary",
        "05",
        "用于永久基本农田补划和动态优化的后备空间范围。",
    ),
    _seed(
        "SuspectedChangePatch",
        "疑似变化图斑",
        "DomainClass",
        "SpatialUnit",
        "08",
        "由遥感监测或其他线索识别、尚待核查处置的疑似变化空间单元。",
    ),
    _seed(
        "Household",
        "住户",
        "DomainClass",
        "NaturalResourceThing",
        "09",
        "在统计或住房分析中作为共同居住和生活单位的人口主体。",
    ),
    _seed(
        "PopulationGroup",
        "人口群体",
        "DomainClass",
        "NaturalResourceThing",
        "09",
        "按行政区域、年龄、性别、就业或其他统计口径界定的人口集合。",
    ),
    _seed(
        "ResourceInventory",
        "资源清查",
        "ProcessClass",
        "SurveyActivity",
        "03",
        "对自然资源实物量、权属、利用状况和价值信息进行系统调查核实的活动。",
    ),
    _seed(
        "ResourceValuation",
        "资源资产评价",
        "ProcessClass",
        "NaturalResourceActivity",
        "03",
        "依据统一口径测算自然资源资产实物量、价格或经济价值的活动。",
    ),
    _seed(
        "ResourceDevelopmentActivity",
        "资源开发利用",
        "ProcessClass",
        "NaturalResourceActivity",
        "07",
        "对土地、矿产、海洋、森林等资源进行依法开发或利用的活动。",
    ),
    _seed(
        "MineralExtraction",
        "矿产开采",
        "ProcessClass",
        "ResourceDevelopmentActivity",
        "07",
        "在采矿权及许可范围内开采矿产资源的活动。",
    ),
    _seed(
        "LandReserveActivity",
        "土地储备",
        "ProcessClass",
        "NaturalResourceActivity",
        "07",
        "依法取得、整理、管护并为供应准备国有建设用地的活动。",
    ),
    _seed(
        "AdministrativeApplication",
        "行政申请",
        "ProcessClass",
        "NaturalResourceActivity",
        "06",
        "申请主体向有权机关提出自然资源许可、审批或登记事项的活动。",
    ),
    _seed(
        "PermitReview",
        "许可审查",
        "ProcessClass",
        "NaturalResourceActivity",
        "06",
        "有权机关对自然资源行政许可申请进行受理、审查和决定的过程。",
    ),
    _seed(
        "ViolationInvestigation",
        "违法案件调查",
        "ProcessClass",
        "EnforcementInspection",
        "08",
        "对涉嫌违反自然资源法律、规划或许可要求的行为进行调查取证的活动。",
    ),
    _seed(
        "RectificationActivity",
        "整改活动",
        "ProcessClass",
        "NaturalResourceActivity",
        "08",
        "责任主体依据执法决定纠正违法或不合规状态的活动。",
    ),
    _seed(
        "StatisticalObservation",
        "统计观测",
        "ObservationClass",
        "NaturalResourceObservation",
        "09",
        "在明确统计区域、时期、指标定义和口径下形成的汇总观测结果。",
    ),
    _seed(
        "AssetValuationObservation",
        "资产价值评价",
        "ObservationClass",
        "QualityAssessment",
        "03",
        "对自然资源资产数量、价格或经济价值形成的可追溯评价结果。",
    ),
    _seed(
        "RiskAssessment",
        "风险评价",
        "ObservationClass",
        "QualityAssessment",
        "05",
        "对危险性、暴露度、脆弱性或损失后果进行综合判断的评价结果。",
    ),
    _seed(
        "InspectionFinding",
        "执法检查发现",
        "ObservationClass",
        "NaturalResourceObservation",
        "08",
        "执法检查或线索核查对违法事实、范围和状态形成的判断结果。",
    ),
    _seed(
        "NaturalResourceAsset",
        "自然资源资产",
        "InformationClass",
        "NaturalResourceThing",
        "03",
        "自然资源对象在统一清查、核算和管理口径下形成的资产信息表达。",
    ),
    _seed(
        "LandAsset",
        "土地资源资产",
        "InformationClass",
        "NaturalResourceAsset",
        "03",
        "土地资源实物量、权利、利用状况和价值的资产信息表达。",
    ),
    _seed(
        "ForestAsset",
        "森林资源资产",
        "InformationClass",
        "NaturalResourceAsset",
        "03",
        "森林资源实物量、权利、生态功能和价值的资产信息表达。",
    ),
    _seed(
        "GrasslandAsset",
        "草原资源资产",
        "InformationClass",
        "NaturalResourceAsset",
        "03",
        "草原资源实物量、权利、利用状况和价值的资产信息表达。",
    ),
    _seed(
        "WetlandAsset",
        "湿地资源资产",
        "InformationClass",
        "NaturalResourceAsset",
        "03",
        "湿地资源实物量、权利、生态功能和价值的资产信息表达。",
    ),
    _seed(
        "MineralAsset",
        "矿产资源资产",
        "InformationClass",
        "NaturalResourceAsset",
        "03",
        "矿产资源储量、矿业权、开发利用和价值的资产信息表达。",
    ),
    _seed(
        "MarineAsset",
        "海洋资源资产",
        "InformationClass",
        "NaturalResourceAsset",
        "03",
        "海域、海岛及相关资源权利和价值的资产信息表达。",
    ),
    _seed(
        "SeaUseRight",
        "海域使用权",
        "InformationClass",
        "Usufruct",
        "03",
        "依法在一定期限和范围内使用特定海域的权利。",
    ),
    _seed(
        "ForestManagementRight",
        "林地经营权",
        "InformationClass",
        "Usufruct",
        "03",
        "依法对林地进行经营并取得收益的权利。",
    ),
    _seed(
        "MasterPlan",
        "总体规划",
        "InformationClass",
        "SpatialPlan",
        "04",
        "对行政区域国土空间保护、开发、利用和修复作出总体安排的规划。",
    ),
    _seed(
        "DetailedPlan",
        "详细规划",
        "InformationClass",
        "SpatialPlan",
        "04",
        "对特定建设区域空间用途和开发建设提出实施性安排的规划。",
    ),
    _seed(
        "VillagePlan",
        "村庄规划",
        "InformationClass",
        "SpatialPlan",
        "04",
        "对村域国土空间保护、开发、建设和整治作出安排的规划。",
    ),
    _seed(
        "SpecialPlan",
        "专项规划",
        "InformationClass",
        "SpatialPlan",
        "04",
        "围绕特定自然资源领域或空间功能形成的专项安排。",
    ),
    _seed(
        "PlanningIndicator",
        "规划指标",
        "InformationClass",
        "NaturalResourceThing",
        "04",
        "用于表达规划目标、规模、结构、强度或约束要求的指标定义。",
    ),
    _seed(
        "AdministrativePermit",
        "行政许可",
        "InformationClass",
        "ApprovalDocument",
        "06",
        "有权机关准予申请主体从事特定自然资源活动的行政决定。",
    ),
    _seed(
        "SiteSelectionPermit",
        "用地预审与选址意见",
        "InformationClass",
        "AdministrativePermit",
        "06",
        "建设项目用地预审与规划选址事项的行政许可结果。",
    ),
    _seed(
        "ConstructionLandApproval",
        "建设用地审批",
        "InformationClass",
        "AdministrativePermit",
        "06",
        "依法批准农用地转用、土地征收或建设用地使用的行政决定。",
    ),
    _seed(
        "TemporaryLandApproval",
        "临时用地审批",
        "InformationClass",
        "AdministrativePermit",
        "06",
        "依法批准在限定期限内临时使用土地的行政决定。",
    ),
    _seed(
        "ExplorationPermit",
        "勘查许可证",
        "InformationClass",
        "AdministrativePermit",
        "06",
        "准予在规定范围和期限内开展矿产勘查活动的许可证。",
    ),
    _seed(
        "MiningPermit",
        "采矿许可证",
        "InformationClass",
        "AdministrativePermit",
        "06",
        "准予在规定范围和期限内开展矿产开采活动的许可证。",
    ),
    _seed(
        "SeaUsePermit",
        "海域使用审批",
        "InformationClass",
        "AdministrativePermit",
        "06",
        "准予在规定范围、用途和期限内使用海域的行政决定。",
    ),
    _seed(
        "SurveyRecord",
        "调查记录",
        "InformationClass",
        "EvidenceArtifact",
        "02",
        "记录调查主体、时间、方法、意见及复核情况的证据材料。",
    ),
    _seed(
        "RegistrationRecord",
        "登记记录",
        "InformationClass",
        "EvidenceArtifact",
        "03",
        "记录自然资源权利受理、审核、登簿、发证和归档过程的证据材料。",
    ),
    _seed(
        "ViolationCase",
        "违法案件",
        "InformationClass",
        "EvidenceArtifact",
        "08",
        "对涉嫌自然资源违法行为的线索、事实、证据和处置过程形成的案件信息。",
    ),
    _seed(
        "EnforcementDecision",
        "执法决定",
        "InformationClass",
        "ApprovalDocument",
        "08",
        "执法机关对违法事实和法律责任作出的行政处理决定。",
    ),
    _seed(
        "RectificationOrder",
        "整改要求",
        "InformationClass",
        "NaturalResourceRule",
        "08",
        "要求责任主体在规定期限内纠正违法或不合规状态的具体要求。",
    ),
    _seed(
        "DemographicIndicator",
        "人口指标",
        "InformationClass",
        "BuiltEnvironmentIndicator",
        "09",
        "描述人口规模、结构、流动或城镇化特征的统计指标定义。",
    ),
    _seed(
        "EconomicIndicator",
        "经济指标",
        "InformationClass",
        "BuiltEnvironmentIndicator",
        "09",
        "描述经济总量、结构、产出或效率的统计指标定义。",
    ),
    _seed(
        "EmploymentIndicator",
        "就业指标",
        "InformationClass",
        "EconomicIndicator",
        "09",
        "描述就业人口、行业结构或劳动参与特征的统计指标定义。",
    ),
    _seed(
        "InvestmentIndicator",
        "投资指标",
        "InformationClass",
        "EconomicIndicator",
        "09",
        "描述固定资产、建设项目或资源开发投资的统计指标定义。",
    ),
    _seed(
        "DatasetMetadata",
        "数据集元数据",
        "InformationClass",
        "EvidenceArtifact",
        "10",
        "描述自然资源数据集标识、范围、质量、时效、责任方和访问条件的元数据记录。",
    ),
    _seed(
        "LineageRecord",
        "数据血缘记录",
        "InformationClass",
        "EvidenceArtifact",
        "10",
        "描述数据来源、处理步骤、派生关系和版本的可追溯记录。",
    ),
    _seed(
        "DataQualityReport",
        "数据质量报告",
        "InformationClass",
        "EvidenceArtifact",
        "10",
        "记录完整性、一致性、位置精度、属性精度和时效性评价结果的报告。",
    ),
    _seed(
        "AccessConstraint",
        "访问约束",
        "InformationClass",
        "NaturalResourceRestriction",
        "10",
        "对数据访问、共享、分发或使用施加的权限和条件。",
    ),
    _seed(
        "ContactInformation",
        "联系信息",
        "InformationClass",
        "NaturalResourceThing",
        "10",
        "描述数据责任主体或业务责任主体联系方式的信息对象。",
    ),
    _seed(
        "NaturalResourceActor",
        "自然资源主体",
        "DomainClass",
        "NaturalResourceThing",
        "03",
        "能够持有权利、承担责任或实施自然资源活动的人或组织。",
    ),
    _seed(
        "Person",
        "自然人",
        "DomainClass",
        "NaturalResourceActor",
        "03",
        "以自然人身份参与自然资源权利或管理关系的主体。",
    ),
    _seed(
        "Organization",
        "组织",
        "DomainClass",
        "NaturalResourceActor",
        "03",
        "以组织身份参与自然资源权利、管理或业务关系的主体。",
    ),
    _seed(
        "PublicAuthority",
        "公共管理机关",
        "DomainClass",
        "Organization",
        "06",
        "依法承担自然资源审批、规划、登记或监管职责的组织主体。",
    ),
    _seed(
        "Enterprise",
        "企业",
        "DomainClass",
        "Organization",
        "07",
        "参与自然资源开发利用、建设或相关经营活动的组织主体。",
    ),
    _seed(
        "SubdistrictOffice",
        "街道办事处",
        "DomainClass",
        "PublicAuthority",
        "09",
        "承担街道行政管理和基层公共服务职能的派出机关。",
    ),
    _seed(
        "VillageCommittee",
        "村民委员会",
        "DomainClass",
        "Organization",
        "09",
        "依法开展村级自治和基层公共服务的组织。",
        "村委会",
    ),
    _seed(
        "NaturalResourceRole",
        "自然资源领域角色",
        "RoleClass",
        "NaturalResourceThing",
        "03",
        "主体在自然资源业务关系中承担的职责或资格。",
    ),
    _seed(
        "RightsHolder",
        "权利人",
        "RoleClass",
        "NaturalResourceRole",
        "03",
        "依法享有自然资源权利的主体角色。",
    ),
    _seed(
        "ApprovingAuthority",
        "审批机关",
        "RoleClass",
        "NaturalResourceRole",
        "06",
        "依法对自然资源事项作出审批决定的机关角色。",
    ),
    _seed(
        "RegulatoryAuthority",
        "监管机关",
        "RoleClass",
        "NaturalResourceRole",
        "08",
        "依法承担自然资源监督管理职责的机关角色。",
    ),
    _seed(
        "DataProvider",
        "数据提供方",
        "RoleClass",
        "NaturalResourceRole",
        "10",
        "对自然资源数据来源、交付和质量承担责任的主体角色。",
    ),
)


OBJECT_PROPERTIES = (
    ObjectPropertySeed(
        "spatiallyRepresents",
        "空间表征",
        "LandParcel",
        "Land",
        inverse="representedBySpatialUnit",
        functional=True,
    ),
    ObjectPropertySeed(
        "representedBySpatialUnit",
        "由空间单元表征",
        "Land",
        "LandParcel",
        inverse="spatiallyRepresents",
    ),
    ObjectPropertySeed(
        "hasLandUseState", "具有土地利用状态", "LandParcel", "LandUseState", inverse="stateOf"
    ),
    ObjectPropertySeed(
        "stateOf",
        "所属地块",
        "LandUseState",
        "LandParcel",
        inverse="hasLandUseState",
        functional=True,
    ),
    ObjectPropertySeed(
        "hasObservedState",
        "具有观测状态",
        "NaturalResourceEntity",
        "ObservedState",
        inverse="observedStateOf",
    ),
    ObjectPropertySeed(
        "observedStateOf",
        "观测状态所属对象",
        "ObservedState",
        "NaturalResourceEntity",
        inverse="hasObservedState",
        functional=True,
    ),
    ObjectPropertySeed(
        "hasPlannedState",
        "具有规划状态",
        "NaturalResourceEntity",
        "PlannedState",
        inverse="plannedStateOf",
    ),
    ObjectPropertySeed(
        "plannedStateOf",
        "规划状态所属对象",
        "PlannedState",
        "NaturalResourceEntity",
        inverse="hasPlannedState",
        functional=True,
    ),
    ObjectPropertySeed(
        "hasSourceState",
        "源状态",
        "LandUseTransition",
        "LandUseState",
        inverse="sourceStateOf",
        functional=True,
    ),
    ObjectPropertySeed(
        "sourceStateOf",
        "作为源状态用于",
        "LandUseState",
        "LandUseTransition",
        inverse="hasSourceState",
    ),
    ObjectPropertySeed(
        "hasTargetState",
        "目标状态",
        "LandUseTransition",
        "LandUseState",
        inverse="targetStateOf",
        functional=True,
    ),
    ObjectPropertySeed(
        "targetStateOf",
        "作为目标状态用于",
        "LandUseState",
        "LandUseTransition",
        inverse="hasTargetState",
    ),
    ObjectPropertySeed(
        "affectsParcel",
        "影响地块",
        "LandUseTransition",
        "LandParcel",
        inverse="parcelAffectedBy",
        functional=True,
    ),
    ObjectPropertySeed(
        "parcelAffectedBy", "受转换影响", "LandParcel", "LandUseTransition", inverse="affectsParcel"
    ),
    ObjectPropertySeed(
        "supportedBy", "依据", "NaturalResourceActivity", "LegalBasis", inverse="supportsActivity"
    ),
    ObjectPropertySeed(
        "supportsActivity",
        "支撑活动",
        "LegalBasis",
        "NaturalResourceActivity",
        inverse="supportedBy",
    ),
    ObjectPropertySeed(
        "authorizedBy",
        "批准文件",
        "LandUseTransition",
        "ApprovalDocument",
        inverse="authorizesTransition",
    ),
    ObjectPropertySeed(
        "authorizesTransition",
        "批准转换",
        "ApprovalDocument",
        "LandUseTransition",
        inverse="authorizedBy",
    ),
    ObjectPropertySeed(
        "observes",
        "观测对象",
        "NaturalResourceObservation",
        "NaturalResourceEntity",
        inverse="observedBy",
    ),
    ObjectPropertySeed(
        "observedBy",
        "被观测",
        "NaturalResourceEntity",
        "NaturalResourceObservation",
        inverse="observes",
    ),
    ObjectPropertySeed(
        "producedBy",
        "由活动产生",
        "NaturalResourceObservation",
        "NaturalResourceActivity",
        inverse="producesObservation",
        functional=True,
    ),
    ObjectPropertySeed(
        "producesObservation",
        "产生观测",
        "NaturalResourceActivity",
        "NaturalResourceObservation",
        inverse="producedBy",
    ),
    ObjectPropertySeed(
        "hasRight", "设有权利", "NaturalResourceEntity", "NaturalResourceRight", inverse="rightOf"
    ),
    ObjectPropertySeed(
        "rightOf",
        "以资源为客体",
        "NaturalResourceRight",
        "NaturalResourceEntity",
        inverse="hasRight",
    ),
    ObjectPropertySeed(
        "heldBy", "由主体持有", "NaturalResourceRight", "NaturalResourceActor", inverse="holdsRight"
    ),
    ObjectPropertySeed(
        "holdsRight", "持有权利", "NaturalResourceActor", "NaturalResourceRight", inverse="heldBy"
    ),
    ObjectPropertySeed(
        "playsRole", "承担角色", "NaturalResourceActor", "NaturalResourceRole", inverse="roleOf"
    ),
    ObjectPropertySeed(
        "roleOf",
        "角色由主体承担",
        "NaturalResourceRole",
        "NaturalResourceActor",
        inverse="playsRole",
        functional=True,
    ),
    ObjectPropertySeed(
        "performedBy",
        "由主体实施",
        "NaturalResourceActivity",
        "NaturalResourceActor",
        inverse="performsActivity",
    ),
    ObjectPropertySeed(
        "performsActivity",
        "实施活动",
        "NaturalResourceActor",
        "NaturalResourceActivity",
        inverse="performedBy",
    ),
    ObjectPropertySeed(
        "appliesTo",
        "适用于",
        "NaturalResourceRule",
        "NaturalResourceEntity",
        inverse="governedEntityByRule",
    ),
    ObjectPropertySeed(
        "governedEntityByRule",
        "对象适用规则",
        "NaturalResourceEntity",
        "NaturalResourceRule",
        inverse="appliesTo",
    ),
    ObjectPropertySeed(
        "governedBy",
        "受规则约束",
        "NaturalResourceActivity",
        "NaturalResourceRule",
        inverse="governsActivity",
    ),
    ObjectPropertySeed(
        "governsActivity",
        "约束活动",
        "NaturalResourceRule",
        "NaturalResourceActivity",
        inverse="governedBy",
    ),
    ObjectPropertySeed(
        "subjectToRestriction",
        "受到限制",
        "NaturalResourceEntity",
        "NaturalResourceRestriction",
        inverse="restricts",
    ),
    ObjectPropertySeed(
        "restricts",
        "限制对象",
        "NaturalResourceRestriction",
        "NaturalResourceEntity",
        inverse="subjectToRestriction",
    ),
    ObjectPropertySeed(
        "supportedByEvidence",
        "由证据支持",
        "NaturalResourceThing",
        "EvidenceArtifact",
        inverse="evidenceFor",
    ),
    ObjectPropertySeed(
        "evidenceFor",
        "证明对象",
        "EvidenceArtifact",
        "NaturalResourceThing",
        inverse="supportedByEvidence",
    ),
    ObjectPropertySeed(
        "locatedIn", "位于", "NaturalResourceEntity", "AdministrativeUnit", inverse="containsEntity"
    ),
    ObjectPropertySeed(
        "containsEntity",
        "包含实体",
        "AdministrativeUnit",
        "NaturalResourceEntity",
        inverse="locatedIn",
    ),
    ObjectPropertySeed(
        "constrainedBy", "受边界约束", "LandParcel", "ControlBoundary", inverse="constrainsParcel"
    ),
    ObjectPropertySeed(
        "constrainsParcel", "约束地块", "ControlBoundary", "LandParcel", inverse="constrainedBy"
    ),
    ObjectPropertySeed(
        "hasPart",
        "包含组成部分",
        "NaturalResourceEntity",
        "NaturalResourceEntity",
        inverse="partOf",
    ),
    ObjectPropertySeed(
        "partOf",
        "组成部分属于",
        "NaturalResourceEntity",
        "NaturalResourceEntity",
        inverse="hasPart",
    ),
    ObjectPropertySeed(
        "hasWaterFeature",
        "包含水系要素",
        "WaterSystem",
        "NaturalResourceEntity",
        inverse="partOfWaterSystem",
    ),
    ObjectPropertySeed(
        "partOfWaterSystem",
        "属于水系",
        "NaturalResourceEntity",
        "WaterSystem",
        inverse="hasWaterFeature",
    ),
    ObjectPropertySeed(
        "representsAdministrativeUnit",
        "标注行政范围",
        "AdministrativePlace",
        "AdministrativeUnit",
        inverse="hasRepresentativePlace",
        functional=True,
    ),
    ObjectPropertySeed(
        "hasRepresentativePlace",
        "具有行政机构地点",
        "AdministrativeUnit",
        "AdministrativePlace",
        inverse="representsAdministrativeUnit",
    ),
    ObjectPropertySeed(
        "officeOf",
        "行政机构服务范围",
        "Organization",
        "AdministrativeUnit",
        inverse="servedByOffice",
    ),
    ObjectPropertySeed(
        "servedByOffice", "由行政机构服务", "AdministrativeUnit", "Organization", inverse="officeOf"
    ),
    ObjectPropertySeed(
        "hasAssessment", "具有评价", "SpatialUnit", "QualityAssessment", inverse="assessmentOf"
    ),
    ObjectPropertySeed(
        "assessmentOf",
        "评价对象",
        "QualityAssessment",
        "SpatialUnit",
        inverse="hasAssessment",
        functional=True,
    ),
    ObjectPropertySeed(
        "aboutEntity",
        "关于实体",
        "NaturalResourceObservation",
        "NaturalResourceEntity",
        inverse="hasObservation",
    ),
    ObjectPropertySeed(
        "hasObservation",
        "具有观测",
        "NaturalResourceEntity",
        "NaturalResourceObservation",
        inverse="aboutEntity",
    ),
    ObjectPropertySeed(
        "hasMeasurement",
        "具有测量值",
        "NaturalResourceObservation",
        "Measurement",
        inverse="measurementOfObservation",
    ),
    ObjectPropertySeed(
        "measurementOfObservation",
        "测量值所属观测",
        "Measurement",
        "NaturalResourceObservation",
        inverse="hasMeasurement",
        functional=True,
    ),
    ObjectPropertySeed(
        "measuresIndicator",
        "测量指标",
        "Measurement",
        "BuiltEnvironmentIndicator",
        inverse="measuredBy",
    ),
    ObjectPropertySeed(
        "measuredBy",
        "由测量值度量",
        "BuiltEnvironmentIndicator",
        "Measurement",
        inverse="measuresIndicator",
    ),
    ObjectPropertySeed("hasUnit", "采用计量单位", "Measurement", "MeasurementUnit"),
    ObjectPropertySeed(
        "hasAggregationContext",
        "采用统计聚合上下文",
        "NaturalResourceObservation",
        "AggregationContext",
    ),
    ObjectPropertySeed(
        "usesTravelMode", "采用出行方式", "ServiceCoverageObservation", "TravelMode"
    ),
    ObjectPropertySeed(
        "hasDistanceThreshold", "采用可达阈值", "ServiceCoverageObservation", "DistanceThreshold"
    ),
    ObjectPropertySeed(
        "usesPopulationDenominator",
        "采用人口分母",
        "NaturalResourceObservation",
        "PopulationDenominator",
    ),
    ObjectPropertySeed("classifiedBy", "采用分类", "SpatialUnit", "LandUseClassification"),
    ObjectPropertySeed(
        "overlapsSpatialUnit",
        "空间叠置关联",
        "SpatialUnit",
        "SpatialUnit",
        inverse="overlapsSpatialUnit",
    ),
    ObjectPropertySeed(
        "intersectsBoundary",
        "与管控边界相交",
        "NaturalResourceEntity",
        "ControlBoundary",
        inverse="boundaryIntersectsEntity",
    ),
    ObjectPropertySeed(
        "boundaryIntersectsEntity",
        "边界相交实体",
        "ControlBoundary",
        "NaturalResourceEntity",
        inverse="intersectsBoundary",
    ),
    ObjectPropertySeed(
        "hasRegistrationUnit",
        "关联登记单元",
        "NaturalResourceThing",
        "NaturalResourceRegistrationUnit",
        inverse="registrationUnitOf",
    ),
    ObjectPropertySeed(
        "registrationUnitOf",
        "登记单元对应事物",
        "NaturalResourceRegistrationUnit",
        "NaturalResourceThing",
        inverse="hasRegistrationUnit",
    ),
    ObjectPropertySeed(
        "documentedBy",
        "由材料记载",
        "NaturalResourceThing",
        "EvidenceArtifact",
        inverse="documents",
    ),
    ObjectPropertySeed(
        "documents", "记载对象", "EvidenceArtifact", "NaturalResourceThing", inverse="documentedBy"
    ),
    ObjectPropertySeed(
        "hasSurveyRecord",
        "具有调查记录",
        "NaturalResourceEntity",
        "SurveyRecord",
        inverse="surveyRecordOf",
    ),
    ObjectPropertySeed(
        "surveyRecordOf",
        "调查记录对应对象",
        "SurveyRecord",
        "NaturalResourceEntity",
        inverse="hasSurveyRecord",
        functional=True,
    ),
    ObjectPropertySeed(
        "hasRegistrationRecord",
        "具有登记记录",
        "NaturalResourceThing",
        "RegistrationRecord",
        inverse="registrationRecordOf",
    ),
    ObjectPropertySeed(
        "registrationRecordOf",
        "登记记录对应对象",
        "RegistrationRecord",
        "NaturalResourceThing",
        inverse="hasRegistrationRecord",
        functional=True,
    ),
    ObjectPropertySeed(
        "hasPermit",
        "具有行政许可",
        "NaturalResourceThing",
        "AdministrativePermit",
        inverse="permits",
    ),
    ObjectPropertySeed(
        "permits", "许可对象", "AdministrativePermit", "NaturalResourceThing", inverse="hasPermit"
    ),
    ObjectPropertySeed(
        "hasAssetRepresentation",
        "具有资产表达",
        "NaturalResourceEntity",
        "NaturalResourceAsset",
        inverse="assetRepresentationOf",
    ),
    ObjectPropertySeed(
        "assetRepresentationOf",
        "资产表达对应资源",
        "NaturalResourceAsset",
        "NaturalResourceEntity",
        inverse="hasAssetRepresentation",
        functional=True,
    ),
    ObjectPropertySeed(
        "hasValuation",
        "具有价值评价",
        "NaturalResourceAsset",
        "AssetValuationObservation",
        inverse="valuationOf",
    ),
    ObjectPropertySeed(
        "valuationOf",
        "价值评价对象",
        "AssetValuationObservation",
        "NaturalResourceAsset",
        inverse="hasValuation",
        functional=True,
    ),
    ObjectPropertySeed(
        "exposedToRisk",
        "暴露于风险区",
        "NaturalResourceEntity",
        "DisasterRiskZone",
        inverse="riskZoneContains",
    ),
    ObjectPropertySeed(
        "riskZoneContains",
        "风险区包含对象",
        "DisasterRiskZone",
        "NaturalResourceEntity",
        inverse="exposedToRisk",
    ),
    ObjectPropertySeed(
        "hasInspectionFinding",
        "具有检查发现",
        "NaturalResourceEntity",
        "InspectionFinding",
        inverse="findingAbout",
    ),
    ObjectPropertySeed(
        "findingAbout",
        "检查发现涉及对象",
        "InspectionFinding",
        "NaturalResourceEntity",
        inverse="hasInspectionFinding",
        functional=True,
    ),
    ObjectPropertySeed(
        "resultedInDecision",
        "形成执法决定",
        "ViolationInvestigation",
        "EnforcementDecision",
        inverse="decisionFromInvestigation",
    ),
    ObjectPropertySeed(
        "decisionFromInvestigation",
        "执法决定源于调查",
        "EnforcementDecision",
        "ViolationInvestigation",
        inverse="resultedInDecision",
    ),
    ObjectPropertySeed(
        "hasStatisticalObservation",
        "具有统计观测",
        "AdministrativeUnit",
        "StatisticalObservation",
        inverse="statisticalObservationOf",
    ),
    ObjectPropertySeed(
        "statisticalObservationOf",
        "统计观测所属区域",
        "StatisticalObservation",
        "AdministrativeUnit",
        inverse="hasStatisticalObservation",
        functional=True,
    ),
    ObjectPropertySeed(
        "describedByMetadata",
        "由元数据描述",
        "NaturalResourceThing",
        "DatasetMetadata",
        inverse="metadataDescribes",
    ),
    ObjectPropertySeed(
        "metadataDescribes",
        "元数据描述对象",
        "DatasetMetadata",
        "NaturalResourceThing",
        inverse="describedByMetadata",
    ),
    ObjectPropertySeed(
        "hasLineage", "具有数据血缘", "DatasetMetadata", "LineageRecord", inverse="lineageOf"
    ),
    ObjectPropertySeed(
        "lineageOf",
        "血缘所属元数据",
        "LineageRecord",
        "DatasetMetadata",
        inverse="hasLineage",
        functional=True,
    ),
    ObjectPropertySeed(
        "hasQualityReport",
        "具有质量报告",
        "DatasetMetadata",
        "DataQualityReport",
        inverse="qualityReportOf",
    ),
    ObjectPropertySeed(
        "qualityReportOf",
        "质量报告所属元数据",
        "DataQualityReport",
        "DatasetMetadata",
        inverse="hasQualityReport",
        functional=True,
    ),
)


DATA_PROPERTIES = (
    _data(
        "featureIdentifier",
        "要素标识",
        "NaturalResourceThing",
        "xsd:string",
        "BSM",
        "FEATID",
        "ID",
        "GUID",
        "ENTITY ID",
        source_labels=("标识码", "要素唯一标识码", "唯一标识", "空间身份编码"),
    ),
    _data(
        "featureTypeCode",
        "要素代码",
        "NaturalResourceThing",
        "xsd:string",
        "YSDM",
        source_labels=("要素代码",),
    ),
    _data(
        "sourceUpdatedAt",
        "来源更新时间",
        "NaturalResourceThing",
        "xsd:dateTime",
        "GXSJ",
        "UPDATETIME",
        source_labels=("更新时间",),
    ),
    _data(
        "sourceCreatedAt",
        "来源入库时间",
        "NaturalResourceThing",
        "xsd:dateTime",
        "CREATETIME",
        source_labels=("入库时间",),
    ),
    _data(
        "sourceChangeType",
        "来源变化类型",
        "NaturalResourceThing",
        "xsd:string",
        "CHANGETYPE",
        source_labels=("变化类型", "标识变化类型"),
    ),
    _data(
        "sourceAccuracyDescription",
        "来源精度说明",
        "NaturalResourceThing",
        "xsd:string",
        "PRCTAG",
        source_labels=("属性来源标注", "界线范围或位置准确程度"),
    ),
    _data(
        "sourceStatus",
        "来源状态",
        "NaturalResourceThing",
        "xsd:string",
        "ZT",
        source_labels=("状态", "现势"),
    ),
    _data(
        "dataYear",
        "数据年份",
        "NaturalResourceThing",
        "xsd:integer",
        "SJNF",
        source_labels=("数据年份",),
    ),
    _data(
        "dataSourceDescription",
        "数据来源",
        "NaturalResourceThing",
        "xsd:string",
        "SJLY",
        source_labels=("数据来源",),
    ),
    _data(
        "administrativeDivisionCode",
        "行政区划代码",
        "NaturalResourceEntity",
        "xsd:string",
        "XZQDM",
        "XZQHDM",
        "QXDM",
        source_labels=("行政区代码", "行政区划代码"),
    ),
    _data(
        "administrativeDivisionName",
        "行政区划名称",
        "NaturalResourceEntity",
        "xsd:string",
        "XZQMC",
        "XZQHMC",
        source_labels=("行政区名称", "行政区划名称"),
    ),
    _data(
        "spatialArea",
        "空间面积",
        "NaturalResourceEntity",
        "xsd:decimal",
        "MJ",
        source_labels=("面积",),
    ),
    _data(
        "priorLandUseCode",
        "变化前地类编码",
        "NaturalResourceObservation",
        "xsd:string",
        "DLBM",
        source_labels=("变化（或细化）前地类编码",),
    ),
    _data(
        "priorLandUseName",
        "变化前地类名称",
        "NaturalResourceObservation",
        "xsd:string",
        "DLMC",
        source_labels=("变化（或细化）前地类名称",),
    ),
    _data(
        "observedLandUseCode",
        "变化后地类编码",
        "NaturalResourceObservation",
        "xsd:string",
        "CC",
        source_labels=("变化（或细化）后地类编码",),
    ),
    _data(
        "observedLandUseName",
        "变化后地类名称",
        "NaturalResourceObservation",
        "xsd:string",
        "CCN",
        source_labels=("变化（或细化）后地类名称",),
    ),
    _data(
        "landUseObservationConsistent",
        "实地与调查地类一致标识",
        "NaturalResourceObservation",
        "xsd:boolean",
        "IFCON",
        source_labels=("监测时实地与上年度国土变更调查成果地类二级类是否一致",),
    ),
    _data(
        "displayName",
        "名称",
        "NaturalResourceEntity",
        "xsd:string",
        "NAME",
        source_labels=(
            "名称",
            "机构名称",
            "设施名称",
            "场馆名称",
            "学校名称",
            "医疗机构名称",
            "应急避难场所名称",
        ),
    ),
    _data(
        "address",
        "地址",
        "NaturalResourceEntity",
        "xsd:string",
        "XXDZ",
        "ADDRESS",
        source_labels=("详细地址", "地址"),
    ),
    _data(
        "cadastralUnitIdentifier", "不动产单元号", "NaturalResourceEntity", "xsd:string", "BDCDYH"
    ),
    _data(
        "projectName",
        "项目名称",
        "BuiltStructure",
        "xsd:string",
        "XMMC",
        "JSXMMC",
        source_labels=("建设项目名称",),
    ),
    _data("buildingName", "建筑物名称", "Building", "xsd:string", "JZWMC"),
    _data(
        "baseArea",
        "基底面积",
        "Building",
        "xsd:decimal",
        "JDMJ",
        "FAREA",
        "ZZDMJ",
        source_labels=("占地面积", "幢占地面积"),
    ),
    _data(
        "buildingHeight",
        "建筑高度",
        "Building",
        "xsd:decimal",
        "JZGD",
        "HEIGHT",
        "JZWGD",
        source_labels=("建筑物高度",),
    ),
    _data("buildingYear", "建筑年代", "Building", "xsd:integer", "JZND"),
    _data("aboveGroundFloorCount", "地上层数", "Building", "xsd:integer", "DSCS"),
    _data("aboveGroundFloorArea", "地上建筑面积", "Building", "xsd:decimal", "DSJZMJ"),
    _data("belowGroundFloorCount", "地下层数", "Building", "xsd:integer", "DXCS"),
    _data("belowGroundFloorArea", "地下建筑面积", "Building", "xsd:decimal", "DXJZMJ"),
    _data(
        "dwellingCount",
        "房屋套数",
        "Building",
        "xsd:integer",
        "FWTS",
        "SETS",
        "ZTS",
        source_labels=("房屋套（间）数", "总套数"),
    ),
    _data(
        "structureType",
        "结构类型",
        "Building",
        "xsd:string",
        "JGLX",
        "FWJG",
        source_labels=("建筑结构",),
    ),
    _data(
        "buildingStatus",
        "建筑状态",
        "Building",
        "xsd:string",
        "JZZT",
        "ZT",
        source_labels=("建筑状态",),
    ),
    _data(
        "plannedUse",
        "规划用途",
        "Building",
        "xsd:string",
        "GHYT",
        "YTMC",
        source_labels=("规划用途名称",),
    ),
    _data("completedUse", "竣工用途", "Building", "xsd:string", "JGYT"),
    _data("propertyNature", "房屋性质", "Building", "xsd:string", "FWXZ"),
    _data("grossFloorArea", "建筑总面积", "Building", "xsd:decimal", "GBAREA"),
    _data("commercialHousingArea", "商品住房建筑面积", "Building", "xsd:decimal", "GBAREA_SPZF"),
    _data("commercialHousingUnitCount", "商品住房房屋套数", "Building", "xsd:integer", "SETS_SPZF"),
    _data("affordableHousingArea", "保障性住房建筑面积", "Building", "xsd:decimal", "GBAREA_BZXZF"),
    _data(
        "affordableHousingUnitCount", "保障性住房房屋套数", "Building", "xsd:integer", "SETS_BZXZF"
    ),
    _data(
        "buildingCode", "楼幢代码", "Building", "xsd:string", "LZDM", source_labels=("楼幢代码",)
    ),
    _data("buildingNumber", "幢号", "Building", "xsd:string", "ZRZH", source_labels=("幢号",)),
    _data(
        "buildingLocation",
        "楼幢坐落",
        "Building",
        "xsd:string",
        "LZZL",
        source_labels=("楼幢坐落",),
    ),
    _data("totalFloorCount", "总层数", "Building", "xsd:integer", "ZCS", source_labels=("总层数",)),
    _data(
        "undergroundDepth",
        "地下深度",
        "Building",
        "xsd:decimal",
        "DXSD",
        source_labels=("地下深度",),
    ),
    _data(
        "predictedFloorArea",
        "预测建筑面积",
        "Building",
        "xsd:decimal",
        "YCJZMJ",
        source_labels=("预测建筑面积",),
    ),
    _data(
        "surveyedFloorArea",
        "实测建筑面积",
        "Building",
        "xsd:decimal",
        "SCJZMJ",
        source_labels=("实测建筑面积",),
    ),
    _data(
        "apportionedFloorArea",
        "分摊建筑面积",
        "Building",
        "xsd:decimal",
        "FTJZMJ",
        source_labels=("分摊建筑面积",),
    ),
    _data(
        "commonPartFloorArea",
        "共有部分建筑面积",
        "Building",
        "xsd:decimal",
        "GYJZMJ",
        source_labels=("共有部分建筑面积",),
    ),
    _data(
        "exclusiveFloorArea",
        "专有部分建筑面积",
        "Building",
        "xsd:decimal",
        "ZYJZMJ",
        source_labels=("专有部分建筑面积",),
    ),
    _data(
        "buildingLandArea",
        "幢用地面积",
        "Building",
        "xsd:decimal",
        "ZYDMJ",
        source_labels=("幢用地面积",),
    ),
    _data(
        "completionDate", "竣工日期", "Building", "xsd:date", "JGRQ", source_labels=("竣工日期",)
    ),
    _data(
        "approvedUse", "批准用途", "Building", "xsd:string", "PZYT", source_labels=("房屋批准用途",)
    ),
    _data(
        "actualUse", "实际用途", "Building", "xsd:string", "SJYT", source_labels=("房屋实际用途",)
    ),
    _data(
        "propertyRightSource",
        "房屋产权来源",
        "Building",
        "xsd:string",
        "FWCQLY",
        source_labels=("房屋产权来源",),
    ),
    _data(
        "commonOwnershipDescription",
        "共有情况",
        "Building",
        "xsd:string",
        "GYQK",
        source_labels=("共有情况",),
    ),
    _data("managementNumber", "管理号", "Building", "xsd:string", "GLH", source_labels=("管理号",)),
    _data(
        "projectIdentifier",
        "项目编号",
        "BuiltStructure",
        "xsd:string",
        "XMBH",
        source_labels=("项目编号",),
    ),
    _data(
        "electronicSupervisionNumber",
        "电子监管号",
        "NaturalResourceThing",
        "xsd:string",
        "DZJGH",
        source_labels=("电子监管号",),
    ),
    _data(
        "previousRealEstateUnitIdentifier",
        "原不动产单元号",
        "Building",
        "xsd:string",
        "YBDCDYH",
        source_labels=("原不动产单元号",),
    ),
    _data(
        "cadastralParcelCode",
        "宗地代码",
        "NaturalResourceEntity",
        "xsd:string",
        "ZDDM",
        source_labels=("宗地代码",),
    ),
    _data(
        "rightsHolderUserTypeCode",
        "权利人或实际使用人类型码",
        "Building",
        "xsd:string",
        "QLRSJSYRLXM",
        source_labels=("权利人|实际使用人类，型码",),
    ),
    _data(
        "housingSecurityType",
        "保障房类型",
        "Building",
        "xsd:string",
        "TYPE",
        source_labels=("保障房类型",),
    ),
    _data(
        "facilityType",
        "设施类型",
        "BuiltStructure",
        "xsd:string",
        "CNN",
        "TYPE",
        source_labels=("类型", "水域类别名称"),
        definition=(
            "CNN 与 TYPE 是源结构字段代码，统一映射到领域设施类型；"
            "水体类别另由 waterCategoryName 表达。"
        ),
    ),
    _data("includesFootballField", "是否包含足球场", "SportsFacility", "xsd:boolean", "IFFF"),
    _data("footballFieldType", "足球场地类型", "SportsFacility", "xsd:string", "TYPE"),
    _data(
        "isEmergencyShelter",
        "是否为应急避难场所",
        "GreenOpenSpace",
        "xsd:boolean",
        source_labels=("是否为应急避难场所",),
    ),
    _data(
        "currentLandUseName",
        "现状地类名称",
        "SpatialUnit",
        "xsd:string",
        "DLMC",
        source_labels=("地类名称", "现状地类名称"),
    ),
    _data(
        "currentLandUseCode",
        "现状地类编码",
        "SpatialUnit",
        "xsd:string",
        "DLBM",
        source_labels=("地类编码", "现状地类编码"),
    ),
    _data("ownershipNature", "权属性质", "SpatialUnit", "xsd:string", "QSXZ"),
    _data("ownerUnitName", "权属单位名称", "SpatialUnit", "xsd:string", "QSDWMC"),
    _data("locationUnitName", "坐落单位名称", "SpatialUnit", "xsd:string", "ZLDWMC"),
    _data("rightType", "权利类型", "NaturalResourceRight", "xsd:string", "QLLX"),
    _data("rightNature", "权利性质", "NaturalResourceRight", "xsd:string", "QLXZ"),
    _data("eastBoundaryDescription", "宗地四至东", "CadastralParcel", "xsd:string", "ZDSZD"),
    _data("southBoundaryDescription", "宗地四至南", "CadastralParcel", "xsd:string", "ZDSZN"),
    _data("westBoundaryDescription", "宗地四至西", "CadastralParcel", "xsd:string", "ZDSZX"),
    _data("northBoundaryDescription", "宗地四至北", "CadastralParcel", "xsd:string", "ZDSZB"),
    _data(
        "parcelPreIdentifier",
        "图斑预编号",
        "LandParcel",
        "xsd:string",
        "TBYBH",
        source_labels=("图斑预编号",),
    ),
    _data(
        "parcelIdentifier",
        "图斑编号",
        "LandParcel",
        "xsd:string",
        "TBBH",
        source_labels=("图斑编号",),
    ),
    _data(
        "parcelArea",
        "图斑面积",
        "LandParcel",
        "xsd:decimal",
        "TBMJ",
        source_labels=("图斑面积", "宗地面积"),
    ),
    _data(
        "landClassArea",
        "图斑地类面积",
        "LandParcel",
        "xsd:decimal",
        "TBDLMJ",
        source_labels=("图斑地类面积",),
    ),
    _data(
        "deductedLandUseCode",
        "扣除地类编码",
        "LandParcel",
        "xsd:string",
        "KCDLBM",
        source_labels=("扣除地类编码",),
    ),
    _data(
        "deductionCoefficient",
        "扣除地类系数",
        "LandParcel",
        "xsd:decimal",
        "KCXS",
        source_labels=("扣除地类系数",),
    ),
    _data(
        "deductedArea",
        "扣除地类面积",
        "LandParcel",
        "xsd:decimal",
        "KCMJ",
        source_labels=("扣除地类面积",),
    ),
    _data(
        "cultivatedLandTypeCode",
        "耕地类型",
        "LandParcel",
        "xsd:string",
        "GDLX",
        source_labels=("耕地类型",),
    ),
    _data(
        "cultivatedLandSlopeGrade",
        "耕地坡度级别",
        "LandParcel",
        "xsd:string",
        "GDPDJB",
        source_labels=("耕地坡度级别",),
    ),
    _data(
        "linearFeatureWidth",
        "线状地物宽度",
        "LandParcel",
        "xsd:decimal",
        "XZDWKD",
        source_labels=("线状地物宽度",),
    ),
    _data(
        "parcelRefinementCode",
        "图斑细化代码",
        "LandParcel",
        "xsd:string",
        "TBXHDM",
        source_labels=("图斑细化代码",),
    ),
    _data(
        "parcelRefinementName",
        "图斑细化名称",
        "LandParcel",
        "xsd:string",
        "TBXHMC",
        source_labels=("图斑细化名称",),
    ),
    _data(
        "plantingAttributeCode",
        "种植属性代码",
        "LandParcel",
        "xsd:string",
        "ZZSXDM",
        source_labels=("种植属性代码",),
    ),
    _data(
        "plantingAttributeName",
        "种植属性名称",
        "LandParcel",
        "xsd:string",
        "ZZSXMC",
        source_labels=("种植属性名称",),
    ),
    _data(
        "cultivatedLandQualityGrade",
        "耕地等别",
        "LandParcel",
        "xsd:integer",
        "GDDB",
        source_labels=("耕地等别",),
    ),
    _data(
        "isEnclave",
        "飞入地标识",
        "LandParcel",
        "xsd:boolean",
        "FRDBS",
        source_labels=("飞入地标识",),
    ),
    _data(
        "urbanRuralAttributeCode",
        "城镇村属性码",
        "LandParcel",
        "xsd:string",
        "CZCSXM",
        source_labels=("城镇村属性码",),
    ),
    _data(
        "ownerUnitCode",
        "权属单位代码",
        "LandParcel",
        "xsd:string",
        "QSDWDM",
        source_labels=("权属单位代码",),
    ),
    _data(
        "locationUnitCode",
        "坐落单位代码",
        "LandParcel",
        "xsd:string",
        "ZLDWDM",
        source_labels=("坐落单位代码",),
    ),
    _data(
        "islandName", "海岛名称", "LandParcel", "xsd:string", "HDMC", source_labels=("海岛名称",)
    ),
    _data(
        "description",
        "描述说明",
        "NaturalResourceThing",
        "xsd:string",
        "MSSM",
        "FJSM",
        source_labels=("描述说明", "附加说明"),
    ),
    _data("cadastralNumber", "地籍号", "CadastralParcel", "xsd:string", source_labels=("地籍号",)),
    _data("mapSheetNumber", "图幅号", "CadastralParcel", "xsd:string", source_labels=("图幅号",)),
    _data("locationDescription", "坐落", "CadastralParcel", "xsd:string", source_labels=("坐落",)),
    _data(
        "boundaryDescription",
        "宗地四至",
        "CadastralParcel",
        "xsd:string",
        source_labels=("宗地四至",),
    ),
    _data(
        "parcelCharacteristicCode",
        "宗地特征码",
        "CadastralParcel",
        "xsd:string",
        source_labels=("宗地特征码",),
    ),
    _data("remark", "备注", "NaturalResourceThing", "xsd:string", "BZ"),
    _data(
        "landSeaUseClassificationName",
        "用地用海分类名称",
        "PlannedLandUseArea",
        "xsd:string",
        "YDYHFLMC",
    ),
    _data(
        "landSeaUseClassificationCode",
        "用地用海分类代码",
        "PlannedLandUseArea",
        "xsd:string",
        "YDYHFLDM",
        source_labels=("用地用海分类代码",),
    ),
    _data(
        "plannedParcelArea",
        "规划图斑面积",
        "PlannedLandUseArea",
        "xsd:decimal",
        "TBMJ",
        source_labels=("图斑面积",),
    ),
    _data(
        "plannedLandClassArea",
        "规划图斑地类面积",
        "PlannedLandUseArea",
        "xsd:decimal",
        "TBDLMJ",
        source_labels=("图斑地类面积",),
    ),
    _data(
        "baselineLandUseCode",
        "基期地类代码",
        "PlannedLandUseArea",
        "xsd:string",
        "JQDLDM",
        source_labels=("基期地类代码",),
    ),
    _data(
        "planningStatus",
        "规划状态",
        "PlannedLandUseArea",
        "xsd:string",
        "GHZT",
        source_labels=("规划状态",),
    ),
    _data("planningZoneName", "规划分区名称", "PlanningZone", "xsd:string", "GHFQMC"),
    _data(
        "planningZoneCode",
        "规划分区代码",
        "PlanningZone",
        "xsd:string",
        "GHFQDM",
        source_labels=("规划分区代码",),
    ),
    _data(
        "planningControlGuidance",
        "管控指引",
        "PlanningZone",
        "xsd:string",
        "GKZY",
        source_labels=("管控指引",),
    ),
    _data(
        "controlRequirement",
        "管控要求",
        "ControlBoundary",
        "xsd:string",
        "GKYQ",
        source_labels=("管控要求",),
    ),
    _data(
        "boundaryGrade",
        "管控边界级别",
        "ControlBoundary",
        "xsd:string",
        "JB",
        source_labels=("级别",),
    ),
    _data(
        "boundaryCategory",
        "管控边界类别",
        "ControlBoundary",
        "xsd:string",
        "LB",
        source_labels=("类别",),
    ),
    _data(
        "greenLineType",
        "城市绿线类型",
        "UrbanGreenLine",
        "xsd:string",
        "LX",
        source_labels=("类型",),
    ),
    _data(
        "yellowLineFacilityType",
        "城市黄线设施类型",
        "UrbanYellowLine",
        "xsd:string",
        "SSLX",
        source_labels=("设施类型",),
    ),
    _data(
        "facilityGrade",
        "设施等级",
        "UrbanFourLine",
        "xsd:string",
        "SSDJ",
        source_labels=("设施等级",),
    ),
    _data("buildingCount", "建筑数量", "UrbanFormAssessment", "xsd:integer", "JZSL"),
    _data("buildingDensity", "建筑密度", "UrbanFormAssessment", "xsd:decimal", "JZMD"),
    _data("meanBuildingHeight", "建筑物平均高度", "UrbanFormAssessment", "xsd:decimal", "JZWPJGD"),
    _data(
        "veryHighRiseBuildingShare", "超高层建筑比", "UrbanFormAssessment", "xsd:decimal", "CGCJZB"
    ),
    _data("floorAreaRatio", "净容积率", "UrbanFormAssessment", "xsd:decimal", "JRJL"),
    _data(
        "undergroundDevelopmentIntensity",
        "地下空间开发强度",
        "UrbanFormAssessment",
        "xsd:decimal",
        "DXKJKFQD",
    ),
    _data(
        "residentialDevelopmentIntensity",
        "住宅建筑开发强度",
        "UrbanFormAssessment",
        "xsd:decimal",
        "ZZJZKFQD",
    ),
    _data(
        "residentialBuildingCount", "住宅建筑数量", "UrbanFormAssessment", "xsd:integer", "ZZJZSL"
    ),
    _data("highRiseBuildingCount", "高层建筑数量", "UrbanFormAssessment", "xsd:integer", "GCJZSL"),
    _data(
        "veryHighRiseBuildingCount",
        "超高层建筑数量",
        "UrbanFormAssessment",
        "xsd:integer",
        "CGCJZSL",
    ),
    _data(
        "buildingUnderConstructionCount",
        "在建建筑数量",
        "UrbanFormAssessment",
        "xsd:integer",
        "ZJJZSL",
    ),
    _data("buildingCrowdingIndex", "建筑拥挤度", "UrbanFormAssessment", "xsd:decimal", "JZYJD"),
    _data(
        "buildingLandscapeOrderliness",
        "建筑物景观整齐度",
        "UrbanFormAssessment",
        "xsd:decimal",
        "JZWJGZQD",
    ),
    _data("incrementalSpace", "增量空间", "UrbanFormAssessment", "xsd:decimal", "ZLKJ"),
    _data(
        "residentialBuildingShare", "居住建筑占比", "UrbanFormAssessment", "xsd:decimal", "JZJZZB"
    ),
    _data(
        "publicAdministrationServiceBuildingShare",
        "公共管理与公共服务建筑占比",
        "UrbanFormAssessment",
        "xsd:decimal",
        source_labels=("公共管理与公共服务建筑占比",),
    ),
    _data(
        "educationBuildingShare",
        "教育建筑占比",
        "UrbanFormAssessment",
        "xsd:decimal",
        source_labels=("教育建筑占比",),
    ),
    _data(
        "medicalBuildingShare",
        "医疗卫生建筑占比",
        "UrbanFormAssessment",
        "xsd:decimal",
        source_labels=("医疗卫生建筑占比",),
    ),
    _data(
        "culturalBuildingShare",
        "文化建筑占比",
        "UrbanFormAssessment",
        "xsd:decimal",
        source_labels=("文化建筑占比",),
    ),
    _data(
        "sportsBuildingShare",
        "体育建筑占比",
        "UrbanFormAssessment",
        "xsd:decimal",
        source_labels=("体育建筑占比",),
    ),
    _data(
        "socialWelfareBuildingShare",
        "社会福利建筑占比",
        "UrbanFormAssessment",
        "xsd:decimal",
        source_labels=("社会福利建筑占比",),
    ),
    _data(
        "commercialServiceBuildingShare",
        "商业服务业建筑占比",
        "UrbanFormAssessment",
        "xsd:decimal",
        source_labels=("商业服务业建筑占比",),
    ),
    _data(
        "commercialBuildingShare",
        "商业建筑占比",
        "UrbanFormAssessment",
        "xsd:decimal",
        source_labels=("商业建筑占比",),
    ),
    _data(
        "businessFinanceBuildingShare",
        "商务金融建筑占比",
        "UrbanFormAssessment",
        "xsd:decimal",
        source_labels=("商务金融建筑占比",),
    ),
    _data(
        "industrialMiningBuildingShare",
        "工矿建筑占比",
        "UrbanFormAssessment",
        "xsd:decimal",
        source_labels=("工矿建筑占比",),
    ),
    _data(
        "storageBuildingShare",
        "仓储建筑占比",
        "UrbanFormAssessment",
        "xsd:decimal",
        source_labels=("仓储建筑占比",),
    ),
    _data(
        "transportBuildingShare",
        "交通运输建筑占比",
        "UrbanFormAssessment",
        "xsd:decimal",
        source_labels=("交通运输建筑占比",),
    ),
    _data(
        "publicFacilityBuildingShare",
        "公共设施建筑占比",
        "UrbanFormAssessment",
        "xsd:decimal",
        source_labels=("公共设施建筑占比", "公共设施建筑占比特殊建筑占比"),
    ),
    _data(
        "specialUseBuildingShare",
        "特殊建筑占比",
        "UrbanFormAssessment",
        "xsd:decimal",
        source_labels=("特殊建筑占比", "公共设施建筑占比特殊建筑占比"),
    ),
    _data(
        "meanDevelopmentYear",
        "平均开发年份",
        "BuiltEnvironmentAssessment",
        "xsd:decimal",
        source_labels=("平均开发年份",),
    ),
    _data("oldBuildingCount", "老旧建筑数", "BuiltEnvironmentAssessment", "xsd:integer", "LJJZS"),
    _data(
        "oldBuildingShare", "老旧建筑占比", "BuiltEnvironmentAssessment", "xsd:decimal", "LJJZZB"
    ),
    _data(
        "stateOwnedLandShare",
        "国有权属用地占比",
        "BuiltEnvironmentAssessment",
        "xsd:decimal",
        "GYQSYDZB",
    ),
    _data(
        "remainingLandUseTerm",
        "剩余土地使用年限",
        "BuiltEnvironmentAssessment",
        "xsd:decimal",
        "SYTDSYNX",
    ),
    _data(
        "suppliedUnstartedLandArea",
        "已供未开工土地面积",
        "BuiltEnvironmentAssessment",
        "xsd:decimal",
        "YGWKGTDMJ",
    ),
    _data("landUnitPrice", "地均房价", "BuiltEnvironmentAssessment", "xsd:decimal", "DJFJ"),
    _data(
        "isVocationalEducationInstitution",
        "职业教育院校标识",
        "EducationalFacility",
        "xsd:boolean",
        "IFTC",
        source_labels=("是否为职业教育院校",),
    ),
    _data(
        "schoolClassCount",
        "班级数",
        "EducationalFacility",
        "xsd:integer",
        "QUOTA",
        source_labels=("班级数",),
    ),
    _data(
        "hospitalGrade",
        "医院等级",
        "MedicalFacility",
        "xsd:string",
        "GRADE",
        source_labels=("医院等级",),
    ),
    _data(
        "isCountyLevelHospital",
        "县级及以上医院标识",
        "MedicalFacility",
        "xsd:boolean",
        "IFTC",
        source_labels=("是否为县（区）级及以上医院",),
    ),
    _data(
        "isInfectiousDiseaseHospital",
        "传染病医院标识",
        "MedicalFacility",
        "xsd:boolean",
        "IFIDH",
        source_labels=("是否为传染病医院（含设置独立传染病院区（病区）的综合性医疗机构）",),
    ),
    _data(
        "medicalFacilityScale",
        "医疗机构规模",
        "MedicalFacility",
        "xsd:string",
        "QUOTA",
        source_labels=("规模",),
    ),
    _data(
        "welfareBedCount",
        "福利机构床位数",
        "WelfareFacility",
        "xsd:integer",
        "QUOTA",
        source_labels=("床位数",),
    ),
    _data(
        "fireRescue5MinuteCoverageRate",
        "消防救援5分钟可达覆盖率",
        "ServiceCoverageObservation",
        "xsd:decimal",
        source_labels=("消防救援5分钟可达覆盖率",),
    ),
    _data(
        "primarySchool10MinuteWalkCoverageRate",
        "社区小学步行10分钟覆盖率",
        "ServiceCoverageObservation",
        "xsd:decimal",
        source_labels=("社区小学步行10分钟覆盖率",),
    ),
    _data(
        "middleSchool15MinuteWalkCoverageRate",
        "社区中学步行15分钟覆盖率",
        "ServiceCoverageObservation",
        "xsd:decimal",
        source_labels=("社区中学步行15分钟覆盖率",),
    ),
    _data(
        "elderlyCare5MinuteWalkCoverageRate",
        "社区养老设施步行5分钟覆盖率",
        "ServiceCoverageObservation",
        "xsd:decimal",
        source_labels=("社区养老设施步行5分钟覆盖率",),
    ),
    _data(
        "culturalFacility15MinuteWalkCoverageRate",
        "社区文化活动设施步行15分钟覆盖率",
        "ServiceCoverageObservation",
        "xsd:decimal",
        source_labels=("社区文化活动设施步行15分钟覆盖率",),
    ),
    _data(
        "marketSupermarket10MinuteWalkCoverageRate",
        "菜市场或超市步行10分钟覆盖率",
        "ServiceCoverageObservation",
        "xsd:decimal",
        source_labels=("菜市场（超市）步行10分钟覆盖率",),
    ),
    _data(
        "sportsFacility15MinuteWalkCoverageRate",
        "社区体育设施步行15分钟覆盖率",
        "ServiceCoverageObservation",
        "xsd:decimal",
        source_labels=("社区体育设施步行15分钟覆盖率",),
    ),
    _data(
        "parkGreenSpace5MinuteWalkCoverageRate",
        "公园绿地或广场步行5分钟覆盖率",
        "ServiceCoverageObservation",
        "xsd:decimal",
        source_labels=("公园绿地、广场步行5分钟覆盖率",),
    ),
    _data(
        "culturalVenueCountPer100k",
        "每10万人文化艺术场馆数",
        "ServiceCoverageObservation",
        "xsd:decimal",
        source_labels=("每10万人拥有博物馆、图书馆、科技馆、艺术馆等文化艺术场馆数",),
    ),
    _data("waterCategoryName", "水域类别名称", "SurfaceWaterBody", "xsd:string", "CNN"),
    _data(
        "surfaceArea", "水面面积", "SurfaceWaterBody", "xsd:decimal", source_labels=("水面面积",)
    ),
    _data(
        "meanWaterDepth", "平均水深", "SurfaceWaterBody", "xsd:decimal", source_labels=("平均水深",)
    ),
    _data(
        "meanWaterWidth", "平均宽度", "SurfaceWaterBody", "xsd:decimal", source_labels=("平均宽度",)
    ),
    _data(
        "waterIndustryCode",
        "水利行业编码",
        "SurfaceWaterBody",
        "xsd:string",
        source_labels=("水利行业编码",),
    ),
    _data("riverType", "河流类型", "RiverSegment", "xsd:string", source_labels=("河流类型",)),
    _data("seasonalMonths", "时令月份", "RiverSegment", "xsd:string", source_labels=("时令月份",)),
    _data("length", "长度", "SurfaceWaterBody", "xsd:decimal", source_labels=("长度",)),
    _data(
        "navigationStatus",
        "通航性质",
        "SurfaceWaterBody",
        "xsd:string",
        source_labels=("通航性质",),
    ),
    _data(
        "flowDirectionality", "单双向", "SurfaceWaterBody", "xsd:string", source_labels=("单双向",)
    ),
    _data(
        "wholeRiverCode",
        "整体河流代码",
        "SurfaceWaterBody",
        "xsd:string",
        source_labels=("整体河流代码",),
    ),
    _data(
        "riverGrade", "河流等级", "SurfaceWaterBody", "xsd:string", source_labels=("新定河流等级",)
    ),
    _data(
        "artificialChannelFlag",
        "是否为人工河流或沟渠",
        "SurfaceWaterBody",
        "xsd:boolean",
        source_labels=("是否为人工河流、沟渠",),
    ),
    _data(
        "lakeReservoirCode",
        "湖泊水库代码",
        "SurfaceWaterBody",
        "xsd:string",
        source_labels=("湖泊水库代码",),
    ),
    _data(
        "lakeGrade", "湖泊等级", "SurfaceWaterBody", "xsd:string", source_labels=("新定湖泊等级",)
    ),
    _data(
        "reservoirUseType",
        "水库用途类型",
        "SurfaceWaterBody",
        "xsd:string",
        source_labels=("用途类型",),
    ),
    _data(
        "storageCapacity", "水库容积", "SurfaceWaterBody", "xsd:decimal", source_labels=("容积",)
    ),
    _data(
        "alternateWaterName",
        "水体其他名称",
        "SurfaceWaterBody",
        "xsd:string",
        "ANAME",
        source_labels=("湖泊水库的其他名称",),
    ),
    _data(
        "riverSectionAlternateNameCode",
        "河段其他名称代码",
        "SurfaceWaterBody",
        "xsd:string",
        "ARCODE",
        source_labels=("河段其他名称代码",),
    ),
    _data(
        "basinCode",
        "流域代码",
        "SurfaceWaterBody",
        "xsd:string",
        "BAS",
        source_labels=("所属流域的代码",),
    ),
    _data("basinName", "流域名称", "SurfaceWaterBody", "xsd:string", source_labels=("流域",)),
    _data(
        "waterEntityCode",
        "水体实体编码",
        "SurfaceWaterBody",
        "xsd:string",
        "EC",
        source_labels=("实体编码",),
    ),
    _data(
        "entityCodeBasisDescription",
        "实体编码依据说明",
        "SurfaceWaterBody",
        "xsd:string",
        "ECRM",
        source_labels=("实体编码依据说明",),
    ),
    _data(
        "waterBodyName",
        "水体名称",
        "SurfaceWaterBody",
        "xsd:string",
        "GNAME",
        source_labels=("湖泊水库实体的名称",),
    ),
    _data(
        "waterBodyGrade",
        "水体等级",
        "SurfaceWaterBody",
        "xsd:string",
        "GRADE",
        source_labels=("等级",),
    ),
    _data(
        "mainRiverCode",
        "所在主要河流代码",
        "SurfaceWaterBody",
        "xsd:string",
        "LKRCODE",
        source_labels=("所在主要河流代码",),
    ),
    _data(
        "localRiverSegmentCode",
        "局部河段代码",
        "SurfaceWaterBody",
        "xsd:string",
        "LRCODE",
        source_labels=("局部河段代码",),
    ),
    _data(
        "maximumWaterDepth",
        "最大水深",
        "SurfaceWaterBody",
        "xsd:decimal",
        "MHEIGHT",
        source_labels=("最大水深",),
    ),
    _data(
        "sharedRiverSegmentCode",
        "共享河段编码",
        "SurfaceWaterBody",
        "xsd:string",
        "SHRC",
        source_labels=("共享河段编码",),
    ),
    _data(
        "waterIndustryRiverGrade",
        "水利行业河流级别",
        "SurfaceWaterBody",
        "xsd:string",
        "WRGR",
        source_labels=("水利行业河流级别",),
    ),
    _data(
        "catchmentCode",
        "集水区代码",
        "SurfaceWaterBody",
        "xsd:string",
        "WSUCODE",
        source_labels=("所在集水区代码",),
    ),
    _data(
        "archiveNumber",
        "档案号",
        "EvidenceArtifact",
        "xsd:string",
        "DAH",
        source_labels=("档案号",),
    ),
    _data(
        "surveyOrganizationName",
        "调查单位",
        "SurveyRecord",
        "xsd:string",
        "DCDW",
        source_labels=("调查单位(机构)",),
    ),
    _data(
        "surveyTypeCode",
        "调查类型特征码",
        "SurveyRecord",
        "xsd:string",
        "DCLXTZM",
        source_labels=("调查类型特征码",),
    ),
    _data(
        "surveyDate", "调查日期", "SurveyRecord", "xsd:date", "DCRQ", source_labels=("调查日期",)
    ),
    _data("surveyorName", "调查员", "SurveyRecord", "xsd:string", "DCY", source_labels=("调查员",)),
    _data(
        "surveyOpinion",
        "调查意见",
        "SurveyRecord",
        "xsd:string",
        "DCYJ",
        source_labels=("调查意见",),
    ),
    _data(
        "reviewDate", "审核日期", "SurveyRecord", "xsd:date", "SHRQ", source_labels=("审核日期",)
    ),
    _data("reviewerName", "审核员", "SurveyRecord", "xsd:string", "SHY", source_labels=("审核员",)),
    _data(
        "reviewOpinion",
        "审核意见",
        "SurveyRecord",
        "xsd:string",
        "SHYJ",
        source_labels=("审核意见",),
    ),
    _data(
        "registrationStatus",
        "登记状态",
        "RegistrationRecord",
        "xsd:string",
        "DJZT",
        source_labels=("登记状态",),
    ),
    _data(
        "registrationReason",
        "登记原因",
        "RegistrationRecord",
        "xsd:string",
        source_labels=("登记原因",),
    ),
    _data(
        "registrationTime",
        "登记时间",
        "RegistrationRecord",
        "xsd:dateTime",
        source_labels=("登记时间",),
    ),
    _data(
        "registrationAuthority",
        "登记机构",
        "RegistrationRecord",
        "xsd:string",
        source_labels=("登记机构",),
    ),
    _data("registrarName", "登簿人", "RegistrationRecord", "xsd:string", source_labels=("登簿人",)),
    _data(
        "registrationType",
        "登记类型",
        "RegistrationRecord",
        "xsd:string",
        source_labels=("变更登记",),
    ),
    _data(
        "certificateNumber",
        "不动产权证号",
        "RegistrationRecord",
        "xsd:string",
        source_labels=("不动产权证号",),
    ),
    _data(
        "permitNumber",
        "许可证号",
        "AdministrativePermit",
        "xsd:string",
        "JSGCGHXKZH",
        "XCJSGHXKZH",
        source_labels=("建设工程规划许可证号", "乡村建设规划许可证号"),
    ),
    _data(
        "rightStartTime",
        "使用权起始时间",
        "LandUseRight",
        "xsd:dateTime",
        source_labels=("使用权起始时间",),
    ),
    _data(
        "rightEndTime",
        "使用权结束时间",
        "LandUseRight",
        "xsd:dateTime",
        source_labels=("使用权结束时间",),
    ),
    _data(
        "rightTerm", "土地使用期限", "LandUseRight", "xsd:string", source_labels=("土地使用期限",)
    ),
    _data("rightArea", "使用权面积", "LandUseRight", "xsd:decimal", source_labels=("使用权面积",)),
    _data(
        "acquisitionPrice", "取得价格", "LandUseRight", "xsd:decimal", source_labels=("取得价格",)
    ),
    _data(
        "rightCreationMethod",
        "权利设定方式",
        "LandUseRight",
        "xsd:string",
        source_labels=("权利设定方式",),
    ),
    _data(
        "landUsePurpose",
        "土地用途",
        "LandUseRight",
        "xsd:string",
        source_labels=("土地用途", "用途"),
    ),
    _data("numericValue", "数值", "Measurement", "xsd:decimal", source_labels=("指标值", "测量值")),
    _data("observationTime", "观测时间", "NaturalResourceObservation", "xsd:dateTime"),
    _data("validFrom", "有效期起", "NaturalResourceState", "xsd:dateTime"),
    _data("validTo", "有效期止", "NaturalResourceState", "xsd:dateTime"),
    _data("aggregationMethod", "聚合方法", "AggregationContext", "xsd:string"),
    _data("aggregationPeriod", "统计周期", "AggregationContext", "xsd:string"),
    _data("thresholdValue", "阈值数值", "DistanceThreshold", "xsd:decimal"),
    _data("thresholdKind", "阈值类型", "DistanceThreshold", "xsd:string"),
    _data("populationValue", "人口数值", "PopulationDenominator", "xsd:decimal"),
    _data("populationReferenceTime", "人口口径时点", "PopulationDenominator", "xsd:dateTime"),
)


# Explicitly reviewed schema-to-domain bindings. A binding says what a source
# schema describes; it never promotes that table or layer to an OWL class.
SCHEMA_BINDINGS = (
    _binding("LandParcel", "DLTB"),
    _binding("Building", "CQNFWJZA", "ZRZ"),
    _binding("EducationalFacility", "XXA"),
    _binding("MedicalFacility", "YLJGA"),
    _binding("WelfareFacility", "FLJGA"),
    _binding("CulturalFacility", "WHHDA", "WYCGA"),
    _binding("SportsFacility", "TYHDA"),
    _binding("TransportStation", "JTFWCZA", "JTYSYDA"),
    _binding("GreenOpenSpace", "GYYLDA"),
    _binding("UtilityFacility", "GYSSA"),
    _binding("EmergencyShelter", "YJBNA"),
    _binding("Cemetery", "BZSSA"),
    _binding("SurfaceWaterBody", "HYDA", "HYDL"),
    _binding("PlannedLandUseArea", "ZXCQGHYDYH"),
    _binding("PlanningZone", "ZXCQGHFQ"),
    _binding("UrbanBlueLine", "CZKFBJFWCSLX"),
    _binding("UrbanGreenLine", "CZKFBJFWCSLVX"),
    _binding("UrbanYellowLine", "CZKFBJFWCSHX"),
    _binding("UrbanPurpleLine", "CZKFBJFWCSZX"),
    _binding(
        "CadastralParcel",
        source_labels=("宗地",),
        package_path_contains="030202国有建设用地使用权",
        source_id="ea-repository",
    ),
    _binding(
        "LandUseRight",
        source_labels=("JSYDSYQ表",),
        package_path_contains="030202国有建设用地使用权",
        source_id="ea-repository",
    ),
)


FIELD_RELATION_MAPPINGS = (
    _field_relation(
        "hasRegistrationUnit",
        "NaturalResourceRegistrationUnit",
        "BDCDYB",
        "不动产单元号",
        source_labels=("幢不动产单元表", "不动产单元号"),
    ),
    _field_relation("rightOf", "CadastralParcel", "宗地代码", source_labels=("宗地代码",)),
    _field_relation(
        "documentedBy",
        "EvidenceArtifact",
        "CQLYZMCL",
        "FCCT",
        "FCT",
        "FWDCB",
        "FWQSJXSYT",
        "GHHSJGWJ",
        source_labels=(
            "产权来源证明材料",
            "房产草图",
            "房产图",
            "房屋调查表",
            "房屋权属界线示意图",
            "规划核实结果文件",
            "宗地图",
        ),
    ),
    _field_relation(
        "hasPermit",
        "AdministrativePermit",
        "JSGCGHXKZ",
        "XCJSGHXKZ",
        source_labels=("建设工程规划许可证", "乡村建设规划许可证"),
    ),
    _field_relation("hasRight", "LandUseRight", source_labels=("国有建设用地使用权",)),
)


# Storage implementation fields stay in the source mapping module. Giving
# them an explicit disposition prevents "not promoted" from being confused
# with an ontology coverage gap.
SCHEMA_ONLY_FIELD_CODES = frozenset(
    {
        "GEOMETRY",
        "SHAPE",
        "SHAPE_LENGTH",
        "SHAPE_AREA",
        "OBJECTID",
        "ROWVERSION",
    }
)


ADDITIONAL_SUBCLASS_AXIOMS = (
    ("ObservedLandUseState", "ObservedState"),
    ("PlannedLandUseState", "PlannedState"),
)


CLASS_RESTRICTIONS = (
    ClassRestrictionSeed("LandParcel", "spatiallyRepresents", "Land", "exact", 1),
    ClassRestrictionSeed("LandUseState", "stateOf", "LandParcel", "exact", 1),
    ClassRestrictionSeed("LandUseTransition", "affectsParcel", "LandParcel", "exact", 1),
    ClassRestrictionSeed("LandUseTransition", "hasSourceState", "LandUseState", "exact", 1),
    ClassRestrictionSeed("LandUseTransition", "hasTargetState", "LandUseState", "exact", 1),
    ClassRestrictionSeed("NaturalResourceRight", "heldBy", "NaturalResourceActor", "min", 1),
    ClassRestrictionSeed("NaturalResourceRole", "roleOf", "NaturalResourceActor", "exact", 1),
    ClassRestrictionSeed("LandUseTransition", "governedBy", "NaturalResourceRule", "min", 1),
    ClassRestrictionSeed(
        "NaturalResourceRestriction", "restricts", "NaturalResourceEntity", "min", 1
    ),
    ClassRestrictionSeed(
        "AdministrativePlace", "representsAdministrativeUnit", "AdministrativeUnit", "exact", 1
    ),
    ClassRestrictionSeed("UrbanFormAssessment", "assessmentOf", "SpatialUnit", "exact", 1),
    ClassRestrictionSeed("BuiltEnvironmentAssessment", "assessmentOf", "SpatialUnit", "exact", 1),
    ClassRestrictionSeed(
        "Measurement", "measurementOfObservation", "NaturalResourceObservation", "exact", 1
    ),
    ClassRestrictionSeed(
        "ServiceCoverageObservation", "aboutEntity", "NaturalResourceEntity", "exact", 1
    ),
    ClassRestrictionSeed("ServiceCoverageObservation", "usesTravelMode", "TravelMode", "min", 1),
    ClassRestrictionSeed(
        "ServiceCoverageObservation", "hasDistanceThreshold", "DistanceThreshold", "min", 1
    ),
    ClassRestrictionSeed("WaterSystem", "hasWaterFeature", "NaturalResourceEntity", "min", 1),
)


DISJOINT_GROUPS = (
    ("AgriculturalLand", "ConstructionLand", "UnusedLand"),
    ("CultivatedLand", "NonCultivatedAgriculturalLand"),
    ("PaddyField", "IrrigatedLand", "DryLand"),
    ("AgriculturalLandUseState", "ConstructionLandUseState", "UnusedLandUseState"),
    ("CultivatedLandUseState", "NonCultivatedAgriculturalLandUseState"),
    ("NaturalResourceEntity", "NaturalResourceActivity", "NaturalResourceState"),
    ("Land", "SpatialUnit"),
    ("ObservedState", "PlannedState"),
    ("NaturalResourceActor", "NaturalResourceRole"),
    ("Person", "Organization"),
    ("PublicAuthority", "Enterprise"),
)


TRANSITION_RULES = (
    ("AgriculturalStructureAdjustment", "allowedSource", "CultivatedLandUseState"),
    ("AgriculturalStructureAdjustment", "allowedSource", "NonCultivatedAgriculturalLandUseState"),
    ("AgriculturalStructureAdjustment", "allowedTarget", "CultivatedLandUseState"),
    ("AgriculturalStructureAdjustment", "allowedTarget", "NonCultivatedAgriculturalLandUseState"),
    ("ConstructionOccupation", "allowedSource", "AgriculturalLandUseState"),
    ("ConstructionOccupation", "allowedTarget", "ConstructionLandUseState"),
)


def class_id(name: str) -> str:
    return f"gda:nr:class:{name}"


def class_uri(name: str) -> str:
    return f"{BASE_URI}class/{name}"


def property_id(name: str) -> str:
    return f"gda:nr:property:{name}"


def property_uri(name: str) -> str:
    return f"{BASE_URI}property/{name}"


def _curated_source() -> SourceRecord:
    payload = {
        "classes": [seed.__dict__ for seed in CLASS_SEEDS],
        "object_properties": [seed.__dict__ for seed in OBJECT_PROPERTIES],
        "data_properties": [seed.__dict__ for seed in DATA_PROPERTIES],
        "schema_bindings": [seed.__dict__ for seed in SCHEMA_BINDINGS],
        "field_relation_mappings": [seed.__dict__ for seed in FIELD_RELATION_MAPPINGS],
        "schema_only_field_codes": sorted(SCHEMA_ONLY_FIELD_CODES),
        "additional_subclass_axioms": ADDITIONAL_SUBCLASS_AXIOMS,
        "class_restrictions": [seed.__dict__ for seed in CLASS_RESTRICTIONS],
        "disjoint_groups": DISJOINT_GROUPS,
        "transition_rules": TRANSITION_RULES,
    }
    return SourceRecord(
        source_id=CURATED_SOURCE_ID,
        source_kind="curated_domain_ontology",
        title="Natural Resource Domain Ontology v2.3 curated model",
        locator="package:data_agent.ontology.domain_model",
        source_version=CURATED_MODEL_VERSION,
        sha256=sha256_json(payload),
        metadata={
            "authority": "ADR-140;ADR-162;ADR-163",
            "review_status": "curated_seed_pending_domain-owner-acceptance",
            "modeling_method": "competency-question-and-source-evidence-driven",
            "attachment_source_id": ATTACHMENT_SOURCE_ID,
        },
    )


def _attachment_source() -> SourceRecord:
    return SourceRecord(
        source_id=ATTACHMENT_SOURCE_ID,
        source_kind="attachment_field_catalog",
        title="时空基底数据属性挂接0804",
        locator="attachment:时空基底数据属性挂接0804.xlsx",
        source_version="2026-08-04",
        sha256=ATTACHMENT_SOURCE_SHA256,
        metadata={
            "worksheet_count": 2,
            "sheet1_attribute_row_count": 129,
            "sheet2_attribute_row_count": 140,
            "role": "field_coverage_and_mapping_evidence",
            "normative_authority": False,
        },
    )


def _source_evidence(
    seed: ClassSeed,
    source_concepts: list[ConceptRecord],
) -> list[dict[str, object]]:
    labels = {_normalize_label(seed.label), *(_normalize_label(label) for label in seed.aliases)}
    matches: list[dict[str, object]] = []
    for concept in source_concepts:
        source_labels = {
            _normalize_label(concept.pref_label),
            *(_normalize_label(label) for label in concept.alt_labels),
        }
        if not labels.intersection(source_labels):
            continue
        matches.append(
            {
                "source_id": concept.source_id,
                "source_concept_id": concept.concept_id,
                "source_object_id": concept.source_object_id,
                "source_system": concept.source_system,
                "source_uri": concept.uri,
                "code": concept.code,
                "heading": concept.provenance.get("heading"),
                "occurrences": concept.provenance.get("occurrences", []),
                "package_path": concept.package_path,
            }
        )
    return sorted(
        matches,
        key=lambda item: (
            0 if str(item["source_id"]).startswith("std-doc-") else 1,
            str(item["source_id"]),
            str(item["source_concept_id"]),
        ),
    )


def _curated_concepts(source_concepts: list[ConceptRecord]) -> list[ConceptRecord]:
    records: list[ConceptRecord] = []
    for seed in CLASS_SEEDS:
        evidence = _source_evidence(seed, source_concepts)
        records.append(
            ConceptRecord(
                concept_id=class_id(seed.name),
                uri=class_uri(seed.name),
                kind=seed.kind,
                code=seed.name,
                pref_label=seed.label,
                alt_labels=list(seed.aliases),
                definition=seed.definition,
                domain_id=seed.domain_id,
                source_system="curated_domain",
                source_id=CURATED_SOURCE_ID,
                lifecycle_status="curated",
                provenance={
                    "modeling_role": seed.kind,
                    "review_status": "domain_owner_review_required",
                    "review_disposition": "accepted",
                    "decision": "ADR-140;ADR-162;ADR-163",
                    "evidence_status": "source_matches_found"
                    if evidence
                    else "explicit_evidence_gap",
                    "source_evidence": evidence,
                },
            )
        )
    return records


def _curated_properties() -> list[PropertyRecord]:
    records: list[PropertyRecord] = []
    for ordinal, seed in enumerate(DATA_PROPERTIES, start=1):
        records.append(
            PropertyRecord(
                property_id=property_id(seed.name),
                owner_concept_id=class_id(seed.owner),
                uri=property_uri(seed.name),
                code=seed.name,
                pref_label=seed.label,
                datatype=seed.datatype,
                min_count=seed.min_count,
                max_count=seed.max_count,
                ordinal=ordinal,
                source_id=CURATED_SOURCE_ID,
                provenance={
                    "modeling_role": "curated_domain_data_property",
                    "definition": seed.definition,
                    "source_field_codes": list(seed.source_codes),
                    "source_field_labels": list(seed.source_labels),
                    "mapping_evidence_source": ATTACHMENT_SOURCE_ID,
                    "automatic_schema_promotion": False,
                    "review_status": "domain_owner_review_required",
                    "review_disposition": "accepted",
                    "decision": "ADR-140;ADR-162;ADR-163;evidence-expansion-0804",
                },
            )
        )
    return records


def _curated_relations() -> list[RelationRecord]:
    records: list[RelationRecord] = []
    for seed in CLASS_SEEDS:
        if seed.parent:
            records.append(
                RelationRecord(
                    relation_id=f"gda:nr:subclass:{seed.name}:{seed.parent}",
                    relation_type="subClassOf",
                    source_concept_id=class_id(seed.name),
                    target_concept_id=class_id(seed.parent),
                    pref_label="属于",
                    transitive=True,
                    source_id=CURATED_SOURCE_ID,
                    provenance={"axiom_type": "rdfs:subClassOf"},
                )
            )
    for child, parent in ADDITIONAL_SUBCLASS_AXIOMS:
        records.append(
            RelationRecord(
                relation_id=f"gda:nr:subclass:{child}:{parent}",
                relation_type="subClassOf",
                source_concept_id=class_id(child),
                target_concept_id=class_id(parent),
                pref_label="属于",
                transitive=True,
                source_id=CURATED_SOURCE_ID,
                provenance={"axiom_type": "rdfs:subClassOf", "decision": "ADR-162"},
            )
        )
    for group in DISJOINT_GROUPS:
        for index, left in enumerate(group):
            for right in group[index + 1 :]:
                records.append(
                    RelationRecord(
                        relation_id=f"gda:nr:disjoint:{left}:{right}",
                        relation_type="disjointWith",
                        source_concept_id=class_id(left),
                        target_concept_id=class_id(right),
                        pref_label="互斥",
                        symmetric=True,
                        source_id=CURATED_SOURCE_ID,
                        provenance={"axiom_type": "owl:disjointWith"},
                    )
                )
    for prop in OBJECT_PROPERTIES:
        records.append(
            RelationRecord(
                relation_id=f"gda:nr:object-property:{prop.name}",
                relation_type="objectProperty",
                source_concept_id=class_id(prop.domain),
                target_concept_id=class_id(prop.range),
                pref_label=prop.label,
                source_id=CURATED_SOURCE_ID,
                provenance={
                    "property_name": prop.name,
                    "restriction": prop.restriction,
                    "inverse_property": prop.inverse,
                    "functional": prop.functional,
                    "decision": "ADR-162",
                },
            )
        )
    for restriction in CLASS_RESTRICTIONS:
        records.append(
            RelationRecord(
                relation_id=(
                    f"gda:nr:class-restriction:{restriction.owner}:"
                    f"{restriction.property_name}:{restriction.cardinality}:{restriction.count}"
                ),
                relation_type="classRestriction",
                source_concept_id=class_id(restriction.owner),
                target_concept_id=class_id(restriction.filler),
                pref_label="基数约束",
                source_id=CURATED_SOURCE_ID,
                provenance={
                    "axiom_type": "owl:Restriction",
                    "property_name": restriction.property_name,
                    "cardinality": restriction.cardinality,
                    "count": restriction.count,
                    "decision": "ADR-162",
                },
            )
        )
    for process, relation_type, state in TRANSITION_RULES:
        records.append(
            RelationRecord(
                relation_id=f"gda:nr:transition-rule:{process}:{relation_type}:{state}",
                relation_type=relation_type,
                source_concept_id=class_id(process),
                target_concept_id=class_id(state),
                pref_label="允许源状态" if relation_type == "allowedSource" else "允许目标状态",
                source_id=CURATED_SOURCE_ID,
                provenance={"axiom_type": "governed-transition-rule"},
            )
        )
    return records


def _transform_source_concepts(
    flat: CompiledOntology,
) -> tuple[list[ConceptRecord], dict[str, str]]:
    kind_map = {
        "Domain": "Domain",
        "FeatureType": "SchemaArtifact",
        "DatasetSchema": "SchemaArtifact",
        "SchemaArtifact": "SchemaArtifact",
        "ValueDomain": "ReferenceScheme",
        "ReferenceScheme": "ReferenceScheme",
        "ValueDomainMember": "ReferenceConcept",
        "ReferenceConcept": "ReferenceConcept",
        "CRS": "CRSReference",
        "CRSReference": "CRSReference",
    }
    concepts: list[ConceptRecord] = []
    transformed_kinds: dict[str, str] = {}
    for record in flat.concepts:
        target_kind = kind_map.get(record.kind)
        if not target_kind:
            continue
        transformed_kinds[record.concept_id] = target_kind
        provenance = dict(record.provenance)
        provenance.update(
            {
                "source_modeling_role": record.kind,
                "modeling_role": target_kind,
                "not_a_domain_class": target_kind
                in {
                    "SchemaArtifact",
                    "ReferenceScheme",
                    "ReferenceConcept",
                    "CRSReference",
                },
            }
        )
        concepts.append(
            record.model_copy(
                update={
                    "kind": target_kind,
                    "source_id": (
                        CURATED_SOURCE_ID
                        if record.source_id == "gda-core-vocabulary"
                        else record.source_id
                    ),
                    "definition": (
                        f"数据结构制品：{record.definition}"
                        if target_kind == "SchemaArtifact"
                        else record.definition
                    ),
                    "provenance": provenance,
                }
            )
        )
    return concepts, transformed_kinds


def _normalize_label(value: str) -> str:
    return "".join(character for character in value.casefold().strip() if character.isalnum())


def _class_ancestor_distances() -> dict[str, dict[str, int]]:
    parents = {seed.name: seed.parent for seed in CLASS_SEEDS}
    distances: dict[str, dict[str, int]] = {}
    for name in parents:
        current: str | None = name
        distance = 0
        values: dict[str, int] = {}
        while current:
            values[current] = distance
            current = parents.get(current)
            distance += 1
        distances[name] = values
    return distances


def _schema_binding_targets(
    concepts: list[ConceptRecord],
) -> dict[str, tuple[str, ...]]:
    targets: dict[str, list[str]] = {}
    for concept in concepts:
        if concept.kind != "SchemaArtifact":
            continue
        code = str(concept.code or "").casefold()
        label = _normalize_label(concept.pref_label)
        path = concept.package_path or ""
        for binding in SCHEMA_BINDINGS:
            if binding.source_id and concept.source_id != binding.source_id:
                continue
            if binding.package_path_contains and binding.package_path_contains not in path:
                continue
            code_match = bool(binding.source_codes) and code in {
                value.casefold() for value in binding.source_codes
            }
            label_match = bool(binding.source_labels) and label in {
                _normalize_label(value) for value in binding.source_labels
            }
            if not code_match and not label_match:
                continue
            targets.setdefault(concept.concept_id, []).append(binding.target_class)
    return {
        concept_id: tuple(dict.fromkeys(class_names)) for concept_id, class_names in targets.items()
    }


def _explicit_schema_mappings(
    concepts: list[ConceptRecord],
    schema_targets: dict[str, tuple[str, ...]],
) -> list[MappingRecord]:
    concept_by_id = {concept.concept_id: concept for concept in concepts}
    mappings: list[MappingRecord] = []
    for source_id, target_names in schema_targets.items():
        source = concept_by_id[source_id]
        for target_name in target_names:
            target_id = class_id(target_name)
            mappings.append(
                MappingRecord(
                    mapping_id=(
                        f"gda:nr:evidence-schema-binding:{stable_token(source_id, target_id)}"
                    ),
                    source_concept_id=source_id,
                    target_concept_id=target_id,
                    mapping_type="describes",
                    mapping_status=MappingStatus.CONFIRMED,
                    confidence=1.0,
                    evidence={
                        "match_basis": ["explicit_curated_schema_binding"],
                        "source_schema_code": source.code,
                        "source_schema_label": source.pref_label,
                        "source_role": "SchemaArtifact",
                        "target_role": concept_by_id[target_id].kind,
                        "automatic_class_promotion": False,
                        "decision": "ADR-163",
                    },
                    reviewed_by="curated-schema-binding-policy-v3",
                    reviewed_at=datetime(2026, 8, 5, tzinfo=UTC),
                )
            )
    return mappings


def _field_relation_mapping(record: PropertyRecord) -> FieldRelationSeed | None:
    code = _normalize_label(record.code)
    label = _normalize_label(record.pref_label)
    label_matches = [
        seed
        for seed in FIELD_RELATION_MAPPINGS
        if label and label in {_normalize_label(value) for value in seed.source_labels}
    ]
    if len(label_matches) == 1:
        return label_matches[0]
    code_matches = [
        seed
        for seed in FIELD_RELATION_MAPPINGS
        if code and code in {_normalize_label(value) for value in seed.source_codes}
    ]
    return code_matches[0] if len(code_matches) == 1 else None


def _annotate_source_properties(
    properties: list[PropertyRecord],
    schema_targets: dict[str, tuple[str, ...]],
) -> list[PropertyRecord]:
    by_code: dict[str, dict[str, DataPropertySeed]] = {}
    by_label: dict[str, dict[str, DataPropertySeed]] = {}
    for seed in DATA_PROPERTIES:
        for code in seed.source_codes:
            by_code.setdefault(_normalize_label(code), {})[seed.name] = seed
        for label in (seed.label, *seed.source_labels):
            by_label.setdefault(_normalize_label(label), {})[seed.name] = seed

    ancestor_distances = _class_ancestor_distances()
    related_owners = {
        "NaturalResourceObservation",
        "Measurement",
        "SurveyRecord",
        "RegistrationRecord",
        "EvidenceArtifact",
        "AdministrativePermit",
        "NaturalResourceRight",
        "LandUseRight",
    }
    annotated: list[PropertyRecord] = []
    for record in properties:
        target_classes = schema_targets.get(record.owner_concept_id)
        if not target_classes:
            annotated.append(record)
            continue

        label_candidates = list(by_label.get(_normalize_label(record.pref_label), {}).values())
        candidates = label_candidates or list(
            by_code.get(_normalize_label(record.code), {}).values()
        )
        scored: list[tuple[int, DataPropertySeed, str]] = []
        for target_class in target_classes:
            distances = ancestor_distances.get(target_class, {target_class: 0})
            for candidate in candidates:
                if candidate.owner in distances:
                    scored.append((distances[candidate.owner], candidate, target_class))
                elif target_class in ancestor_distances.get(candidate.owner, {}):
                    descendant_distance = ancestor_distances[candidate.owner][target_class]
                    scored.append((50 + descendant_distance, candidate, target_class))
                elif candidate.owner in related_owners:
                    scored.append((100, candidate, target_class))

        provenance = dict(record.provenance)
        if scored:
            minimum = min(score for score, _, _ in scored)
            best = {
                candidate.name: (candidate, target_class)
                for score, candidate, target_class in scored
                if score == minimum
            }
            if len(best) == 1:
                candidate, target_class = next(iter(best.values()))
                provenance.update(
                    {
                        "semantic_disposition": (
                            "mapped_domain_property" if minimum < 50 else "mapped_related_semantics"
                        ),
                        "semantic_target_property_id": property_id(candidate.name),
                        "semantic_target_property_uri": property_uri(candidate.name),
                        "semantic_target_class_id": class_id(target_class),
                        "semantic_mapping_basis": (
                            "source_field_label" if label_candidates else "source_field_code"
                        ),
                        "automatic_schema_promotion": False,
                        "decision": "ADR-163",
                    }
                )
                annotated.append(record.model_copy(update={"provenance": provenance}))
                continue
            provenance.update(
                {
                    "semantic_disposition": "ambiguous_property_mapping",
                    "semantic_candidate_property_ids": sorted(property_id(name) for name in best),
                    "decision": "ADR-163",
                }
            )
            annotated.append(record.model_copy(update={"provenance": provenance}))
            continue

        relation = _field_relation_mapping(record)
        if relation:
            provenance.update(
                {
                    "semantic_disposition": "mapped_object_relation",
                    "semantic_target_relation": relation.relation_name,
                    "semantic_relation_range_class_id": class_id(relation.target_class),
                    "semantic_target_class_ids": [
                        class_id(target_class) for target_class in target_classes
                    ],
                    "automatic_schema_promotion": False,
                    "decision": "ADR-163",
                }
            )
        elif record.code.upper() in SCHEMA_ONLY_FIELD_CODES:
            provenance.update(
                {
                    "semantic_disposition": "schema_implementation_only",
                    "semantic_exclusion_reason": (
                        "storage or geometry implementation field; retained as SchemaField"
                    ),
                    "decision": "ADR-163",
                }
            )
        else:
            provenance.update(
                {
                    "semantic_disposition": "unresolved_domain_field",
                    "semantic_target_class_ids": [
                        class_id(target_class) for target_class in target_classes
                    ],
                    "decision": "ADR-163",
                }
            )
        annotated.append(record.model_copy(update={"provenance": provenance}))
    return annotated


def _semantic_mappings(
    concepts: list[ConceptRecord],
    *,
    explicitly_bound_source_ids: set[str] | None = None,
) -> list[MappingRecord]:
    explicitly_bound_source_ids = explicitly_bound_source_ids or set()
    curated_by_label: dict[str, ConceptRecord] = {}
    for concept in concepts:
        if concept.kind not in {
            "DomainClass",
            "ProcessClass",
            "StateClass",
            "RoleClass",
            "InformationClass",
            "ObservationClass",
        }:
            continue
        for label in [concept.pref_label, *concept.alt_labels]:
            curated_by_label.setdefault(_normalize_label(label), concept)

    mappings: list[MappingRecord] = []
    for concept in concepts:
        if concept.concept_id in explicitly_bound_source_ids:
            continue
        normalized = _normalize_label(concept.pref_label)
        target = curated_by_label.get(normalized)
        if not target or concept.concept_id == target.concept_id:
            continue
        if concept.kind == "ReferenceConcept":
            mapping_type = "denotes_class"
            status = MappingStatus.CONFIRMED
            confidence = 1.0
        elif concept.kind == "SchemaArtifact":
            mapping_type = "describes"
            status = MappingStatus.CANDIDATE
            confidence = 0.92
        else:
            continue
        mappings.append(
            MappingRecord(
                mapping_id=(
                    "gda:nr:semantic-mapping:"
                    f"{stable_token(concept.concept_id, target.concept_id)}"
                ),
                source_concept_id=concept.concept_id,
                target_concept_id=target.concept_id,
                mapping_type=mapping_type,
                mapping_status=status,
                confidence=confidence,
                evidence={
                    "match_basis": ["normalized_pref_label"],
                    "semantic_assertion": mapping_type,
                    "source_role": concept.kind,
                    "target_role": target.kind,
                    "automatic_class_promotion": False,
                },
                reviewed_by="curated-label-mapping-policy-v2"
                if status == MappingStatus.CONFIRMED
                else None,
                reviewed_at=datetime(2026, 8, 4, tzinfo=UTC)
                if status == MappingStatus.CONFIRMED
                else None,
            )
        )
    return mappings


def compile_curated_domain_ontology(flat: CompiledOntology) -> CompiledOntology:
    """Project flat extraction into domain, reference and mapping modules."""
    from .compiler import CompiledOntology

    source_concepts, _ = _transform_source_concepts(flat)
    curated_concepts = _curated_concepts(flat.concepts)
    concepts = curated_concepts + source_concepts
    concept_ids = {record.concept_id for record in concepts}
    schema_targets = _schema_binding_targets(source_concepts)

    source_properties = [
        record
        for record in flat.properties
        if record.owner_concept_id in concept_ids and record.source_id != CURATED_SOURCE_ID
    ]
    properties = _curated_properties() + _annotate_source_properties(
        source_properties,
        schema_targets,
    )
    relations = _curated_relations()
    for seed in CLASS_SEEDS:
        domain_concept_id = f"gda:nr:domain:{seed.domain_id}"
        if domain_concept_id not in concept_ids:
            continue
        relations.append(
            RelationRecord(
                relation_id=f"gda:nr:subject-area-class:{seed.domain_id}:{seed.name}",
                relation_type="hasDomainConcept",
                source_concept_id=domain_concept_id,
                target_concept_id=class_id(seed.name),
                pref_label="包含领域概念",
                source_id=CURATED_SOURCE_ID,
                provenance={"modeling_role": "navigation"},
            )
        )
    for record in flat.relations:
        if record.source_id == CURATED_SOURCE_ID:
            continue
        if (
            record.source_concept_id not in concept_ids
            or record.target_concept_id not in concept_ids
        ):
            continue
        if record.relation_type == "hasMember":
            relations.append(record)
        elif record.relation_type == "schemaAssociation":
            relations.append(record)
        elif record.relation_type == "associatedWith":
            relations.append(
                record.model_copy(
                    update={
                        "relation_type": "schemaAssociation",
                        "provenance": dict(record.provenance, modeling_role="schema_metadata"),
                    }
                )
            )
        elif record.relation_type == "usesCRS":
            relations.append(
                record.model_copy(
                    update={
                        "source_id": (
                            CURATED_SOURCE_ID
                            if record.source_id == "gda-core-vocabulary"
                            else record.source_id
                        ),
                        "provenance": dict(record.provenance, modeling_role="metadata_constraint"),
                    }
                )
            )

    for concept in source_concepts:
        if concept.kind != "SchemaArtifact" or not concept.domain_id:
            continue
        domain_id = f"gda:nr:domain:{concept.domain_id}"
        if domain_id not in concept_ids:
            continue
        relations.append(
            RelationRecord(
                relation_id=f"gda:nr:subject-area-artifact:{stable_token(concept.concept_id)}",
                relation_type="hasSchemaArtifact",
                source_concept_id=domain_id,
                target_concept_id=concept.concept_id,
                pref_label="包含数据结构制品",
                source_id=concept.source_id,
                provenance={"modeling_role": "data_application_mapping"},
            )
        )

    mappings: list[MappingRecord] = []
    curated_concept_ids = {record.concept_id for record in curated_concepts}
    for record in flat.mappings:
        if (
            record.source_concept_id in concept_ids
            and record.target_concept_id in concept_ids
            and record.source_concept_id not in curated_concept_ids
            and record.target_concept_id not in curated_concept_ids
        ):
            mappings.append(
                record.model_copy(
                    update={
                        "mapping_type": "schema_correspondence",
                        "evidence": dict(
                            record.evidence, semantic_assertion="schema_correspondence"
                        ),
                    }
                )
            )
    mappings.extend(_explicit_schema_mappings(concepts, schema_targets))
    mappings.extend(
        _semantic_mappings(
            concepts,
            explicitly_bound_source_ids=set(schema_targets),
        )
    )
    mappings = list({record.mapping_id: record for record in mappings}.values())

    mappings_by_source: dict[str, list[MappingRecord]] = {}
    for mapping in mappings:
        mappings_by_source.setdefault(mapping.source_concept_id, []).append(mapping)
    transformed_roles = {concept.concept_id: concept.kind for concept in source_concepts}
    review_dispositions: list[dict[str, object]] = []
    for concept in curated_concepts:
        review_dispositions.append(
            {
                "candidate_id": concept.concept_id,
                "candidate_kind": concept.kind,
                "candidate_label": concept.pref_label,
                "source_id": concept.source_id,
                "disposition": "accepted",
                "retained_modeling_role": concept.kind,
                "review_status": concept.provenance["review_status"],
                "evidence_status": concept.provenance["evidence_status"],
                "evidence": concept.provenance["source_evidence"],
                "decision": "ADR-140;ADR-162;ADR-163",
            }
        )
    for concept in flat.concepts:
        if concept.source_system == "curated_domain":
            continue
        concept_mappings = mappings_by_source.get(concept.concept_id, [])
        retained_role = transformed_roles.get(concept.concept_id)
        if concept_mappings:
            disposition = "mapped"
            reason = "source candidate is retained outside the domain class hierarchy and mapped"
        elif concept.lifecycle_status in {"deprecated", "retired", "superseded"}:
            disposition = "deprecated"
            reason = "source lifecycle status marks the candidate as deprecated"
        else:
            disposition = "rejected"
            reason = (
                "retained as a source artifact but rejected for automatic domain-class promotion"
                if retained_role
                else (
                    "excluded from the curated projection because its source role "
                    "is not a domain concept"
                )
            )
        review_dispositions.append(
            {
                "candidate_id": concept.concept_id,
                "candidate_kind": concept.kind,
                "candidate_label": concept.pref_label,
                "source_id": concept.source_id,
                "source_object_id": concept.source_object_id,
                "disposition": disposition,
                "retained_modeling_role": retained_role,
                "review_status": "policy_reviewed"
                if disposition != "mapped"
                else "mapping_review_required",
                "mapping_ids": [mapping.mapping_id for mapping in concept_mappings],
                "reason": reason,
                "decision": "ADR-140;ADR-162;ADR-163",
            }
        )

    sources = [
        source
        for source in flat.sources
        if source.source_id
        not in {
            "gda-core-vocabulary",
            CURATED_SOURCE_ID,
            ATTACHMENT_SOURCE_ID,
        }
    ]
    sources.extend((_attachment_source(), _curated_source()))
    issues = [
        dict(issue, layer="source_quality") if "layer" not in issue else issue
        for issue in flat.issues
    ]
    return CompiledOntology(
        sources=sources,
        concepts=concepts,
        properties=properties,
        relations=relations,
        mappings=mappings,
        issues=issues,
        review_dispositions=review_dispositions,
    )
