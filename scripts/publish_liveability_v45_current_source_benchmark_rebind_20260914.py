#!/usr/bin/env python3
"""Publish immutable v17 evaluation contracts for the current v45 source binding.

The v45 runtime semantic bundle was rebound after the registered source moved
from port 5444 to 5443.  The v15 benchmark remained bound to the previous
metadata fingerprint, which correctly prevented a new full evaluation.  This
publisher forks the public benchmark and its private Gold contracts while
proving that only source-binding metadata and artifact references changed.
"""

from __future__ import annotations

import copy
import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from data_agent.free_form_nl2sql_benchmark import _validate_benchmark
import publish_liveability_v15_discovery_rebind_benchmark_20260911 as v15


ARTIFACT_ROOT = ROOT / "docs/customer/abu_dhabi_liveability_site_validation"
INPUT_BENCHMARK = ARTIFACT_ROOT / "liveability_customer_strict_gold_benchmark_v15_20260911.json"
INPUT_PRIVATE_GOLD = (
    ARTIFACT_ROOT / "liveability_customer_strict_gold_benchmark_v15_20260911_private_gold.json"
)
SEMANTIC = ARTIFACT_ROOT / "liveability_data_20260730_semantic_layer_v45_plot_detail_audited_relationships_20260913.json"
ONTOLOGY = ARTIFACT_ROOT / "liveability_data_20260730_ontology_v44_plot_detail_audited_relationships_20260913.json"
SOURCE_AUDIT = ARTIFACT_ROOT / "liveability_v45_plot_relationship_source_audit_20260913.json"
CURRENT_BUNDLE = ARTIFACT_ROOT / "abu_dhabi_current_artifact_bundle.json"

OUTPUT_BENCHMARK = ARTIFACT_ROOT / "liveability_customer_strict_gold_benchmark_v17_20260914.json"
OUTPUT_PRIVATE_GOLD = (
    ARTIFACT_ROOT / "liveability_customer_strict_gold_benchmark_v17_20260914_private_gold.json"
)
OUTPUT_CONTRACT_DIR = (
    ARTIFACT_ROOT / "evaluation_private/liveability_customer_strict_gold_20260914_v17_endpoint_5443_rebind"
)
OUTPUT_EVIDENCE = (
    ARTIFACT_ROOT / "liveability_customer_strict_gold_benchmark_v17_endpoint_5443_rebind_evidence_20260914.json"
)

BUNDLE_ID = "abu-dhabi-liveability-current-20260913-plot-detail-audited-relationships-v45"
BENCHMARK_ID = "abu-dhabi-liveability-customer-strict-gold-v17"
BENCHMARK_VERSION = "17.0.0-v45-current-source-metadata-rebind-20260914"
REBIND_REASON = "v45_endpoint_port_5443_metadata_rebind"
BINDING_KEYS = (
    "source_id",
    "database_name",
    "allowed_schemas",
    "discovery_fingerprint",
    "profile_fingerprint",
    "execution_mode",
)


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"object_required:{v15._relative(path)}")
    return value


def _binding_from_published_v45() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    semantic = _load(SEMANTIC)
    ontology = _load(ONTOLOGY)
    source_audit = _load(SOURCE_AUDIT)
    bundle = _load(CURRENT_BUNDLE)
    binding = copy.deepcopy(semantic.get("source_binding") or {})
    if any(binding.get(key) in (None, "", []) for key in BINDING_KEYS):
        raise RuntimeError("v45_semantic_source_binding_incomplete")
    if semantic.get("semantic_version") != (
        "abu-dhabi-liveability_data_20260730-v45-plot-detail-audited-relationships-20260913"
    ):
        raise RuntimeError("current_v45_semantic_version_required")
    if ontology.get("ontology_enrichment_version") != (
        "abu-dhabi-liveability-ontology-v44-plot-detail-audited-relationships-20260913"
    ):
        raise RuntimeError("current_v45_ontology_version_required")
    if semantic.get("artifact_bundle_id") != BUNDLE_ID or ontology.get("artifact_bundle_id") != BUNDLE_ID:
        raise RuntimeError("v45_bundle_identity_mismatch")
    if source_audit.get("status") != "passed":
        raise RuntimeError("v45_source_audit_not_passed")
    audited_binding = {
        key: copy.deepcopy((source_audit.get("source") or {}).get(key))
        for key in BINDING_KEYS
    }
    if audited_binding != binding:
        raise RuntimeError("v45_source_audit_binding_mismatch")
    if bundle.get("artifact_bundle_id") != BUNDLE_ID or bundle.get("source") != binding:
        raise RuntimeError("current_bundle_v45_binding_mismatch")
    for role, expected_path in (("semantic", SEMANTIC), ("ontology", ONTOLOGY)):
        descriptor = (bundle.get("artifacts") or {}).get(role) or {}
        if descriptor.get("path") != v15._relative(expected_path) or descriptor.get("sha256") != v15._sha(expected_path):
            raise RuntimeError(f"current_bundle_{role}_checksum_mismatch")
    return binding, semantic, ontology, bundle


