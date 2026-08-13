import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from data_agent import staging_golden_slice
from data_agent.platform_contracts import (
    quality_result_fingerprint,
    run_success_evidence_fingerprint,
)
from data_agent.test_staging_live_evidence import (
    DEPLOYMENT_UID,
    NOW,
    _candidate,
    _collection,
)

TENANT_ID = "local-dev"
RUN_ID = "00000000-0000-4000-8000-000000000201"
CAPABILITY_ID = "transportation.osm_roads.layered_publish"
DEFINITION_VERSION_ID = "00000000-0000-4000-8000-000000000207"
INPUT_RESOURCE_VERSION_ID = "00000000-0000-4000-8000-000000000208"


def _live_collection() -> dict:
    collection = _collection(_candidate())
    collection["kubernetes"]["pods"][0]["created_at"] = (
        NOW - timedelta(minutes=10)
    ).isoformat()
    return collection


def _ledger() -> dict:
    evidence_time = NOW - timedelta(minutes=5)
    ledger = {
        "tenant_id": TENANT_ID,
        "run_id": RUN_ID,
        "capability_id": CAPABILITY_ID,
        "definition_version_id": DEFINITION_VERSION_ID,
        "definition_sha256": "5" * 64,
        "run_status": "succeeded",
        "run_submitted_at": evidence_time,
        "run_started_at": evidence_time + timedelta(seconds=1),
        "run_terminal_at": evidence_time + timedelta(minutes=1),
        "terminal_actor_subject": "workload:dolphinscheduler-gda-dataops",
        "event_to_status": "succeeded",
        "terminal_event_occurred_at": evidence_time + timedelta(minutes=1),
        "success_evidence_schema": "gda.run_success_evidence.v1",
        "attempt_observation_id": "00000000-0000-4000-8000-000000000204",
        "output_artifact_id": "00000000-0000-4000-8000-000000000205",
        "quality_result_id": "00000000-0000-4000-8000-000000000202",
        "lineage_event_id": "00000000-0000-4000-8000-000000000203",
        "run_success_evidence_fingerprint": "",
        "attempt_framework_kind": "dolphinscheduler",
        "attempt_observed_state": "success",
        "attempt_observed_at": evidence_time + timedelta(seconds=30),
        "output_artifact_role": "output",
        "output_artifact_sha256": "2" * 64,
        "output_resource_version_id": "00000000-0000-4000-8000-000000000206",
        "output_created_at": evidence_time + timedelta(seconds=35),
        "quality_verdict": "passed",
        "quality_resource_version_id": "00000000-0000-4000-8000-000000000206",
        "quality_rule_version_ref": "quality:osm-roads-golden:v1",
        "quality_metrics": {"feature_count": 50366, "critical_failures": 0},
        "quality_evidence_artifact_id": (
            "00000000-0000-4000-8000-000000000209"
        ),
        "quality_result_sha256": "",
        "quality_evaluated_by": "workload:independent-quality-evaluator",
        "quality_evaluated_at": evidence_time + timedelta(seconds=40),
        "quality_evidence_artifact_role": "evidence",
        "lineage_target_resource_version_id": (
            "00000000-0000-4000-8000-000000000206"
        ),
        "lineage_source_resource_version_id": INPUT_RESOURCE_VERSION_ID,
        "lineage_occurred_at": evidence_time + timedelta(seconds=45),
    }
    ledger["run_success_evidence_fingerprint"] = (
        run_success_evidence_fingerprint(
            tenant_id=TENANT_ID,
            run_id=RUN_ID,
            attempt_observation_id=ledger["attempt_observation_id"],
            output_artifact_id=ledger["output_artifact_id"],
            quality_result_id=ledger["quality_result_id"],
            lineage_event_id=ledger["lineage_event_id"],
        )
    )
    ledger["quality_result_sha256"] = quality_result_fingerprint(
        tenant_id=TENANT_ID,
        run_id=RUN_ID,
        resource_version_id=ledger["quality_resource_version_id"],
        rule_version_ref=ledger["quality_rule_version_ref"],
        verdict="passed",
        metrics=ledger["quality_metrics"],
        evidence_artifact_id=ledger["quality_evidence_artifact_id"],
        evaluated_by=ledger["quality_evaluated_by"],
        evaluated_at=ledger["quality_evaluated_at"],
    )
    return ledger


def _refresh_quality_fingerprint(ledger: dict) -> None:
    ledger["quality_result_sha256"] = quality_result_fingerprint(
        tenant_id=TENANT_ID,
        run_id=RUN_ID,
        resource_version_id=ledger["quality_resource_version_id"],
        rule_version_ref=ledger["quality_rule_version_ref"],
        verdict="passed",
        metrics=ledger["quality_metrics"],
        evidence_artifact_id=ledger["quality_evidence_artifact_id"],
        evaluated_by=ledger["quality_evaluated_by"],
        evaluated_at=ledger["quality_evaluated_at"],
    )


