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


def _append_multiplicity(parent: ET.Element, *, nullable: bool) -> None:
    lower = "0" if nullable else "1"
    upper = "1"
    ET.SubElement(parent, "lowerValue", {"value": lower})
    ET.SubElement(parent, "upperValue", {"value": upper})


def export_pdm_to_ea_xmi(
    pdm: dict,
    *,
    model_name: str = "Standards Platform Data Model",
    package_name: str | None = None,
) -> str:
    """Return an EA-compatible UML/XMI XML document."""
    del model_name

    package_name = package_name or "Standards Platform Data Model"

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
    for entity_index, entity in enumerate(entities):
        class_name = entity.get("name_zh") or entity.get("physical_table") or ""
        class_elem = ET.SubElement(
            package,
            "packagedElement",
            {
                f"{{{XMI_NS}}}type": "uml:Class",
                f"{{{XMI_NS}}}id": _stable_id("CLASS", package_name, entity.get("physical_table"), entity_index, class_name),
                "name": class_name,
            },
        )

        attributes = entity.get("attributes", []) or []
        for attr_index, attribute in enumerate(attributes):
            attr_name = attribute.get("name_zh") or attribute.get("physical_column") or ""
            nullable = bool(attribute.get("nullable", True))
            primitive_id = _ea_java_type(attribute.get("physical_type"), bool(attribute.get("is_geometry")))
            prop_elem = ET.SubElement(
                class_elem,
                "ownedAttribute",
                {
                    f"{{{XMI_NS}}}type": "uml:Property",
                    f"{{{XMI_NS}}}id": _stable_id(
                        "ATTR",
                        package_name,
                        entity.get("physical_table"),
                        attribute.get("physical_column"),
                        attr_index,
                        attr_name,
                    ),
                    "name": attr_name,
                    "visibility": "private",
                },
            )
            _append_multiplicity(prop_elem, nullable=nullable)
            ET.SubElement(prop_elem, "type", {f"{{{XMI_NS}}}idref": primitive_id})

    xml = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    return xml.decode("utf-8") + "\n"
