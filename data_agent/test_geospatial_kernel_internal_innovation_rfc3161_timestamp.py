from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

from scripts import (
    assess_geospatial_kernel_internal_innovation_timestamp_authority_candidate as assess_candidate,
)
from scripts import (
    freeze_geospatial_kernel_internal_innovation_timestamp_authority_registry as freeze,
)
from scripts import verify_geospatial_kernel_internal_innovation_rfc3161_timestamp as verify

REPO_ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/"
    "geospatial_kernel_internal_innovation_timestamp_authority_registry.json"
)
CANDIDATE_ASSESSMENT_PATH = REPO_ROOT / (
    "benchmarks/geotransport_v0_1/"
    "geospatial_kernel_internal_innovation_timestamp_authority_candidate_assessment.json"
)


def test_timestamp_authority_registry_is_reproducibly_frozen() -> None:
    frozen = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))

    assert frozen == freeze.compile_registry()
    assert frozen["status"] == "frozen_no_registered_rfc3161_timestamp_authority"
    assert frozen["registered_authorities"] == {}
    assert frozen["claim_boundary"]["trusted_external_timestamp_verified"] is False


def test_registry_seal_and_file_identity_recompute() -> None:
    body = REGISTRY_PATH.read_bytes()
    frozen = json.loads(body)
    seal = frozen.pop("registry_seal")
    canonical = json.dumps(
        frozen,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")

    assert hashlib.sha256(body).hexdigest() == verify.EXPECTED_REGISTRY_FILE_SHA256
    assert seal["sha256"] == hashlib.sha256(canonical).hexdigest()
    assert seal["sha256"] == verify.EXPECTED_REGISTRY_SEAL_SHA256


def test_production_registry_is_explicitly_not_ready() -> None:
    report = verify.assess_timestamp_authority_registry()

    assert report["status"] == "blocked_no_registered_rfc3161_timestamp_authority"
    assert report["registered_authority_count"] == 0
    assert report["trusted_external_timestamp_verification_ready"] is False
    assert report["gates"]["frozen_registry_identity_verified"] is True
    assert report["execution_boundary"]["network_requests_performed"] is False


def test_unregistered_authority_fails_before_opening_candidate_files(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="authority_not_registered"):
        verify.verify_receipt_timestamp(
            receipt_path=tmp_path / "missing-receipt.json",
            timestamp_response_path=tmp_path / "missing-response.tsr",
            authority_id="not-registered",
            forecast_issue_time=datetime.now(UTC),
        )


def test_rfc3161_primitive_verifies_signature_chain_and_exact_receipt(
    tmp_path: Path,
) -> None:
    receipt = tmp_path / "receipt.json"
    receipt.write_text('{"source":"fixture"}\n', encoding="utf-8")
    authority, response = _local_timestamp_authority(tmp_path, receipt)

    result = verify._verify_registered_token(
        root=tmp_path,
        receipt_path=receipt,
        timestamp_response_path=response,
        authority_id="local-test-tsa",
        authority=authority,
    )

    assert result["policy_oid"] == "1.2.3.4.1"
    assert result["openssl_version"]
    assert result["tsa_certificate_artifact"] == authority["tsa_certificate"]
    receipt.write_text('{"source":"tampered"}\n', encoding="utf-8")
    with pytest.raises(ValueError, match="openssl_verification_failed"):
        verify._verify_registered_token(
            root=tmp_path,
            receipt_path=receipt,
            timestamp_response_path=response,
            authority_id="local-test-tsa",
            authority=authority,
        )


def test_timestamp_reply_parser_rejects_unapproved_hash() -> None:
    detail = """Status: Granted.
Policy OID: 1.2.3.4.1
Hash Algorithm: sha1
Serial number: 0x01
Time stamp: Jul 31 10:37:43 2026 GMT
"""

    with pytest.raises(ValueError, match="hash_algorithm_invalid"):
        verify._parse_timestamp_reply(detail)


def test_empty_candidate_inventory_remains_explicitly_awaiting(tmp_path: Path) -> None:
    report = assess_candidate.assess_timestamp_authority_candidates(
        [],
        repo_root=tmp_path,
        assessed_at=datetime(2026, 7, 31, 12, 0, tzinfo=UTC),
    )

    assert report["status"] == "awaiting_timestamp_authority_candidate_dossier"
    assert report["candidate_dossier_count"] == 0
    assert report["submitted_production_candidate_count"] == 0
    assert report["candidate_registration_ready"] is False
    assert report["execution_boundary"]["network_requests_performed"] is False
    assert report["execution_boundary"]["registry_modified"] is False


def test_current_candidate_assessment_recomputes_as_zero_submissions() -> None:
    frozen = json.loads(CANDIDATE_ASSESSMENT_PATH.read_text(encoding="utf-8"))
    generated_at = datetime.fromisoformat(frozen["generated_at"])

    assert frozen == assess_candidate.assess_timestamp_authority_candidates(
        [],
        assessed_at=generated_at,
    )
    assert frozen["status"] == "awaiting_timestamp_authority_candidate_dossier"
    assert frozen["submitted_production_candidate_count"] == 0
    assert frozen["candidate_registration_ready"] is False


def test_candidate_contract_can_reach_manual_registration_gate_without_mutating_registry(
    tmp_path: Path,
) -> None:
    registry_before = REGISTRY_PATH.read_bytes()
    receipt = tmp_path / "canary-receipt.json"
    receipt.write_text('{"source":"external-canary"}\n', encoding="utf-8")
    authority, response = _local_timestamp_authority(tmp_path, receipt)
    dossier = _candidate_dossier(tmp_path, receipt, response, authority)
    assessed_at = datetime.now(UTC)

    report = assess_candidate.assess_timestamp_authority_candidates(
        [dossier],
        repo_root=tmp_path,
        assessed_at=assessed_at,
    )

    assert report["status"] == (
        "timestamp_authority_candidate_ready_for_manual_registration"
    )
    assert report["candidate_registration_ready"] is True
    assert report["registration_ready_candidate_ids"] == ["synthetic-contract-tsa"]
    candidate = report["candidates"][0]
    assert candidate["candidate_registration_ready"] is True
    assert all(candidate["gates"].values())
    assert candidate["cryptographic_verification"][
        "signature_chain_exact_imprint_and_policy_verified"
    ] is True
    assert report["claim_boundary"]["candidate_assessment_is_registration"] is False
    assert REGISTRY_PATH.read_bytes() == registry_before


def test_test_only_candidate_cannot_become_registration_ready(tmp_path: Path) -> None:
    receipt = tmp_path / "canary-receipt.json"
    receipt.write_text('{"source":"test-canary"}\n', encoding="utf-8")
    authority, response = _local_timestamp_authority(tmp_path, receipt)
    dossier = _candidate_dossier(
        tmp_path,
        receipt,
        response,
        authority,
        test_only=True,
    )

    report = assess_candidate.assess_timestamp_authority_candidates(
        [dossier],
        repo_root=tmp_path,
        assessed_at=datetime.now(UTC),
    )

    candidate = report["candidates"][0]
    assert candidate["gates"]["canary_signature_and_chain_verified"] is True
    assert candidate["gates"]["production_candidate_not_test_only"] is False
    assert candidate["candidate_registration_ready"] is False
    assert report["registration_ready_candidate_count"] == 0


def test_candidate_recomputes_document_hashes_and_rejects_drift(tmp_path: Path) -> None:
    receipt = tmp_path / "canary-receipt.json"
    receipt.write_text('{"source":"external-canary"}\n', encoding="utf-8")
    authority, response = _local_timestamp_authority(tmp_path, receipt)
    dossier = _candidate_dossier(tmp_path, receipt, response, authority)
    (tmp_path / "service-policy.txt").write_text("changed\n", encoding="utf-8")

    report = assess_candidate.assess_timestamp_authority_candidates(
        [dossier],
        repo_root=tmp_path,
        assessed_at=datetime.now(UTC),
    )

    candidate = report["candidates"][0]
    assert candidate["gates"]["all_declared_artifacts_hash_bound"] is False
    assert candidate["gates"]["service_policy_hash_bound"] is False
    assert candidate["candidate_registration_ready"] is False
    assert any(
        "registered_artifact_mismatch" in error
        for error in candidate["verification_errors"]
    )


def test_endpoint_policy_and_revocation_gates_are_non_compensatory(
    tmp_path: Path,
) -> None:
    receipt = tmp_path / "canary-receipt.json"
    receipt.write_text('{"source":"external-canary"}\n', encoding="utf-8")
    authority, response = _local_timestamp_authority(tmp_path, receipt)
    dossier = _candidate_dossier(tmp_path, receipt, response, authority)
    payload = json.loads(dossier.read_text(encoding="utf-8"))
    payload["service_identity"]["service_endpoint"] = "http://tsa.invalid/timestamp"
    payload["accepted_policy_oids"] = ["not-an-oid"]
    payload["revocation_strategy"]["failure_mode"] = "best_effort"
    dossier.write_text(json.dumps(payload), encoding="utf-8")

    report = assess_candidate.assess_timestamp_authority_candidates(
        [dossier],
        repo_root=tmp_path,
        assessed_at=datetime.now(UTC),
    )

    candidate = report["candidates"][0]
    assert candidate["gates"]["https_endpoint_valid"] is False
    assert candidate["gates"]["policy_oid_allowlist_valid"] is False
    assert candidate["gates"]["revocation_strategy_documented"] is False
    assert candidate["candidate_registration_ready"] is False


def test_self_signed_tsa_leaf_is_rejected_for_production(tmp_path: Path) -> None:
    receipt = tmp_path / "canary-receipt.json"
    receipt.write_text('{"source":"external-canary"}\n', encoding="utf-8")
    authority, response = _local_timestamp_authority(tmp_path, receipt)
    dossier = _candidate_dossier(tmp_path, receipt, response, authority)
    payload = json.loads(dossier.read_text(encoding="utf-8"))
    payload["artifacts"]["tsa_certificate"] = authority["ca_bundle"]
    dossier.write_text(json.dumps(payload), encoding="utf-8")

    report = assess_candidate.assess_timestamp_authority_candidates(
        [dossier],
        repo_root=tmp_path,
        assessed_at=datetime.now(UTC),
    )

    candidate = report["candidates"][0]
    assert candidate["gates"]["tsa_leaf_not_self_signed"] is False
    assert candidate["gates"]["tsa_leaf_distinct_from_ca_bundle"] is False
    assert candidate["candidate_registration_ready"] is False


def test_candidate_requires_a_cryptographically_valid_der_canary(tmp_path: Path) -> None:
    receipt = tmp_path / "canary-receipt.json"
    receipt.write_text('{"source":"external-canary"}\n', encoding="utf-8")
    authority, response = _local_timestamp_authority(tmp_path, receipt)
    dossier = _candidate_dossier(tmp_path, receipt, response, authority)
    payload = bytearray(response.read_bytes())
    payload[-1] ^= 1
    response.write_bytes(payload)
    dossier_payload = json.loads(dossier.read_text(encoding="utf-8"))
    dossier_payload["artifacts"]["canary_timestamp_response"] = _artifact(
        tmp_path,
        response,
    )
    dossier.write_text(json.dumps(dossier_payload), encoding="utf-8")

    report = assess_candidate.assess_timestamp_authority_candidates(
        [dossier],
        repo_root=tmp_path,
        assessed_at=datetime.now(UTC),
    )

    candidate = report["candidates"][0]
    assert candidate["gates"]["all_declared_artifacts_hash_bound"] is True
    assert candidate["gates"]["canary_signature_and_chain_verified"] is False
    assert candidate["candidate_registration_ready"] is False


def _candidate_dossier(
    root: Path,
    receipt: Path,
    response: Path,
    authority: dict[str, object],
    *,
    test_only: bool = False,
) -> Path:
    now = datetime.now(UTC)
    documents = {
        "legal_identity_evidence": root / "legal-identity.txt",
        "service_policy": root / "service-policy.txt",
        "certification_practice_statement": root / "cps.txt",
        "revocation_policy": root / "revocation-policy.txt",
    }
    for name, path in documents.items():
        path.write_text(f"synthetic contract fixture: {name}\n", encoding="utf-8")
    dossier = root / "candidate-dossier.json"
    dossier.write_text(
        json.dumps(
            {
                "schema": assess_candidate.DOSSIER_SCHEMA,
                "candidate_id": "synthetic-contract-tsa",
                "test_only": test_only,
                "service_identity": {
                    "legal_entity_name": "Synthetic Contract Fixture",
                    "service_name": "Synthetic RFC 3161 Contract Service",
                    "service_endpoint": "https://tsa.invalid/timestamp",
                    "independent_of_gwm_runtime": True,
                },
                "accepted_policy_oids": authority["accepted_policy_oids"],
                "prospective_campaign": {
                    "starts_at": now.isoformat(),
                    "ends_at": (now + timedelta(hours=12)).isoformat(),
                },
                "artifacts": {
                    **{
                        name: _artifact(root, path)
                        for name, path in documents.items()
                    },
                    "tsa_certificate": authority["tsa_certificate"],
                    "ca_bundle": authority["ca_bundle"],
                    "canary_receipt": _artifact(root, receipt),
                    "canary_timestamp_response": _artifact(root, response),
                },
                "revocation_strategy": {
                    "mechanisms": ["ocsp", "crl"],
                    "check_before_registration": True,
                    "check_before_each_token_verification": True,
                    "failure_mode": "fail_closed",
                    "maximum_status_age_seconds": 86400,
                },
                "canary": {
                    "acquisition_mode": "real_external_rfc3161_service",
                    "acquired_at": now.isoformat(),
                    "external_service_response": True,
                    "test_only": test_only,
                },
            },
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return dossier


def _local_timestamp_authority(
    root: Path,
    receipt: Path,
) -> tuple[dict[str, object], Path]:
    now = datetime.now(UTC)
    ca_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    ca_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Fixture TSA Root")])
    ca_certificate = (
        x509.CertificateBuilder()
        .subject_name(ca_name)
        .issuer_name(ca_name)
        .public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=1))
        .not_valid_after(now + timedelta(days=2))
        .add_extension(x509.BasicConstraints(ca=True, path_length=1), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=False,
                content_commitment=False,
                key_encipherment=False,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=True,
                crl_sign=True,
                encipher_only=None,
                decipher_only=None,
            ),
            critical=True,
        )
        .sign(ca_key, hashes.SHA256())
    )
    tsa_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    tsa_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "Fixture TSA")])
    tsa_certificate = (
        x509.CertificateBuilder()
        .subject_name(tsa_name)
        .issuer_name(ca_name)
        .public_key(tsa_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=1))
        .not_valid_after(now + timedelta(days=1))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                content_commitment=True,
                key_encipherment=False,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=False,
                crl_sign=False,
                encipher_only=None,
                decipher_only=None,
            ),
            critical=True,
        )
        .add_extension(
            x509.ExtendedKeyUsage([ExtendedKeyUsageOID.TIME_STAMPING]),
            critical=True,
        )
        .sign(ca_key, hashes.SHA256())
    )
    ca_path = root / "ca.pem"
    tsa_path = root / "tsa.pem"
    key_path = root / "tsa-key.pem"
    ca_path.write_bytes(ca_certificate.public_bytes(serialization.Encoding.PEM))
    tsa_path.write_bytes(tsa_certificate.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(
        tsa_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    serial_path = root / "tsa-serial"
    serial_path.write_text("01\n", encoding="ascii")
    config_path = root / "tsa.cnf"
    config_path.write_text(
        "\n".join(
            [
                "[ tsa ]",
                "default_tsa = tsa_config",
                "[ tsa_config ]",
                f"dir = {root}",
                f"serial = {serial_path}",
                "crypto_device = builtin",
                f"signer_cert = {tsa_path}",
                f"certs = {ca_path}",
                f"signer_key = {key_path}",
                "signer_digest = sha256",
                "default_policy = 1.2.3.4.1",
                "other_policies = 1.2.3.4.2",
                "digests = sha256",
                "accuracy = secs:1",
                "ordering = yes",
                "tsa_name = no",
                "ess_cert_id_chain = no",
                "",
            ]
        ),
        encoding="utf-8",
    )
    query = root / "request.tsq"
    response = root / "response.tsr"
    _openssl("ts", "-query", "-data", str(receipt), "-sha256", "-cert", "-out", str(query))
    _openssl(
        "ts",
        "-reply",
        "-config",
        str(config_path),
        "-queryfile",
        str(query),
        "-out",
        str(response),
    )
    return (
        {
            "status": "test_only_not_admitted",
            "test_only": True,
            "service_name": "Local fixture TSA",
            "service_endpoint": "local-test-only",
            "accepted_policy_oids": ["1.2.3.4.1"],
            "tsa_certificate": _artifact(root, tsa_path),
            "ca_bundle": _artifact(root, ca_path),
            "revocation_strategy": "test_fixture_no_revocation",
        },
        response,
    )


def _openssl(*arguments: str) -> None:
    subprocess.run(
        ["openssl", *arguments],
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )


def _artifact(root: Path, path: Path) -> dict[str, object]:
    body = path.read_bytes()
    return {
        "path": path.relative_to(root).as_posix(),
        "sha256": hashlib.sha256(body).hexdigest(),
        "size_bytes": len(body),
    }
