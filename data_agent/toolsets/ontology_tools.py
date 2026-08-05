"""Read-only Cognitive Runtime tools backed by the governed ontology service."""

from __future__ import annotations

import json
from typing import Any

from google.adk.tools import FunctionTool, ToolContext
from google.adk.tools.base_toolset import BaseToolset

from ..ontology import get_ontology_service
from ..ontology.query_contracts import OntologyQueryPlan, OntologyQueryType


def _result(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)


def discover_ontology_concepts(
    query: str,
    domain_id: str = "",
    concept_kinds: list[str] | None = None,
    limit: int = 20,
) -> str:
    """Search governed ontology concepts by code, Chinese label, alias or EA GUID.

    Args:
        query: Exact code, label, alias, package fragment or EA GUID.
        domain_id: Optional one-map domain number, for example 02 or 06.
        concept_kinds: Optional kinds such as FeatureType, ValueDomain,
            ValueDomainMember, and DatasetSchema.
        limit: Maximum candidates, capped by the semantic query gateway.
    """
    service = get_ontology_service()
    payload = service.search_concepts(
        query=query,
        domain_id=domain_id.strip() or None,
        kinds=set(concept_kinds or []) or None,
        limit=limit,
    )
    return _result(
        {
            "ontology_version": service.reader.manifest.semantic_version,
            "content_sha256": service.reader.manifest.content_sha256,
            **payload,
        }
    )


def resolve_ontology_concept(concept_id: str) -> str:
    """Resolve one stable ontology ID with provenance and field/relation counts."""
    service = get_ontology_service()
    concept = service.get_concept(concept_id)
    if concept is None:
        return _result({"status": "not_found", "concept_id": concept_id})
    return _result(
        {
            "status": "resolved",
            "ontology_version": service.reader.manifest.semantic_version,
            "content_sha256": service.reader.manifest.content_sha256,
            "concept": concept,
        }
    )


def traverse_ontology_relationships(
    concept_id: str,
    direction: str = "both",
    limit: int = 100,
) -> str:
    """Traverse a bounded set of incoming/outgoing governed ontology relations."""
    service = get_ontology_service()
    payload = service.get_relations(concept_id, direction=direction, limit=limit)
    return _result(
        {
            "ontology_version": service.reader.manifest.semantic_version,
            "root_concept_id": concept_id,
            **payload,
        }
    )


def align_schema_to_ontology(fields: list[dict[str, Any]], domain_id: str = "") -> str:
    """Generate deterministic field candidates without publishing mappings.

    Args:
        fields: Objects with name/code and optional label/datatype.
        domain_id: Optional one-map domain number used to constrain candidates.
    """
    return _result(
        get_ontology_service().align_fields(
            fields,
            domain_id=domain_id.strip() or None,
        )
    )


def validate_ontology_binding(concept_id: str, field_codes: list[str]) -> str:
    """Validate that a concept exists and report required/missing/unknown fields."""
    service = get_ontology_service()
    concept = service.get_concept(concept_id)
    if concept is None:
        return _result({"valid": False, "reason": "concept_not_found", "concept_id": concept_id})
    properties = service.get_properties(concept_id, limit=service.MAX_PROPERTY_LIMIT)["items"]
    by_code = {str(prop.get("code") or "").casefold(): prop for prop in properties}
    supplied = {str(code).strip().casefold() for code in field_codes if str(code).strip()}
    required = {code for code, prop in by_code.items() if int(prop.get("min_count") or 0) > 0}
    return _result(
        {
            "valid": required.issubset(supplied),
            "concept_id": concept_id,
            "ontology_version": service.reader.manifest.semantic_version,
            "missing_required": sorted(required - supplied),
            "unknown_fields": sorted(supplied - set(by_code)),
            "recognized_fields": sorted(supplied & set(by_code)),
            "validation_scope": "schema_presence_only",
        }
    )


def query_ontology(
    query_type: str,
    subject: str = "",
    target: str = "",
    field_codes: list[str] | None = None,
    domain_id: str = "",
    depth: int = 2,
    limit: int = 50,
    tool_context: ToolContext | None = None,
) -> str:
    """Run one typed, read-only ontology analysis without accepting raw SQL/SPARQL.

    Args:
        query_type: One of concept_explanation, hierarchy, relation_path,
            transition_rules, or schema_mapping.
        subject: Stable concept ID, exact code, Chinese label, or alias. For
            transition_rules this may be a transition process (建设占用), a
            land class (农用地/耕地), or a land-use state class.
        target: Target concept for relation_path, or the requested target land
            class/state for transition_rules (for example 建设用地).
        field_codes: Dataset field codes for schema_mapping only.
        domain_id: Optional two-digit one-map domain identifier.
        depth: Maximum relationship traversal depth, capped at four.
        limit: Maximum returned records, capped at one hundred.
    """
    if tool_context is not None:
        tool_context.actions.skip_summarization = True
    try:
        plan = OntologyQueryPlan(
            query_type=OntologyQueryType(query_type),
            subject=subject,
            target=target,
            field_codes=field_codes or [],
            domain_id=domain_id.strip() or None,
            depth=depth,
            limit=limit,
        )
        return _result(get_ontology_service().execute_query(plan))
    except (ValueError, TypeError) as exc:
        return _result(
            {
                "status": "invalid_plan",
                "error": str(exc),
                "allowed_query_types": [
                    item.value
                    for item in OntologyQueryType
                    if item != OntologyQueryType.DEMO_SCENARIO_ANALYSIS
                ],
            }
        )


def run_ontology_application_scenario(
    scenario_id: str = "heping_review",
    tool_context: ToolContext | None = None,
) -> str:
    """Run a version-locked natural-resource ontology customer scenario.

    Args:
        scenario_id: heping_review for parcel compliance/evidence analysis, or
            banzhu_adjustment for agricultural structure adjustment analysis.
    """
    if tool_context is not None:
        tool_context.actions.skip_summarization = True
    try:
        plan = OntologyQueryPlan(
            query_type=OntologyQueryType.DEMO_SCENARIO_ANALYSIS,
            scenario_id=scenario_id,
            limit=50,
        )
        payload = get_ontology_service().execute_query(plan)
        result = payload.get("result") or {}
        map_update = result.pop("map_update", None) or {}
        layers = map_update.get("layers") or []
        result["map_update_summary"] = {
            "layer_count": len(layers),
            "layer_names": [str(layer.get("name") or "") for layer in layers],
            "scenario_id": scenario_id,
        }
        return _result(payload)
    except (KeyError, ValueError, TypeError) as exc:
        return _result(
            {
                "status": "invalid_plan",
                "error": str(exc),
                "allowed_scenarios": ["heping_review", "banzhu_adjustment"],
            }
        )


class OntologyToolset(BaseToolset):
    """Governed natural-resource ontology discovery and validation tools."""

    name = "OntologyToolset"
    description = "自然资源本体概念发现、关系遍历、字段对齐与约束检查"
    category = "domain_standards"

    def __init__(self, tool_filter=None):
        super().__init__(tool_filter=tool_filter)

    async def get_tools(self, readonly_context=None):
        tools = [
            FunctionTool(function)
            for function in (
                discover_ontology_concepts,
                resolve_ontology_concept,
                traverse_ontology_relationships,
                align_schema_to_ontology,
                validate_ontology_binding,
                query_ontology,
                run_ontology_application_scenario,
            )
        ]
        if self.tool_filter:
            if callable(self.tool_filter):
                tools = [tool for tool in tools if self.tool_filter(tool, readonly_context)]
            else:
                allowed = set(self.tool_filter)
                tools = [tool for tool in tools if tool.name in allowed]
        return tools
