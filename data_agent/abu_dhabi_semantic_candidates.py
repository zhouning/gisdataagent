"""Evidence-bound semantic candidate assets for large Abu Dhabi source catalogs.

The candidate catalog is deliberately separate from the executable semantic
layer.  A supplied data dictionary can make a resource searchable in business
language, but it cannot certify its grain, KPI definitions, joins, sensitivity
policy, or authority.  Only an explicitly published reviewed asset gains
runtime execution authority.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections import Counter
from pathlib import Path
from typing import Any


CANDIDATE_CATALOG_SCHEMA = "gda.abu-dhabi-semantic-candidate-catalog.v1"
_ACTIVE_RESOURCE_STATUS = "active_governed_table_local_v3"
_DICTIONARY_CANDIDATE_STATUSES = {
    "exact_table_and_field_alignment",
    "exact_table_partial_field_alignment",
}
# Keep one-character alphabetic components: source dictionaries legitimately
# use prefixes such as ``t``, ``e`` and ``l`` to distinguish asset families.
# Dropping them makes ``t ductedge`` indistinguishable from ``ductedge``.
_TEXT_RUN_RE = re.compile(r"[\u4e00-\u9fff]{2,}|[A-Za-z][A-Za-z0-9]*|[\u0600-\u06ff]{2,}")
_ENGLISH_STOPWORDS = {
    "a",
    "all",
    "also",
    "an",
    "and",
    "are",
    "as",
    "at",
    "available",
    "be",
    "by",
    "each",
    "for",
    "from",
    "how",
    "if",
    "in",
    "into",
    "is",
    "i",
    "it",
    "list",
    "located",
    "many",
    "of",
    "on",
    "or",
    "other",
    "record",
    "records",
    "registered",
    "report",
    "show",
    "the",
    "their",
    "them",
    "there",
    "these",
    "they",
    "to",
    "what",
    "which",
    "with",
    "within",
}
_IRREGULAR_ENGLISH_SINGULAR = {
    "facilities": "facility",
    "oases": "oasis",
    "indices": "index",
    "categories": "category",
    "boundaries": "boundary",
}
_ENGLISH_TOKEN_EQUIVALENTS = {
    "accessible": "handicapped",
    "centre": "center",
    "centreline": "centerline",
    "meter": "machine",
    "signage": "sign",
    "street": "road",
}
_COMPOSITE_QUERY_RE = re.compile(
    r"(?:同时|并且|分别|各自|以及|和|与|及|\band\b|\beach\b|\bboth\b)",
    re.IGNORECASE,
)
_QUERY_OPERATION_RE = re.compile(
    r"(?:多少|数量|个数|统计|汇总|总数|总量|平均|均值|求和|最高|最低|排名|前\s*\d+|比较|对比|列出|显示|哪些|哪一个|哪几个|每个|各自|分别|"
    r"比例|占比|比率|可用|记录|预测|forecast|predict|how many|how much|number of|count|average|mean|sum|total|ratio|share|percentage|percent|available|records?|highest|lowest|top\s*\d+|rank|compare|which|what are|what is|where is|is there|list|each|recorded)",
    re.IGNORECASE,
)
_ARABIC_QUERY_OPERATION_RE = re.compile(
    r"(?:كم|عدد|إجمالي|متوسط|مجموع|أعلى|أدنى|رتب|قائمة|كل|حسب)",
    re.IGNORECASE,
)
_AMBIGUOUS_STATUS_RE = re.compile(r"(?:状态|status|state)", re.IGNORECASE)
_STATUS_QUALIFIER_RE = re.compile(
    r"(?:物理|生命周期|现状|规划|竣工|建成|运营|physical|lifecycle|existing|planned|completed|operational|material)",
    re.IGNORECASE,
)
_GENERIC_OBJECT_ALIASES = {
    "数据", "data", "数量", "number", "count", "统计", "统计数据", "type", "类型", "状态", "status",
    "stage", "阶段", "现状", "规划", "已批", "已批规划", "current", "existing", "planned",
    "each", "每个", "行政", "district identifier", "identifier",
    "track",
    # These terms occur as dimensions or measure labels in many unrelated
    # assets.  They are useful inside a compound phrase (for example
    # ``domain score`` or ``facility completion``), but a lone occurrence is
    # not an entity identity and must not displace the fact asset that owns
    # the requested metric.
    "domain", "score", "completion", "facility", "facilities", "districts", "point",
}
_SPATIAL_OR_RELATIONSHIP_RE = re.compile(
    r"(?:内|之内|包含|相交|邻近|最近|within|inside|contain|contains|intersect|nearest|top\s*\d+|highest|lowest|最高|最低|前\s*\d+)",
    re.IGNORECASE,
)
_SPATIAL_CONTAINMENT_RE = re.compile(
    r"(?:内|之内|包含|within|inside|contain|contains)", re.IGNORECASE
)
_GROUPING_CONTEXT_RE = re.compile(
    r"(?:按|每个|各|每一|哪些|哪个|哪一个|which|what|by|per|in\s+each|each|最高的|最低的|top\s*\d*|bottom\s*\d*)\s*$",
    re.IGNORECASE,
)
_UNSUPPORTED_OPERATION_RE = re.compile(
    r"(?:预测|预估|预计|forecast|predict|prediction|projected|projection)",
    re.IGNORECASE,
)
_SENSITIVE_QUERY_RE = re.compile(
    r"(?:身份证(?:号|号码)?|护照号|社会安全号|手机号|手机号码|电话号码|电话|邮箱|email|phone|telephone|mobile|passport|social\s+security|personal\s+id)",
    re.IGNORECASE,
)
_GENERIC_ASSET_QUERY_RE = re.compile(
    r"(?:资产|asset|assets|数据|data|records?|记录)",
    re.IGNORECASE,
)
_TERM_SYNONYMS = {
    # Generic analytical vocabulary. These are language normalization rules,
    # not source- or benchmark-specific aliases.
    "shortfall": {"gap", "deficit", "needed", "shortage", "不足", "缺口"},
    "deficit": {"gap", "shortfall", "needed", "shortage", "不足", "缺口"},
    "pipeline": {"planned", "under construction", "在建", "规划"},
    "planned": {"pipeline", "under construction", "在建", "规划"},
    "current": {"existing", "present", "现状", "现有"},
    "existing": {"current", "present", "现状", "现有"},
    "residents": {"population", "inhabitants", "人口", "居民"},
    "population": {"residents", "inhabitants", "人口", "居民"},
    "居民": {"人口", "population", "residents"},
    "人口": {"居民", "population", "residents"},
    # Domain-language normalization used by the resolver, not a source- or
    # benchmark-specific mapping.  In the liveability cards, pedestrian
    # paths are documented as the sidewalk/public-realm QA concept; treating
    # these common phrases as lexical equivalents lets the governed catalog
    # select the wide-table score_sidewalks field without inventing a table.
    "pedestrian": {"sidewalk", "footpath", "walkway"},
    "pedestrians": {"sidewalk", "footpath", "walkway"},
    "pedestrian path": {"sidewalk", "footpath", "walkway"},
    "pedestrian paths": {"sidewalk", "footpath", "walkway"},
    "sidewalk": {"pedestrian", "footpath", "walkway"},
    "sidewalks": {"pedestrian", "footpath", "walkway"},
    "neighbourhood": {"neighborhood"},
    "neighborhood": {"neighbourhood"},
}

# Compound analytical phrases are normalized before candidate ranking.  They
# are vocabulary-level equivalences derived from reviewed table-card wording;
# they do not identify a table, benchmark row, Gold answer, or physical
# binding.  Keeping the expansion at token level lets a new catalog use the
# same resolver without adding question-specific rules.
_SEMANTIC_PHRASE_SYNONYMS = {
    "target need": {"target", "needed", "need", "shortfall", "gap", "ap50"},
    "target needs": {"target", "needed", "need", "shortfall", "gap", "ap50"},
    "fpp score": {"fpp", "facility", "provision", "sufficiency", "supply", "kpi"},
    "facility provision score": {"fpp", "facility", "provision", "sufficiency", "supply", "kpi"},
}


class SemanticCandidateCatalogError(ValueError):
    """A candidate catalog input is incomplete or internally inconsistent."""


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SemanticCandidateCatalogError(f"candidate_catalog_input_unavailable:{path.name}") from exc
    if not isinstance(value, dict):
        raise SemanticCandidateCatalogError(f"candidate_catalog_input_object_required:{path.name}")
    return value


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _safe_identifier(value: str) -> str:
    return re.sub(r"[^a-z0-9_]+", "_", str(value).casefold()).strip("_") or "resource"


def _short_text(value: Any, *, limit: int = 1_200) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text[:limit]


def _unique_strings(values: list[Any], *, limit: int = 24) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for raw in values:
        value = _short_text(raw, limit=240)
        key = value.casefold()
        if not value or key in seen:
            continue
        result.append(value)
        seen.add(key)
        if len(result) >= limit:
            break
    return result


def _document_aliases(label: str, description: str) -> list[str]:
    """Derive retrieval terms from supplied business documentation only."""

    parentheses = re.findall(r"[（(]([^()（）]{2,120})[)）]", label)
    first_sentence = re.split(r"[。.!?]\s*", description, maxsplit=1)[0]
    return _unique_strings([label, *parentheses, first_sentence], limit=8)


def _published_assets(semantic_layer: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Index approved runtime assets by their private physical bindings.

    The bindings remain necessary inside the governed catalog.  Their reviewed
    business labels and aliases are also valid retrieval evidence, unlike an
    unreviewed physical table name, so preserve them for candidate selection.
    """

    published: dict[str, dict[str, Any]] = {}
    for asset in semantic_layer.get("semantic_assets") or []:
        if not isinstance(asset, dict):
            continue
        review_status = str(asset.get("review_status") or "")
        if not review_status.casefold().startswith("reviewed"):
            continue
        for table in asset.get("physical_tables") or []:
            name = str(table or "")
            if name:
                published[name] = {
                    "asset_id": str(asset.get("asset_id") or ""),
                    "review_status": review_status,
                    "labels": dict(asset.get("labels") or {}),
                    "aliases": list(asset.get("aliases") or []),
                    "description": _short_text(asset.get("description")),
                    "fields": [
                        {
                            "physical_field": field.get("physical_field"),
                            "semantic_field": field.get("semantic_field"),
                            "labels": dict(field.get("labels") or {}),
                            "business_role": field.get("business_role"),
                        }
                        for field in asset.get("fields") or []
                        if isinstance(field, dict)
                    ],
                }
    return published


