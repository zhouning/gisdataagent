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
    RelationRecord,
    SourceRecord,
    sha256_json,
    stable_token,
)

if TYPE_CHECKING:
    from .compiler import CompiledOntology


CURATED_SOURCE_ID = "natural-resource-domain-model-v2"


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


CLASS_SEEDS = (
    _seed("NaturalResourceThing", "自然资源领域事物", "DomainClass", None, "01", "自然资源领域中可被区分和描述的事物总类。"),
    _seed("NaturalResourceEntity", "自然资源实体", "DomainClass", "NaturalResourceThing", "01", "在空间中持续存在并可被调查、确权、规划或管制的现实对象。"),
    _seed("NaturalResource", "自然资源", "DomainClass", "NaturalResourceEntity", "02", "具有自然形成基础和资源利用、生态或资产价值的现实对象。"),
    _seed("Land", "土地", "DomainClass", "NaturalResource", "02", "由一定空间范围、地表及相关自然和利用属性构成的核心自然资源对象。"),
    _seed("LandParcel", "地块", "DomainClass", "Land", "02", "为调查、规划、管理或业务处理而划定边界的土地空间单元。", "图斑"),
    _seed("CadastralParcel", "宗地", "DomainClass", "LandParcel", "03", "权属界址封闭且具有独立不动产单元语义的土地单元。"),
    _seed("AgriculturalLand", "农用地", "DomainClass", "Land", "02", "在某一有效时段主要用于农业生产及其直接服务活动的土地。"),
    _seed("ConstructionLand", "建设用地", "DomainClass", "Land", "02", "在某一有效时段用于建造建筑物、构筑物或其他建设活动的土地。"),
    _seed("UnusedLand", "未利用地", "DomainClass", "Land", "02", "在某一有效时段未归入农用地或建设用地利用状态的土地。"),
    _seed("CultivatedLand", "耕地", "DomainClass", "AgriculturalLand", "02", "用于种植农作物并按耕地制度调查、保护和管理的农用地。", "农田"),
    _seed("NonCultivatedAgriculturalLand", "非耕农用地", "DomainClass", "AgriculturalLand", "02", "除耕地以外用于农业生产或直接服务农业生产的农用地集合。"),
    _seed("PaddyField", "水田", "DomainClass", "CultivatedLand", "02", "用于种植水生作物、具备相应灌溉条件的耕地。"),
    _seed("IrrigatedLand", "水浇地", "DomainClass", "CultivatedLand", "02", "有水源和灌溉设施、一般年份能正常灌溉的耕地。"),
    _seed("DryLand", "旱地", "DomainClass", "CultivatedLand", "02", "主要依靠天然降水种植旱生作物的耕地。"),
    _seed("GardenLand", "园地", "DomainClass", "NonCultivatedAgriculturalLand", "02", "集约经营多年生作物的土地。"),
    _seed("ForestLand", "林地", "DomainClass", "NonCultivatedAgriculturalLand", "02", "生长乔木、竹类、灌木等林业植被并按林地管理的土地。"),
    _seed("GrassLand", "草地", "DomainClass", "NonCultivatedAgriculturalLand", "02", "生长草本植物并具有生态或牧业利用功能的土地。", "草原"),
    _seed("AgriculturalFacilityLand", "农业设施用地", "DomainClass", "NonCultivatedAgriculturalLand", "02", "直接服务于农业生产设施的土地；具体归类以适用标准和有效时点为准。", "设施农用地"),
    _seed("ResidentialLand", "居住用地", "DomainClass", "ConstructionLand", "04", "用于城乡居住及相应生活服务设施的建设用地。"),
    _seed("PublicServiceLand", "公共管理与公共服务用地", "DomainClass", "ConstructionLand", "04", "用于机关、教育、文化、体育、医疗和社会福利等公共服务的建设用地。"),
    _seed("CommercialServiceLand", "商业服务业用地", "DomainClass", "ConstructionLand", "04", "用于商业、商务金融、娱乐等服务业的建设用地。"),
    _seed("IndustrialMiningLand", "工矿用地", "DomainClass", "ConstructionLand", "04", "用于工业生产、采矿及其直接配套设施的建设用地。"),
    _seed("StorageLand", "仓储用地", "DomainClass", "ConstructionLand", "04", "用于物资储备、物流仓储设施的建设用地。"),
    _seed("TransportLand", "交通运输用地", "DomainClass", "ConstructionLand", "04", "用于铁路、公路、机场、港口、管道及交通场站的建设用地。"),
    _seed("UtilitiesLand", "公用设施用地", "DomainClass", "ConstructionLand", "04", "用于供水、排水、能源、通信、环卫、消防等公用设施的建设用地。"),
    _seed("GreenOpenSpaceLand", "绿地与开敞空间用地", "DomainClass", "ConstructionLand", "04", "城镇建设范围内承担游憩、防护或公共开放功能的土地。"),
    _seed("SpecialUseLand", "特殊用地", "DomainClass", "ConstructionLand", "04", "用于军事、宗教、文物保护、殡葬等特定用途的建设用地。"),
    _seed("VacantLand", "空闲地", "DomainClass", "UnusedLand", "02", "尚未确定现实利用活动或处于闲置状态的土地。"),
    _seed("SalineAlkaliLand", "盐碱地", "DomainClass", "UnusedLand", "02", "受盐碱作用影响且当前利用受限的土地。"),
    _seed("SandyLand", "沙地", "DomainClass", "UnusedLand", "02", "地表主要由沙质物质覆盖的土地。"),
    _seed("BareLand", "裸土地", "DomainClass", "UnusedLand", "02", "地表土质裸露、植被覆盖稀少的土地。"),
    _seed("BareRockGravelLand", "裸岩石砾地", "DomainClass", "UnusedLand", "02", "地表主要为裸露岩石或砾石的土地。"),
    _seed("WaterResource", "水资源", "DomainClass", "NaturalResource", "02", "地表水、地下水及其可利用或生态价值的资源对象。"),
    _seed("SurfaceWaterBody", "地表水体", "DomainClass", "WaterResource", "01", "在地表具有相对稳定空间范围的水体。"),
    _seed("River", "河流", "DomainClass", "SurfaceWaterBody", "01", "沿天然或人工河道流动的地表水体。"),
    _seed("Lake", "湖泊", "DomainClass", "SurfaceWaterBody", "01", "陆地洼地内相对静止的天然水体。"),
    _seed("Reservoir", "水库", "DomainClass", "SurfaceWaterBody", "01", "由水工程形成并调蓄水量的水体。"),
    _seed("GroundwaterBody", "地下水体", "DomainClass", "WaterResource", "02", "赋存于地下含水介质中的水资源对象。"),
    _seed("ForestResource", "森林资源", "DomainClass", "NaturalResource", "03", "由森林生态系统及其林木、林地等要素构成的资源对象。"),
    _seed("GrasslandResource", "草原资源", "DomainClass", "NaturalResource", "03", "由草原生态系统及其植被、土地等要素构成的资源对象。"),
    _seed("WetlandResource", "湿地资源", "DomainClass", "NaturalResource", "03", "具有显著水文、土壤和生物特征的湿地生态资源对象。"),
    _seed("MineralResource", "矿产资源", "DomainClass", "NaturalResource", "03", "经地质作用形成、具有利用价值的矿物或能源资源对象。"),
    _seed("MineralDeposit", "矿床", "DomainClass", "MineralResource", "03", "具有一定规模、形态和品位的矿产聚集体。"),
    _seed("MarineResource", "海洋资源", "DomainClass", "NaturalResource", "03", "海域、海岛、海岸带及其生物、矿产和空间资源对象。"),
    _seed("SeaArea", "海域", "DomainClass", "MarineResource", "03", "依法确定范围的海洋空间资源对象。"),
    _seed("Island", "海岛", "DomainClass", "MarineResource", "03", "四面环水且高潮时高于水面的自然形成陆地区域。"),
    _seed("AdministrativeUnit", "行政区", "DomainClass", "NaturalResourceEntity", "01", "由法定行政界线确定的空间管理单元。"),
    _seed("PlanningUnit", "规划单元", "DomainClass", "NaturalResourceEntity", "04", "为国土空间规划编制、传导和实施管理划定的空间单元。"),
    _seed("NaturalResourceRegistrationUnit", "自然资源登记单元", "DomainClass", "NaturalResourceEntity", "03", "为自然资源统一确权登记划定的空间单元。"),
    _seed("ControlBoundary", "管控边界", "DomainClass", "NaturalResourceEntity", "05", "承载空间准入、保护或开发约束的边界或范围。"),
    _seed("EcologicalConservationRedline", "生态保护红线", "DomainClass", "ControlBoundary", "05", "在生态空间范围内具有特殊重要生态功能、必须强制性严格保护的区域边界。"),
    _seed("PermanentBasicFarmland", "永久基本农田", "DomainClass", "ControlBoundary", "05", "依法划定并实行特殊保护的耕地范围。"),
    _seed("UrbanDevelopmentBoundary", "城镇开发边界", "DomainClass", "ControlBoundary", "05", "在一定时期内允许城镇开发建设的空间边界。"),

    _seed("NaturalResourceState", "自然资源状态", "StateClass", "NaturalResourceThing", "02", "自然资源对象在一个有效时段内具有的可变化情形。"),
    _seed("LandUseState", "土地利用状态", "StateClass", "NaturalResourceState", "02", "地块在指定有效时段内的土地利用分类状态。"),
    _seed("AgriculturalLandUseState", "农用地利用状态", "StateClass", "LandUseState", "02", "地块在有效时段内被分类为农用地的状态。"),
    _seed("ConstructionLandUseState", "建设用地利用状态", "StateClass", "LandUseState", "02", "地块在有效时段内被分类为建设用地的状态。"),
    _seed("UnusedLandUseState", "未利用地利用状态", "StateClass", "LandUseState", "02", "地块在有效时段内被分类为未利用地的状态。"),
    _seed("CultivatedLandUseState", "耕地利用状态", "StateClass", "AgriculturalLandUseState", "02", "地块在有效时段内被分类为耕地的状态。"),
    _seed("NonCultivatedAgriculturalLandUseState", "非耕农用地利用状态", "StateClass", "AgriculturalLandUseState", "02", "地块在有效时段内被分类为非耕农用地的状态。"),
    _seed("RightState", "权利状态", "StateClass", "NaturalResourceState", "03", "自然资源权利在有效、限制、注销等生命周期阶段的状态。"),
    _seed("QualityState", "质量状态", "StateClass", "NaturalResourceState", "02", "自然资源对象在质量评价时点或时段内的状态。"),

    _seed("NaturalResourceActivity", "自然资源活动", "ProcessClass", "NaturalResourceThing", "02", "随时间发生并可能改变、认知或管理自然资源对象的过程。"),
    _seed("SurveyActivity", "调查活动", "ProcessClass", "NaturalResourceActivity", "02", "获取自然资源位置、范围、属性或权属信息的活动。"),
    _seed("MonitoringActivity", "监测活动", "ProcessClass", "NaturalResourceActivity", "02", "持续或周期性观测自然资源状态及变化的活动。"),
    _seed("LandUseTransition", "土地利用转换", "ProcessClass", "NaturalResourceActivity", "06", "使地块从一个有时效的土地利用状态转移到另一个状态的过程。"),
    _seed("AgriculturalStructureAdjustment", "农业结构调整", "ProcessClass", "LandUseTransition", "06", "在符合法律政策和用途管制要求的前提下，造成耕地与非耕农用地利用状态转换的农业生产结构调整过程。"),
    _seed("ConstructionOccupation", "建设占用", "ProcessClass", "LandUseTransition", "06", "经依法审批，由建设活动占用农用地并形成建设用地利用状态的过程。", "农用地转用"),
    _seed("LandReclamation", "土地复垦", "ProcessClass", "LandUseTransition", "07", "对生产建设损毁或退化土地采取整治措施以恢复可利用状态的过程。"),
    _seed("LandConsolidation", "土地整治", "ProcessClass", "LandUseTransition", "07", "通过工程、生物或管理措施改善土地利用条件和空间格局的过程。"),
    _seed("EcologicalRestoration", "生态修复", "ProcessClass", "NaturalResourceActivity", "05", "修复受损自然生态系统结构、过程和功能的活动。"),
    _seed("LandExpropriation", "土地征收", "ProcessClass", "NaturalResourceActivity", "06", "国家基于公共利益并依照法定程序将集体所有土地征为国有的行政过程。"),
    _seed("LandSupply", "土地供应", "ProcessClass", "NaturalResourceActivity", "07", "依法配置国有建设用地使用权的行政和市场过程。"),
    _seed("UseApproval", "用途审批", "ProcessClass", "NaturalResourceActivity", "06", "对自然资源用途或用途变化进行审查并作出行政决定的过程。"),
    _seed("RightRegistration", "权利登记", "ProcessClass", "NaturalResourceActivity", "03", "将自然资源权利及其变动记载于法定登记簿的过程。"),
    _seed("EnforcementInspection", "执法检查", "ProcessClass", "NaturalResourceActivity", "08", "检查自然资源开发利用行为是否符合法律、规划和管制要求的活动。"),

    _seed("NaturalResourceObservation", "自然资源观测", "ObservationClass", "NaturalResourceThing", "02", "对自然资源对象、状态或过程在指定时空范围内形成的观测结果。"),
    _seed("LandChangeObservation", "土地变化观测", "ObservationClass", "NaturalResourceObservation", "02", "记录地块利用类别、范围或质量变化的观测结果。"),
    _seed("QualityAssessment", "质量评价", "ObservationClass", "NaturalResourceObservation", "02", "依据评价规则形成的自然资源质量判断结果。"),

    _seed("NaturalResourceRight", "自然资源权利", "InformationClass", "NaturalResourceThing", "03", "由法律确认、以自然资源对象为客体并由特定主体享有的权利。"),
    _seed("Ownership", "所有权", "InformationClass", "NaturalResourceRight", "03", "权利人依法对自然资源享有占有、使用、收益和处分的权利。"),
    _seed("Usufruct", "用益物权", "InformationClass", "NaturalResourceRight", "03", "权利人依法对他人所有的自然资源享有占有、使用和收益的权利。"),
    _seed("LandUseRight", "土地使用权", "InformationClass", "Usufruct", "03", "依法对土地占有、使用并取得收益的权利。"),
    _seed("ContractedManagementRight", "土地承包经营权", "InformationClass", "Usufruct", "03", "以家庭承包等方式依法取得的农村土地承包经营权。"),
    _seed("ExplorationRight", "探矿权", "InformationClass", "NaturalResourceRight", "03", "在许可证规定范围和期限内勘查矿产资源的权利。"),
    _seed("MiningRight", "采矿权", "InformationClass", "NaturalResourceRight", "03", "在许可证规定范围和期限内开采矿产资源并取得矿产品的权利。"),
    _seed("SpatialPlan", "国土空间规划", "InformationClass", "NaturalResourceThing", "04", "对一定区域国土空间保护、开发、利用和修复作出的总体安排。"),
    _seed("UseControlRule", "用途管制规则", "InformationClass", "NaturalResourceThing", "06", "规定空间准入、用途许可、禁止或条件要求的规则。"),
    _seed("LegalBasis", "法律政策依据", "InformationClass", "NaturalResourceThing", "06", "支撑管理活动或状态变更合法性的法律、法规、政策或标准依据。"),
    _seed("ApprovalDocument", "审批文件", "InformationClass", "NaturalResourceThing", "06", "由有权机关对申请事项作出的可追溯行政决定载体。"),
    _seed("EvidenceArtifact", "证据材料", "InformationClass", "NaturalResourceThing", "08", "用于证明自然资源事实、过程或行政行为的材料。"),

    _seed("NaturalResourceRole", "自然资源领域角色", "RoleClass", "NaturalResourceThing", "03", "主体在自然资源业务关系中承担的职责或资格。"),
    _seed("RightsHolder", "权利人", "RoleClass", "NaturalResourceRole", "03", "依法享有自然资源权利的主体角色。"),
    _seed("ApprovingAuthority", "审批机关", "RoleClass", "NaturalResourceRole", "06", "依法对自然资源事项作出审批决定的机关角色。"),
    _seed("RegulatoryAuthority", "监管机关", "RoleClass", "NaturalResourceRole", "08", "依法承担自然资源监督管理职责的机关角色。"),
    _seed("DataProvider", "数据提供方", "RoleClass", "NaturalResourceRole", "10", "对自然资源数据来源、交付和质量承担责任的主体角色。"),
)


