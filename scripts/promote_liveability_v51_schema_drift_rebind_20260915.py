#!/usr/bin/env python3
"""Publish v51 after a reviewed, technical-only Liveability schema addition.

The registered source added one boolean field to a parameter table.  This
release refuses all other structural drift, preserves the v50 artifacts, and
labels the new field as technical metadata until a customer table card defines
its business meaning.  It never reads a benchmark, Gold SQL/results, or model
output.
"""

from __future__ import annotations

import asyncio
import copy
import importlib.util
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping

from data_agent.abu_dhabi_semantic_evolution import validate_semantic_evolution
from data_agent.governed_virtual_nl2sql import (
    _validate_metric_contracts,
    _validate_row_scope_policies,
    _validate_semantic_answerability_contracts,
    _validate_semantic_caveats,
)
from data_agent.semantic_projection_policy import validate_projection_completeness_policies
from data_agent.semantic_query_ir import validate_derived_projection_policies
from data_agent.virtual_source_operator import _load_environment
from data_agent.virtual_sources import discover_virtual_source, get_virtual_source_discovery


ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_ROOT = ROOT / "docs/customer/abu_dhabi_liveability_site_validation"
SOURCE_ID = 12
OWNER = "abu-dhabi-site-operator"
DRIFT_TABLE = "public.param_prioritization_category_weights"
DRIFT_FIELD = "include_in_facility_scores"


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


v50 = _load_module(
    "liveability_v50_schema_parent",
    ROOT / "scripts/promote_liveability_v50_metric_composition_audit_boundary_20260915.py",
)
v40 = _load_module(
    "liveability_v40_schema_guard",
    ROOT / "scripts/promote_liveability_v40_discovery_rebind_20260911.py",
)
base = v50.base

INPUT_SEMANTIC = ARTIFACT_ROOT / (
    "liveability_data_20260730_semantic_layer_v50_metric_composition_audit_boundary_20260915.json"
)
INPUT_ONTOLOGY = ARTIFACT_ROOT / (
    "liveability_data_20260730_ontology_v49_metric_composition_audit_boundary_20260915.json"
)
INPUT_CATALOG = ARTIFACT_ROOT / (
    "liveability_data_20260730_technical_semantic_catalog_v6_discovery_rebind_20260913.json"
)
OUTPUT_SEMANTIC = ARTIFACT_ROOT / (
    "liveability_data_20260730_semantic_layer_v51_schema_drift_rebind_20260915.json"
)
OUTPUT_ONTOLOGY = ARTIFACT_ROOT / (
    "liveability_data_20260730_ontology_v50_schema_drift_rebind_20260915.json"
)
OUTPUT_CATALOG = ARTIFACT_ROOT / (
    "liveability_data_20260730_technical_semantic_catalog_v7_schema_drift_rebind_20260915.json"
)
OUTPUT_SOURCE_AUDIT = ARTIFACT_ROOT / (
    "liveability_v51_schema_drift_rebind_source_audit_20260915.json"
)
OUTPUT_PUBLICATION_AUDIT = ARTIFACT_ROOT / (
    "liveability_v51_schema_drift_rebind_publication_audit_20260915.json"
)

SEMANTIC_VERSION = "abu-dhabi-liveability_data_20260730-v51-schema-drift-rebind-20260915"
ONTOLOGY_VERSION = "abu-dhabi-liveability-ontology-v50-schema-drift-rebind-20260915"
BUNDLE_ID = "abu-dhabi-liveability-current-20260915-schema-drift-rebind-v51"
METRIC_CONTRACT_VERSION = "abu-dhabi-liveability-metric-contracts-v39-schema-drift-rebind-20260915"


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"artifact_object_required:{path.name}")
    return value


def _rebind(value: Any, discovery: str, profile: str) -> Any:
    if isinstance(value, list):
        return [_rebind(item, discovery, profile) for item in value]
    if not isinstance(value, dict):
        return value
    result = {}
    scoped = value.get("source_id") == SOURCE_ID
    for key, item in value.items():
        if scoped and key == "discovery_fingerprint":
            result[key] = discovery
        elif scoped and key == "profile_fingerprint":
            result[key] = profile
        else:
            result[key] = _rebind(item, discovery, profile)
    return result


