"""Publish dictionary-backed Abu Dhabi business semantics by evidence policy.

This module promotes source metadata only when the current technical catalog
and the supplied dictionary agree on the complete table field set.  It never
accepts benchmark questions, expected SQL, or result values as input.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any


ACTIVE_RESOURCE_STATUS = "active_governed_table_local_v3"
FULL_ALIGNMENT_STATUS = "exact_table_and_field_alignment"
PUBLISHER_SCHEMA = "gda.dictionary-semantic-publication.v1"

_GEOMETRY_TYPE_RE = re.compile(r"\b(?:geometry|geography)\b", re.IGNORECASE)
_NUMERIC_TYPE_RE = re.compile(
    r"\b(?:smallint|integer|bigint|numeric|decimal|real|double precision|float)\b",
    re.IGNORECASE,
)
_TEMPORAL_TYPE_RE = re.compile(r"\b(?:date|timestamp|time)\b", re.IGNORECASE)
_BINARY_TYPE_RE = re.compile(r"\b(?:bytea|raster)\b", re.IGNORECASE)
_SENSITIVE_FIELD_RE = re.compile(
    r"(?:password|passwd|credential|secret|access_?token|refresh_?token|passport)|"
    r"(?:^|_)(?:email|e_?mail|phone|mobile|fax|national_?id)(?:$|_)",
    re.IGNORECASE,
)
_OPERATIONAL_FIELD_RE = re.compile(
    r"^(?:created|updated|modified|last_edited)_(?:user|by)$|"
    r"^(?:createduser|updateduser|modifieduser|lastediteduser)$",
    re.IGNORECASE,
)
_IDENTIFIER_FIELD_RE = re.compile(
    r"(?:^|_)(?:id|ids|fid|uid|guid|uuid|objectid|globalid|code|number)(?:$|_)",
    re.IGNORECASE,
)
_LABEL_FIELD_RE = re.compile(
    r"(?:^|_)(?:name|nameenglish|namearabic|description|desc|label|title|road)(?:$|_)",
    re.IGNORECASE,
)
_PRIMARY_LABEL_RE = re.compile(
    r"(?:nameenglish|english(?:name|label|description)|(?:^|_)(?:name|label|description|title)_(?:en|eng|engl)(?:$|_))",
    re.IGNORECASE,
)
_LOCALIZED_LABEL_RE = re.compile(
    r"(?:namearabic|arabic(?:name|label|description)|(?:^|_)(?:name|label|description|title)_(?:ar|ara|arab)(?:$|_))",
    re.IGNORECASE,
)
_MEASURE_TERM_RE = re.compile(
    r"(?:count|capacity|area|length|width|height|diameter|elevation|distance|"
    r"ratio|percentage|percent|score|amount|total|volume|weight|数量|容量|面积|"
    r"长度|宽度|高度|直径|高程|距离|比例|得分|总量)",
    re.IGNORECASE,
)
_DIMENSION_TERM_RE = re.compile(
    r"(?:status|type|category|class|kind|municipality|district|region|city|"
    r"状态|类型|类别|市政|片区|区域|城市)",
    re.IGNORECASE,
)
_ALL_NULL_RE = re.compile(r"(?:全空字段|all[- ]null|no non[- ]null)", re.IGNORECASE)
_PROFILE_SUFFIX_RE = re.compile(
    r"(?:[。；;]?\s*样例值\s*[:：]|[（(]\s*\d+\s*个取值|"
    r"[（(]\s*(?:全表唯一|唯一\s*\d+)|[（(]\s*单值)",
    re.IGNORECASE,
)


class DictionarySemanticPublicationError(ValueError):
    """Raised when publication evidence is inconsistent or incomplete."""


def _load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _safe_identifier(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_]+", "_", str(value)).strip("_").lower() or "resource"


def _humanize_identifier(value: str) -> str:
    text = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", str(value))
    return re.sub(r"[^A-Za-z0-9]+", " ", text).strip().lower()


def _business_table_alias(table: str) -> str:
    bare = table.rsplit(".", 1)[-1]
    bare = re.sub(
        r"^(?:udm_|ud_|poi_|masterplan_|adwea_[a-z]+_)",
        "",
        bare,
        flags=re.IGNORECASE,
    )
    return _humanize_identifier(bare)


def _normalized_compound(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "", str(value or "").casefold())
    replacements = {
        "facilities": "facility",
        "boundaries": "boundary",
        "oases": "oasis",
        "centrelines": "centreline",
    }
    for plural, singular in replacements.items():
        if normalized.endswith(plural):
            normalized = normalized[: -len(plural)] + singular
    if len(normalized) > 3 and normalized.endswith("s") and not normalized.endswith(
        ("ss", "is", "us")
    ):
        normalized = normalized[:-1]
    return normalized


def _dictionary_compound_aliases(table: str, evidence_text: str) -> list[str]:
    """Recover spaced business names from concatenated source identifiers."""

    target = _normalized_compound(_business_table_alias(table))
    words = re.findall(r"[A-Za-z][A-Za-z0-9]*", evidence_text)
    aliases: list[str] = []
    for width in range(2, 6):
        for index in range(len(words) - width + 1):
            phrase_words = words[index : index + width]
            phrase = " ".join(phrase_words).casefold()
            if _normalized_compound(phrase) == target:
                aliases.append(phrase)
    return list(dict.fromkeys(aliases))[:8]


def _agency_aliases(value: str) -> list[str]:
    aliases: list[str] = []
    expansions = {
        "adr ": ("address ", "addressing "),
        "dct ": ("culture and tourism ", "cultural ", "tourism "),
        "doh ": ("health ", "healthcare "),
        "adek ": ("education ", "school "),
    }
    folded = str(value or "").casefold()
    for prefix, replacements in expansions.items():
        if folded.startswith(prefix):
            aliases.extend(replacement + folded[len(prefix) :] for replacement in replacements)
    return aliases


def _strip_profile_values(value: Any, *, limit: int = 220) -> str:
    text = re.sub(r"[`*_]", "", str(value or ""))
    text = re.sub(r"\s+", " ", text).strip()
    match = _PROFILE_SUFFIX_RE.search(text)
    if match:
        text = text[: match.start()].rstrip(" 。；;,，")
    return text[:limit].strip()


def _language_label(description: str, physical: str, language: str) -> str:
    fallback = _humanize_identifier(physical)
    if language == "zh":
        match = re.search(r"[\u4e00-\u9fff][^。；;（(——]{0,54}", description)
        return (match.group(0).strip(" ，,:：-/") if match else fallback) or fallback
    if language == "en":
        match = re.match(r"\s*([A-Za-z][A-Za-z0-9 ,/'()\-]{2,110})", description)
        return (match.group(1).strip(" ,.-") if match else fallback) or fallback
    return fallback


def _field_role(name: str, data_type: str, description: str) -> str:
    lowered = name.casefold()
    if _GEOMETRY_TYPE_RE.search(data_type):
        return "geometry"
    if _IDENTIFIER_FIELD_RE.search(lowered) or re.search(
        r"(?:unique identifier|唯一标识|唯一编号|自增主键|globalid|guid)",
        description,
        re.IGNORECASE,
    ):
        return "identifier"
    if _LABEL_FIELD_RE.search(lowered):
        return "label"
    if _TEMPORAL_TYPE_RE.search(data_type):
        return "temporal_dimension"
    if _NUMERIC_TYPE_RE.search(data_type) and _MEASURE_TERM_RE.search(
        f"{lowered} {description}"
    ) and not _DIMENSION_TERM_RE.search(f"{lowered} {description}"):
        return "measure"
    return "dimension"


def _field_display_role(name: str, role: str, description: str) -> str | None:
    """Classify human-readable labels without treating IDs as display values."""

    if role != "label":
        return None
    evidence = f"{name} {description}"
    if _LOCALIZED_LABEL_RE.search(evidence) or re.search(
        r"(?:阿文|阿拉伯|arabic-language|arabic language)", description, re.IGNORECASE
    ):
        return "localized_label"
    if _PRIMARY_LABEL_RE.search(evidence) or re.search(
        r"(?:英文|english-language|english language)", description, re.IGNORECASE
    ):
        return "primary_label"
    if re.fullmatch(r"(?:name|label|title)", name, re.IGNORECASE):
        return "primary_label"
    return None


def _field_is_publishable(name: str, data_type: str, description: str) -> bool:
    if not name or _BINARY_TYPE_RE.search(data_type):
        return False
    if _SENSITIVE_FIELD_RE.search(name) or _OPERATIONAL_FIELD_RE.search(name):
        return False
    return not _ALL_NULL_RE.search(description)


def _semantic_field(
    physical: str,
    data_type: str,
    description: str,
) -> dict[str, Any]:
    business_description = _strip_profile_values(description)
    role = _field_role(physical, data_type, business_description)
    field: dict[str, Any] = {
        "semantic_field": physical,
        "physical_field": physical,
        "labels": {
            "zh": _language_label(business_description, physical, "zh"),
            "en": _language_label(business_description, physical, "en"),
            "ar": _language_label(business_description, physical, "ar"),
        },
        "business_role": role,
        "definition_status": "dictionary_supported",
    }
    display_role = _field_display_role(physical, role, business_description)
    if display_role:
        field["display_role"] = display_role
    if business_description:
        field["description"] = business_description
    if role == "geometry":
        field["usage"] = "predicate_or_derived_metric_only"
    return field


def _merge_fields(
    generated: list[dict[str, Any]],
    reviewed: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    reviewed_by_name = {
        str(item.get("physical_field") or "").casefold(): item
        for item in reviewed
        if isinstance(item, dict) and item.get("physical_field")
    }
    merged: list[dict[str, Any]] = []
    for field in generated:
        override = reviewed_by_name.pop(str(field["physical_field"]).casefold(), None)
        merged.append({**field, **(override or {})})
    merged.extend(reviewed_by_name.values())
    return merged


def _generated_asset(
    resource: dict[str, Any],
    alignment: dict[str, Any],
    existing: dict[str, Any] | None,
    existing_binding_fields: list[dict[str, Any]],
    required_contract_fields: set[str],
    vocabulary: dict[str, Any],
) -> dict[str, Any]:
    table = str(resource["physical_table"])
    document = alignment.get("dictionary_document") or {}
    field_descriptions = {
        str(name).casefold(): str(description or "")
        for name, description in (document.get("field_descriptions") or {}).items()
    }
    fields: list[dict[str, Any]] = []
    retrieval_terms: list[str] = []
    for item in resource.get("fields") or []:
        physical = str(item.get("physical_field") or "")
        data_type = str(item.get("data_type") or "")
        description = field_descriptions.get(physical.casefold(), "")
        if not _field_is_publishable(physical, data_type, description):
            continue
        fields.append(_semantic_field(physical, data_type, description))
        term = _strip_profile_values(description, limit=160)
        if term:
            retrieval_terms.append(term)

    existing = existing or {}
    # Existing table-local contracts may still reference a conservative field
    # selected by the v3 inventory builder.  Preserve that already-authorized
    # surface so publication is atomic with respect to active contracts; the
    # dictionary definition still wins whenever both sources describe a field.
    generated_names = {
        str(item.get("physical_field") or "").casefold() for item in fields
    }
    for binding_field in existing_binding_fields:
        name = str(binding_field.get("physical_field") or "")
        if name.casefold() not in generated_names and not _SENSITIVE_FIELD_RE.search(name):
            fields.append(dict(binding_field))
            generated_names.add(name.casefold())
    resource_fields = {
        str(item.get("physical_field") or "").casefold(): item
        for item in resource.get("fields") or []
        if isinstance(item, dict) and item.get("physical_field")
    }
    for required_name in sorted(required_contract_fields, key=str.casefold):
        if required_name.casefold() in generated_names:
            continue
        source_field = resource_fields.get(required_name.casefold())
        if source_field is None or _SENSITIVE_FIELD_RE.search(required_name):
            continue
        data_type = str(source_field.get("data_type") or "")
        fields.append(
            _semantic_field(
                required_name,
                data_type,
                field_descriptions.get(required_name.casefold(), ""),
            )
        )
        generated_names.add(required_name.casefold())
    fields = _merge_fields(fields, list(existing.get("fields") or []))
    value_semantics = vocabulary.get("field_value_semantics") or {}
    for field in fields:
        physical = str(field.get("physical_field") or "")
        configured = value_semantics.get(f"{table}.{physical}") or value_semantics.get(
            f"*.{physical}"
        )
        if configured:
            field["value_semantics"] = {
                str(source_value): [str(alias) for alias in aliases]
                for source_value, aliases in configured.items()
            }
    geometry_fields = [
        item for item in fields if item.get("business_role") == "geometry"
    ]
    measure_fields = [item for item in fields if item.get("business_role") == "measure"]
    label = str(document.get("label") or table.rsplit(".", 1)[-1])
    description = _strip_profile_values(document.get("description"), limit=600)
    business_alias = _business_table_alias(table)
    evidence_text = " ".join(
        [
            str(document.get("description") or ""),
            *field_descriptions.values(),
        ]
    )
    compound_aliases = _dictionary_compound_aliases(table, evidence_text)
    agency_aliases = [
        alias
        for value in [business_alias, *compound_aliases]
        for alias in _agency_aliases(value)
    ]
    configured_aliases = [
        str(value)
        for value in (vocabulary.get("entity_aliases") or {}).get(table, [])
        if str(value).strip()
    ]
    aliases = list(
        dict.fromkeys(
            str(value).strip()
            for value in [
                *((existing.get("labels") or {}).values()),
                *(existing.get("aliases") or []),
                label,
                business_alias,
                *compound_aliases,
                *agency_aliases,
                *configured_aliases,
            ]
            if str(value or "").strip()
        )
    )
    roles = ["entity", "countable"]
    if geometry_fields:
        roles.append("spatial_entity")
    capabilities = ["count", "group_by", "filter", "detail"]
    if measure_fields:
        capabilities.extend(["sum", "average", "ranking"])
    if geometry_fields:
        capabilities.extend(["spatial_predicate", "spatial_distance"])

    asset = {
        "asset_id": existing.get("asset_id")
        or f"makani.dictionary.{_safe_identifier(table.rsplit('.', 1)[-1])}",
        "review_status": existing.get("review_status")
        or "reviewed_dictionary_supported_v1",
        "physical_tables": [table],
        "labels": existing.get("labels")
        or {"zh": label, "en": business_alias, "ar": business_alias},
        "aliases": aliases,
        "description": existing.get("description") or description or label,
        "retrieval_terms": list(
            dict.fromkeys(
                [
                    description,
                    *retrieval_terms,
                    *(existing.get("retrieval_terms") or []),
                ]
            )
        )[:96],
        "grain": existing.get("grain") or f"one row per documented {label} record",
        "roles": list(dict.fromkeys([*(existing.get("roles") or []), *roles])),
        "capabilities": list(
            dict.fromkeys([*(existing.get("capabilities") or []), *capabilities])
        ),
        "fields": fields,
        "publication_evidence": {
            "policy": PUBLISHER_SCHEMA,
            "alignment_status": alignment.get("dictionary_alignment_status"),
            "matched_field_coverage": alignment.get("matched_field_coverage"),
            "dictionary_path": document.get("path"),
            "dictionary_sha256": document.get("sha256"),
            "profile_values_in_runtime_terms": False,
            "business_alias_derivation": "dictionary_and_identifier_normalization",
            "reviewed_vocabulary_alias_count": len(configured_aliases),
        },
    }
    return asset


def build_dictionary_supported_assets(
    *,
    catalog: dict[str, Any],
    alignment: dict[str, Any],
    semantic_layer: dict[str, Any],
    vocabulary: dict[str, Any] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Build reviewed assets solely from current metadata and dictionary evidence."""

    vocabulary = vocabulary or {}
    if vocabulary and vocabulary.get("schema") != "gda.makani-business-vocabulary.v1":
        raise DictionarySemanticPublicationError("business vocabulary schema is unsupported")
    if catalog.get("schema") != "gda.technical-semantic-catalog.v1":
        raise DictionarySemanticPublicationError("technical catalog schema is unsupported")
    if alignment.get("schema") != "gda.abu-dhabi-dictionary-alignment.v1":
        raise DictionarySemanticPublicationError("dictionary alignment schema is unsupported")
    if alignment.get("source_kind") != "makani":
        raise DictionarySemanticPublicationError("only Makani publication is supported")
    catalog_evidence = catalog.get("source_evidence") or {}
    alignment_evidence = alignment.get("source_evidence") or {}
    if catalog_evidence.get("discovery_fingerprint") != alignment_evidence.get(
        "discovery_fingerprint"
    ):
        raise DictionarySemanticPublicationError("dictionary discovery fingerprint mismatch")

    alignments = {
        str(item.get("physical_table") or ""): item
        for item in alignment.get("resources") or []
        if isinstance(item, dict) and item.get("physical_table")
    }
    existing_by_table = {
        str(table): asset
        for asset in semantic_layer.get("semantic_assets") or []
        if isinstance(asset, dict)
        for table in asset.get("physical_tables") or []
    }
    bindings_by_table = {
        str(item.get("physical_table") or ""): item
        for item in semantic_layer.get("table_bindings") or []
        if isinstance(item, dict) and item.get("physical_table")
    }
    contract_fields_by_table: dict[str, set[str]] = {}
    for contract in semantic_layer.get("metric_contracts") or []:
        if not isinstance(contract, dict):
            continue
        for item in [
            *(contract.get("dimensions") or []),
            *(contract.get("metrics") or []),
        ]:
            if not isinstance(item, dict) or item.get("field") in {None, "*"}:
                continue
            table = str(item.get("table") or "")
            field = str(item.get("field") or "")
            if table and field:
                contract_fields_by_table.setdefault(table, set()).add(field)
    assets: list[dict[str, Any]] = []
    eligible_table_count = 0
    published_field_count = 0
    excluded_field_count = 0
    for resource in catalog.get("resources") or []:
        if not isinstance(resource, dict):
            continue
        table = str(resource.get("physical_table") or "")
        evidence = alignments.get(table)
        if (
            resource.get("semantic_status") != ACTIVE_RESOURCE_STATUS
            or not evidence
            or evidence.get("dictionary_alignment_status") != FULL_ALIGNMENT_STATUS
        ):
            continue
        eligible_table_count += 1
        asset = _generated_asset(
            resource,
            evidence,
            existing_by_table.get(table),
            list((bindings_by_table.get(table) or {}).get("fields") or []),
            contract_fields_by_table.get(table, set()),
            vocabulary,
        )
        published_field_count += len(asset["fields"])
        excluded_field_count += max(0, len(resource.get("fields") or []) - len(asset["fields"]))
        assets.append(asset)

    assets.sort(key=lambda item: str(item["physical_tables"][0]).casefold())
    summary = {
        "schema": PUBLISHER_SCHEMA,
        "source_kind": "makani",
        "eligible_table_count": eligible_table_count,
        "published_asset_count": len(assets),
        "published_field_count": published_field_count,
        "policy_excluded_field_count": excluded_field_count,
        "publication_inputs": {
            "benchmark_questions": False,
            "gold_sql": False,
            "expected_results": False,
        },
        "reviewed_vocabulary_entity_count": len(vocabulary.get("entity_aliases") or {}),
        "reviewed_value_semantic_field_count": len(
            vocabulary.get("field_value_semantics") or {}
        ),
    }
    return assets, summary


