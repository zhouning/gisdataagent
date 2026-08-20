"""Governed run contract shared by traditional urban-flood solvers.

This contract separates numerical execution quality from model admission.  A
successful solver process is evidence that the runtime works; it is not, by
itself, evidence that an Abu Dhabi engineering model is calibrated or fit for
GWM training or operational use.
"""

from __future__ import annotations

import math
import re
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

TRADITIONAL_SOLVER_RUN_REQUEST_SCHEMA = (
    "gwm.abu_dhabi_flood.traditional_solver_run_request.v1"
)
TRADITIONAL_SOLVER_QUALITY_POLICY_SCHEMA = (
    "gwm.abu_dhabi_flood.traditional_solver_quality_policy.v1"
)
SUPPORTED_SOLVERS = frozenset({"anuga_2d", "epa_swmm", "lisflood_fp_2d"})
SUPPORTED_EVIDENCE_CLASSES = frozenset(
    {
        "synthetic_fixture",
        "public_proxy",
        "customer_unverified",
        "customer_authoritative",
    }
)
SUPPORTED_CALIBRATION_STATUSES = frozenset(
    {
        "not_calibrated",
        "calibration_candidate",
        "calibrated_not_independently_validated",
        "independently_validated",
    }
)
_IDENTIFIER_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}\Z")
_VERSION_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9.+_-]{0,95}\Z")


class TraditionalSolverQualityPolicyProtocol(Protocol):
    """Structural interface implemented by solver-specific quality policies."""

    def to_dict(self) -> dict[str, object]: ...


class TraditionalSolverExecutionError(RuntimeError):
    """Fail-closed traditional-solver execution or quality-gate failure."""

    def __init__(self, code: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.details = details or {}


@dataclass(frozen=True)
class TraditionalSolverRunRequest:
    """One immutable, diagnostic-only traditional-solver invocation."""

    run_id: str
    solver_id: str
    executable_path: Path
    model_input_path: Path
    expected_solver_version: str
    evidence_class: str = "synthetic_fixture"
    calibration_status: str = "not_calibrated"
    intended_use: str = "runtime_and_numerical_diagnostic"
    diagnostic_only: bool = True
    training_admitted: bool = False
    production_admitted: bool = False

    def __post_init__(self) -> None:
        if (
            not isinstance(self.run_id, str)
            or _IDENTIFIER_PATTERN.fullmatch(self.run_id) is None
        ):
            raise ValueError("traditional_solver_run_id_invalid")
        if self.solver_id not in SUPPORTED_SOLVERS:
            raise ValueError("traditional_solver_not_supported")
        if (
            not isinstance(self.expected_solver_version, str)
            or _VERSION_PATTERN.fullmatch(self.expected_solver_version) is None
        ):
            raise ValueError("traditional_solver_expected_version_invalid")
        if self.evidence_class not in SUPPORTED_EVIDENCE_CLASSES:
            raise ValueError("traditional_solver_evidence_class_invalid")
        if self.calibration_status not in SUPPORTED_CALIBRATION_STATUSES:
            raise ValueError("traditional_solver_calibration_status_invalid")
        if not isinstance(self.intended_use, str) or not self.intended_use.strip():
            raise ValueError("traditional_solver_intended_use_required")
        if (
            self.diagnostic_only is not True
            or self.training_admitted is not False
            or self.production_admitted is not False
        ):
            raise ValueError("traditional_solver_adapter_cannot_grant_admission")
        if (
            self.evidence_class in {"synthetic_fixture", "public_proxy"}
            and self.calibration_status != "not_calibrated"
        ):
            raise ValueError("proxy_or_synthetic_solver_input_cannot_be_calibrated")

    def claim_boundary(self) -> dict[str, object]:
        return {
            "diagnostic_only": True,
            "numerical_quality_is_not_engineering_validation": True,
            "traditional_model_admitted": False,
            "gwm_training_admitted": False,
            "production_admitted": False,
            "city_scale_prediction_claim_allowed": False,
            "separate_k0_k1_k2_review_required_for_any_admission": True,
        }


@dataclass(frozen=True)
class TraditionalSolverQualityPolicy:
    """Conservative numerical checks for a diagnostic solver execution."""

    maximum_absolute_runoff_continuity_error_percent: float = 1.0
    maximum_absolute_routing_continuity_error_percent: float = 1.0
    maximum_nonconverging_steps_percent: float = 0.0
    require_stable_links: bool = True
    reject_reported_errors: bool = True

    def __post_init__(self) -> None:
        numeric_values = (
            self.maximum_absolute_runoff_continuity_error_percent,
            self.maximum_absolute_routing_continuity_error_percent,
            self.maximum_nonconverging_steps_percent,
        )
        if any(
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            or value < 0.0
            for value in numeric_values
        ):
            raise ValueError("traditional_solver_quality_threshold_invalid")
        if (
            not isinstance(self.require_stable_links, bool)
            or not isinstance(self.reject_reported_errors, bool)
        ):
            raise ValueError("traditional_solver_quality_flag_invalid")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": TRADITIONAL_SOLVER_QUALITY_POLICY_SCHEMA,
            "maximum_absolute_runoff_continuity_error_percent": float(
                self.maximum_absolute_runoff_continuity_error_percent
            ),
            "maximum_absolute_routing_continuity_error_percent": float(
                self.maximum_absolute_routing_continuity_error_percent
            ),
            "maximum_nonconverging_steps_percent": float(
                self.maximum_nonconverging_steps_percent
            ),
            "require_stable_links": self.require_stable_links,
            "reject_reported_errors": self.reject_reported_errors,
        }


