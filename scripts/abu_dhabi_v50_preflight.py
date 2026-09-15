#!/usr/bin/env python3
"""Verify a versioned Liveability artifact bundle and runtime evidence boundary."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
from pathlib import Path
from urllib.parse import urlsplit

from data_agent.abu_dhabi_artifact_registry import (
    current_artifact_manifest,
    current_artifact_path,
)
from data_agent.free_form_nl2sql_benchmark import _validate_benchmark
from data_agent.migration_runner import verify_schema_state
from data_agent.virtual_source_operator import _load_environment
from data_agent.virtual_sources import (
    discover_virtual_source,
    get_virtual_source,
    get_virtual_source_discovery,
)


EXPECTED_CONTRACT_KINDS = {
    "LIVEABILITY_FPP_SUPPLY_BY_TYPE_STAGE_V1": "wide_stage_unpivot",
    "LIVEABILITY_INFRASTRUCTURE_COMPLETION_BY_ASSET_STAGE_V1": "wide_stage_unpivot",
    "LIVEABILITY_DISTRICT_SCORE_STAGE_DETAIL_WITH_COVERAGE_V1": "detail_with_partition_total",
    "LIVEABILITY_FPP_UNIVERSAL_EXISTING_SUPPLY_COVERAGE_V1": "universal_coverage",
}


def _load_artifact(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _walk_runtime_artifact(value: object) -> None:
    """Reject executable/private evaluation payloads while allowing audit flags."""

    if isinstance(value, dict):
        for key, item in value.items():
            folded = str(key).casefold()
            if folded in {"gold_sql", "gold_result", "source_rows"} and item not in (
                False,
                None,
                "",
                [],
                {},
            ):
                raise ValueError("runtime_artifact_contains_blocked_payload")
            if folded in {"source_rows_persisted", "source_result_rows_persisted"} and item is True:
                raise ValueError("runtime_artifact_source_rows_persisted")
            _walk_runtime_artifact(item)
    elif isinstance(value, list):
        for item in value:
            _walk_runtime_artifact(item)


def _require_false(mapping: dict, *keys: str) -> None:
    for key in keys:
        if mapping.get(key) is not False:
            raise ValueError(f"audit_boundary_not_false:{key}")


def _validate_v50_artifacts(
    *,
    manifest: dict,
    paths: dict[str, Path],
    source_id: int,
    discovery: str,
    profile: str,
    semantic_revision: int,
    ontology_revision: int,
    require_technical_schema_drift: bool,
) -> tuple[dict, dict, dict, dict]:
    semantic = _load_artifact(paths["semantic"])
    ontology = _load_artifact(paths["ontology"])
    benchmark = _load_artifact(paths["benchmark"])
    source_audit = _load_artifact(paths["table_card_metric_compositions_source_audit"])
    publication = _load_artifact(paths["table_card_metric_compositions_publication_audit"])

    if f"-v{semantic_revision}-" not in str(semantic.get("semantic_version") or ""):
        raise ValueError(f"semantic_artifact_revision_missing:v{semantic_revision}")
    if f"-v{ontology_revision}-" not in str(ontology.get("ontology_enrichment_version") or ""):
        raise ValueError(f"ontology_overlay_revision_missing:v{ontology_revision}")
    binding = semantic.get("source_binding") or {}
    for key, expected in (
        ("source_id", source_id),
        ("discovery_fingerprint", discovery),
        ("profile_fingerprint", profile),
    ):
        if binding.get(key) != expected:
            raise ValueError(f"semantic_source_binding_mismatch:{key}")

    contracts = {
        item.get("contract_id"): item
        for item in semantic.get("metric_contracts") or []
        if isinstance(item, dict)
    }
    if not EXPECTED_CONTRACT_KINDS.keys() <= contracts.keys():
        raise ValueError("v50_metric_composition_contracts_missing")
    for contract_id, kind in EXPECTED_CONTRACT_KINDS.items():
        contract = contracts[contract_id]
        if (contract.get("metric_composition") or {}).get("kind") != kind:
            raise ValueError(f"v50_metric_composition_kind_mismatch:{contract_id}")
        if (contract.get("direct_execution") or {}).get("enabled") is not True:
            raise ValueError(f"v50_metric_composition_not_executable:{contract_id}")
    if require_technical_schema_drift:
        drift = semantic.get("technical_schema_drift") or {}
        if (
            drift.get("table") != "public.param_prioritization_category_weights"
            or drift.get("field") != "include_in_facility_scores"
            or drift.get("business_definition_status") != "pending_customer_governance"
            or drift.get("runtime_behavior") != "technical_metadata_only"
            or drift.get("source_rows_persisted") is not False
        ):
            raise ValueError("v51_technical_schema_drift_boundary_invalid")

    if source_audit.get("status") != "passed":
        raise ValueError("v50_source_audit_not_passed")
    audit_source = source_audit.get("source") or {}
    for key, expected in (
        ("source_id", source_id),
        ("discovery_fingerprint", discovery),
        ("profile_fingerprint", profile),
    ):
        if audit_source.get(key) != expected:
            raise ValueError(f"v50_source_audit_binding_mismatch:{key}")
    boundary = source_audit.get("claim_boundary") or {}
    _require_false(
        boundary,
        "benchmark_questions_used",
        "gold_sql_used",
        "gold_results_used",
        "model_outputs_used",
        "source_rows_persisted",
        "source_result_rows_persisted",
    )
    if boundary.get("read_only_query_execution") is not True:
        raise ValueError("v50_source_audit_not_read_only")
    probes = source_audit.get("contract_probes") or {}
    if set(probes) != set(EXPECTED_CONTRACT_KINDS):
        raise ValueError("v50_source_audit_contract_coverage_mismatch")
    for contract_id, probe in probes.items():
        if probe.get("source_rows_persisted") is not False:
            raise ValueError(f"v50_probe_rows_persisted:{contract_id}")
        if len(str(probe.get("statement_sha256") or "")) != 64:
            raise ValueError(f"v50_probe_statement_digest_invalid:{contract_id}")
        if not isinstance(probe.get("row_count"), int) or not isinstance(probe.get("columns"), list):
            raise ValueError(f"v50_probe_summary_invalid:{contract_id}")

    if publication.get("status") != "complete":
        raise ValueError("v50_publication_audit_incomplete")
    if publication.get("semantic_version") != semantic.get("semantic_version"):
        raise ValueError("v50_publication_semantic_version_mismatch")
    if publication.get("ontology_version") != ontology.get("ontology_enrichment_version"):
        raise ValueError("v50_publication_ontology_version_mismatch")
    if publication.get("semantic_sha256") != _sha256(paths["semantic"]):
        raise ValueError("v50_publication_semantic_checksum_mismatch")
    if publication.get("ontology_sha256") != _sha256(paths["ontology"]):
        raise ValueError("v50_publication_ontology_checksum_mismatch")
    if publication.get("source_audit_sha256") != _sha256(paths["table_card_metric_compositions_source_audit"]):
        raise ValueError("v50_publication_source_audit_checksum_mismatch")
    published = publication.get("publication") or {}
    if set(published.get("contract_ids") or []) != set(EXPECTED_CONTRACT_KINDS):
        raise ValueError("v50_publication_contract_coverage_mismatch")
    _require_false(
        published,
        "benchmark_questions_used",
        "gold_sql_used",
        "gold_results_used",
        "model_outputs_used",
        "source_rows_persisted",
    )

    _validate_benchmark(benchmark, semantic, source_id=source_id, benchmark_path=paths["benchmark"])
    private_gold = (manifest.get("artifacts") or {}).get("benchmark_private_gold") or {}
    if private_gold.get("runtime_usage_prohibited") is not True:
        raise ValueError("benchmark_private_gold_runtime_boundary_missing")
    _walk_runtime_artifact(semantic)
    _walk_runtime_artifact(ontology)
    return semantic, ontology, benchmark, source_audit


async def run(
    *,
    source_id: int,
    owner: str,
    expected_port: int,
    semantic_revision: int = 50,
    ontology_revision: int = 49,
    require_technical_schema_drift: bool = False,
) -> dict:
    _load_environment()
    source = get_virtual_source(source_id, owner)
    if source is None:
        raise ValueError("registered_source_unavailable")
    endpoint_port = urlsplit(str(source.get("endpoint_url") or "")).port
    if endpoint_port != expected_port:
        raise ValueError(f"source_endpoint_port_mismatch:{endpoint_port}:{expected_port}")
    if source.get("source_type") != "database" or not source.get("enabled"):
        raise ValueError("registered_database_source_not_enabled")
    if source.get("health_status") != "healthy":
        raise ValueError(f"source_health_not_healthy:{source.get('health_status')}")
    if source.get("credential_status") != "available":
        raise ValueError("source_credentials_unavailable")

    migration = verify_schema_state()
    persisted = get_virtual_source_discovery(source_id, owner)
    if persisted is None or persisted.get("discovery_status") != "succeeded":
        raise ValueError("persisted_discovery_not_succeeded")
    persisted_snapshot = persisted.get("discovery_snapshot") or {}
    if persisted_snapshot.get("contains_source_rows") is not False:
        raise ValueError("persisted_discovery_contains_source_rows")
    if persisted_snapshot.get("truncated") is not False:
        raise ValueError("persisted_discovery_truncated")
    discovery = str(persisted.get("discovery_fingerprint") or "")
    profile = str(persisted.get("profile_fingerprint") or "")
    if len(discovery) != 64 or len(profile) != 64:
        raise ValueError("persisted_discovery_fingerprint_invalid")

    fresh = await discover_virtual_source(source_id, owner)
    if fresh.get("status") != "ok" or fresh.get("discovery_status") != "succeeded":
        raise ValueError(f"rediscovery_failed:{fresh.get('message') or fresh.get('status')}")
    if fresh.get("discovery_fingerprint") != discovery:
        raise ValueError("discovery_fingerprint_changed")
    if fresh.get("profile_fingerprint") != profile:
        raise ValueError("profile_fingerprint_changed")
    fresh_snapshot = fresh.get("snapshot") or {}
    if fresh_snapshot.get("contains_source_rows") is not False or fresh_snapshot.get("truncated") is not False:
        raise ValueError("rediscovery_metadata_boundary_invalid")

    manifest = current_artifact_manifest("liveability")
    manifest_source = manifest.get("source") or {}
    for key, expected in (
        ("source_id", source_id),
        ("database_name", "liveability_data_20260730"),
        ("allowed_schemas", ["public"]),
        ("discovery_fingerprint", discovery),
        ("profile_fingerprint", profile),
    ):
        if manifest_source.get(key) != expected:
            raise ValueError(f"artifact_bundle_source_mismatch:{key}")
    roles = (
        "semantic",
        "ontology",
        "catalog",
        "benchmark",
        "table_card_metric_compositions_source_audit",
        "table_card_metric_compositions_publication_audit",
    )
    paths = {role: current_artifact_path("liveability", role) for role in roles}
    semantic, ontology, benchmark, audit = _validate_v50_artifacts(
        manifest=manifest,
        paths=paths,
        source_id=source_id,
        discovery=discovery,
        profile=profile,
        semantic_revision=semantic_revision,
        ontology_revision=ontology_revision,
        require_technical_schema_drift=require_technical_schema_drift,
    )
    return {
        "status": "ok",
        "source_id": source_id,
        "endpoint_port": endpoint_port,
        "health_status": source.get("health_status"),
        "migration_status": migration.status,
        "discovery_status": fresh.get("discovery_status"),
        "discovery_fingerprint": discovery,
        "profile_fingerprint": profile,
        "semantic_version": semantic.get("semantic_version"),
        "ontology_version": ontology.get("ontology_enrichment_version"),
        "expected_semantic_revision": semantic_revision,
        "expected_ontology_revision": ontology_revision,
        "metric_composition_contract_ids": sorted(EXPECTED_CONTRACT_KINDS),
        "metric_contract_count": len(semantic.get("metric_contracts") or []),
        "benchmark_id": benchmark.get("benchmark_id"),
        "benchmark_case_count": len(benchmark.get("cases") or []),
        "source_audit_probe_count": len(audit.get("contract_probes") or {}),
        "source_rows_persisted": False,
        "gold_sql_runtime_accessible": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-id", type=int, default=12)
    parser.add_argument("--owner", default="abu-dhabi-site-operator")
    parser.add_argument("--expected-port", type=int, default=5443)
    parser.add_argument("--semantic-revision", type=int, default=50)
    parser.add_argument("--ontology-revision", type=int, default=49)
    parser.add_argument("--require-technical-schema-drift", action="store_true")
    args = parser.parse_args()
    try:
        result = asyncio.run(
            run(
                source_id=args.source_id,
                owner=args.owner,
                expected_port=args.expected_port,
                semantic_revision=args.semantic_revision,
                ontology_revision=args.ontology_revision,
                require_technical_schema_drift=args.require_technical_schema_drift,
            )
        )
    except Exception as exc:
        print(json.dumps({"status": "error", "error": str(exc)}), file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
