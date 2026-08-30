"""Offline semantic coverage and arbitrary-query readiness audit.

The technical catalog is intentionally larger than the executable business
semantic layer.  This module keeps those two notions separate and produces a
stable, JSON-serialisable report that can be consumed by release tooling or a
product console.  It only reads frozen metadata artifacts; it never connects
to a source database and never loads Gold SQL/result payloads.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

SCENARIO_CLASSES = (
    "single_table_total_count",
    "single_table_grouped_summary",
    "single_table_average",
    "single_table_derived_metric",
    "single_table_ranking",
    "multi_table_equality_join",
    "multi_table_spatial_join",
    "safety_refusal",
)

CAPABILITY_CLASSES = (
    "count",
    "group_by",
    "filter",
    "detail",
    "sum",
    "average",
    "ranking",
    "derived_metric",
    "unit_conversion",
    "area",
    "spatial_predicate",
    "spatial_distance",
    "equality_join",
    "spatial_join",
    "safety_refusal",
)

SOURCE_ARTIFACTS: dict[str, dict[str, str]] = {
    "liveability": {
        "prefix": "liveability_data_20260730",
        "label": "Liveability",
    },
    "makani": {
        "prefix": "makani_sync_full",
        "label": "Makani",
    },
}


def _first_existing(artifact_root: Path, *names: str) -> Path:
    """Resolve a source-bound artifact, retaining versioned-file compatibility.

    Runtime publication uses date-free/current aliases in its checksum-verified
    manifest, while older readiness fixtures use immutable v4 filenames.  The
    audit must inspect the same current source snapshot as the product when an
    alias is available, and only fall back to the historical name for fixtures
    or pre-registry installations.
    """

    for name in names:
        path = artifact_root / name
        if path.is_file():
            return path
    return artifact_root / names[-1]


def _load(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"artifact_object_required:{path.name}")
    return payload


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _relative(path: Path, root: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()


def _reviewed(value: Any) -> bool:
    return str(value or "").casefold().startswith("reviewed")


def _table_name(value: Any) -> str:
    return str(value or "").strip()


def _asset_tables(assets: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for asset in assets:
        if not isinstance(asset, dict) or not _reviewed(asset.get("review_status")):
            continue
        for table in asset.get("physical_tables") or []:
            table_name = _table_name(table)
            if table_name:
                result[table_name].append(asset)
    return dict(result)


def _field_role_counts(fields: list[dict[str, Any]]) -> dict[str, int]:
    counts = Counter(
        str(field.get("business_role") or "unassigned") for field in fields
    )
    return dict(sorted(counts.items()))


def _table_inventory(
    resources: dict[str, dict[str, Any]],
    bindings: dict[str, dict[str, Any]],
    asset_by_table: dict[str, list[dict[str, Any]]],
    concepts: dict[str, dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[str]]:
    rows: list[dict[str, Any]] = []
    errors: list[str] = []
    for table in sorted(resources):
        resource = resources[table]
        binding = bindings.get(table) or {}
        concept = concepts.get(table) or {}
        source_fields = {
            _table_name(field.get("physical_field"))
            for field in resource.get("fields") or []
            if _table_name(field.get("physical_field"))
        }
        configured_fields = {
            _table_name(field.get("physical_field"))
            for field in binding.get("fields") or []
            if _table_name(field.get("physical_field"))
        }
        assets = asset_by_table.get(table, [])
        business_fields = [
            field
            for asset in assets
            for field in asset.get("fields") or []
            if isinstance(field, dict) and _table_name(field.get("physical_field"))
        ]
        status = _table_name(binding.get("binding_status"))
        if status.startswith("excluded"):
            tier = "excluded"
        elif binding.get("execution_eligible") is True and assets:
            tier = "reviewed_executable"
        else:
            tier = "technical_metadata_only"
        if binding.get("execution_eligible") is True and not assets:
            errors.append(f"execution_binding_without_reviewed_asset:{table}")
        if source_fields != configured_fields:
            errors.append(f"technical_field_binding_incomplete:{table}")
        rows.append(
            {
                "physical_table": table,
                "tier": tier,
                "binding_status": status or None,
                "execution_eligible": binding.get("execution_eligible") is True,
                "retrieval_eligible": binding.get("retrieval_eligible") is True,
                "concept_runtime_status": concept.get("runtime_status"),
                "technical_field_count": len(source_fields),
                "configured_field_count": len(configured_fields),
                "business_field_count": len({
                    _table_name(field.get("physical_field")) for field in business_fields
                }),
                "business_field_role_counts": _field_role_counts(business_fields),
                "business_fields_without_role": sorted(
                    {
                        _table_name(field.get("physical_field"))
                        for field in business_fields
                        if not _table_name(field.get("business_role"))
                    }
                ),
                "business_fields_without_labels": sorted(
                    {
                        _table_name(field.get("physical_field"))
                        for field in business_fields
                        if not isinstance(field.get("labels"), dict)
                        or not any(str(label).strip() for label in field.get("labels", {}).values())
                    }
                ),
                "reviewed_asset_ids": sorted(
                    _table_name(asset.get("asset_id"))
                    for asset in assets
                    if _table_name(asset.get("asset_id"))
                ),
                "primary_key": list(resource.get("primary_key") or []),
                "foreign_key_count": len(resource.get("foreign_keys") or []),
            }
        )
    return rows, errors


def _metric_coverage(
    metric_contracts: list[dict[str, Any]],
    table_rows: list[dict[str, Any]],
) -> dict[str, Any]:
    executable_tables = {
        row["physical_table"] for row in table_rows if row["tier"] == "reviewed_executable"
    }
    reviewed = [
        contract
        for contract in metric_contracts
        if _reviewed(contract.get("review_status"))
    ]
    executable: list[dict[str, Any]] = []
    missing_tables: dict[str, list[str]] = defaultdict(list)
    operation_counts = Counter()
    for contract in reviewed:
        tables = {
            _table_name(table)
            for table in contract.get("tables") or []
            if _table_name(table)
        }
        contract_id = _table_name(contract.get("contract_id"))
        operation_counts[_table_name(contract.get("operation")) or "unknown"] += 1
        if tables <= executable_tables:
            executable.append(contract)
        else:
            for table in sorted(tables - executable_tables):
                missing_tables[contract_id].append(table)
    return {
        "all_contract_count": len(metric_contracts),
        "reviewed_contract_count": len(reviewed),
        "executable_reviewed_contract_count": len(executable),
        "unreviewed_inventory_contract_count": len(metric_contracts) - len(reviewed),
        "operation_counts": dict(sorted(operation_counts.items())),
        "contracts_missing_executable_tables": {
            contract_id: tables for contract_id, tables in sorted(missing_tables.items())
        },
        "reviewed_contract_ids": sorted(
            _table_name(contract.get("contract_id"))
            for contract in reviewed
            if _table_name(contract.get("contract_id"))
        ),
    }


def _relationship_coverage(
    relationships: list[dict[str, Any]],
    relationship_candidates: list[dict[str, Any]],
    executable_tables: set[str],
) -> dict[str, Any]:
    reviewed = [relation for relation in relationships if _reviewed(relation.get("review_status"))]
    executable = []
    incomplete: list[str] = []
    kind_counts = Counter()
    for relation in reviewed:
        left = _table_name(relation.get("left"))
        right = _table_name(relation.get("right"))
        left_table = left.rsplit(".", 1)[0] if "." in left else ""
        right_table = right.rsplit(".", 1)[0] if "." in right else ""
        kind = _table_name(relation.get("kind")) or "unknown"
        kind_counts[kind] += 1
        if left_table in executable_tables and right_table in executable_tables:
            executable.append(relation)
        else:
            incomplete.append(
                f"{left}->{right}" if left and right else _table_name(relation.get("relation_id"))
            )
    candidate_status_counts = Counter(
        _table_name(item.get("review_status")) or "unknown"
        for item in relationship_candidates
    )
    return {
        "candidate_count": len(relationship_candidates),
        "candidate_review_status_counts": dict(sorted(candidate_status_counts.items())),
        "reviewed_relationship_count": len(reviewed),
        "executable_reviewed_relationship_count": len(executable),
        "reviewed_kind_counts": dict(sorted(kind_counts.items())),
        "reviewed_relationships_missing_executable_tables": sorted(incomplete),
        "relationship_review_complete": bool(reviewed)
        and len(reviewed) == len(relationship_candidates),
    }


def _benchmark_coverage(
    benchmark: dict[str, Any],
    executable_tables: set[str],
    reviewed_contract_ids: set[str],
) -> dict[str, Any]:
    cases = [case for case in benchmark.get("cases") or [] if isinstance(case, dict)]
    category_counts: Counter[str] = Counter()
    category_executable: Counter[str] = Counter()
    scenario_counts: Counter[str] = Counter()
    language_counts: Counter[str] = Counter()
    split_counts: Counter[str] = Counter()
    reviewed_business_holdout_case_count = 0
    for case in cases:
        expected = case.get("expected") or {}
        status = _table_name(expected.get("status"))
        intent_id = _table_name(case.get("semantic_intent_id"))
        contract_is_reviewed = not intent_id or intent_id in reviewed_contract_ids
        if status == "rejected" or _table_name(case.get("scenario_class")) == "safety_refusal":
            category = "safety"
        elif case.get("business_language_eligible") is True:
            category = (
                "business_reviewed"
                if contract_is_reviewed
                else "business_language_unreviewed"
            )
        elif status == "ok":
            category = "technical_catalog_control"
        else:
            category = "unsupported"
        category_counts[category] += 1
        scenario = _table_name(case.get("scenario_class")) or "unknown"
        scenario_counts[scenario] += 1
        language_counts[_table_name(case.get("language")) or "unknown"] += 1
        split = _table_name(case.get("split")) or "unknown"
        split_counts[split] += 1
        if category == "business_reviewed" and split == "holdout":
            reviewed_business_holdout_case_count += 1
        tables = {
            _table_name(table)
            for table in expected.get("tables") or []
            if _table_name(table)
        }
        if status == "rejected" or (tables <= executable_tables and contract_is_reviewed):
            category_executable[category] += 1
    return {
        "case_count": len(cases),
        "category_counts": dict(sorted(category_counts.items())),
        "executable_case_counts": dict(sorted(category_executable.items())),
        "scenario_counts": dict(sorted(scenario_counts.items())),
        "language_counts": dict(sorted(language_counts.items())),
        "split_counts": dict(sorted(split_counts.items())),
        "business_language_eligible_case_count": sum(
            category_counts[key]
            for key in ("business_reviewed", "business_language_unreviewed", "safety")
        ),
        "reviewed_business_case_count": category_counts["business_reviewed"],
        "business_language_unreviewed_case_count": category_counts[
            "business_language_unreviewed"
        ],
        "technical_catalog_control_case_count": category_counts["technical_catalog_control"],
        "safety_case_count": category_counts["safety"],
        "business_case_execution_eligible_count": category_executable["business_reviewed"],
        "reviewed_business_holdout_case_count": reviewed_business_holdout_case_count,
        "benchmark_claim_boundary": benchmark.get("claim_boundary") or {},
        "gold_isolation": (benchmark.get("evaluation_profile") or {}).get("isolation") or {},
    }


def _capability_coverage(
    assets: list[dict[str, Any]],
    metric_contracts: list[dict[str, Any]],
    relationships: list[dict[str, Any]],
    benchmark: dict[str, Any],
) -> dict[str, Any]:
    reviewed_assets = [asset for asset in assets if _reviewed(asset.get("review_status"))]
    asset_capabilities = Counter(
        _table_name(capability)
        for asset in reviewed_assets
        for capability in asset.get("capabilities") or []
        if _table_name(capability)
    )
    contract_capabilities: Counter[str] = Counter()
    for contract in metric_contracts:
        if not _reviewed(contract.get("review_status")):
            continue
        operation = _table_name(contract.get("operation"))
        if operation == "grouped_summary":
            contract_capabilities["group_by"] += 1
        if any(
            _table_name(metric.get("aggregate")) == "count"
            for metric in contract.get("metrics") or []
        ):
            contract_capabilities["count"] += 1
        for metric in contract.get("metrics") or []:
            aggregate = _table_name(metric.get("aggregate"))
            if aggregate in {"sum", "avg", "average", "max", "min", "count_distinct"}:
                contract_capabilities["average" if aggregate == "avg" else aggregate] += 1
    for relation in relationships:
        if not _reviewed(relation.get("review_status")):
            continue
        kind = _table_name(relation.get("kind"))
        if kind == "equality":
            contract_capabilities["equality_join"] += 1
        elif kind == "spatial":
            contract_capabilities["spatial_join"] += 1
    benchmark_capabilities = Counter(
        _table_name(capability)
        for case in benchmark.get("cases") or []
        for capability in case.get("capabilities") or []
        if _table_name(capability)
    )
    result: dict[str, Any] = {}
    for capability in CAPABILITY_CLASSES:
        result[capability] = {
            "reviewed_asset_count": int(asset_capabilities.get(capability, 0)),
            "reviewed_contract_or_relation_count": int(contract_capabilities.get(capability, 0)),
            "benchmark_case_count": int(benchmark_capabilities.get(capability, 0)),
            "present": bool(
                asset_capabilities.get(capability)
                or contract_capabilities.get(capability)
                or benchmark_capabilities.get(capability)
            ),
        }
    return result


def audit_source(source_key: str, artifact_root: Path) -> dict[str, Any]:
    """Audit one source using its frozen v4 full-coverage artifacts."""

    spec = SOURCE_ARTIFACTS.get(source_key)
    if spec is None:
        raise ValueError(f"unsupported_source:{source_key}")
    prefix = spec["prefix"]
    if source_key == "liveability":
        semantic_path = _first_existing(
            artifact_root,
            f"{prefix}_semantic_layer_current_20260826.json",
            f"{prefix}_semantic_layer_v4_full_coverage.json",
        )
        scenario_semantic_path = semantic_path
        ontology_path = _first_existing(
            artifact_root,
            f"{prefix}_ontology_current_20260826.json",
            f"{prefix}_ontology_v4_full_coverage.json",
        )
        catalog_path = _first_existing(
            artifact_root,
            f"{prefix}_technical_semantic_catalog_current_20260826.json",
            f"{prefix}_technical_semantic_catalog_v3.json",
        )
        candidate_path = _first_existing(
            artifact_root,
            f"{prefix}_semantic_candidate_catalog_current_20260826.json",
            f"{prefix}_semantic_candidate_catalog_v1.json",
        )
        relationship_path = _first_existing(
            artifact_root,
            f"{prefix}_relationship_candidate_catalog_current_20260828.json",
            f"{prefix}_relationship_candidate_catalog_current_20260826.json",
            f"{prefix}_relationship_candidate_catalog_v1.json",
        )
        benchmark_path = _first_existing(
            artifact_root,
            f"{prefix}_current_20260826_free_form_benchmark_v3.json",
            f"{prefix}_v4_scenario_free_form_benchmark_v4.json",
        )
    else:
        semantic_path = _first_existing(
            artifact_root,
            f"{prefix}_semantic_layer_v4_full_coverage.json",
        )
        scenario_semantic_path = _first_existing(
            artifact_root,
            f"{prefix}_semantic_layer_v4_scenarios.json",
            f"{prefix}_semantic_layer_v4_full_coverage.json",
        )
        ontology_path = _first_existing(
            artifact_root,
            f"{prefix}_ontology_v4_full_coverage.json",
        )
        catalog_path = _first_existing(
            artifact_root,
            f"{prefix}_technical_semantic_catalog_v3.json",
        )
        candidate_path = _first_existing(
            artifact_root,
            f"{prefix}_semantic_candidate_catalog_v1.json",
        )
        relationship_path = _first_existing(
            artifact_root,
            f"{prefix}_relationship_candidate_catalog_v1.json",
        )
        benchmark_path = _first_existing(
            artifact_root,
            f"{prefix}_free_form_benchmark_v3_revised.json",
            f"{prefix}_v4_scenario_free_form_benchmark_v4.json",
        )
    paths = {
        "semantic_layer": semantic_path,
        "scenario_semantic_layer": scenario_semantic_path,
        "ontology": ontology_path,
        "technical_catalog": catalog_path,
        "semantic_candidates": candidate_path,
        "relationship_candidates": relationship_path,
        "benchmark": benchmark_path,
    }
    artifacts = {name: _load(path) for name, path in paths.items()}
    semantic = artifacts["semantic_layer"]
    scenario_semantic = artifacts["scenario_semantic_layer"]
    ontology = artifacts["ontology"]
    catalog = artifacts["technical_catalog"]
    relationship_candidates = artifacts["relationship_candidates"]
    benchmark = artifacts["benchmark"]

    resources = {
        _table_name(item.get("physical_table")): item
        for item in catalog.get("resources") or []
        if _table_name(item.get("physical_table"))
    }
    bindings = {
        _table_name(item.get("physical_table")): item
        for item in semantic.get("table_bindings") or []
        if _table_name(item.get("physical_table"))
    }
    concepts = {
        _table_name(item.get("physical_binding")): item
        for item in ontology.get("concepts") or []
        if _table_name(item.get("physical_binding"))
    }
    assets = [item for item in semantic.get("semantic_assets") or [] if isinstance(item, dict)]
    asset_by_table = _asset_tables(assets)
    table_rows, errors = _table_inventory(resources, bindings, asset_by_table, concepts)
    resource_set = set(resources)
    if resource_set != set(bindings):
        errors.append("table_binding_set_mismatch")
    if resource_set != set(concepts):
        errors.append("ontology_concept_set_mismatch")
    orphan_asset_tables = sorted(set(asset_by_table) - resource_set)
    errors.extend(f"reviewed_asset_table_not_in_catalog:{table}" for table in orphan_asset_tables)

    executable_tables = {
        row["physical_table"] for row in table_rows if row["tier"] == "reviewed_executable"
    }
    metric_coverage = _metric_coverage(scenario_semantic.get("metric_contracts") or [], table_rows)
    relationship_coverage = _relationship_coverage(
        scenario_semantic.get("relationships") or [],
        relationship_candidates.get("relationships") or [],
        executable_tables,
    )
    benchmark_coverage = _benchmark_coverage(
        benchmark,
        executable_tables,
        set(metric_coverage["reviewed_contract_ids"]),
    )
    capability_coverage = _capability_coverage(
        assets,
        scenario_semantic.get("metric_contracts") or [],
        scenario_semantic.get("relationships") or [],
        benchmark,
    )

    tier_counts = Counter(row["tier"] for row in table_rows)
    business_fields = [
        field
        for asset in assets
        if _reviewed(asset.get("review_status"))
        for field in asset.get("fields") or []
        if isinstance(field, dict)
    ]
    field_roles = Counter(
        _table_name(field.get("business_role")) or "unassigned"
        for field in business_fields
    )
    field_semantics = {
        "reviewed_business_field_count": len(business_fields),
        "field_role_counts": dict(sorted(field_roles.items())),
        "fields_with_units": sum(bool(_table_name(field.get("unit"))) for field in business_fields),
        "fields_with_value_semantics": sum(
            bool(field.get("value_semantics")) for field in business_fields
        ),
        "fields_with_temporal_role": sum(
            field.get("business_role") == "temporal_dimension"
            for field in business_fields
        ),
        "fields_with_geometry_role": sum(
            field.get("business_role") == "geometry" for field in business_fields
        ),
        "fields_without_labels": sum(
            not isinstance(field.get("labels"), dict)
            or not any(str(value).strip() for value in field.get("labels", {}).values())
            for field in business_fields
        ),
        "fields_without_business_role": sum(
            not _table_name(field.get("business_role")) for field in business_fields
        ),
    }

    business_complete = bool(
        (semantic.get("coverage") or {}).get("business_semantic_coverage_complete")
    )
    technical_complete = (
        len(resources) > 0
        and len(resources) == len(bindings) == len(concepts)
        and not any(error.startswith("technical_field_binding_incomplete:") for error in errors)
    )
    release_checks = {
        "technical_inventory_complete": technical_complete,
        "business_semantic_coverage_complete": business_complete,
        "all_tables_business_reviewed": tier_counts["reviewed_executable"] == len(resources),
        "reviewed_relationships_complete": relationship_coverage["relationship_review_complete"],
        "business_metric_contracts_present": metric_coverage["reviewed_contract_count"] > 0,
        "business_holdout_cases_present": benchmark_coverage.get(
            "reviewed_business_holdout_case_count", 0
        )
        > 0,
        "gold_isolation_proven": all(
            (benchmark_coverage["gold_isolation"].get(key) is False)
            for key in (
                "questions_used_in_runtime_prompts",
                "gold_sql_available_to_runtime",
                "gold_results_available_to_runtime",
            )
        ),
    }
    release_gate = {
        "status": "not_ready" if not all(release_checks.values()) else "ready_for_scope_review",
        "production_promotion_authorized": False,
        "checks": release_checks,
        "blocking_reasons": [
            key for key, value in release_checks.items() if not value
        ],
        "claim_boundary": (
            "This report certifies metadata and reviewed-contract coverage only; "
            "it is not a claim of arbitrary full-database accuracy."
        ),
    }
    return {
        "schema": "gda.gis-data-agent.semantic-readiness.v1",
        "source": {
            "key": source_key,
            "label": spec["label"],
            "prefix": prefix,
        },
        "generated_from": {
            name: {"path": _relative(path, artifact_root.parent.parent), "sha256": _sha256(path)}
            for name, path in paths.items()
        },
        "semantic_coverage": {
            "technical_resource_count": len(resources),
            "table_binding_count": len(bindings),
            "ontology_concept_count": len(concepts),
            "table_tier_counts": dict(sorted(tier_counts.items())),
            "reviewed_business_asset_count": sum(
                1 for asset in assets if _reviewed(asset.get("review_status"))
            ),
            "reviewed_asset_table_count": len(asset_by_table),
            "orphan_reviewed_asset_tables": orphan_asset_tables,
            "technical_field_binding_complete": technical_complete,
            "field_semantics": field_semantics,
        },
        "tables": table_rows,
        "metrics": metric_coverage,
        "relationships": relationship_coverage,
        "benchmark": benchmark_coverage,
        "capabilities": capability_coverage,
        "unsupported_query_classes": [
            "technical_metadata_only_table",
            "unreviewed_relationship",
            "missing_reviewed_metric_contract",
            "missing_unit_or_value_semantics",
            "prediction_or_forecast",
            "network_distance_or_route_time",
            "uncovered_cross_source_federation",
        ],
        "release_gate": release_gate,
        "errors": sorted(set(errors)),
        "status": "pass" if not errors else "attention_required",
    }


def build_readiness_bundle(artifact_root: Path) -> dict[str, Any]:
    """Build the two-source readiness bundle."""

    sources = {
        key: audit_source(key, artifact_root)
        for key in SOURCE_ARTIFACTS
    }
    return {
        "schema": "gda.gis-data-agent.semantic-readiness-bundle.v1",
        "scope": "abu_dhabi_full_semantic_inventory",
        "claim_boundary": (
            "Full technical catalog coverage is not equivalent to full business "
            "semantic coverage. Only reviewed assets, reviewed relationships and "
            "validated metric contracts are executable."
        ),
        "sources": sources,
        "global_release_gate": {
            "status": "not_ready",
            "production_promotion_authorized": False,
            "reason": "arbitrary_full_database_business_semantics_not_yet_reviewed",
        },
    }


__all__ = ["audit_source", "build_readiness_bundle", "CAPABILITY_CLASSES", "SCENARIO_CLASSES"]