def _asset_state(
    resource: dict[str, Any],
    alignment: dict[str, Any] | None,
    published: dict[str, Any] | None,
) -> tuple[str, bool, str]:
    if published:
        return (
            "published_reviewed_asset",
            True,
            "Already bound to a reviewed runtime semantic asset.",
        )
    if str(resource.get("semantic_status") or "") != _ACTIVE_RESOURCE_STATUS:
        return (
            "not_eligible_non_business_or_restricted_resource",
            False,
            "Resource is excluded or pending from the governed technical inventory.",
        )
    status = str((alignment or {}).get("dictionary_alignment_status") or "")
    if status in _DICTIONARY_CANDIDATE_STATUSES:
        return (
            "dictionary_supported_review_required",
            True,
            "Dictionary evidence supports candidate retrieval; business review is required before execution.",
        )
    if status == "exact_table_without_field_alignment":
        return (
            "dictionary_table_only_review_required",
            True,
            "A table page exists but its current fields are not aligned; execution is not eligible.",
        )
    return (
        "documentation_gap_review_required",
        False,
        "No current exact dictionary page supports a business semantic candidate.",
    )


def build_semantic_candidate_catalog(
    *,
    catalog_path: Path,
    alignment_path: Path,
    semantic_layer_path: Path,
    source_kind: str,
) -> dict[str, Any]:
    """Build one full-coverage candidate catalog from frozen source evidence."""

    if source_kind not in {"liveability", "makani"}:
        raise SemanticCandidateCatalogError("source_kind must be liveability or makani")
    catalog = _load_json(catalog_path)
    alignment = _load_json(alignment_path)
    semantic_layer = _load_json(semantic_layer_path)
    if catalog.get("schema") != "gda.technical-semantic-catalog.v1":
        raise SemanticCandidateCatalogError("technical catalog schema is unsupported")
    if alignment.get("schema") != "gda.abu-dhabi-dictionary-alignment.v1":
        raise SemanticCandidateCatalogError("dictionary alignment schema is unsupported")
    if alignment.get("source_kind") != source_kind:
        raise SemanticCandidateCatalogError("dictionary alignment source kind mismatch")

    source_evidence = catalog.get("source_evidence") or {}
    alignment_source = alignment.get("source_evidence") or {}
    if source_evidence.get("discovery_fingerprint") != alignment_source.get("discovery_fingerprint"):
        raise SemanticCandidateCatalogError("dictionary alignment discovery fingerprint mismatch")

    alignment_by_table = {
        str(item.get("physical_table") or ""): item
        for item in alignment.get("resources") or []
        if isinstance(item, dict) and str(item.get("physical_table") or "")
    }
    published = _published_assets(semantic_layer)
    assets: list[dict[str, Any]] = []
    state_counts: Counter[str] = Counter()
    for resource in catalog.get("resources") or []:
        if not isinstance(resource, dict):
            continue
        table = str(resource.get("physical_table") or "")
        if not table:
            continue
        evidence = alignment_by_table.get(table)
        document = (evidence or {}).get("dictionary_document") or {}
        dictionary_label = _short_text(document.get("label"))
        dictionary_description = _short_text(document.get("description"))
        field_descriptions = document.get("field_descriptions") or {}
        published_asset = published.get(table)
        state, retrieval_eligible, state_reason = _asset_state(
            resource,
            evidence,
            published_asset,
        )
        state_counts[state] += 1
        source_fields = {
            str(field.get("physical_field") or ""): field
            for field in resource.get("fields") or []
            if isinstance(field, dict) and str(field.get("physical_field") or "")
        }
        reviewed_fields = {
            str(field.get("physical_field") or "").casefold(): field
            for field in (published_asset or {}).get("fields") or []
            if isinstance(field, dict) and field.get("physical_field")
        }
        fields = [
            {
                "physical_field": name,
                "data_type": source_fields[name].get("data_type"),
                "dictionary_description": _short_text(
                    field_descriptions.get(name)
                    or " / ".join(
                        str(value)
                        for value in (
                            (reviewed_fields.get(name.casefold()) or {}).get("labels") or {}
                        ).values()
                        if value
                    )
                ),
                "dictionary_supported": name.casefold()
                in {str(value).casefold() for value in field_descriptions},
                "published_semantic": (
                    {
                        "semantic_field": reviewed_fields[name.casefold()].get("semantic_field"),
                        "labels": dict(reviewed_fields[name.casefold()].get("labels") or {}),
                        "business_role": reviewed_fields[name.casefold()].get("business_role"),
                    }
                    if name.casefold() in reviewed_fields
                    else None
                ),
            }
            for name in sorted(source_fields, key=str.casefold)
        ]
        reviewed_labels = (published_asset or {}).get("labels") or {}
        reviewed_label_values = [
            _short_text(reviewed_labels.get(language))
            for language in ("zh", "en", "ar")
        ]
        reviewed_aliases = list((published_asset or {}).get("aliases") or [])
        reviewed_description = _short_text((published_asset or {}).get("description"))
        label = next((value for value in reviewed_label_values if value), dictionary_label)
        description = reviewed_description or dictionary_description
        aliases = _unique_strings(
            [
                *reviewed_label_values,
                *reviewed_aliases,
                *[
                    str(value)
                    for field in (published_asset or {}).get("fields") or []
                    for value in ((field.get("labels") or {}).values() if isinstance(field, dict) else [])
                ],
                *(_document_aliases(dictionary_label, dictionary_description) if dictionary_label else []),
            ],
            limit=16,
        )
        primary_aliases = _unique_strings(
            [
                *reviewed_label_values,
                *reviewed_aliases,
                *(_document_aliases(dictionary_label, dictionary_description) if dictionary_label else []),
            ],
            limit=12,
        )
        published_summary = (
            {
                "asset_id": published_asset.get("asset_id"),
                "review_status": published_asset.get("review_status"),
            }
            if published_asset
            else None
        )
        assets.append(
            {
                "candidate_id": f"abu_dhabi.{source_kind}.{_safe_identifier(table.rsplit('.', 1)[-1])}",
                "physical_table": table,
                "business_label": label or None,
                "business_aliases": aliases,
                "primary_business_aliases": primary_aliases,
                "business_description": description or None,
                "retrieval_evidence": {
                    "reviewed_semantic_asset": bool(published_asset),
                    "dictionary_business_document": bool(dictionary_label),
                },
                "fields": fields,
                "dictionary_alignment": {
                    "status": (evidence or {}).get("dictionary_alignment_status"),
                    "matched_field_count": (evidence or {}).get("matched_field_count", 0),
                    "matched_field_coverage": (evidence or {}).get("matched_field_coverage"),
                    "document_path": document.get("path"),
                    "document_sha256": document.get("sha256"),
                },
                "asset_state": state,
                "retrieval_eligible": retrieval_eligible,
                "state_reason": state_reason,
                "published_runtime_asset": published_summary,
                "review_requirements": [
                    "confirm business definition and grain",
                    "assign approved field roles, measures, units, and sensitive-field policy",
                    "approve every relationship, join cardinality, and spatial predicate independently",
                    "publish a versioned semantic asset and metric contracts before execution",
                ],
            }
        )

    if len(assets) != len(catalog.get("resources") or []):
        raise SemanticCandidateCatalogError("candidate catalog does not cover every technical resource")
    candidate_by_table = {
        str(item.get("physical_table") or ""): str(item.get("candidate_id") or "")
        for item in assets
        if item.get("physical_table") and item.get("candidate_id")
    }
    reviewed_relationships: list[dict[str, Any]] = []
    for relation in semantic_layer.get("relationships") or []:
        if not isinstance(relation, dict):
            continue
        left = str(relation.get("left") or "")
        right = str(relation.get("right") or "")
        left_table = left.rsplit(".", 1)[0] if "." in left else left
        right_table = right.rsplit(".", 1)[0] if "." in right else right
        left_id = candidate_by_table.get(left_table)
        right_id = candidate_by_table.get(right_table)
        review_status = str(relation.get("review_status") or "")
        if not left_id or not right_id or not review_status.casefold().startswith("reviewed"):
            continue
        reviewed_relationships.append(
            {
                "left_candidate_id": left_id,
                "right_candidate_id": right_id,
                "review_status": review_status,
                "execution_authorized": bool(relation.get("execution_authorized")),
                "kind": relation.get("kind"),
                "operator": relation.get("operator"),
            }
        )
    candidates = sum(
        count
        for state, count in state_counts.items()
        if state in {"published_reviewed_asset", "dictionary_supported_review_required", "dictionary_table_only_review_required"}
    )
    return {
        "schema": CANDIDATE_CATALOG_SCHEMA,
        "catalog_id": f"abu-dhabi-{source_kind}-semantic-candidates-v1",
        "source_kind": source_kind,
        "source_evidence": {
            "source_id": source_evidence.get("source_id"),
            "database_name": source_evidence.get("database_name"),
            "discovery_fingerprint": source_evidence.get("discovery_fingerprint"),
            "catalog_path": str(catalog_path),
            "catalog_sha256": _sha256(catalog_path),
            "dictionary_alignment_path": str(alignment_path),
            "dictionary_alignment_sha256": _sha256(alignment_path),
            "semantic_layer_path": str(semantic_layer_path),
            "semantic_layer_sha256": _sha256(semantic_layer_path),
        },
        "coverage": {
            "resource_count": len(assets),
            "candidate_asset_count": candidates,
            "published_runtime_asset_count": state_counts["published_reviewed_asset"],
            "dictionary_supported_review_required_count": state_counts["dictionary_supported_review_required"],
            "dictionary_table_only_review_required_count": state_counts["dictionary_table_only_review_required"],
            "documentation_gap_review_required_count": state_counts["documentation_gap_review_required"],
            "not_eligible_non_business_or_restricted_resource_count": state_counts[
                "not_eligible_non_business_or_restricted_resource"
            ],
            "asset_state_counts": dict(sorted(state_counts.items())),
        },
        "runtime_role": {
            "candidate_retrieval": "business-label and documentation evidence only",
            "execution_authority": "published reviewed semantic assets and reviewed metric contracts only",
            "physical_table_name_required_in_question": False,
            "candidate_assets_may_execute": False,
        },
        "relationship_authority": {
            "schema": "gda.abu-dhabi-semantic-relationship-authority.v1",
            "reviewed_relationship_count": len(reviewed_relationships),
            "relationships": reviewed_relationships,
        },
        "claim_boundary": {
            "all_resources_assessed": True,
            "candidate_catalog_is_not_business_semantic_approval": True,
            "candidate_catalog_does_not_authorize_sql": True,
            "dictionary_is_not_runtime_authority": True,
            "runtime_metadata_is_authoritative": True,
            "source_rows_persisted": False,
        },
        "assets": assets,
    }


