#!/usr/bin/env python3
"""Fork v18 evaluation contracts for the reviewed v51 source binding.

This is evaluation control-plane code. It changes source-binding metadata and
artifact references only; the invariant check rejects any change to benchmark
questions, Gold SQL, expected results, or equivalence fingerprints.
"""

from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping

from data_agent.free_form_nl2sql_benchmark import _validate_benchmark


ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_ROOT = ROOT / "docs/customer/abu_dhabi_liveability_site_validation"
SOURCE_ID = 12
BINDING_KEYS = (
    "source_id",
    "database_name",
    "allowed_schemas",
    "discovery_fingerprint",
    "profile_fingerprint",
    "execution_mode",
)
INPUT_BENCHMARK = ARTIFACT_ROOT / "liveability_customer_strict_gold_benchmark_v17_20260914.json"
INPUT_PRIVATE_GOLD = ARTIFACT_ROOT / "liveability_customer_strict_gold_benchmark_v17_20260914_private_gold.json"
SEMANTIC = ARTIFACT_ROOT / "liveability_data_20260730_semantic_layer_v51_schema_drift_rebind_20260915.json"
ONTOLOGY = ARTIFACT_ROOT / "liveability_data_20260730_ontology_v50_schema_drift_rebind_20260915.json"
SOURCE_AUDIT = ARTIFACT_ROOT / "liveability_v51_schema_drift_rebind_source_audit_20260915.json"
CURRENT_BUNDLE = ARTIFACT_ROOT / "abu_dhabi_current_artifact_bundle.json"
OUTPUT_BENCHMARK = ARTIFACT_ROOT / "liveability_customer_strict_gold_benchmark_v18_20260915.json"
OUTPUT_PRIVATE_GOLD = ARTIFACT_ROOT / "liveability_customer_strict_gold_benchmark_v18_20260915_private_gold.json"
OUTPUT_CONTRACT_DIR = ARTIFACT_ROOT / "evaluation_private/liveability_customer_strict_gold_20260915_v18_schema_drift_rebind"
OUTPUT_EVIDENCE = ARTIFACT_ROOT / "liveability_customer_strict_gold_benchmark_v18_schema_drift_rebind_evidence_20260915.json"
BUNDLE_ID = "abu-dhabi-liveability-current-20260915-schema-drift-rebind-v51"
BENCHMARK_ID = "abu-dhabi-liveability-customer-strict-gold-v18"
BENCHMARK_VERSION = "18.0.0-v51-schema-drift-rebind-20260915"
REBIND_REASON = "v51_reviewed_technical_schema_drift_rebind"


def _load_module():
    path = ROOT / "scripts/publish_liveability_v15_discovery_rebind_benchmark_20260911.py"
    spec = importlib.util.spec_from_file_location("liveability_v15_rebind_base", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


v15 = _load_module()


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"object_required:{path.name}")
    return value


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _raw(value: Mapping[str, Any]) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8")


def _write_new(path: Path, value: Mapping[str, Any]) -> str:
    if path.exists():
        raise RuntimeError(f"immutable_output_already_exists:{path.name}")
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = _raw(value)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(raw)
    temporary.replace(path)
    return hashlib.sha256(raw).hexdigest()


def _write_bundle(value: Mapping[str, Any]) -> None:
    raw = _raw(value)
    temporary = CURRENT_BUNDLE.with_suffix(CURRENT_BUNDLE.suffix + ".tmp")
    temporary.write_bytes(raw)
    temporary.replace(CURRENT_BUNDLE)


def _relative(path: Path) -> str:
    return path.resolve().relative_to(ROOT.resolve()).as_posix()


def _binding_from_v51() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    semantic = _load(SEMANTIC)
    ontology = _load(ONTOLOGY)
    audit = _load(SOURCE_AUDIT)
    bundle = _load(CURRENT_BUNDLE)
    binding = copy.deepcopy(semantic.get("source_binding") or {})
    if any(binding.get(key) in (None, "", []) for key in BINDING_KEYS):
        raise RuntimeError("v51_semantic_source_binding_incomplete")
    if semantic.get("semantic_version") != "abu-dhabi-liveability_data_20260730-v51-schema-drift-rebind-20260915":
        raise RuntimeError("v51_semantic_version_required")
    if ontology.get("ontology_enrichment_version") != "abu-dhabi-liveability-ontology-v50-schema-drift-rebind-20260915":
        raise RuntimeError("v51_ontology_version_required")
    if semantic.get("artifact_bundle_id") != BUNDLE_ID or ontology.get("artifact_bundle_id") != BUNDLE_ID:
        raise RuntimeError("v51_bundle_identity_mismatch")
    audit_binding = {key: copy.deepcopy((audit.get("source") or {}).get(key)) for key in BINDING_KEYS}
    if audit.get("status") != "passed" or audit_binding != binding:
        raise RuntimeError("v51_source_audit_binding_mismatch")
    if bundle.get("artifact_bundle_id") != BUNDLE_ID or bundle.get("source") != binding:
        raise RuntimeError("current_bundle_v51_binding_mismatch")
    for role, path in (("semantic", SEMANTIC), ("ontology", ONTOLOGY)):
        descriptor = (bundle.get("artifacts") or {}).get(role) or {}
        if descriptor.get("path") != _relative(path) or descriptor.get("sha256") != _sha(path):
            raise RuntimeError(f"current_bundle_{role}_checksum_mismatch")
    return binding, semantic, ontology, bundle