def _binding_and_snapshot() -> tuple[dict[str, Any], dict[str, Any]]:
    discovery = get_virtual_source_discovery(SOURCE_ID, OWNER)
    if not discovery or discovery.get("discovery_status") != "succeeded":
        raise RuntimeError("source_discovery_not_succeeded")
    snapshot = discovery.get("discovery_snapshot") or {}
    if snapshot.get("contains_source_rows") is not False or snapshot.get("truncated") is not False:
        raise RuntimeError("discovery_must_be_complete_metadata_only")
    binding = {
        "source_id": SOURCE_ID,
        "database_name": str(snapshot.get("database_name") or ""),
        "allowed_schemas": list(snapshot.get("authorized_schemas") or []),
        "discovery_fingerprint": str(discovery.get("discovery_fingerprint") or ""),
        "profile_fingerprint": str(discovery.get("profile_fingerprint") or ""),
        "execution_mode": "registered_governed_virtual_read_only",
    }
    if (
        binding["database_name"] != "liveability_data_20260730"
        or binding["allowed_schemas"] != ["public"]
        or any(len(str(binding[key])) != 64 for key in ("discovery_fingerprint", "profile_fingerprint"))
    ):
        raise RuntimeError("source_binding_incomplete")
    return binding, snapshot


def _assert_only_allowed_drift(catalog: Mapping[str, Any], snapshot: Mapping[str, Any]) -> dict[str, Any]:
    """Allow exactly one documented field addition and reject every other drift."""

    old = v40._catalog_resources(catalog)
    current = v40._resources(snapshot)
    if set(old) != set(current):
        raise RuntimeError("discovery_resource_set_changed_requires_review")
    metadata_changes: list[dict[str, Any]] = []
    for table in sorted(old):
        old_resource = old[table]
        current_resource = current[table]
        old_columns = v40._catalog_columns(old_resource)
        current_columns = v40._snapshot_columns(current_resource)
        added = sorted(set(current_columns) - set(old_columns))
        removed = sorted(set(old_columns) - set(current_columns))
        changed = sorted(
            field
            for field in set(old_columns) & set(current_columns)
            if old_columns[field] != current_columns[field]
        )
        if table == DRIFT_TABLE:
            expected = DRIFT_FIELD.casefold()
            if added != [expected] or removed or changed or current_columns[expected] != ("BOOLEAN", False):
                raise RuntimeError("reviewed_field_addition_changed_or_incomplete")
        elif added or removed or changed:
            raise RuntimeError(f"discovery_field_change_requires_review:{table}")
        if str(old_resource.get("resource_type") or "") != str(current_resource.get("resource_type") or ""):
            raise RuntimeError(f"discovery_resource_type_change_requires_review:{table}")
        if v40._metadata_signature(old_resource, "foreign_keys") != v40._metadata_signature(current_resource, "foreign_keys"):
            raise RuntimeError(f"discovery_foreign_key_change_requires_review:{table}")
        changed_metadata = [
            key
            for key in ("primary_key", "indexes")
            if v40._metadata_signature(old_resource, key) != v40._metadata_signature(current_resource, key)
        ]
        if changed_metadata or old_resource.get("estimated_record_count") != current_resource.get("estimated_record_count"):
            metadata_changes.append(
                {
                    "physical_table": table,
                    "metadata_changes": changed_metadata,
                    "estimated_record_count_changed": old_resource.get("estimated_record_count")
                    != current_resource.get("estimated_record_count"),
                }
            )
    return {
        "kind": "technical_field_addition",
        "table": DRIFT_TABLE,
        "field": DRIFT_FIELD,
        "data_type": "BOOLEAN",
        "nullable": False,
        "business_definition_status": "pending_customer_governance",
        "benchmark_questions_used": False,
        "gold_sql_used": False,
        "gold_results_used": False,
        "model_outputs_used": False,
        "source_rows_persisted": False,
        "other_metadata_changes": metadata_changes,
    }


