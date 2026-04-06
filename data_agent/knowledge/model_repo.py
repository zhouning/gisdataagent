"""
知识管理层 — 数据模型库

解析 EA Native XMI 格式的自然资源数据模型。
输出结构化的：业务域 → 实体对象 → 字段定义 + 关系。

输入源：自然资源全域数据模型 ZIP（EA 导出的 XMI 文件集合）
格式：UML 2.5 XMI，由 Enterprise Architect 6.5 导出
"""

from __future__ import annotations

import logging
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

# EA XMI 命名空间
_NS = {
    "xmi": "http://www.omg.org/spec/XMI/20131001",
    "uml": "http://www.omg.org/spec/UML/20161101",
}

# EA Java 类型到通用类型的映射
_TYPE_MAP = {
    "EAJava_char": "VARCHAR",
    "EAJava_int": "INTEGER",
    "EAJava_float": "FLOAT",
    "EAJava_double": "DOUBLE",
    "EAJava_date": "DATE",
    "EAJava_boolean": "BOOLEAN",
    "EAJava_long": "BIGINT",
    "EAJava_String": "VARCHAR",
}


@dataclass
class ModelField:
    """数据模型中的字段定义"""

    name: str
    data_type: str = "VARCHAR"
    nullable: bool = True
    xmi_id: str = ""


@dataclass
class ModelGeneralization:
    """泛化（继承）关系"""

    parent_id: str
    parent_name: str = ""  # 解析后回填


@dataclass
class ModelAssociation:
    """关联关系"""

    source_id: str
    target_id: str
    source_name: str = ""  # 解析后回填
    target_name: str = ""  # 解析后回填


@dataclass
class ModelEntity:
    """数据模型中的实体对象（对应 UML Class）"""

    name: str
    xmi_id: str
    fields: list[ModelField] = field(default_factory=list)
    generalizations: list[ModelGeneralization] = field(default_factory=list)


@dataclass
class DomainModel:
    """一个业务域的完整数据模型"""

    domain_name: str
    entities: list[ModelEntity] = field(default_factory=list)
    associations: list[ModelAssociation] = field(default_factory=list)

    def get_entity(self, name: str) -> ModelEntity | None:
        """按名称查找实体"""
        for e in self.entities:
            if e.name == name:
                return e
        return None

    def get_entity_by_id(self, xmi_id: str) -> ModelEntity | None:
        """按 XMI ID 查找实体"""
        for e in self.entities:
            if e.xmi_id == xmi_id:
                return e
        return None

    def summary(self) -> dict:
        """生成摘要信息"""
        return {
            "业务域": self.domain_name,
            "实体数量": len(self.entities),
            "关联数量": len(self.associations),
            "实体列表": [
                {
                    "名称": e.name,
                    "字段数": len(e.fields),
                    "父类": [g.parent_name for g in e.generalizations],
                }
                for e in self.entities
                if e.name  # 排除匿名实体
            ],
        }

    def to_dict(self) -> dict:
        """导出为完整的字典结构（供 AI 推理使用）"""
        return {
            "业务域": self.domain_name,
            "实体对象": [
                {
                    "名称": e.name,
                    "xmi_id": e.xmi_id,
                    "字段": [
                        {
                            "名称": f.name,
                            "类型": f.data_type,
                            "可空": f.nullable,
                        }
                        for f in e.fields
                    ],
                    "继承自": [g.parent_name for g in e.generalizations],
                }
                for e in self.entities
                if e.name
            ],
            "关联关系": [
                {
                    "源实体": a.source_name,
                    "目标实体": a.target_name,
                }
                for a in self.associations
                if a.source_name and a.target_name
            ],
        }


def _resolve_type(type_idref: str) -> str:
    """将 EA Java 类型引用解析为通用类型名"""
    return _TYPE_MAP.get(type_idref, type_idref)


def _parse_class(element: ET.Element) -> ModelEntity:
    """解析一个 UML Class 元素为 ModelEntity"""
    name = element.get("name", "")
    xmi_id = element.get("{http://www.omg.org/spec/XMI/20131001}id", "")

    fields = []
    for attr in element.findall("ownedAttribute", _NS):
        attr_name = attr.get("name", "")
        if not attr_name:
            continue

        type_ref = attr.find("type", _NS)
        type_idref = ""
        if type_ref is not None:
            type_idref = type_ref.get(
                "{http://www.omg.org/spec/XMI/20131001}idref", ""
            )

        lower = attr.find("lowerValue", _NS)
        nullable = True
        if lower is not None and lower.get("value") == "1":
            nullable = False

        fields.append(
            ModelField(
                name=attr_name,
                data_type=_resolve_type(type_idref),
                nullable=nullable,
                xmi_id=attr.get(
                    "{http://www.omg.org/spec/XMI/20131001}id", ""
                ),
            )
        )

    generalizations = []
    for gen in element.findall("generalization", _NS):
        parent_id = gen.get("general", "")
        if parent_id:
            generalizations.append(ModelGeneralization(parent_id=parent_id))

    return ModelEntity(
        name=name,
        xmi_id=xmi_id,
        fields=fields,
        generalizations=generalizations,
    )


