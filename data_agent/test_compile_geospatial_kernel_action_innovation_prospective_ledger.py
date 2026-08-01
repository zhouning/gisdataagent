import hashlib
import json
from copy import deepcopy
from datetime import UTC, datetime, timedelta

import pytest

from data_agent.uwm.geospatial_kernel_v2.action_innovation_prospective_verification import (
    ACTION_INNOVATION_PROSPECTIVE_SCORE_SCHEMA,
)
from scripts.compile_geospatial_kernel_action_innovation_prospective_ledger import (
    SCHEMA,
    compile_prospective_evidence_ledger,
    main,
)
from scripts.verify_geospatial_kernel_action_innovation_uncertainty_shadow import (
    REPORT_SCHEMA,
)

NETWORK_ID = "center-hill:dam-to-gauge:full-incremental-subnetwork-v1"
START = datetime(2026, 8, 1, tzinfo=UTC)
IDENTITY = {
    "point_freeze_sha256": "a" * 64,
    "point_parameter_sha256": "b" * 64,
    "uncertainty_freeze_sha256": "c" * 64,
    "uncertainty_parameter_sha256": "d" * 64,
}


def _report(*, request_id: str, issue_time: datetime, network_id: str = NETWORK_ID) -> dict:
    rows = []
    for horizon in (1, 3, 6, 12):
        point = 100.0 + horizon
        rows.append(
            {
                "horizon_hours": horizon,
                "target_valid_time": (issue_time + timedelta(hours=horizon)).isoformat(),
                "point_discharge_m3s": point,
                "lower_discharge_m3s": point - 10.0,
                "upper_discharge_m3s": point + 10.0,
                "observed_discharge_m3s": point,
                "error_m3s": 0.0,
                "absolute_error_m3s": 0.0,
                "interval_contains_observation": True,
                "interval_width_m3s": 20.0,
                "interval_score": 20.0,
            }
        )
    aggregate = {
        "sample_count": 4,
        "mae_m3s": 0.0,
        "rmse_m3s": 0.0,
        "bias_m3s": 0.0,
        "empirical_marginal_coverage": 1.0,
        "mean_interval_width_m3s": 20.0,
        "mean_interval_score": 20.0,
    }
    forecast_hash = hashlib.sha256(f"forecast:{request_id}".encode()).hexdigest()
    outcome_hash = hashlib.sha256(f"outcome:{request_id}".encode()).hexdigest()
    observation_hash = hashlib.sha256(
        f"observation-source:{request_id}".encode()
    ).hexdigest()
    return {
        "schema": REPORT_SCHEMA,
        "status": "single_issue_shadow_outcomes_scored_not_admitted",
        "generated_at": (issue_time + timedelta(hours=13)).isoformat(),
        "source_artifacts": {
            "forecast_receipt": {"sha256": forecast_hash, "size_bytes": 1000},
            "outcomes": {"sha256": outcome_hash, "size_bytes": 500},
            "observation_batch": {
                "sha256": observation_hash,
                "size_bytes": 250,
            },
            "uncertainty_freeze": {
                "path": "/repo/uncertainty-freeze.json",
                "sha256": IDENTITY["uncertainty_freeze_sha256"],
                "size_bytes": 4000,
            },
        },
        "request_identity": {
            "request_id": request_id,
            "network_id": network_id,
            "issue_time": issue_time.isoformat(),
            "forecast_generated_at": (issue_time + timedelta(minutes=5)).isoformat(),
            "outcomes_available_at": (issue_time + timedelta(hours=12, minutes=5)).isoformat(),
            "outlet_observation_provenance_id": f"authoritative:{request_id}",
            "source_observation_artifact_sha256": observation_hash,
            "source_observation_artifact_size_bytes": 250,
        },
        "frozen_candidate_identity": dict(IDENTITY),
        "score": {
            "schema": ACTION_INNOVATION_PROSPECTIVE_SCORE_SCHEMA,
            "target_marginal_coverage": 0.9,
            "rows": rows,
            "aggregate": aggregate,
            "single_issue_only": True,
            "finite_sample_coverage_guarantee_claimed": False,
            "conditional_coverage_guarantee_claimed": False,
            "admitted": False,
        },
        "ordering_audit": {
            "forecast_generated_after_uncertainty_freeze": True,
            "forecast_generated_within_issue_latency_limit": True,
            "forecast_generated_before_first_target": True,
            "all_observations_available_no_earlier_than_target": True,
            "outcome_document_bound_to_exact_forecast_receipt": True,
            "source_observation_artifact_verified": True,
            "outcome_values_match_source_observation_batch": True,
            "outcomes_declared_available_before_scoring": True,
            "trusted_external_timestamp_verified": False,
        },
        "claim_boundary": {
            "fresh_window_separation_verified": True,
            "single_issue_shadow_score_available": True,
            "independent_timestamped_prospective_validation": False,
            "multi_issue_uncertainty_validated": False,
            "multi_system_uncertainty_validated": False,
            "coverage_or_radii_recalibrated": False,
            "runtime_default_enabled": False,
            "uncertainty_candidate_admitted": False,
        },
    }