def _assert_outputs_absent(contract_paths: Mapping[str, Path]) -> None:
    targets = [OUTPUT_BENCHMARK, OUTPUT_PRIVATE_GOLD, OUTPUT_EVIDENCE]
    targets.extend(OUTPUT_CONTRACT_DIR / path.name for path in contract_paths.values())
    existing = [path for path in targets if path.exists()]
    if OUTPUT_CONTRACT_DIR.exists() or existing:
        details = [_relative(path) for path in existing]
        if OUTPUT_CONTRACT_DIR.exists() and not details:
            details.append(_relative(OUTPUT_CONTRACT_DIR))
        raise RuntimeError("immutable_v18_output_already_exists:" + ",".join(details))


def _rebound_contract(
    original: Mapping[str, Any], *, binding: Mapping[str, Any], semantic_version: str,
    ontology_overlay_id: str, parent_path: Path, rebound_at: str,
) -> dict[str, Any]:
    result = v15._rebound_contract(
        original,
        binding=binding,
        semantic_version=semantic_version,
        ontology_overlay_id=ontology_overlay_id,
        parent_path=parent_path,
        parent_sha=_sha(parent_path),
        rebound_at=rebound_at,
    )
    result["source_rebind"]["reason_code"] = REBIND_REASON
    if v15._contract_invariant(original) != v15._contract_invariant(result):
        raise RuntimeError(f"gold_content_changed_during_v18_rebind:{parent_path.name}")
    return result


def _rebound_benchmark(
    original: Mapping[str, Any], *, binding: Mapping[str, Any], semantic_version: str,
    references: Mapping[str, dict[str, Any]], rebound_at: str,
) -> dict[str, Any]:
    prior_id, prior_version = v15.BENCHMARK_ID, v15.BENCHMARK_VERSION
    v15.BENCHMARK_ID, v15.BENCHMARK_VERSION = BENCHMARK_ID, BENCHMARK_VERSION
    try:
        result = v15._rebound_benchmark(
            original,
            binding=binding,
            semantic_version=semantic_version,
            parent_sha=_sha(INPUT_BENCHMARK),
            contract_references=references,
            rebound_at=rebound_at,
        )
    finally:
        v15.BENCHMARK_ID, v15.BENCHMARK_VERSION = prior_id, prior_version
    result["source_rebind"]["reason_code"] = REBIND_REASON
    result["source_rebind"]["parent_benchmark"] = _relative(INPUT_BENCHMARK)
    if v15._benchmark_invariant(original) != v15._benchmark_invariant(result):
        raise RuntimeError("benchmark_content_changed_during_v18_rebind")
    return result