def _assert_outputs_absent(contract_paths: Mapping[str, Path]) -> None:
    targets = [OUTPUT_BENCHMARK, OUTPUT_PRIVATE_GOLD, OUTPUT_EVIDENCE]
    targets.extend(OUTPUT_CONTRACT_DIR / path.name for path in contract_paths.values())
    existing = [v15._relative(path) for path in targets if path.exists()]
    if OUTPUT_CONTRACT_DIR.exists() or existing:
        if OUTPUT_CONTRACT_DIR.exists() and v15._relative(OUTPUT_CONTRACT_DIR) not in existing:
            existing.append(v15._relative(OUTPUT_CONTRACT_DIR))
        raise RuntimeError("immutable_v17_output_already_exists:" + ",".join(sorted(existing)))


def _rebound_contract(
    original: Mapping[str, Any],
    *,
    binding: Mapping[str, Any],
    semantic_version: str,
    ontology_overlay_id: str,
    parent_path: Path,
    rebound_at: str,
) -> dict[str, Any]:
    result = v15._rebound_contract(
        original,
        binding=binding,
        semantic_version=semantic_version,
        ontology_overlay_id=ontology_overlay_id,
        parent_path=parent_path,
        parent_sha=v15._sha(parent_path),
        rebound_at=rebound_at,
    )
    result["source_rebind"]["reason_code"] = REBIND_REASON
    if v15._contract_invariant(original) != v15._contract_invariant(result):
        raise RuntimeError(f"gold_content_changed_during_v45_rebind:{parent_path.name}")
    return result


def _rebound_benchmark(
    original: Mapping[str, Any],
    *,
    binding: Mapping[str, Any],
    semantic_version: str,
    contract_references: Mapping[str, dict[str, Any]],
    rebound_at: str,
) -> dict[str, Any]:
    result = v15._rebound_benchmark(
        original,
        binding=binding,
        semantic_version=semantic_version,
        parent_sha=v15._sha(INPUT_BENCHMARK),
        contract_references=contract_references,
        rebound_at=rebound_at,
    )
    result["benchmark_id"] = BENCHMARK_ID
    result["version"] = BENCHMARK_VERSION
    result["source_rebind"].update(
        {
            "reason_code": REBIND_REASON,
            "parent_benchmark": v15._relative(INPUT_BENCHMARK),
            "parent_benchmark_sha256": v15._sha(INPUT_BENCHMARK),
        }
    )
    if v15._benchmark_invariant(original) != v15._benchmark_invariant(result):
        raise RuntimeError("benchmark_content_changed_during_v45_rebind")
    return result


