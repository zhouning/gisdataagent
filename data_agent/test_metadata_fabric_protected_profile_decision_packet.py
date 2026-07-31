import json
from copy import deepcopy
from datetime import UTC, datetime

from data_agent import metadata_fabric_protected_profile_decision_packet as packet

GENERATED_AT = datetime(2026, 7, 31, 8, 30, tzinfo=UTC)


def _checked_packet() -> dict:
    return json.loads(packet.DEFAULT_PACKET_PATH.read_text(encoding="utf-8"))


def _rehash(value: dict) -> None:
    stable = {key: item for key, item in value.items() if key != "packet_sha256"}
    value["packet_sha256"] = packet.canonical_json_fingerprint(stable)


def test_packet_assigns_every_m3_26_blocker_exactly_once():
    value = packet.build_packet(generated_at=GENERATED_AT)
    predecessor = json.loads(packet.DEFAULT_PREDECESSOR_PATH.read_text(encoding="utf-8"))
    assigned = [blocker for group in value["decision_groups"] for blocker in group["blockers"]]

    assert len(value["decision_groups"]) == 16
    assert len(assigned) == 85
    assert len(set(assigned)) == 85
    assert set(assigned) == set(predecessor["blockers"])
    assert value["blocker_summary"] == {
        "assigned": 85,
        "decision_groups": 16,
        "expected": 85,
        "identity_attestation": 1,
        "identity_profile": 40,
        "object_store_attestation": 1,
        "object_store_profile": 43,
        "unique": 85,
        "unresolved_decision_groups": 16,
    }


def test_checked_packet_is_valid_unresolved_and_non_authoritative():
    value = _checked_packet()
    report = packet.build_validation_report()

    assert packet.validate_packet(value) == []
    assert report["status"] == "valid"
    assert report["errors"] == []
    assert value["status"] == packet.PACKET_STATUS
    assert all(group["status"] == packet.GROUP_STATUS for group in value["decision_groups"])
    assert set(value["claims"]) == packet.CLAIMS
    assert not any(value["claims"].values())
    assert value["resolution_policy"]["packet_records_decisions"] is False
    assert value["resolution_policy"]["packet_grants_execution_authority"] is False


def test_dependency_graph_rejects_unknown_edges_and_cycles():
    unknown = packet.build_packet(generated_at=GENERATED_AT)
    unknown["decision_groups"][0]["depends_on"] = ["missing-owner-decision"]
    _rehash(unknown)
    unknown_errors = packet.validate_packet(unknown)

    cyclic = packet.build_packet(generated_at=GENERATED_AT)
    cyclic["decision_groups"][0]["depends_on"] = ["protected-identity-attestation"]
    _rehash(cyclic)
    cyclic_errors = packet.validate_packet(cyclic)

    assert any("dependencies are unknown" in error for error in unknown_errors)
    assert "M3-27 dependency graph contains a cycle" in cyclic_errors


def test_malformed_group_and_blocker_fail_closed_without_exception():
    malformed_group = packet.build_packet(generated_at=GENERATED_AT)
    malformed_group["decision_groups"][0] = "not-an-object"
    _rehash(malformed_group)

    malformed_blocker = packet.build_packet(generated_at=GENERATED_AT)
    malformed_blocker["decision_groups"][0]["blockers"][0] = 7
    _rehash(malformed_blocker)

    group_errors = packet.validate_packet(malformed_group)
    blocker_errors = packet.validate_packet(malformed_blocker)

    assert "M3-27 decision group is not an object" in group_errors
    assert any("group blockers is invalid" in error for error in blocker_errors)
    assert "M3-27 blocker coverage does not match M3-26" in blocker_errors


def test_outer_rehash_cannot_hide_duplicate_resolution_or_overclaim():
    value = packet.build_packet(generated_at=GENERATED_AT)
    value["decision_groups"][1]["blockers"].append(value["decision_groups"][0]["blockers"][0])
    value["decision_groups"][1]["profile_paths"] = packet._profile_paths(
        value["decision_groups"][1]["blockers"]
    )
    value["decision_groups"][0]["status"] = "approved"
    value["claims"]["production_profiles_ready"] = True
    _rehash(value)

    errors = packet.validate_packet(value)

    assert "M3-27 blockers are not assigned exactly once" in errors
    assert any("group is not unresolved" in error for error in errors)
    assert "M3-27 packet may not assert production claims" in errors
    assert "M3-27 packet does not match current bound inputs" in errors


def test_profile_paths_are_exact_and_attestations_have_no_profile_path():
    value = packet.build_packet(generated_at=GENERATED_AT)

    for group in value["decision_groups"]:
        assert group["profile_paths"] == packet._profile_paths(group["blockers"])
        command = group["protected_verification_command"]
        assert " evaluate " in command
        assert "--attestation $GDA_" in command
        if group["decision_id"].startswith("protected-"):
            assert group["profile_paths"] == []


def test_checked_packet_contains_no_local_path_payload_or_credential_fields():
    rendered = packet.DEFAULT_PACKET_PATH.read_text(encoding="utf-8")
    value = json.loads(rendered)

    assert "/Users/" not in rendered
    assert "Downloads/" not in rendered
    assert "geometry_values" not in rendered
    assert packet._sensitive_paths(value) == []
    assert value["resolution_policy"]["credential_material_forbidden"] is True
    assert value["resolution_policy"]["local_retained_material_promotion_forbidden"] is True


def test_predecessor_or_group_tampering_fails_closed(tmp_path):
    predecessor = tmp_path / "m3-26.json"
    predecessor.write_bytes(packet.DEFAULT_PREDECESSOR_PATH.read_bytes() + b"\n")

    try:
        packet.build_packet(
            predecessor_path=predecessor,
            generated_at=GENERATED_AT,
        )
    except packet.ProtectedProfileDecisionPacketError as exc:
        assert "predecessor file fingerprint does not match" in str(exc)
    else:
        raise AssertionError("drifted predecessor was accepted")

    value = deepcopy(_checked_packet())
    value["decision_groups"][0]["allowed_choices"] = ["Unreviewed provider"]
    _rehash(value)
    assert "M3-27 packet does not match current bound inputs" in packet.validate_packet(value)


def test_wrapper_is_strict_and_invokes_packet_validator():
    wrapper = packet.REPO_ROOT / "scripts/metadata-fabric-protected-profile-decision-packet.sh"
    text = wrapper.read_text(encoding="utf-8")

    assert "set -euo pipefail" in text
    assert "metadata_fabric_protected_profile_decision_packet" in text
