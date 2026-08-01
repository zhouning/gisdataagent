#!/usr/bin/env python3
"""Freeze the approved RFC 3161 timestamp-authority registry."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/"
    "geospatial_kernel_internal_innovation_timestamp_authority_registry.json"
)
SCHEMA = "gwm.geospatial_kernel.timestamp_authority_registry.v1"
FROZEN_AT = "2026-07-31T10:37:43Z"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def compile_registry() -> dict[str, Any]:
    payload: dict[str, Any] = {
        "schema": SCHEMA,
        "status": "frozen_no_registered_rfc3161_timestamp_authority",
        "frozen_at": FROZEN_AT,
        "evidence_contract": {
            "accepted_standard": "RFC3161",
            "message_imprint_algorithm": "sha256",
            "message_imprint_must_equal_exact_source_receipt_sha256": True,
            "timestamp_response_der_required": True,
            "tsa_leaf_certificate_sha256_required": True,
            "ca_bundle_sha256_required": True,
            "signature_chain_verified_offline": True,
            "policy_oid_allowlist_required": True,
            "token_time_must_not_follow_forecast_issue_time": True,
            "token_time_must_not_precede_receipt_issued_at": True,
            "http_date_header_alone_accepted": False,
            "local_clock_alone_accepted": False,
            "self_signed_test_authority_accepted_as_production": False,
        },
        "authority_admission_contract": {
            "legal_entity_and_service_identity_documented": True,
            "service_policy_and_cps_artifacts_hash_bound": True,
            "tsa_certificate_extended_key_usage_timestamping_required": True,
            "certificate_validity_covers_prospective_campaign": True,
            "revocation_check_strategy_documented": True,
            "endpoint_and_policy_oid_frozen_before_first_real_receipt": True,
            "independent_of_gwm_runtime": True,
            "manual_waiver_allowed": False,
        },
        "registered_authorities": {},
        "readiness": {
            "registered_authority_count": 0,
            "real_rfc3161_token_acquired": False,
            "trusted_external_timestamp_verification_ready": False,
            "blocker": "no_registered_rfc3161_timestamp_authority",
        },
        "claim_boundary": {
            "registry_frozen": True,
            "network_requests_performed": False,
            "timestamp_authority_selected": False,
            "real_timestamp_token_acquired": False,
            "trusted_external_timestamp_verified": False,
            "prospective_manifest_acquired": False,
            "physical_prediction_executed": False,
            "outcomes_loaded": False,
            "innovation_fitted": False,
            "candidate_promoted": False,
            "runtime_enabled": False,
            "geospatial_kernel_validated": False,
        },
    }
    canonical = json.dumps(
        payload,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    payload["registry_seal"] = {
        "algorithm": "sha256_canonical_json_without_registry_seal",
        "sha256": hashlib.sha256(canonical).hexdigest(),
    }
    return payload


def main() -> int:
    args = parse_args()
    payload = compile_registry()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(args.output)
    print(f"status={payload['status']}")
    print(f"registry_sha256={payload['registry_seal']['sha256']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
