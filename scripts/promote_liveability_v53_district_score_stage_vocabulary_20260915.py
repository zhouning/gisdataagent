#!/usr/bin/env python3
"""Publish v53 after auditing the current district-score stage vocabulary.

v52 remains immutable. This corrective release changes only the audited stage
literal used by the current quantitative-score ranking and its published field
definition. The publisher does not read benchmark inputs, Gold SQL/results,
or model output.
"""

from __future__ import annotations

import asyncio
import copy
import importlib.util
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

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
from data_agent.virtual_sources import discover_virtual_source


ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_ROOT = ROOT / "docs/customer/abu_dhabi_liveability_site_validation"
SOURCE_ID = 12
OWNER = "abu-dhabi-site-operator"
STAGE_TABLE = "public.fact_district_scores"
STAGE_FIELD = "stage"
CONTRACT_ID = "LIVEABILITY_CURRENT_QUANTITATIVE_SCORE_RANKING_V1"


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


v52 = _load_module(
    "liveability_v52_stage_vocabulary_parent",
    ROOT / "scripts/promote_liveability_v52_governed_parameterized_business_metrics_20260915.py",
)
base = v52.base

INPUT_SEMANTIC = ARTIFACT_ROOT / "liveability_data_20260730_semantic_layer_v52_governed_parameterized_business_metrics_20260915.json"
INPUT_ONTOLOGY = ARTIFACT_ROOT / "liveability_data_20260730_ontology_v51_governed_parameterized_business_metrics_20260915.json"
INPUT_CATALOG = ARTIFACT_ROOT / "liveability_data_20260730_technical_semantic_catalog_v8_governed_parameterized_business_metrics_20260915.json"
OUTPUT_SEMANTIC = ARTIFACT_ROOT / "liveability_data_20260730_semantic_layer_v53_district_score_stage_vocabulary_20260915.json"
OUTPUT_ONTOLOGY = ARTIFACT_ROOT / "liveability_data_20260730_ontology_v52_district_score_stage_vocabulary_20260915.json"
OUTPUT_CATALOG = ARTIFACT_ROOT / "liveability_data_20260730_technical_semantic_catalog_v9_district_score_stage_vocabulary_20260915.json"
OUTPUT_SOURCE_AUDIT = ARTIFACT_ROOT / "liveability_v53_district_score_stage_vocabulary_source_audit_20260915.json"
OUTPUT_PUBLICATION_AUDIT = ARTIFACT_ROOT / "liveability_v53_district_score_stage_vocabulary_publication_audit_20260915.json"

SEMANTIC_VERSION = "abu-dhabi-liveability_data_20260730-v53-district-score-stage-vocabulary-20260915"
ONTOLOGY_VERSION = "abu-dhabi-liveability-ontology-v52-district-score-stage-vocabulary-20260915"
BUNDLE_ID = "abu-dhabi-liveability-current-20260915-district-score-stage-vocabulary-v53"
METRIC_CONTRACT_VERSION = "abu-dhabi-liveability-metric-contracts-v41-district-score-stage-vocabulary-20260915"

_BASE_CONTRACTS = v52._contracts


def _contracts() -> list[dict[str, Any]]:
    contracts = copy.deepcopy(_BASE_CONTRACTS())
    contract = next(item for item in contracts if item["contract_id"] == CONTRACT_ID)
    contract["filters"][0]["values"] = ["Existing"]
    contract["canonical_sql_template"] = contract["canonical_sql_template"].replace(
        "s.stage='current'", "s.stage='Existing'"
    )
    contract["provenance"] = "current_source_stage_aggregate_audit_plus_reviewed_quantitative_score_definition"
    return contracts


def _update_stage_vocabulary(semantic: dict[str, Any], ontology: dict[str, Any]) -> None:
    definition = (
        "Lifecycle stage for the quantitative liveability score. A current-source aggregate audit "
        "on the approved calculation version observed the literal vocabulary Existing, Pipeline, and AP50. "
        "Map user terms existing/current to Existing, pipeline/post-pipeline to Pipeline, and Target stage "
        "to AP50. Do not infer an Ultimate district-score stage when it is absent from the audited current version."
    )
    containers = [
        *[item for item in semantic.get("table_bindings") or [] if item.get("physical_table") == STAGE_TABLE],
        *[item for item in semantic.get("semantic_assets") or [] if STAGE_TABLE in (item.get("physical_tables") or [])],
        *[item for item in ontology.get("concepts") or [] if item.get("physical_binding") == STAGE_TABLE],
    ]
    if len(containers) != 3:
        raise RuntimeError("district_score_stage_projection_missing")
    for container in containers:
        field = next((item for item in container.get("fields") or [] if item.get("physical_field") == STAGE_FIELD), None)
        if not isinstance(field, dict):
            raise RuntimeError("district_score_stage_field_missing")
        field["description"] = definition
        field["definition"] = definition
        field["definition_status"] = "source_bound_stage_vocabulary_audited"
        field["observed_value_domain"] = ["Existing", "Pipeline", "AP50"]