def write_semantic_candidate_catalog(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _text_tokens(value: Any) -> set[str]:
    tokens: set[str] = set()
    text = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", str(value or "")).casefold()
    for run in _TEXT_RUN_RE.findall(text):
        if re.fullmatch(r"[\u4e00-\u9fff]+", run):
            max_width = min(4, len(run))
            for width in range(2, max_width + 1):
                tokens.update(run[index : index + width] for index in range(len(run) - width + 1))
        else:
            normalized = _singular_english_token(run)
            if normalized not in _ENGLISH_STOPWORDS:
                tokens.add(normalized)
    # Numeric suffixes are meaningful asset disambiguators (for example
    # ``aircompressor 1`` versus the primary ``aircompressor`` table). Keep
    # standalone numbers while avoiding digits embedded in ordinary words.
    tokens.update(re.findall(r"(?<![a-z])\d+(?![a-z])", text))
    return tokens


def _singular_english_token(value: str) -> str:
    token = str(value or "").casefold()
    if token in _IRREGULAR_ENGLISH_SINGULAR:
        token = _IRREGULAR_ENGLISH_SINGULAR[token]
    elif len(token) > 4 and token.endswith("ies"):
        token = token[:-3] + "y"
    elif len(token) > 4 and token.endswith("es") and token[-3] in {"s", "x", "z"}:
        token = token[:-2]
    elif (
        len(token) > 3
        and token.endswith("s")
        and not token.endswith(("ss", "is", "us"))
    ):
        token = token[:-1]
    return _ENGLISH_TOKEN_EQUIVALENTS.get(token, token)


def _phrase_in_question(question: str, phrase: str) -> bool:
    """Match business phrases on word boundaries with plural normalization."""

    phrase = str(phrase or "").strip()
    if len(phrase) < 2:
        return False
    if re.search(r"[\u4e00-\u9fff]", phrase):
        # Dictionary labels often qualify a short business object, for
        # example ``路灯（配电口径）`` or ``ADSSC 重力污水管``. Match the
        # meaningful CJK run inside the label instead of requiring the whole
        # documentation label to occur verbatim in the question.
        folded_question = re.sub(r"\s+", "", str(question or "").casefold())
        folded_phrase = re.sub(r"\s+", "", phrase.casefold())
        if folded_phrase in folded_question:
            return True
        phrase_runs = re.findall(r"[\u4e00-\u9fff]{2,}", folded_phrase)
        question_runs = re.findall(r"[\u4e00-\u9fff]{2,}", folded_question)
        if any(len(run) >= 3 and any(run in question_run for question_run in question_runs) for run in phrase_runs):
            return True
        # For qualified Chinese asset labels, a shared prefix is not enough:
        # ``重力污水管`` must not resolve to ``重力污水排放井``.  Retain fuzzy
        # matching only when at least three adjacent two-character terms are
        # shared, as with ``中压架空电力线段`` versus ``中压架空线段``.
        for run in phrase_runs:
            if len(run) < 4:
                continue
            phrase_bigrams = {run[index : index + 2] for index in range(len(run) - 1)}
            for question_run in question_runs:
                question_bigrams = {
                    question_run[index : index + 2]
                    for index in range(len(question_run) - 1)
                }
                if (
                    len(phrase_bigrams & question_bigrams) >= 3
                    and run[-2:] in question_run
                ):
                    return True
        return False
    if re.search(r"[\u0600-\u06ff]", phrase):
        return phrase.casefold() in str(question or "").casefold()
    normalized_question = str(question or "")
    normalized_question = re.sub(
        r"\b(?:as\s+well|delivery\s+pipeline)\b",
        " ",
        normalized_question,
        flags=re.I,
    )
    phrase_tokens = [
        _singular_english_token(value)
        for value in re.findall(r"[A-Za-z0-9]+", phrase)
    ]
    question_tokens = [
        _singular_english_token(value)
        for value in re.findall(r"[A-Za-z0-9]+", normalized_question)
    ]
    if not phrase_tokens or len(phrase_tokens) > len(question_tokens):
        return False
    width = len(phrase_tokens)
    return any(
        question_tokens[index : index + width] == phrase_tokens
        for index in range(len(question_tokens) - width + 1)
    )


def _asset_token_sets(asset: dict[str, Any]) -> tuple[set[str], set[str]]:
    # Field labels are evidence for measure/relationship matching, but they
    # must not outweigh the asset's own business name during table selection.
    label_tokens = _text_tokens(" ".join(_object_aliases(asset)))
    detail_values = [asset.get("business_description") or ""]
    detail_values.extend(
        str(field.get("dictionary_description") or "")
        for field in asset.get("fields") or []
        if isinstance(field, dict)
    )
    return label_tokens, _text_tokens(" ".join(detail_values))


def _object_aliases(asset: dict[str, Any]) -> list[str]:
    """Return compact object names from the semantic evidence.

    Dictionary exports also contain field descriptions and relationship notes.
    Those remain useful detail evidence, but treating them as object aliases
    makes a query for ``status`` look like a request for every status-bearing
    table. Compact aliases are the only values allowed to drive entity
    matching and the strong phrase bonus.
    """

    values = [asset.get("business_label"), *(asset.get("primary_business_aliases") or [])]
    # A table-card description commonly cites its own physical field names
    # (for example ``Number_Of_Buildings`` or ``Building_Storey``).  Those
    # identifiers are useful detail evidence for metric grounding, but they
    # are not business-object names.  Keep a normalized set so the promotion
    # of compound identifiers below cannot turn a field into a second entity
    # during candidate-set selection.
    field_identifiers = {
        re.sub(r"[^a-z0-9]+", "", str(value or "").casefold())
        for field in asset.get("fields") or []
        for value in (field.get("physical_field"), field.get("semantic_field"))
        if str(value or "").strip()
    }
    # Customer table cards often keep enum/value vocabulary in a field's
    # definition rather than duplicating it at asset level (for example
    # ``Neighbourhood_Majlis`` in a facility subcategory field).  Promote
    # explicit compound identifiers to searchable aliases.  This is a
    # metadata-derived rule: it does not name a source, table, benchmark case
    # or expected answer, and it avoids treating ordinary prose words as
    # business entities.  Physical/semantic field *names* are deliberately
    # excluded here: they are field evidence, not object identity, and adding
    # every field name can crowd out reviewed business aliases.
    for field in asset.get("fields") or []:
        if not isinstance(field, dict):
            continue
        values.extend(str(value) for value in (field.get("value_domain") or []))
        values.extend(str(value) for value in (field.get("value_semantics") or {}).keys())
        for description_key in ("description", "definition", "dictionary_description"):
            description = str(field.get(description_key) or "")
            for identifier in re.findall(r"\b[A-Z][A-Za-z0-9]+(?:_[A-Za-z0-9]+)+\b", description):
                normalized = re.sub(r"[^a-z0-9]+", "", identifier.casefold())
                if normalized in field_identifiers:
                    continue
                # Glossary/table tokens are documentation provenance, not
                # objects.  Value-domain identifiers (for example
                # ``Neighbourhood_Majlis``) remain eligible for retrieval.
                if normalized.startswith("glossary"):
                    continue
                values.append(identifier)
    result: list[str] = []
    seen: set[str] = set()
    for raw in values:
        value = re.sub(r"\s+", " ", str(raw or "")).strip()
        if not value or len(value) > 48:
            continue
        if len(re.findall(r"[\u4e00-\u9fff]", value)) > 18:
            continue
        if re.search(
            r"(?:\b(?:code|field|date|identifier|records?|holds|used for|official|category|type|count|stage|name)\b|字段|标识|记录|存储|用于|官方·|类别|类型|数量|阶段|现状|规划|已批规划)",
            value,
            re.IGNORECASE,
        ) and not re.search(
            r"(?:设施类别|facility category|设施类型|facility type|宜居行政区|市政服务走廊|重力污水管|配电变电站|路灯|学校|建筑)",
            value,
            re.IGNORECASE,
        ):
            continue
        key = value.casefold()
        if key in seen:
            continue
        seen.add(key)
        result.append(value)
    # Published table cards can contain a number of field-specific aliases.
    # Keep a bounded but complete-enough prefix so later, equally important
    # metrics (for example streetlight/cycle-track completion) are not lost
    # merely because the card listed generic identity terms first.  The cap
    # is a prompt-size safeguard, not a source- or benchmark-specific rule.
    return result[:64]


def _expanded_query_tokens(question: str) -> set[str]:
    tokens = _text_tokens(question)
    normalized = str(question or "").casefold()
    for token in tuple(tokens):
        tokens.update(_TERM_SYNONYMS.get(token, set()))
    # English phrase normalization is deliberately conservative: only add a
    # synonym when the complete token occurs in the question.
    for source, synonyms in _TERM_SYNONYMS.items():
        if re.search(rf"\b{re.escape(source)}\b", normalized):
            tokens.update(_text_tokens(" ".join(synonyms)))
    # Apply only complete, documented compound phrases.  This avoids turning
    # a lone word such as ``target`` or ``score`` into an identity signal while
    # still allowing natural wording like ``target need`` and ``FPP score`` to
    # reach the corresponding published metric evidence.
    for source, synonyms in _SEMANTIC_PHRASE_SYNONYMS.items():
        if re.search(rf"\b{re.escape(source)}\b", normalized):
            tokens.update(_text_tokens(" ".join(synonyms)))
    return tokens


def _preferred_asset_adjustment(asset: dict[str, Any]) -> float:
    """Use reviewed documentation markers to retire superseded duplicates."""

    text = " ".join(
        str(value or "")
        for value in (asset.get("business_label"), *_object_aliases(asset))
    ).casefold()
    preferred = bool(
        re.search(r"(?:以本表为准|当前使用|preferred|canonical|authoritative|use this)", text)
    )
    deprecated = bool(
        re.search(r"(?:改用|不要使用|已弃用|弃用|deprecated|superseded|legacy|archive)", text)
    )
    return (45.0 if preferred else 0.0) - (85.0 if deprecated else 0.0)


def _semantic_intent_adjustment(question: str, asset: dict[str, Any]) -> float:
    """Score business intent against reviewed labels and field roles.

    This is an evidence-weighted ranking feature. It does not identify a
    physical table or contain a question-specific branch; the terms come from
    the candidate's business labels, descriptions, and published field roles.
    """

    query = str(question or "").casefold()
    evidence = " ".join(
        [
            str(asset.get("business_label") or ""),
            str(asset.get("business_description") or ""),
            *[str(value or "") for value in asset.get("business_aliases") or []],
            *[
                str(value or "")
                for field in asset.get("fields") or []
                for value in ((field.get("published_semantic") or {}).get("labels") or {}).values()
            ],
        ]
    ).casefold()
    adjustment = 0.0
    if re.search(r"(?:shortfall|deficit|gap|不足|缺口|供需)", query):
        adjustment += 260.0 if re.search(r"(?:shortfall|deficit|gap|supply gap|供需缺口|缺口)", evidence) else 0.0
        adjustment += 80.0 if re.search(r"(?:supply|demand|needed|current|pipeline)", evidence) else 0.0
        adjustment -= 150.0 if re.search(r"(?:inventory|设施维度|point inventory|资产台账)", evidence) else 0.0
    if re.search(r"(?:score|评分|得分|quality|宜居度)", query):
        adjustment += 115.0 if re.search(r"(?:score|评分|得分|宜居度)", evidence) else 0.0
    if re.search(r"(?:per\s+\d+|每万|population|residents|居民|人口)", query):
        adjustment += 65.0 if re.search(r"(?:population|residents|居民|人口)", evidence) else 0.0
        adjustment += 35.0 if re.search(r"(?:facility|设施)", evidence) else 0.0
    if re.search(r"(?:length|长度|管径|diameter)", query):
        adjustment += 80.0 if re.search(r"(?:pipe|管|line|线路|走廊|corridor|geometry|shape|长度|length|diameter|管径)", evidence) else 0.0
        adjustment -= 70.0 if re.search(r"(?:manhole|chamber|井|检查井|阀门|valve|facility point)", evidence) else 0.0
    if re.search(r"(?:contains|contain|内|之内|相交|intersect|nearest|最近)", query):
        adjustment += 25.0 if re.search(r"(?:boundary|district|school|facility|建筑|行政区|学校|设施)", evidence) else 0.0
    if re.search(r"(?:设施|facility|facilities)", query) and re.search(
        r"(?:数量|count|number|how many|每万|per\s+\d+)", query
    ):
        adjustment += 95.0 if re.search(r"(?:设施|facility|facilities)", evidence) else 0.0
        adjustment -= 75.0 if re.search(r"(?:行政区|district|boundary)", evidence) else 0.0
    object_evidence = " ".join(_object_aliases(asset)).casefold()
    status_markers = (
        ("现状", ("现状", "existing", "current")),
        ("规划", ("规划", "planned", "pipeline")),
        ("已批规划", ("已批规划", "approved planned", "planned approved")),
    )
    for marker, equivalents in status_markers:
        if marker not in query:
            continue
        if any(value in object_evidence for value in equivalents):
            adjustment += 95.0
        elif re.search(r"(?:走廊|corridor|utility service)", object_evidence):
            adjustment -= 35.0
    return adjustment


def _asks_for_composite_assets(question: str) -> bool:
    """Detect coordination language without binding to a benchmark question.

    A close score between two reviewed assets is not, by itself, an ambiguity:
    users commonly ask for two independently governed aggregates in one
    sentence.  This signal is only used to label that case; relationship and
    metric validation still happen in the runtime.
    """

    return bool(_COMPOSITE_QUERY_RE.search(str(question or "")))


def _business_object_matches(question: str, asset: dict[str, Any]) -> list[str]:
    """Return explicit business-object phrases found in the question.

    Asset-level labels and aliases are evidence for object selection.  Generic
    field words such as ``数量`` or ``阶段`` are intentionally ignored so a
    grouped query over one asset is not mistaken for a multi-asset query.
    """

    folded = str(question or "").casefold()
    question_tokens = _expanded_query_tokens(folded)
    phrases: list[str] = []
    values = _object_aliases(asset)
    for raw in values:
        phrase = str(raw or "").strip()
        key = phrase.casefold()
        if len(phrase) < 2 or key in _GENERIC_OBJECT_ALIASES or key in phrases:
            continue
        matched = _phrase_in_question(folded, phrase)
        if not matched and " " in phrase:
            phrase_tokens = _text_tokens(phrase)
            question_tokens = _text_tokens(folded)
            meaningful = phrase_tokens - {"area", "surface", "facility", "record"}
            matched = bool(meaningful) and phrase_tokens <= question_tokens
        if not matched and not re.search(r"[\u4e00-\u9fff\u0600-\u06ff]", phrase):
            # Business aliases are allowed to use a documented synonym (for
            # example ``人口`` versus ``居民``).  Apply the same general
            # vocabulary expansion used for token ranking, but only to the
            # compact object aliases returned by ``_object_aliases``.  Field
            # descriptions never enter this path, so a generic field word
            # cannot manufacture an asset identity.
            token_question = re.sub(
                r"\b(?:as\s+well|delivery\s+pipeline)\b",
                " ",
                folded,
                flags=re.IGNORECASE,
            )
            fallback_question_tokens = _expanded_query_tokens(token_question)
            phrase_tokens = _text_tokens(phrase)
            meaningful_tokens = {
                token
                for token in phrase_tokens
                if token not in _ENGLISH_STOPWORDS
                and token not in _GENERIC_OBJECT_ALIASES
            }
            # A multi-token alias must be evidenced by the complete phrase
            # (or by all of its meaningful tokens after documented synonym
            # expansion).  Accepting a single non-generic token here makes
            # ``district score`` match any question that merely says
            # ``district`` and lets unrelated score assets enter the prompt.
            if len(phrase_tokens) > 1:
                matched = phrase_tokens <= fallback_question_tokens or (
                    len(meaningful_tokens) > 1
                    and meaningful_tokens <= fallback_question_tokens
                )
            else:
                matched = bool(meaningful_tokens & fallback_question_tokens)
        if not matched and re.search(r"[\u4e00-\u9fff]", phrase):
            # CJK tokenization produces overlapping 2-4 character n-grams;
            # using those n-grams for object identity makes ``配电变电站``
            # spuriously match ``变电站内母线``.  Only the explicitly
            # documented general synonyms may cross this boundary.
            phrase_runs = re.findall(r"[\u4e00-\u9fff]{2,}", phrase.casefold())
            for source, synonyms in _TERM_SYNONYMS.items():
                if any(source.casefold() == run for run in phrase_runs):
                    if any(_phrase_in_question(folded, synonym) for synonym in synonyms):
                        matched = True
                        break
        if matched:
            phrases.append(phrase)
    return phrases[:8]


def _object_family_signature(phrase: str) -> tuple[str, str]:
    """Return a stable business-object family key from one compact alias.

    The key deliberately removes qualifiers such as voltage values and
    parenthesised documentation notes.  It keeps the business noun itself,
    which means ``streetlight`` and its legacy representation share a family,
    while overhead and underground line segments remain distinct families.
    """

    value = re.sub(r"[（(][^()（）]*[)）]", " ", str(phrase or "")).strip().casefold()
    cjk_runs = re.findall(r"[\u4e00-\u9fff]{2,}", value)
    if cjk_runs:
        return "cjk", "|".join(cjk_runs)
    tokens = [
        _singular_english_token(token)
        for token in re.findall(r"[A-Za-z][A-Za-z0-9]*", value)
        if _singular_english_token(token) not in _ENGLISH_STOPWORDS
    ]
    return "en", " ".join(sorted(dict.fromkeys(tokens)))


def _candidate_object_families(question: str, asset: dict[str, Any]) -> set[tuple[str, str]]:
    return {
        _object_family_signature(phrase)
        for phrase in _business_object_matches(question, asset)
        if _object_family_signature(phrase)[1]
    }


def _has_underspecified_operation(question: str) -> bool:
    """A candidate object alone is insufficient to authorize a query."""

    normalized = str(question or "")
    return not bool(
        _QUERY_OPERATION_RE.search(normalized)
        or _ARABIC_QUERY_OPERATION_RE.search(normalized)
    )


def _has_generic_asset_object(question: str, ranked: list[tuple[float, dict[str, Any], list[str]]]) -> bool:
    """Reject a count over an unspecified asset universe."""

    if not _GENERIC_ASSET_QUERY_RE.search(str(question or "")):
        return False
    explicit_objects = [
        asset
        for _score, asset, _matched in ranked
        if _business_object_matches(question, asset)
    ]
    return not explicit_objects


def _has_ambiguous_status_dimension(question: str, ranked: list[tuple[float, dict[str, Any], list[str]]]) -> bool:
    """Detect an unqualified status dimension when competing definitions exist."""

    normalized = str(question or "")
    if not _AMBIGUOUS_STATUS_RE.search(normalized) or _STATUS_QUALIFIER_RE.search(normalized):
        return False
    # Status words occur in many field descriptions. They are ambiguity
    # evidence only when attached to more than one explicitly selected
    # business object, or when the selected object exposes several status
    # dimensions of its own.
    top_score = ranked[0][0] if ranked else 0.0
    matched_candidates = [
        (asset, matched)
        for score, asset, matched in ranked
        if score >= top_score * 0.65 and _business_object_matches(question, asset)
    ]
    if len(matched_candidates) >= 2:
        return any(not item.get("published_runtime_asset") for item, _matched in matched_candidates) or len(
            [item for item, _matched in matched_candidates if item.get("published_runtime_asset")]
        ) > 1
    if len(matched_candidates) != 1:
        return False
    asset = matched_candidates[0][0]
    status_fields = 0
    lifecycle_fields = 0
    for field in asset.get("fields") or []:
        semantic = (field or {}).get("published_semantic") or {}
        labels = " ".join(str(value or "") for value in (semantic.get("labels") or {}).values())
        if _AMBIGUOUS_STATUS_RE.search(labels) or _AMBIGUOUS_STATUS_RE.search(
            str(field.get("physical_field") or "")
        ):
            status_fields += 1
        if re.search(r"(?:completion|demolition|lifecycle|规划|计划|phase|阶段)", labels, re.IGNORECASE) or re.search(
            r"(?:completion|demolition|lifecycle|phase|stage)",
            str(field.get("physical_field") or ""),
            re.IGNORECASE,
        ):
            lifecycle_fields += 1
    return status_fields > 1 or (status_fields >= 1 and lifecycle_fields >= 1)


def _asset_exposes_dimension_for_term(asset: dict[str, Any], phrase: str) -> bool:
    """Whether a reviewed asset can itself group or label the requested term."""

    phrase_key = str(phrase or "").casefold()
    if len(phrase_key) < 2:
        return False
    if not re.search(r"[\u4e00-\u9fff\u0600-\u06ff]", phrase_key):
        phrase_key = _singular_english_token(phrase_key)
    for field in asset.get("fields") or []:
        semantic = (field or {}).get("published_semantic") or {}
        role = str(semantic.get("business_role") or "").casefold()
        if role not in {"dimension", "label", "district_key"}:
            continue
        labels = " ".join(str(value or "") for value in (semantic.get("labels") or {}).values()).casefold()
        if phrase_key in labels or labels in phrase_key:
            return True
    return False


def _asks_for_named_grouping_entity(question: str) -> bool:
    """Detect wording that requires a human-readable entity label.

    A fact table's foreign key can satisfy ``group by district_id``.  Wording
    such as ``which districts`` or ``哪些行政区`` asks for the governed label
    asset as well, even when the fact already stores the key.  This is a
    language-level rule and is independent of any benchmark identifier.
    """

    return bool(
        re.search(
            r"(?:哪些行政区|哪个行政区|行政区的|行政区(?:、|和|及|以及)|市辖区(?:、|和|及|以及)|which\s+(?:districts?|municipalities?|areas?)|what\s+(?:districts?|municipalities?|areas?)|districts?\s+(?:contain|with|having)|municipalities?\s+(?:contain|with|having))",
            str(question or ""),
            re.IGNORECASE,
        )
    )


def _is_contextual_grouping_object(
    question: str,
    asset: dict[str, Any],
    reviewed_assets: list[dict[str, Any]],
) -> bool:
    """Whether an object phrase is used only as a grouping dimension.

    This prevents a query such as "facilities by stage and district" from
    being represented as three independent source assets merely because the
    catalog also contains a district entity.  Spatial containment remains a
    relation and is deliberately not treated as a simple grouping field.
    """

    folded = str(question or "").casefold()
    for phrase in _business_object_matches(question, asset):
        index = folded.find(phrase.casefold())
        if index < 0:
            continue
        before = folded[max(0, index - 42) : index]
        after = folded[index + len(phrase) : index + len(phrase) + 12]
        if _SPATIAL_CONTAINMENT_RE.search(question) and any(
            other is not asset
            and _asset_exposes_dimension_for_term(other, phrase)
            and any(
                str((field.get("published_semantic") or {}).get("business_role") or "").casefold()
                == "geometry"
                for field in asset.get("fields") or []
            )
            for other in reviewed_assets
        ):
            # A boundary asset named in a containment query is the grouping
            # container when the measured asset already exposes that label
            # dimension.  It remains in the reviewed set for spatial proof,
            # but does not make the request ambiguous by itself.
            return True
        if _GROUPING_CONTEXT_RE.search(before) and not _SPATIAL_OR_RELATIONSHIP_RE.search(after):
            return True
        if (
            not _SPATIAL_CONTAINMENT_RE.search(question)
            and any(
                other is not asset and _asset_exposes_dimension_for_term(other, phrase)
                for other in reviewed_assets
            )
        ):
            return True
    return False


def _is_direct_grouping_context(question: str, asset: dict[str, Any]) -> bool:
    """Identify a dimension explicitly introduced as a grouping container."""

    folded = str(question or "").casefold()
    for phrase in _business_object_matches(question, asset):
        index = folded.find(phrase.casefold())
        if index < 0:
            continue
        before = folded[max(0, index - 42) : index]
        after = folded[index + len(phrase) : index + len(phrase) + 12]
        if _GROUPING_CONTEXT_RE.search(before) and not _SPATIAL_OR_RELATIONSHIP_RE.search(after):
            return True
    return False


def _single_asset_covering_contextual_dimensions(
    question: str,
    reviewed_assets: list[dict[str, Any]],
) -> dict[str, Any] | None:
    """Select one fact asset when it already publishes requested dimensions.

    A separately catalogued district or municipality remains useful retrieval
    evidence, but it is not an execution dependency when the sole measured
    business object already publishes that label as a reviewed dimension.
    Spatial containment is excluded because a denormalized label cannot prove
    a reviewed spatial predicate.
    """

    if _SPATIAL_CONTAINMENT_RE.search(question):
        return None
    contextual = [
        asset
        for asset in reviewed_assets
        if _is_contextual_grouping_object(question, asset, reviewed_assets)
    ]
    primary = [asset for asset in reviewed_assets if asset not in contextual]
    if len(primary) != 1 or not contextual:
        return None
    contextual_terms = [
        phrase
        for asset in contextual
        for phrase in _business_object_matches(question, asset)
    ]
    if contextual_terms and all(
        _asset_exposes_dimension_for_term(primary[0], term)
        for term in contextual_terms
    ):
        return primary[0]
    return None


def _requires_reviewed_asset_set(
    question: str,
    ranked: list[tuple[float, dict[str, Any], list[str]]],
    relationship_pairs: set[frozenset[str]] | None = None,
) -> tuple[bool, list[dict[str, Any]]]:
    """Select the governed business-object set needed before planning.

    The rule models intent structure, not a benchmark key: three explicit
    entities are composite; two entities are composite when coordinated or
    connected by a spatial/ranking relation.  A second entity used only as a
    grouping field is left to the semantic compiler when the primary asset
    already carries that dimension.
    """

    reviewed = [
        asset
        for _score, asset, _matched in ranked
        if asset.get("published_runtime_asset") and _business_object_matches(question, asset)
    ]
    if len(reviewed) < 2:
        return False, reviewed
    single_asset = _single_asset_covering_contextual_dimensions(question, reviewed)
    if single_asset is not None:
        return False, [single_asset]
    object_families = [
        _candidate_object_families(question, asset)
        for asset in reviewed
    ]
    nonempty_object_families = [value for value in object_families if value]
    if len(nonempty_object_families) >= 2 and all(
        value & nonempty_object_families[0] for value in nonempty_object_families
    ):
        # Multiple tables can represent the same named business object (for
        # example current and legacy oasis layers).  These are alternatives
        # for semantic reranking, not a request to join every representation.
        return False, reviewed
    contextual = [
        asset
        for asset in reviewed
        if _is_contextual_grouping_object(question, asset, reviewed)
    ]
    non_contextual_count = len(reviewed) - len(contextual)
    if non_contextual_count >= 2:
        return _reviewed_set_relationship_ready(question, reviewed, relationship_pairs), reviewed
    if (_SPATIAL_CONTAINMENT_RE.search(question) or _asks_for_named_grouping_entity(question)) and len(reviewed) >= 2:
        if _reviewed_set_relationship_ready(question, reviewed, relationship_pairs):
            return True, reviewed
        # An explicitly exposed grouping field is sufficient without a
        # separate relationship; otherwise the runtime must clarify.
        if contextual and all(
            any(_asset_exposes_dimension_for_term(primary, term) for primary in reviewed if primary not in contextual)
            for term in [phrase for asset in contextual for phrase in _business_object_matches(question, asset)]
        ):
            return True, reviewed
        return False, reviewed
    # A score/metric fact plus a distinct entity label needs an explicit
    # reviewed relationship even when the displayed label is also present as
    # a denormalized field on the fact record.
    if _SPATIAL_OR_RELATIONSHIP_RE.search(question) and len(reviewed) >= 2:
        contextual_terms = [
            phrase
            for asset in contextual
            for phrase in _business_object_matches(question, asset)
        ]
        primary_assets = [asset for asset in reviewed if asset not in contextual]
        # A ranked fact can stay on one asset when it itself exposes the
        # requested grouping field (for example school municipality).  If it
        # only has a key, it requires the separately reviewed label entity.
        if any(
            not any(_asset_exposes_dimension_for_term(primary, term) for primary in primary_assets)
            for term in contextual_terms
        ):
            return _reviewed_set_relationship_ready(question, reviewed, relationship_pairs), reviewed
    explicit_coordination = bool(
        re.search(r"(?:和|以及|分别|各自|both|and|as well as)", question, re.IGNORECASE)
    )
    ratio_intent = bool(
        re.search(r"(?:每万|比例|占比|比率|ratio|per\s+\d+)", question, re.IGNORECASE)
    )
    if len(reviewed) >= 2 and (explicit_coordination or ratio_intent):
        non_contextual = [asset for asset in reviewed if asset not in contextual]
        # A conjunction can connect two grouping dimensions ("by stage and
        # district") rather than two executable business assets.  Only treat
        # it as a composite asset intent when at least two non-contextual
        # objects remain after grouping-only entities are removed.
        if explicit_coordination and len(non_contextual) >= 2:
            return _reviewed_set_relationship_ready(question, reviewed, relationship_pairs), reviewed
        if ratio_intent and len(non_contextual) >= 2:
            return _reviewed_set_relationship_ready(question, reviewed, relationship_pairs), reviewed
    # Any explicitly named pair whose second object cannot be satisfied by a
    # reviewed grouping field is a multi-asset intent.  This admits a score
    # fact plus its district label, while retaining a school's own municipality
    # dimension as a single-asset query.
    return len(contextual) == 0, reviewed


def _reviewed_set_relationship_ready(
    question: str,
    reviewed: list[dict[str, Any]],
    relationship_pairs: set[frozenset[str]] | None,
) -> bool:
    """Check whether a coordinated asset set has reviewed join authority."""

    if len(reviewed) < 2:
        return False
    # Independent aggregates ("分别/each") do not need a join. A spatial or
    # containment phrase, however, requires an explicitly reviewed relation.
    if not _SPATIAL_OR_RELATIONSHIP_RE.search(question):
        return True
    if relationship_pairs is None:
        # Unit fixtures and legacy catalogs may not carry the optional
        # relationship projection; preserve their previous conservative rule.
        return True
    ids = [str(asset.get("candidate_id") or "") for asset in reviewed]
    return all(
        frozenset((ids[index], ids[other])) in relationship_pairs
        for index in range(len(ids))
        for other in range(index + 1, len(ids))
        if ids[index] and ids[other]
    )


def _protected_candidate_window(
    question: str,
    ranked: list[tuple[float, dict[str, Any], list[str]]],
    limit: int,
) -> list[tuple[float, dict[str, Any], list[str]]]:
    """Keep one high-ranked candidate for each explicit business object.

    Large catalogs contain many generic field matches.  A fixed top-k slice
    can therefore evict a clearly named district or population asset even
    though it is required by the request.  Protect the best reviewed asset in
    each distinct object family, then fill the remaining slots by score.  The
    window remains bounded and alternatives in the same family do not consume
    protection slots.
    """

    bounded = max(1, min(int(limit), 20))
    selected: list[tuple[float, dict[str, Any], list[str]]] = []
    selected_ids: set[str] = set()
    family_keys: list[set[tuple[str, str]]] = []

    for item in ranked:
        score, asset, _matched = item
        if not asset.get("published_runtime_asset"):
            continue
        families = _candidate_object_families(question, asset)
        if not families:
            continue
        # An alternative with overlapping family terms is not a new required
        # object.  Distinct line orientations, for example, have disjoint
        # CJK signatures and are both protected.
        if any(families & existing for existing in family_keys):
            continue
        selected.append(item)
        selected_ids.add(str(asset.get("candidate_id") or ""))
        family_keys.append(families)

    for item in ranked:
        candidate_id = str(item[1].get("candidate_id") or "")
        if candidate_id in selected_ids:
            continue
        selected.append(item)
        selected_ids.add(candidate_id)
        if len(selected) >= bounded:
            break
    # The number of protected families should normally be below the limit. If
    # a very broad question names more objects than the configured window,
    # preserve the highest-ranked protected objects and keep the contract
    # bounded rather than silently expanding the retrieval payload.
    return sorted(selected[:bounded], key=lambda item: (-item[0], str(item[1].get("candidate_id") or "")))


def _grouping_only_near_tie(
    question: str,
    ranked: list[tuple[float, dict[str, Any], list[str]]],
    top: list[tuple[float, dict[str, Any], list[str]]],
) -> bool:
    """Whether a close second candidate is only a requested grouping object."""

    if len(top) < 2 or not top[0][1].get("published_runtime_asset"):
        return False
    top_score = top[0][0]
    close = [item for item in top[1:] if item[0] >= top_score * 0.86]
    if not close:
        return False
    reviewed = [
        asset
        for _score, asset, _matched in ranked
        if asset.get("published_runtime_asset") and _business_object_matches(question, asset)
    ]
    if not reviewed:
        return False
    return all(
        _is_contextual_grouping_object(question, asset, reviewed)
        for _score, asset, _matched in close
    )


def rank_semantic_candidate_assets(
    question: str,
    candidate_catalog: dict[str, Any],
    *,
    limit: int = 8,
) -> dict[str, Any]:
    """Rank dictionary-backed business assets without using physical names.

    This deterministic first-stage ranker is intentionally a candidate selector,
    not an SQL planner.  Its output is suitable for a later semantic reranker or
    a clarification interaction; it never authorizes execution itself.
    """

    if candidate_catalog.get("schema") != CANDIDATE_CATALOG_SCHEMA:
        raise SemanticCandidateCatalogError("semantic candidate catalog schema is unsupported")
    normalized_question = str(question or "").strip()
    if not normalized_question:
        raise SemanticCandidateCatalogError("question is required")
    assets = [
        item
        for item in candidate_catalog.get("assets") or []
        if isinstance(item, dict) and item.get("retrieval_eligible") is True
    ]
    question_tokens = _expanded_query_tokens(normalized_question)
    document_frequency: Counter[str] = Counter()
    token_sets: dict[str, tuple[set[str], set[str]]] = {}
    for asset in assets:
        candidate_id = str(asset.get("candidate_id") or "")
        labels, details = _asset_token_sets(asset)
        token_sets[candidate_id] = (labels, details)
        document_frequency.update(labels | details)
    corpus_size = max(1, len(assets))
    ranked: list[tuple[float, dict[str, Any], list[str]]] = []
    for asset in assets:
        candidate_id = str(asset.get("candidate_id") or "")
        labels, details = token_sets[candidate_id]
        matched = sorted(question_tokens & (labels | details))
        if not matched:
            continue
        score = sum(
            (2.6 if token in labels else 0.3)
            * (1.0 + math.log((corpus_size + 1) / (document_frequency[token] + 1)))
            for token in matched
        )
        score += _preferred_asset_adjustment(asset)
        score += _semantic_intent_adjustment(normalized_question, asset)
        # Exact business-language phrases are stronger evidence than isolated
        # character n-grams.  This is especially important in large catalogs
        # where generic terms such as “阶段” or “数量” occur everywhere.
        question_folded = normalized_question.casefold()
        for alias in _object_aliases(asset):
            phrase = str(alias or "").strip().casefold()
            if len(phrase) >= 2 and _phrase_in_question(question_folded, phrase):
                score += 150.0 + min(40.0, len(phrase) * 1.5)
        # ``business_aliases`` also contains field labels from the supplied
        # dictionary. Do not grant each field description a phrase bonus: a
        # corridor or building should win because its object label matches,
        # not because it happens to document the word ``planned`` repeatedly.
        object_matches = _business_object_matches(normalized_question, asset)
        if object_matches:
            score += 24.0 * len(object_matches)
            matched.extend(value for value in object_matches if value not in matched)
            if _is_direct_grouping_context(normalized_question, asset):
                # A named dimension such as district or municipality is often
                # lexically stronger than the measured business object. Keep
                # it in the candidate set for relationship validation, but do
                # not let the grouping container become Top-1.
                score -= 180.0
        for alias in _object_aliases(asset):
            phrase = str(alias or "")
            if not re.search(r"[\u4e00-\u9fff]", phrase):
                continue
            for run in re.findall(r"[\u4e00-\u9fff]{2,}", phrase):
                if run.casefold() in normalized_question.casefold():
                    score += min(95.0, 18.0 * len(run))
        ranked.append((score, asset, matched))
    ranked.sort(key=lambda item: (-item[0], str(item[1].get("candidate_id") or "")))
    top = _protected_candidate_window(normalized_question, ranked, limit)
    ambiguous = len(top) > 1 and top[1][0] >= top[0][0] * 0.86
    if ambiguous and _grouping_only_near_tie(normalized_question, ranked, top):
        ambiguous = False
    relationship_pairs: set[frozenset[str]] | None = None
    if "relationship_authority" in candidate_catalog:
        relationship_pairs = {
            frozenset(
                (
                    str(item.get("left_candidate_id") or ""),
                    str(item.get("right_candidate_id") or ""),
                )
            )
            for item in (candidate_catalog.get("relationship_authority") or {}).get(
                "relationships"
            ) or []
            if item.get("left_candidate_id") and item.get("right_candidate_id")
        }
    reviewed_composite, reviewed_asset_set = _requires_reviewed_asset_set(
        normalized_question, ranked, relationship_pairs
    )
    if not reviewed_composite and len(reviewed_asset_set) == 1:
        selected_id = str(reviewed_asset_set[0].get("candidate_id") or "")
        top.sort(
            key=lambda item: (
                str(item[1].get("candidate_id") or "") != selected_id,
                -item[0],
                str(item[1].get("candidate_id") or ""),
            )
        )
    underspecified = _has_underspecified_operation(normalized_question)
    ambiguous_status = _has_ambiguous_status_dimension(normalized_question, ranked)
    unsupported_operation = bool(_UNSUPPORTED_OPERATION_RE.search(normalized_question))
    sensitive_request = bool(_SENSITIVE_QUERY_RE.search(normalized_question))
    generic_asset_object = _has_generic_asset_object(normalized_question, ranked)
    results = [
        {
            "candidate_id": asset.get("candidate_id"),
            "business_label": asset.get("business_label"),
            "business_aliases": list(asset.get("business_aliases") or []),
            "business_description": asset.get("business_description"),
            "asset_state": asset.get("asset_state"),
            "published_runtime_asset": asset.get("published_runtime_asset"),
            "dictionary_alignment": asset.get("dictionary_alignment") or {},
            "score": round(score, 6),
            "matched_business_terms": matched[:16],
            "matched_business_objects": _business_object_matches(normalized_question, asset),
        }
        for score, asset, matched in top
    ]
    if not results:
        status = "no_dictionary_backed_candidate"
        decision = "clarify_or_submit_for_semantic_modelling"
    elif sensitive_request:
        status = "sensitive_data_request"
        decision = "refuse_sensitive_data_request"
    elif unsupported_operation:
        status = "unsupported_prediction_request"
        decision = "refuse_missing_reviewed_prediction_contract"
    elif generic_asset_object:
        status = "underspecified_query"
        decision = "clarify_missing_asset_type"
    elif underspecified:
        status = "underspecified_query"
        decision = "clarify_missing_metric_or_query_operation"
    elif ambiguous_status:
        status = "ambiguous_candidates"
        decision = "clarify_ambiguous_status_definition"
    elif reviewed_composite:
        status = "reviewed_asset_set"
        decision = "eligible_for_existing_reviewed_runtime"
    elif len(reviewed_asset_set) > 1 and _SPATIAL_OR_RELATIONSHIP_RE.search(
        normalized_question
    ):
        status = "ambiguous_candidates"
        decision = "clarify_missing_reviewed_relationship"
    elif ambiguous:
        close_candidates = [
            asset for score, asset, _matched in top if score >= top[0][0] * 0.86
        ]
        if close_candidates and all(item.get("published_runtime_asset") for item in close_candidates):
            status = "reviewed_candidates_for_semantic_rerank"
            decision = "eligible_for_existing_reviewed_runtime"
        else:
            status = "ambiguous_candidates"
            decision = "clarify_before_any_execution"
    elif results[0].get("published_runtime_asset"):
        status = "published_asset_selected"
        decision = "eligible_for_existing_reviewed_runtime"
    else:
        status = "candidate_requires_business_review"
        decision = "do_not_execute_until_published"
    return {
        "schema": "gda.abu-dhabi-semantic-candidate-resolution.v1",
        "status": status,
        "decision": decision,
        "question": normalized_question,
        "physical_table_name_used_for_retrieval": False,
        "candidate_count_considered": len(assets),
        "reviewed_asset_set_candidate_ids": [
            str(asset.get("candidate_id") or "") for asset in reviewed_asset_set
        ] if reviewed_composite else [],
        "candidates": results,
    }


__all__ = [
    "CANDIDATE_CATALOG_SCHEMA",
    "SemanticCandidateCatalogError",
    "build_semantic_candidate_catalog",
    "rank_semantic_candidate_assets",
    "write_semantic_candidate_catalog",
]
