"""Regression coverage for the v18 evaluation-only metadata rebind."""

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/publish_liveability_v18_schema_drift_rebind_benchmark_20260915.py"
spec = importlib.util.spec_from_file_location("liveability_v18_rebind", SCRIPT)
assert spec and spec.loader
publisher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(publisher)


def _binding() -> dict:
    return {
        "source_id": 12,
        "database_name": "liveability",
        "allowed_schemas": ["public"],
        "discovery_fingerprint": "d" * 64,
        "profile_fingerprint": "p" * 64,
        "execution_mode": "registered_governed_virtual_read_only",
    }


def _contract() -> dict:
    return {
        "contract_id": "CONTRACT_1",
        "source_contract": {
            "source_id": 12,
            "database_name": "liveability",
            "authorized_schema": "public",
            "discovery_fingerprint": "o" * 64,
            "profile_fingerprint": "q" * 64,
            "semantic_version": "old",
            "ontology_overlay_id": "old",
        },
        "query": {"path": "gold.sql", "sha256": "s" * 64, "read_only": True},
        "expected_result": {"columns": ["count"], "row_count": 1, "ordered_result_fingerprint": "r" * 64},
        "equivalence": {"accepted_fingerprint_keys": ["position_fingerprint"], "expected_fingerprints": {"position_fingerprint": "f" * 64}},
    }


def test_v18_contract_rebind_preserves_gold_content() -> None:
    original = _contract()
    rebound = publisher._rebound_contract(
        original, binding=_binding(), semantic_version="semantic-v51", ontology_overlay_id="ontology-v50",
        parent_path=SCRIPT, rebound_at="2026-09-15T00:00:00+00:00",
    )
    assert publisher.v15._contract_invariant(rebound) == publisher.v15._contract_invariant(original)
    assert rebound["source_contract"]["semantic_version"] == "semantic-v51"
    assert rebound["source_rebind"]["reason_code"] == publisher.REBIND_REASON


def test_v18_publisher_is_explicitly_evaluation_control_plane() -> None:
    source = SCRIPT.read_text(encoding="utf-8").casefold()
    assert "gold_sql_changed" in source
    assert "gold_sql_available_to_runtime" in source
