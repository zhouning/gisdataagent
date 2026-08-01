"""Analytic response-family gates for candidate transport operators.

The references are linearized limiting equations, not river predictions.  A
candidate implementation must first reproduce these identities before it can
be compared on public development or frozen holdout data.
"""

from __future__ import annotations

from dataclasses import dataclass
import math

import numpy as np


ANALYTIC_TRANSPORT_FAMILY_CASE_SCHEMA = (
    "gwm.geospatial_kernel.analytic_transport_family_case.v1"
)
TRANSPORT_FAMILY_PROFILE_GATE_SCHEMA = (
    "gwm.geospatial_kernel.transport_family_profile_gate.v1"
)
_FAMILIES = {"kinematic", "diffusive", "local_inertial"}


@dataclass(frozen=True)
class GaussianPulseComponent:
    volume_m3: float
    center_m: float
    variance_m2: float

    def __post_init__(self) -> None:
        values = (self.volume_m3, self.center_m, self.variance_m2)
        if not all(math.isfinite(float(value)) for value in values):
            raise ValueError("gaussian_pulse_component_finite_values_required")
        if self.volume_m3 <= 0.0 or self.variance_m2 <= 0.0:
            raise ValueError("gaussian_pulse_component_positive_scale_required")

    def profile_incremental_area_m2(self, coordinates_m: np.ndarray) -> np.ndarray:
        coordinates = np.asarray(coordinates_m, dtype=float)
        scale = self.volume_m3 / math.sqrt(2.0 * math.pi * self.variance_m2)
        return scale * np.exp(
            -0.5 * ((coordinates - self.center_m) ** 2) / self.variance_m2
        )

    def as_dict(self) -> dict[str, float]:
        return {
            "volume_m3": float(self.volume_m3),
            "center_m": float(self.center_m),
            "variance_m2": float(self.variance_m2),
        }


