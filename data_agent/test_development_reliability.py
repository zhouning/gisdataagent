from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from data_agent.platform_runtime.deployment_profile import load_deployment_profile
from data_agent.platform_runtime.development_reliability import (
    CompatibilityStatus,
    DevelopmentReliabilityError,
    ReliabilityEvidenceKind,
    build_capacity_observation,
    build_compatibility_case,
    build_compatibility_matrix,
    build_development_reliability_baseline,
    build_evidence_reference,
    build_latency_observation,
    build_slo_thresholds,
    evaluate_development_slo,
    verify_development_reliability_baseline,
)

PROFILE_PATH = "config/deployment_profiles/main-compose-dev.json"
NOW = datetime(2026, 8, 19, 13, 0, tzinfo=UTC)


def _parts():
    profile = load_deployment_profile(PROFILE_PATH)
    evidence = tuple(
        build_evidence_reference(
            kind=kind,
            evidence_sha256=f"{position:x}" * 64,
            profile_id=profile.profile_id,
            compose_config_sha256=profile.compose.config_sha256,
            observed_at=NOW,
        )
        for position, kind in enumerate(
            (
                ReliabilityEvidenceKind.BACKUP,
                ReliabilityEvidenceKind.PITR,
                ReliabilityEvidenceKind.RECOVERY_SLI,
            ),
        )
    )
    latency = build_latency_observation(
        operation="semantic_query_execute",
        samples_ms=(10, 12, 15, 17, 19, 22, 25, 28, 31, 40),
        observed_at=NOW,
    )
    capacity = build_capacity_observation(
        operation="semantic_query_execute",
        concurrency=4,
        duration_seconds=10,
        completed_count=95,
        failed_count=5,
        max_queue_depth=3,
        observed_at=NOW,
    )
    thresholds = build_slo_thresholds(
        operation="semantic_query_execute",
        max_p95_ms=40,
        max_p99_ms=40,
        min_throughput_per_second=9,
        max_error_rate=0.1,
    )
    cases = build_compatibility_matrix(
        (
            build_compatibility_case(
                cpu="arm64",
                os="linux",
                database="postgresql16",
                middleware="minio",
                model_service="openai-compatible",
                status=CompatibilityStatus.PASSED,
                evidence_sha256="b" * 64,
            ),
            build_compatibility_case(
                cpu="kunpeng920-arm64",
                os="kylin-v10",
                database="opengauss-6",
                middleware="tongweb-8",
                model_service="qwen3-compatible",
                status=CompatibilityStatus.UNTESTED,
            ),
        )
    )
    return profile, evidence, latency, capacity, thresholds, cases


def test_percentiles_capacity_and_slo_are_reproducible():
    _, _, latency, capacity, thresholds, _ = _parts()

    assert latency.sample_count == 10
    assert latency.p50_ms == 19
    assert latency.p95_ms == 40
    assert latency.p99_ms == 40
    assert capacity.throughput_per_second == 9.5
    assert capacity.error_rate == 0.05
    assert evaluate_development_slo(
        latency=latency,
        capacity=capacity,
        thresholds=thresholds,
    ) == {
        "p95_within_threshold": True,
        "p99_within_threshold": True,
        "throughput_within_threshold": True,
        "error_rate_within_threshold": True,
    }


def test_baseline_binds_backup_pitr_recovery_and_compatibility_without_promotion():
    profile, evidence, latency, capacity, thresholds, compatibility = _parts()
    baseline = build_development_reliability_baseline(
        baseline_id="main-compose-dev-reliability-v1",
        profile=profile,
        evidence=evidence,
        latency=(latency,),
        capacity=(capacity,),
        slo_thresholds=(thresholds,),
        compatibility=compatibility,
        observed_at=NOW,
    )

    verification = verify_development_reliability_baseline(
        baseline=baseline,
        profile=profile,
        evidence=evidence,
        latency=(latency,),
        capacity=(capacity,),
        slo_thresholds=(thresholds,),
        compatibility=compatibility,
    )

    assert verification["technical_pass"] is True
    assert verification["promotion_ready"] is False
    assert verification["compatibility_status"] == "incomplete"
    assert baseline.slo_status == "observed_not_approved"
    assert baseline.rpo_status == "not_defined"
    assert baseline.rto_status == "not_approved"


