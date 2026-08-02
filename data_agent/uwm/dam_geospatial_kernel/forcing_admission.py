"""Non-compensatory evidence admission for GWM forcing features."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Mapping, Sequence


GWM_FORCING_ADMISSION_SCHEMA = (
    "gwm.geospatial_kernel.forcing_admission_certificate.v1"
)
GWM_FORCING_ADMISSION_GATES = (
    "source_identity_and_hashes",
    "feature_semantics",
    "temporal_resolution_and_coverage",
    "action_outcome_independence",
    "input_time_availability",
    "spatial_role_and_topology",
    "license_and_access",
    "normalization_and_split",
)


class ForcingGateStatus(StrEnum):
    PASS = "pass"
    FAIL = "fail"
    INDETERMINATE = "indeterminate"


@dataclass(frozen=True)
class GWMForcingAdmissionCertificate:
    schema: str
    source_id: str
    feature_names: tuple[str, ...]
    gate_statuses: dict[str, ForcingGateStatus]
    certificate_status: ForcingGateStatus
    first_nonpass_gate: str | None
    model_input_admitted: bool

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "source_id": self.source_id,
            "feature_names": list(self.feature_names),
            "gate_statuses": {
                gate: status.value for gate, status in self.gate_statuses.items()
            },
            "certificate_status": self.certificate_status.value,
            "first_nonpass_gate": self.first_nonpass_gate,
            "model_input_admitted": self.model_input_admitted,
            "aggregation": "non_compensatory_all_gates_must_pass",
            "claim_boundary": {
                "causal_effect_identified": False,
                "general_gwm_validated": False,
            },
        }


def evaluate_gwm_forcing_admission(
    *,
    source_id: str,
    feature_names: Sequence[str],
    checks: Mapping[
        str, bool | None | ForcingGateStatus | str
    ],
) -> GWMForcingAdmissionCertificate:
    """Evaluate forcing evidence without averaging failed gates."""

    normalized_source = str(source_id).strip()
    normalized_features = tuple(str(value) for value in feature_names)
    if not normalized_source:
        raise ValueError("forcing_admission_source_id_required")
    if not normalized_features or len(set(normalized_features)) != len(
        normalized_features
    ):
        raise ValueError("forcing_admission_feature_names_must_be_unique")
    extras = sorted(set(checks) - set(GWM_FORCING_ADMISSION_GATES))
    if extras:
        raise ValueError("unknown_forcing_admission_gates:" + ",".join(extras))

    gate_statuses = {
        gate: _normalize_status(checks.get(gate))
        for gate in GWM_FORCING_ADMISSION_GATES
    }
    if any(status is ForcingGateStatus.FAIL for status in gate_statuses.values()):
        certificate_status = ForcingGateStatus.FAIL
    elif any(
        status is ForcingGateStatus.INDETERMINATE
        for status in gate_statuses.values()
    ):
        certificate_status = ForcingGateStatus.INDETERMINATE
    else:
        certificate_status = ForcingGateStatus.PASS
    first_nonpass = next(
        (
            gate
            for gate in GWM_FORCING_ADMISSION_GATES
            if gate_statuses[gate] is not ForcingGateStatus.PASS
        ),
        None,
    )
    return GWMForcingAdmissionCertificate(
        schema=GWM_FORCING_ADMISSION_SCHEMA,
        source_id=normalized_source,
        feature_names=normalized_features,
        gate_statuses=gate_statuses,
        certificate_status=certificate_status,
        first_nonpass_gate=first_nonpass,
        model_input_admitted=certificate_status is ForcingGateStatus.PASS,
    )


def verify_gwm_forcing_admission_certificate(
    certificate: GWMForcingAdmissionCertificate,
) -> None:
    """Reject manually constructed certificates with inconsistent status."""

    if certificate.schema != GWM_FORCING_ADMISSION_SCHEMA:
        raise ValueError("forcing_admission_certificate_schema_mismatch")
    if set(certificate.gate_statuses) != set(GWM_FORCING_ADMISSION_GATES):
        raise ValueError("forcing_admission_certificate_gate_set_mismatch")
    recomputed = evaluate_gwm_forcing_admission(
        source_id=certificate.source_id,
        feature_names=certificate.feature_names,
        checks=certificate.gate_statuses,
    )
    if certificate != recomputed:
        raise ValueError("forcing_admission_certificate_inconsistent")


def _normalize_status(
    value: bool | None | ForcingGateStatus | str,
) -> ForcingGateStatus:
    if value is True:
        return ForcingGateStatus.PASS
    if value is False:
        return ForcingGateStatus.FAIL
    if value is None:
        return ForcingGateStatus.INDETERMINATE
    try:
        return ForcingGateStatus(value)
    except ValueError as exc:
        raise ValueError(f"invalid_forcing_admission_status:{value}") from exc
