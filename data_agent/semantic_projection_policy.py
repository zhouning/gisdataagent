"""Reviewed, configuration-driven projection completeness policies.

Some business phrases name a governed field collection rather than one
column.  For example, ``all domain scores`` means every member of the
published domain-score family.  This module resolves those phrases from the
semantic layer only.  It deliberately has no benchmark, Gold SQL, model, or
database dependency so the same policy can be used by the baseline SQL AST
route and the typed SemanticQueryIR compiler without evaluation leakage.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable, Mapping
from functools import lru_cache
from typing import Any


SUPPORTED_LANGUAGES = ("zh", "en", "ar")
ALLOWED_PROJECTION_ROLES = {"attribute", "dimension"}


def question_is_entity_list(question: str, language: str) -> bool:
    """Return whether wording requests a set/list of entities.

    This is intentionally a small language-level classifier.  It does not
    name a table, field, benchmark case, or expected answer; the selected
    semantic display policy still decides which label is eligible.
    """

    normalized = " ".join(str(question or "").casefold().split())
    patterns = {
        "en": r"(?:\bwhich\b|\blist\b|\bidentify\b|\bshow\b|\bname\b|\bwhat\b)",
        "zh": r"(?:哪些|列出|列举|找出|识别|显示|展示|名称)",
        "ar": r"(?:ما هي|اذكر|قائمة|حدد|اعرض|اسم)",
    }
    return bool(re.search(patterns.get(language, patterns["en"]), normalized))


def question_requests_explicit_attributes(question: str, language: str) -> bool:
    """Return whether the user explicitly asks to display attributes.

    Conditions used to select entities (for example ``zero existing`` or
    ``needed > 0``) are not display requests.  The gate therefore looks for
    display verbs/question forms coupled with an attribute noun, or explicit
    ``their/each`` attribute wording.  If uncertain it returns ``False`` only
    for the narrowly recognized entity-list form; callers fail open when the
    query is not a simple list.
    """

    normalized = " ".join(str(question or "").casefold().split())
    patterns = {
        "en":
            r"(?:\b(?:show|display|return|include|provide|give)\b[^.]{0,100}"
            r"\b(?:score|count|value|target|need|municipality|attribute|field|metric|detail|column)\b)"
            r"|(?:\b(?:what are|what is|their|each)\b[^.]{0,100}"
            r"\b(?:score|count|value|target|need|municipality|attribute|field|metric|detail|column)\b)"
            # Ranking/comparison wording makes the ordered measure part of
            # the requested result even when the user does not say "show".
            # Keep this language-level and field-agnostic: the governed
            # semantic layer still decides which projection is valid.
            r"|(?:\b(?:highest|lowest|top|bottom|largest|smallest|most|least)\b[^.]{0,100}"
            r"\b(?:score|scores|count|counts|value|values|rate|rates|completion|coverage|"
            r"capacity|demand|need|needs|gap|fpp|fc|qa|qol|ic|incident|incidents)\b)"
            # Collection requests such as "list all domain scores" are
            # explicit attribute requests, not entity-only listings.
            r"|(?:\b(?:all|every|complete|full)\b[^.]{0,80}"
            r"\b(?:domain\s+scores?|scores?|rates?|completion|coverage|metrics?)\b)",
        "zh":
            r"(?:显示|展示|返回|包括|提供|给出)[^。.!?]{0,80}"
            r"(?:得分|数量|数值|目标|缺口|市政|属性|字段|指标|明细|列)"
            r"|(?:它们的|各自|每个)[^。.!?]{0,80}(?:得分|数量|数值|目标|缺口|属性|字段|指标|明细)",
        "ar":
            r"(?:اعرض|إظهار|أعد|تضمين|قدم)[^.]{0,100}"
            r"(?:درجة|درجات|عدد|قيمة|هدف|فجوة|بلدية|سمة|حقل|مؤشر|تفاصيل|عمود)"
            r"|(?:قيمهم|كل|لكل)[^.]{0,100}(?:درجة|عدد|قيمة|هدف|فجوة|سمة|حقل|مؤشر|تفاصيل)",
    }
    return bool(re.search(patterns.get(language, patterns["en"]), normalized))


class ProjectionCompletenessPolicyError(ValueError):
    """A persisted projection policy is invalid or unsafe to execute."""


@lru_cache(maxsize=8192)
def _normalized_match_text(value: str) -> str:
    value = unicodedata.normalize("NFKC", str(value or ""))
    value = "".join(
        character for character in value if unicodedata.category(character) != "Mn"
    )
    return " ".join(
        "".join(
            character.casefold()
            if character.isalnum() or character.isspace()
            else " "
            for character in value
        ).split()
    )


def _contains_match_term(question: str, term: str) -> bool:
    normalized_question = _normalized_match_text(question)
    normalized_term = _normalized_match_text(term)
    if not normalized_term:
        return False
    if normalized_term.isascii():
        pattern = (
            r"(?<![A-Za-z0-9_$])"
            + re.escape(normalized_term).replace(r"\ ", r"\s+")
            + r"(?![A-Za-z0-9_$])"
        )
        return re.search(pattern, normalized_question) is not None
    return normalized_term in normalized_question


def _normalized_table(value: Any) -> str:
    return str(value or "").strip().casefold()


def validate_projection_completeness_policies(
    semantic_layer: Mapping[str, Any],
) -> None:
    """Validate every published field collection against active bindings."""

    raw_policies = semantic_layer.get("projection_completeness_policies") or []
    if not isinstance(raw_policies, list):
        raise ProjectionCompletenessPolicyError(
            "projection_completeness_policies_invalid"
        )
    bindings_by_table = {
        _normalized_table(item.get("physical_table")): item
        for item in semantic_layer.get("table_bindings") or []
        if isinstance(item, Mapping) and _normalized_table(item.get("physical_table"))
    }
    seen_policy_ids: set[str] = set()
    for policy in raw_policies:
        if not isinstance(policy, Mapping):
            raise ProjectionCompletenessPolicyError(
                "projection_completeness_policy_invalid"
            )
        policy_id = str(policy.get("policy_id") or "").strip()
        if not policy_id or policy_id in seen_policy_ids:
            raise ProjectionCompletenessPolicyError(
                "projection_completeness_policy_id_invalid"
            )
        seen_policy_ids.add(policy_id)
        if policy.get("review_status") != "reviewed":
            raise ProjectionCompletenessPolicyError(
                f"projection_completeness_policy_review_invalid:{policy_id}"
            )
        if policy.get("operation") != "detail_projection":
            raise ProjectionCompletenessPolicyError(
                f"projection_completeness_policy_operation_invalid:{policy_id}"
            )
        physical_table = _normalized_table(policy.get("physical_table"))
        semantic_entity = str(policy.get("semantic_entity") or "").strip()
        binding = bindings_by_table.get(physical_table)
        if (
            binding is None
            or not semantic_entity
            or str(binding.get("semantic_entity") or "") != semantic_entity
            or binding.get("execution_eligible") is not True
        ):
            raise ProjectionCompletenessPolicyError(
                f"projection_completeness_policy_binding_invalid:{policy_id}"
            )

        match = policy.get("match") or {}
        term_groups = match.get("required_term_groups") or {}
        if not isinstance(term_groups, Mapping):
            raise ProjectionCompletenessPolicyError(
                f"projection_completeness_policy_match_invalid:{policy_id}"
            )
        for language in SUPPORTED_LANGUAGES:
            groups = term_groups.get(language) or []
            if (
                not isinstance(groups, list)
                or not groups
                or any(
                    not isinstance(group, list)
                    or not group
                    or any(not str(term).strip() for term in group)
                    for group in groups
                )
            ):
                raise ProjectionCompletenessPolicyError(
                    f"projection_completeness_policy_match_invalid:{policy_id}:{language}"
                )
        forbidden_terms = match.get("forbidden_terms") or {}
        if not isinstance(forbidden_terms, Mapping):
            raise ProjectionCompletenessPolicyError(
                f"projection_completeness_policy_match_invalid:{policy_id}"
            )
        for language, terms in forbidden_terms.items():
            if (
                language not in SUPPORTED_LANGUAGES
                or not isinstance(terms, list)
                or any(not str(term).strip() for term in terms)
            ):
                raise ProjectionCompletenessPolicyError(
                    f"projection_completeness_policy_match_invalid:{policy_id}:{language}"
                )

        available_fields = {
            str(item.get("semantic_field") or ""): str(
                item.get("physical_field") or ""
            )
            for item in binding.get("fields") or []
            if isinstance(item, Mapping)
            and str(item.get("semantic_field") or "").strip()
            and str(item.get("physical_field") or "").strip()
        }
        required_fields = policy.get("required_fields") or []
        if (
            not isinstance(required_fields, list)
            or not 2 <= len(required_fields) <= 32
        ):
            raise ProjectionCompletenessPolicyError(
                f"projection_completeness_policy_fields_invalid:{policy_id}"
            )
        seen_semantic_fields: set[str] = set()
        seen_output_names: set[str] = set()
        for field in required_fields:
            if not isinstance(field, Mapping):
                raise ProjectionCompletenessPolicyError(
                    f"projection_completeness_policy_field_invalid:{policy_id}"
                )
            semantic_field = str(field.get("semantic_field") or "").strip()
            physical_field = str(field.get("physical_field") or "").strip()
            output_name = str(field.get("output_name") or semantic_field).strip()
            role = str(field.get("role") or "attribute").strip().casefold()
            if (
                not semantic_field
                or available_fields.get(semantic_field) != physical_field
                or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*", output_name)
                or role not in ALLOWED_PROJECTION_ROLES
                or semantic_field.casefold() in seen_semantic_fields
                or output_name.casefold() in seen_output_names
            ):
                raise ProjectionCompletenessPolicyError(
                    f"projection_completeness_policy_field_invalid:{policy_id}:{semantic_field}"
                )
            seen_semantic_fields.add(semantic_field.casefold())
            seen_output_names.add(output_name.casefold())


def policy_matches_question(
    policy: Mapping[str, Any],
    *,
    question: str,
    language: str,
) -> bool:
    """Return whether a reviewed collection phrase is explicitly requested."""

    match = policy.get("match") or {}
    groups = (match.get("required_term_groups") or {}).get(language) or []
    if not groups or not all(
        any(_contains_match_term(question, str(term)) for term in group)
        for group in groups
    ):
        return False
    forbidden = (match.get("forbidden_terms") or {}).get(language) or []
    return not any(_contains_match_term(question, str(term)) for term in forbidden)


def resolve_projection_completeness_policies(
    *,
    question: str,
    language: str,
    semantic_layer: Mapping[str, Any],
    physical_tables: Iterable[str] = (),
    semantic_entities: Iterable[str] = (),
) -> tuple[Mapping[str, Any], ...]:
    """Resolve reviewed policies within the already selected query scope."""

    if language not in SUPPORTED_LANGUAGES:
        return ()
    normalized_tables = {_normalized_table(value) for value in physical_tables}
    normalized_entities = {str(value).strip() for value in semantic_entities}
    matches: list[Mapping[str, Any]] = []
    for policy in semantic_layer.get("projection_completeness_policies") or []:
        if not isinstance(policy, Mapping) or policy.get("review_status") != "reviewed":
            continue
        table_match = (
            not normalized_tables
            or _normalized_table(policy.get("physical_table")) in normalized_tables
        )
        entity_match = (
            not normalized_entities
            or str(policy.get("semantic_entity") or "") in normalized_entities
        )
        if (
            table_match
            and entity_match
            and policy_matches_question(
                policy,
                question=question,
                language=language,
            )
        ):
            matches.append(policy)
    return tuple(matches)


__all__ = [
    "ProjectionCompletenessPolicyError",
    "policy_matches_question",
    "question_is_entity_list",
    "question_requests_explicit_attributes",
    "resolve_projection_completeness_policies",
    "validate_projection_completeness_policies",
]