@dataclass(frozen=True)
class AnalyticTransportFamilyCase:
    case_id: str
    family: str
    initial_volume_m3: float
    initial_center_m: float
    initial_standard_deviation_m: float
    elapsed_seconds: float
    advection_celerity_mps: float | None = None
    diffusion_coefficient_m2s: float | None = None
    gravity_wave_celerity_mps: float | None = None

    def __post_init__(self) -> None:
        if not self.case_id.strip() or self.family not in _FAMILIES:
            raise ValueError("analytic_transport_family_case_identity_invalid")
        scales = (
            self.initial_volume_m3,
            self.initial_center_m,
            self.initial_standard_deviation_m,
            self.elapsed_seconds,
        )
        if not all(math.isfinite(float(value)) for value in scales):
            raise ValueError("analytic_transport_family_case_finite_values_required")
        if (
            self.initial_volume_m3 <= 0.0
            or self.initial_standard_deviation_m <= 0.0
            or self.elapsed_seconds < 0.0
        ):
            raise ValueError("analytic_transport_family_case_scale_invalid")
        if self.family in {"kinematic", "diffusive"}:
            if (
                self.advection_celerity_mps is None
                or not math.isfinite(float(self.advection_celerity_mps))
                or self.gravity_wave_celerity_mps is not None
            ):
                raise ValueError("advective_family_celerity_contract_invalid")
        if self.family == "kinematic":
            if self.diffusion_coefficient_m2s not in (None, 0.0):
                raise ValueError("kinematic_family_diffusion_must_be_zero")
        elif self.family == "diffusive":
            if (
                self.diffusion_coefficient_m2s is None
                or not math.isfinite(float(self.diffusion_coefficient_m2s))
                or self.diffusion_coefficient_m2s < 0.0
            ):
                raise ValueError("diffusive_family_coefficient_invalid")
        else:
            if (
                self.advection_celerity_mps is not None
                or self.diffusion_coefficient_m2s is not None
                or self.gravity_wave_celerity_mps is None
                or not math.isfinite(float(self.gravity_wave_celerity_mps))
                or self.gravity_wave_celerity_mps <= 0.0
            ):
                raise ValueError("local_inertial_family_celerity_contract_invalid")

    @property
    def governing_equation(self) -> str:
        if self.family == "kinematic":
            return "da/dt + c_k da/dx = 0"
        if self.family == "diffusive":
            return "da/dt + c_k da/dx = D d2a/dx2"
        return "d2a/dt2 = c_g^2 d2a/dx2; initial da/dt = 0"

    @property
    def components(self) -> tuple[GaussianPulseComponent, ...]:
        initial_variance = self.initial_standard_deviation_m**2
        if self.family == "kinematic":
            return (
                GaussianPulseComponent(
                    volume_m3=self.initial_volume_m3,
                    center_m=(
                        self.initial_center_m
                        + float(self.advection_celerity_mps) * self.elapsed_seconds
                    ),
                    variance_m2=initial_variance,
                ),
            )
        if self.family == "diffusive":
            return (
                GaussianPulseComponent(
                    volume_m3=self.initial_volume_m3,
                    center_m=(
                        self.initial_center_m
                        + float(self.advection_celerity_mps) * self.elapsed_seconds
                    ),
                    variance_m2=(
                        initial_variance
                        + 2.0
                        * float(self.diffusion_coefficient_m2s)
                        * self.elapsed_seconds
                    ),
                ),
            )
        displacement = float(self.gravity_wave_celerity_mps) * self.elapsed_seconds
        return (
            GaussianPulseComponent(
                volume_m3=0.5 * self.initial_volume_m3,
                center_m=self.initial_center_m - displacement,
                variance_m2=initial_variance,
            ),
            GaussianPulseComponent(
                volume_m3=0.5 * self.initial_volume_m3,
                center_m=self.initial_center_m + displacement,
                variance_m2=initial_variance,
            ),
        )

    @property
    def expected_centroid_m(self) -> float:
        return float(
            sum(value.volume_m3 * value.center_m for value in self.components)
            / self.initial_volume_m3
        )

    @property
    def expected_variance_m2(self) -> float:
        center = self.expected_centroid_m
        return float(
            sum(
                value.volume_m3
                * (value.variance_m2 + (value.center_m - center) ** 2)
                for value in self.components
            )
            / self.initial_volume_m3
        )

    def profile_incremental_area_m2(self, coordinates_m: np.ndarray) -> np.ndarray:
        coordinates = np.asarray(coordinates_m, dtype=float)
        if coordinates.ndim != 1 or coordinates.size < 2 or not np.isfinite(coordinates).all():
            raise ValueError("analytic_transport_family_coordinate_axis_invalid")
        return np.sum(
            [
                component.profile_incremental_area_m2(coordinates)
                for component in self.components
            ],
            axis=0,
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": ANALYTIC_TRANSPORT_FAMILY_CASE_SCHEMA,
            "case_id": self.case_id,
            "family": self.family,
            "governing_equation": self.governing_equation,
            "state_quantity": "incremental_cross_section_area",
            "integrated_quantity": "incremental_volume",
            "initial_volume_m3": self.initial_volume_m3,
            "initial_center_m": self.initial_center_m,
            "initial_standard_deviation_m": self.initial_standard_deviation_m,
            "elapsed_seconds": self.elapsed_seconds,
            "advection_celerity_mps": self.advection_celerity_mps,
            "diffusion_coefficient_m2s": self.diffusion_coefficient_m2s,
            "gravity_wave_celerity_mps": self.gravity_wave_celerity_mps,
            "analytic_components": [value.as_dict() for value in self.components],
            "expected_volume_m3": self.initial_volume_m3,
            "expected_centroid_m": self.expected_centroid_m,
            "expected_variance_m2": self.expected_variance_m2,
            "outcome_calibrated": False,
            "operator_admitted": False,
        }


