"""Execution admission, oracle isolation, and single-use guards for RegimeWorld-IEC."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from enum import StrEnum
import hashlib
import json
import os
from pathlib import Path
from typing import Any, Iterable, Mapping

from data_agent.uwm.gwm_geospatial_kernel_readiness import (
    validate_k0_certificate_file,
)
from data_agent.uwm.regimeworld_iec_generator import ControlledScenarioSpec
from data_agent.uwm.regimeworld_iec_protocol import PRIMARY_SEEDS


class ExperimentScope(StrEnum):
    FIXTURE = "fixture"
    PRIMARY = "primary"
    UNTOUCHED = "untouched"


class AdmissionError(RuntimeError):
    """Raised when an experiment attempts to cross a frozen admission boundary."""


class SingleUseError(RuntimeError):
    """Raised when an untouched evaluation is missing a freeze or was already used."""


REQUIRED_HUMAN_APPROVALS = (
    "gwm_geospatial_kernel_readiness_approved",
    "uwm_shared_kernel_binding_approved",
    "contracted_contribution_approved",
    "g0_g6_spec_approved",
    "two_level_support_interpretation_approved",
    "generator_and_protocol_approved",
    "t3a_execution_contract_approved",
    "frozen_v4_denylist_approved",
    "nyc_2012_seal_acknowledged",
    "paper_experimenter_admitted",
)

HUMAN_ADMISSION_SCHEMA = "uwm.regimeworld_iec_t4_human_admission.v1"
MACHINE_PREADMISSION_SCHEMA = "uwm.regimeworld_iec_t4_machine_preadmission.v1"
NOVELTY_COMPLETION_SCHEMA = "uwm.regimeworld_iec_t0_novelty_completion.v1"
GWM_DEPENDENCY_STATUS_SCHEMA = "uwm.gwm_geospatial_kernel_dependency_status.v1"
GWM_DEPENDENCY_STATUS_RELATIVE_PATH = (
    "docs/research/UWM_GWM_KERNEL_DEPENDENCY_STATUS_2026-07-20.json"
)
REQUIRED_NOVELTY_COVERAGE = (
    "google_scholar",
    "acm_digital_library",
    "ieee_xplore",
    "semantic_scholar_unthrottled",
    "backward_forward_citation_chaining",
)
MACHINE_PREADMISSION_RELATIVE_PATH = (
    "plans/regimeworld-intervention-evidence-uwm/"
    "T4_MACHINE_PREADMISSION_RECEIPT.json"
)
REQUIRED_T4_REVIEWED_ARTIFACTS = (
    "plans/regimeworld-intervention-evidence-uwm/paper_plan.md",
    "plans/regimeworld-intervention-evidence-uwm/BENCHMARK_PROTOCOL.json",
    "plans/regimeworld-intervention-evidence-uwm/T4_HUMAN_ADMISSION_REVIEW.md",
    "data_agent/uwm/intervention_evidence_certificate_spec.yaml",
    "docs/research/uwm_regimeworld_iec_generator_validation_2026-07-19.json",
    "docs/research/uwm_regimeworld_v4_primitive_support_reaudit_2026-07-19.json",
    "docs/research/UWM_INTERVENTION_EVIDENCE_NOVELTY_AUDIT_2026-07-19.md",
    "docs/research/UWM_INTERVENTION_EVIDENCE_CITATION_CHAIN_2026-07-20.md",
    "docs/research/UWM_INTERVENTION_EVIDENCE_EXACT_QUERY_LEDGER_2026-07-20.json",
    "docs/research/GWM_GEOSPATIAL_KERNEL_K0_READINESS_CONTRACT_2026-07-20.json",
    "data/benchmarks/gwm_geospatial_kernel_k0_2026-07-20/readiness_report.json",
    GWM_DEPENDENCY_STATUS_RELATIVE_PATH,
    "data_agent/uwm/regimeworld_iec_execution_guard.py",
    "data_agent/uwm/regimeworld_iec_benchmark.py",
    "data_agent/uwm/regimeworld_iec_runner.py",
    "data_agent/uwm/regimeworld_iec_assessment.py",
    "scripts/smoke_regimeworld_iec_fixture.py",
)

FROZEN_V4_EXECUTABLES = (
    "paper-output/regimeworld-nyc-v4-compositional-uwm/exp/compositional_uwm.py",
    "paper-output/regimeworld-nyc-v4-compositional-uwm/exp/evaluate_heldout_2015_once.py",
    "scripts/build_uwm_regimeworld_v4_heldout_state.py",
)

FORMAL_RESULT_RELATIVE_PATHS = (
    "paper-output/regimeworld-intervention-evidence-uwm/"
    "results/T5_PRIMARY_EXECUTION_RECEIPT.json",
    "paper-output/regimeworld-intervention-evidence-uwm/models",
    "paper-output/regimeworld-intervention-evidence-uwm/results/certificate_primary.csv",
    "paper-output/regimeworld-intervention-evidence-uwm/results/divergence_metrics.parquet",
    "paper-output/regimeworld-intervention-evidence-uwm/results/primary_run_manifest.json",
    "paper-output/regimeworld-intervention-evidence-uwm/results/untouched_evaluation_receipt.json",
    "paper-output/regimeworld-intervention-evidence-uwm/results/untouched_metrics.parquet",
)
T5_PRIMARY_EXECUTION_RECEIPT_RELATIVE_PATH = FORMAL_RESULT_RELATIVE_PATHS[0]


def sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def audit_formal_result_absence(repo_root: Path) -> dict[str, Any]:
    present = [
        relative
        for relative in FORMAL_RESULT_RELATIVE_PATHS
        if (repo_root / relative).exists()
    ]
    return {
        "checked_paths": list(FORMAL_RESULT_RELATIVE_PATHS),
        "present_paths": present,
        "primary_or_untouched_results_absent": not present,
    }


def _parse_aware_datetime(value: str, *, field: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise AdmissionError(f"human admission {field} is required")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise AdmissionError(f"human admission {field} is not ISO-8601") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise AdmissionError(f"human admission {field} must include a timezone")
    return parsed


def _resolve_receipt_artifact(root: Path, raw_path: str) -> Path:
    artifact = (root / raw_path).resolve()
    try:
        artifact.relative_to(root)
    except ValueError as exc:
        raise AdmissionError(f"human admission artifact escapes root: {raw_path}") from exc
    return artifact


def _validate_upstream_architecture(root: Path) -> dict[str, Any]:
    path = _resolve_receipt_artifact(root, GWM_DEPENDENCY_STATUS_RELATIVE_PATH)
    if not path.is_file():
        raise AdmissionError("GWM/UWM upstream dependency status does not exist")
    try:
        status = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AdmissionError("GWM/UWM upstream dependency status is invalid") from exc
    if status.get("schema") != GWM_DEPENDENCY_STATUS_SCHEMA:
        raise AdmissionError("GWM/UWM upstream dependency schema mismatch")
    observed = status.get("observed_state")
    required_observed = (
        "gwm_geospatial_kernel_ready",
        "gwm_kernel_persistence_gate_passed",
        "uwm_shared_kernel_binding_implemented",
        "uwm_shared_kernel_conformance_passed",
        "regimeworld_uses_shared_gwm_geospatial_kernel",
    )
    blocked = [
        field
        for field in required_observed
        if not isinstance(observed, dict) or observed.get(field) is not True
    ]
    decision = status.get("decision")
    if (
        not isinstance(decision, dict)
        or decision.get("uwm_scientific_experiment_ready") is not True
    ):
        blocked.append("uwm_scientific_experiment_ready")
    future = status.get("required_future_artifacts")
    artifact_roles = (
        "gwm_geospatial_kernel_readiness_certificate",
        "uwm_shared_kernel_binding_conformance_receipt",
    )
    invalid_artifacts: list[str] = []
    for role in artifact_roles:
        record = future.get(role) if isinstance(future, dict) else None
        if not isinstance(record, dict):
            invalid_artifacts.append(role)
            continue
        raw_path = record.get("path")
        expected_hash = record.get("sha256")
        if (
            not isinstance(raw_path, str)
            or not raw_path.strip()
            or not isinstance(expected_hash, str)
            or len(expected_hash) != 64
        ):
            invalid_artifacts.append(role)
            continue
        artifact = _resolve_receipt_artifact(root, raw_path)
        if not artifact.is_file() or sha256_path(artifact) != expected_hash:
            invalid_artifacts.append(role)
            continue
        if role == "gwm_geospatial_kernel_readiness_certificate":
            if not validate_k0_certificate_file(root=root, path=artifact):
                invalid_artifacts.append(role)
    if blocked or invalid_artifacts:
        raise AdmissionError(
            "GWM Geospatial Kernel or UWM binding is not ready; "
            f"blocked={blocked}, invalid_artifacts={invalid_artifacts}"
        )
    return status


def _load_machine_preadmission(root: Path) -> tuple[dict[str, Any], Path]:
    path = _resolve_receipt_artifact(root, MACHINE_PREADMISSION_RELATIVE_PATH)
    if not path.is_file():
        raise AdmissionError("current T4 machine preadmission receipt does not exist")
    try:
        receipt = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AdmissionError("T4 machine preadmission receipt is not valid JSON") from exc
    if receipt.get("schema") != MACHINE_PREADMISSION_SCHEMA:
        raise AdmissionError("T4 machine preadmission schema mismatch")
    _validate_upstream_architecture(root)
    expected_state = {
        "iec_component_pass": True,
        "architecture_pass": True,
        "technical_pass": True,
        "novelty_status": "caution",
        "human_review_pending": True,
        "human_review_status": "pending",
        "paper_experimenter_admitted": False,
    }
    wrong_state = [
        field for field, expected in expected_state.items() if receipt.get(field) != expected
    ]
    if wrong_state:
        raise AdmissionError(
            f"T4 machine preadmission is not in review-ready state: {wrong_state}"
        )
    component_gates = receipt.get("iec_component_gates")
    architecture_gates = receipt.get("architecture_gates")
    if (
        not isinstance(component_gates, dict)
        or not component_gates
        or not all(value is True for value in component_gates.values())
        or not isinstance(architecture_gates, dict)
        or not architecture_gates
        or not all(value is True for value in architecture_gates.values())
    ):
        raise AdmissionError("T4 machine preadmission technical gates are incomplete")
    hashes = receipt.get("artifact_hashes")
    if not isinstance(hashes, dict) or set(hashes) != set(REQUIRED_T4_REVIEWED_ARTIFACTS):
        raise AdmissionError("T4 machine preadmission artifact set is incomplete")
    mismatches = [
        raw_path
        for raw_path, expected_hash in hashes.items()
        if not isinstance(expected_hash, str)
        or len(expected_hash) != 64
        or not (artifact := _resolve_receipt_artifact(root, raw_path)).is_file()
        or sha256_path(artifact) != expected_hash
    ]
    if mismatches:
        raise AdmissionError(
            f"T4 machine preadmission artifact hash mismatch: {mismatches}"
        )
    return receipt, path


def _validate_novelty_completion(
    path: Path,
    *,
    reviewer_name: str,
    machine_created_at: datetime,
    admission_reviewed_at: datetime,
) -> None:
    try:
        completion = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AdmissionError("novelty completion artifact is not valid JSON") from exc
    if completion.get("schema") != NOVELTY_COMPLETION_SCHEMA:
        raise AdmissionError("novelty completion artifact schema mismatch")
    if completion.get("reviewer_name") != reviewer_name:
        raise AdmissionError("novelty completion reviewer does not match admission")
    reviewed_at = _parse_aware_datetime(
        completion.get("reviewed_at", ""), field="novelty reviewed_at"
    )
    if not machine_created_at < reviewed_at <= admission_reviewed_at:
        raise AdmissionError(
            "novelty completion must postdate machine preadmission and not "
            "postdate human admission"
        )
    required_decisions = {
        "novelty_status": "pass",
        "direct_equivalent_found": False,
        "contracted_contribution_survives_review": True,
        "first_of_kind_claim_permitted": False,
        "coverage_limitations_acknowledged": True,
    }
    wrong_decisions = [
        field
        for field, expected in required_decisions.items()
        if completion.get(field) != expected
    ]
    if wrong_decisions:
        raise AdmissionError(
            f"novelty completion decisions are not admissible: {wrong_decisions}"
        )
    if (
        not isinstance(completion.get("decision_reason"), str)
        or not completion["decision_reason"].strip()
    ):
        raise AdmissionError("novelty completion decision_reason is required")
    coverage = completion.get("coverage")
    if not isinstance(coverage, dict):
        raise AdmissionError("novelty completion coverage must be an object")
    incomplete = []
    for source in REQUIRED_NOVELTY_COVERAGE:
        record = coverage.get(source)
        if (
            not isinstance(record, dict)
            or record.get("status") != "completed"
            or not isinstance(record.get("evidence"), str)
            or not record["evidence"].strip()
        ):
            incomplete.append(source)
    if incomplete:
        raise AdmissionError(f"novelty completion coverage is incomplete: {incomplete}")


def validate_human_admission_receipt(
    path: Path,
    *,
    artifact_root: Path,
) -> dict[str, Any]:
    if not path.is_file():
        raise AdmissionError(f"human admission receipt does not exist: {path}")
    try:
        receipt = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AdmissionError("human admission receipt is not valid JSON") from exc
    if receipt.get("schema") != HUMAN_ADMISSION_SCHEMA:
        raise AdmissionError("human admission receipt schema mismatch")
    missing_text = [
        field
        for field in (
            "reviewer_name",
            "reviewed_at",
            "novelty_completion_artifact",
            "decision_reason",
        )
        if not isinstance(receipt.get(field), str) or not receipt[field].strip()
    ]
    if missing_text:
        raise AdmissionError(f"human admission receipt lacks fields: {missing_text}")
    failed = [field for field in REQUIRED_HUMAN_APPROVALS if receipt.get(field) is not True]
    if failed:
        raise AdmissionError(f"human admission approvals are not all true: {failed}")
    if receipt.get("novelty_status") != "pass":
        raise AdmissionError("human admission requires novelty_status=pass")
    root = artifact_root.resolve()
    machine_receipt, machine_path = _load_machine_preadmission(root)
    reviewed_at = _parse_aware_datetime(receipt["reviewed_at"], field="reviewed_at")
    machine_created_at = _parse_aware_datetime(
        machine_receipt.get("created_at", ""), field="machine created_at"
    )
    if reviewed_at <= machine_created_at:
        raise AdmissionError("human admission must postdate machine preadmission")
    hashes = receipt.get("artifact_hashes")
    if not isinstance(hashes, dict) or not hashes:
        raise AdmissionError("human admission requires non-empty artifact_hashes")
    novelty_path = receipt["novelty_completion_artifact"]
    if novelty_path in {
        *REQUIRED_T4_REVIEWED_ARTIFACTS,
        MACHINE_PREADMISSION_RELATIVE_PATH,
    }:
        raise AdmissionError("novelty completion artifact must be a separate artifact")
    required_hash_paths = {
        *REQUIRED_T4_REVIEWED_ARTIFACTS,
        MACHINE_PREADMISSION_RELATIVE_PATH,
        novelty_path,
    }
    missing_hashes = sorted(required_hash_paths - set(hashes))
    if missing_hashes:
        raise AdmissionError(
            f"human admission does not cover required artifacts: {missing_hashes}"
        )
    novelty_artifact = _resolve_receipt_artifact(root, novelty_path)
    _validate_novelty_completion(
        novelty_artifact,
        reviewer_name=receipt["reviewer_name"],
        machine_created_at=machine_created_at,
        admission_reviewed_at=reviewed_at,
    )
    mismatches: list[str] = []
    for raw_path, expected_hash in hashes.items():
        if (
            not isinstance(raw_path, str)
            or not isinstance(expected_hash, str)
            or len(expected_hash) != 64
        ):
            raise AdmissionError("human admission artifact hashes must map strings to strings")
        artifact = _resolve_receipt_artifact(root, raw_path)
        if not artifact.is_file() or sha256_path(artifact) != expected_hash:
            mismatches.append(raw_path)
    if mismatches:
        raise AdmissionError(f"human admission artifact hash mismatch: {mismatches}")
    machine_relative = machine_path.relative_to(root).as_posix()
    if hashes[machine_relative] != sha256_path(machine_path):
        raise AdmissionError("human admission does not sign current machine preadmission")
    machine_hashes = machine_receipt["artifact_hashes"]
    inconsistent = [
        raw_path
        for raw_path, expected_hash in machine_hashes.items()
        if hashes.get(raw_path) != expected_hash
    ]
    if inconsistent:
        raise AdmissionError(
            f"human and machine reviewed-artifact hashes differ: {inconsistent}"
        )
    return receipt


def _scenario_manifest_sha256(specs: Iterable[ControlledScenarioSpec]) -> str:
    canonical = json.dumps(
        [asdict(spec) for spec in specs],
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _authorize_primary_start(
    *,
    artifact_root: Path,
    human_receipt_sha256: str,
    specs: tuple[ControlledScenarioSpec, ...],
) -> None:
    root = artifact_root.resolve()
    path = _resolve_receipt_artifact(
        root, T5_PRIMARY_EXECUTION_RECEIPT_RELATIVE_PATH
    )
    scenario_manifest_sha256 = _scenario_manifest_sha256(specs)
    expected = {
        "schema": "uwm.regimeworld_iec_t5_primary_execution_receipt.v1",
        "status": "reserved",
        "human_receipt_sha256": human_receipt_sha256,
        "scenario_manifest_sha256": scenario_manifest_sha256,
        "rerun_permitted": False,
        "resume_same_frozen_run_permitted": True,
    }
    if path.exists():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise AdmissionError("T5 primary execution receipt is invalid") from exc
        if existing != expected:
            raise AdmissionError("T5 primary execution receipt does not match this run")
        return

    present_before_start = [
        relative
        for relative in FORMAL_RESULT_RELATIVE_PATHS
        if relative != T5_PRIMARY_EXECUTION_RECEIPT_RELATIVE_PATH
        and (root / relative).exists()
    ]
    if present_before_start:
        raise AdmissionError(
            "formal result paths exist before the first T5 authorization: "
            f"{present_before_start}"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    try:
        descriptor = os.open(path, flags, 0o600)
    except FileExistsError as exc:
        raise AdmissionError("T5 primary execution was concurrently reserved") from exc
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(json.dumps(expected, indent=2) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def assert_fixture_only(specs: Iterable[ControlledScenarioSpec]) -> None:
    specs = tuple(specs)
    if not specs:
        raise AdmissionError("fixture execution requires at least one scenario")
    violations: list[str] = []
    for spec in specs:
        if not spec.name.startswith("fixture_"):
            violations.append(f"{spec.name}: fixture_ prefix required")
        if spec.name.startswith(("primary_", "untouched_")):
            violations.append(f"{spec.name}: frozen protocol scenario")
        if spec.seed in PRIMARY_SEEDS:
            violations.append(f"{spec.name}: frozen protocol seed")
        if spec.n_nodes > 16 or spec.n_steps > 64:
            violations.append(f"{spec.name}: fixture dimensions exceeded")
    if violations:
        raise AdmissionError("fixture boundary violation: " + "; ".join(violations))


def authorize_execution(
    scope: ExperimentScope | str,
    specs: Iterable[ControlledScenarioSpec],
    *,
    human_admission_receipt: Path | None = None,
    artifact_root: Path | None = None,
    untouched_freeze_manifest: Path | None = None,
    frozen_artifact_paths: Mapping[str, Path] | None = None,
) -> ExecutionAuthorization:
    normalized_scope = ExperimentScope(scope)
    specs = tuple(specs)
    if normalized_scope is ExperimentScope.FIXTURE:
        assert_fixture_only(specs)
        return ExecutionAuthorization(
            scope=normalized_scope,
            scientific_result=False,
            scenario_names=tuple(spec.name for spec in specs),
        )
    dependency_root = (
        artifact_root.resolve()
        if artifact_root is not None
        else Path(__file__).resolve().parents[2]
    )
    _validate_upstream_architecture(dependency_root)
    if human_admission_receipt is None:
        raise AdmissionError(f"{normalized_scope.value} execution requires human T4 admission")
    if artifact_root is None:
        raise AdmissionError("formal execution requires an artifact root for hash validation")
    receipt = validate_human_admission_receipt(
        human_admission_receipt,
        artifact_root=artifact_root,
    )
    from data_agent.uwm.regimeworld_iec_protocol import (
        primary_scenario_specs,
        untouched_family_specs,
    )

    official_specs = (
        primary_scenario_specs()
        if normalized_scope is ExperimentScope.PRIMARY
        else untouched_family_specs()
    )
    if specs != official_specs:
        expected_by_name = {spec.name: spec for spec in official_specs}
        wrong = [
            spec.name
            for spec in specs
            if expected_by_name.get(spec.name) != spec
        ]
        detail = wrong[:3] or ["missing_or_reordered_scenarios"]
        raise AdmissionError(
            f"{normalized_scope.value} execution requires the complete frozen "
            f"scenario manifest: {detail}"
        )
    human_receipt_sha256 = sha256_path(human_admission_receipt)
    if normalized_scope is ExperimentScope.PRIMARY:
        _authorize_primary_start(
            artifact_root=artifact_root,
            human_receipt_sha256=human_receipt_sha256,
            specs=specs,
        )
    if normalized_scope is ExperimentScope.UNTOUCHED:
        if untouched_freeze_manifest is None or frozen_artifact_paths is None:
            raise SingleUseError("untouched execution requires the T6 freeze manifest")
        manifest = json.loads(untouched_freeze_manifest.read_text(encoding="utf-8"))
        validate_freeze_manifest(manifest, frozen_artifact_paths)
    return ExecutionAuthorization(
        scope=normalized_scope,
        scientific_result=True,
        scenario_names=tuple(spec.name for spec in specs),
        human_receipt_sha256=human_receipt_sha256,
        reviewer_name=receipt["reviewer_name"],
    )


def validate_freeze_manifest(
    freeze_manifest: Mapping[str, Any],
    artifact_paths: Mapping[str, Path],
) -> None:
    if freeze_manifest.get("status") != "frozen_for_single_use_untouched_evaluation":
        raise SingleUseError("untouched freeze manifest is not active")
    expected = freeze_manifest.get("artifact_hashes")
    if not isinstance(expected, dict) or set(expected) != set(artifact_paths):
        raise SingleUseError("untouched freeze artifact set does not match")
    mismatches = [
        name
        for name, path in artifact_paths.items()
        if not path.is_file() or sha256_path(path) != expected[name]
    ]
    if mismatches:
        raise SingleUseError(f"untouched freeze hash mismatch: {mismatches}")


def build_untouched_freeze_manifest(
    artifact_paths: Mapping[str, Path],
    *,
    primary_run_manifest_sha256: str,
) -> dict[str, Any]:
    required_roles = {
        "selected_models",
        "frozen_scalers",
        "certificate_thresholds",
        "untouched_evaluator",
        "untouched_scenario_manifest",
    }
    if set(artifact_paths) != required_roles:
        missing = sorted(required_roles - set(artifact_paths))
        extra = sorted(set(artifact_paths) - required_roles)
        raise SingleUseError(f"T6 freeze role mismatch; missing={missing}, extra={extra}")
    missing_paths = [name for name, path in artifact_paths.items() if not path.is_file()]
    if missing_paths:
        raise SingleUseError(f"T6 freeze artifacts do not exist: {missing_paths}")
    if len(primary_run_manifest_sha256) != 64:
        raise SingleUseError("T6 freeze requires a SHA-256 primary run manifest hash")
    return {
        "schema": "uwm.regimeworld_iec_t6_freeze.v1",
        "status": "frozen_for_single_use_untouched_evaluation",
        "primary_run_manifest_sha256": primary_run_manifest_sha256,
        "artifact_hashes": {
            name: sha256_path(path) for name, path in sorted(artifact_paths.items())
        },
        "single_use_receipt_required": True,
        "rerun_permitted": False,
    }


@dataclass(frozen=True)
class SingleUseReservation:
    path: Path
    receipt: dict[str, Any]

    def finalize(self, *, status: str, result_hashes: Mapping[str, str]) -> None:
        current = json.loads(self.path.read_text(encoding="utf-8"))
        if current != self.receipt or current.get("status") != "reserved":
            raise SingleUseError("single-use reservation changed before finalization")
        finalized = {
            **current,
            "status": status,
            "result_hashes": dict(sorted(result_hashes.items())),
        }
        self.path.write_text(json.dumps(finalized, indent=2) + "\n", encoding="utf-8")


@dataclass(frozen=True)
class ExecutionAuthorization:
    scope: ExperimentScope
    scientific_result: bool
    scenario_names: tuple[str, ...]
    human_receipt_sha256: str | None = None
    reviewer_name: str | None = None


@dataclass(frozen=True)
class ExternalEvaluationAuthorization:
    scope: ExperimentScope
    scenario_name: str
    scientific_result: bool
    frozen_model_hashes: dict[str, str]
    frozen_scaler_hashes: dict[str, str]
    reservation: SingleUseReservation | None


def authorize_external_evaluation(
    execution_authorization: ExecutionAuthorization,
    *,
    scenario_name: str,
    frozen_model_hashes: Mapping[str, str],
    frozen_scaler_hashes: Mapping[str, str],
    receipt_path: Path | None = None,
) -> ExternalEvaluationAuthorization:
    if scenario_name not in execution_authorization.scenario_names:
        raise SingleUseError("external scenario is outside the execution authorization")
    if not frozen_model_hashes or not frozen_scaler_hashes:
        raise SingleUseError("external evaluation requires frozen model and scaler hashes")
    if set(frozen_model_hashes) != set(frozen_scaler_hashes):
        raise SingleUseError("model and scaler variant sets do not match")
    invalid = [
        name
        for name, value in {**frozen_model_hashes, **frozen_scaler_hashes}.items()
        if not isinstance(value, str) or len(value) != 64
    ]
    if invalid:
        raise SingleUseError(f"invalid model or scaler SHA-256 values: {invalid}")
    canonical = json.dumps(
        {
            "scenario_name": scenario_name,
            "model_hashes": dict(sorted(frozen_model_hashes.items())),
            "scaler_hashes": dict(sorted(frozen_scaler_hashes.items())),
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    freeze_hash = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    reservation = None
    if execution_authorization.scientific_result:
        if receipt_path is None:
            raise SingleUseError("formal external evaluation requires a receipt path")
        reservation = reserve_single_use_receipt(
            receipt_path,
            freeze_manifest_sha256=freeze_hash,
            evaluator_sha256=hashlib.sha256(b"regimeworld_iec_external_v1").hexdigest(),
        )
    elif receipt_path is not None:
        raise SingleUseError("fixture external evaluation must not write a formal receipt")
    return ExternalEvaluationAuthorization(
        scope=execution_authorization.scope,
        scenario_name=scenario_name,
        scientific_result=execution_authorization.scientific_result,
        frozen_model_hashes=dict(sorted(frozen_model_hashes.items())),
        frozen_scaler_hashes=dict(sorted(frozen_scaler_hashes.items())),
        reservation=reservation,
    )


def reserve_single_use_receipt(
    path: Path,
    *,
    freeze_manifest_sha256: str,
    evaluator_sha256: str,
) -> SingleUseReservation:
    path.parent.mkdir(parents=True, exist_ok=True)
    receipt = {
        "schema": "uwm.regimeworld_iec_single_use_receipt.v1",
        "status": "reserved",
        "freeze_manifest_sha256": freeze_manifest_sha256,
        "evaluator_sha256": evaluator_sha256,
        "rerun_permitted": False,
    }
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    try:
        descriptor = os.open(path, flags, 0o600)
    except FileExistsError as exc:
        raise SingleUseError(f"single-use receipt already exists: {path}") from exc
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        handle.write(json.dumps(receipt, indent=2) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    return SingleUseReservation(path=path, receipt=receipt)


def reject_frozen_v4_execution(path: Path, *, repo_root: Path) -> None:
    try:
        relative = path.resolve().relative_to(repo_root.resolve()).as_posix()
    except ValueError:
        return
    if relative in FROZEN_V4_EXECUTABLES:
        raise AdmissionError(f"frozen v4 executable may not be invoked: {relative}")
