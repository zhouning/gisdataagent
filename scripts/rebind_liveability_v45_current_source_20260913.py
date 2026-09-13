#!/usr/bin/env python3
"""Rebind v45 runtime artifacts to the current metadata-only source snapshot.

The 20260912 v45 artifacts remain immutable historical evidence.  This command
creates a new v45 source-bound set after the registered source endpoint moved
from 5444 to 5443 and after metadata-only discovery produced a new fingerprint.
It refuses structural discovery drift, runs the aggregate relationship probes
again, and never reads benchmark, Gold, model-output, or source-row payloads.
"""

from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import sys
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
from data_agent.virtual_sources import get_virtual_source_discovery

sys.path.insert(0, str(Path(__file__).resolve().parent))
import promote_liveability_v45_plot_detail_audited_relationships_20260912 as v45
from promote_liveability_v40_discovery_rebind_20260911 import (
    _assert_additive_compatible,
)

ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_ROOT = ROOT / "docs/customer/abu_dhabi_liveability_site_validation"
SOURCE_ID = 12
OWNER = "abu-dhabi-site-operator"
INPUT_SEMANTIC = ARTIFACT_ROOT / "liveability_data_20260730_semantic_layer_v45_plot_detail_audited_relationships_20260912.json"
INPUT_ONTOLOGY = ARTIFACT_ROOT / "liveability_data_20260730_ontology_v44_plot_detail_audited_relationships_20260912.json"
INPUT_CATALOG = ARTIFACT_ROOT / "liveability_data_20260730_technical_semantic_catalog_v6_discovery_rebind_20260911.json"
OUTPUT_SEMANTIC = ARTIFACT_ROOT / "liveability_data_20260730_semantic_layer_v45_plot_detail_audited_relationships_20260913.json"
OUTPUT_ONTOLOGY = ARTIFACT_ROOT / "liveability_data_20260730_ontology_v44_plot_detail_audited_relationships_20260913.json"
OUTPUT_CATALOG = ARTIFACT_ROOT / "liveability_data_20260730_technical_semantic_catalog_v6_discovery_rebind_20260913.json"
OUTPUT_SOURCE_AUDIT = ARTIFACT_ROOT / "liveability_v45_plot_relationship_source_audit_20260913.json"
OUTPUT_PUBLICATION_AUDIT = ARTIFACT_ROOT / "liveability_v45_plot_detail_audited_relationships_publication_audit_20260913.json"
BUNDLE = ARTIFACT_ROOT / "abu_dhabi_current_artifact_bundle.json"
SEMANTIC_VERSION = "abu-dhabi-liveability_data_20260730-v45-plot-detail-audited-relationships-20260913"
ONTOLOGY_VERSION = "abu-dhabi-liveability-ontology-v44-plot-detail-audited-relationships-20260913"
BUNDLE_ID = "abu-dhabi-liveability-current-20260913-plot-detail-audited-relationships-v45"


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"artifact_object_required:{path.name}")
    return value


def _raw(value: Mapping[str, Any]) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _write_new(path: Path, value: Mapping[str, Any]) -> str:
    if path.exists():
        raise RuntimeError(f"immutable_output_already_exists:{path.name}")
    raw = _raw(value)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(raw)
    temporary.replace(path)
    return _sha(raw)


def _write_mutable(path: Path, value: Mapping[str, Any]) -> None:
    raw = _raw(value)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(raw)
    temporary.replace(path)


def _relative(path: Path) -> str:
    return path.resolve().relative_to(ROOT.resolve()).as_posix()


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


def _rebind_relationship_evidence(value: Any, path: str, sha256: str) -> Any:
    """Point runtime relationship evidence at the audit produced in this run.

    The inherited v45 payload contains historical relationship evidence for the
    two plot-to-district joins.  Those joins are re-probed against the current
    source binding, so every relationship object carrying the old audit path
    must carry the new path and digest as well.  This is deliberately limited
    to ``evidence_path``/``evidence_sha256`` fields and does not rewrite
    historical semantic-evolution entries.
    """
    if isinstance(value, list):
        return [_rebind_relationship_evidence(item, path, sha256) for item in value]
    if not isinstance(value, dict):
        return value
    has_relationship_audit = any(
        key == "evidence_path"
        and isinstance(item, str)
        and "plot_relationship_source_audit_" in item
        for key, item in value.items()
    )
    result = {}
    for key, item in value.items():
        if has_relationship_audit and key == "evidence_path":
            result[key] = path
        elif has_relationship_audit and key == "evidence_sha256":
            result[key] = sha256
        else:
            result[key] = _rebind_relationship_evidence(item, path, sha256)
    return result