def _write(path, payload: dict) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


@pytest.fixture(autouse=True)
def _stub_recomputed_evidence_audit(monkeypatch):
    def load(path, *, repository_root):
        body = path.read_bytes()
        return {
            "audit_path": path,
            "audit_body": body,
            "audit": {},
            "verification_path": path,
            "verification_body": body,
            "verification": json.loads(body),
        }

    monkeypatch.setattr(
        "scripts.compile_geospatial_kernel_action_innovation_prospective_ledger."
        "load_and_recompute_prospective_evidence_audit",
        load,
    )

    def load_issued(path, *, runtime, frozen_at):
        del runtime, frozen_at
        body = path.read_bytes()
        payload = json.loads(body)
        request = payload["request_identity"]
        return {
            "path": path,
            "body": body,
            "forecast_sha256": payload["source_artifacts"]["forecast_receipt"][
                "sha256"
            ],
            "request_id": request["request_id"],
            "network_id": request["network_id"],
            "issue_time": datetime.fromisoformat(request["issue_time"]),
            "issue_time_text": request["issue_time"],
            "target_valid_times": tuple(
                datetime.fromisoformat(row["target_valid_time"])
                for row in payload["score"]["rows"]
            ),
            "candidate_identity": payload["frozen_candidate_identity"],
        }

    monkeypatch.setattr(
        "scripts.compile_geospatial_kernel_action_innovation_prospective_ledger."
        "_load_issued_forecast",
        load_issued,
    )


def test_ledger_recomputes_and_accumulates_two_unique_issues(tmp_path) -> None:
    first = tmp_path / "first.json"
    second = tmp_path / "second.json"
    _write(first, _report(request_id="issue-001", issue_time=START))
    _write(
        second,
        _report(request_id="issue-002", issue_time=START + timedelta(days=1)),
    )

    ledger = compile_prospective_evidence_ledger(
        [second, first],
        forecast_receipt_paths=[second, first],
    )

    assert ledger["schema"] == SCHEMA
    assert ledger["evidence_coverage"]["issue_count"] == 2
    assert ledger["evidence_coverage"]["scored_row_count"] == 8
    assert ledger["aggregate"]["all_horizons"]["sample_count"] == 8
    assert ledger["aggregate"]["by_horizon_hours"]["12"]["sample_count"] == 2
    assert ledger["evidence_gates"]["multi_issue_shadow_evidence_present"] is True
    assert ledger["evidence_gates"]["all_source_observation_artifacts_verified"] is True
    assert (
        ledger["evidence_gates"][
            "all_verification_reports_recomputed_from_exact_sources"
        ]
        is True
    )
    assert ledger["evidence_gates"]["multi_system_evidence_present"] is False
    assert ledger["claim_boundary"]["multi_issue_uncertainty_validated"] is False
    assert [item["request_id"] for item in ledger["verification_artifacts"]] == [
        "issue-001",
        "issue-002",
    ]


def test_ledger_exposes_matured_unscored_and_pending_issued_forecasts(
    tmp_path,
    monkeypatch,
) -> None:
    scored = tmp_path / "scored.json"
    matured = tmp_path / "matured.json"
    pending = tmp_path / "pending.json"
    _write(scored, _report(request_id="issue-001", issue_time=START))
    _write(
        matured,
        _report(request_id="issue-002", issue_time=START + timedelta(days=1)),
    )
    _write(
        pending,
        _report(request_id="issue-003", issue_time=START + timedelta(days=20)),
    )
    monkeypatch.setattr(
        "scripts.compile_geospatial_kernel_action_innovation_prospective_ledger._now",
        lambda: START + timedelta(days=10),
    )

    ledger = compile_prospective_evidence_ledger(
        [scored],
        forecast_receipt_paths=[scored, matured, pending],
    )

    assert ledger["evidence_coverage"]["issued_forecast_count"] == 3
    assert ledger["evidence_coverage"]["scored_issue_count"] == 1
    assert ledger["evidence_coverage"]["unscored_matured_issue_count"] == 1
    assert ledger["evidence_coverage"]["pending_outcome_count"] == 1
    assert [value["reconciliation_status"] for value in ledger["issuance_inventory"]] == [
        "scored_and_source_recomputed",
        "unscored_matured",
        "pending_outcomes",
    ]
    assert ledger["evidence_gates"]["all_matured_issued_forecasts_scored"] is False
    assert ledger["claim_boundary"]["selective_reporting_bias_excluded"] is False


