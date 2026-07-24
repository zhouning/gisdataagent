import json
from datetime import datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from data_agent import platform_crosswalk as crosswalk
from data_agent.platform_contracts import canonical_json_fingerprint


FIXTURE = Path(crosswalk.DEFAULT_GOLDEN_FIXTURE)
ROW_SHA = "a" * 64


def _candidate(**overrides):
    values = {
        "source_table": "agent_data_assets",
        "legacy_key": "asset:42",
        "source_row_sha256": ROW_SHA,
        "extracted_at": "2026-07-24T12:00:00Z",
        "adapter_id": "ar0-crosswalk-test",
        "target_contract": "resource",
        "target_payload": {
            "tenant_id": "tenant-a",
            "resource_urn": "gda://tenant-a/dataset/land-use-parcels",
            "resource_kind": "dataset",
            "authority_system": "legacy-postgresql",
            "authority_locator": "agent_data_assets:42",
            "owner_ref": "user:dataops",
            "governance_ref": {"legacy_asset_id": 42},
            "technical_refs": [],
        },
    }
    values.update(overrides)
    return values


def _write_inventory_skeleton(root: Path) -> None:
    content_by_path: dict[str, list[str]] = {}
    for spec in crosswalk.LEGACY_TABLE_SPECS:
        markers = spec.schema_markers + spec.writer_markers + spec.endpoint_markers
        for marker in markers:
            content_by_path.setdefault(marker.path, []).append(marker.marker)
    for relative_path, markers in content_by_path.items():
        path = root / relative_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(markers) + "\n", encoding="utf-8")


def test_repository_inventory_freezes_tables_writers_and_prohibited_run_mapping():
    report = crosswalk.build_inventory_report()

    assert report["status"] == "valid"
    assert report["table_count"] == 5
    assert {item["table_name"] for item in report["tables"]} == {
        "agent_data_assets",
        "agent_asset_versions",
        "agent_workflows",
        "agent_workflow_runs",
        "agent_asset_lineage",
    }
    assert all(not item["unregistered_writer_paths"] for item in report["tables"])

    run_spec = crosswalk.LEGACY_TABLES["agent_workflow_runs"]
    run_rule = next(
        rule for rule in run_spec.rules if rule.target_contract == "platform_run"
    )
    assert run_rule.policy == crosswalk.MappingPolicy.PROHIBITED


@pytest.mark.parametrize(
    "sql",
    (
        "UPDATE agent_data_assets SET asset_name = :name",
        "UPDATE agent_data_catalog SET version = :version",
        "UPDATE {T_DATA_CATALOG} SET version = :version",
    ),
)
def test_inventory_rejects_an_unregistered_legacy_writer(tmp_path, sql):
    _write_inventory_skeleton(tmp_path)
    rogue = tmp_path / "data_agent" / "rogue_writer.py"
    rogue.write_text(f'SQL = "{sql}"\n', encoding="utf-8")

    report = crosswalk.build_inventory_report(tmp_path)

    assert report["status"] == "invalid"
    asset = next(
        item for item in report["tables"]
        if item["table_name"] == "agent_data_assets"
    )
    assert asset["unregistered_writer_paths"] == ["data_agent/rogue_writer.py"]


def test_crosswalk_resource_plan_is_validated_deterministic_and_read_only():
    first = crosswalk.plan_crosswalk(_candidate())
    second = crosswalk.plan_crosswalk(_candidate())

    assert first["disposition"] == "eligible"
    assert first["plan_id"] == second["plan_id"]
    assert first["mutates_database"] is False
    assert first["target_payload"]["resource_kind"] == "dataset"


def test_crosswalk_blocks_incomplete_version_evidence():
    plan = crosswalk.plan_crosswalk(
        _candidate(
            target_contract="resource_version",
            target_payload={
                "tenant_id": "tenant-a",
                "resource_urn": "gda://tenant-a/dataset/land-use-parcels",
            },
        )
    )

    assert plan["disposition"] == "blocked"
    issue_fields = {issue["field"] for issue in plan["issues"]}
    assert "content_sha256" in issue_fields
    assert "resource_version_id" in issue_fields
    assert "authority_version_ref" in issue_fields


