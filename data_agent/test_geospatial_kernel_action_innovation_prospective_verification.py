import hashlib
import json
from copy import deepcopy
from datetime import datetime, timedelta

import pytest

from data_agent.uwm.geospatial_kernel_v2.action_conditioned_transition import (
    HourlyActionForcingSeries,
    OutletTransitionState,
)
from data_agent.uwm.geospatial_kernel_v2.action_innovation_prospective_verification import (
    ACTION_INNOVATION_AUTHORITATIVE_OBSERVATION_BATCH_SCHEMA,
    ActionInnovationProspectiveOutcomeDocument,
    ProspectiveOutletObservation,
    action_innovation_authoritative_observation_batch_from_dict,
    action_innovation_prospective_outcomes_from_dict,
)
from data_agent.uwm.geospatial_kernel_v2.action_innovation_shadow_request import (
    ActionInnovationShadowRequest,
)
from data_agent.uwm.geospatial_kernel_v2.action_innovation_shadow_runtime import (
    IssueTimeInputAttestation,
)
from data_agent.uwm.geospatial_kernel_v2.action_innovation_uncertainty_shadow_runtime import (
    DEFAULT_UNCERTAINTY_FREEZE_PATH,
)
from scripts.audit_geospatial_kernel_action_innovation_prospective_evidence import (
    compile_prospective_evidence_audit,
    load_and_recompute_prospective_evidence_audit,
)
from scripts.compile_geospatial_kernel_action_innovation_prospective_ledger import (
    compile_prospective_evidence_ledger,
)
from scripts.finalize_geospatial_kernel_action_innovation_prospective_issue import (
    EVIDENCE_AUDIT_FILENAME,
    OUTCOME_FILENAME,
    VERIFICATION_FILENAME,
    finalize_prospective_issue,
)
from scripts.finalize_geospatial_kernel_action_innovation_prospective_issue import (
    main as finalize_main,
)
from scripts.run_geospatial_kernel_action_innovation_uncertainty_shadow import (
    compile_uncertainty_shadow_receipt,
)
from scripts.verify_geospatial_kernel_action_innovation_uncertainty_shadow import (
    compile_prospective_verification,
    main,
)

HORIZONS = (1, 3, 6, 12)
FROZEN_AT = datetime.fromisoformat(
    json.loads(DEFAULT_UNCERTAINTY_FREEZE_PATH.read_bytes())["frozen_at"]
)
ISSUE = FROZEN_AT + timedelta(hours=1)
VERIFIED_AT = ISSUE + timedelta(hours=13)
AUDITED_AT = VERIFIED_AT + timedelta(minutes=5)
NETWORK_ID = "center-hill:dam-to-gauge:full-incremental-subnetwork-v1"


def _request() -> ActionInnovationShadowRequest:
    valid_times = tuple(ISSUE + timedelta(hours=index) for index in range(-8, 13))
    return ActionInnovationShadowRequest(
        request_id="center-hill-prospective-issue-0001",
        network_id=NETWORK_ID,
        shadow_only_acknowledged=True,
        issue_time=ISSUE,
        target_valid_times=tuple(ISSUE + timedelta(hours=horizon) for horizon in HORIZONS),
        outlet_state=OutletTransitionState(
            valid_at=ISSUE - timedelta(hours=1),
            available_at=ISSUE,
            discharge_m3s=100.0,
            provenance_id="outlet-observation-prospective-0001",
            evidence_level="authoritative",
            observed=True,
        ),
        hourly_inputs=HourlyActionForcingSeries(
            valid_times=valid_times,
            action_release_m3s=tuple(50.0 + float(index % 4) for index in range(len(valid_times))),
            nwm_lateral_inflow_m3s=tuple(2.0 for _ in valid_times),
            action_provenance_id="release-plan-prospective-0001",
            forcing_provenance_id="nwm-forecast-prospective-0001",
            action_plan_vintage_verified=True,
            forcing_vintage_verified=True,
        ),
        input_attestation=IssueTimeInputAttestation(
            issue_time=ISSUE,
            network_id=NETWORK_ID,
            action_provenance_id="release-plan-prospective-0001",
            action_plan_available_at=ISSUE - timedelta(minutes=30),
            forcing_provenance_id="nwm-forecast-prospective-0001",
            forcing_forecast_available_at=ISSUE - timedelta(minutes=15),
            outlet_state_provenance_id="outlet-observation-prospective-0001",
            outlet_state_available_at=ISSUE,
            verification_id="prospective-vintage-audit-0001",
        ),
    )