OBJECT_PROPERTIES = (
    ObjectPropertySeed("hasLandUseState", "具有土地利用状态", "LandParcel", "LandUseState", "some"),
    ObjectPropertySeed("stateOf", "所属地块", "LandUseState", "LandParcel", "some"),
    ObjectPropertySeed("hasSourceState", "源状态", "LandUseTransition", "LandUseState", "some"),
    ObjectPropertySeed("hasTargetState", "目标状态", "LandUseTransition", "LandUseState", "some"),
    ObjectPropertySeed("affectsParcel", "影响地块", "LandUseTransition", "LandParcel", "some"),
    ObjectPropertySeed("supportedBy", "依据", "NaturalResourceActivity", "LegalBasis", None),
    ObjectPropertySeed("authorizedBy", "批准文件", "LandUseTransition", "ApprovalDocument", None),
    ObjectPropertySeed("observes", "观测对象", "NaturalResourceObservation", "NaturalResourceEntity", "some"),
    ObjectPropertySeed("producedBy", "由活动产生", "NaturalResourceObservation", "NaturalResourceActivity", None),
    ObjectPropertySeed("hasRight", "设有权利", "NaturalResourceEntity", "NaturalResourceRight", None),
    ObjectPropertySeed("heldBy", "由权利人持有", "NaturalResourceRight", "RightsHolder", "some"),
    ObjectPropertySeed("appliesTo", "适用于", "UseControlRule", "NaturalResourceEntity", None),
    ObjectPropertySeed("locatedIn", "位于", "NaturalResourceEntity", "AdministrativeUnit", None),
    ObjectPropertySeed("constrainedBy", "受边界约束", "LandParcel", "ControlBoundary", None),
)