def _technical_field() -> dict[str, Any]:
    return {
        "semantic_field": DRIFT_FIELD,
        "physical_field": DRIFT_FIELD,
        "labels": {
            "zh": "include in facility scores",
            "en": "include in facility scores",
            "ar": "include in facility scores",
        },
        "business_role": "attribute",
        "technical_metadata": {
            "data_type": "BOOLEAN",
            "nullable": False,
            "source_semantic_status": "technical_metadata_only",
        },
        "semantic_status": "technical_metadata_only",
        "inference": {
            "status": "source_metadata_only",
            "method": "current_registered_source_discovery",
            "confidence": "technical",
            "dictionary_evidence": False,
            "runtime_authority": True,
            "review_required": True,
        },
        "description": "Boolean source field; business meaning requires customer governance review.",
        "definition": "Boolean source field; business meaning requires customer governance review.",
        "definition_status": "source_bound_technical_metadata_only",
    }


def _append_field(container: dict[str, Any]) -> None:
    fields = list(container.get("fields") or [])
    existing = {str(field.get("physical_field") or "") for field in fields if isinstance(field, dict)}
    if DRIFT_FIELD not in existing:
        fields.append(_technical_field())
    container["fields"] = sorted(fields, key=lambda item: str(item.get("physical_field") or ""))
    evidence = container.get("business_table_card_evidence")
    if isinstance(evidence, dict):
        evidence["current_fields_without_card_count"] = 1
        evidence["current_fields_without_card"] = [DRIFT_FIELD]
        evidence["matched_current_field_count"] = int(evidence.get("explicit_field_count") or 0)
    description = str(container.get("description") or "")
    if "12 columns" in description:
        container["description"] = description.replace("12 columns", "13 columns")


def _apply_technical_field(
    semantic: dict[str, Any], ontology: dict[str, Any], catalog: dict[str, Any]
) -> None:
    catalog_resource = next(
        (item for item in catalog.get("resources") or [] if item.get("physical_table") == DRIFT_TABLE),
        None,
    )
    if not isinstance(catalog_resource, dict):
        raise RuntimeError("drift_table_missing_from_catalog")
    catalog_fields = list(catalog_resource.get("fields") or [])
    if DRIFT_FIELD not in {str(item.get("physical_field") or "") for item in catalog_fields}:
        catalog_fields.append(
            {
                "physical_field": DRIFT_FIELD,
                "data_type": "BOOLEAN",
                "nullable": False,
                "semantic_status": "technical_metadata_only",
            }
        )
    catalog_resource["fields"] = sorted(catalog_fields, key=lambda item: str(item.get("physical_field") or ""))

    bindings = [item for item in semantic.get("table_bindings") or [] if item.get("physical_table") == DRIFT_TABLE]
    assets = [
        item
        for item in semantic.get("semantic_assets") or []
        if DRIFT_TABLE in (item.get("physical_tables") or [])
    ]
    concepts = [item for item in ontology.get("concepts") or [] if item.get("physical_binding") == DRIFT_TABLE]
    if len(bindings) != 1 or len(assets) != 1 or len(concepts) != 1:
        raise RuntimeError("drift_table_semantic_projection_missing")
    for item in [*bindings, *assets, *concepts]:
        _append_field(item)
    semantic["technical_schema_drift"] = {
        "table": DRIFT_TABLE,
        "field": DRIFT_FIELD,
        "business_definition_status": "pending_customer_governance",
        "runtime_behavior": "technical_metadata_only",
        "source_rows_persisted": False,
    }
    ontology["technical_schema_drift"] = copy.deepcopy(semantic["technical_schema_drift"])