def _forecast_receipt() -> dict:
    request_body = json.dumps(_request().as_dict()).encode()
    receipt = compile_uncertainty_shadow_receipt(
        request_body,
        enable_shadow=True,
    )
    receipt["generated_at"] = (ISSUE + timedelta(minutes=5)).isoformat()
    return receipt


def _receipt_body(receipt: dict | None = None) -> bytes:
    return (json.dumps(receipt or _forecast_receipt(), sort_keys=True) + "\n").encode()


def _observation_batch(forecast_body: bytes) -> dict:
    receipt = json.loads(forecast_body)
    point = receipt["result"]["interval_forecast"]["point_forecast"]
    observations = [
        {
            "target_valid_time": target,
            "observed_discharge_m3s": observed,
            "observation_available_at": (
                datetime.fromisoformat(target) + timedelta(minutes=5)
            ).isoformat(),
        }
        for target, observed in zip(
            point["target_valid_times"],
            point["target_discharge_m3s"],
            strict=True,
        )
    ]
    return {
        "schema": ACTION_INNOVATION_AUTHORITATIVE_OBSERVATION_BATCH_SCHEMA,
        "network_id": NETWORK_ID,
        "outlet_observation_provenance_id": "authoritative-outlet-series-0001",
        "outlet_observation_evidence_level": "authoritative",
        "retrieved_at": max(
            value["observation_available_at"] for value in observations
        ),
        "observations": observations,
        "values_imputed": False,
    }


def _observation_batch_body(forecast_body: bytes) -> bytes:
    return (json.dumps(_observation_batch(forecast_body), sort_keys=True) + "\n").encode()


def _outcomes(forecast_body: bytes) -> ActionInnovationProspectiveOutcomeDocument:
    receipt = json.loads(forecast_body)
    observation_body = _observation_batch_body(forecast_body)
    batch = action_innovation_authoritative_observation_batch_from_dict(
        json.loads(observation_body)
    )
    observations = tuple(
        ProspectiveOutletObservation(
            target_valid_time=value.target_valid_time,
            observed_discharge_m3s=value.observed_discharge_m3s,
            observation_available_at=value.observation_available_at,
        )
        for value in batch.observations
    )
    return ActionInnovationProspectiveOutcomeDocument(
        request_id=receipt["request_identity"]["request_id"],
        forecast_receipt_sha256=hashlib.sha256(forecast_body).hexdigest(),
        source_observation_artifact_sha256=hashlib.sha256(observation_body).hexdigest(),
        source_observation_artifact_size_bytes=len(observation_body),
        outcomes_available_at=batch.retrieved_at,
        outlet_observation_provenance_id=batch.outlet_observation_provenance_id,
        outlet_observation_evidence_level="authoritative",
        observations=observations,
    )


def _outcome_body(forecast_body: bytes) -> bytes:
    return (json.dumps(_outcomes(forecast_body).as_dict(), sort_keys=True) + "\n").encode()


def test_prospective_outcome_document_round_trips_strictly() -> None:
    forecast_body = _receipt_body()
    original = _outcomes(forecast_body)

    loaded = action_innovation_prospective_outcomes_from_dict(original.as_dict())

    assert loaded == original
    assert loaded.as_dict() == original.as_dict()
    assert loaded.as_dict()["values_imputed"] is False


def test_authoritative_observation_batch_round_trips_strictly() -> None:
    forecast_body = _receipt_body()
    original = _observation_batch(forecast_body)

    loaded = action_innovation_authoritative_observation_batch_from_dict(original)

    assert loaded.as_dict() == original
    assert loaded.network_id == NETWORK_ID


def test_prospective_outcome_rejects_observation_available_before_target() -> None:
    forecast_body = _receipt_body()
    payload = _outcomes(forecast_body).as_dict()
    payload["observations"][0]["observation_available_at"] = (
        datetime.fromisoformat(payload["observations"][0]["target_valid_time"])
        - timedelta(seconds=1)
    ).isoformat()

    with pytest.raises(ValueError, match="prospective_observation_invalid"):
        action_innovation_prospective_outcomes_from_dict(payload)


