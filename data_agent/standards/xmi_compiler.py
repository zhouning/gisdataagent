"""XMI corpus compiler for generating normalized artifacts and indexes.

This compiler consumes the real XMI parser contract from
``data_agent.standards.xmi_parser.parse_xmi_file`` and emits:
- per-file normalized JSON
- corpus-level YAML indexes
- lightweight KG node/edge JSON
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml


REQUIRED_MODULE_ALIASES = {
    "统一规划": "统一空间规划",
    "执法督察": "督察执法",
    "开发利用": "统一资源利用",
}

CANDIDATE_MODULE_ALIASES = {
    "底线安全": "统一灾害防治",
}


def _parse_xmi_file(path: str) -> Any:
    """Proxy parser entry to keep import lazy and patch-friendly in tests."""
    from data_agent.standards.xmi_parser import parse_xmi_file

    return parse_xmi_file(path)


def _safe_stem(path: Path) -> str:
    return path.stem.replace(" ", "_")


def _stable_suffix_from_source(source_key: str) -> str:
    digest = hashlib.sha1(source_key.encode("utf-8")).hexdigest()
    return digest[:8]


def _compose_unique_module_id(module_id_raw: str, source_key: str) -> str:
    return f"{module_id_raw}__{_stable_suffix_from_source(source_key)}"


def _coerce_mapping(value: Any) -> dict[str, Any]:
    """Coerce parser output into a plain mapping.

    Real parser returns ``XMIParseResult`` dataclass with ``to_dict()``.
    Tests may still patch plain dicts.
    """
    if hasattr(value, "to_dict") and callable(value.to_dict):
        result = value.to_dict()
        if isinstance(result, dict):
            return result
    if isinstance(value, dict):
        return value
    raise TypeError(f"Unsupported parsed XMI result type: {type(value)!r}")


def _ensure_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _ensure_package_path(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value]
    if isinstance(value, str) and value:
        return [value]
    return []


def _raw_class_id(module_id_raw: str, class_obj: dict[str, Any], index: int) -> str:
    cid = class_obj.get("class_id") or class_obj.get("id") or class_obj.get("xmi_id")
    if cid:
        return str(cid)
    name = class_obj.get("name_decoded") or class_obj.get("name") or "class"
    return f"{module_id_raw}::local_class::{name}::{index}"


def _global_class_id(module_id: str, class_id_raw: str) -> str:
    return f"{module_id}::class::{class_id_raw}"


def _raw_attribute_id(class_id_raw: str, attr_obj: dict[str, Any], index: int) -> str:
    aid = attr_obj.get("attr_id") or attr_obj.get("attribute_id") or attr_obj.get("id") or attr_obj.get("xmi_id")
    if aid:
        return str(aid)
    name = attr_obj.get("name_decoded") or attr_obj.get("name") or "attr"
    return f"{class_id_raw}::local_attr::{name}::{index}"


def _global_attribute_id(global_class_id: str, attribute_id_raw: str) -> str:
    return f"{global_class_id}::attr::{attribute_id_raw}"


def _association_id(module_id: str, assoc_obj: dict[str, Any], index: int) -> str:
    aid = assoc_obj.get("association_id") or assoc_obj.get("id")
    if aid:
        return str(aid)
    name = assoc_obj.get("name_decoded") or assoc_obj.get("name") or "assoc"
    return f"assoc::{module_id}::{name}::{index}"


def _generalization_id(source_class_id_raw: str, gen_obj: dict[str, Any], index: int) -> str:
    gid = gen_obj.get("generalization_id") or gen_obj.get("id")
    if gid:
        return str(gid)
    target_class_id = gen_obj.get("target_class_id") or gen_obj.get("general") or "target"
    source_token = source_class_id_raw or "source"
    return f"gen::{source_token}::{target_class_id}::{index}"


def _normalize_generalization(
    module_id: str,
    source_class_id_raw: str,
    gen_obj: dict[str, Any],
    index: int,
    class_id_map: dict[str, str],
) -> dict[str, Any]:
    target_class_id_raw = str(gen_obj.get("target_class_id") or gen_obj.get("general") or "")
    return {
        "generalization_id": _generalization_id(source_class_id_raw, gen_obj, index),
        "source_class_id": class_id_map.get(source_class_id_raw) or _global_class_id(module_id, source_class_id_raw),
        "source_class_id_raw": source_class_id_raw,
        "target_class_id": class_id_map.get(target_class_id_raw),
        "target_class_id_raw": target_class_id_raw,
        "target_class_name": gen_obj.get("target_class_name"),
    }


def _normalize_attribute(
    global_class_id: str,
    class_id_map: dict[str, str],
    attr_obj: dict[str, Any],
    class_id_raw: str,
    index: int,
) -> dict[str, Any]:
    attribute_id_raw = _raw_attribute_id(class_id_raw, attr_obj, index)
    type_ref_raw = attr_obj.get("type_ref")
    return {
        "attribute_id": _global_attribute_id(global_class_id, attribute_id_raw),
        "attribute_id_raw": attribute_id_raw,
        "attribute_name": attr_obj.get("name_decoded") or attr_obj.get("name") or "",
        "attribute_raw_name": attr_obj.get("name") or "",
        "attribute_type": attr_obj.get("type_name") or type_ref_raw or "",
        "type_ref": type_ref_raw,
        "type_global_ref": class_id_map.get(str(type_ref_raw)) if type_ref_raw is not None else None,
        "lower": attr_obj.get("lower"),
        "upper": attr_obj.get("upper"),
        "visibility": attr_obj.get("visibility"),
    }


def _normalize_association_end(
    class_id_map: dict[str, str],
    end_obj: dict[str, Any],
    index: int,
) -> dict[str, Any]:
    end_id = end_obj.get("end_id") or end_obj.get("id") or f"end_{index}"
    type_ref_raw = end_obj.get("type_ref")
    owner_class_id_raw = end_obj.get("owner_class_id")
    return {
        "end_id": str(end_id),
        "role_name": end_obj.get("role_name"),
        "role_name_decoded": end_obj.get("role_name_decoded") or end_obj.get("role_name"),
        "type_ref": type_ref_raw,
        "type_global_ref": class_id_map.get(str(type_ref_raw)) if type_ref_raw is not None else None,
        "type_name": end_obj.get("type_name"),
        "owner_class_id": class_id_map.get(str(owner_class_id_raw)) if owner_class_id_raw is not None else None,
        "owner_class_id_raw": owner_class_id_raw,
        "owner_class_name": end_obj.get("owner_class_name"),
        "lower": end_obj.get("lower"),
        "upper": end_obj.get("upper"),
        "visibility": end_obj.get("visibility"),
        "aggregation": end_obj.get("aggregation"),
    }


def _normalize_class(
    module_id: str,
    module_id_raw: str,
    class_obj: dict[str, Any],
    index: int,
    class_id_map: dict[str, str],
    inherited_targets_by_class: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    class_id_raw = _raw_class_id(module_id_raw, class_obj, index)
    global_class_id = class_id_map[class_id_raw]
    attrs_raw = _ensure_list(class_obj.get("attributes"))
    class_generalizations_raw = _ensure_list(class_obj.get("generalizations"))

    normalized_attrs = [
        _normalize_attribute(global_class_id, class_id_map, attr, class_id_raw, i)
        for i, attr in enumerate(attrs_raw)
        if isinstance(attr, dict)
    ]

    normalized_generalizations = [
        _normalize_generalization(module_id, class_id_raw, gen, i, class_id_map)
        for i, gen in enumerate(class_generalizations_raw)
        if isinstance(gen, dict)
    ]

    if not normalized_generalizations:
        normalized_generalizations = inherited_targets_by_class.get(class_id_raw, [])

    super_class_ids = [
        gen["target_class_id"]
        for gen in normalized_generalizations
        if gen.get("target_class_id")
    ]
    super_class_ids_raw = [
        gen["target_class_id_raw"]
        for gen in normalized_generalizations
        if gen.get("target_class_id_raw")
    ]

    return {
        "class_id": global_class_id,
        "class_id_raw": class_id_raw,
        "class_name": class_obj.get("name_decoded") or class_obj.get("name") or "",
        "class_raw_name": class_obj.get("name") or "",
        "package_path": _ensure_package_path(class_obj.get("package_path")),
        "source": class_obj.get("source") or "",
        "attributes": normalized_attrs,
        "generalizations": normalized_generalizations,
        "super_class_ids": super_class_ids,
        "super_class_ids_raw": super_class_ids_raw,
        "super_class_id": super_class_ids[0] if super_class_ids else None,
        "super_class_id_raw": super_class_ids_raw[0] if super_class_ids_raw else None,
    }


def _normalize_association(
    module_id: str,
    assoc_obj: dict[str, Any],
    index: int,
    class_id_map: dict[str, str],
) -> dict[str, Any]:
    ends_raw = _ensure_list(assoc_obj.get("ends"))
    normalized_ends = [
        _normalize_association_end(class_id_map, end, i)
        for i, end in enumerate(ends_raw)
        if isinstance(end, dict)
    ]
    return {
        "association_id": _association_id(module_id, assoc_obj, index),
        "association_name": assoc_obj.get("name_decoded") or assoc_obj.get("name") or "",
        "association_raw_name": assoc_obj.get("name") or "",
        "source": assoc_obj.get("source") or "",
        "ends": normalized_ends,
    }


def normalize_parsed_xmi(
    parsed: Any,
    source_file: str,
    module_id_override: str | None = None,
    source_file_override: str | None = None,
) -> dict[str, Any]:
    """Convert real parser output into a stable normalized structure."""
    parsed_map = _coerce_mapping(parsed)
    source_path = Path(source_file)

    module_id_raw = str(parsed_map.get("module_id") or f"module::{_safe_stem(source_path)}")
    module_id = str(module_id_override or module_id_raw)
    module_name = str(parsed_map.get("module_name") or parsed_map.get("top_package_name") or source_path.stem)
    top_package_name = str(parsed_map.get("top_package_name") or "")

    classes_raw = _ensure_list(parsed_map.get("classes"))
    associations_raw = _ensure_list(parsed_map.get("associations"))
    top_generalizations_raw = _ensure_list(parsed_map.get("generalizations"))
    unresolved_refs = _ensure_list(parsed_map.get("unresolved_refs"))

    class_id_map: dict[str, str] = {}
    for i, item in enumerate(classes_raw):
        if not isinstance(item, dict):
            continue
        class_id_raw = _raw_class_id(module_id_raw, item, i)
        class_id_map[class_id_raw] = _global_class_id(module_id, class_id_raw)

    inherited_targets_by_class: dict[str, list[dict[str, Any]]] = {}
    normalized_top_generalizations: list[dict[str, Any]] = []
    for i, gen in enumerate(top_generalizations_raw):
        if not isinstance(gen, dict):
            continue
        source_class_id_raw = str(gen.get("source_class_id") or "")
        normalized = _normalize_generalization(
            module_id,
            source_class_id_raw,
            gen,
            i,
            class_id_map,
        )
        normalized_top_generalizations.append(normalized)
        if source_class_id_raw:
            inherited_targets_by_class.setdefault(source_class_id_raw, []).append(normalized)

    normalized_classes: list[dict[str, Any]] = []
    for i, item in enumerate(classes_raw):
        if not isinstance(item, dict):
            continue
        normalized_classes.append(
            _normalize_class(module_id, module_id_raw, item, i, class_id_map, inherited_targets_by_class)
        )

    normalized_associations: list[dict[str, Any]] = []
    for i, assoc in enumerate(associations_raw):
        if not isinstance(assoc, dict):
            continue
        normalized_associations.append(
            _normalize_association(module_id, assoc, i, class_id_map)
        )

    return {
        "module_id": module_id,
        "module_id_raw": module_id_raw,
        "module_name": module_name,
        "source_file": str(source_file_override or parsed_map.get("source_file") or source_path.name),
        "top_package_name": top_package_name,
        "classes": normalized_classes,
        "associations": normalized_associations,
        "generalizations": normalized_top_generalizations,
        "class_count": len(normalized_classes),
        "association_count": len(normalized_associations),
        "generalization_count": len(normalized_top_generalizations),
        "unresolved_ref_count": len(unresolved_refs),
        "unresolved_refs": unresolved_refs,
        "stats": parsed_map.get("stats") if isinstance(parsed_map.get("stats"), dict) else {},
    }


def _build_module_aliases() -> dict[str, Any]:
    return {
        "mappings": [
            {"left": k, "right": v, "type": "equivalent"}
            for k, v in REQUIRED_MODULE_ALIASES.items()
        ],
        "candidate_mappings": [
            {"left": k, "right": v, "type": "candidate"}
            for k, v in CANDIDATE_MODULE_ALIASES.items()
        ],
    }


def _build_global_index(
    normalized_docs: list[dict[str, Any]],
    source_root: str,
) -> dict[str, Any]:
    modules: list[dict[str, Any]] = []
    class_index: dict[str, dict[str, Any]] = {}
    unresolved_refs: list[dict[str, Any]] = []

    total_class_count = 0
    total_association_count = 0
    total_unresolved_ref_count = 0

    for doc in normalized_docs:
        module = {
            "module_id": doc["module_id"],
            "module_id_raw": doc.get("module_id_raw"),
            "module_name": doc["module_name"],
            "source_file": doc["source_file"],
            "top_package_name": doc["top_package_name"],
            "class_count": doc["class_count"],
            "association_count": doc["association_count"],
            "unresolved_ref_count": doc.get("unresolved_ref_count", 0),
        }
        modules.append(module)

        total_class_count += doc["class_count"]
        total_association_count += doc["association_count"]
        total_unresolved_ref_count += doc.get("unresolved_ref_count", 0)

        for unresolved in doc.get("unresolved_refs", []):
            if not isinstance(unresolved, dict):
                continue
            unresolved_refs.append(
                {
                    **unresolved,
                    "module_id": doc["module_id"],
                    "module_id_raw": doc.get("module_id_raw"),
                    "module_name": doc["module_name"],
                    "source_file": doc["source_file"],
                }
            )

        for clazz in doc["classes"]:
            class_index[clazz["class_id"]] = {
                "class_id_raw": clazz["class_id_raw"],
                "module_id": doc["module_id"],
                "module_id_raw": doc.get("module_id_raw"),
                "module_name": doc["module_name"],
                "class_name": clazz["class_name"],
                "package_path": clazz["package_path"],
                "source_file": doc["source_file"],
            }

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_root": source_root,
        "module_count": len(normalized_docs),
        "class_count": total_class_count,
        "association_count": total_association_count,
        "unresolved_ref_count": total_unresolved_ref_count,
        "unresolved_refs": unresolved_refs,
        "modules": modules,
        "class_index": class_index,
    }


def _build_kg(normalized_docs: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    nodes: list[dict[str, Any]] = []
    edges: list[dict[str, Any]] = []

    for doc in normalized_docs:
        module_id = doc["module_id"]
        nodes.append(
            {
                "id": module_id,
                "id_raw": doc.get("module_id_raw"),
                "type": "module",
                "name": doc["module_name"],
                "source_file": doc["source_file"],
                "unresolved_ref_count": doc.get("unresolved_ref_count", 0),
            }
        )

        for clazz in doc["classes"]:
            class_id = clazz["class_id"]
            nodes.append(
                {
                    "id": class_id,
                    "id_raw": clazz["class_id_raw"],
                    "type": "class",
                    "name": clazz["class_name"],
                    "module_id": module_id,
                    "package_path": clazz["package_path"],
                    "source_file": doc["source_file"],
                }
            )
            edges.append(
                {
                    "source": class_id,
                    "target": module_id,
                    "type": "belongs_to_module",
                }
            )

            for attr in clazz["attributes"]:
                attr_id = attr["attribute_id"]
                nodes.append(
                    {
                        "id": attr_id,
                        "id_raw": attr["attribute_id_raw"],
                        "type": "attribute",
                        "name": attr["attribute_name"],
                        "class_id": class_id,
                        "module_id": module_id,
                        "attribute_type": attr["attribute_type"],
                        "source_file": doc["source_file"],
                    }
                )
                edges.append(
                    {
                        "source": class_id,
                        "target": attr_id,
                        "type": "has_attribute",
                    }
                )

        if doc.get("unresolved_ref_count", 0):
            for unresolved in doc.get("unresolved_refs", []):
                if not isinstance(unresolved, dict):
                    continue
                edges.append(
                    {
                        "source": module_id,
                        "target": unresolved.get("ref_id") or "",
                        "type": "has_unresolved_ref",
                        "context": unresolved.get("context"),
                        "owner_id": unresolved.get("owner_id"),
                        "source_file": doc["source_file"],
                    }
                )

        for gen in doc.get("generalizations", []):
            source = gen.get("source_class_id")
            target = gen.get("target_class_id")
            if source and target:
                edges.append(
                    {
                        "source": source,
                        "target": target,
                        "type": "inherits_from",
                        "generalization_id": gen.get("generalization_id"),
                        "source_class_id_raw": gen.get("source_class_id_raw"),
                        "target_class_id_raw": gen.get("target_class_id_raw"),
                        "target_class_name": gen.get("target_class_name"),
                    }
                )

        for assoc in doc["associations"]:
            ends = [end for end in assoc.get("ends", []) if isinstance(end, dict)]
            if len(ends) == 2:
                source = ends[0].get("type_global_ref")
                target = ends[1].get("type_global_ref")
                if source and target:
                    edges.append(
                        {
                            "source": source,
                            "target": target,
                            "type": "associates_with",
                            "association_id": assoc.get("association_id"),
                            "association_name": assoc.get("association_name"),
                            "source_class_id_raw": ends[0].get("type_ref"),
                            "target_class_id_raw": ends[1].get("type_ref"),
                        }
                    )

    return nodes, edges


def _normalized_output_path(normalized_dir: Path, file_path: Path, source_key: str) -> Path:
    return normalized_dir / f"{_safe_stem(file_path)}__{_stable_suffix_from_source(source_key)}.json"


def compile_xmi_corpus(
    source_dir: str | Path,
    output_dir: str | Path,
    *,
    source_glob: str = "*.xml",
) -> dict[str, Any]:
    """Compile an XMI/XML corpus into normalized artifacts and indexes."""
    source_root = Path(source_dir)
    out_root = Path(output_dir)

    normalized_dir = out_root / "xmi_normalized"
    indexes_dir = out_root / "indexes"
    kg_dir = out_root / "kg"

    normalized_dir.mkdir(parents=True, exist_ok=True)
    indexes_dir.mkdir(parents=True, exist_ok=True)
    kg_dir.mkdir(parents=True, exist_ok=True)

    files = sorted(p for p in source_root.glob(source_glob) if p.is_file())

    normalized_docs: list[dict[str, Any]] = []

    for file_path in files:
        parsed = _parse_xmi_file(str(file_path))
        parsed_map = _coerce_mapping(parsed)
        source_key = file_path.relative_to(source_root).as_posix()
        module_id_raw = str(parsed_map.get("module_id") or f"module::{_safe_stem(file_path)}")
        module_id = _compose_unique_module_id(module_id_raw, source_key)
        normalized = normalize_parsed_xmi(
            parsed_map,
            str(file_path),
            module_id_override=module_id,
            source_file_override=source_key,
        )
        normalized_docs.append(normalized)

        output_path = _normalized_output_path(normalized_dir, file_path, source_key)
        with output_path.open("w", encoding="utf-8") as f:
            json.dump(normalized, f, ensure_ascii=False, indent=2)

    global_index = _build_global_index(normalized_docs, str(source_root.resolve()))
    aliases = _build_module_aliases()
    kg_nodes, kg_edges = _build_kg(normalized_docs)

    with (indexes_dir / "xmi_global_index.yaml").open("w", encoding="utf-8") as f:
        yaml.safe_dump(global_index, f, allow_unicode=True, sort_keys=False)

    with (indexes_dir / "module_aliases.yaml").open("w", encoding="utf-8") as f:
        yaml.safe_dump(aliases, f, allow_unicode=True, sort_keys=False)

    with (kg_dir / "domain_model_nodes.json").open("w", encoding="utf-8") as f:
        json.dump(kg_nodes, f, ensure_ascii=False, indent=2)

    with (kg_dir / "domain_model_edges.json").open("w", encoding="utf-8") as f:
        json.dump(kg_edges, f, ensure_ascii=False, indent=2)

    return {
        "source_root": str(source_root.resolve()),
        "output_root": str(out_root.resolve()),
        "file_count": len(files),
        "module_count": global_index["module_count"],
        "class_count": global_index["class_count"],
        "association_count": global_index["association_count"],
    }


__all__ = [
    "compile_xmi_corpus",
    "normalize_parsed_xmi",
]