def _rebind_current_bundle(
    bundle: Mapping[str, Any],
    *,
    binding: Mapping[str, Any],
    benchmark_sha: str,
    private_sha: str,
    evidence_sha: str,
    generated_at: str,
) -> dict[str, Any]:
    result = copy.deepcopy(dict(bundle))
    if result.get("artifact_bundle_id") != BUNDLE_ID or result.get("source") != binding:
        raise RuntimeError("current_bundle_changed_before_v17_pointer_update")
    artifacts = result.setdefault("artifacts", {})
    artifacts["benchmark"] = {
        "role": "business_benchmark",
        "path": v15._relative(OUTPUT_BENCHMARK),
        "sha256": benchmark_sha,
    }
    artifacts["benchmark_private_gold"] = {
        "role": "evaluation_private_gold_bundle",
        "path": v15._relative(OUTPUT_PRIVATE_GOLD),
        "sha256": private_sha,
        "runtime_usage_prohibited": True,
    }
    artifacts["benchmark_revision_evidence"] = {
        "role": "evaluation_only_revision_evidence",
        "path": v15._relative(OUTPUT_EVIDENCE),
        "sha256": evidence_sha,
        "runtime_usage_prohibited": True,
    }
    result["generated_at"] = generated_at
    result.setdefault("claim_boundary", {}).update(
        {
            "benchmark_v17_current_source_metadata_rebound": True,
            "benchmark_v17_questions_changed": False,
            "benchmark_v17_gold_sql_changed": False,
            "benchmark_v17_gold_results_changed": False,
            "benchmark_v17_model_outputs_used": False,
            "benchmark_v17_source_rows_persisted": False,
        }
    )
    return result


