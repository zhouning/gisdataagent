"""Confirmatory cohort assessment for component-total empirical lag support."""

from __future__ import annotations

from dataclasses import dataclass

from data_agent.uwm.geospatial_kernel_v2 import empirical_lag_support

SCHEMA = "gwm.geospatial.component_lag_replication_assessment.v1"
EXPECTED_STRATA = (
    "high_increase",
    "high_decrease",
    "low_increase",
    "low_decrease",
)
REQUIRED_LAG_BY_FLOW_CLASS = {"high": 5, "low": 6}


@dataclass(frozen=True)
class ComponentLagReplicationEventResult:
    event_id: str
    selection_rank: int
    selection_stratum: str
    lag_support: empirical_lag_support.EmpiricalLagSupport

    def __post_init__(self) -> None:
        if (
            not self.event_id
            or self.selection_rank not in range(1, 5)
            or self.selection_stratum not in EXPECTED_STRATA
        ):
            raise ValueError("component_lag_replication_event_result_invalid")

    @property
    def flow_class(self) -> str:
        return self.selection_stratum.split("_", maxsplit=1)[0]

    @property
    def direction(self) -> str:
        return self.selection_stratum.split("_", maxsplit=1)[1]

    @property
    def required_lag_hours(self) -> int:
        return REQUIRED_LAG_BY_FLOW_CLASS[self.flow_class]

    @property
    def replication_passed(self) -> bool:
        return (
            self.lag_support.response_detectable
            and self.required_lag_hours in self.lag_support.supported_lags_hours
        )

    @property
    def rejection_reasons(self) -> tuple[str, ...]:
        reasons = []
        if not self.lag_support.response_detectable:
            reasons.append("event_response_not_detectable")
        if self.required_lag_hours not in self.lag_support.supported_lags_hours:
            reasons.append(
                f"required_{self.flow_class}_flow_lag_{self.required_lag_hours}h_not_supported"
            )
        return tuple(reasons)

    def as_dict(self) -> dict[str, object]:
        return {
            "event_id": self.event_id,
            "selection_rank": self.selection_rank,
            "selection_stratum": self.selection_stratum,
            "flow_class": self.flow_class,
            "direction": self.direction,
            "required_lag_hours": self.required_lag_hours,
            "response_detectable": self.lag_support.response_detectable,
            "supported_lags_hours": list(self.lag_support.supported_lags_hours),
            "replication_passed": self.replication_passed,
            "rejection_reasons": list(self.rejection_reasons),
            "lag_support": self.lag_support.as_dict(),
        }


@dataclass(frozen=True)
class ComponentLagReplicationAssessment:
    events: tuple[ComponentLagReplicationEventResult, ...]

    def __post_init__(self) -> None:
        if (
            len(self.events) != 4
            or tuple(value.selection_rank for value in self.events) != (1, 2, 3, 4)
            or tuple(value.selection_stratum for value in self.events) != EXPECTED_STRATA
            or len({value.event_id for value in self.events}) != 4
        ):
            raise ValueError("component_lag_replication_four_frozen_strata_required")

    @property
    def high_flow_bidirectional_replication_passed(self) -> bool:
        return all(value.replication_passed for value in self.events if value.flow_class == "high")

    @property
    def low_flow_bidirectional_replication_passed(self) -> bool:
        return all(value.replication_passed for value in self.events if value.flow_class == "low")

    @property
    def cohort_replication_admitted(self) -> bool:
        return (
            self.high_flow_bidirectional_replication_passed
            and self.low_flow_bidirectional_replication_passed
            and all(value.replication_passed for value in self.events)
        )

    @property
    def failed_strata(self) -> tuple[str, ...]:
        return tuple(
            value.selection_stratum for value in self.events if not value.replication_passed
        )

    def require_cohort_replication(self) -> None:
        if not self.cohort_replication_admitted:
            raise ValueError("component_lag_cohort_replication_not_admitted")

    def require_universal_lag(self) -> None:
        raise ValueError("component_lag_replication_is_not_universal_lag")

    def override_stage30_falsification(self) -> None:
        raise ValueError("component_lag_replication_cannot_override_stage30")

    def require_non_turbine_component_contrast(self) -> None:
        raise ValueError("component_lag_replication_non_turbine_contrast_unadmitted")

    def require_causal_or_physical_relation(self) -> None:
        raise ValueError("component_lag_replication_causal_physical_unadmitted")

    def promote_to_runtime_operator(self) -> None:
        raise ValueError("component_lag_replication_runtime_operator_unadmitted")

    def as_dict(self) -> dict[str, object]:
        return {
            "schema": SCHEMA,
            "role": "confirmatory_center_hill_component_total_cohort_assessment",
            "required_strata": list(EXPECTED_STRATA),
            "required_lag_by_flow_class_hours": REQUIRED_LAG_BY_FLOW_CLASS,
            "partial_direction_or_flow_class_pass_allowed": False,
            "events": [value.as_dict() for value in self.events],
            "decision": {
                "high_flow_bidirectional_replication_passed": (
                    self.high_flow_bidirectional_replication_passed
                ),
                "low_flow_bidirectional_replication_passed": (
                    self.low_flow_bidirectional_replication_passed
                ),
                "cohort_replication_admitted": (self.cohort_replication_admitted),
                "failed_strata": list(self.failed_strata),
                "universal_lag_admitted": False,
                "stage30_historical_falsification_overturned": False,
                "non_turbine_component_contrast_admitted": False,
                "causal_or_physical_relation_admitted": False,
                "runtime_operator_admitted": False,
            },
            "claim_boundary": {
                "admitted_scope_on_pass": (
                    "center_hill_component_total_flow_class_cohort_replication_only"
                ),
                "support_membership_not_exact_hour_equality": True,
                "all_four_frozen_strata_required": True,
                "event_reselection_allowed": False,
                "target_operator_retuning_allowed": False,
                "universal_lag_inference_allowed": False,
                "stage30_override_allowed": False,
                "causal_or_physical_promotion_allowed": False,
                "runtime_promotion_allowed": False,
            },
        }


def compile_component_lag_replication_assessment(
    events: tuple[ComponentLagReplicationEventResult, ...],
) -> ComponentLagReplicationAssessment:
    return ComponentLagReplicationAssessment(events)