DISJOINT_GROUPS = (
    ("AgriculturalLand", "ConstructionLand", "UnusedLand"),
    ("CultivatedLand", "NonCultivatedAgriculturalLand"),
    ("PaddyField", "IrrigatedLand", "DryLand"),
    ("AgriculturalLandUseState", "ConstructionLandUseState", "UnusedLandUseState"),
    ("CultivatedLandUseState", "NonCultivatedAgriculturalLandUseState"),
    ("NaturalResourceEntity", "NaturalResourceActivity", "NaturalResourceState"),
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


def _curated_source() -> SourceRecord:
    payload = {
        "classes": [seed.__dict__ for seed in CLASS_SEEDS],
        "object_properties": [seed.__dict__ for seed in OBJECT_PROPERTIES],
        "disjoint_groups": DISJOINT_GROUPS,
        "transition_rules": TRANSITION_RULES,
    }
    return SourceRecord(
        source_id=CURATED_SOURCE_ID,
        source_kind="curated_domain_ontology",
        title="Natural Resource Domain Ontology v2 curated model",
        locator="package:data_agent.ontology.domain_model",
        source_version="2.0.0",
        sha256=sha256_json(payload),
        metadata={
            "authority": "ADR-140",
            "review_status": "curated_seed_pending_domain-owner-acceptance",
            "modeling_method": "competency-question-driven",
        },
    )


def _curated_concepts() -> list[ConceptRecord]:
    return [
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
                "decision": "ADR-140",
            },
        )
        for seed in CLASS_SEEDS
    ]


