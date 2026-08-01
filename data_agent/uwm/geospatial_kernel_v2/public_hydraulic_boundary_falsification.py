"""Stage 37 public attribution of the frozen Stage 36 negative result."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from data_agent.uwm.geospatial_kernel_v2 import (
    hydraulic_boundary_falsification as falsification,
)
from data_agent.uwm.geospatial_kernel_v2 import (
    public_hydraulic_boundary_response as stage36,
)

REPO_ROOT = Path(__file__).resolve().parents[3]
STAGE37_ROOT = (
    "data/geotransport_v0_1/"
    "stage37_center_hill_hydraulic_boundary_falsification"
)
DEFAULT_STAGE36_ROOT = REPO_ROOT / stage36.STAGE36_ROOT
STAGE36_LEDGER_PATH = (
    f"{stage36.STAGE36_ROOT}/"
    "hydraulic_boundary_response_evidence_ledger.json"
)
STAGE36_GATES_PATH = (
    "benchmarks/geotransport_v0_1/"
    "stage36_hydraulic_boundary_response_gates.json"
)
SCHEMA = "gwm.geotransport.public_hydraulic_boundary_falsification.v1"
STATUS = "blind_hydraulic_boundary_departure_support_rejected"
SUPPORT_FAILURE = "observation_support_insufficient"
THRESHOLD_FAILURE = "frozen_persistent_departure_not_detected"


@dataclass(frozen=True)
class PublicHydraulicBoundaryFailureAttribution:
    event_id: str
    selection_rank: int
    source_direction: str
    failure_class: str
    raw_sample_count: int
    grid_real_sample_count: int
    grid_missing_sample_count: int
    baseline_real_sample_count: int
    frozen_target_functional_assessable: bool
    attribution: (
        falsification.PersistentDepartureFalsificationAttribution | None
    )

    def __post_init__(self) -> None:
        if (
            self.event_id not in stage36.EXPECTED_EVENT_IDS
            or self.selection_rank not in range(1, 5)
            or self.source_direction not in {"rise", "fall"}
            or self.failure_class not in {SUPPORT_FAILURE, THRESHOLD_FAILURE}
            or (
                self.failure_class == SUPPORT_FAILURE
                and (
                    self.frozen_target_functional_assessable
                    or self.attribution is not None
                )
            )
            or (
                self.failure_class == THRESHOLD_FAILURE
                and (
                    not self.frozen_target_functional_assessable
                    or self.attribution is None
                    or self.attribution.frozen_gate_detected
                )
            )
        ):
            raise ValueError("public_hydraulic_boundary_failure_event_invalid")

    @property
    def direction_concordant(self) -> bool | None:
        if self.attribution is None:
            return None
        expected = "increase" if self.source_direction == "rise" else "decrease"
        return self.attribution.strongest_persistent_direction == expected

    @property
    def single_sample_crosses_frozen_threshold(self) -> bool | None:
        if self.attribution is None:
            return None
        return self.attribution.maximum_single_sample_threshold_ratio >= 1.0

    @property
    def persistence_only_failure(self) -> bool:
        return (
            self.single_sample_crosses_frozen_threshold is True
            and self.attribution is not None
            and not self.attribution.frozen_gate_detected
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "event_id": self.event_id,
            "selection_rank": self.selection_rank,
            "source_direction": self.source_direction,
            "failure_class": self.failure_class,
            "raw_sample_count": self.raw_sample_count,
            "expected_half_hour_grid_sample_count": 97,
            "grid_real_sample_count": self.grid_real_sample_count,
            "grid_missing_sample_count": self.grid_missing_sample_count,
            "baseline_real_sample_count": self.baseline_real_sample_count,
            "frozen_target_functional_assessable": (
                self.frozen_target_functional_assessable
            ),
            "frozen_gate_detected": (
                False
                if self.attribution is None
                else self.attribution.frozen_gate_detected
            ),
            "strongest_persistent_direction_concordant_with_source": (
                self.direction_concordant
            ),
            "single_sample_crosses_frozen_threshold": (
                self.single_sample_crosses_frozen_threshold
            ),
            "persistence_only_failure": self.persistence_only_failure,
            "attribution": (
                None if self.attribution is None else self.attribution.as_dict()
            ),
            "missing_values_filled": False,
            "alternative_detector_admitted": False,
            "causal_response_admitted": False,
            "physical_response_time_admitted": False,
            "runtime_operator_admitted": False,
        }


@dataclass(frozen=True)
class PublicHydraulicBoundaryFalsificationLedger:
    attribution_operator_artifact: dict[str, object]
    stage36_ledger_artifact: dict[str, object]
    stage36_gates_artifact: dict[str, object]
    events: tuple[PublicHydraulicBoundaryFailureAttribution, ...]
    provenance_id: str

    def __post_init__(self) -> None:
        if (
            tuple(value.event_id for value in self.events)
            != stage36.EXPECTED_EVENT_IDS
            or tuple(value.selection_rank for value in self.events)
            != (1, 2, 3, 4)
            or self.measurement_support_failure_count != 1
            or self.frozen_threshold_failure_count != 3
        ):
            raise ValueError("public_hydraulic_boundary_falsification_invalid")

    @property
    def measurement_support_failure_count(self) -> int:
        return sum(value.failure_class == SUPPORT_FAILURE for value in self.events)

    @property
    def frozen_threshold_failure_count(self) -> int:
        return sum(value.failure_class == THRESHOLD_FAILURE for value in self.events)

    @property
    def any_assessable_event_detected(self) -> bool:
        return any(
            value.attribution is not None
            and value.attribution.frozen_gate_detected
            for value in self.events
        )

    @property
    def direction_concordant_event_count(self) -> int:
        return sum(value.direction_concordant is True for value in self.events)

    @property
    def single_sample_threshold_crossing_count(self) -> int:
        return sum(
            value.single_sample_crosses_frozen_threshold is True
            for value in self.events
        )

    @property
    def persistence_only_failure_count(self) -> int:
        return sum(value.persistence_only_failure for value in self.events)

    def require_alternative_detector(self) -> None:
        raise ValueError(
            "public_falsification_does_not_admit_alternative_detector"
        )

    def require_causal_response(self) -> None:
        raise ValueError("public_falsification_does_not_admit_causal_response")

    def require_physical_response_time(self) -> None:
        raise ValueError("public_falsification_does_not_admit_physical_time")

    def promote_to_runtime_operator(self) -> None:
        raise ValueError("public_falsification_runtime_operator_unadmitted")

    def as_dict(self) -> dict[str, object]:
        assessable = tuple(
            value.attribution
            for value in self.events
            if value.attribution is not None
        )
        return {
            "schema": SCHEMA,
            "attribution_operator_artifact": (
                self.attribution_operator_artifact
            ),
            "stage36_ledger_artifact": self.stage36_ledger_artifact,
            "stage36_gates_artifact": self.stage36_gates_artifact,
            "events": [value.as_dict() for value in self.events],
            "provenance_id": self.provenance_id,
            "diagnostic_summary": {
                "event_count": len(self.events),
                "measurement_support_failure_count": (
                    self.measurement_support_failure_count
                ),
                "frozen_threshold_failure_count": (
                    self.frozen_threshold_failure_count
                ),
                "any_assessable_event_detected": (
                    self.any_assessable_event_detected
                ),
                "direction_concordant_event_count": (
                    self.direction_concordant_event_count
                ),
                "single_sample_threshold_crossing_count": (
                    self.single_sample_threshold_crossing_count
                ),
                "persistence_only_failure_count": (
                    self.persistence_only_failure_count
                ),
                "per_event_failure_class": [
                    value.failure_class for value in self.events
                ],
                "assessable_dominant_threshold_components": [
                    value.dominant_threshold_component for value in assessable
                ],
                "assessable_strongest_persistent_threshold_ratios": [
                    value.strongest_persistent_threshold_ratio
                    for value in assessable
                ],
                "assessable_maximum_single_sample_threshold_ratios": [
                    value.maximum_single_sample_threshold_ratio
                    for value in assessable
                ],
            },
            "claim_boundary": {
                "post_outcome_diagnostic_only": True,
                "stage36_event_set_and_target_gate_unchanged": True,
                "missing_values_filled": False,
                "alternative_threshold_or_detector_admitted": False,
                "causal_response_admitted": False,
                "physical_response_time_admitted": False,
                "runtime_operator_admitted": False,
            },
            "decision": {
                "stage36_negative_result_preserved": True,
                "failure_attribution_admitted": True,
                "measurement_support_failure_count": (
                    self.measurement_support_failure_count
                ),
                "frozen_threshold_failure_count": (
                    self.frozen_threshold_failure_count
                ),
                "any_assessable_event_detected": (
                    self.any_assessable_event_detected
                ),
                "directional_response_support_admitted": False,
                "alternative_detector_admitted": False,
                "causal_response_admitted": False,
                "physical_response_time_admitted": False,
                "runtime_operator_admitted": False,
            },
        }


def compile_public_hydraulic_boundary_falsification(
    stage36_root: Path = DEFAULT_STAGE36_ROOT,
    *,
    repo_root: Path = REPO_ROOT,
) -> PublicHydraulicBoundaryFalsificationLedger:
    root = Path(repo_root).resolve()
    stage36_compiled = stage36.compile_public_hydraulic_boundary_response(
        source_root=stage36_root,
        repo_root=root,
    )
    stage36_ledger_path = root / STAGE36_LEDGER_PATH
    stage36_ledger_file = _read_json(stage36_ledger_path)
    if stage36_compiled.as_dict() != stage36_ledger_file:
        raise ValueError("public_falsification_stage36_ledger_not_reproducible")
    stage36_gates_path = root / STAGE36_GATES_PATH
    stage36_gates = _read_json(stage36_gates_path)
    if (
        stage36_gates.get("all_gates_passed") is not True
        or stage36_gates.get("status") != STATUS
        or sum(bool(value) for value in stage36_gates.get("gates", {}).values())
        != 32
    ):
        raise ValueError("public_falsification_stage36_gates_invalid")

    events = tuple(_compile_event(value) for value in stage36_compiled.events)
    operator_path = (
        root
        / "data_agent/uwm/geospatial_kernel_v2/"
        "hydraulic_boundary_falsification.py"
    )
    artifacts = (
        _artifact(operator_path, root),
        _artifact(stage36_ledger_path, root),
        _artifact(stage36_gates_path, root),
    )
    digest = hashlib.sha256(
        "|".join(str(value["sha256"]) for value in artifacts).encode("ascii")
    ).hexdigest()
    return PublicHydraulicBoundaryFalsificationLedger(
        artifacts[0],
        artifacts[1],
        artifacts[2],
        events,
        f"center-hill-hydraulic-boundary-falsification:{digest}",
    )


def _compile_event(
    value: stage36.PublicHydraulicBoundaryResponseEvent,
) -> PublicHydraulicBoundaryFailureAttribution:
    if not value.target_functional_assessable:
        return PublicHydraulicBoundaryFailureAttribution(
            value.event_id,
            value.selection_rank,
            str(value.source_perturbation["direction"]),
            SUPPORT_FAILURE,
            value.raw_sample_count,
            value.grid_real_sample_count,
            value.grid_missing_sample_count,
            value.baseline_real_sample_count,
            False,
            None,
        )
    attribution = falsification.compile_persistent_departure_falsification(
        value.discharge_grid_m3s
    )
    return PublicHydraulicBoundaryFailureAttribution(
        value.event_id,
        value.selection_rank,
        str(value.source_perturbation["direction"]),
        THRESHOLD_FAILURE,
        value.raw_sample_count,
        value.grid_real_sample_count,
        value.grid_missing_sample_count,
        value.baseline_real_sample_count,
        True,
        attribution,
    )


def _artifact(path: Path, root: Path) -> dict[str, object]:
    resolved = path.resolve()
    try:
        relative = resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError("public_falsification_artifact_outside_repository") from exc
    body = resolved.read_bytes()
    return {
        "path": str(relative),
        "sha256": hashlib.sha256(body).hexdigest(),
        "size_bytes": len(body),
    }


def _read_json(path: Path) -> dict[str, object]:
    value = json.loads(path.read_bytes())
    if not isinstance(value, dict):
        raise ValueError("public_falsification_json_object_required")
    return value
