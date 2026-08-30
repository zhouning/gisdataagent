"""Pure EA-compatible XMI export for Standards Platform PDM snapshots."""
from __future__ import annotations

from hashlib import sha1
import re
import xml.etree.ElementTree as ET


UML_NS = "http://www.omg.org/spec/UML/20161101"
XMI_NS = "http://www.omg.org/spec/XMI/20131001"


ET.register_namespace("uml", UML_NS)
ET.register_namespace("xmi", XMI_NS)


def _stable_id(prefix: str, *parts: object) -> str:
    digest = sha1("|".join("" if part is None else str(part) for part in parts).encode("utf-8")).hexdigest().upper()
    return f"{prefix}_{digest[:16]}"


def _class_id(package_name: str, entity: dict, entity_index: int) -> str:
    physical_table = entity.get("physical_table")
    if physical_table:
        return _stable_id("CLASS", package_name, physical_table)
    class_name = entity.get("name_zh") or entity.get("name_en") or ""
    return _stable_id("CLASS", package_name, class_name, entity_index)


def _attr_id(package_name: str, entity: dict, attribute: dict, attr_index: int) -> str:
    physical_table = entity.get("physical_table")
    physical_column = attribute.get("physical_column")
    if physical_table and physical_column:
        return _stable_id("ATTR", package_name, physical_table, physical_column)
    attr_name = attribute.get("name_zh") or attribute.get("name_en") or ""
    return _stable_id("ATTR", package_name, physical_table or "", attr_name, attr_index)


def _ea_java_type(physical_type: str | None, is_geometry: bool) -> str:
    if is_geometry:
        return "EAJava_String"

    normalized = (physical_type or "").upper()
    if "GEOMETRY" in normalized:
        return "EAJava_String"
    if any(token in normalized for token in ("NUMERIC", "DECIMAL", "DOUBLE", "FLOAT", "REAL")):
        return "EAJava_double"
    if re.search(r"(^|[^A-Z0-9])(?:BIGINT|INTEGER|SMALLINT|INT)(?=$|[^A-Z0-9])", normalized):
        return "EAJava_long"
    if "BOOLEAN" in normalized or "BOOL" in normalized:
        return "EAJava_boolean"
    return "EAJava_String"


def _append_multiplicity(parent: ET.Element, *, attr_id: str, nullable: bool) -> None:
    lower = "0" if nullable else "1"
    upper = "1"
    ET.SubElement(
        parent,
        "lowerValue",
        {
            f"{{{XMI_NS}}}type": "uml:LiteralInteger",
            f"{{{XMI_NS}}}id": _stable_id("LOWER", attr_id),
            "value": lower,
        },
    )
    ET.SubElement(
        parent,
        "upperValue",
        {
            f"{{{XMI_NS}}}type": "uml:LiteralUnlimitedNatural",
            f"{{{XMI_NS}}}id": _stable_id("UPPER", attr_id),
            "value": upper,
        },
    )


def _append_explicit_multiplicity(
    parent: ET.Element,
    *,
    end_id: str,
    lower: str,
    upper: str,
) -> None:
    ET.SubElement(
        parent,
        "lowerValue",
        {
            f"{{{XMI_NS}}}type": "uml:LiteralInteger",
            f"{{{XMI_NS}}}id": _stable_id("LOWER", end_id),
            "value": lower,
        },
    )
    ET.SubElement(
        parent,
        "upperValue",
        {
            f"{{{XMI_NS}}}type": "uml:LiteralUnlimitedNatural",
            f"{{{XMI_NS}}}id": _stable_id("UPPER", end_id),
            "value": upper,
        },
    )


def _cardinality_end(token: object) -> tuple[str, str]:
    normalized = str(token or "").strip().upper()
    if normalized in {"N", "M", "*", "0..*", "1..*"}:
        return ("1", "*") if normalized == "1..*" else ("0", "*")
    if normalized in {"0..1", "?"}:
        return "0", "1"
    return "1", "1"


def _relation_end_cardinalities(cardinality: object) -> tuple[tuple[str, str], tuple[str, str]]:
    parts = [part.strip() for part in str(cardinality or "").split(":")]
    if len(parts) != 2:
        return ("0", "*"), ("1", "1")
    return _cardinality_end(parts[0]), _cardinality_end(parts[1])


def _entity_reference(entity: dict) -> list[str]:
    return [
        str(value)
        for value in (
            entity.get("id"),
            entity.get("physical_table"),
            entity.get("table"),
            entity.get("name_en"),
            entity.get("name_zh"),
        )
        if value
    ]