def publish() -> dict[str, Any]:
    """Fork evaluation-only artifacts, then atomically move the bundle pointers."""

    binding, semantic, ontology, bundle = _binding_from_published_v45()
    original_benchmark = _load(INPUT_BENCHMARK)
    original_private = _load(INPUT_PRIVATE_GOLD)
    source_contract_paths = v15._contract_paths(original_benchmark)
    _assert_outputs_absent(source_contract_paths)
    now = datetime.now(UTC).isoformat()
    semantic_version = str(semantic.get("semantic_version") or "")
    ontology_overlay_id = v15._ontology_id(semantic, ontology)

    rebound_by_parent: dict[str, dict[str, Any]] = {}
    rebound_by_id: dict[str, dict[str, Any]] = {}
    contract_audit: list[dict[str, Any]] = []
    for parent_reference, parent_path in sorted(source_contract_paths.items()):
        rebound = _rebound_contract(
            _load(parent_path),
            binding=binding,
            semantic_version=semantic_version,
            ontology_overlay_id=ontology_overlay_id,
            parent_path=parent_path,
            rebound_at=now,
        )
        contract_id = str(rebound.get("contract_id") or "")
        if not contract_id or contract_id in rebound_by_id:
            raise RuntimeError(f"gold_contract_id_invalid_or_duplicate:{parent_path.name}")
        output_path = OUTPUT_CONTRACT_DIR / parent_path.name
        descriptor = {
            "payload": rebound,
            "parent_path": parent_path,
            "output_path": output_path,
            "reference": {
                "contract_id": contract_id,
                "path": v15._relative(output_path),
                "sha256": "",
            },
        }
        rebound_by_parent[parent_reference] = descriptor
        rebound_by_id[contract_id] = rebound

    for descriptor in rebound_by_parent.values():
        output_sha = v15._write_new(descriptor["output_path"], descriptor["payload"])
        descriptor["reference"]["sha256"] = output_sha
        contract_audit.append(
            {
                "contract_id": descriptor["reference"]["contract_id"],
                "parent_path": v15._relative(descriptor["parent_path"]),
                "parent_sha256": v15._sha(descriptor["parent_path"]),
                "output_path": descriptor["reference"]["path"],
                "output_sha256": output_sha,
                "preserved_gold_content_sha256": v15._sha_value(
                    v15._contract_invariant(descriptor["payload"])
                ),
            }
        )

    references = {
        parent: descriptor["reference"] for parent, descriptor in rebound_by_parent.items()
    }
    rebound_benchmark = _rebound_benchmark(
        original_benchmark,
        binding=binding,
        semantic_version=semantic_version,
        contract_references=references,
        rebound_at=now,
    )
    _validate_benchmark(
        copy.deepcopy(rebound_benchmark),
        copy.deepcopy(semantic),
        source_id=int(binding["source_id"]),
        benchmark_path=OUTPUT_BENCHMARK,
    )
    benchmark_sha = v15._write_new(OUTPUT_BENCHMARK, rebound_benchmark)

    private_contracts: list[dict[str, Any]] = []
    for contract in original_private.get("contracts") or []:
        contract_id = str((contract or {}).get("contract_id") or "")
        if contract_id not in rebound_by_id:
            raise RuntimeError(f"private_gold_contract_not_referenced_by_benchmark:{contract_id}")
        private_contracts.append(copy.deepcopy(rebound_by_id[contract_id]))
    if not private_contracts or len(private_contracts) != len(original_private.get("contracts") or []):
        raise RuntimeError("private_gold_contract_copy_incomplete")
    rebound_private = copy.deepcopy(original_private)
    rebound_private.update(
        {
            "generated_at": now,
            "benchmark": v15._relative(OUTPUT_BENCHMARK),
            "benchmark_sha256": benchmark_sha,
            "contracts": private_contracts,
            "source_rebind": {
                "reason_code": REBIND_REASON,
                "parent_private_gold": v15._relative(INPUT_PRIVATE_GOLD),
                "parent_private_gold_sha256": v15._sha(INPUT_PRIVATE_GOLD),
                "gold_sql_changed": False,
                "gold_results_changed": False,
                "model_outputs_used": False,
                "source_rows_persisted": False,
            },
        }
    )
    private_sha = v15._write_new(OUTPUT_PRIVATE_GOLD, rebound_private)

    evidence = {
        "schema": "gda.liveability-benchmark-discovery-metadata-rebind-evidence.v1",
        "generated_at": now,
        "status": "published",
        "bundle_id": BUNDLE_ID,
        "source": copy.deepcopy(binding),
        "semantic": {
            "path": v15._relative(SEMANTIC),
            "sha256": v15._sha(SEMANTIC),
            "semantic_version": semantic_version,
        },
        "ontology": {"path": v15._relative(ONTOLOGY), "sha256": v15._sha(ONTOLOGY)},
        "source_audit": {"path": v15._relative(SOURCE_AUDIT), "sha256": v15._sha(SOURCE_AUDIT)},
        "input": {
            "benchmark": v15._relative(INPUT_BENCHMARK),
            "benchmark_sha256": v15._sha(INPUT_BENCHMARK),
            "private_gold": v15._relative(INPUT_PRIVATE_GOLD),
            "private_gold_sha256": v15._sha(INPUT_PRIVATE_GOLD),
        },
        "output": {
            "benchmark": v15._relative(OUTPUT_BENCHMARK),
            "benchmark_sha256": benchmark_sha,
            "private_gold": v15._relative(OUTPUT_PRIVATE_GOLD),
            "private_gold_sha256": private_sha,
        },
        "contract_count": len(contract_audit),
        "contracts": sorted(contract_audit, key=lambda item: str(item["contract_id"])),
        "validation": {
            "benchmark_validated_against_current_v45_semantic": True,
            "source_audit_matches_semantic_binding": True,
            "questions_changed": False,
            "gold_sql_changed": False,
            "expected_results_changed": False,
            "equivalence_fingerprints_changed": False,
        },
        "claim_boundary": {
            "benchmark_questions_used_for_runtime": False,
            "gold_sql_available_to_runtime": False,
            "gold_results_available_to_runtime": False,
            "model_outputs_used": False,
            "source_rows_persisted": False,
        },
    }
    evidence_sha = v15._write_new(OUTPUT_EVIDENCE, evidence)
    v15._write_mutable(
        CURRENT_BUNDLE,
        _rebind_current_bundle(
            bundle,
            binding=binding,
            benchmark_sha=benchmark_sha,
            private_sha=private_sha,
            evidence_sha=evidence_sha,
            generated_at=now,
        ),
    )
    return {
        "status": "published",
        "bundle_id": BUNDLE_ID,
        "benchmark": v15._relative(OUTPUT_BENCHMARK),
        "benchmark_sha256": benchmark_sha,
        "private_gold": v15._relative(OUTPUT_PRIVATE_GOLD),
        "private_gold_sha256": private_sha,
        "evidence": v15._relative(OUTPUT_EVIDENCE),
        "contract_count": len(contract_audit),
    }


if __name__ == "__main__":
    print(json.dumps(publish(), ensure_ascii=False, indent=2))