def _curated_relations() -> list[RelationRecord]:
    records: list[RelationRecord] = []
    for seed in CLASS_SEEDS:
        if seed.parent:
            records.append(RelationRecord(
                relation_id=f"gda:nr:subclass:{seed.name}:{seed.parent}",
                relation_type="subClassOf",
                source_concept_id=class_id(seed.name),
                target_concept_id=class_id(seed.parent),
                pref_label="属于",
                transitive=True,
                source_id=CURATED_SOURCE_ID,
                provenance={"axiom_type": "rdfs:subClassOf"},
            ))
    for group in DISJOINT_GROUPS:
        for index, left in enumerate(group):
            for right in group[index + 1:]:
                records.append(RelationRecord(
                    relation_id=f"gda:nr:disjoint:{left}:{right}",
                    relation_type="disjointWith",
                    source_concept_id=class_id(left),
                    target_concept_id=class_id(right),
                    pref_label="互斥",
                    symmetric=True,
                    source_id=CURATED_SOURCE_ID,
                    provenance={"axiom_type": "owl:disjointWith"},
                ))
    for prop in OBJECT_PROPERTIES:
        records.append(RelationRecord(
            relation_id=f"gda:nr:object-property:{prop.name}",
            relation_type="objectProperty",
            source_concept_id=class_id(prop.domain),
            target_concept_id=class_id(prop.range),
            pref_label=prop.label,
            source_id=CURATED_SOURCE_ID,
            provenance={
                "property_name": prop.name,
                "restriction": prop.restriction,
            },
        ))
    for process, relation_type, state in TRANSITION_RULES:
        records.append(RelationRecord(
            relation_id=f"gda:nr:transition-rule:{process}:{relation_type}:{state}",
            relation_type=relation_type,
            source_concept_id=class_id(process),
            target_concept_id=class_id(state),
            pref_label="允许源状态" if relation_type == "allowedSource" else "允许目标状态",
            source_id=CURATED_SOURCE_ID,
            provenance={"axiom_type": "governed-transition-rule"},
        ))
    return records