def _set_evolution(semantic: dict[str, Any], ontology: dict[str, Any], audit_sha256: str) -> None:
    parent_semantic = str(semantic.get("semantic_version") or "")
    parent_ontology = str(ontology.get("ontology_enrichment_version") or ontology.get("overlay_id") or "")
    if not parent_semantic or not parent_ontology:
        raise RuntimeError("parent_version_missing")
    evolution = copy.deepcopy(semantic.get("semantic_evolution") or {})
    evolution.update(
        {
            "schema": "gda.abu-dhabi-semantic-evolution.v1",
            "change_id": "abu-dhabi-liveability-20260915-v51-technical-schema-drift-rebind",
            "parent_semantic_version": parent_semantic,
            "parent_ontology_version": parent_ontology,
            "source_evidence": [
                *(evolution.get("source_evidence") or []),
                {
                    "path": base._relative(OUTPUT_SOURCE_AUDIT),
                    "sha256": audit_sha256,
                    "benchmark_questions_used": False,
                    "gold_sql_used": False,
                    "gold_results_used": False,
                    "model_outputs_used": False,
                },
            ],
            "changes": [
                *(evolution.get("changes") or []),
                "rebound to the current registered source after one reviewed technical boolean field addition",
                "published include_in_facility_scores as technical metadata only pending customer business definition",
            ],
            "benchmark_questions_used": False,
            "gold_sql_used": False,
            "gold_results_used": False,
            "model_outputs_used": False,
            "source_rows_persisted": False,
        }
    )
    semantic["semantic_evolution"] = evolution
    ontology["semantic_evolution"] = copy.deepcopy(evolution)


