import json
import zipfile
from copy import deepcopy
from datetime import UTC, datetime

from data_agent import chongqing_real_source_admission as admission

CAPTURED_AT = datetime(2026, 7, 31, 9, 30, tzinfo=UTC)


def _checked_evidence() -> dict:
    return json.loads(admission.DEFAULT_EVIDENCE_PATH.read_text(encoding="utf-8"))


def _rehash(value: dict) -> None:
    for profile in value.get("asset_profiles", []):
        stable = {key: item for key, item in profile.items() if key != "profile_sha256"}
        profile["profile_sha256"] = admission.canonical_json_fingerprint(stable)
    stable = {key: item for key, item in value.items() if key != "evidence_sha256"}
    value["evidence_sha256"] = admission.canonical_json_fingerprint(stable)


def test_checked_full_source_evidence_is_valid_and_blocked():
    evidence = _checked_evidence()
    report = admission.build_validation_report()

    assert admission.validate_evidence(evidence) == []
    assert report["status"] == "valid"
    assert report["errors"] == []
    assert report["extracted_file_count"] == 584
    assert report["source_group_count"] == 11
    assert report["asset_profile_count"] == 16
    assert evidence["status"] == admission.STATUS
    assert evidence["claims"]["source_content_admitted"] is False
    assert evidence["claims"]["scheduler_submission_authorized"] is False
    assert evidence["claims"]["provider_mutation_authorized"] is False
    assert evidence["claims"]["production_ready"] is False


def test_checked_evidence_binds_real_archive_and_all_extracted_bytes():
    evidence = _checked_evidence()
    source = evidence["source_binding"]

    assert source["archive_sha256"] == admission.EXPECTED_ARCHIVE_SHA256
    assert source["archive_size_bytes"] == 468_462_251
    assert source["archive_entry_count"] == 533
    assert source["archive_uncompressed_size_bytes"] == 694_164_379
    assert source["archive_source_scope_entry_count"] == 532
    assert source["archive_source_scope_size_bytes"] == 694_147_946
    assert source["extracted_file_count"] == 584
    assert source["extracted_size_bytes"] == 700_610_744
    assert source["archive_original_entry_exact_match_count"] == 526
    assert source["archive_original_entry_modified_count"] == 6
    assert source["archive_original_entry_missing_count"] == 0
    assert source["extracted_additional_file_count"] == 52
    assert source["archive_integrity_verified"] is True
    assert source["archive_extracted_entry_multiset_verified"] is False
    assert source["source_payload_in_repository"] is False
    assert source["absolute_source_paths_in_evidence"] is False


def test_source_groups_cover_physical_inventory_and_stay_unadmitted():
    evidence = _checked_evidence()
    groups = evidence["source_groups"]

    assert [group["source_group_id"] for group in groups] == [
        spec["source_group_id"] for spec in admission.SOURCE_GROUP_SPECS
    ]
    assert sum(group["file_count"] for group in groups) == 584
    assert sum(group["size_bytes"] for group in groups) == 700_610_744
    assert all(group["metadata_profiled"] is True for group in groups)
    assert all(group["content_admitted"] is False for group in groups)
    assert all(group["license_status"] == "unverified_restricted" for group in groups)
    assert all(group["blockers"] for group in groups)
    assert len(evidence["admission_blockers"]) == len(set(evidence["admission_blockers"]))


def test_asset_profiles_correct_old_village_layer_scope_and_bind_baselines():
    evidence = _checked_evidence()
    profiles = {profile["asset_id"]: profile for profile in evidence["asset_profiles"]}
    village = profiles["fulu_village_planning_database_local"]

    assert set(profiles) == set(admission.EXPECTED_ASSET_BASELINES)
    assert village["record_metrics"] == {
        "feature_count": 8050,
        "layer_count": 28,
        "nonempty_layer_count": 20,
    }
    assert profiles["gaode_poi_2024"]["record_metrics"]["feature_count"] == 1_194_351
    assert profiles["chongqing_clcd_2020"]["record_metrics"]["pixel_count"] == 280_208_478
    assert profiles["chongqing_unicom_commuting_2023_local"]["data_classification"] == (
        "highly_restricted_aggregate_mobility"
    )
    assert all(profile["source_content_in_evidence"] is False for profile in profiles.values())