def _transform_source_concepts(
    flat: CompiledOntology,
) -> tuple[list[ConceptRecord], dict[str, str]]:
    kind_map = {
        "Domain": "Domain",
        "FeatureType": "SchemaArtifact",
        "DatasetSchema": "SchemaArtifact",
        "ValueDomain": "ReferenceScheme",
        "ValueDomainMember": "ReferenceConcept",
        "CRS": "CRSReference",
    }
    concepts: list[ConceptRecord] = []
    transformed_kinds: dict[str, str] = {}
    for record in flat.concepts:
        target_kind = kind_map.get(record.kind)
        if not target_kind:
            continue
        transformed_kinds[record.concept_id] = target_kind
        provenance = dict(record.provenance)
        provenance.update({
            "source_modeling_role": record.kind,
            "modeling_role": target_kind,
            "not_a_domain_class": target_kind in {
                "SchemaArtifact", "ReferenceScheme", "ReferenceConcept", "CRSReference",
            },
        })
        concepts.append(record.model_copy(update={
            "kind": target_kind,
            "source_id": (
                CURATED_SOURCE_ID
                if record.source_id == "gda-core-vocabulary"
                else record.source_id
            ),
            "definition": (
                f"数据结构制品：{record.definition}" if target_kind == "SchemaArtifact"
                else record.definition
            ),
            "provenance": provenance,
        }))
    return concepts, transformed_kinds