def test_drifted_latency_or_evidence_fails_reproduction():
    profile, evidence, latency, capacity, thresholds, compatibility = _parts()
    baseline = build_development_reliability_baseline(
        baseline_id="main-compose-dev-reliability-v1",
        profile=profile,
        evidence=evidence,
        latency=(latency,),
        capacity=(capacity,),
        slo_thresholds=(thresholds,),
        compatibility=compatibility,
        observed_at=NOW,
    )
    drifted_latency = build_latency_observation(
        operation="semantic_query_execute",
        samples_ms=(10, 12, 15, 17, 19, 22, 25, 28, 31, 41),
        observed_at=NOW,
    )
    verification = verify_development_reliability_baseline(
        baseline=baseline,
        profile=profile,
        evidence=evidence,
        latency=(drifted_latency,),
        capacity=(capacity,),
        slo_thresholds=(thresholds,),
        compatibility=compatibility,
    )
    assert verification["checks"]["latency_bindings"] is False
    assert verification["checks"]["baseline_reproducible"] is False


def test_baseline_requires_development_profile_and_all_evidence_kinds():
    profile, evidence, latency, capacity, thresholds, compatibility = _parts()
    with pytest.raises(DevelopmentReliabilityError, match="dev or test"):
        production_profile = profile.model_copy(update={"environment": "production"})
        build_development_reliability_baseline(
            baseline_id="main-compose-prod-reliability-v1",
            profile=production_profile,
            evidence=evidence,
            latency=(latency,),
            capacity=(capacity,),
            slo_thresholds=(thresholds,),
            compatibility=compatibility,
            observed_at=NOW,
        )

    with pytest.raises(ValidationError, match="Tuple should have at least 3 items"):
        build_development_reliability_baseline(
            baseline_id="main-compose-dev-reliability-v1",
            profile=profile,
            evidence=evidence[:2],
            latency=(latency,),
            capacity=(capacity,),
            slo_thresholds=(thresholds,),
            compatibility=compatibility,
            observed_at=NOW,
        )


def test_baseline_requires_exact_operation_and_profile_bindings():
    profile, evidence, latency, capacity, thresholds, compatibility = _parts()
    other_capacity = build_capacity_observation(
        operation="other_operation",
        concurrency=4,
        duration_seconds=10,
        completed_count=95,
        failed_count=5,
        max_queue_depth=3,
        observed_at=NOW,
    )
    with pytest.raises(ValidationError, match="must match exactly"):
        build_development_reliability_baseline(
            baseline_id="main-compose-dev-reliability-v1",
            profile=profile,
            evidence=evidence,
            latency=(latency,),
            capacity=(other_capacity,),
            slo_thresholds=(thresholds,),
            compatibility=compatibility,
            observed_at=NOW,
        )

    drifted_evidence = (
        build_evidence_reference(
            kind=ReliabilityEvidenceKind.BACKUP,
            evidence_sha256="0" * 64,
            profile_id="other-dev",
            compose_config_sha256=profile.compose.config_sha256,
            observed_at=NOW,
        ),
        *evidence[1:],
    )
    with pytest.raises(ValidationError, match="profile differs"):
        build_development_reliability_baseline(
            baseline_id="main-compose-dev-reliability-v1",
            profile=profile,
            evidence=drifted_evidence,
            latency=(latency,),
            capacity=(capacity,),
            slo_thresholds=(thresholds,),
            compatibility=compatibility,
            observed_at=NOW,
        )


def test_compatibility_cases_require_evidence_only_for_passed_and_no_duplicates():
    with pytest.raises(ValidationError, match="requires evidence"):
        build_compatibility_case(
            cpu="arm64",
            os="linux",
            database="postgresql16",
            middleware="minio",
            model_service="openai-compatible",
            status=CompatibilityStatus.PASSED,
        )

    case = build_compatibility_case(
        cpu="arm64",
        os="linux",
        database="postgresql16",
        middleware="minio",
        model_service="openai-compatible",
        status=CompatibilityStatus.UNTESTED,
    )
    with pytest.raises(ValidationError, match="unique"):
        build_compatibility_matrix((case, case))


def test_percentile_contract_rejects_too_few_samples_and_tampering():
    with pytest.raises(DevelopmentReliabilityError, match="at least five"):
        build_latency_observation(
            operation="semantic_query_execute",
            samples_ms=(1, 2, 3, 4),
            observed_at=NOW,
        )

    _, _, latency, _, _, _ = _parts()
    payload = latency.model_dump(mode="json")
    payload["p99_ms"] = 999
    with pytest.raises(ValidationError, match="percentile"):
        type(latency).model_validate(payload)


def test_capacity_and_slo_contracts_reject_empty_or_inverted_observations():
    with pytest.raises(ValidationError, match="at least one request"):
        build_capacity_observation(
            operation="semantic_query_execute",
            concurrency=1,
            duration_seconds=1,
            completed_count=0,
            failed_count=0,
            max_queue_depth=0,
            observed_at=NOW,
        )

    with pytest.raises(ValidationError, match="cannot be lower"):
        build_slo_thresholds(
            operation="semantic_query_execute",
            max_p95_ms=100,
            max_p99_ms=99,
            min_throughput_per_second=1,
            max_error_rate=0.1,
        )