def publish() -> dict[str, Any]:
    _load_environment()
    discovery = asyncio.run(discover_virtual_source(SOURCE_ID, OWNER))
    if discovery.get("status") != "ok":
        raise RuntimeError("fresh_discovery_failed")
    binding, snapshot = _binding_and_snapshot()
    catalog = _load(INPUT_CATALOG)
    drift = _assert_only_allowed_drift(catalog, snapshot)
    semantic = _rebind(_load(INPUT_SEMANTIC), binding["discovery_fingerprint"], binding["profile_fingerprint"])
    ontology = _rebind(_load(INPUT_ONTOLOGY), binding["discovery_fingerprint"], binding["profile_fingerprint"])
    catalog = _rebind(catalog, binding["discovery_fingerprint"], binding["profile_fingerprint"])
    semantic["source_binding"] = copy.deepcopy(binding)
    ontology["source_evidence"] = {**(ontology.get("source_evidence") or {}), **binding, "contains_source_rows": False}
    catalog["source_evidence"] = {**(catalog.get("source_evidence") or {}), **binding, "contains_source_rows": False}
    _apply_technical_field(semantic, ontology, catalog)

    source_audit = asyncio.run(v50._audit_contract_queries(semantic))
    source_audit["technical_schema_drift"] = copy.deepcopy(drift)
    source_audit_sha256 = base._sha256(base._raw(source_audit))
    contract_ids = base._upsert_contracts(semantic, ontology)
    table_cards = base._table_card_evidence(semantic)
    _set_evolution(semantic, ontology, source_audit_sha256)

    semantic.update(
        {
            "semantic_version": SEMANTIC_VERSION,
            "metric_contract_version": METRIC_CONTRACT_VERSION,
            "artifact_bundle_id": BUNDLE_ID,
            "ontology_overlay": base._relative(OUTPUT_ONTOLOGY),
            "technical_catalog": base._relative(OUTPUT_CATALOG),
        }
    )
    semantic["gold_compatible_semantic_versions"] = list(
        dict.fromkeys([*(semantic.get("gold_compatible_semantic_versions") or []), SEMANTIC_VERSION])
    )
    ontology.update(
        {
            "ontology_enrichment_version": ONTOLOGY_VERSION,
            "overlay_id": ONTOLOGY_VERSION,
            "artifact_bundle_id": BUNDLE_ID,
        }
    )
    catalog["artifact_bundle_id"] = BUNDLE_ID

    publication = {
        "status": "published_v51_schema_drift_rebind",
        "purpose": "table_card_metric_compositions",
        "contract_ids": contract_ids,
        "table_card_evidence": table_cards,
        "source_audit_path": base._relative(OUTPUT_SOURCE_AUDIT),
        "source_audit_sha256": source_audit_sha256,
        "technical_schema_drift": drift,
        "benchmark_questions_used": False,
        "gold_sql_used": False,
        "gold_results_used": False,
        "model_outputs_used": False,
        "source_rows_persisted": False,
    }
    semantic["table_card_metric_compositions_publication"] = copy.deepcopy(publication)
    ontology["table_card_metric_compositions_publication"] = copy.deepcopy(publication)

    _validate_metric_contracts(semantic)
    _validate_row_scope_policies(semantic)
    _validate_semantic_answerability_contracts(semantic)
    _validate_semantic_caveats(semantic)
    validate_projection_completeness_policies(semantic)
    validate_derived_projection_policies(semantic)
    validate_semantic_evolution(semantic, ontology)
    if ontology.get("runtime_metric_contracts") != semantic.get("metric_contracts"):
        raise RuntimeError("ontology_runtime_metric_contracts_out_of_sync")

    catalog_sha = base._write_new(OUTPUT_CATALOG, catalog)
    source_audit_sha = base._write_new(OUTPUT_SOURCE_AUDIT, source_audit)
    semantic_sha = base._write_new(OUTPUT_SEMANTIC, semantic)
    ontology_sha = base._write_new(OUTPUT_ONTOLOGY, ontology)
    publication_audit = {
        "schema": "gda.liveability-v51-schema-drift-rebind-publication-audit.v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "status": "complete",
        "semantic_version": SEMANTIC_VERSION,
        "ontology_version": ONTOLOGY_VERSION,
        "semantic_sha256": semantic_sha,
        "ontology_sha256": ontology_sha,
        "catalog_sha256": catalog_sha,
        "source_audit_sha256": source_audit_sha,
        "publication": publication,
    }
    publication_sha = base._write_new(OUTPUT_PUBLICATION_AUDIT, publication_audit)

    bundle = copy.deepcopy(base._load(base.BUNDLE))
    bundle.update(
        {
            "artifact_bundle_id": BUNDLE_ID,
            "bundle_id": BUNDLE_ID,
            "semantic_version": SEMANTIC_VERSION,
            "ontology_version": ONTOLOGY_VERSION,
            "generated_at": datetime.now(UTC).isoformat(),
            "source": binding,
        }
    )
    artifacts = bundle.setdefault("artifacts", {})
    artifacts["semantic"] = {"role": "runtime_semantic_layer", "path": base._relative(OUTPUT_SEMANTIC), "sha256": semantic_sha}
    artifacts["ontology"] = {"role": "ontology_overlay", "path": base._relative(OUTPUT_ONTOLOGY), "sha256": ontology_sha}
    artifacts["catalog"] = {"role": "technical_metadata_catalog", "path": base._relative(OUTPUT_CATALOG), "sha256": catalog_sha}
    artifacts["table_card_metric_compositions_source_audit"] = {"role": "source_aggregate_audit", "path": base._relative(OUTPUT_SOURCE_AUDIT), "sha256": source_audit_sha}
    artifacts["table_card_metric_compositions_publication_audit"] = {"role": "metric_composition_publication_audit", "path": base._relative(OUTPUT_PUBLICATION_AUDIT), "sha256": publication_sha}
    bundle.setdefault("claim_boundary", {}).update(
        {
            "v51_technical_schema_drift_rebind": True,
            "v51_benchmark_questions_used": False,
            "v51_gold_sql_used": False,
            "v51_gold_results_used": False,
            "v51_model_outputs_used": False,
            "v51_source_rows_persisted": False,
        }
    )
    base._write_bundle(bundle)
    return {
        "status": "published",
        "source": binding,
        "technical_schema_drift": drift,
        "semantic": base._relative(OUTPUT_SEMANTIC),
        "ontology": base._relative(OUTPUT_ONTOLOGY),
        "catalog": base._relative(OUTPUT_CATALOG),
        "source_audit": base._relative(OUTPUT_SOURCE_AUDIT),
        "publication_audit": base._relative(OUTPUT_PUBLICATION_AUDIT),
        "contract_ids": contract_ids,
    }


if __name__ == "__main__":
    print(json.dumps(publish(), ensure_ascii=False, indent=2))