def publish_dictionary_supported_semantics(
    *,
    catalog_path: Path,
    alignment_path: Path,
    semantic_layer_path: Path,
    ontology_path: Path,
    business_vocabulary_path: Path | None = None,
) -> dict[str, Any]:
    """Publish eligible assets into the executable semantic and ontology layers."""

    catalog = _load_json(catalog_path)
    alignment = _load_json(alignment_path)
    semantic = _load_json(semantic_layer_path)
    ontology = _load_json(ontology_path)
    vocabulary = _load_json(business_vocabulary_path) if business_vocabulary_path else {}
    assets, summary = build_dictionary_supported_assets(
        catalog=catalog,
        alignment=alignment,
        semantic_layer=semantic,
        vocabulary=vocabulary,
    )
    if summary["published_asset_count"] != summary["eligible_table_count"]:
        raise DictionarySemanticPublicationError("not every eligible table was published")

    bindings = {
        str(item.get("physical_table") or ""): item
        for item in semantic.get("table_bindings") or []
    }
    for asset in assets:
        table = str(asset["physical_tables"][0])
        binding = bindings.get(table)
        if binding is None:
            raise DictionarySemanticPublicationError(f"semantic table binding missing: {table}")
        binding.update(
            {
                "business_asset_id": asset["asset_id"],
                "business_description": asset["description"],
                "business_roles": asset["roles"],
                "business_grain": asset["grain"],
                "review_status": asset["review_status"],
                "labels": asset["labels"],
                "aliases": asset["aliases"],
                "fields": asset["fields"],
            }
        )

    semantic["semantic_version"] = "abu-dhabi-makani-v5-dictionary-published"
    semantic["semantic_assets"] = assets
    semantic["dictionary_semantic_publication"] = {
        **summary,
        "catalog_path": str(catalog_path),
        "catalog_sha256": _sha256(catalog_path),
        "alignment_path": str(alignment_path),
        "alignment_sha256": _sha256(alignment_path),
        "business_vocabulary_path": (
            str(business_vocabulary_path) if business_vocabulary_path else None
        ),
        "business_vocabulary_sha256": (
            _sha256(business_vocabulary_path) if business_vocabulary_path else None
        ),
    }
    gate = semantic.setdefault("activation_gate", {})
    gate["business_semantic_coverage_complete"] = False
    gate["business_semantic_coverage_scope"] = "exact_full_dictionary_alignment"
    gate["published_business_asset_count"] = len(assets)
    semantic_layer_path.write_text(
        json.dumps(semantic, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    concepts = {
        str(item.get("physical_binding") or ""): item
        for item in ontology.get("concepts") or []
    }
    for asset in assets:
        table = str(asset["physical_tables"][0])
        concept = concepts.get(table)
        if concept is None:
            raise DictionarySemanticPublicationError(f"ontology concept missing: {table}")
        concept.update(
            {
                "business_asset_id": asset["asset_id"],
                "review_status": asset["review_status"],
                "labels": asset["labels"],
                "aliases": asset["aliases"],
                "description": asset["description"],
                "grain": asset["grain"],
                "roles": asset["roles"],
                "capabilities": asset["capabilities"],
                "fields": asset["fields"],
                "publication_evidence": asset["publication_evidence"],
            }
        )
    ontology["ontology_enrichment_version"] = semantic["semantic_version"]
    ontology["dictionary_semantic_publication"] = semantic[
        "dictionary_semantic_publication"
    ]
    coverage = ontology.setdefault("coverage", {})
    coverage["reviewed_business_asset_count"] = len(assets)
    ontology["relations"] = list(semantic.get("relationships") or [])
    coverage["reviewed_relationship_count"] = len(ontology["relations"])
    coverage["business_semantic_coverage_complete"] = False
    coverage["business_semantic_coverage_scope"] = "exact_full_dictionary_alignment"
    ontology_path.write_text(
        json.dumps(ontology, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return summary


__all__ = [
    "DictionarySemanticPublicationError",
    "PUBLISHER_SCHEMA",
    "build_dictionary_supported_assets",
    "publish_dictionary_supported_semantics",
]