def test_prospective_verification_scores_exact_frozen_forecast(monkeypatch) -> None:
    monkeypatch.setattr(
        "scripts.verify_geospatial_kernel_action_innovation_uncertainty_shadow._now",
        lambda: VERIFIED_AT,
    )
    forecast_body = _receipt_body()

    report = compile_prospective_verification(
        forecast_body,
        _outcome_body(forecast_body),
        _observation_batch_body(forecast_body),
    )

    assert report["status"] == "single_issue_shadow_outcomes_scored_not_admitted"
    assert report["score"]["aggregate"]["sample_count"] == 4
    assert report["score"]["aggregate"]["mae_m3s"] == pytest.approx(0.0)
    assert report["score"]["aggregate"]["empirical_marginal_coverage"] == 1.0
    assert report["request_identity"]["network_id"] == NETWORK_ID
    observation_body = _observation_batch_body(forecast_body)
    assert report["request_identity"][
        "source_observation_artifact_sha256"
    ] == hashlib.sha256(observation_body).hexdigest()
    assert report["request_identity"]["source_observation_artifact_size_bytes"] == len(
        observation_body
    )
    assert report["source_artifacts"]["observation_batch"] == {
        "sha256": hashlib.sha256(observation_body).hexdigest(),
        "size_bytes": len(observation_body),
    }
    assert report["ordering_audit"]["trusted_external_timestamp_verified"] is False
    assert report["claim_boundary"] == {
        "fresh_window_separation_verified": True,
        "single_issue_shadow_score_available": True,
        "independent_timestamped_prospective_validation": False,
        "multi_issue_uncertainty_validated": False,
        "multi_system_uncertainty_validated": False,
        "coverage_or_radii_recalibrated": False,
        "runtime_default_enabled": False,
        "uncertainty_candidate_admitted": False,
    }


def test_prospective_verification_rejects_wrong_receipt_binding(monkeypatch) -> None:
    monkeypatch.setattr(
        "scripts.verify_geospatial_kernel_action_innovation_uncertainty_shadow._now",
        lambda: VERIFIED_AT,
    )
    forecast_body = _receipt_body()
    payload = _outcomes(forecast_body).as_dict()
    payload["forecast_receipt_sha256"] = "f" * 64

    with pytest.raises(ValueError, match="outcome_forecast_binding_invalid"):
        compile_prospective_verification(
            forecast_body,
            json.dumps(payload).encode(),
            _observation_batch_body(forecast_body),
        )


def test_prospective_verification_rejects_wrong_observation_artifact_binding(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "scripts.verify_geospatial_kernel_action_innovation_uncertainty_shadow._now",
        lambda: VERIFIED_AT,
    )
    forecast_body = _receipt_body()
    batch = _observation_batch(forecast_body)
    batch["observations"][0]["observed_discharge_m3s"] += 1.0

    with pytest.raises(ValueError, match="observation_artifact_binding_invalid"):
        compile_prospective_verification(
            forecast_body,
            _outcome_body(forecast_body),
            (json.dumps(batch, sort_keys=True) + "\n").encode(),
        )


def test_prospective_verification_rejects_source_content_rewritten_with_new_hash(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "scripts.verify_geospatial_kernel_action_innovation_uncertainty_shadow._now",
        lambda: VERIFIED_AT,
    )
    forecast_body = _receipt_body()
    batch = _observation_batch(forecast_body)
    batch["observations"][0]["observed_discharge_m3s"] += 1.0
    batch_body = (json.dumps(batch, sort_keys=True) + "\n").encode()
    outcomes = _outcomes(forecast_body).as_dict()
    outcomes["source_observation_artifact_sha256"] = hashlib.sha256(
        batch_body
    ).hexdigest()
    outcomes["source_observation_artifact_size_bytes"] = len(batch_body)

    with pytest.raises(ValueError, match="observation_content_mismatch"):
        compile_prospective_verification(
            forecast_body,
            json.dumps(outcomes).encode(),
            batch_body,
        )


def test_prospective_verification_rejects_post_target_forecast(monkeypatch) -> None:
    monkeypatch.setattr(
        "scripts.verify_geospatial_kernel_action_innovation_uncertainty_shadow._now",
        lambda: VERIFIED_AT,
    )
    receipt = _forecast_receipt()
    receipt["generated_at"] = (ISSUE + timedelta(hours=2)).isoformat()
    forecast_body = _receipt_body(receipt)

    with pytest.raises(ValueError, match="prospective_ordering_invalid"):
        compile_prospective_verification(
            forecast_body,
            _outcome_body(forecast_body),
            _observation_batch_body(forecast_body),
        )


def test_prospective_verification_rejects_embedded_parameter_change(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "scripts.verify_geospatial_kernel_action_innovation_uncertainty_shadow._now",
        lambda: VERIFIED_AT,
    )
    receipt = _forecast_receipt()
    receipt["result"]["interval_forecast"]["parameters"]["target_marginal_coverage"] = 0.95
    forecast_body = _receipt_body(receipt)

    with pytest.raises(ValueError, match="embedded_parameter_mismatch"):
        compile_prospective_verification(
            forecast_body,
            _outcome_body(forecast_body),
            _observation_batch_body(forecast_body),
        )


