"""Enterprise Architect XMI parser for domain standard models."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from html import unescape
from pathlib import Path
import re
from typing import Any
import xml.etree.ElementTree as ET


UML_NS = "http://www.omg.org/spec/UML/20161101"
XMI_NS = "http://www.omg.org/spec/XMI/20131001"


PRIMITIVE_TYPE_MAP = {
    "eajava_int": "integer",
    "eajava_long": "integer",
    "eajava_string": "string",
    "eajava_double": "numeric",
    "eajava_boolean": "boolean",
    "int": "integer",
    "long": "integer",
    "string": "string",
    "double": "numeric",
    "boolean": "boolean",
}


@dataclass
class XMIAttribute:
    attr_id: str
    name: str
    name_decoded: str
    type_ref: str | None
    type_name: str | None
    lower: str | None
    upper: str | None
    visibility: str | None


@dataclass
class XMIGeneralization:
    generalization_id: str
    source_class_id: str
    target_class_id: str
    target_class_name: str | None = None


@dataclass
class XMIClass:
    class_id: str
    name: str
    name_decoded: str
    package_path: list[str]
    attributes: list[XMIAttribute] = field(default_factory=list)
    generalizations: list[XMIGeneralization] = field(default_factory=list)
    source: str = ""


@dataclass
class XMIAssociationEnd:
    end_id: str
    role_name: str | None
    role_name_decoded: str | None
    type_ref: str | None
    type_name: str | None
    lower: str | None
    upper: str | None
    visibility: str | None
    aggregation: str | None
    owner_class_id: str | None = None
    owner_class_name: str | None = None


@dataclass
class XMIAssociation:
    association_id: str
    name: str
    name_decoded: str
    ends: list[XMIAssociationEnd] = field(default_factory=list)
    source: str = ""


@dataclass
class XMIParseStats:
    total_packages: int = 0
    total_classes: int = 0
    total_attributes: int = 0
    total_associations: int = 0
    total_generalizations: int = 0


@dataclass
class XMIParseResult:
    module_id: str
    module_name: str
    source_file: str
    top_package_name: str
    classes: list[XMIClass]
    associations: list[XMIAssociation]
    generalizations: list[XMIGeneralization]
    stats: XMIParseStats
    unresolved_refs: list[dict[str, str]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def decode_html_entities(value: str | None) -> str:
    """Decode HTML entities and trim spaces."""
    if value is None:
        return ""
    return unescape(value).strip()


def normalize_primitive_type(type_ref: str | None, type_name: str | None = None) -> str | None:
    """Normalize primitive aliases used by EA into canonical type names."""
    candidates = [type_ref, type_name]
    for item in candidates:
        if not item:
            continue
        normalized_key = item.strip().lower()
        if normalized_key in PRIMITIVE_TYPE_MAP:
            return PRIMITIVE_TYPE_MAP[normalized_key]

    if type_name:
        return decode_html_entities(type_name)
    if type_ref:
        return type_ref
    return None


def is_unknown_eajava_primitive(type_ref: str | None, type_name: str | None = None) -> bool:
    """Return True when an EAJava primitive alias is present but not recognized."""
    for item in (type_ref, type_name):
        if not item:
            continue
        normalized_key = item.strip().lower()
        if normalized_key.startswith("eajava_") and normalized_key not in PRIMITIVE_TYPE_MAP:
            return True
    return False


def infer_module_name(path: Path, top_package_name: str) -> tuple[str, str]:
    """Infer module identifier/name with file name as primary signal."""
    raw_module_name = decode_html_entities(path.stem) or decode_html_entities(top_package_name)
    if not raw_module_name:
        raw_module_name = "unknown_module"
    module_id = re.sub(r"\W+", "_", raw_module_name).strip("_").lower() or "unknown_module"
    return module_id, raw_module_name


def _get_xmi_attr(elem: ET.Element, name: str) -> str | None:
    return elem.get(f"{{{XMI_NS}}}{name}") or elem.get(f"xmi:{name}")


def _get_type_ref(elem: ET.Element) -> tuple[str | None, str | None]:
    type_elem = elem.find("type")
    if type_elem is not None:
        type_ref = _get_xmi_attr(type_elem, "idref") or type_elem.get("type")
        type_name = type_elem.get("name")
        if type_ref or type_name:
            return type_ref, type_name

    direct_type_ref = elem.get("type")
    direct_type_name = elem.get("typeName") or elem.get("type_name")
    if direct_type_ref or direct_type_name:
        return direct_type_ref, direct_type_name

    return None, None


def _get_multiplicity(elem: ET.Element) -> tuple[str | None, str | None]:
    lower_elem = elem.find("lowerValue")
    upper_elem = elem.find("upperValue")
    lower = lower_elem.get("value") if lower_elem is not None else None
    upper = upper_elem.get("value") if upper_elem is not None else None
    return lower, upper


def _parse_owned_attribute(attr_elem: ET.Element) -> XMIAttribute:
    attr_id = _get_xmi_attr(attr_elem, "id") or ""
    raw_name = attr_elem.get("name", "")
    type_ref, type_name = _get_type_ref(attr_elem)
    lower, upper = _get_multiplicity(attr_elem)
    visibility = attr_elem.get("visibility")

    return XMIAttribute(
        attr_id=attr_id,
        name=raw_name,
        name_decoded=decode_html_entities(raw_name),
        type_ref=type_ref,
        type_name=normalize_primitive_type(type_ref=type_ref, type_name=type_name),
        lower=lower,
        upper=upper,
        visibility=visibility,
    )


def _parse_association_end(
    end_elem: ET.Element,
    owner_class_id: str | None = None,
    owner_class_name: str | None = None,
) -> XMIAssociationEnd:
    type_ref, type_name = _get_type_ref(end_elem)
    lower, upper = _get_multiplicity(end_elem)
    role_name = end_elem.get("name")
    return XMIAssociationEnd(
        end_id=_get_xmi_attr(end_elem, "id") or "",
        role_name=role_name,
        role_name_decoded=decode_html_entities(role_name) if role_name else None,
        type_ref=type_ref,
        type_name=normalize_primitive_type(type_ref=type_ref, type_name=type_name),
        lower=lower,
        upper=upper,
        visibility=end_elem.get("visibility"),
        aggregation=end_elem.get("aggregation"),
        owner_class_id=owner_class_id,
        owner_class_name=owner_class_name,
    )


def _is_packaged_type(elem: ET.Element, uml_type: str) -> bool:
    return _get_xmi_attr(elem, "type") == uml_type


def _collect_packages(root: ET.Element) -> list[ET.Element]:
    return [
        elem for elem in root.iter("packagedElement")
        if _is_packaged_type(elem, "uml:Package")
    ]


def _collect_classes(root: ET.Element) -> list[ET.Element]:
    return [
        elem for elem in root.iter("packagedElement")
        if _is_packaged_type(elem, "uml:Class")
    ]


def _collect_associations(root: ET.Element) -> list[ET.Element]:
    return [
        elem for elem in root.iter("packagedElement")
        if _is_packaged_type(elem, "uml:Association")
    ]


def _find_top_package(model_elem: ET.Element) -> str:
    for child in model_elem.findall("packagedElement"):
        if _is_packaged_type(child, "uml:Package"):
            return decode_html_entities(child.get("name", ""))
    return ""


def _parse_class_element(
    elem: ET.Element,
    package_path: list[str],
    source_file: str,
    classes: list[XMIClass],
    generalizations: list[XMIGeneralization],
    association_end_index: dict[str, XMIAssociationEnd],
    association_owner_index: dict[str, list[str]],
):
    class_id = _get_xmi_attr(elem, "id") or ""
    raw_name = elem.get("name", "")
    decoded_name = decode_html_entities(raw_name)
    klass = XMIClass(
        class_id=class_id,
        name=raw_name,
        name_decoded=decoded_name,
        package_path=package_path.copy(),
        source=source_file,
    )

    for attr_elem in elem.findall("ownedAttribute"):
        if _get_xmi_attr(attr_elem, "type") != "uml:Property":
            continue
        association_id = attr_elem.get("association")
        if association_id:
            association_end = _parse_association_end(
                attr_elem,
                owner_class_id=class_id,
                owner_class_name=decoded_name,
            )
            association_end_index[association_end.end_id] = association_end
            association_owner_index.setdefault(association_id, []).append(association_end.end_id)
            continue
        klass.attributes.append(_parse_owned_attribute(attr_elem))

    for gen_elem in elem.findall("generalization"):
        if _get_xmi_attr(gen_elem, "type") != "uml:Generalization":
            continue
        generalization = XMIGeneralization(
            generalization_id=_get_xmi_attr(gen_elem, "id") or "",
            source_class_id=class_id,
            target_class_id=gen_elem.get("general", ""),
        )
        klass.generalizations.append(generalization)
        generalizations.append(generalization)

    classes.append(klass)


def _parse_classes_from_package(
    package_elem: ET.Element,
    package_path: list[str],
    source_file: str,
    classes: list[XMIClass],
    generalizations: list[XMIGeneralization],
    association_end_index: dict[str, XMIAssociationEnd],
    association_owner_index: dict[str, list[str]],
):
    for elem in package_elem.findall("packagedElement"):
        xmi_type = _get_xmi_attr(elem, "type")

        if xmi_type == "uml:Package":
            package_name = decode_html_entities(elem.get("name", ""))
            next_path = package_path + ([package_name] if package_name else [])
            _parse_classes_from_package(
                package_elem=elem,
                package_path=next_path,
                source_file=source_file,
                classes=classes,
                generalizations=generalizations,
                association_end_index=association_end_index,
                association_owner_index=association_owner_index,
            )
            continue

        if xmi_type != "uml:Class":
            continue

        _parse_class_element(
            elem=elem,
            package_path=package_path,
            source_file=source_file,
            classes=classes,
            generalizations=generalizations,
            association_end_index=association_end_index,
            association_owner_index=association_owner_index,
        )


def _parse_association(
    assoc_elem: ET.Element,
    source_file: str,
    association_end_index: dict[str, XMIAssociationEnd],
    association_owner_index: dict[str, list[str]],
    add_unresolved,
) -> XMIAssociation:
    assoc_id = _get_xmi_attr(assoc_elem, "id") or ""
    raw_name = assoc_elem.get("name", "")
    association = XMIAssociation(
        association_id=assoc_id,
        name=raw_name,
        name_decoded=decode_html_entities(raw_name),
        source=source_file,
    )

    end_ids: list[str] = []
    for end_elem in assoc_elem.findall("ownedEnd"):
        if _get_xmi_attr(end_elem, "type") != "uml:Property":
            continue
        association_end = _parse_association_end(end_elem)
        association_end_index[association_end.end_id] = association_end
        end_ids.append(association_end.end_id)

    for member_end in assoc_elem.findall("memberEnd"):
        ref_id = _get_xmi_attr(member_end, "idref")
        if ref_id:
            end_ids.append(ref_id)

    member_end_attr = assoc_elem.get("memberEnd")
    if member_end_attr:
        end_ids.extend(part for part in member_end_attr.split() if part)

    end_ids.extend(association_owner_index.get(assoc_id, []))

    seen: set[str] = set()
    for end_id in end_ids:
        if not end_id or end_id in seen:
            continue
        seen.add(end_id)
        if end_id in association_end_index:
            association.ends.append(association_end_index[end_id])
        else:
            add_unresolved(end_id, "association_end_ref", assoc_id)

    if len(association.ends) < len(seen):
        add_unresolved(
            str(len(seen) - len(association.ends)),
            "association_incomplete",
            assoc_id,
        )

    return association


def parse_xmi_file(path: str | Path) -> XMIParseResult:
    """Parse a local Enterprise Architect XMI/XML file to a stable dataclass structure."""
    source_path = Path(path).expanduser()
    if not source_path.exists():
        raise FileNotFoundError(f"XMI file not found: {source_path}")

    tree = ET.parse(source_path)
    root = tree.getroot()

    model_elem = root.find(f"{{{UML_NS}}}Model")
    if model_elem is None:
        raise ValueError("Invalid XMI: missing uml:Model")

    top_package_name = _find_top_package(model_elem)
    module_id, module_name = infer_module_name(source_path, top_package_name)

    classes: list[XMIClass] = []
    associations: list[XMIAssociation] = []
    generalizations: list[XMIGeneralization] = []
    association_end_index: dict[str, XMIAssociationEnd] = {}
    association_owner_index: dict[str, list[str]] = {}
    unresolved_refs: dict[tuple[str, str, str], dict[str, str]] = {}

    def add_unresolved(ref_id: str, context: str, owner_id: str):
        key = (ref_id, context, owner_id)
        unresolved_refs[key] = {
            "ref_id": ref_id,
            "context": context,
            "owner_id": owner_id,
        }

    for pkg in model_elem.findall("packagedElement"):
        if _is_packaged_type(pkg, "uml:Package"):
            package_name = decode_html_entities(pkg.get("name", ""))
            initial_path = [package_name] if package_name else []
            _parse_classes_from_package(
                package_elem=pkg,
                package_path=initial_path,
                source_file=str(source_path),
                classes=classes,
                generalizations=generalizations,
                association_end_index=association_end_index,
                association_owner_index=association_owner_index,
            )
        elif _is_packaged_type(pkg, "uml:Class"):
            _parse_class_element(
                elem=pkg,
                package_path=[],
                source_file=str(source_path),
                classes=classes,
                generalizations=generalizations,
                association_end_index=association_end_index,
                association_owner_index=association_owner_index,
            )

    for assoc_elem in _collect_associations(model_elem):
        associations.append(
            _parse_association(
                assoc_elem,
                source_file=str(source_path),
                association_end_index=association_end_index,
                association_owner_index=association_owner_index,
                add_unresolved=add_unresolved,
            )
        )

    class_name_index = {klass.class_id: klass.name_decoded for klass in classes}

    for klass in classes:
        for attr in klass.attributes:
            if not attr.type_ref and not attr.type_name:
                add_unresolved(attr.attr_id, "missing_type_ref", klass.class_id)
                continue
            if attr.type_ref in class_name_index:
                attr.type_name = class_name_index[attr.type_ref]
            elif attr.type_ref:
                normalized = normalize_primitive_type(attr.type_ref, attr.type_name)
                attr.type_name = normalized
                if is_unknown_eajava_primitive(attr.type_ref, attr.type_name):
                    add_unresolved(attr.type_ref, "unknown_primitive_type", klass.class_id)
                elif normalized == attr.type_ref:
                    add_unresolved(attr.type_ref, "attribute_type", klass.class_id)

        for gen in klass.generalizations:
            gen.target_class_name = class_name_index.get(gen.target_class_id)
            if not gen.target_class_name and gen.target_class_id:
                add_unresolved(gen.target_class_id, "generalization_target", klass.class_id)

    for assoc in associations:
        for end in assoc.ends:
            if end.owner_class_id and not end.owner_class_name:
                end.owner_class_name = class_name_index.get(end.owner_class_id)
            if not end.type_ref and not end.type_name:
                add_unresolved(end.end_id, "missing_type_ref", assoc.association_id)
                continue
            if end.type_ref in class_name_index:
                end.type_name = class_name_index[end.type_ref]
            elif end.type_ref:
                normalized = normalize_primitive_type(end.type_ref, end.type_name)
                end.type_name = normalized
                if is_unknown_eajava_primitive(end.type_ref, end.type_name):
                    add_unresolved(end.type_ref, "unknown_primitive_type", assoc.association_id)
                elif normalized == end.type_ref:
                    add_unresolved(end.type_ref, "association_end_type", assoc.association_id)

    stats = XMIParseStats(
        total_packages=len(_collect_packages(model_elem)),
        total_classes=len(classes),
        total_attributes=sum(len(klass.attributes) for klass in classes),
        total_associations=len(associations),
        total_generalizations=len(generalizations),
    )

    return XMIParseResult(
        module_id=module_id,
        module_name=module_name,
        source_file=str(source_path),
        top_package_name=top_package_name,
        classes=classes,
        associations=associations,
        generalizations=generalizations,
        stats=stats,
        unresolved_refs=list(unresolved_refs.values()),
    )