def test_evidence_is_path_free_and_contains_no_source_values():
    rendered = admission.DEFAULT_EVIDENCE_PATH.read_text(encoding="utf-8")
    evidence = json.loads(rendered)

    assert "/Users/" not in rendered
    assert "Downloads/" not in rendered
    assert ".tmp/twm_standard_1128" not in rendered
    assert "geometry_values" not in rendered
    assert "od_rows" not in rendered
    assert "flow_rows" not in rendered
    assert admission._sensitive_paths(evidence) == []
    assert all(
        profile["source_ref"].startswith("source://chongqing-planning-institute-sample/assets/")
        for profile in evidence["asset_profiles"]
    )


def test_outer_rehash_cannot_hide_admission_or_baseline_overclaim():
    evidence = deepcopy(_checked_evidence())
    evidence["claims"]["source_content_admitted"] = True
    evidence["admission_policy"]["ci_requires_local_source_payload"] = True
    evidence["source_binding"]["local_source_path"] = "/untrusted/source"
    evidence["research_audit_binding"]["admission_authority"] = True
    evidence["source_groups"][0]["content_admitted"] = True
    profile = next(
        item for item in evidence["asset_profiles"] if item["asset_id"] == "gaode_poi_2024"
    )
    profile["record_metrics"]["feature_count"] = 1
    _rehash(evidence)

    errors = admission.validate_evidence(evidence)

    assert "M3-28 claim does not match: source_content_admitted" in errors
    assert "M3-28 admission policy does not match" in errors
    assert "M3-28 source binding inventory does not match" in errors
    assert "M3-28 research audit binding does not match" in errors
    assert any("source group claim does not match" in error for error in errors)
    assert "M3-28 asset metric does not match: gaode_poi_2024.feature_count" in errors


def test_checked_file_fingerprint_rejects_rehashed_copy(tmp_path):
    evidence = deepcopy(_checked_evidence())
    evidence["captured_at"] = "2026-07-31T10:00:00Z"
    _rehash(evidence)
    path = tmp_path / "evidence.json"
    path.write_text(json.dumps(evidence, ensure_ascii=False), encoding="utf-8")

    report = admission.build_validation_report(path)

    assert report["status"] == "invalid"
    assert "M3-28 evidence file fingerprint does not match" in report["errors"]


def test_archive_and_extracted_entry_multiset_is_verified(tmp_path):
    root = tmp_path / "source"
    group = root / "01-dem"
    group.mkdir(parents=True)
    payload = group / "tile.bin"
    payload.write_bytes(b"real-source-content")
    archive_path = tmp_path / "source.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.write(payload, "bundle/01数据样例/01-dem/tile.bin")

    records = admission._scan_payload_files(root)
    binding = admission._archive_binding(archive_path, records)

    assert len(records) == 1
    assert binding["archive_entry_count"] == 1
    assert binding["archive_source_scope_entry_count"] == 1
    assert binding["archive_original_entry_exact_match_count"] == 1
    assert binding["archive_original_entry_modified_count"] == 0
    assert binding["extracted_additional_file_count"] == 0
    assert binding["archive_integrity_verified"] is True
    assert binding["archive_extracted_entry_multiset_verified"] is True


def test_source_scan_rejects_symbolic_links(tmp_path):
    root = tmp_path / "source"
    group = root / "01-dem"
    group.mkdir(parents=True)
    target = tmp_path / "outside.bin"
    target.write_bytes(b"outside")
    (group / "linked.bin").symlink_to(target)

    try:
        admission._scan_payload_files(root)
    except admission.ChongqingRealSourceAdmissionError as exc:
        assert "symbolic link" in str(exc)
    else:
        raise AssertionError("symbolic link was accepted")


def test_wrapper_is_strict_and_invokes_source_admission():
    wrapper = admission.REPO_ROOT / "scripts/chongqing-real-source-admission.sh"
    text = wrapper.read_text(encoding="utf-8")

    assert "set -euo pipefail" in text
    assert "chongqing_real_source_admission" in text
