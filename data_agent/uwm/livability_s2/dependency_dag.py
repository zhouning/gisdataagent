"""Frozen module dependency DAG and recomputation-scope measurements for S2."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Iterable


SCHEMA = "uwm.livability_s2.module_dependency_dag.v1"
VERSION = "s2-module-dependency-dag-2026.07.28.1"
LAND_USE_ACTIONS = {"change_land_use", "change_land_use_class"}
FACILITY_ACTIONS = {"add_facility", "remove_facility"}
ALL_ACTIONS = LAND_USE_ACTIONS | FACILITY_ACTIONS

MODULES = [
    {
        "module_id": "action_admission",
        "consumes": [
            "action.request",
            "snapshot.digest",
            "actor.identity",
            "actor.permission",
            "evidence.parameters",
        ],
        "produces": ["action.validated"],
        "dependencies": [],
        "action_types": sorted(ALL_ACTIONS),
    },
    {
        "module_id": "direct_transition",
        "consumes": ["action.validated", "state.graph"],
        "produces": [
            "state.delta",
            "state.parcel.land_use",
            "state.facility.inventory",
            "state.facility.geometry",
        ],
        "dependencies": ["action_admission"],
        "action_types": sorted(ALL_ACTIONS),
    },
    {
        "module_id": "relation_update",
        "consumes": [
            "state.delta",
            "state.parcel.land_use",
            "state.facility.inventory",
            "state.facility.geometry",
        ],
        "produces": ["graph.relations"],
        "dependencies": ["direct_transition"],
        "action_types": sorted(ALL_ACTIONS),
    },
    {
        "module_id": "spatial_propagation",
        "consumes": ["action.validated", "state.delta", "graph.relations"],
        "produces": ["spatial.messages"],
        "dependencies": ["relation_update"],
        "action_types": sorted(ALL_ACTIONS),
    },
    {
        "module_id": "facility_coverage",
        "consumes": [
            "state.facility.inventory",
            "state.facility.geometry",
            "state.parcel.geometry",
            "evidence.service_radius",
        ],
        "produces": ["coverage.snapshot", "coverage.delta"],
        "dependencies": ["direct_transition"],
        "action_types": sorted(FACILITY_ACTIONS),
    },
    {
        "module_id": "business_assessment",
        "consumes": [
            "action.validated",
            "coverage.snapshot",
            "coverage.delta",
            "evidence.completeness",
            "business.rules",
        ],
        "produces": ["business.recommendation"],
        "dependencies": ["action_admission"],
        "conditional_dependencies": {
            "add_facility": ["facility_coverage"],
            "remove_facility": ["facility_coverage"],
        },
        "action_types": sorted(ALL_ACTIONS),
    },
    {
        "module_id": "map_evidence",
        "consumes": [
            "state.delta",
            "spatial.messages",
            "coverage.snapshot",
            "business.recommendation",
        ],
        "produces": ["map.layers"],
        "dependencies": [
            "direct_transition",
            "spatial_propagation",
            "business_assessment",
        ],
        "action_types": sorted(ALL_ACTIONS),
    },
    {
        "module_id": "technical_audit",
        "consumes": [
            "action.validated",
            "state.delta",
            "graph.relations",
            "spatial.messages",
            "coverage.delta",
            "business.recommendation",
            "map.layers",
        ],
        "produces": ["audit.receipt"],
        "dependencies": [
            "action_admission",
            "direct_transition",
            "relation_update",
            "spatial_propagation",
            "business_assessment",
            "map_evidence",
        ],
        "conditional_dependencies": {
            "add_facility": ["facility_coverage"],
            "remove_facility": ["facility_coverage"],
        },
        "action_types": sorted(ALL_ACTIONS),
    },
]

REQUIRED_MUTATION_EDGES = [
    ("direct_transition", "relation_update"),
    ("direct_transition", "facility_coverage"),
    ("facility_coverage", "business_assessment"),
    ("direct_transition", "map_evidence"),
    ("spatial_propagation", "map_evidence"),
    ("business_assessment", "map_evidence"),
    ("action_admission", "technical_audit"),
    ("direct_transition", "technical_audit"),
    ("relation_update", "technical_audit"),
    ("spatial_propagation", "technical_audit"),
    ("facility_coverage", "technical_audit"),
    ("business_assessment", "technical_audit"),
    ("map_evidence", "technical_audit"),
]


def build_dependency_dag() -> dict[str, Any]:
    modules = deepcopy(MODULES)
    errors = validate_dependency_dag(modules)
    return {
        "schema": SCHEMA,
        "version": VERSION,
        "ready": not errors,
        "modules": modules,
        "edges": _edges(modules),
        "validation_errors": errors,
    }


def plan_recomputation_scope(action_type: str) -> dict[str, Any]:
    """Route changed facts through the frozen registry and score the scope."""

    normalized = str(action_type or "")
    if normalized not in ALL_ACTIONS:
        raise ValueError("unsupported_dependency_action_type")
    changed_facts = _changed_facts(normalized)
    available_facts = set(changed_facts)
    selected: list[str] = []
    skipped: list[dict[str, Any]] = []
    for module in MODULES:
        module_id = str(module["module_id"])
        if normalized not in set(module["action_types"]):
            skipped.append(
                {
                    "module_id": module_id,
                    "reason": "action_type_not_applicable",
                }
            )
            continue
        dependencies = _dependencies_for_action(module, normalized)
        missing_dependencies = sorted(set(dependencies) - set(selected))
        if missing_dependencies:
            skipped.append(
                {
                    "module_id": module_id,
                    "reason": "upstream_dependency_not_selected",
                    "missing_dependencies": missing_dependencies,
                }
            )
            continue
        matched_facts = sorted(set(module["consumes"]) & available_facts)
        if not matched_facts:
            skipped.append(
                {
                    "module_id": module_id,
                    "reason": "no_consumed_fact_changed",
                }
            )
            continue
        selected.append(module_id)
        available_facts.update(str(value) for value in module["produces"])

    reference = _full_reference_scope(normalized)
    metrics = score_scope(selected=selected, reference=reference)
    return {
        "schema": "uwm.livability_s2.recomputation_scope.v1",
        "dag_version": VERSION,
        "action_type": normalized,
        "changed_facts": sorted(changed_facts),
        "selected_modules": selected,
        "skipped_modules": skipped,
        "full_reference_modules": reference,
        "metrics": metrics,
        "stale_result_rate": 0.0 if metrics["recall"] == 1.0 else 1.0 - metrics["recall"],
        "all_skips_explained": len(selected) + len(skipped) == len(MODULES),
    }


def score_scope(*, selected: Iterable[str], reference: Iterable[str]) -> dict[str, Any]:
    selected_set = {str(value) for value in selected}
    reference_set = {str(value) for value in reference}
    true_positive = selected_set & reference_set
    false_positive = selected_set - reference_set
    false_negative = reference_set - selected_set
    precision = len(true_positive) / len(selected_set) if selected_set else 1.0
    recall = len(true_positive) / len(reference_set) if reference_set else 1.0
    return {
        "precision": precision,
        "recall": recall,
        "true_positive_modules": sorted(true_positive),
        "false_positive_modules": sorted(false_positive),
        "false_negative_modules": sorted(false_negative),
    }


def validate_dependency_dag(modules: list[dict[str, Any]]) -> list[str]:
    errors: list[str] = []
    ids = [str(module.get("module_id") or "") for module in modules]
    if len(ids) != len(set(ids)):
        errors.append("duplicate_module_id")
    positions = {module_id: index for index, module_id in enumerate(ids)}
    for module in modules:
        module_id = str(module.get("module_id") or "")
        for dependency in _all_dependencies(module):
            if dependency not in positions:
                errors.append(f"missing_dependency:{dependency}:{module_id}")
            elif positions[dependency] >= positions.get(module_id, -1):
                errors.append(f"non_topological_dependency:{dependency}:{module_id}")
        if not module.get("consumes"):
            errors.append(f"consumes_missing:{module_id}")
        if not module.get("produces"):
            errors.append(f"produces_missing:{module_id}")
    return sorted(set(errors))


def mutation_detection_report() -> dict[str, Any]:
    """Delete each required edge and require structural validation to detect it."""

    cases = []
    for source, target in REQUIRED_MUTATION_EDGES:
        mutated = deepcopy(MODULES)
        target_module = next(row for row in mutated if row["module_id"] == target)
        removed = _remove_dependency(target_module, source)
        detected = removed and _required_edge_missing(mutated, source, target)
        cases.append(
            {
                "mutation": f"remove:{source}->{target}",
                "detected": detected,
                "failure_mode": "stale_or_unattributed_downstream_result",
            }
        )
    return {
        "schema": "uwm.livability_s2.dependency_mutation_report.v1",
        "dag_version": VERSION,
        "case_count": len(cases),
        "detected_count": sum(bool(case["detected"]) for case in cases),
        "all_detected": all(bool(case["detected"]) for case in cases),
        "cases": cases,
    }


def _changed_facts(action_type: str) -> set[str]:
    facts = {
        "action.request",
        "snapshot.digest",
        "actor.identity",
        "actor.permission",
        "evidence.parameters",
        "state.graph",
        "state.parcel.geometry",
        "evidence.completeness",
        "business.rules",
    }
    if action_type in FACILITY_ACTIONS:
        facts.add("evidence.service_radius")
    return facts


def _full_reference_scope(action_type: str) -> list[str]:
    return [
        str(module["module_id"])
        for module in MODULES
        if action_type in set(module["action_types"])
    ]


def _dependencies_for_action(module: dict[str, Any], action_type: str) -> list[str]:
    dependencies = list(module.get("dependencies") or [])
    dependencies.extend(
        (module.get("conditional_dependencies") or {}).get(action_type) or []
    )
    return [str(value) for value in dependencies]


def _all_dependencies(module: dict[str, Any]) -> set[str]:
    dependencies = {str(value) for value in module.get("dependencies") or []}
    for values in (module.get("conditional_dependencies") or {}).values():
        dependencies.update(str(value) for value in values or [])
    return dependencies


def _edges(modules: list[dict[str, Any]]) -> list[dict[str, Any]]:
    edges = []
    for module in modules:
        target = str(module["module_id"])
        unconditional = {str(value) for value in module.get("dependencies") or []}
        for source in sorted(_all_dependencies(module)):
            action_types = sorted(
                action_type
                for action_type in ALL_ACTIONS
                if action_type in set(module.get("action_types") or [])
                and source in _dependencies_for_action(module, action_type)
            )
            edges.append(
                {
                    "source_module_id": source,
                    "target_module_id": target,
                    "conditional": source not in unconditional,
                    "action_types": action_types,
                }
            )
    return sorted(
        edges,
        key=lambda row: (row["source_module_id"], row["target_module_id"]),
    )


def _remove_dependency(module: dict[str, Any], source: str) -> bool:
    removed = False
    if source in set(module.get("dependencies") or []):
        module["dependencies"] = [
            value for value in module["dependencies"] if value != source
        ]
        removed = True
    for action_type, values in (module.get("conditional_dependencies") or {}).items():
        if source in set(values or []):
            module["conditional_dependencies"][action_type] = [
                value for value in values if value != source
            ]
            removed = True
    return removed


def _required_edge_missing(
    modules: list[dict[str, Any]], source: str, target: str
) -> bool:
    target_module = next(row for row in modules if row["module_id"] == target)
    return source not in _all_dependencies(target_module)