def _json_ledger() -> dict:
    return {
        key: value.isoformat() if isinstance(value, datetime) else value
        for key, value in _ledger().items()
    }


def _ledger_export(rows: list[dict] | None = None) -> dict:
    return {
        "schema": staging_golden_slice.LEDGER_EXPORT_SCHEMA,
        "rows": [_json_ledger()] if rows is None else rows,
    }


def test_builds_golden_slice_from_fresh_evidence_gated_run():
    golden = staging_golden_slice.build_staging_golden_slice(
        _ledger(),
        _live_collection(),
        tenant_id=TENANT_ID,
        run_id=RUN_ID,
        capability_id=CAPABILITY_ID,
        definition_version_id=DEFINITION_VERSION_ID,
        input_resource_version_id=INPUT_RESOURCE_VERSION_ID,
        now=NOW,
    )

    assert golden["status"] == "passed"
    assert golden["deployment_uid"] == DEPLOYMENT_UID
    assert golden["run_id"] == RUN_ID
    assert golden["quality_evidence_fingerprint"] == _ledger()[
        "quality_result_sha256"
    ]
    assert golden["run_success_evidence_fingerprint"] == _ledger()[
        "run_success_evidence_fingerprint"
    ]
    assert golden["evidence_fingerprint"] == (
        staging_golden_slice.golden_slice_fingerprint(golden)
    )


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("run_status", "running", "run_status"),
        ("quality_verdict", "failed", "quality_verdict"),
        ("attempt_observed_state", "FAILURE", "attempt_observed_state"),
        ("output_artifact_role", "evidence", "output_artifact_role"),
    ],
)
def test_rejects_incomplete_or_failed_ledger_evidence(field, value, message):
    ledger = _ledger()
    ledger[field] = value

    with pytest.raises(staging_golden_slice.StagingGoldenSliceError, match=message):
        staging_golden_slice.build_staging_golden_slice(
            ledger,
            _live_collection(),
            tenant_id=TENANT_ID,
            run_id=RUN_ID,
            capability_id=CAPABILITY_ID,
            definition_version_id=DEFINITION_VERSION_ID,
            input_resource_version_id=INPUT_RESOURCE_VERSION_ID,
            now=NOW,
        )


def test_rejects_run_that_predates_current_ready_pod():
    collection = _live_collection()
    collection["kubernetes"]["pods"][0]["created_at"] = (
        NOW - timedelta(minutes=2)
    ).isoformat()

    with pytest.raises(
        staging_golden_slice.StagingGoldenSliceError,
        match="predates the newest ready staging Pod",
    ):
        staging_golden_slice.build_staging_golden_slice(
            _ledger(),
            collection,
            tenant_id=TENANT_ID,
            run_id=RUN_ID,
            capability_id=CAPABILITY_ID,
            definition_version_id=DEFINITION_VERSION_ID,
            input_resource_version_id=INPUT_RESOURCE_VERSION_ID,
            now=NOW,
        )


def test_rejects_stale_run_and_cross_capability_reuse():
    ledger = _ledger()
    old = NOW - timedelta(hours=2)
    for field in (
        "run_submitted_at",
        "run_started_at",
        "run_terminal_at",
        "terminal_event_occurred_at",
        "attempt_observed_at",
        "output_created_at",
        "quality_evaluated_at",
        "lineage_occurred_at",
    ):
        ledger[field] = old
    _refresh_quality_fingerprint(ledger)
    collection = _live_collection()
    collection["kubernetes"]["pods"][0]["created_at"] = (
        old - timedelta(minutes=1)
    ).isoformat()

    with pytest.raises(staging_golden_slice.StagingGoldenSliceError, match="stale"):
        staging_golden_slice.build_staging_golden_slice(
            ledger,
            collection,
            tenant_id=TENANT_ID,
            run_id=RUN_ID,
            capability_id=CAPABILITY_ID,
            definition_version_id=DEFINITION_VERSION_ID,
            input_resource_version_id=INPUT_RESOURCE_VERSION_ID,
            now=NOW,
            max_run_age_seconds=900,
        )

    ledger = _ledger()
    ledger["capability_id"] = "transportation.other"
    with pytest.raises(
        staging_golden_slice.StagingGoldenSliceError,
        match="capability_id",
    ):
        staging_golden_slice.build_staging_golden_slice(
            ledger,
            _live_collection(),
            tenant_id=TENANT_ID,
            run_id=RUN_ID,
            capability_id=CAPABILITY_ID,
            definition_version_id=DEFINITION_VERSION_ID,
            input_resource_version_id=INPUT_RESOURCE_VERSION_ID,
            now=NOW,
        )