def build_traditional_solver_run_contract(
    request: TraditionalSolverRunRequest,
    *,
    executable_artifact: dict[str, object],
    input_artifact: dict[str, object],
    quality_policy: TraditionalSolverQualityPolicyProtocol,
    runtime_dependency_artifacts: Sequence[dict[str, object]] = (),
    model_input_dependency_artifacts: Sequence[dict[str, object]] = (),
) -> dict[str, object]:
    """Bind a validated request to immutable runtime and input artifacts."""

    if not isinstance(request, TraditionalSolverRunRequest):
        raise ValueError("traditional_solver_run_request_invalid")
    _validate_artifact(executable_artifact, "executable")
    _validate_artifact(input_artifact, "model_input")
    for dependency in runtime_dependency_artifacts:
        _validate_artifact(dependency, "runtime_dependency")
    for dependency in model_input_dependency_artifacts:
        _validate_artifact(dependency, "model_input_dependency")
    return {
        "schema": TRADITIONAL_SOLVER_RUN_REQUEST_SCHEMA,
        "run_id": request.run_id,
        "solver_id": request.solver_id,
        "expected_solver_version": request.expected_solver_version,
        "runtime_artifact": dict(executable_artifact),
        "runtime_dependency_artifacts": [
            dict(dependency) for dependency in runtime_dependency_artifacts
        ],
        "model_input_artifact": dict(input_artifact),
        "model_input_dependency_artifacts": [
            dict(dependency) for dependency in model_input_dependency_artifacts
        ],
        "input_governance": {
            "evidence_class": request.evidence_class,
            "calibration_status": request.calibration_status,
            "intended_use": request.intended_use,
        },
        "quality_policy": quality_policy.to_dict(),
        "claim_boundary": request.claim_boundary(),
    }


def artifact_descriptor(path: Path, *, sha256: str, path_label: str) -> dict[str, object]:
    """Build a canonical descriptor after the caller has hashed a local file."""

    descriptor = {
        "path": path_label,
        "sha256": sha256,
        "size_bytes": path.stat().st_size,
    }
    _validate_artifact(descriptor, "artifact")
    return descriptor


def _validate_artifact(value: dict[str, object], label: str) -> None:
    path = value.get("path")
    sha256 = value.get("sha256")
    size_bytes = value.get("size_bytes")
    if (
        not isinstance(path, str)
        or not path
        or not isinstance(sha256, str)
        or re.fullmatch(r"[0-9a-f]{64}", sha256) is None
        or not isinstance(size_bytes, int)
        or isinstance(size_bytes, bool)
        or size_bytes <= 0
    ):
        raise ValueError(f"traditional_solver_{label}_artifact_invalid")
