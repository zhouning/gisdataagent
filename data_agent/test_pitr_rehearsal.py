from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from data_agent.platform_runtime.deployment_profile import load_deployment_profile
from data_agent.platform_runtime.pitr_rehearsal import (
    PITR_LIMITATIONS,
    PITRContract,
    PITRRehearsalError,
    _classify_command_failure,
    _wal_directory_facts,
    failure_report,
    pgpass_line,
    recovery_settings,
    resolve_pitr_contract,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
PROFILE_PATH = REPO_ROOT / "config" / "deployment_profiles" / "main-compose-dev.json"


def _compose_model(password: str = "test:pass\\word") -> dict:
    return {
        "services": {
            "db": {
                "image": "postgis:test",
                "environment": {
                    "POSTGRES_DB": "gis_agent",
                    "POSTGRES_USER": "postgres",
                    "POSTGRES_PASSWORD": password,
                },
            },
            "minio": {},
            "minio-bucket-init": {
                "environment": {
                    "AWS_S3_BUCKET": "gis-agent-uploads",
                    "MMFE_LAKEHOUSE_BUCKET": "gis-agent-lakehouse",
                }
            },
        },
        "networks": {"agent-net": {"name": "gisdataagent_agent-net"}},
    }


def test_pitr_contract_keeps_auth_out_of_repr_and_escapes_pgpass() -> None:
    profile = load_deployment_profile(PROFILE_PATH)
    contract = resolve_pitr_contract(profile, _compose_model())

    assert contract.network_name == "gisdataagent_agent-net"
    assert "test:pass" not in repr(contract)
    assert pgpass_line(contract) == (
        "127.0.0.1:5432:*:postgres:test\\:pass\\\\word\n"
    )


def test_pitr_contract_rejects_missing_password_or_unsafe_network() -> None:
    profile = load_deployment_profile(PROFILE_PATH)
    missing_password = _compose_model("")
    with pytest.raises(PITRRehearsalError, match="database_auth"):
        resolve_pitr_contract(profile, missing_password)

    unsafe_network = _compose_model()
    unsafe_network["networks"]["agent-net"]["name"] = "../host"
    with pytest.raises(PITRRehearsalError, match="contract.network"):
        resolve_pitr_contract(profile, unsafe_network)


def test_recovery_settings_require_timezone_and_isolated_restore_command() -> None:
    rendered = recovery_settings(datetime(2026, 7, 31, 12, 0, tzinfo=UTC))

    assert "2026-07-31T12:00:00+00:00" in rendered
    assert "cp /recovery-wal/%f %p" in rendered
    assert "recovery_target_action = 'promote'" in rendered
    with pytest.raises(PITRRehearsalError, match="target_timezone"):
        recovery_settings(datetime(2026, 7, 31, 12, 0))


def test_wal_inventory_is_content_bound_without_exposing_names(tmp_path: Path) -> None:
    first = tmp_path / "000000010000000000000001"
    second = tmp_path / "000000010000000000000002"
    first.write_bytes(b"first")
    second.write_bytes(b"second")
    (tmp_path / "000000010000000000000003.partial").write_bytes(b"partial")

    facts = _wal_directory_facts(tmp_path)

    assert facts["complete_segment_count"] == 2
    assert facts["partial_segment_count"] == 1
    assert facts["bytes"] == 11
    assert "00000001" not in json.dumps(facts)
    second.write_bytes(b"change")
    assert _wal_directory_facts(tmp_path)["inventory_sha256"] != facts[
        "inventory_sha256"
    ]


def test_wal_inventory_requires_at_least_one_complete_segment(tmp_path: Path) -> None:
    (tmp_path / "000000010000000000000001.partial").write_bytes(b"partial")
    with pytest.raises(PITRRehearsalError, match="complete_segment"):
        _wal_directory_facts(tmp_path)


def test_failure_report_is_sparse_and_never_promotes() -> None:
    report = failure_report(
        profile_id="main-compose-dev",
        stage="wal.receiver_flush",
        error_type="PITRRehearsalError",
    )
    rendered = json.dumps(report, sort_keys=True)

    assert report["technical_pass"] is False
    assert report["promotion_ready"] is False
    assert set(PITR_LIMITATIONS).issubset(report["promotion_blockers"])
    assert "/Users/" not in rendered
    assert "password" not in rendered.lower()


@pytest.mark.parametrize(
    ("stderr", "expected"),
    [
        ("could not create directory: Permission denied", "backup.base.permission"),
        ("no space left on device", "backup.base.capacity"),
        ("replication slot x does not exist", "backup.base.slot_missing"),
        ("password authentication failed", "backup.base.authentication"),
        (
            "no pg_hba.conf entry for replication connection",
            "backup.base.replication_hba",
        ),
        ("unrecognized option --invalid", "backup.base.client_contract"),
        ("unknown client error", "backup.base"),
    ],
)
def test_command_failure_is_classified_without_raw_output(
    stderr: str, expected: str
) -> None:
    assert _classify_command_failure("backup.base", stderr) == expected


def test_pitr_contract_repr_does_not_expose_password() -> None:
    profile = load_deployment_profile(PROFILE_PATH)
    recovery = resolve_pitr_contract(profile, _compose_model("must-not-leak"))
    copied = PITRContract(
        database=recovery.database,
        network_name=recovery.network_name,
        database_password="must-not-leak",
    )
    assert "must-not-leak" not in repr(copied)