@dataclass(frozen=True)
class TransportFamilyProfileGate:
    case_id: str
    family: str
    finite: bool
    nonnegative: bool
    integrated_volume_m3: float | None
    centroid_m: float | None
    variance_m2: float | None
    relative_volume_error: float | None
    absolute_centroid_error_m: float | None
    relative_variance_error: float | None
    volume_gate_passed: bool
    centroid_gate_passed: bool
    variance_gate_passed: bool

    @property
    def all_gates_passed(self) -> bool:
        return all(
            (
                self.finite,
                self.nonnegative,
                self.volume_gate_passed,
                self.centroid_gate_passed,
                self.variance_gate_passed,
            )
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": TRANSPORT_FAMILY_PROFILE_GATE_SCHEMA,
            "case_id": self.case_id,
            "family": self.family,
            "finite": self.finite,
            "nonnegative": self.nonnegative,
            "integrated_volume_m3": self.integrated_volume_m3,
            "centroid_m": self.centroid_m,
            "variance_m2": self.variance_m2,
            "relative_volume_error": self.relative_volume_error,
            "absolute_centroid_error_m": self.absolute_centroid_error_m,
            "relative_variance_error": self.relative_variance_error,
            "volume_gate_passed": self.volume_gate_passed,
            "centroid_gate_passed": self.centroid_gate_passed,
            "variance_gate_passed": self.variance_gate_passed,
            "all_gates_passed": self.all_gates_passed,
        }


def evaluate_transport_family_profile(
    case: AnalyticTransportFamilyCase,
    *,
    coordinates_m: np.ndarray,
    profile_incremental_area_m2: np.ndarray,
    maximum_relative_volume_error: float,
    maximum_absolute_centroid_error_m: float,
    maximum_relative_variance_error: float,
    negative_area_tolerance_m2: float = 0.0,
) -> TransportFamilyProfileGate:
    coordinates = np.asarray(coordinates_m, dtype=float)
    values = np.asarray(profile_incremental_area_m2, dtype=float)
    tolerances = np.asarray(
        [
            maximum_relative_volume_error,
            maximum_absolute_centroid_error_m,
            maximum_relative_variance_error,
            negative_area_tolerance_m2,
        ],
        dtype=float,
    )
    if (
        coordinates.ndim != 1
        or coordinates.size < 2
        or values.shape != coordinates.shape
        or not np.isfinite(coordinates).all()
        or not np.all(np.diff(coordinates) > 0.0)
        or not np.isfinite(tolerances).all()
        or (tolerances < 0.0).any()
    ):
        raise ValueError("transport_family_profile_gate_input_invalid")
    finite = bool(np.isfinite(values).all())
    nonnegative = finite and bool(values.min() >= -negative_area_tolerance_m2)
    if not finite:
        return TransportFamilyProfileGate(
            case_id=case.case_id,
            family=case.family,
            finite=False,
            nonnegative=False,
            integrated_volume_m3=None,
            centroid_m=None,
            variance_m2=None,
            relative_volume_error=None,
            absolute_centroid_error_m=None,
            relative_variance_error=None,
            volume_gate_passed=False,
            centroid_gate_passed=False,
            variance_gate_passed=False,
        )
    volume = float(np.trapezoid(values, coordinates))
    if volume <= 0.0:
        centroid = None
        variance = None
        centroid_error = None
        variance_error = None
    else:
        centroid = float(np.trapezoid(coordinates * values, coordinates) / volume)
        variance = float(
            np.trapezoid(((coordinates - centroid) ** 2) * values, coordinates)
            / volume
        )
        centroid_error = abs(centroid - case.expected_centroid_m)
        variance_error = abs(variance - case.expected_variance_m2) / (
            case.expected_variance_m2
        )
    volume_error = abs(volume - case.initial_volume_m3) / case.initial_volume_m3
    return TransportFamilyProfileGate(
        case_id=case.case_id,
        family=case.family,
        finite=finite,
        nonnegative=nonnegative,
        integrated_volume_m3=volume,
        centroid_m=centroid,
        variance_m2=variance,
        relative_volume_error=volume_error,
        absolute_centroid_error_m=centroid_error,
        relative_variance_error=variance_error,
        volume_gate_passed=volume_error <= maximum_relative_volume_error,
        centroid_gate_passed=(
            centroid_error is not None
            and centroid_error <= maximum_absolute_centroid_error_m
        ),
        variance_gate_passed=(
            variance_error is not None
            and variance_error <= maximum_relative_variance_error
        ),
    )