def export_pdm_to_ea_xmi(
    pdm: dict,
    *,
    model_name: str = "Standards Platform Data Model",
    package_name: str | None = None,
    group_by_domain: bool = False,
    domain_labels: dict[str, str] | None = None,
) -> str:
    """Return an EA-compatible UML/XMI XML document."""
    package_name = package_name or model_name or "Standards Platform Data Model"
    domain_labels = domain_labels or {}

    root = ET.Element(f"{{{XMI_NS}}}XMI")
    model = ET.SubElement(
        root,
        f"{{{UML_NS}}}Model",
        {
            f"{{{XMI_NS}}}type": "uml:Model",
            f"{{{XMI_NS}}}id": _stable_id("MODEL", "EA_Model", package_name),
            "name": "EA_Model",
        },
    )
    package = ET.SubElement(
        model,
        "packagedElement",
        {
            f"{{{XMI_NS}}}type": "uml:Package",
            f"{{{XMI_NS}}}id": _stable_id("PACKAGE", package_name),
            "name": package_name,
        },
    )

    entities = pdm.get("entities", []) or []
    domain_packages: dict[str, ET.Element] = {}
    if group_by_domain:
        for entity in entities:
            domain = str(entity.get("domain") or "").strip()
            if not domain or domain in domain_packages:
                continue
            label = domain_labels.get(domain) or domain
            display_name = label if label == domain else f"{label} ({domain})"
            domain_packages[domain] = ET.SubElement(
                package,
                "packagedElement",
                {
                    f"{{{XMI_NS}}}type": "uml:Package",
                    f"{{{XMI_NS}}}id": _stable_id("PACKAGE_DOMAIN", package_name, domain),
                    "name": display_name,
                },
            )

    class_ids: dict[str, str] = {}
    for entity_index, entity in enumerate(entities):
        class_name = entity.get("name_zh") or entity.get("physical_table") or ""
        class_id = _class_id(package_name, entity, entity_index)
        for reference in _entity_reference(entity):
            class_ids.setdefault(reference, class_id)
        domain = str(entity.get("domain") or "").strip()
        class_parent = domain_packages.get(domain, package)
        class_elem = ET.SubElement(
            class_parent,
            "packagedElement",
            {
                f"{{{XMI_NS}}}type": "uml:Class",
                f"{{{XMI_NS}}}id": class_id,
                "name": class_name,
            },
        )

        attributes = entity.get("attributes", []) or []
        for attr_index, attribute in enumerate(attributes):
            attr_name = attribute.get("name_zh") or attribute.get("physical_column") or ""
            nullable = bool(attribute.get("nullable", True))
            primitive_id = _ea_java_type(attribute.get("physical_type"), bool(attribute.get("is_geometry")))
            attr_id = _attr_id(package_name, entity, attribute, attr_index)
            prop_elem = ET.SubElement(
                class_elem,
                "ownedAttribute",
                {
                    f"{{{XMI_NS}}}type": "uml:Property",
                    f"{{{XMI_NS}}}id": attr_id,
                    "name": attr_name,
                    "visibility": "private",
                },
            )
            _append_multiplicity(prop_elem, attr_id=attr_id, nullable=nullable)
            ET.SubElement(prop_elem, "type", {f"{{{XMI_NS}}}idref": primitive_id})

    for relation in pdm.get("relationships", []) or []:
        source_ref = str(relation.get("source") or "")
        target_ref = str(relation.get("target") or "")
        source_class_id = class_ids.get(source_ref)
        target_class_id = class_ids.get(target_ref)
        if not source_class_id or not target_class_id:
            continue

        relation_name = str(
            relation.get("name")
            or relation.get("source_field")
            or relation.get("method")
            or relation.get("type")
            or f"{source_ref} to {target_ref}"
        )
        association_id = _stable_id(
            "ASSOC",
            package_name,
            source_ref,
            target_ref,
            relation.get("source_field"),
            relation.get("type"),
            relation.get("method"),
            relation.get("cardinality"),
        )
        source_end_id = _stable_id("END_SOURCE", association_id)
        target_end_id = _stable_id("END_TARGET", association_id)
        source_cardinality, target_cardinality = _relation_end_cardinalities(
            relation.get("cardinality")
        )
        association = ET.SubElement(
            package,
            "packagedElement",
            {
                f"{{{XMI_NS}}}type": "uml:Association",
                f"{{{XMI_NS}}}id": association_id,
                "name": relation_name,
            },
        )
        source_end = ET.SubElement(
            association,
            "ownedEnd",
            {
                f"{{{XMI_NS}}}type": "uml:Property",
                f"{{{XMI_NS}}}id": source_end_id,
                "name": source_ref.rsplit(".", 1)[-1],
                "type": source_class_id,
                "association": association_id,
                "visibility": "public",
            },
        )
        _append_explicit_multiplicity(
            source_end,
            end_id=source_end_id,
            lower=source_cardinality[0],
            upper=source_cardinality[1],
        )
        target_end = ET.SubElement(
            association,
            "ownedEnd",
            {
                f"{{{XMI_NS}}}type": "uml:Property",
                f"{{{XMI_NS}}}id": target_end_id,
                "name": target_ref.rsplit(".", 1)[-1],
                "type": target_class_id,
                "association": association_id,
                "visibility": "public",
            },
        )
        _append_explicit_multiplicity(
            target_end,
            end_id=target_end_id,
            lower=target_cardinality[0],
            upper=target_cardinality[1],
        )
        ET.SubElement(association, "memberEnd", {f"{{{XMI_NS}}}idref": source_end_id})
        ET.SubElement(association, "memberEnd", {f"{{{XMI_NS}}}idref": target_end_id})

    xml = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    return xml.decode("utf-8") + "\n"