def _normalize_label(value: str) -> str:
    return "".join(character for character in value.casefold().strip() if character.isalnum())


def _semantic_mappings(concepts: list[ConceptRecord]) -> list[MappingRecord]:
    curated_by_label: dict[str, ConceptRecord] = {}
    for concept in concepts:
        if concept.kind not in {
            "DomainClass", "ProcessClass", "StateClass", "RoleClass",
            "InformationClass", "ObservationClass",
        }:
            continue
        for label in [concept.pref_label, *concept.alt_labels]:
            curated_by_label.setdefault(_normalize_label(label), concept)

    mappings: list[MappingRecord] = []
    for concept in concepts:
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
        mappings.append(MappingRecord(
            mapping_id=f"gda:nr:semantic-mapping:{stable_token(concept.concept_id, target.concept_id)}",
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
            reviewed_by="curated-label-mapping-policy-v2" if status == MappingStatus.CONFIRMED else None,
            reviewed_at=datetime(2026, 8, 4, tzinfo=UTC) if status == MappingStatus.CONFIRMED else None,
        ))
    return mappings


def compile_curated_domain_ontology(flat: CompiledOntology) -> CompiledOntology:
    """Project flat extraction into domain, reference and mapping modules."""
    from .compiler import CompiledOntology

    source_concepts, transformed_kinds = _transform_source_concepts(flat)
    concepts = _curated_concepts() + source_concepts
    concept_ids = {record.concept_id for record in concepts}

    properties = [
        record for record in flat.properties
        if record.owner_concept_id in concept_ids
    ]
    relations = _curated_relations()
    for seed in CLASS_SEEDS:
        domain_concept_id = f"gda:nr:domain:{seed.domain_id}"
        if domain_concept_id not in concept_ids:
            continue
        relations.append(RelationRecord(
            relation_id=f"gda:nr:subject-area-class:{seed.domain_id}:{seed.name}",
            relation_type="hasDomainConcept",
            source_concept_id=domain_concept_id,
            target_concept_id=class_id(seed.name),
            pref_label="包含领域概念",
            source_id=CURATED_SOURCE_ID,
            provenance={"modeling_role": "navigation"},
        ))
    for record in flat.relations:
        if record.source_concept_id not in concept_ids or record.target_concept_id not in concept_ids:
            continue
        if record.relation_type == "hasMember":
            relations.append(record)
        elif record.relation_type == "associatedWith":
            relations.append(record.model_copy(update={
                "relation_type": "schemaAssociation",
                "provenance": dict(record.provenance, modeling_role="schema_metadata"),
            }))
        elif record.relation_type == "usesCRS":
            relations.append(record.model_copy(update={
                "source_id": (
                    CURATED_SOURCE_ID
                    if record.source_id == "gda-core-vocabulary"
                    else record.source_id
                ),
                "provenance": dict(record.provenance, modeling_role="metadata_constraint"),
            }))

    for concept in source_concepts:
        if concept.kind != "SchemaArtifact" or not concept.domain_id:
            continue
        domain_id = f"gda:nr:domain:{concept.domain_id}"
        if domain_id not in concept_ids:
            continue
        relations.append(RelationRecord(
            relation_id=f"gda:nr:subject-area-artifact:{stable_token(concept.concept_id)}",
            relation_type="hasSchemaArtifact",
            source_concept_id=domain_id,
            target_concept_id=concept.concept_id,
            pref_label="包含数据结构制品",
            source_id=concept.source_id,
            provenance={"modeling_role": "data_application_mapping"},
        ))

    mappings: list[MappingRecord] = []
    for record in flat.mappings:
        if record.source_concept_id in concept_ids and record.target_concept_id in concept_ids:
            mappings.append(record.model_copy(update={
                "mapping_type": "schema_correspondence",
                "evidence": dict(record.evidence, semantic_assertion="schema_correspondence"),
            }))
    mappings.extend(_semantic_mappings(concepts))

    sources = [source for source in flat.sources if source.source_id != "gda-core-vocabulary"]
    sources.append(_curated_source())
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
    )
