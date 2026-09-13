#!/usr/bin/env python3
"""Run the source, artifact, and runtime-boundary checks for v45."""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from urllib.parse import urlsplit

from data_agent.abu_dhabi_artifact_registry import (
    current_artifact_manifest,
    current_artifact_path,
)
from data_agent.migration_runner import verify_schema_state
from data_agent.virtual_source_operator import _load_environment
from data_agent.virtual_sources import (
    discover_virtual_source,
    get_virtual_source,
    get_virtual_source_discovery,
)


def _walk_runtime_artifact(value: object) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            folded = str(key).casefold()
            # Published artifacts may carry explicit negative audit markers
            # such as ``gold_sql: false``.  Those markers are not payloads and
            # must not make a valid runtime artifact fail closed.  Any actual
            # SQL/result/row material remains prohibited.
            if folded in {"gold_sql", "gold_result", "source_rows"} and item not in (
                False,
                None,
                "",
                [],
                {},
            ):
                raise ValueError("runtime_artifact_contains_blocked_payload")
            if folded == "source_rows_persisted" and item is True:
                raise ValueError("runtime_artifact_source_rows_persisted")
            _walk_runtime_artifact(item)
    elif isinstance(value, list):
        for item in value:
            _walk_runtime_artifact(item)


def _load_artifact(path):
    return json.loads(path.read_text(encoding="utf-8"))


async def run(*, source_id: int, owner: str, expected_port: int) -> dict:
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

    expected_discovery = str(persisted.get("discovery_fingerprint") or "")
    expected_profile = str(persisted.get("profile_fingerprint") or "")
    fresh = await discover_virtual_source(source_id, owner)
    if fresh.get("status") != "ok" or fresh.get("discovery_status") != "succeeded":
        raise ValueError(f"rediscovery_failed:{fresh.get('message') or fresh.get('status')}")
    if fresh.get("discovery_fingerprint") != expected_discovery:
        raise ValueError("discovery_fingerprint_changed")
    if fresh.get("profile_fingerprint") != expected_profile:
        raise ValueError("profile_fingerprint_changed")
    snapshot = fresh.get("snapshot") or {}
    if snapshot.get("contains_source_rows") is not False:
        raise ValueError("rediscovery_contains_source_rows")
    if snapshot.get("truncated") is not False:
        raise ValueError("rediscovery_truncated")

    manifest = current_artifact_manifest("liveability")
    manifest_source = manifest.get("source") or {}
    if manifest.get("status") != "current_source_bound":
        raise ValueError("artifact_bundle_not_current")
    if int(manifest_source.get("source_id") or -1) != source_id:
        raise ValueError("artifact_bundle_source_mismatch")
    if manifest_source.get("database_name") != "liveability_data_20260730":
        raise ValueError("artifact_bundle_database_mismatch")
    if manifest_source.get("allowed_schemas") != ["public"]:
        raise ValueError("artifact_bundle_schema_scope_mismatch")
    if manifest_source.get("discovery_fingerprint") != expected_discovery:
        raise ValueError("artifact_bundle_discovery_fingerprint_mismatch")
    if manifest_source.get("profile_fingerprint") != expected_profile:
        raise ValueError("artifact_bundle_profile_fingerprint_mismatch")

    roles = (
        "semantic",
        "ontology",
        "catalog",
        "plot_relationship_source_audit",
        "plot_detail_audited_relationships_publication_audit",
    )
    paths = {role: current_artifact_path("liveability", role) for role in roles}
    semantic = _load_artifact(paths["semantic"])
    ontology = _load_artifact(paths["ontology"])
    source_audit = _load_artifact(paths["plot_relationship_source_audit"])
    publication = _load_artifact(
        paths["plot_detail_audited_relationships_publication_audit"]
    )
    if "-v45-" not in str(semantic.get("semantic_version")):
        raise ValueError("v45_semantic_artifact_missing")
    if "-v44-" not in str(ontology.get("ontology_enrichment_version")):
        raise ValueError("v44_ontology_overlay_missing")
    if source_audit.get("status") != "passed":
        raise ValueError("plot_relationship_source_audit_not_passed")
    if publication.get("status") != "complete":
        raise ValueError("plot_publication_audit_incomplete")
    if source_audit.get("claim_boundary", {}).get("source_rows_persisted") is not False:
        raise ValueError("plot_audit_source_row_boundary_invalid")
    _walk_runtime_artifact(semantic)
    _walk_runtime_artifact(ontology)

    return {
        "status": "ok",
        "source_id": source_id,
        "endpoint_port": endpoint_port,
        "health_status": source.get("health_status"),
        "discovery_status": fresh.get("discovery_status"),
        "migration_status": migration.status,
        "discovery_fingerprint": expected_discovery,
        "profile_fingerprint": expected_profile,
        "semantic_version": semantic.get("semantic_version"),
        "ontology_version": ontology.get("ontology_enrichment_version"),
        "metric_contract_count": len(semantic.get("metric_contracts") or []),
        "table_binding_count": len(semantic.get("table_bindings") or []),
        "reviewed_asset_count": sum(
            str(item.get("review_status") or "")
            .casefold()
            .startswith("reviewed")
            for item in semantic.get("semantic_assets") or []
        ),
        "relationship_count": len(semantic.get("relationships") or []),
        "source_rows_persisted": False,
        "gold_sql_runtime_accessible": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-id", type=int, default=12)
    parser.add_argument("--owner", default="abu-dhabi-site-operator")
    parser.add_argument("--expected-port", type=int, default=5443)
    args = parser.parse_args()
    try:
        result = asyncio.run(
            run(
                source_id=args.source_id,
                owner=args.owner,
                expected_port=args.expected_port,
            )
        )
    except Exception as exc:
        print(json.dumps({"status": "error", "error": str(exc)}), file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