def test_prospective_verification_rejects_admission_inflation(monkeypatch) -> None:
    monkeypatch.setattr(
        "scripts.verify_geospatial_kernel_action_innovation_uncertainty_shadow._now",
        lambda: VERIFIED_AT,
    )
    receipt = deepcopy(_forecast_receipt())
    receipt["claim_boundary"]["admitted"] = True
    forecast_body = _receipt_body(receipt)

    with pytest.raises(ValueError, match="forecast_receipt_invalid"):
        compile_prospective_verification(
            forecast_body,
            _outcome_body(forecast_body),
            _observation_batch_body(forecast_body),
        )


def test_prospective_verification_cli_writes_once(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        "scripts.verify_geospatial_kernel_action_innovation_uncertainty_shadow._now",
        lambda: VERIFIED_AT,
    )
    forecast_body = _receipt_body()
    forecast_path = tmp_path / "forecast.json"
    outcome_path = tmp_path / "outcomes.json"
    observation_batch_path = tmp_path / "observation-batch.json"
    output_path = tmp_path / "verification.json"
    forecast_path.write_bytes(forecast_body)
    outcome_path.write_bytes(_outcome_body(forecast_body))
    observation_batch_path.write_bytes(_observation_batch_body(forecast_body))
    monkeypatch.setattr(
        "sys.argv",
        [
            "verify_geospatial_kernel_action_innovation_uncertainty_shadow.py",
            "--forecast-receipt",
            str(forecast_path),
            "--outcomes",
            str(outcome_path),
            "--observation-batch",
            str(observation_batch_path),
            "--output",
            str(output_path),
        ],
    )

    assert main() == 0
    report = json.loads(output_path.read_bytes())
    assert report["claim_boundary"]["uncertainty_candidate_admitted"] is False

    with pytest.raises(ValueError, match="verification_refuses_overwrite"):
        main()