def parse_xmi(xml_content: str | bytes) -> DomainModel:
    """
    解析 EA Native XMI 内容，返回 DomainModel。

    Args:
        xml_content: XMI 文件的文本或字节内容

    Returns:
        DomainModel 包含所有实体、字段和关系
    """
    if isinstance(xml_content, str):
        root = ET.fromstring(xml_content)
    else:
        root = ET.fromstring(xml_content)

    model_elem = root.find(".//uml:Model", _NS)
    if model_elem is None:
        raise ValueError("未找到 uml:Model 元素")

    top_pkg = model_elem.find(
        'packagedElement[@xmi:type="uml:Package"]', _NS
    )
    if top_pkg is None:
        raise ValueError("未找到顶层 Package")

    domain_name = top_pkg.get("name", "未命名")

    # 解析所有 Class
    class_elements = top_pkg.findall(
        './/packagedElement[@xmi:type="uml:Class"]', _NS
    )

    id_to_entity: dict[str, ModelEntity] = {}
    entities = []
    for cls_elem in class_elements:
        entity = _parse_class(cls_elem)
        entities.append(entity)
        if entity.xmi_id:
            id_to_entity[entity.xmi_id] = entity

    # 回填泛化关系的父类名称
    for entity in entities:
        for gen in entity.generalizations:
            parent = id_to_entity.get(gen.parent_id)
            if parent:
                gen.parent_name = parent.name

    # 解析 Association
    associations = []
    assoc_elements = top_pkg.findall(
        './/packagedElement[@xmi:type="uml:Association"]', _NS
    )
    for assoc_elem in assoc_elements:
        owned_ends = assoc_elem.findall("ownedEnd", _NS)
        if len(owned_ends) >= 2:
            src_type = owned_ends[0].find("type", _NS)
            dst_type = owned_ends[1].find("type", _NS)
            if src_type is not None and dst_type is not None:
                src_id = src_type.get(
                    "{http://www.omg.org/spec/XMI/20131001}idref", ""
                )
                dst_id = dst_type.get(
                    "{http://www.omg.org/spec/XMI/20131001}idref", ""
                )
                src_entity = id_to_entity.get(src_id)
                dst_entity = id_to_entity.get(dst_id)
                associations.append(
                    ModelAssociation(
                        source_id=src_id,
                        target_id=dst_id,
                        source_name=src_entity.name if src_entity else "",
                        target_name=dst_entity.name if dst_entity else "",
                    )
                )

    logger.info(
        "解析完成: 业务域=%s, 实体=%d, 关联=%d",
        domain_name,
        len(entities),
        len(associations),
    )

    return DomainModel(
        domain_name=domain_name,
        entities=entities,
        associations=associations,
    )


def load_from_zip(
    zip_path: str | Path, xml_filename: str
) -> DomainModel:
    """
    从 ZIP 包中加载指定的 XMI 文件并解析。

    Args:
        zip_path: ZIP 文件路径（如 D:/自然资源全域数据模型.zip）
        xml_filename: ZIP 内的 XML 文件名（如 自然资源全域数据模型/02统一调查监测.xml）

    Returns:
        DomainModel
    """
    zip_path = Path(zip_path)
    if not zip_path.exists():
        raise FileNotFoundError(f"ZIP 文件不存在: {zip_path}")

    with zipfile.ZipFile(zip_path, "r") as z:
        if xml_filename not in z.namelist():
            raise FileNotFoundError(
                f"ZIP 中未找到 {xml_filename}，可用文件: {z.namelist()}"
            )
        content = z.read(xml_filename)

    return parse_xmi(content)


def load_survey_model(
    zip_path: str | Path = r"D:\自然资源全域数据模型.zip",
) -> DomainModel:
    """
    加载三调（统一调查监测）数据模型的便捷方法。

    Returns:
        三调业务域的 DomainModel
    """
    return load_from_zip(
        zip_path, "自然资源全域数据模型/02统一调查监测.xml"
    )