def test_rejects_non_independent_quality_and_binding_drift():
    ledger = _ledger()
    ledger["quality_evaluated_by"] = ledger["terminal_actor_subject"]
    _refresh_quality_fingerprint(ledger)
    with pytest.raises(
        staging_golden_slice.StagingGoldenSliceError,
        match="not independent",
    ):
        staging_golden_slice.build_staging_golden_slice(
            ledger,
            _live_collection(),
            tenant_id=TENANT_ID,
            run_id=RUN_ID,
            capability_id=CAPABILITY_ID,
            definition_version_id=DEFINITION_VERSION_ID,
            input_resource_version_id=INPUT_RESOURCE_VERSION_ID,
            now=NOW,
        )

    collection = _live_collection()
    collection["kubernetes"]["deployment"]["image"] = "gis-agent:latest"
    with pytest.raises(
        staging_golden_slice.StagingGoldenSliceError,
        match="digest-bound",
    ):
        staging_golden_slice.build_staging_golden_slice(
            _ledger(),
            collection,
            tenant_id=TENANT_ID,
            run_id=RUN_ID,
            capability_id=CAPABILITY_ID,
            definition_version_id=DEFINITION_VERSION_ID,
            input_resource_version_id=INPUT_RESOURCE_VERSION_ID,
            now=datetime.now(UTC),
        )


def test_loads_only_one_allowlisted_protected_ledger_row(tmp_path: Path):
    path = tmp_path / "ledger.json"
    path.write_text(json.dumps(_ledger_export()), encoding="utf-8")

    assert staging_golden_slice.load_golden_ledger_export(path.as_posix()) == (
        _json_ledger()
    )

    extra = _ledger_export()
    extra["rows"][0]["secret"] = "must-not-pass"
    path.write_text(json.dumps(extra), encoding="utf-8")
    with pytest.raises(
        staging_golden_slice.StagingGoldenSliceError,
        match="fields are invalid",
    ):
        staging_golden_slice.load_golden_ledger_export(path.as_posix())


@pytest.mark.parametrize("rows", [[], [_json_ledger(), _json_ledger()]])
def test_rejects_missing_or_ambiguous_ledger_export(
    tmp_path: Path, rows: list[dict]
):
    path = tmp_path / "ledger.json"
    path.write_text(json.dumps(_ledger_export(rows)), encoding="utf-8")

    with pytest.raises(
        staging_golden_slice.StagingGoldenSliceError,
        match="exactly one evidence set",
    ):
        staging_golden_slice.load_golden_ledger_export(path.as_posix())


def test_cli_builds_golden_only_from_explicit_export_and_collection(
    tmp_path: Path, capsys
):
    ledger = tmp_path / "ledger.json"
    ledger.write_text(json.dumps(_ledger_export()), encoding="utf-8")
    collection = tmp_path / "collection.json"
    collection.write_text(json.dumps(_live_collection()), encoding="utf-8")

    result = staging_golden_slice.main(
        [
            "--tenant-id",
            TENANT_ID,
            "--run-id",
            RUN_ID,
            "--capability-id",
            CAPABILITY_ID,
            "--definition-version-id",
            DEFINITION_VERSION_ID,
            "--input-resource-version-id",
            INPUT_RESOURCE_VERSION_ID,
            "--ledger-evidence",
            ledger.as_posix(),
            "--live-collection",
            collection.as_posix(),
            "--max-run-age-seconds",
            "10000000",
        ]
    )

    assert result == 0
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "passed"
    assert report["run_id"] == RUN_ID


def test_protected_sql_is_read_only_tenant_scoped_and_parameterized():
    sql = (
        Path(staging_golden_slice.__file__).with_name(
            "staging_golden_ledger.sql"
        )
    ).read_text(encoding="utf-8")

    assert "BEGIN READ ONLY" in sql
    assert "SET LOCAL ROLE gda_control_gateway" in sql
    assert "set_config('app.current_tenant', :'tenant_id', true)" in sql
    assert "run.tenant_id = :'tenant_id'" in sql
    assert "run.run_id = CAST(:'run_id' AS uuid)" in sql
    assert "definition.capability_id = :'capability_id'" in sql
    assert "gda.staging_golden_ledger_export.v1" in sql
    assert "INSERT " not in sql
    assert "UPDATE " not in sql
    assert "DELETE " not in sql
    assert "COMMIT" not in sql
    assert sql.rstrip().endswith("ROLLBACK;")