def test_evidence_audit_reopens_sources_and_feeds_ledger(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        "scripts.verify_geospatial_kernel_action_innovation_uncertainty_shadow._now",
        lambda: VERIFIED_AT,
    )
    monkeypatch.setattr(
        "scripts.audit_geospatial_kernel_action_innovation_prospective_evidence._now",
        lambda: AUDITED_AT,
    )
    forecast_body = _receipt_body()
    outcome_body = _outcome_body(forecast_body)
    observation_body = _observation_batch_body(forecast_body)
    verification = compile_prospective_verification(
        forecast_body,
        outcome_body,
        observation_body,
    )
    verification_body = (json.dumps(verification, sort_keys=True) + "\n").encode()
    forecast_path = tmp_path / "forecast.json"
    outcome_path = tmp_path / "outcomes.json"
    observation_path = tmp_path / "observation-batch.json"
    verification_path = tmp_path / "verification.json"
    audit_path = tmp_path / "evidence-audit.json"
    forecast_path.write_bytes(forecast_body)
    outcome_path.write_bytes(outcome_body)
    observation_path.write_bytes(observation_body)
    verification_path.write_bytes(verification_body)
    audit = compile_prospective_evidence_audit(
        forecast_receipt_path=forecast_path,
        outcome_path=outcome_path,
        observation_batch_path=observation_path,
        verification_path=verification_path,
    )
    audit_path.write_text(
        json.dumps(audit, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    loaded = load_and_recompute_prospective_evidence_audit(audit_path)
    ledger = compile_prospective_evidence_ledger(
        [audit_path],
        forecast_receipt_paths=[forecast_path],
    )

    assert loaded["verification"] == verification
    assert audit["checks"]["verification_report_recomputed_exactly"] is True
    assert ledger["evidence_coverage"]["issue_count"] == 1
    assert ledger["evidence_coverage"]["issued_forecast_count"] == 1
    assert ledger["evidence_coverage"]["unscored_matured_issue_count"] == 0
    assert (
        ledger["evidence_gates"][
            "all_verification_reports_recomputed_from_exact_sources"
        ]
        is True
    )


def test_evidence_audit_rejects_source_changed_after_audit(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        "scripts.verify_geospatial_kernel_action_innovation_uncertainty_shadow._now",
        lambda: VERIFIED_AT,
    )
    monkeypatch.setattr(
        "scripts.audit_geospatial_kernel_action_innovation_prospective_evidence._now",
        lambda: AUDITED_AT,
    )
    forecast_body = _receipt_body()
    outcome_body = _outcome_body(forecast_body)
    observation_body = _observation_batch_body(forecast_body)
    verification = compile_prospective_verification(
        forecast_body,
        outcome_body,
        observation_body,
    )
    forecast_path = tmp_path / "forecast.json"
    outcome_path = tmp_path / "outcomes.json"
    observation_path = tmp_path / "observation-batch.json"
    verification_path = tmp_path / "verification.json"
    audit_path = tmp_path / "evidence-audit.json"
    forecast_path.write_bytes(forecast_body)
    outcome_path.write_bytes(outcome_body)
    observation_path.write_bytes(observation_body)
    verification_path.write_text(json.dumps(verification), encoding="utf-8")
    audit = compile_prospective_evidence_audit(
        forecast_receipt_path=forecast_path,
        outcome_path=outcome_path,
        observation_batch_path=observation_path,
        verification_path=verification_path,
    )
    audit_path.write_text(json.dumps(audit), encoding="utf-8")
    observation_path.write_bytes(observation_body + b" ")

    with pytest.raises(ValueError, match="evidence_audit_artifact_mismatch"):
        load_and_recompute_prospective_evidence_audit(audit_path)


def test_issue_finalizer_writes_complete_recomputable_chain(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        "scripts.audit_geospatial_kernel_action_innovation_prospective_evidence._now",
        lambda: AUDITED_AT,
    )
    forecast_body = _receipt_body()
    forecast_path = tmp_path / "forecast.json"
    observation_path = tmp_path / "observation-batch.json"
    output_directory = tmp_path / "finalized"
    forecast_path.write_bytes(forecast_body)
    observation_path.write_bytes(_observation_batch_body(forecast_body))

    outputs = finalize_prospective_issue(
        forecast_receipt_path=forecast_path,
        observation_batch_path=observation_path,
        output_directory=output_directory,
        finalized_at=VERIFIED_AT,
    )
    loaded = load_and_recompute_prospective_evidence_audit(
        outputs["evidence_audit"]
    )
    ledger = compile_prospective_evidence_ledger(
        [outputs["evidence_audit"]],
        forecast_receipt_paths=[forecast_path],
    )

    assert set(path.name for path in output_directory.iterdir()) == {
        OUTCOME_FILENAME,
        VERIFICATION_FILENAME,
        EVIDENCE_AUDIT_FILENAME,
    }
    assert loaded["verification"]["generated_at"] == VERIFIED_AT.isoformat()
    assert loaded["audit"]["generated_at"] == VERIFIED_AT.isoformat()
    assert ledger["issuance_inventory"][0]["reconciliation_status"] == (
        "scored_and_source_recomputed"
    )


def test_issue_finalizer_failure_leaves_no_output_directory(tmp_path) -> None:
    forecast_body = _receipt_body()
    forecast_path = tmp_path / "forecast.json"
    observation_path = tmp_path / "observation-batch.json"
    output_directory = tmp_path / "finalized"
    forecast_path.write_bytes(forecast_body)
    batch = _observation_batch(forecast_body)
    batch["values_imputed"] = True
    observation_path.write_text(json.dumps(batch), encoding="utf-8")

    with pytest.raises(ValueError, match="observation_batch_claims_invalid"):
        finalize_prospective_issue(
            forecast_receipt_path=forecast_path,
            observation_batch_path=observation_path,
            output_directory=output_directory,
            finalized_at=VERIFIED_AT,
        )

    assert not output_directory.exists()


def test_issue_finalizer_cli_refuses_existing_output_directory(
    tmp_path,
    monkeypatch,
) -> None:
    forecast_body = _receipt_body()
    forecast_path = tmp_path / "forecast.json"
    observation_path = tmp_path / "observation-batch.json"
    output_directory = tmp_path / "finalized"
    forecast_path.write_bytes(forecast_body)
    observation_path.write_bytes(_observation_batch_body(forecast_body))
    monkeypatch.setattr(
        "scripts.finalize_geospatial_kernel_action_innovation_prospective_issue._now",
        lambda: VERIFIED_AT,
    )
    monkeypatch.setattr(
        "sys.argv",
        [
            "finalize_geospatial_kernel_action_innovation_prospective_issue.py",
            "--forecast-receipt",
            str(forecast_path),
            "--observation-batch",
            str(observation_path),
            "--output-directory",
            str(output_directory),
        ],
    )

    assert finalize_main() == 0
    with pytest.raises(ValueError, match="finalizer_refuses_existing_directory"):
        finalize_main()