def _upsert_contracts(semantic: dict[str, Any], ontology: dict[str, Any]) -> list[str]:
    original = v52._contracts
    try:
        v52._contracts = _contracts
        contract_ids = v52._upsert_contracts(semantic, ontology)
    finally:
        v52._contracts = original
    _update_stage_vocabulary(semantic, ontology)
    return contract_ids


async def _audit_contract_queries(semantic: dict[str, Any]) -> dict[str, Any]:
    original = v52._contracts
    try:
        v52._contracts = _contracts
        audit = await v52._audit_contract_queries(semantic)
    finally:
        v52._contracts = original
    score_probe = (audit.get("contract_probes") or {}).get(CONTRACT_ID) or {}
    if int(score_probe.get("row_count") or 0) <= 0:
        raise RuntimeError("district_score_stage_vocabulary_probe_empty")
    audit.update(
        {
            "schema": "gda.liveability-v53-district-score-stage-vocabulary-source-audit.v1",
            "district_score_stage_vocabulary": {
                "table": STAGE_TABLE,
                "field": STAGE_FIELD,
                "approved_current_version_values": ["Existing", "Pipeline", "AP50"],
                "current_ranking_literal": "Existing",
                "aggregate_only": True,
                "source_rows_persisted": False,
            },
        }
    )
    return audit