def publish() -> dict[str, Any]:
    binding, semantic, ontology, bundle = _binding_from_v51()
    original_benchmark = _load(INPUT_BENCHMARK)
    original_private = _load(INPUT_PRIVATE_GOLD)
    paths = v15._contract_paths(original_benchmark)
    _assert_outputs_absent(paths)
    now = datetime.now(UTC).isoformat()
    semantic_version = str(semantic["semantic_version"])
    ontology_id = str(ontology.get("overlay_id") or "")
    if not ontology_id:
        raise RuntimeError("v51_ontology_overlay_id_missing")

    rebound_by_parent: dict[str, dict[str, Any]] = {}
    rebound_by_id: dict[str, dict[str, Any]] = {}
    audit_rows: list[dict[str, Any]] = []
    for parent_ref, parent_path in sorted(paths.items()):
        payload = _rebound_contract(
            _load(parent_path), binding=binding, semantic_version=semantic_version,
            ontology_overlay_id=ontology_id, parent_path=parent_path, rebound_at=now,
        )
        contract_id = str(payload.get("contract_id") or "")
        if not contract_id or contract_id in rebound_by_id:
            raise RuntimeError(f"gold_contract_id_invalid_or_duplicate:{parent_path.name}")
        descriptor = {
            "payload": payload,
            "parent_path": parent_path,
            "output_path": OUTPUT_CONTRACT_DIR / parent_path.name,
            "reference": {"contract_id": contract_id, "path": _relative(OUTPUT_CONTRACT_DIR / parent_path.name), "sha256": ""},
        }
        rebound_by_parent[parent_ref] = descriptor
        rebound_by_id[contract_id] = payload
    for descriptor in rebound_by_parent.values():
        output_sha = _write_new(descriptor["output_path"], descriptor["payload"])
        descriptor["reference"]["sha256"] = output_sha
        audit_rows.append(
            {
                "contract_id": descriptor["reference"]["contract_id"],
                "parent_path": _relative(descriptor["parent_path"]),
                "parent_sha256": _sha(descriptor["parent_path"]),
                "output_path": descriptor["reference"]["path"],
                "output_sha256": output_sha,
                "preserved_gold_content_sha256": v15._sha_value(v15._contract_invariant(descriptor["payload"])),
            }
        )
    references = {parent: descriptor["reference"] for parent, descriptor in rebound_by_parent.items()}
    benchmark = _rebound_benchmark(
        original_benchmark, binding=binding, semantic_version=semantic_version,
        references=references, rebound_at=now,
    )
    _validate_benchmark(copy.deepcopy(benchmark), copy.deepcopy(semantic), source_id=SOURCE_ID, benchmark_path=OUTPUT_BENCHMARK)
    benchmark_sha = _write_new(OUTPUT_BENCHMARK, benchmark)
    private_contracts = []
    for contract in original_private.get("contracts") or []:
        contract_id = str((contract or {}).get("contract_id") or "")
        if contract_id not in rebound_by_id:
            raise RuntimeError(f"private_gold_contract_not_referenced_by_benchmark:{contract_id}")
        private_contracts.append(copy.deepcopy(rebound_by_id[contract_id]))
    if len(private_contracts) != len(original_private.get("contracts") or []):
        raise RuntimeError("private_gold_contract_copy_incomplete")
    private = copy.deepcopy(original_private)
    private.update(
        {
            "generated_at": now,
            "benchmark": _relative(OUTPUT_BENCHMARK),
            "benchmark_sha256": benchmark_sha,
            "contracts": private_contracts,
            "source_rebind": {
                "reason_code": REBIND_REASON,
                "parent_private_gold": _relative(INPUT_PRIVATE_GOLD),
                "parent_private_gold_sha256": _sha(INPUT_PRIVATE_GOLD),
                "gold_sql_changed": False,
                "gold_results_changed": False,
                "model_outputs_used": False,
                "source_rows_persisted": False,
            },
        }
    )
    private_sha = _write_new(OUTPUT_PRIVATE_GOLD, private)
    evidence = {
        "schema": "gda.liveability-benchmark-discovery-metadata-rebind-evidence.v1",
        "generated_at": now,
        "status": "published",
        "bundle_id": BUNDLE_ID,
        "source": copy.deepcopy(binding),
        "semantic": {"path": _relative(SEMANTIC), "sha256": _sha(SEMANTIC), "semantic_version": semantic_version},
        "ontology": {"path": _relative(ONTOLOGY), "sha256": _sha(ONTOLOGY)},
        "input": {"benchmark": _relative(INPUT_BENCHMARK), "benchmark_sha256": _sha(INPUT_BENCHMARK), "private_gold": _relative(INPUT_PRIVATE_GOLD), "private_gold_sha256": _sha(INPUT_PRIVATE_GOLD)},
        "output": {"benchmark": _relative(OUTPUT_BENCHMARK), "benchmark_sha256": benchmark_sha, "private_gold": _relative(OUTPUT_PRIVATE_GOLD), "private_gold_sha256": private_sha},
        "contract_count": len(audit_rows),
        "contracts": sorted(audit_rows, key=lambda item: str(item["contract_id"])),
        "validation": {
            "benchmark_validated_against_v51_semantic": True,
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
    evidence_sha = _write_new(OUTPUT_EVIDENCE, evidence)
    artifacts = bundle.setdefault("artifacts", {})
    artifacts["benchmark"] = {"role": "business_benchmark", "path": _relative(OUTPUT_BENCHMARK), "sha256": benchmark_sha}
    artifacts["benchmark_private_gold"] = {"role": "evaluation_private_gold_bundle", "path": _relative(OUTPUT_PRIVATE_GOLD), "sha256": private_sha, "runtime_usage_prohibited": True}
    artifacts["benchmark_revision_evidence"] = {"role": "evaluation_only_revision_evidence", "path": _relative(OUTPUT_EVIDENCE), "sha256": evidence_sha, "runtime_usage_prohibited": True}
    bundle["generated_at"] = now
    bundle.setdefault("claim_boundary", {}).update(
        {
            "benchmark_v18_schema_drift_rebound": True,
            "benchmark_v18_questions_changed": False,
            "benchmark_v18_gold_sql_changed": False,
            "benchmark_v18_gold_results_changed": False,
            "benchmark_v18_model_outputs_used": False,
            "benchmark_v18_source_rows_persisted": False,
        }
    )
    _write_bundle(bundle)
    return {
        "status": "published",
        "bundle_id": BUNDLE_ID,
        "benchmark": _relative(OUTPUT_BENCHMARK),
        "private_gold": _relative(OUTPUT_PRIVATE_GOLD),
        "evidence": _relative(OUTPUT_EVIDENCE),
        "contract_count": len(audit_rows),
    }


if __name__ == "__main__":
    print(json.dumps(publish(), ensure_ascii=False, indent=2))