def test_ledger_rejects_audit_not_in_issuance_inventory(tmp_path) -> None:
    audit = tmp_path / "audit.json"
    different_issuance = tmp_path / "different-issuance.json"
    _write(audit, _report(request_id="issue-001", issue_time=START))
    _write(
        different_issuance,
        _report(request_id="issue-002", issue_time=START + timedelta(days=1)),
    )

    with pytest.raises(ValueError, match="audit_not_in_issuance_inventory"):
        compile_prospective_evidence_ledger(
            [audit],
            forecast_receipt_paths=[different_issuance],
        )


def test_ledger_rejects_duplicate_network_issue(tmp_path) -> None:
    first = tmp_path / "first.json"
    second = tmp_path / "second.json"
    _write(first, _report(request_id="issue-001", issue_time=START))
    _write(second, _report(request_id="issue-002", issue_time=START))

    with pytest.raises(ValueError, match="duplicate_issue"):
        compile_prospective_evidence_ledger(
            [first, second],
            forecast_receipt_paths=[first, second],
        )


def test_ledger_rejects_reused_observation_artifact_across_issues(tmp_path) -> None:
    first = tmp_path / "first.json"
    second = tmp_path / "second.json"
    first_report = _report(request_id="issue-001", issue_time=START)
    second_report = _report(
        request_id="issue-002",
        issue_time=START + timedelta(days=1),
    )
    second_report["source_artifacts"]["observation_batch"] = deepcopy(
        first_report["source_artifacts"]["observation_batch"]
    )
    second_report["request_identity"]["source_observation_artifact_sha256"] = (
        first_report["request_identity"]["source_observation_artifact_sha256"]
    )
    _write(first, first_report)
    _write(second, second_report)

    with pytest.raises(ValueError, match="duplicate_issue"):
        compile_prospective_evidence_ledger(
            [first, second],
            forecast_receipt_paths=[first, second],
        )


def test_ledger_rejects_candidate_or_network_mixing(tmp_path) -> None:
    first = tmp_path / "first.json"
    mixed_candidate = tmp_path / "mixed-candidate.json"
    mixed_network = tmp_path / "mixed-network.json"
    _write(first, _report(request_id="issue-001", issue_time=START))
    candidate = _report(
        request_id="issue-002",
        issue_time=START + timedelta(days=1),
    )
    candidate["frozen_candidate_identity"]["point_freeze_sha256"] = "e" * 64
    _write(mixed_candidate, candidate)
    _write(
        mixed_network,
        _report(
            request_id="issue-003",
            issue_time=START + timedelta(days=2),
            network_id="different-basin:dam-to-gauge",
        ),
    )

    with pytest.raises(ValueError, match="candidate_identity_mismatch"):
        compile_prospective_evidence_ledger(
            [first, mixed_candidate],
            forecast_receipt_paths=[first, mixed_candidate],
        )
    with pytest.raises(ValueError, match="network_identity_mismatch"):
        compile_prospective_evidence_ledger(
            [first, mixed_network],
            forecast_receipt_paths=[first, mixed_network],
        )


def test_ledger_rejects_tampered_score_row_or_aggregate(tmp_path) -> None:
    row_path = tmp_path / "row.json"
    aggregate_path = tmp_path / "aggregate.json"
    row = _report(request_id="issue-001", issue_time=START)
    row["score"]["rows"][0]["error_m3s"] = 9.0
    aggregate = deepcopy(_report(request_id="issue-002", issue_time=START))
    aggregate["score"]["aggregate"]["mae_m3s"] = 9.0
    _write(row_path, row)
    _write(aggregate_path, aggregate)

    with pytest.raises(ValueError, match="score_row_invalid"):
        compile_prospective_evidence_ledger(
            [row_path],
            forecast_receipt_paths=[row_path],
        )
    with pytest.raises(ValueError, match="aggregate_invalid"):
        compile_prospective_evidence_ledger(
            [aggregate_path],
            forecast_receipt_paths=[aggregate_path],
        )


def test_ledger_cli_writes_once(tmp_path, monkeypatch) -> None:
    verification = tmp_path / "verification.json"
    output = tmp_path / "ledger.json"
    _write(verification, _report(request_id="issue-001", issue_time=START))
    monkeypatch.setattr(
        "sys.argv",
        [
            "compile_geospatial_kernel_action_innovation_prospective_ledger.py",
            "--forecast-receipt",
            str(verification),
            "--evidence-audit",
            str(verification),
            "--output",
            str(output),
        ],
    )

    assert main() == 0
    assert (
        json.loads(output.read_bytes())["claim_boundary"]["uncertainty_candidate_admitted"] is False
    )

    with pytest.raises(ValueError, match="ledger_refuses_overwrite"):
        main()