def _set_evolution(semantic: dict[str, Any], ontology: dict[str, Any], audit_sha256: str) -> None:
    evolution = copy.deepcopy(semantic.get("semantic_evolution") or {})
    parent_semantic = str(semantic.get("semantic_version") or "")
    parent_ontology = str(ontology.get("ontology_enrichment_version") or ontology.get("overlay_id") or "")
    if not parent_semantic or not parent_ontology:
        raise RuntimeError("parent_version_missing")
    evolution.update(
        {
            "schema": "gda.abu-dhabi-semantic-evolution.v1",
            "change_id": "abu-dhabi-liveability-20260915-v53-district-score-stage-vocabulary",
            "parent_semantic_version": parent_semantic,
            "parent_ontology_version": parent_ontology,
            "source_evidence": [
                *(evolution.get("source_evidence") or []),
                {"path": base._relative(OUTPUT_SOURCE_AUDIT), "sha256": audit_sha256, "benchmark_questions_used": False, "gold_sql_used": False, "gold_results_used": False, "model_outputs_used": False},
            ],
            "changes": [
                *(evolution.get("changes") or []),
                "corrected the quantitative district-score current-stage literal from an unverified normalized token to the audited source value Existing",
                "published the audited Existing/Pipeline/AP50 value domain and made an empty ranking probe a release failure",
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
    binding, snapshot = v52.v51._binding_and_snapshot()
    catalog = v52.v51._load(INPUT_CATALOG)
    record_count_changes = v52._assert_no_unreviewed_drift(catalog, snapshot)
    semantic = v52.v51._rebind(v52.v51._load(INPUT_SEMANTIC), binding["discovery_fingerprint"], binding["profile_fingerprint"])
    ontology = v52.v51._rebind(v52.v51._load(INPUT_ONTOLOGY), binding["discovery_fingerprint"], binding["profile_fingerprint"])
    catalog = v52.v51._rebind(catalog, binding["discovery_fingerprint"], binding["profile_fingerprint"])
    semantic["source_binding"] = copy.deepcopy(binding)
    ontology["source_evidence"] = {**(ontology.get("source_evidence") or {}), **binding, "contains_source_rows": False}
    catalog["source_evidence"] = {**(catalog.get("source_evidence") or {}), **binding, "contains_source_rows": False}
    contract_ids = _upsert_contracts(semantic, ontology)
    source_audit = asyncio.run(_audit_contract_queries(semantic))
    source_audit["discovery_metadata_refresh"] = {"estimated_record_count_changed_tables": record_count_changes, "structural_drift_detected": False, "source_rows_persisted": False}
    source_audit_sha256 = base._sha256(base._raw(source_audit))
    _set_evolution(semantic, ontology, source_audit_sha256)
    semantic.update({"semantic_version": SEMANTIC_VERSION, "metric_contract_version": METRIC_CONTRACT_VERSION, "artifact_bundle_id": BUNDLE_ID, "ontology_overlay": base._relative(OUTPUT_ONTOLOGY), "technical_catalog": base._relative(OUTPUT_CATALOG)})
    semantic["gold_compatible_semantic_versions"] = list(dict.fromkeys([*(semantic.get("gold_compatible_semantic_versions") or []), SEMANTIC_VERSION]))
    ontology.update({"ontology_enrichment_version": ONTOLOGY_VERSION, "overlay_id": ONTOLOGY_VERSION, "artifact_bundle_id": BUNDLE_ID})
    catalog["artifact_bundle_id"] = BUNDLE_ID
    publication = {"status": "published_v53", "purpose": "district_score_stage_vocabulary_correction", "corrected_contract_id": CONTRACT_ID, "source_audit_path": base._relative(OUTPUT_SOURCE_AUDIT), "source_audit_sha256": source_audit_sha256, "benchmark_questions_used": False, "gold_sql_used": False, "gold_results_used": False, "model_outputs_used": False, "source_rows_persisted": False}
    semantic["district_score_stage_vocabulary_publication"] = copy.deepcopy(publication)
    ontology["district_score_stage_vocabulary_publication"] = copy.deepcopy(publication)
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
    publication_audit = {"schema": "gda.liveability-v53-district-score-stage-vocabulary-publication-audit.v1", "generated_at": datetime.now(UTC).isoformat(), "status": "complete", "semantic_version": SEMANTIC_VERSION, "ontology_version": ONTOLOGY_VERSION, "semantic_sha256": semantic_sha, "ontology_sha256": ontology_sha, "catalog_sha256": catalog_sha, "source_audit_sha256": source_audit_sha, "publication": publication}
    publication_sha = base._write_new(OUTPUT_PUBLICATION_AUDIT, publication_audit)
    bundle = copy.deepcopy(base._load(base.BUNDLE))
    bundle.update({"artifact_bundle_id": BUNDLE_ID, "bundle_id": BUNDLE_ID, "semantic_version": SEMANTIC_VERSION, "ontology_version": ONTOLOGY_VERSION, "generated_at": datetime.now(UTC).isoformat(), "source": binding})
    artifacts = bundle.setdefault("artifacts", {})
    artifacts["semantic"] = {"role": "runtime_semantic_layer", "path": base._relative(OUTPUT_SEMANTIC), "sha256": semantic_sha}
    artifacts["ontology"] = {"role": "ontology_overlay", "path": base._relative(OUTPUT_ONTOLOGY), "sha256": ontology_sha}
    artifacts["catalog"] = {"role": "technical_metadata_catalog", "path": base._relative(OUTPUT_CATALOG), "sha256": catalog_sha}
    artifacts["district_score_stage_vocabulary_source_audit"] = {"role": "source_aggregate_audit", "path": base._relative(OUTPUT_SOURCE_AUDIT), "sha256": source_audit_sha}
    artifacts["district_score_stage_vocabulary_publication_audit"] = {"role": "metric_publication_audit", "path": base._relative(OUTPUT_PUBLICATION_AUDIT), "sha256": publication_sha}
    bundle.setdefault("claim_boundary", {}).update({"v53_benchmark_questions_used": False, "v53_gold_sql_used": False, "v53_gold_results_used": False, "v53_model_outputs_used": False, "v53_source_rows_persisted": False})
    base._write_bundle(bundle)
    return {"status": "published", "source": binding, "semantic": base._relative(OUTPUT_SEMANTIC), "ontology": base._relative(OUTPUT_ONTOLOGY), "source_audit": base._relative(OUTPUT_SOURCE_AUDIT), "publication_audit": base._relative(OUTPUT_PUBLICATION_AUDIT), "corrected_contract_id": CONTRACT_ID}


if __name__ == "__main__":
    print(json.dumps(publish(), ensure_ascii=False, indent=2))
