"""Non-compensatory evidence decisions for intervention-conditioned UWM claims."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any, Mapping

import yaml


SPEC_PATH = Path(__file__).with_name("intervention_evidence_certificate_spec.yaml")
GATE_IDS = ("G0", "G1", "G2", "G3", "G4", "G5", "G6")


class GateStatus(StrEnum):
    PASS = "pass"
    FAIL = "fail"
    INDETERMINATE = "indeterminate"


class ClaimTier(StrEnum):
    NO_INTERVENTION_CLAIM = "no_intervention_claim"
    TOKEN_RESPONSIVENESS = "token_responsiveness"
    SEMANTIC_INCREMENTAL_PREDICTION = "semantic_incremental_prediction"
    OUTCOME_SEALED_SEMANTIC_TRANSFER = "outcome_sealed_semantic_transfer"
    CONTROLLED_INTERVENTION_LAW_RECOVERY = (
        "controlled_intervention_law_recovery"
    )


class ControlledTruthStatus(StrEnum):
    UNAVAILABLE = "unavailable"
    PASS = "pass"
    FAIL = "fail"
    INDETERMINATE = "indeterminate"


@dataclass(frozen=True)
class CertificateEvaluation:
    gate_statuses: dict[str, GateStatus]
    certificate_status: GateStatus
    first_nonpass_gate: str | None
    highest_claim_tier: ClaimTier
    controlled_truth_status: ControlledTruthStatus

    def as_dict(self) -> dict[str, Any]:
        return {
            "gate_statuses": {
                gate_id: status.value
                for gate_id, status in self.gate_statuses.items()
            },
            "certificate_status": self.certificate_status.value,
            "first_nonpass_gate": self.first_nonpass_gate,
            "highest_claim_tier": self.highest_claim_tier.value,
            "controlled_truth_status": self.controlled_truth_status.value,
        }


def load_spec(path: Path = SPEC_PATH) -> dict[str, Any]:
    """Load and structurally validate the human-readable IEC specification."""

    spec = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(spec, dict):
        raise ValueError("IEC specification must be a mapping")
    gate_ids = tuple(gate.get("id") for gate in spec.get("gates", []))
    if gate_ids != GATE_IDS:
        raise ValueError(f"IEC gates must be ordered exactly as {GATE_IDS!r}")
    if tuple(spec.get("status_values", [])) != tuple(status.value for status in GateStatus):
        raise ValueError("IEC status_values do not match the executable contract")
    return spec


def _normalize_gates(
    values: Mapping[str, GateStatus | str],
) -> dict[str, GateStatus]:
    extras = set(values) - set(GATE_IDS)
    if extras:
        raise ValueError(f"unknown IEC gates: {sorted(extras)!r}")
    normalized: dict[str, GateStatus] = {}
    for gate_id in GATE_IDS:
        raw = values.get(gate_id, GateStatus.INDETERMINATE)
        try:
            normalized[gate_id] = GateStatus(raw)
        except ValueError as exc:
            raise ValueError(f"invalid status for {gate_id}: {raw!r}") from exc
    return normalized


def _certificate_status(gates: Mapping[str, GateStatus]) -> GateStatus:
    if any(status is GateStatus.FAIL for status in gates.values()):
        return GateStatus.FAIL
    if any(status is GateStatus.INDETERMINATE for status in gates.values()):
        return GateStatus.INDETERMINATE
    return GateStatus.PASS


def _controlled_truth_status(
    truth: Mapping[str, bool | None] | None,
) -> ControlledTruthStatus:
    if truth is None or truth.get("reference_available") is False:
        return ControlledTruthStatus.UNAVAILABLE
    if truth.get("reference_available") is not True:
        return ControlledTruthStatus.INDETERMINATE

    checks = (truth.get("response_surface_pass"), truth.get("jacobian_pass"))
    if any(value is False for value in checks):
        return ControlledTruthStatus.FAIL
    if any(value is not True for value in checks):
        return ControlledTruthStatus.INDETERMINATE
    return ControlledTruthStatus.PASS


def _prefix_passes(gates: Mapping[str, GateStatus], final_gate: str) -> bool:
    final_index = GATE_IDS.index(final_gate)
    return all(gates[gate_id] is GateStatus.PASS for gate_id in GATE_IDS[: final_index + 1])


def evaluate_certificate(
    gate_statuses: Mapping[str, GateStatus | str],
    *,
    token_responsive: bool | None,
    controlled_truth: Mapping[str, bool | None] | None = None,
) -> CertificateEvaluation:
    """Return the highest claim earned without averaging across failed gates.

    Missing gates are indeterminate. Controlled law recovery is intentionally
    unavailable unless a reference transition and both truth-recovery checks
    are explicitly present and passed.
    """

    gates = _normalize_gates(gate_statuses)
    overall = _certificate_status(gates)
    truth_status = _controlled_truth_status(controlled_truth)
    first_nonpass = next(
        (gate_id for gate_id in GATE_IDS if gates[gate_id] is not GateStatus.PASS),
        None,
    )

    if token_responsive is not True:
        tier = ClaimTier.NO_INTERVENTION_CLAIM
    elif _prefix_passes(gates, "G6"):
        if truth_status is ControlledTruthStatus.PASS:
            tier = ClaimTier.CONTROLLED_INTERVENTION_LAW_RECOVERY
        else:
            tier = ClaimTier.OUTCOME_SEALED_SEMANTIC_TRANSFER
    elif _prefix_passes(gates, "G5"):
        tier = ClaimTier.SEMANTIC_INCREMENTAL_PREDICTION
    else:
        tier = ClaimTier.TOKEN_RESPONSIVENESS

    return CertificateEvaluation(
        gate_statuses=gates,
        certificate_status=overall,
        first_nonpass_gate=first_nonpass,
        highest_claim_tier=tier,
        controlled_truth_status=truth_status,
    )