def _binding() -> tuple[dict[str, Any], dict[str, Any]]:
    _load_environment()
    discovery = get_virtual_source_discovery(SOURCE_ID, OWNER)
    if not discovery or discovery.get("discovery_status") != "succeeded":
        raise RuntimeError("source_discovery_not_succeeded")
    snapshot = discovery.get("discovery_snapshot") or {}
    profile = discovery.get("profile_snapshot") or {}
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
    if not binding["database_name"] or binding["allowed_schemas"] != ["public"] or any(
        len(binding[key]) != 64 for key in ("discovery_fingerprint", "profile_fingerprint")
    ):
        raise RuntimeError("source_binding_incomplete")
    return binding, snapshot


def publish() -> dict[str, Any]:
    binding, snapshot = _binding()
    catalog = _load(INPUT_CATALOG)
    compatibility = _assert_additive_compatible(catalog, snapshot)
    semantic = _rebind(_load(INPUT_SEMANTIC), binding["discovery_fingerprint"], binding["profile_fingerprint"])
    ontology = _rebind(_load(INPUT_ONTOLOGY), binding["discovery_fingerprint"], binding["profile_fingerprint"])
    semantic["source_binding"] = copy.deepcopy(binding)
    ontology["source_evidence"] = {**(ontology.get("source_evidence") or {}), **binding, "contains_source_rows": False}

    # Reuse the published aggregate-only probe implementation after rebinding.
    source_audit = asyncio.run(v45._audit_source(semantic))
    source_audit["rebind"] = {
        "reason": "registered_source_endpoint_port_changed_5444_to_5443",
        "previous_artifacts_preserved": True,
        "schema_compatibility": compatibility,
    }
    source_audit_sha = _sha(_raw(source_audit))

    relationship_evidence_path = _relative(OUTPUT_SOURCE_AUDIT)
    semantic = _rebind_relationship_evidence(semantic, relationship_evidence_path, source_audit_sha)
    ontology = _rebind_relationship_evidence(ontology, relationship_evidence_path, source_audit_sha)

    semantic["semantic_version"] = SEMANTIC_VERSION
    semantic["artifact_bundle_id"] = BUNDLE_ID
    semantic["ontology_overlay"] = _relative(OUTPUT_ONTOLOGY)
    ontology["ontology_enrichment_version"] = ONTOLOGY_VERSION
    ontology["overlay_id"] = ONTOLOGY_VERSION
    ontology["artifact_bundle_id"] = BUNDLE_ID
    for payload in (semantic, ontology):
        evolution = payload.get("semantic_evolution")
        if isinstance(evolution, dict):
            evolution["source_evidence"] = [
                *[item for item in evolution.get("source_evidence") or [] if item.get("path") != _relative(OUTPUT_SOURCE_AUDIT)],
                {
                    "path": _relative(OUTPUT_SOURCE_AUDIT),
                    "sha256": source_audit_sha,
                    "benchmark_questions_used": False,
                    "gold_sql_used": False,
                    "gold_results_used": False,
                    "model_outputs_used": False,
                },
            ]
            evolution["source_rows_persisted"] = False
            evolution["benchmark_questions_used"] = False
            evolution["gold_sql_used"] = False
            evolution["gold_results_used"] = False
            evolution["model_outputs_used"] = False

    _validate_metric_contracts(semantic)
    _validate_row_scope_policies(semantic)
    _validate_semantic_answerability_contracts(semantic)
    _validate_semantic_caveats(semantic)
    validate_projection_completeness_policies(semantic)
    validate_derived_projection_policies(semantic)
    validate_semantic_evolution(semantic, ontology)
    if ontology.get("runtime_answerability_contracts") != semantic.get("semantic_answerability_contracts"):
        raise RuntimeError("ontology_runtime_answerability_contracts_out_of_sync")
    if ontology.get("semantic_answerability_contracts") != semantic.get("semantic_answerability_contracts"):
        raise RuntimeError("ontology_semantic_answerability_contracts_out_of_sync")
    if ontology.get("runtime_metric_contracts") != semantic.get("metric_contracts"):
        raise RuntimeError("ontology_runtime_metric_contracts_out_of_sync")

    catalog = _rebind(catalog, binding["discovery_fingerprint"], binding["profile_fingerprint"])
    catalog["source_evidence"] = {**(catalog.get("source_evidence") or {}), **binding, "contains_source_rows": False}
    catalog["artifact_bundle_id"] = BUNDLE_ID
    catalog_sha = _write_new(OUTPUT_CATALOG, catalog)
    source_audit_sha = _write_new(OUTPUT_SOURCE_AUDIT, source_audit)
    semantic_sha = _write_new(OUTPUT_SEMANTIC, semantic)
    ontology_sha = _write_new(OUTPUT_ONTOLOGY, ontology)
    publication = {
        "schema": "gda.liveability-v45-plot-detail-audited-relationships-publication-audit.v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "status": "complete",
        "semantic_version": SEMANTIC_VERSION,
        "ontology_version": ONTOLOGY_VERSION,
        "source_audit_sha256": source_audit_sha,
        "semantic_sha256": semantic_sha,
        "ontology_sha256": ontology_sha,
        "catalog_sha256": catalog_sha,
        "source": source_audit["source"],
        "relationships": source_audit["relationships"],
        "detail_contract_ids": [
            "LIVEABILITY_PLOT_DETAIL_DIM_PARKS_CALC_PLOTS_V1",
            "LIVEABILITY_PLOT_DETAIL_DIM_UDM_PLOTS_V1",
        ],
        "publication": {
            "status": "published_v45_current_source_rebind",
            "purpose": "plot_detail_and_audited_district_relationships",
            "rebind_reason": "registered_source_endpoint_port_changed_5444_to_5443",
            "benchmark_questions_used": False,
            "gold_sql_used": False,
            "gold_results_used": False,
            "model_outputs_used": False,
            "source_rows_persisted": False,
        },
    }
    publication_sha = _write_new(OUTPUT_PUBLICATION_AUDIT, publication)

    bundle = copy.deepcopy(_load(BUNDLE))
    bundle.update({
        "artifact_bundle_id": BUNDLE_ID,
        "bundle_id": BUNDLE_ID,
        "semantic_version": SEMANTIC_VERSION,
        "ontology_version": ONTOLOGY_VERSION,
        "generated_at": datetime.now(UTC).isoformat(),
        "source": binding,
    })
    artifacts = bundle.setdefault("artifacts", {})
    artifacts["semantic"] = {"role": "runtime_semantic_layer", "path": _relative(OUTPUT_SEMANTIC), "sha256": semantic_sha}
    artifacts["ontology"] = {"role": "ontology_overlay", "path": _relative(OUTPUT_ONTOLOGY), "sha256": ontology_sha}
    artifacts["catalog"] = {"role": "technical_metadata_catalog", "path": _relative(OUTPUT_CATALOG), "sha256": catalog_sha}
    artifacts["plot_relationship_source_audit"] = {"role": "source_relationship_aggregate_audit", "path": _relative(OUTPUT_SOURCE_AUDIT), "sha256": source_audit_sha}
    artifacts["plot_detail_audited_relationships_publication_audit"] = {"role": "plot_detail_and_relationship_publication_audit", "path": _relative(OUTPUT_PUBLICATION_AUDIT), "sha256": publication_sha}
    bundle["claim_boundary"] = {**(bundle.get("claim_boundary") or {}), "source_rows_persisted": False}
    _write_mutable(BUNDLE, bundle)
    return {
        "status": "published",
        "source": binding,
        "schema_compatibility": compatibility,
        "semantic": _relative(OUTPUT_SEMANTIC),
        "ontology": _relative(OUTPUT_ONTOLOGY),
        "catalog": _relative(OUTPUT_CATALOG),
        "source_audit": _relative(OUTPUT_SOURCE_AUDIT),
        "publication_audit": _relative(OUTPUT_PUBLICATION_AUDIT),
        "bundle": _relative(BUNDLE),
    }


if __name__ == "__main__":
    print(json.dumps(publish(), ensure_ascii=False, indent=2))