def test_legacy_workflow_run_cannot_fabricate_platform_run():
    plan = crosswalk.plan_crosswalk(
        _candidate(
            source_table="agent_workflow_runs",
            legacy_key="workflow-run:42",
            target_contract="platform_run",
            target_payload={},
        )
    )

    assert plan["disposition"] == "prohibited"
    assert "must never fabricate" in plan["reason"]
    assert plan["mutates_database"] is False


def test_legacy_workflow_run_can_only_become_a_validated_attempt_observation():
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    observation = fixture["contracts"]["attempt_observation"]
    plan = crosswalk.plan_crosswalk(
        _candidate(
            source_table="agent_workflow_runs",
            legacy_key="workflow-run:42",
            target_contract="framework_attempt_observation",
            target_payload=observation,
        )
    )

    assert plan["disposition"] == "eligible"
    assert plan["target_payload"]["framework_kind"] == "legacy"
    assert plan["target_payload"]["observed_state"] == "completed_fixture_only"


def test_crosswalk_candidate_rejects_naive_evidence_timestamp():
    with pytest.raises(ValidationError, match="timezone"):
        crosswalk.CrosswalkCandidate.model_validate(
            _candidate(extracted_at=datetime(2026, 7, 24, 12, 0))
        )


def test_plan_file_reports_eligible_blocked_and_prohibited(tmp_path):
    document = [
        _candidate(),
        _candidate(
            legacy_key="asset:43",
            target_contract="resource_version",
            target_payload={},
        ),
        _candidate(
            source_table="agent_workflow_runs",
            legacy_key="workflow-run:42",
            target_contract="platform_run",
            target_payload={},
        ),
    ]
    path = tmp_path / "candidates.json"
    path.write_text(json.dumps(document), encoding="utf-8")

    report = crosswalk.plan_crosswalk_file(path)

    assert report["status"] == "valid"
    assert [plan["disposition"] for plan in report["plans"]] == [
        "eligible",
        "blocked",
        "prohibited",
    ]


def test_land_use_golden_fixture_binds_contracts_hashes_quality_and_exit_gates():
    report = crosswalk.validate_golden_fixture()

    assert report["status"] == "valid"
    assert report["resource_count"] == 3
    assert report["contract_count"] == 9
    assert report["output_size_bytes"] == 956
    assert report["quality"] == {
        "feature_count": 3,
        "geometry_structure_errors": 0,
        "required_field_missing_count": 0,
        "duplicate_bsm_count": 0,
        "total_area": "17500.50",
    }


def test_golden_fixture_tampering_breaks_the_version_and_artifact_chain(tmp_path):
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    fixture["expected_output_dataset"]["features"][0]["properties"]["TBMJ"] = 1
    tampered = tmp_path / "tampered.json"
    tampered.write_text(json.dumps(fixture), encoding="utf-8")

    report = crosswalk.validate_golden_fixture(tampered)

    assert report["status"] == "invalid"
    assert "target ResourceVersion hash does not match expected output" in report["errors"]
    assert "expected output quality does not match quality expectations" in report["errors"]


def test_golden_fixture_rejects_definition_resource_version_drift(tmp_path):
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    fixture["contracts"]["definition_resource_version"]["content_sha256"] = "f" * 64
    tampered = tmp_path / "definition-drift.json"
    tampered.write_text(json.dumps(fixture), encoding="utf-8")

    report = crosswalk.validate_golden_fixture(tampered)

    assert report["status"] == "invalid"
    assert "definition ResourceVersion hash does not match definition" in report["errors"]


def test_golden_fixture_rejects_artifact_size_drift(tmp_path):
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    fixture["contracts"]["artifact"]["size_bytes"] = 955
    tampered = tmp_path / "artifact-size-drift.json"
    tampered.write_text(json.dumps(fixture), encoding="utf-8")

    report = crosswalk.validate_golden_fixture(tampered)

    assert report["status"] == "invalid"
    assert "artifact size does not match expected output" in report["errors"]


def test_canonical_json_fingerprint_ignores_object_key_order():
    assert canonical_json_fingerprint({"b": 2, "a": {"y": 2, "x": 1}}) == (
        canonical_json_fingerprint({"a": {"x": 1, "y": 2}, "b": 2})
    )


def test_combined_crosswalk_validation_report_is_valid():
    report = crosswalk.build_validation_report()

    assert report["status"] == "valid"
    assert report["inventory"]["status"] == "valid"
    assert report["golden"]["status"] == "valid"
